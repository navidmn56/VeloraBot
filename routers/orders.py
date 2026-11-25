"""
routers/orders.py
-----------------
روتر سفارشات و فرآیند خرید:
- شروع خرید سرویس، تغییر حجم و روز (buy_service, vol_up/down, day_up/down)
- اعتبارسنجی وضعیت تسویه‌حساب (is_valid_checkout_state)
- شروع پرداخت کارت به کارت و ایجاد سفارش (pay_card)
- یادآوری ارسال رسید (send_receipt_reminder)
- لغو مستقیم سفارش توسط کاربر (cancel_order_direct)
- تمدید سرویس در پنل و دیتابیس (extend_service, extend_service_start)
- ساخت کلاینت در پنل (create_client_in_panel)
"""

import math
import re
import html
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple, Union

import aiohttp
from aiogram import Router, F, Bot, types
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CopyTextButton,
)
from aiogram.enums import ParseMode

from config import (
    SENAI_PANEL_URL,
    SENAI_PANEL_ENABLED,
    is_senai_panel_enabled,
    BANK_CARD_NUMBER,
    BANK_CARD_HOLDER,
    BANK_NAME,
    BANK_CARD_HOLDER_EN,
    BANK_NAME_EN,
    SUPPORT_USERNAME,
    ADMIN_ID,
)
from core.state_stores import (
    user_states,
    USER_INBOUND_SELECTION,
)
from database import (
    users,
    orders,
    READY_PACKAGES,
    configs_pool,
    update_order,
    BLACKLIST,
    save_all,
    now_tehran,
    now_tehran_iso,
    TEHRAN_TZ,
)
from user_manager import (
    get_user,
    get_user_safe,
    get_admin_id_int,
    update_user,
    COUPONS,
    save_coupons,
    save_coupon_to_user_db,
    load_coupon_from_user_db,
    is_coupon_valid_for_user,
    can_user_purchase,
    calculate_price,
    consume_coupon,
    debug_coupon_state,
    record_purchase,
)
from routers.force_join import check_membership
from routers.shop import (
    check_shop_status_and_notify,
    show_ready_categories,
    format_package_volume,
)
from routers.admin_test import save_user_inbound_selection
from services.panel_api import (
    xui_login,
    xui_get_csrf_token,
    xui_get_client_info,
    get_client_inbounds,
    xui_detach_inbounds,
    xui_attach_inbounds,
    xui_reset_client_traffic,
    xui_create_client_with_inbound,
    get_user_inbound,
)
from sms_payment_system import sms_payment_manager
from strings import t
from emoji_sticker_system import premium_emoji
from utils.helpers import safe_answer, safe_html
from utils.rate_limiter import buy_rate_limiter

logger = logging.getLogger(__name__)

router = Router(name="orders")

ADMIN_ID_INT = get_admin_id_int()

bot: Optional[Bot] = None


def set_bot(b: Bot):
    global bot
    bot = b


def get_bot() -> Optional[Bot]:
    return bot


# ==============================================================================
# Late-binding proxies for shared systems
# ==============================================================================


class _LogSystemProxy:
    def __bool__(self):
        try:
            import main
            return bool(getattr(main, "log_system", None))
        except Exception:
            return False

    def __getattr__(self, name):
        import main
        ls = getattr(main, "log_system", None)
        if ls is not None:
            return getattr(ls, name)
        raise AttributeError(f"'NoneType' object has no attribute '{name}'")


log_system = _LogSystemProxy()


class _AlertSystemProxy:
    def __bool__(self):
        try:
            import main
            return bool(getattr(main, "alert_system", None))
        except Exception:
            return False

    def __getattr__(self, name):
        import main
        als = getattr(main, "alert_system", None)
        if als is not None:
            return getattr(als, name)
        raise AttributeError(f"'NoneType' object has no attribute '{name}'")


alert_system = _AlertSystemProxy()


def create_order(*args, **kwargs):
    import main
    if hasattr(main, "create_order"):
        return main.create_order(*args, **kwargs)
    return 0


def get_purchase_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_purchase_keyboard"):
        return main.get_purchase_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def get_main_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_main_keyboard"):
        return main.get_main_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def get_back_only_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_back_only_keyboard"):
        return main.get_back_only_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def get_extension_success_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_extension_success_keyboard"):
        return main.get_extension_success_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def build_receipt_text(*args, **kwargs):
    import main
    if hasattr(main, "build_receipt_text"):
        return main.build_receipt_text(*args, **kwargs)
    return ""


async def notify_blacklisted_user(*args, **kwargs):
    import main
    if hasattr(main, "notify_blacklisted_user"):
        return await main.notify_blacklisted_user(*args, **kwargs)


async def send_sticker(*args, **kwargs):
    import main
    if hasattr(main, "send_sticker"):
        return await main.send_sticker(*args, **kwargs)


async def send_admin_notification(*args, **kwargs):
    import main
    if hasattr(main, "send_admin_notification"):
        return await main.send_admin_notification(*args, **kwargs)


async def send_config_with_qr_option(*args, **kwargs):
    import main
    if hasattr(main, "send_config_with_qr_option"):
        return await main.send_config_with_qr_option(*args, **kwargs)


async def cancel_order_admin(*args, **kwargs):
    import main
    if hasattr(main, "cancel_order_admin"):
        return await main.cancel_order_admin(*args, **kwargs)


# ==============================================================================
# Helper Functions
# ==============================================================================

def is_valid_checkout_state(state):
    """بررسی معتبر بودن وضعیت پرداخت قبل از ایجاد سفارش"""
    if not isinstance(state, dict) or not state.get('payment_ready'):
        return False

    payment_type = state.get('payment_type')
    if payment_type not in ('purchase', 'ready_package'):
        return False

    try:
        created_at = datetime.fromisoformat(state.get('timestamp', ''))
    except (TypeError, ValueError):
        return False

    ref_now = now_tehran() if created_at.tzinfo is not None else now_tehran().replace(tzinfo=None)
    age_seconds = (ref_now - created_at).total_seconds()
    if age_seconds < 0 or age_seconds > 1800:
        return False

    volume = state.get('volume')
    days = state.get('days')
    price = state.get('price')
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (volume, days, price)):
        return False
    if volume < 0 or days < 0 or price < 0:
        return False

    if payment_type == 'ready_package':
        return (
            state.get('is_ready_package') is True
            and state.get('category_id') is not None
            and state.get('package_id') is not None
        )

    return state.get('is_ready_package') is False


async def reject_expired_checkout(callback: CallbackQuery, lang: str):
    """رد درخواست پرداخت به دلیل انقضای وضعیت یا نامعتبر بودن داده‌ها"""
    message = t('this_checkout_has_expired_or_6ffee4935c', lang)
    await callback.answer(message, show_alert=True)


async def create_client_in_panel(
    user_id: int, 
    email: str, 
    volume_gb: int, 
    days: int, 
    user_name: str = None, 
    ip_limit: int = 0
) -> Optional[str]:
    """ساخت کلاینت در پنل با استفاده از اینباند انتخاب شده کاربر"""
    if not is_senai_panel_enabled():
        logger.warning('⚠️ Panel is disabled')
        return None
    
    if not user_name:
        user_info = get_user(user_id)
        user_name = user_info.get('name', f'user_{user_id}')
    inbound_id = get_user_inbound(user_id)
    
    return await xui_create_client_with_inbound(email, volume_gb, days, user_name, user_id, inbound_id, ip_limit=ip_limit)


# ==============================================================================
# Service Extension (Renewal) Engine
# ==============================================================================

async def extend_service(
    order_id: int, 
    user_id: int, 
    extra_volume: int, 
    extra_days: int,
    new_inbounds: list = None,
    new_ip_limit: int = None,
    new_category_id: int = None,
    new_category_name: str = None,
    new_category_name_en: str = None,
    new_package_id: int = None,
) -> bool:
    """
    تمدید سرویس موجود - افزایش حجم و روز + جایگزینی اینباندها
    + آپدیت اطلاعات دسته در سفارش اصلی
    + ریست ترافیک مصرفی در صورت سرویس نامحدود قبلی یا تغییر پکیج/دسته
    """
    logger.info(f"🔄 [extend_service] starting service extension - order_id={order_id}, user_id={user_id}")
    logger.info(f"   Additional Volume: {extra_volume}GB {'(unlimited)' if extra_volume == 0 else ''}")
    logger.info(f"   Additional Days: {extra_days}days")
    logger.info(f"   New IP limit: {new_ip_limit if new_ip_limit is not None else 'no change'}")
    order = orders.get(str(order_id))
    if not order:
        logger.error(f"❌ order #{order_id} not found for renewal")
        return False
    
    email = order.get('email')
    if not email:
        logger.error(f"❌ order # email {order_id} not found")
        return False
    
    if not is_senai_panel_enabled():
        logger.error('❌ panel service renewal not active')
        return False
    try:
        logger.info(f"📡 receiving client info {email} from panel...")
        client_info = await xui_get_client_info(email)
        
        if not client_info:
            logger.error(f"❌ Client {email} not found in the panel")
            return False
        current_inbounds = await get_client_inbounds(email)
        if not isinstance(current_inbounds, list):
            current_inbounds = [current_inbounds] if current_inbounds else []
        
        logger.info(f"📡 current inbounds: {current_inbounds}")
        if new_inbounds:
            selected_inbounds = new_inbounds
        else:
            selected_inbounds = order.get('inbound_id', [])
            if not selected_inbounds:
                selected_inbounds = current_inbounds if current_inbounds else get_user_inbound(user_id)
        
        if not isinstance(selected_inbounds, list):
            selected_inbounds = [selected_inbounds] if selected_inbounds else []
        
        logger.info(f"📡 new inbounds (selected): {selected_inbounds}")
        inbounds_to_detach = []
        for inbound_id in current_inbounds:
            if inbound_id and inbound_id not in selected_inbounds:
                inbounds_to_detach.append(inbound_id)
                logger.info(f"➖ Inbound {inbound_id} should be removed")
        
        inbounds_to_attach = []
        for inbound_id in selected_inbounds:
            if inbound_id and inbound_id not in current_inbounds:
                inbounds_to_attach.append(inbound_id)
                logger.info(f"➕ Inbound {inbound_id} should be added")
        current_volume_gb = client_info.get('totalGB', 0) / (1024**3)
        current_expiry = client_info.get('expiryTime', 0)
        current_ip_limit = client_info.get('limitIp', 0)
        
        logger.info("📊 Current client information:")
        logger.info(f"   📦 Current volume: {current_volume_gb:.2f} GB")
        logger.info(f"   ⏱ Current expiration: {datetime.fromtimestamp(current_expiry/1000).strftime('%Y-%m-%d %H:%M:%S') if current_expiry > 0 else 'unlimited'}")
        logger.info(f"   👤 Current IP limit: {current_ip_limit if current_ip_limit > 0 else 'unlimited'}")

        # ✅ بررسی سرویس نامحدود
        old_volume = order.get('volume', 0)
        is_old_unlimited = (old_volume == 0) or (client_info.get('totalGB', 0) == 0)
        is_new_unlimited = (extra_volume == 0)

        # ✅ بررسی تغییر دسته (دسته‌بندی سرویس)
        old_cat_id = order.get('category_id')
        old_cat_name = order.get('category_name')

        if old_cat_id is None and old_cat_name:
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('name') and str(cat.get('name')).strip() == str(old_cat_name).strip():
                    old_cat_id = cat.get('id')
                    break

        is_category_changed = False
        if new_category_id is not None and old_cat_id is not None:
            if int(new_category_id) != int(old_cat_id):
                is_category_changed = True
        elif new_category_name and old_cat_name:
            if str(new_category_name).strip() != str(old_cat_name).strip():
                is_category_changed = True
        elif new_category_id is not None and old_cat_id is None:
            is_category_changed = True

        should_replace_volume = is_old_unlimited or is_new_unlimited or is_category_changed
        should_reset_traffic = is_old_unlimited or is_new_unlimited or is_category_changed

        logger.info(f"🔍 Renewal status: is_old_unlimited={is_old_unlimited}, is_new_unlimited={is_new_unlimited}, is_category_changed={is_category_changed}")
        logger.info(f"   ➡️ should_replace_volume={should_replace_volume}, should_reset_traffic={should_reset_traffic}")

        if is_new_unlimited:
            new_volume_bytes = 0
            new_volume_gb = 0
            new_volume_total = 0
            logger.info("📦 New data limit: Unlimited (0 bytes)")
        elif should_replace_volume:
            new_volume_bytes = int(extra_volume * 1024 * 1024 * 1024)
            new_volume_gb = float(extra_volume)
            new_volume_total = extra_volume
            logger.info(f"📦 New data limit (replaced): {new_volume_gb:.2f} GB")
        else:
            new_volume_bytes = int((current_volume_gb + extra_volume) * 1024 * 1024 * 1024)
            new_volume_gb = current_volume_gb + extra_volume
            new_volume_total = current_volume_gb + extra_volume
            logger.info(f"📦 New data limit (cumulative): {new_volume_gb:.2f} GB")

        now_dt = datetime.now()
        if current_expiry > 0:
            current_expiry_date = datetime.fromtimestamp(current_expiry / 1000)
            base_date = current_expiry_date if current_expiry_date > now_dt else now_dt
            new_expiry_date = base_date + timedelta(days=extra_days)
            new_expiry = int(new_expiry_date.timestamp() * 1000)
        else:
            new_expiry_date = now_dt + timedelta(days=extra_days)
            new_expiry = int(new_expiry_date.timestamp() * 1000)
        
        logger.info(f"⏱ New expiration: {new_expiry_date.strftime('%Y-%m-%d %H:%M:%S')}")
        final_ip_limit = new_ip_limit if new_ip_limit is not None else current_ip_limit
        logger.info(f"👤 New IP limit: {final_ip_limit if final_ip_limit > 0 else 'unlimited'}")
        
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            logger.info("🔑 Logging in to the panel...")
            cookie = await xui_login()
            if not cookie:
                logger.error("❌ Error logging in to the panel")
                return False
            
            logger.info("🔐 Retrieving CSRF token...")
            csrf = await xui_get_csrf_token(session)
            headers = {"X-CSRF-Token": csrf} if csrf else {}
            update_data = {
                "email": email,
                "totalGB": new_volume_bytes,
                "expiryTime": new_expiry,
                "enable": True,
                "tgId": client_info.get('tgId', 0),
                "subId": client_info.get('subId', email),
                "flow": client_info.get('flow', ''),
                "limitIp": final_ip_limit,
                "comment": client_info.get('comment', ''),
                "resetStrategy": client_info.get('resetStrategy', 'no_reset')
            }
            
            logger.info("📤 Sending UPDATE request to the panel...")
            logger.info(f"   🌐 URL: {SENAI_PANEL_URL}/panel/api/clients/update/{email}")
            logger.info(f"   📝 Data: {'unlimited' if new_volume_bytes == 0 else f'{new_volume_gb:.2f}GB'}")
            logger.info(f"   👤 IP limit: {final_ip_limit if final_ip_limit > 0 else 'unlimited'}")
            
            async with session.post(
                f"{SENAI_PANEL_URL}/panel/api/clients/update/{email}",
                cookies={"3x-ui": cookie},
                headers=headers,
                json=update_data,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                response_text = await response.text()
                logger.info(f"📥 UPDATE response: Status {response.status}")
                
                if response.status != 200:
                    logger.error(f"❌ Error in UPDATE: Status {response.status}")
                    return False
                
                try:
                    data = json.loads(response_text)
                    if not data.get("success"):
                        logger.error(f"❌ UPDATE failed: {data.get('msg', 'Unknown error')}")
                        return False
                except json.JSONDecodeError:
                    logger.error("❌ Invalid JSON response")
                    return False
            
            logger.info("✅ UPDATE completed successfully")

            # ✅ در صورت تمدید سرویس نامحدود یا تغییر پکیج، ترافیک مصرفی ریست شود
            if should_reset_traffic:
                logger.info(f"🔄 Starting used traffic reset for client {email} in the panel...")
                reset_ok = await xui_reset_client_traffic(email, selected_inbounds)
                if reset_ok:
                    logger.info(f"✅ Traffic usage for client {email} successfully reset in the panel")
                else:
                    logger.warning(f"⚠️ Traffic reset result for client {email} failed or was unsupported")

            if inbounds_to_detach:
                logger.info(f"📤 Removing inbounds {inbounds_to_detach} from client {email}...")
                detach_success = await xui_detach_inbounds(email, inbounds_to_detach)
                if detach_success:
                    logger.info(f"✅ Inbounds {inbounds_to_detach} successfully removed")
                else:
                    logger.warning("⚠️ Error detaching inbounds")
            if inbounds_to_attach:
                logger.info(f"📤 Adding inbounds {inbounds_to_attach} to client {email}...")
                attach_success = await xui_attach_inbounds(email, inbounds_to_attach)
                if attach_success:
                    logger.info(f"✅ Inbounds {inbounds_to_attach} successfully added")
                else:
                    logger.warning("⚠️ Error attaching inbounds")

        new_days_total = order.get('days', 0) + extra_days
        
        logger.info(f"📝 Updating order #{order_id} in the database...")
        logger.info(f"   📦 New volume: {'unlimited' if new_volume_total == 0 else f'{new_volume_total:.2f}GB'}")
        logger.info(f"   ⏱ New days: {new_days_total}")
        logger.info(f"   New IP limit: {final_ip_limit if final_ip_limit > 0 else 'unlimited'}")
        logger.info(f"   📡 Inbounds: {selected_inbounds}")

        update_data = {
            'volume': new_volume_total,
            'days': new_days_total,
            'inbound_id': selected_inbounds,
            'ip_limit': final_ip_limit,
            'updated_at': now_tehran_iso(),
            'is_active_in_panel': True,
        }

        if new_category_id is not None:
            update_data['category_id'] = new_category_id
            logger.info(f"   🏷️ New category: {new_category_name or new_category_id}")

        if new_category_name:
            update_data['category_name'] = new_category_name

        if new_category_name_en:
            update_data['category_name_en'] = new_category_name_en

        if new_package_id is not None:
            update_data['package_id'] = new_package_id

        update_order(order_id, **update_data)

        if selected_inbounds:
            save_user_inbound_selection(user_id, selected_inbounds)

        if alert_system:
            try:
                await alert_system.record_service_renewal(
                    order,
                    email,
                    client_info,
                    {'totalGB': new_volume_bytes, 'expiryTime': new_expiry}
                )
            except Exception as alert_error:
                logger.error(
                    f"Failed to log service renewal for order #{order_id}: {alert_error}",
                    exc_info=True
                )

        logger.info(f"✅ Service renewal {email} completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error extending service: {e}", exc_info=True)
        return False
    finally:
        try:
            await connector.close()
        except Exception:
            pass


@router.callback_query(F.data.startswith("extend_service_"))
async def extend_service_start(callback: CallbackQuery):
    """شروع فرآیند تمدید سرویس - با بررسی وجود کانفیگ در پنل"""
    user_id = callback.from_user.id
    
    try:
        order_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(user_id).get('lang', 'fa')
    
    # ✅ چک لیست سیاه
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    # ✅ چک عضویت اجباری
    if not await check_membership(user_id):
        await callback.answer(
            t('please_verify_your_membershi_28b48b1f0b', lang),
            show_alert=True
        )
        return
    
    # ✅ چک باز بودن فروشگاه
    if not await check_shop_status_and_notify(user_id, callback, short_alert=True):
        return
    
    # ✅ چک اجازه خرید/تمدید
    can_purchase, msg = can_user_purchase(user_id)
    if not can_purchase:
        await callback.answer(
            msg if lang == "fa" else t('i18n_pending_admin_approval', lang),
            show_alert=True
        )
        return
    
    # ✅ بررسی سفارش
    order = orders.get(str(order_id))
    if not order or order.get('user_id') != user_id:
        await callback.answer(
            t('order_not_found_075d800b08', lang),
            show_alert=True
        )
        return
    
    if order.get('status') not in ['approved', 'inactive']:
        await callback.answer(
            t('this_service_cannot_be_exten_b6a29e23a8', lang),
            show_alert=True
        )
        return
    
    # ✅ جلوگیری از تمدید سرویس تست
    order_type = order.get('type', 'purchase')
    email_str = str(order.get('email', '') or '')
    is_test = (
        order_type == 'test'
        or order.get('is_test', False)
        or email_str.startswith('test_')
        or bool(re.match(r'^t\d+_', email_str))
    )
    if is_test:
        await callback.answer(
            t('cannot_extend_trial_service_a01c6c06a4', lang),
            show_alert=True
        )
        return
    
    # ✅ بررسی وجود کانفیگ در پنل
    email = order.get('email')
    resolved_email = email
    client_info = None

    if email and is_senai_panel_enabled():
        try:
            client_info = await xui_get_client_info(email)
        except Exception as e:
            logger.warning(f"Error checking client info for renewal: {e}")

    # Fallback به پیدا کردن ایمیل از ساب‌لینک
    if not client_info and is_senai_panel_enabled():
        sub_link = order.get('sub_link') or order.get('config_link')
        if sub_link:
            m = re.search(r'/sub/([a-zA-Z0-9]+)', sub_link)
            if m:
                sub_id = m.group(1)
                from services.panel_api import find_email_by_sub_id
                found_email = await find_email_by_sub_id(sub_id)
                if found_email:
                    resolved_email = found_email
                    order['email'] = found_email
                    update_order(order_id, email=found_email)
                    try:
                        client_info = await xui_get_client_info(found_email)
                    except Exception as e:
                        logger.warning(f"Error checking resolved client info for renewal: {e}")

    if is_senai_panel_enabled() and not client_info:
        logger.warning(
            f"❌ [extend_service_start] Order #{order_id} (email: {email}) was not found in the panel! Renewal canceled."
        )
        await callback.answer(
            t('this_service_cannot_be_exten_9962a37f5b', lang),
            show_alert=True
        )
        return

    # ✅ ذخیره حالت تمدید در user_states
    user_states[user_id] = {
        'extend_order_id': order_id,
        'current_volume': order.get('volume', 0),
        'current_days': order.get('days', 0),
        'email': resolved_email,
        'is_extend': True,
        'timestamp': now_tehran_iso()
    }
    
    logger.info(
        f"🔄 [extend_service_start] user {user_id} extending order #{order_id} started"
    )
    
    # ✅ ریست حجم و روز
    update_user(user_id, 'volume', 1)
    update_user(user_id, 'days', 30)
    
    # ✅ فراخوانی buy_service
    await buy_service(callback)


# ==============================================================================
# Service Purchase & Checkout Handlers
# ==============================================================================

@router.callback_query(F.data == "buy_service")
async def buy_service(callback: CallbackQuery):
    """خرید سرویس - نسخه نهایی با حفظ کوپن و پشتیبانی از تمدید"""
    user_id = callback.from_user.id
    if buy_rate_limiter.is_rate_limited(user_id, action="buy_service", cooldown=1.5):
        lang = get_user(user_id).get('lang', 'fa')
        wait_msg = "⏳ لطفاً کمی صبر کنید..." if lang == "fa" else "⏳ Please wait a moment..."
        await safe_answer(callback, wait_msg, alert=False)
        return
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    can_purchase, msg = can_user_purchase(user_id)
    if not can_purchase:
        lang = get_user(user_id).get('lang', 'fa')
        await callback.answer(msg if lang == "fa" else t('i18n_pending_admin_approval', lang), show_alert=True)
        return
    if not await check_membership(user_id):
        lang = get_user(user_id).get('lang', 'fa')
        await callback.answer(t('please_verify_your_membershi_28b48b1f0b', lang), show_alert=True)
        return
    if not await check_shop_status_and_notify(user_id, callback):
        return
    user = get_user(user_id)
    lang = user.get('lang', 'fa')

    # ✅ buy_service = شروع خرید جدید
    old_state = user_states.get(user_id, {})
    logger.info(f"🔍 [buy_service] previous state: {old_state}")

    # ✅ فقط اطلاعات ضروری حفظ میشن
    preserved_state = {
        key: old_state[key]
        for key in (
            'coupon_code',
            'coupon_discount',
            'coupon_applied',
            'is_extend',
            'extend_order_id',
            'current_volume',
            'current_days',
        )
        if key in old_state
    }

    # ✅ اگه کوپن توی user_states نبود، از دیتابیس بازیابی کن
    if not preserved_state.get('coupon_applied') or not preserved_state.get('coupon_code'):
        coupon_data = load_coupon_from_user_db(user_id)
        if coupon_data.get('coupon_applied') and coupon_data.get('coupon_code'):
            preserved_state['coupon_code'] = coupon_data.get('coupon_code')
            preserved_state['coupon_discount'] = coupon_data.get('coupon_discount', 0)
            preserved_state['coupon_applied'] = True
            logger.info(f"🏷️ [buy_service] Coupon {coupon_data.get('coupon_code')} restored from the database")

    # ✅ state رو با preserved جایگزین کن
    user_states[user_id] = preserved_state
    full_state = user_states[user_id]

    logger.info(f"🔄 [buy_service] cleared - preserved: {preserved_state}")

    coupon_code = full_state.get('coupon_code')
    coupon_discount = full_state.get('coupon_discount')
    coupon_applied = full_state.get('coupon_applied', False)

    is_extend = full_state.get('is_extend', False)
    extend_order_id = full_state.get('extend_order_id')

    vol = user.get('volume', 1)
    days = user.get('days', 30)
    original_price = calculate_price(vol, days)

    logger.info(f"🔍 [buy_service] coupon: code={coupon_code}, applied={coupon_applied}, discount={coupon_discount}")
    logger.info(f"🔍 [buy_service] renewal: is_extend={is_extend}, extend_order_id={extend_order_id}")
    logger.info(f"🔍 [buy_service] volume/days: {vol}GB / {days}days")
    discount_percent = 0
    final_price = original_price
    
    if coupon_applied and coupon_code:
        is_valid, reason = is_coupon_valid_for_user(coupon_code, user_id)
        if is_valid:
            discount_percent = coupon_discount
            if discount_percent > 0:
                final_price = original_price - (original_price * discount_percent // 100)
                logger.info(f"🏷️ [buy_service] Discount {discount_percent}% applied: {original_price:,} → {final_price:,}")
        else:
            logger.warning(f"⚠️ [buy_service] Invalid coupon: {reason}")
            if user_id in user_states:
                user_states[user_id].pop('coupon_code', None)
                user_states[user_id].pop('coupon_discount', None)
                user_states[user_id].pop('coupon_applied', None)
            coupon_applied = False
    if coupon_applied and coupon_code and discount_percent > 0:
        user_states[user_id]['coupon_code'] = coupon_code
        user_states[user_id]['coupon_applied'] = True
        user_states[user_id]['coupon_discount'] = discount_percent
        logger.info(f"🏷️ [buy_service] Coupon {coupon_code} in user_states for user {user_id} preserved")
    
    balance = user.get('balance', 0)
    ready_enabled = READY_PACKAGES.get('enabled', True)
    has_active_packages = False
    
    if ready_enabled:
        for cat in READY_PACKAGES.get('categories', []):
            if cat.get('is_active', True):
                active_packages = [p for p in cat.get('packages', []) if p.get('is_active', True)]
                if active_packages:
                    has_active_packages = True
                    break
    is_ready_package = full_state.get('is_ready_package', False)
    package_price = full_state.get('price', 0)
    category_name = full_state.get('category_name', 'بسته آماده')
    category_icon = full_state.get('category_icon', '📦')
    category_id = full_state.get('category_id')
    package_id = full_state.get('package_id')
    inbound_ids = full_state.get('inbound_ids', [])
    if is_ready_package and package_price > 0:
        final_price = package_price
        logger.info(f"📦 [buy_service] Ready-made package: {category_name} - fixed price: {final_price:,}tomans")
        
        discount_text = ""
        
        if discount_percent > 0 and final_price != original_price:
            discount_text = t('b_discounted_price_b_toman_o_17c3cb6633', lang, fa_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{final_price:,}', f'{discount_percent}'), en_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{final_price:,}', f'{discount_percent}'))
        user_states[user_id] = {
            'payment_type': 'ready_package',
            'category_id': category_id,
            'package_id': package_id,
            'volume': vol,
            'days': days,
            'price': final_price,
            'original_price': original_price,
            'discount_percent': discount_percent,
            'inbound_ids': inbound_ids,
            'category_name': category_name,
            'is_ready_package': True,
            'category_icon': category_icon,
            'current_page': 'package_payment',
            'payment_ready': True,
            'timestamp': now_tehran_iso()
        }
        
        if coupon_applied and coupon_code and discount_percent > 0:
            user_states[user_id]['coupon_code'] = coupon_code
            user_states[user_id]['coupon_applied'] = True
            user_states[user_id]['coupon_discount'] = discount_percent
            logger.info(f"🏷️ [buy_service] Coupon {coupon_code} in user_states for user {user_id} preserved")
        if is_extend and extend_order_id:
            user_states[user_id]['is_extend'] = True
            user_states[user_id]['extend_order_id'] = extend_order_id
            user_states[user_id]['current_volume'] = full_state.get('current_volume', 0)
            user_states[user_id]['current_days'] = full_state.get('current_days', 0)
            logger.info(f"🔄 [buy_service] Renewal mode enabled - order_id: {extend_order_id}")
        
        text = t('b_ready_package_b_volume_gb_99d385e64e', lang, fa_parts=lambda: (f'{category_icon}', f'{category_name}', f"{premium_emoji('config', '📦')}", f'{vol}', f"{premium_emoji('time', '⏱')}", f'{days}', f"{premium_emoji('money', '💰')}", f'{final_price:,}', f'{discount_text}', f"{premium_emoji('wallet', '💰')}", f'{balance:,}', f"{premium_emoji('info', '💡')}"), en_parts=lambda: (f'{category_icon}', f'{category_name}', f"{premium_emoji('config', '📦')}", f'{vol}', f"{premium_emoji('time', '⏱')}", f'{days}', f"{premium_emoji('money', '💰')}", f'{final_price:,}', f'{discount_text}', f"{premium_emoji('wallet', '💰')}", f'{balance:,}', f"{premium_emoji('info', '💡')}"))
        
        buttons = [
            [
                InlineKeyboardButton(
                    text=f"💳 {t('pay_by_card_8ef3792b24', lang)}",
                    callback_data="pay_card",
                    style="success"
                ),
                InlineKeyboardButton(
                    text=f"💰 {t('pay_by_balance_782475a04b', lang)}",
                    callback_data="pay_balance",
                    style="success"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔙 {t('back_to_packages_a33d8b6e6a', lang)}",
                    callback_data="show_ready_categories",
                    style="danger"
                )
            ]
        ]
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            if "message is not modified" not in str(e):
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer(
                    text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
        
        await safe_answer(callback)
        return
    if ready_enabled and has_active_packages:
        logger.info(f"📦 Ready-made packages are enabled - user {user_id} redirected to the category page")
        
        user_states[user_id] = {
            'payment_type': 'purchase',
            'volume': vol,
            'days': days,
            'price': final_price,
            'original_price': original_price,
            'discount_percent': discount_percent,
            'is_ready_package': False,
            'current_page': 'purchase',
            'timestamp': now_tehran_iso()
        }
        
        if coupon_applied and coupon_code and discount_percent > 0:
            user_states[user_id]['coupon_code'] = coupon_code
            user_states[user_id]['coupon_applied'] = True
            user_states[user_id]['coupon_discount'] = discount_percent
            logger.info(f"🏷️ [buy_service] Coupon {coupon_code} in user_states for user {user_id} preserved")
        if is_extend and extend_order_id:
            user_states[user_id]['is_extend'] = True
            user_states[user_id]['extend_order_id'] = extend_order_id
            user_states[user_id]['current_volume'] = full_state.get('current_volume', 0)
            user_states[user_id]['current_days'] = full_state.get('current_days', 0)
            logger.info(f"🔄 [buy_service] Renewal mode enabled - order_id: {extend_order_id}")
        
        await show_ready_categories(callback)
        return
    logger.info(f"🛒 [buy_service] custom purchase: {vol}GB/{days}days - price: {final_price:,}tomans")
    user_states[user_id] = {
        'payment_type': 'purchase',
        'volume': vol,
        'days': days,
        'price': final_price,
        'original_price': original_price,
        'discount_percent': discount_percent,
        'is_ready_package': False,
        'current_page': 'purchase',
        'payment_ready': True,
        'timestamp': now_tehran_iso()
    }
    
    if coupon_applied and coupon_code and discount_percent > 0:
        user_states[user_id]['coupon_code'] = coupon_code
        user_states[user_id]['coupon_applied'] = True
        user_states[user_id]['coupon_discount'] = discount_percent
        logger.info(f"🏷️ [buy_service] Coupon {coupon_code} in user_states for user {user_id} preserved")
    if is_extend and extend_order_id:
        user_states[user_id]['is_extend'] = True
        user_states[user_id]['extend_order_id'] = extend_order_id
        user_states[user_id]['current_volume'] = full_state.get('current_volume', 0)
        user_states[user_id]['current_days'] = full_state.get('current_days', 0)
        logger.info(f"🔄 [buy_service] Renewal mode enabled - order_id: {extend_order_id}")
    discount_text = ""
    if discount_percent > 0 and final_price != original_price:
        discount_text = t('b_discounted_price_b_toman_o_17c3cb6633', lang, fa_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{final_price:,}', f'{discount_percent}'), en_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{final_price:,}', f'{discount_percent}'))
    text = t('purchase_service_volume_gb_d_d95d0909aa', lang, fa_parts=lambda: (f"{premium_emoji('rocket', '🛒')}", f"{premium_emoji('config', '📦')}", f'{vol}', f"{premium_emoji('time', '⏱')}", f'{days}', f"{premium_emoji('money', '💰')}", f'{original_price:,}', f'{discount_text}', f"{premium_emoji('wallet', '💰')}", f'{balance:,}'), en_parts=lambda: (f"{premium_emoji('rocket', '🛒')}", f"{premium_emoji('config', '📦')}", f'{vol}', f"{premium_emoji('time', '⏱')}", f'{days}', f"{premium_emoji('money', '💰')}", f'{original_price:,}', f'{discount_text}', f"{premium_emoji('wallet', '💰')}", f'{balance:,}'))
    
    keyboard = get_purchase_keyboard(vol, days, lang)
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
    
    debug_coupon_state(user_id, "buy_service_end")
    
    await safe_answer(callback)


@router.callback_query(F.data == "vol_down")
async def vol_down(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    vol = user.get('volume', 1)
    if vol > 1:
        update_user(user_id, 'volume', vol - 1)
        logger.debug(f"User {user_id} reduced the volume: {vol} -> {vol-1}")
        await buy_service(callback)
    else:
        await callback.answer(t('minimum_volume_is_1_gb_9c04cdccbc', lang), show_alert=True)


@router.callback_query(F.data == "vol_up")
async def vol_up(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    vol = user.get('volume', 1)
    if vol < 100:
        update_user(user_id, 'volume', vol + 1)
        logger.debug(f"User {user_id} increased the volume: {vol} -> {vol+1}")
        await buy_service(callback)
    else:
        await callback.answer(t('maximum_volume_is_100_gb_e526281e2a', lang), show_alert=True)


@router.callback_query(F.data == "day_down")
async def day_down(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    days = user.get('days', 30)
    if days > 30:
        update_user(user_id, 'days', days - 15)
        logger.debug(f"User {user_id} reduced the days: {days} -> {days-15}")
        await buy_service(callback)
    else:
        await callback.answer(t('minimum_duration_is_30_days_ec62f2c52e', lang), show_alert=True)


@router.callback_query(F.data == "day_up")
async def day_up(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    days = user.get('days', 30)
    if days < 365:
        update_user(user_id, 'days', days + 15)
        logger.debug(f"User {user_id} increased the days: {days} -> {days+15}")
        await buy_service(callback)
    else:
        await callback.answer(t('maximum_duration_is_365_days_ecb47da82a', lang), show_alert=True)


@router.callback_query(F.data == "pay_card")
async def pay_card(callback: CallbackQuery):
    """پرداخت با کارت بانکی - نسخه کامل با پشتیبانی از تمدید"""
    user_id = callback.from_user.id
    logger.info(f"🔍 [pay_card] starting for user {user_id}")
    debug_coupon_state(user_id, "pay_card_start")
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    if not await check_membership(user_id):
        lang = get_user(user_id).get('lang', 'fa')
        await callback.answer(t('please_verify_your_membershi_28b48b1f0b', lang), show_alert=True)
        return
    if not await check_shop_status_and_notify(user_id, callback):
        return
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    
    current_user_state = user_states.get(user_id, {})
    if not is_valid_checkout_state(current_user_state):
        logger.warning(f"⚠️ [pay_card] Payment rejected; purchase state is invalid or stale (user {user_id})")
        await reject_expired_checkout(callback, lang)
        return

    save_coupon_to_user_db(user_id)
    
    is_extend = current_user_state.get('is_extend', False)
    extend_order_id = current_user_state.get('extend_order_id')
    current_volume = current_user_state.get('current_volume', 0)
    current_days = current_user_state.get('current_days', 0)
    
    full_state = current_user_state
    
    logger.info(f"🔍 [pay_card] complete STATE: {current_user_state}")
    logger.info(f"🔍 [pay_card] is_extend={is_extend}, extend_order_id={extend_order_id}")
    
    logger.info(f"🔍 [pay_card] previous state: {full_state}")
    logger.info(f"🔍 [pay_card] renewal: is_extend={is_extend}, extend_order_id={extend_order_id}")
    logger.info(f"🔍 [pay_card] current_volume={current_volume}GB, current_days={current_days}days")
    coupon_code = full_state.get('coupon_code')
    coupon_discount = full_state.get('coupon_discount')
    coupon_applied = full_state.get('coupon_applied', False)
    
    logger.info(f"🔍 [pay_card] extracted coupon: code={coupon_code}, applied={coupon_applied}, discount={coupon_discount}")
    is_ready_package = full_state.get('is_ready_package', False)
    if is_ready_package:
        vol = full_state.get('volume', 1)
        days = full_state.get('days', 30)
        final_price = full_state.get('price', 0)
        original_price = full_state.get('original_price', 0)
        discount_percent = full_state.get('discount_percent', 0)
        inbound_ids = full_state.get('inbound_ids', [])
        if not isinstance(inbound_ids, list):
            inbound_ids = [inbound_ids] if inbound_ids else []
        category_id = full_state.get('category_id')
        package_id = full_state.get('package_id')

        category_name = full_state.get('category_name', '') or ''
        category_name_en = full_state.get('category_name_en', '') or ''

        if (not category_name or not category_name_en) and category_id:
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('id') == category_id:
                    if not category_name:
                        category_name = cat.get('name') or ''
                    if not category_name_en:
                        category_name_en = cat.get('name_en') or cat.get('name') or ''
                    break

        if not category_name:
            category_name = "بسته آماده"
        if not category_name_en:
            category_name_en = "Ready Package"

        category_display = category_name if lang == 'fa' else category_name_en
        ip_limit = full_state.get('ip_limit', 0)
        order_type = "ready_package"
        
        volume_display = (t('unlimited_b72dd6e126', lang)) if vol == 0 else f"{vol} GB"
        logger.info(f"📦 [pay_card] Ready-made package: {category_name} - Volume: {volume_display} - price: {final_price:,}tomans")
    else:
        vol = user.get('volume', 1)
        days = user.get('days', 30)
        original_price = calculate_price(vol, days)
        final_price = original_price
        discount_percent = 0
        order_type = "purchase"
        inbound_ids = []
        category_name = None
        category_id = None
        package_id = None
        ip_limit = 0
        if coupon_applied and coupon_code:
            coupon = COUPONS.get(coupon_code)
            if coupon and coupon.get('status') == 'active':
                if user_id not in coupon.get('used_by', []):
                    discount_percent = coupon_discount
                    if discount_percent > 0:
                        final_price = original_price - (original_price * discount_percent // 100)
                        logger.info(f"🏷️ [pay_card] Discount {discount_percent}% applied: {original_price:,} → {final_price:,}")
        
        volume_display = (t('unlimited_b72dd6e126', lang)) if vol == 0 else f"{vol} GB"
        logger.info(f"🛒 [pay_card] Custom purchase: {vol}GB/{days}days - price: {final_price:,}tomans")
    if final_price == 0:
        logger.info(f"💰 [pay_card] Free payment for user {user_id}")
        await callback.message.edit_text(t('i18n_activating_free_service', lang))
        if is_extend and extend_order_id:
            logger.info(f"🔄 [pay_card] Starting free renewal for order #{extend_order_id}")
            parent_order = orders.get(str(extend_order_id))
            if not parent_order:
                logger.error(f"❌ [pay_card] Original order #{extend_order_id} not found")
                await callback.message.edit_text(
                    t('error_original_order_not_fou_26c4727bb4', lang),
                    reply_markup=get_back_only_keyboard(lang)
                )
                return

            _state = user_states.get(user_id, {})
            _cat_id = _state.get('category_id') or full_state.get('category_id')
            _cat_name = _state.get('category_name') or full_state.get('category_name')
            _cat_name_en = _state.get('category_name_en') or full_state.get('category_name_en')
            _pkg_id = _state.get('package_id') or full_state.get('package_id')

            if not isinstance(inbound_ids, list):
                inbound_ids = [inbound_ids] if inbound_ids else []

            success = await extend_service(
                extend_order_id, user_id, vol, days,
                new_inbounds=inbound_ids,
                new_ip_limit=ip_limit,
                new_category_id=_cat_id,
                new_category_name=_cat_name,
                new_category_name_en=_cat_name_en,
                new_package_id=_pkg_id,
            )
            if success:
                order_id = create_order(user_id, vol, days, 0, "extend", ip_limit=ip_limit)
                update_order(order_id, 
                            status='approved',
                            approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
                            payment_method='free_coupon_extend',
                            payment_label='🎁 رایگان (تمدید)',
                            parent_order_id=extend_order_id,
                            is_extend=True)
                if is_ready_package:
                    update_order(order_id, 
                                category_id=category_id,
                                category_name=category_name,
                                category_name_en=category_name_en,
                                package_id=package_id,
                                inbound_id=inbound_ids)
                
                consume_coupon(user_id)
                if user_id in user_states:
                    user_states[user_id].pop('is_extend', None)
                    user_states[user_id].pop('extend_order_id', None)
                    user_states[user_id].pop('current_volume', None)
                    user_states[user_id].pop('current_days', None)
                updated_parent = orders.get(str(extend_order_id))
                new_volume = updated_parent.get('volume', 0) if updated_parent else current_volume + vol
                new_days = updated_parent.get('days', 0) if updated_parent else current_days + days
                await send_admin_notification('extend', {
                    'user_id': user_id,
                    'volume': vol,
                    'days': days,
                    'price': 0,
                    'discount_percent': discount_percent,
                    'balance_before': user.get('balance', 0),
                    'balance_after': user.get('balance', 0),
                    'order_id': order_id,
                    'payment_type': 'free_extend',
                    'payment_label': '🎁 رایگان (تمدید)',
                    'payment_emoji': '🎁',
                    'is_extend': True,
                    'parent_order_id': extend_order_id,
                    'old_volume': current_volume,
                    'old_days': current_days,
                    'new_volume': new_volume,
                    'new_days': new_days,
                    'category_name': category_name
                })
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                
                RLM = "\u200F"
                if lang == "fa":
                    if vol == 0:
                        vol_line = t('b_traffic_b_unlimited_e5a9561386', lang, fa_parts=lambda: (f'{RLM}',))
                    else:
                        vol_line = t('b_added_volume_b_gb_7f1d65c8dd', lang, fa_parts=lambda: (f'{RLM}', f'{vol}'))
                    
                    text = (
                        t('b_service_extended_successfu_80e47c2bbe', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f'{RLM}', f'{extend_order_id}', f'{vol_line}', f'{RLM}', f'{days}', f'{RLM}'))
                    )
                else:
                    vol_line = t('b_traffic_b_unlimited_e5a9561386', lang) if vol == 0 else t('b_added_volume_b_gb_7f1d65c8dd', lang, en_parts=lambda: (f'{vol}',))
                    text = (
                        t('b_service_extended_successfu_80e47c2bbe', lang, en_parts=lambda: (f'{extend_order_id}', f'{vol_line}', f'{days}'))
                    )
                
                await callback.message.answer(
                    text, 
                    parse_mode=ParseMode.HTML, 
                    reply_markup=get_extension_success_keyboard(extend_order_id, lang)
                )
                logger.info(f"✅ [pay_card] Free renewal for user {user_id} - order #{order_id}")
                await callback.answer(t('service_extended_36fc3cd187', lang))
                return
            else:
                await callback.message.edit_text(
                    t('error_extending_service_plea_855d6546d7', lang),
                    reply_markup=get_back_only_keyboard(lang)
                )
                return
        order_id = create_order(user_id, vol, days, 0, order_type, ip_limit=ip_limit)
        update_order(order_id, 
                    status='approved',
                    approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
                    payment_method='free_coupon',
                    payment_label='🎁 رایگان (کوپن)')
        
        if is_ready_package:
            update_order(order_id, 
                        category_id=category_id,
                        category_name=category_name,
                        category_name_en=category_name_en,
                        package_id=package_id,
                        inbound_id=inbound_ids)
        
        timestamp = int(datetime.now().timestamp())
        email = f"user{user_id}_{timestamp}"
        user_name = user.get('name', f'کاربر_{user_id}')
        
        if is_ready_package and inbound_ids:
            inbound_to_use = inbound_ids
        else:
            inbound_to_use = get_user_inbound(user_id)
        
        sub_link = await xui_create_client_with_inbound(email, vol, days, user_name, user_id, inbound_to_use, ip_limit=ip_limit)
        
        if sub_link:
            update_order(order_id, config_link=sub_link, sub_link=sub_link, email=email)
            record_purchase(user_id, 0)
            consume_coupon(user_id)
            
            await send_config_with_qr_option(user_id, order_id, vol, days, 0, sub_link, lang)
            
            if is_ready_package:
                category_display_final = f"{category_display} - "
            else:
                category_display_final = ""
            volume_display_text = format_package_volume(vol, lang)
                        
            text = t('b_free_service_activated_suc_6742be6139', lang, fa_parts=lambda: (f'{category_display_final}', f'{volume_display_text}', f'{days}'), en_parts=lambda: (f'{category_display_final}', f'{volume_display_text}', f'{days}'))
            
            await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=get_back_only_keyboard(lang))
            logger.info(f"✅ [pay_card] Free service activated for user {user_id} activated - order #{order_id}")
            await callback.answer(t('free_service_activated_f728c97970', lang))
            return
        else:
            await callback.message.edit_text(
                t('error_creating_service_pleas_7adc93c4dd', lang),
                reply_markup=get_back_only_keyboard(lang)
            )
            return
    logger.info(f"💰 [pay_card] user {user_id} starting card payment - price: {final_price:,}tomans")
    
    if log_system:
        await log_system.log_user_action(
            user_id, 
            "Started card payment",
            f"Price: {final_price:,} Toman | Volume: {vol}GB | Duration: {days} days"
        )
    order_id = create_order(user_id, vol, days, final_price, order_type, ip_limit=ip_limit)

    base_order_price = final_price
    payable_amount = final_price
    discount_offset = 0

    if sms_payment_manager.is_enabled():
        try:
            window_min = sms_payment_manager.get_window_minutes()
            payable_amount, discount_offset = sms_payment_manager.db.reserve_unique_payable_amount(
                order_id=order_id,
                order_type=order_type if not is_extend else "extend",
                user_id=user_id,
                base_price=base_order_price,
                window_minutes=window_min
            )
            final_price = payable_amount
        except Exception as e:
            logger.error(f"❌ Error reserving custom card amount: {e}")
            update_order(order_id, status='cancelled')
            err_msg = (
                t('unable_to_reserve_a_unique_p_a66aedad8b', lang)
            )
            await callback.answer(err_msg, show_alert=True)
            return

    final_price = payable_amount

    if is_ready_package:
        update_order(order_id,
                    category_id=category_id,
                    category_name=category_name,
                    category_name_en=category_name_en,
                    package_id=package_id,
                    inbound_id=inbound_ids,
                    base_price=base_order_price,
                    payable_amount=payable_amount,
                    discount_offset=discount_offset,
                    price=payable_amount,
                    amount=payable_amount,
                    status='awaiting_payment',
                    payment_method='card',
                    payment_label='💳 کارت به کارت')
    else:
        update_order(order_id,
                    base_price=base_order_price,
                    payable_amount=payable_amount,
                    discount_offset=discount_offset,
                    price=payable_amount,
                    amount=payable_amount,
                    status='awaiting_payment',
                    payment_method='card',
                    payment_label='💳 کارت به کارت')
    if is_extend and extend_order_id:
        parent_order = orders.get(str(extend_order_id))
        if parent_order:
            update_order(order_id, 
                        parent_order_id=extend_order_id,
                        is_extend=True)
            logger.info(f"🔄 [pay_card] Order #{order_id} for renewal of order #{extend_order_id} created")
        else:
            logger.warning(f"⚠️ [pay_card] Original order #{extend_order_id} not found; renewal canceled")
            is_extend = False
            extend_order_id = None
    
    logger.info(f"📝 [pay_card] order #{order_id} created - type: {order_type} - Volume: {vol}GB")
    logger.info("💳 [pay_card] payment method: card-to-card")
    try:
        await send_sticker(user_id, 'payment', '💳')
    except Exception as e:
        logger.warning(f"Error sending sticker: {e}")
        await callback.message.answer(premium_emoji('card', '💳'))
    
    card_num = ' '.join([BANK_CARD_NUMBER[i:i+4] for i in range(0, 16, 4)])
    price_display = t('toman_287614cf02', lang, fa_parts=lambda: (f'{final_price:,}',), en_parts=lambda: (f'{final_price:,}',))
    if discount_percent > 0 and final_price != original_price:
        price_display = t('s_s_toman_off_6e5cab5ced', lang, fa_parts=lambda: (f'{original_price:,}', f'{final_price:,}', f'{discount_percent}'), en_parts=lambda: (f'{original_price:,}', f'{final_price:,}', f'{discount_percent}'))
    
    order = orders.get(str(order_id))
    text = build_receipt_text(order, lang, mode="card")
    card_num_copy = BANK_CARD_NUMBER.replace(' ', '').replace('-', '')

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📋 {t('copy_amount_in_rial_2426b59317', lang)} ({final_price * 10:,})",
            copy_text=CopyTextButton(text=str(final_price * 10))
        )],
        [InlineKeyboardButton(
            text=f"💳 {t('copy_card_number_0a73534ca5', lang)}",
            copy_text=CopyTextButton(text=card_num_copy)
        )],
        [InlineKeyboardButton(
            text=f"❌ {t('cancel_payment_77ac7fd08e', lang)}",
            callback_data=f"cancel_order_{order_id}",
            style="danger"
        )]
    ])
    
    payment_message = await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    update_order(order_id, payment_message_id=payment_message.message_id)

    try:
        await callback.message.delete()
    except Exception:
        pass
    new_state = {
        'awaiting_receipt': True, 
        'current_order_id': order_id, 
        'timestamp': now_tehran_iso(),
        'payment_type': order_type,
        'final_price': final_price,
        'original_price': original_price,
        'discount_percent': discount_percent,
        'payment_method': 'card',
        'payment_label': '💳 کارت به کارت'
    }
    if coupon_applied and coupon_code:
        new_state['coupon_code'] = coupon_code
        new_state['coupon_applied'] = True
        new_state['coupon_discount'] = coupon_discount if coupon_discount else 0
        logger.info(f"🏷️ [pay_card] Coupon {coupon_code} transferred to the new state")
    if is_ready_package:
        new_state['is_ready_package'] = True
        new_state['category_id'] = category_id
        new_state['package_id'] = package_id
        new_state['inbound_id'] = inbound_ids
        new_state['category_name'] = category_name
    if is_extend and extend_order_id:
        new_state['is_extend'] = True
        new_state['extend_order_id'] = extend_order_id
        new_state['current_volume'] = current_volume
        new_state['current_days'] = current_days
        logger.info(f"🔄 [pay_card] Renewal information transferred to the new state: order_id={extend_order_id}")
    else:
        if full_state.get('is_extend', False) and full_state.get('extend_order_id'):
            new_state['is_extend'] = full_state.get('is_extend')
            new_state['extend_order_id'] = full_state.get('extend_order_id')
            new_state['current_volume'] = full_state.get('current_volume', 0)
            new_state['current_days'] = full_state.get('current_days', 0)
            logger.info(f"🔄 [pay_card] Renewal information transferred from full_state to new_state: order_id={full_state.get('extend_order_id')}")
    user_states[user_id] = new_state
    
    logger.info(f"✅ [pay_card] user status {user_id} set to awaiting_receipt for order #{order_id}")
    logger.info(f"🔍 [pay_card] new_state: {new_state}")
    debug_coupon_state(user_id, "pay_card_end")
    
    await safe_answer(callback)


@router.callback_query(F.data.startswith("send_receipt_"))
async def send_receipt_reminder(callback: CallbackQuery):
    """آماده دریافت فیش - با استایل یکپارچه"""
    user_id = callback.from_user.id
    order_id = int(callback.data.split("_")[2])
    lang = get_user(user_id).get('lang', 'fa')
    
    full_state = user_states.get(user_id, {})
    coupon_code = full_state.get('coupon_code')
    coupon_discount = full_state.get('coupon_discount')
    coupon_applied = full_state.get('coupon_applied', False)
    
    order = orders.get(str(order_id))
    if not order or order.get('status') != 'awaiting_payment':
        await callback.answer(t('invalid_order_77d8e07d6d', lang), show_alert=True)
        return
    
    user_states[user_id] = {
        'awaiting_receipt': True,
        'current_order_id': order_id,
        'timestamp': now_tehran_iso()
    }
    
    if coupon_applied and coupon_code:
        user_states[user_id]['coupon_code'] = coupon_code
        user_states[user_id]['coupon_applied'] = True
        user_states[user_id]['coupon_discount'] = coupon_discount if coupon_discount else 0
    
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    text = build_receipt_text(order, lang, mode="reminder")
    
    cancel_btn = t('cancel_4197bafba5', lang)
    
    current_bot = bot or get_bot() or callback.bot
    await current_bot.send_message(
        user_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=cancel_btn, callback_data=f"cancel_order_{order_id}", style="danger")]
        ])
    )
    
    await safe_answer(callback)


@router.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order_direct(callback: CallbackQuery):
    """انصراف مستقیم از سفارش توسط کاربر - کوپن باقی می‌ماند"""
    if callback.data.startswith("cancel_order_admin_"):
        logger.debug(f"⏩ Callback cancel_order_admin routed to the admin handler: {callback.data}")
        await cancel_order_admin(callback)
        return
    
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    parts = callback.data.split("_")
    
    if len(parts) < 3:
        await callback.answer(t('i18n_invalid_callback_format', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    try:
        order_id = int(parts[2])
    except ValueError:
        await callback.answer(t('i18n_order_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    user_state = user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)
    
    has_real_coupon = bool(coupon_applied and coupon_code)
    
    logger.info(f"🔍 [cancel_order_direct] coupon: code={coupon_code}, applied={coupon_applied}, has_real={has_real_coupon}")
    
    order = orders.get(str(order_id))
    if not order:
        await callback.answer(t('i18n_order_process_error', lang), show_alert=True)
        return

    if order.get('user_id') != user_id and user_id != ADMIN_ID_INT:
        logger.warning(f"Unauthorized cancel_order attempt: user {user_id} tried to cancel order #{order_id} of user {order.get('user_id')}")
        await callback.answer("⛔", show_alert=True)
        return

    if order.get('status') in ['pending', 'pending_balance_charge']:
        await callback.answer(t('your_receipt_has_been_submit_8f52c3371d', lang), show_alert=True)
        return
    
    if order.get('status') == 'awaiting_payment':
        update_order(order_id, status='cancelled')
        try:
            sms_payment_manager.db.cancel_reservation(order_id, order.get('type', 'purchase'))
        except Exception:
            pass
        logger.info(f"Order #{order_id} canceled by the user")
        
        if log_system:
            await log_system.log_user_action(
                user_id,
                "Cancelled order",
                f"Order #{order_id} was cancelled"
            )
        
        await callback.answer(t('order_cancelled_successfully_2dcc7269f4', lang, fa_parts=lambda: (f'{order_id}',), en_parts=lambda: (f'{order_id}',)), show_alert=True)
    else:
        await callback.answer(t('this_order_cannot_be_cancell_8b13c665bb', lang), show_alert=True)
        return
    
    # ✅ پاک کردن state
    if user_id in user_states:
        user_states.pop(user_id, None)
    
    # ✅ بازیابی کوپن فقط اگه واقعاً وجود داشت
    if has_real_coupon:
        user_states[user_id] = {
            'coupon_code': coupon_code,
            'coupon_discount': coupon_discount if coupon_discount else 0,
            'coupon_applied': True
        }
        logger.info(f"🏷️ [cancel_order_direct] Coupon {coupon_code} for user {user_id} preserved")
        save_coupon_to_user_db(user_id)
    
    is_admin = (user_id == ADMIN_ID_INT)
    
    text = (
        t('payment_cancelled_54c880919a', lang, fa_parts=lambda: (f"{premium_emoji('danger', '❌')}",), en_parts=lambda: (f"{premium_emoji('danger', '❌')}",))
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_main_keyboard(is_admin, lang, user_id)
        )
    except Exception as e:
        logger.debug(f"Failed to edit message in cancel_order_direct, sending new: {e}")
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            text,
            reply_markup=get_main_keyboard(is_admin, lang, user_id)
        )
    
    await safe_answer(callback)

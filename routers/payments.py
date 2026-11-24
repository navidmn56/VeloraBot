"""
routers/payments.py
-------------------
ماژول پرداخت و رسیدهای ربات تلگرام (فاز ۳.۳)
شامل:
- پرداخت از موجودی (pay_balance, _process_pay_balance)
- دریافت و پردازش فیش واریزی (handle_receipt)
- پرداخت دلخواه توسط ادمین (custom_payment_receipt_*)
- تأیید و انتخاب اینباندهای سفارش (approve_receipt, select_user_inbound, save_inbounds, ...)
- اعمال و لغو کوپن در خرید (apply_coupon_page, cancel_coupon)
- لغو پرداخت و تلاش مجدد رسید (cancel_payment, retry_receipt)
- ارسال کانفیگ دستی ادمین (send_config_to_user, admin_get_config)
"""

import html
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from aiogram import Bot, Router, F, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from config import SENAI_PANEL_ENABLED, is_senai_panel_enabled
from utils.payment_guard import payment_guard, order_guard, PaymentInProgressError
from core.state_stores import TEMP_INBOUND_SELECTION, user_states
from database import (
    users,
    orders,
    configs_pool,
    BLACKLIST,
    READY_PACKAGES,
    DB_FILES,
    save_json,
    update_order,
    now_tehran,
    now_tehran_iso,
    get_valid_orders,
)
from user_manager import (
    get_user,
    update_user,
    calculate_price,
    consume_coupon,
    record_purchase,
    get_admin_id_int,
    is_coupon_valid_for_user,
    save_coupon_to_user_db,
    debug_coupon_state,
    COUPONS,
    add_balance,
)
from balance_system import approve_balance
from routers.force_join import check_membership
from routers.shop import check_shop_status_and_notify, format_package_volume
from routers.orders import (
    is_valid_checkout_state,
    reject_expired_checkout,
    extend_service,
    create_client_in_panel,
)
from routers.configs_view import send_config_with_qr_option
from routers.admin_test import OrderInboundCB, save_user_inbound_selection
from routers.support import handle_chat_message
from routers.admin_tools import admin_chat_reply
from services.panel_api import (
    xui_create_client_with_inbound,
    get_user_inbound,
    filter_valid_inbounds,
    xui_get_inbounds,
    get_inbound_display_names,
)
from strings import t
from utils.filters import IsAdmin
from utils.guards import admin_only
from utils.helpers import premium_emoji, safe_answer, safe_html

logger = logging.getLogger(__name__)

router = Router(name="payments")

ADMIN_ID_INT = get_admin_id_int()

# ---------------------------------------------------------------------------
# Bot Reference & Proxy
# ---------------------------------------------------------------------------
_bot: Optional[Bot] = None

def set_bot(b: Bot):
    global _bot
    _bot = b

class _PaymentsBotProxy:
    def __getattr__(self, name):
        if _bot is not None:
            return getattr(_bot, name)
        import main
        main_bot = getattr(main, "bot", None)
        if main_bot is not None:
            return getattr(main_bot, name)
        raise RuntimeError("Bot instance not set in routers.payments")

bot = _PaymentsBotProxy()

# ---------------------------------------------------------------------------
# Late-binding Proxies for functions still in main.py
# ---------------------------------------------------------------------------
def create_order(*args, **kwargs):
    import main
    if hasattr(main, "create_order"):
        return main.create_order(*args, **kwargs)
    raise RuntimeError("main.create_order is not initialized")

async def send_admin_notification(*args, **kwargs):
    import main
    if hasattr(main, "send_admin_notification"):
        return await main.send_admin_notification(*args, **kwargs)

def build_receipt_text(*args, **kwargs):
    import main
    if hasattr(main, "build_receipt_text"):
        return main.build_receipt_text(*args, **kwargs)

def get_extension_success_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_extension_success_keyboard"):
        return main.get_extension_success_keyboard(*args, **kwargs)

def get_feedback_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_feedback_keyboard"):
        return main.get_feedback_keyboard(*args, **kwargs)

def get_back_only_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_back_only_keyboard"):
        return main.get_back_only_keyboard(*args, **kwargs)

def get_main_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_main_keyboard"):
        return main.get_main_keyboard(*args, **kwargs)

async def notify_blacklisted_user(*args, **kwargs):
    import main
    if hasattr(main, "notify_blacklisted_user"):
        return await main.notify_blacklisted_user(*args, **kwargs)

async def update_user_receipt_review_status(*args, **kwargs):
    import main
    if hasattr(main, "update_user_receipt_review_status"):
        return await main.update_user_receipt_review_status(*args, **kwargs)

def find_pending_order(*args, **kwargs):
    import main
    if hasattr(main, "find_pending_order"):
        return main.find_pending_order(*args, **kwargs)

def get_order_category_name(*args, **kwargs):
    import main
    if hasattr(main, "get_order_category_name"):
        return main.get_order_category_name(*args, **kwargs)

def backfill_order_category(*args, **kwargs):
    import main
    if hasattr(main, "backfill_order_category"):
        return main.backfill_order_category(*args, **kwargs)

async def get_config_from_pool_safe(*args, **kwargs):
    import main
    if hasattr(main, "get_config_from_pool_safe"):
        return await main.get_config_from_pool_safe(*args, **kwargs)

async def check_referral_bonus(*args, **kwargs):
    import main
    if hasattr(main, "check_referral_bonus"):
        return await main.check_referral_bonus(*args, **kwargs)

class _PaymentsLogSystemProxy:
    def __getattr__(self, name):
        import main
        ls = getattr(main, "log_system", None)
        if ls is not None:
            return getattr(ls, name)
        async def _noop(*args, **kwargs):
            return None
        return _noop
    def __bool__(self):
        import main
        return bool(getattr(main, "log_system", None))

log_system = _PaymentsLogSystemProxy()

# ---------------------------------------------------------------------------
# Payment & Receipt Handlers
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "pay_balance")
async def pay_balance(callback: CallbackQuery):
    """پرداخت از موجودی - نسخه کامل با پشتیبانی از تمدید و ترکیب اینباندها"""
    user_id = callback.from_user.id
    logger.info(f"🔍 [pay_balance] starting for user {user_id}")
    debug_coupon_state(user_id, "pay_balance_start")
    
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

    try:
        async with payment_guard.lock_user(user_id):
            return await _process_pay_balance(callback, user_id)
    except PaymentInProgressError:
        lang = get_user(user_id).get('lang', 'fa')
        msg = (
            "⏳ درخواست پرداخت شما در حال پردازش است، لطفاً شکیبا باشید."
            if lang == "fa"
            else "⏳ Your payment is already being processed, please wait."
        )
        await safe_answer(callback, msg, alert=True)
        return


async def _process_pay_balance(callback: CallbackQuery, user_id: int):
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    
    # ✅✅✅ خواندن مستقیم از user_states (نه از full_state)
    current_user_state = user_states.get(user_id, {})
    if not is_valid_checkout_state(current_user_state):
        logger.warning(f"⚠️ [pay_balance] Payment rejected; purchase state is invalid or stale (user {user_id})")
        await reject_expired_checkout(callback, lang)
        return
    
    # ابطال فوری وضعیت پرداخت برای جلوگیری از استفاده مجدد یا race condition
    current_user_state['payment_ready'] = False
    
    is_extend = current_user_state.get('is_extend', False)
    extend_order_id = current_user_state.get('extend_order_id')
    current_volume = current_user_state.get('current_volume', 0)
    current_days = current_user_state.get('current_days', 0)
    
    full_state = current_user_state  # برای سازگاری با بقیه کد
    
    logger.info(f"🔍 [pay_balance] complete STATE: {current_user_state}")
    logger.info(f"🔍 [pay_balance] is_extend={is_extend}, extend_order_id={extend_order_id}")
    
    is_ready_package = full_state.get('is_ready_package', False)
    ip_limit = full_state.get('ip_limit', 0)
    inbound_ids = full_state.get('inbound_ids', [])
    
    if not isinstance(inbound_ids, list):
        inbound_ids = [inbound_ids] if inbound_ids else []
    
    logger.info(f"🔍 [pay_balance] complete state: {full_state}")
    logger.info(f"🔍 [pay_balance] renewal: is_extend={is_extend}, extend_order_id={extend_order_id}")
    logger.info(f"🔍 [pay_balance] current_volume={current_volume}GB, current_days={current_days}days")
    logger.info(f"🔍 [pay_balance] ip_limit={ip_limit}, inbound_ids={inbound_ids}")
    
    if is_ready_package:
        vol = full_state.get('volume', 1)
        days = full_state.get('days', 30)
        final_price = full_state.get('price', 0)
        original_price = full_state.get('original_price', 0)
        discount_percent = full_state.get('discount_percent', 0)
        category_id = full_state.get('category_id')
        package_id = full_state.get('package_id')

        # ✅ هر دو اسم رو بگیر، مستقل از زبان
        category_name = full_state.get('category_name', '') or ''
        category_name_en = full_state.get('category_name_en', '') or ''

        # اگه یکی از اسم‌ها خالی بود → از READY_PACKAGES پر کن
        if (not category_name or not category_name_en) and category_id:
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('id') == category_id:
                    if not category_name:
                        category_name = cat.get('name') or ''
                    if not category_name_en:
                        category_name_en = cat.get('name_en') or cat.get('name') or ''
                    break

        # اگه هنوز خالی → پیش‌فرض
        if not category_name:
            category_name = "بسته آماده"
        if not category_name_en:
            category_name_en = "Ready Package"

        # ✅ برای نمایش توی متن، بر اساس زبان انتخاب کن
        category_display = category_name if lang == 'fa' else category_name_en
        order_type = "ready_package"
        
        volume_display = (t('unlimited_b72dd6e126', lang)) if vol == 0 else f"{vol} GB"
        logger.info(f"📦 [pay_balance] Ready-made package: {category_name} - Volume: {volume_display} - final price: {final_price:,}tomans")
    else:
        vol = user.get('volume', 1)
        days = user.get('days', 30)
        original_price = calculate_price(vol, days)
        final_price = original_price
        discount_percent = 0
        order_type = "purchase"
        category_name = None
        category_id = None
        package_id = None
        coupon_code = full_state.get('coupon_code')
        coupon_applied = full_state.get('coupon_applied', False)
        
        if coupon_applied and coupon_code:
            is_valid, reason = is_coupon_valid_for_user(coupon_code, user_id)
            if is_valid:
                discount_percent = full_state.get('coupon_discount', 0)
                if discount_percent > 0:
                    final_price = original_price - (original_price * discount_percent // 100)
            else:
                logger.warning(f"⚠️ [pay_balance] Invalid coupon: {reason}")
                if user_id in user_states:
                    user_states[user_id].pop('coupon_code', None)
                    user_states[user_id].pop('coupon_discount', None)
                    user_states[user_id].pop('coupon_applied', None)
        
        volume_display = (t('unlimited_b72dd6e126', lang)) if vol == 0 else f"{vol} GB"
        logger.info(f"🛒 [pay_balance] Custom purchase: {volume_display}/{days}days - price: {final_price:,}tomans")
    
    user = get_user(user_id)
    balance = user.get('balance', 0)
    
    logger.info(f"💰 [pay_balance] user balance: {balance:,}tomans")
    logger.info(f"💰 [pay_balance] final price: {final_price:,}tomans")
    
    # ✅ بررسی موجودی کافی (برای خریدهای غیر رایگان)
    if final_price > 0 and balance < final_price:
        current_user_state['payment_ready'] = True
        # ==================== 0) حذف پیام بسته ====================
        try:
            await callback.message.delete()
            logger.info(f"🗑 Ready-package message for user {user_id} deleted")
        except Exception as e:
            logger.debug(f"Failed to delete message: {e}")
        
        # ==================== محاسبه کمبود ====================
        shortage = final_price - balance
        
        # ==================== 1) آلرت ====================
        alert_text = t('insufficient_balance_ac359d68f7', lang)
        
        await safe_answer(callback, alert_text)
        
        # ==================== 2) استیکر ====================
        try:
            insufficient_sticker = "CAACAgIAAxkBAAERYtdqLYNgjzOUQi8uRFj-ZxHiOhEZvwACRh4AAvyUOEnTIzZfgD7FIDwE"
            await callback.message.answer_sticker(insufficient_sticker)
        except Exception as e:
            logger.warning(f"⚠️ Error sending sticker: {e}")
        
        # ==================== 3) متن + دکمه‌ها ====================
        text = (
            t('b_insufficient_balance_b_pri_bfeaf3048a', lang, fa_parts=lambda: (f'{final_price:,}', f'{balance:,}', f'{shortage:,}'), en_parts=lambda: (f'{final_price:,}', f'{balance:,}', f'{shortage:,}'))
        )
        btn_increase = t('increase_balance_693da7ac44', lang)
        btn_main = t('main_menu_0cdd07a7cc', lang)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=btn_increase,
                callback_data="increase_balance",
                style="success"
            )],
            [InlineKeyboardButton(
                text=btn_main,
                callback_data="back_to_main",
                style="primary"
            )]
        ])
        
        try:
            await callback.message.answer(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"❌ Error sending message: {e}", exc_info=True)
        
        # ==================== 4) لاگ ====================
        if log_system:
            await log_system.log_user_action(
                user_id,
                "Insufficient balance",
                f"Balance: {balance:,} | Required: {final_price:,} | Shortfall: {shortage:,}"
            )
        
        return
    
    # ✅ کسر موجودی (فقط اگر قیمت > 0)
    new_balance = balance
    if final_price > 0:
        new_balance = balance - final_price
        update_user(user_id, 'balance', new_balance)
        if log_system:
            await log_system.log_balance_change(
                user_id=user_id,
                amount=-final_price,
                new_balance=new_balance,
                action="reduce",
                admin_id=None,
                details=f"Purchased service {vol}GB/{days} days (discount {discount_percent}%)"
            )
    
    # ============================================
    # ✅ ساخت سفارش فقط یکبار در این نقطه
    # ============================================
    if is_extend and extend_order_id:
        order_id = create_order(user_id, vol, days, final_price, "extend", ip_limit=ip_limit)
    else:
        order_id = create_order(user_id, vol, days, final_price, order_type, ip_limit=ip_limit)
    
    logger.info(f"📝 [pay_balance] order #{order_id} created - type: {order_type if not is_extend else 'extend'} - Volume: {vol}GB - price: {final_price:,}")
    
    # ✅ آپدیت اطلاعات پایه سفارش
    update_order(order_id, inbound_id=inbound_ids, ip_limit=ip_limit)
    
    if is_ready_package:
        update_order(order_id, 
                    category_id=category_id,
                    category_name=category_name,
                    category_name_en=category_name_en,
                    package_id=package_id)
    
    if is_extend and extend_order_id:
        update_order(order_id, parent_order_id=extend_order_id, is_extend=True)
        logger.info(f"🔄 [pay_balance] Order #{order_id} for renewal of order #{extend_order_id} set")
    
    logger.info(f"[pay_balance] payment method: {'account balance' if final_price > 0 else 'free (coupon)'}")
    logger.info(f"📡 [pay_balance] inbounds: {inbound_ids}")
    logger.info(f"[pay_balance] IP limit: {ip_limit if ip_limit > 0 else 'unlimited'}")
    
    # ============================================
    # ✅ پردازش تمدید
    # ============================================
    if is_extend and extend_order_id:
        logger.info(f"🔄 [pay_balance] Starting renewal for order #{extend_order_id}")
        parent_order = orders.get(str(extend_order_id))
        if not parent_order:
            logger.error(f"❌ [pay_balance] Original order #{extend_order_id} not found")
            if final_price > 0:
                update_user(user_id, 'balance', balance)
                if log_system:
                    await log_system.log_balance_change(
                        user_id=user_id,
                        amount=final_price,
                        new_balance=balance,
                        action="add",
                        admin_id=None,
                        details="Balance refunded because the original renewal order was not found"
                    )
            await callback.message.edit_text(
                t('error_original_order_not_fou_2e42225077', lang),
                reply_markup=get_back_only_keyboard(lang)
            )
            return
        
        # ✅ استخراج اطلاعات کتگوری از state
        _state = user_states.get(user_id, {})
        _cat_id = _state.get('category_id') or full_state.get('category_id')
        _cat_name = _state.get('category_name') or full_state.get('category_name')
        _cat_name_en = _state.get('category_name_en') or full_state.get('category_name_en')
        _pkg_id = _state.get('package_id') or full_state.get('package_id')

        success = await extend_service(
            extend_order_id, 
            user_id, 
            vol, 
            days,
            inbound_ids,
            ip_limit,
            new_category_id=_cat_id,
            new_category_name=_cat_name,
            new_category_name_en=_cat_name_en,
            new_package_id=_pkg_id,
        )
        
        if success:
            # ✅ آپدیت سفارش موجود با اطلاعات موفقیت
            update_order(order_id, 
                        status='approved',
                        approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"))
            
            if final_price > 0:
                update_order(order_id, 
                            payment_method='balance_extend',
                            payment_label='🔄 موجودی (تمدید)')
            else:
                update_order(order_id, 
                            payment_method='free_coupon_extend',
                            payment_label='🎁 رایگان (تمدید)')
            
            record_purchase(user_id, final_price)
            consume_coupon(user_id)
            
            # پاکسازی state
            if user_id in user_states:
                user_states[user_id].pop('is_extend', None)
                user_states[user_id].pop('extend_order_id', None)
                user_states[user_id].pop('current_volume', None)
                user_states[user_id].pop('current_days', None)
                user_states[user_id].pop('is_ready_package', None)
                user_states[user_id].pop('inbound_ids', None)
                user_states[user_id].pop('ip_limit', None)
            
            updated_parent = orders.get(str(extend_order_id))
            new_volume = updated_parent.get('volume', 0) if updated_parent else current_volume + vol
            new_days = updated_parent.get('days', 0) if updated_parent else current_days + days
            
            payment_label = '🔄 موجودی (تمدید)' if final_price > 0 else '🎁 رایگان (تمدید)'
            payment_emoji = '🔄💰' if final_price > 0 else '🎁🔄'
            payment_type = 'balance_extend' if final_price > 0 else 'free_extend'
            
            await send_admin_notification('extend', {
                'user_id': user_id,
                'volume': vol,
                'days': days,
                'price': final_price,
                'discount_percent': discount_percent,
                'balance_before': balance,
                'balance_after': new_balance,
                'order_id': order_id,
                'payment_type': payment_type,
                'payment_label': payment_label,
                'payment_emoji': payment_emoji,
                'is_extend': True,
                'parent_order_id': extend_order_id,
                'old_volume': current_volume,
                'old_days': current_days,
                'new_volume': new_volume,
                'new_days': new_days,
                'category_name': category_name,
                'inbound_ids': inbound_ids,
                'ip_limit': ip_limit
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
                    t('b_service_extended_successfu_cb17d8e70b', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f'{RLM}', f'{extend_order_id}', f'{vol_line}', f'{RLM}', f'{days}', f'{RLM}', f'{final_price:,}'))
                )
            else:
                vol_line = t('b_traffic_b_unlimited_e5a9561386', lang) if vol == 0 else t('b_added_volume_b_gb_7f1d65c8dd', lang, en_parts=lambda: (f'{vol}',))
                text = (
                    t('b_service_extended_successfu_cb17d8e70b', lang, en_parts=lambda: (f'{extend_order_id}', f'{vol_line}', f'{days}', f'{final_price:,}'))
                )
            
            await callback.message.answer(
                text, 
                parse_mode=ParseMode.HTML, 
                reply_markup=get_extension_success_keyboard(extend_order_id, lang)
            )
            logger.info(f"✅ [pay_balance] Renewal for user {user_id} - order #{order_id}")
            await callback.answer(t('service_extended_36fc3cd187', lang))
            debug_coupon_state(user_id, "pay_balance_end")
            return
        else:
            # ✅ برگشت موجودی در صورت خطا
            if final_price > 0:
                update_user(user_id, 'balance', balance)
                if log_system:
                    await log_system.log_balance_change(
                        user_id=user_id,
                        amount=final_price,
                        new_balance=balance,
                        action="add",
                        admin_id=None,
                        details="Balance refunded because service renewal failed"
                    )
            error_msg = t('error_extending_service_bala_bddeee9e65', lang)
            await callback.message.edit_text(
                f"{premium_emoji('danger', '❌')} {error_msg}",
                reply_markup=get_back_only_keyboard(lang)
            )
            return
    
    # ============================================
    # ✅ پردازش خرید عادی (غیر تمدید)
    # ============================================
    await callback.message.edit_text(t('i18n_creating_config', lang))
    
    timestamp = int(datetime.now().timestamp())
    email = f"user{user_id}_{timestamp}"
    user_name = user.get('name', f'کاربر_{user_id}')
    
    # ✅ انتخاب اینباند مناسب
    if is_ready_package and inbound_ids:
        inbound_to_use = inbound_ids
        logger.info(f"📡 [pay_balance] Using package inbounds: {inbound_ids}")
    else:
        inbound_to_use = get_user_inbound(user_id)
        logger.info(f"📡 [pay_balance] Using default inbound: {inbound_to_use}")
    
    # ✅ تلاش برای ساخت کانفیگ
    sub_link = None
    config_id = None
    
    if is_senai_panel_enabled():
        # حالت پنل فعال - ساخت مستقیم کلاینت
        try:
            if is_ready_package and inbound_ids:
                sub_link = await xui_create_client_with_inbound(email, vol, days, user_name, user_id, inbound_ids, ip_limit=ip_limit)
                logger.info(f"📡 [pay_balance] Using package inbounds: {inbound_ids}")
            else:
                sub_link = await create_client_in_panel(user_id, email, vol, days, user_name)
        except Exception as e:
            logger.error(f"❌ [pay_balance] Error creating panel client: {e}")
            sub_link = None
    else:
        # حالت پنل غیرفعال - استفاده از مخزن کانفیگ
        try:
            config = await get_config_from_pool_safe(vol, days)
            if config:
                sub_link = config['link']
                config_id = config.get('id')
                logger.info('📦 [pay_balance] Config retrieved from repository')
        except Exception as e:
            logger.error(f"❌ [pay_balance] Error retrieving from repository: {e}")
            sub_link = None
    
    if sub_link:
        # ✅ آپدیت سفارش موجود با اطلاعات موفقیت
        update_order(order_id, 
                    status='approved',
                    approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
                    config_link=sub_link, 
                    sub_link=sub_link, 
                    email=email)
        
        if config_id:
            update_order(order_id, config_id=config_id)
        
        if final_price > 0:
            if is_senai_panel_enabled():
                update_order(order_id, 
                            payment_method='balance',
                            payment_label='💰 موجودی حساب')
            else:
                update_order(order_id, 
                            payment_method='balance_pool',
                            payment_label='💰 موجودی حساب (مخزن)')
        else:
            update_order(order_id, 
                        payment_method='free_coupon',
                        payment_label='🎁 رایگان (کوپن)')
        
        record_purchase(user_id, final_price)
        consume_coupon(user_id)
        
        if final_price > 0:
            referral_result = await check_referral_bonus(user_id)
            if referral_result:
                logger.info(f"✅ [pay_balance] Referral reward for user {user_id} applied")
        
        if log_system:
            await log_system.log_config_created(user_id, order_id, email, vol, days)
            await log_system.log_purchase(user_id, order_id, vol, days, final_price, "Balance" if final_price > 0 else "Free")
        
        payment_type = 'balance' if final_price > 0 else 'free'
        payment_label = '💰 موجودی حساب' if final_price > 0 else '🎁 رایگان (کوپن)'
        payment_emoji = '💰' if final_price > 0 else '🎁'
        
        await send_admin_notification('balance', {
            'user_id': user_id,
            'volume': vol,
            'days': days,
            'price': final_price,
            'discount_percent': discount_percent,
            'balance_before': balance,
            'balance_after': new_balance,
            'order_id': order_id,
            'payment_type': payment_type,
            'payment_label': payment_label,
            'payment_emoji': payment_emoji,
            'inbound_ids': inbound_ids,
            'ip_limit': ip_limit
        })
        
        try:
            await callback.message.delete()
        except Exception:
            pass
        
        await send_config_with_qr_option(user_id, order_id, vol, days, final_price, sub_link, lang)
        
        if final_price > 0:
            await callback.message.answer(
                f"{premium_emoji('star', '⭐')} {t('please_rate_396db52377', lang)}",
                reply_markup=get_feedback_keyboard(order_id, lang)
            )
        
        # پاکسازی state
        if user_id in user_states:
            user_states[user_id].pop('is_ready_package', None)
            user_states[user_id].pop('price', None)
            user_states[user_id].pop('inbound_id', None)
            user_states[user_id].pop('inbound_ids', None)
            user_states[user_id].pop('ip_limit', None)
            user_states[user_id].pop('coupon_code', None)
            user_states[user_id].pop('coupon_applied', None)
            user_states[user_id].pop('coupon_discount', None)
        
        volume_display_text = format_package_volume(vol, lang)
        if is_ready_package:
            category_display_final = f"{category_display} - "
        else:
            category_display_final = ""        
        text = t('b_service_activated_successf_81448e3f2f', lang, fa_parts=lambda: (f'{category_display_final}', f'{volume_display_text}', f'{days}', f'{payment_label}', f'{final_price:,}'), en_parts=lambda: (f'{category_display_final}', f'{volume_display_text}', f'{days}', f'{payment_label}', f'{final_price:,}'))
        
        logger.info(f"✅ [pay_balance] Successful purchase by user {user_id} - order #{order_id} - Volume: {volume_display_text} - amount: {final_price:,}tomans")
        
    else:
        # ✅ خطا در ساخت کانفیگ - برگشت موجودی
        if final_price > 0:
            update_user(user_id, 'balance', balance)
            if log_system:
                await log_system.log_balance_change(
                    user_id=user_id,
                    amount=final_price,
                    new_balance=balance,
                    action="add",
                    admin_id=None,
                    details="Balance refunded because configuration creation failed"
                )
        
        error_msg = t('error_creating_config_balanc_047d0dbebe', lang)
        
        await callback.message.edit_text(
            f"{premium_emoji('danger', '❌')} {error_msg}",
            reply_markup=get_back_only_keyboard(lang)
        )
        
        if log_system:
            await log_system.log_error(
                Exception("Failed to create client"), 
                "pay_balance_create_client", 
                user_id
            )
        
        logger.error(f"❌ [pay_balance] Error creating client for user {user_id}")
    
    debug_coupon_state(user_id, "pay_balance_end")
    
    await safe_answer(callback)
    return


@router.callback_query(F.data.startswith("send_config_"))
@admin_only
async def send_config_to_user(callback: CallbackQuery):

    lang = get_user(callback.from_user.id).get('lang', 'fa')
    order_id = int(callback.data.split("_")[2])
    order = orders.get(str(order_id))
    if not order:
        return await callback.answer("❌", show_alert=True)
    
    user_states[callback.from_user.id] = {
        'awaiting_config': True,
        'order_id': order_id,
        'user_id': order['user_id'],
        'volume': order['volume'],
        'days': order['days'],
        'price': order['price']
    }
    
    await callback.message.edit_text(
        t('i18n_send_config_for_order_prompt', lang, fa_parts=lambda: (f'{order_id}', f"{order['user_id']}", f"{order['volume']}", f"{order['days']}"), en_parts=lambda: (f'{order_id}', f"{order['user_id']}", f"{order['volume']}", f"{order['days']}")),
        parse_mode=ParseMode.HTML
    )
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_config'))
async def admin_get_config(message: Message):
    state = user_states.get(message.from_user.id, {})
    
    order_id = state.get('order_id')
    user_id = state.get('user_id')
    volume = state.get('volume')
    days = state.get('days')
    price = state.get('price')
    config_link = message.text.strip()
    lang = get_user(user_id).get('lang', 'fa')
    
    update_order(order_id, status='approved', config_link=config_link,
                 approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"))
    record_purchase(user_id, price)
    await check_referral_bonus(user_id)
    
    await send_config_with_qr_option(user_id, order_id, volume, days, price, config_link, lang)
    
    try:
        await bot.send_message(
            user_id,
            f"{premium_emoji('star', '⭐')} {t('please_rate_our_service_e52df3f954', lang)}",
            reply_markup=get_feedback_keyboard(order_id, lang)
        )
    except Exception as e:
        logger.error(f"Error sending feedback request: {e}")
    
    await message.reply(t('i18n_config_sent_short', get_user(message.from_user.id).get('lang', 'fa'), fa_parts=lambda: (f'{order_id}',), en_parts=lambda: (f'{order_id}',)))
    user_states.pop(message.from_user.id, None)
@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery):
    """لغو پرداخت - کوپن باقی می‌ماند"""
    user_id = callback.from_user.id
    save_coupon_to_user_db(user_id)
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    is_admin = (user_id == ADMIN_ID_INT)
    
    logger.info(f"User {user_id} cancelled payment - previous status: {user_states.get(user_id, 'No state')}")
    user_state = user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied')
    
    pending_order = find_pending_order(user_id)
    if pending_order:
        if pending_order.get('status') == 'pending' or pending_order.get('status') == 'pending_balance_charge':
            await callback.answer(t('your_receipt_has_been_submit_b33f0d8949', lang), show_alert=True)
            return
        
        if pending_order.get('status') == 'awaiting_payment':
            update_order(pending_order['order_id'], status='cancelled')
            logger.info(f"Order #{pending_order['order_id']} cancelled")
            
            if log_system:
                await log_system.log_user_action(
                    user_id,
                    "Cancelled payment",
                    f"Order #{pending_order['order_id']} was cancelled"
                )
            
            await callback.answer(t('payment_cancelled_6a44050712', lang), show_alert=True)
    if user_id in user_states:
        user_states.pop(user_id, None)
    if coupon_applied and coupon_code:
        user_states[user_id] = {
            'coupon_code': coupon_code,
            'coupon_discount': coupon_discount,
            'coupon_applied': True
        }
        logger.info(f"🏷️ coupon {coupon_code} for user {user_id} preserved in cancel_payment")
    
    has_real_coupon = bool(coupon_applied and coupon_code)
    
    text = (
        t('payment_cancelled_54c880919a', lang, fa_parts=lambda: (f"{premium_emoji('danger', '❌')}",), en_parts=lambda: (f"{premium_emoji('danger', '❌')}",))
    )

    
    await callback.message.edit_text(text, reply_markup=get_main_keyboard(is_admin, lang, user_id))
    await safe_answer(callback)
        
        


@router.callback_query(F.data == "retry_receipt")
async def retry_receipt(callback: CallbackQuery):
    """تلاش مجدد برای ارسال فیش - با استایل یکپارچه"""
    user_id = callback.from_user.id
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    
    full_state = user_states.get(user_id, {})
    coupon_code = full_state.get('coupon_code')
    coupon_discount = full_state.get('coupon_discount')
    coupon_applied = full_state.get('coupon_applied', False)
    
    pending_order = find_pending_order(user_id)
    if not pending_order:
        await callback.answer(t('no_order_found_0a02e99eb6', lang), show_alert=True)
        return
    
    user_states[user_id] = {
        'awaiting_receipt': True,
        'current_order_id': pending_order['order_id'],
        'timestamp': now_tehran_iso()
    }
    
    if coupon_applied and coupon_code:
        user_states[user_id]['coupon_code'] = coupon_code
        user_states[user_id]['coupon_applied'] = True
        user_states[user_id]['coupon_discount'] = coupon_discount if coupon_discount else 0
    
    text = build_receipt_text(pending_order, lang, mode="reminder")
    
    cancel_btn = t('cancel_4197bafba5', lang)
    
    await callback.message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=cancel_btn, callback_data=f"cancel_order_{pending_order['order_id']}", style="danger")]
        ])
    )
    
    await safe_answer(callback)


    
async def get_user_display_name(user_id: int) -> str:
    """دریافت نام نمایشی کاربر با اولویت یوزرنیم
    
    Args:
        user_id: آیدی کاربر
        
    Returns:
        نام نمایشی کاربر (یوزرنیم یا نام + آیدی)
    """
    try:
        user = get_user(user_id)
        username = user.get('username') or user.get('telegram_username')
        
        if username:
            return f"@{html.escape(username)}"
        chat = await bot.get_chat(user_id)
        if chat.username:
            update_user(user_id, 'username', chat.username)
            update_user(user_id, 'telegram_username', chat.username)
            return f"@{html.escape(chat.username)}"
        name = chat.first_name or chat.last_name or f"کاربر_{user_id}"
        if chat.last_name:
            name = f"{chat.first_name} {chat.last_name}"
        name_escaped = html.escape(name)
        return f"{name_escaped} (ID: {user_id})"
        
    except Exception as e:
        logger.error(f"Error retrieving username for user {user_id}: {e}")
        user = get_user(user_id)
        name = user.get('name', f"کاربر_{user_id}")
        name_escaped = html.escape(name)
        return f"{name_escaped} (ID: {user_id})"
@router.message(F.photo)
async def handle_receipt(message: Message):
    """دریافت فیش واریزی - با تشخیص کامل تمدید و نوع پرداخت"""
    user_id = message.from_user.id
    
    user_state = user_states.get(user_id, {})
    if user_state.get('awaiting_chat'):
        await handle_chat_message(message)
        return
    if user_id == ADMIN_ID_INT and user_state.get('awaiting_chat_reply'):
        await admin_chat_reply(message)
        return
    if not user_state.get('awaiting_receipt'):
        logger.debug(f"User {user_id} sent a photo but is not in awaiting_receipt state")
        return
    
    if user_id in BLACKLIST:
        logger.warning(f"⛔ blocked user {user_id} attempted to send a receipt")
        await message.reply(
            "⛔ <b>دسترسی مسدود شده</b>\n\nشما در لیست سیاه قرار دارید و امکان استفاده از ربات را ندارید.",
            parse_mode=ParseMode.HTML
        )
        if user_id in user_states:
            user_states.pop(user_id, None)
        return
    
    lang = get_user(user_id).get('lang', 'fa')
    
    try:
        photo_id = message.photo[-1].file_id
    except Exception:
        await message.reply(t('error_9eed101558', lang))
        return
    
    valid_orders = get_valid_orders()
    pending_orders = []
    for o in valid_orders.values():
        if o.get('user_id') == user_id and o.get('status') == 'awaiting_payment':
            pending_orders.append(o)
    
    if not pending_orders:
        await message.reply(t('no_order_found_0a02e99eb6', lang),
                           reply_markup=get_back_only_keyboard(lang))
        if user_id in user_states:
            user_states[user_id]['awaiting_receipt'] = False
        return
    
    pending_orders.sort(key=lambda x: x.get('created_at', x.get('date', '')), reverse=True)
    pending = pending_orders[0]
    order_id = pending['order_id']
    
    if len(pending_orders) > 1:
        old_orders = pending_orders[1:]
        for old_o in old_orders:
            old_id = old_o.get('order_id')
            update_order(old_id, status='cancelled')
            logger.info(f"🗑 Old order #{old_id} was canceled because a newer order exists")
        
        try:
            old_ids = [str(o.get('order_id')) for o in old_orders]
            await bot.send_message(
                user_id,
                t('your_old_orders_have_been_ex_8782dbdfc3', lang, fa_parts=lambda: (f"{premium_emoji('reload', '🔄')}", f"{', '.join(old_ids)}", f"{premium_emoji('success', '✅')}", f'{order_id}'), en_parts=lambda: (f"{premium_emoji('reload', '🔄')}", f"{', '.join(old_ids)}", f"{premium_emoji('success', '✅')}", f'{order_id}'))
            )
        except Exception:
            pass
    
    order_type = pending.get('type', 'purchase')
    parent_order_id = pending.get('parent_order_id')
    is_extend = parent_order_id is not None
    
    if order_type == 'balance_charge':
        new_status = 'pending_balance_charge'
    else:
        new_status = 'pending'
    
    update_order(order_id, receipt_photo_id=photo_id, status=new_status, payment_method=pending.get('payment_method') or 'card')
    
    logger.info(f"📸 receipt for order #{order_id} received - new status: {new_status}")
    if is_extend:
        logger.info(f"🔄 This order is for renewing service #{parent_order_id} is")
    
    # ✅ تعریف همه متغیرها با مقادیر امن
    order_price = pending.get('price', 0) or 0
    order_amount = pending.get('amount', 0) or 0
    order_volume = pending.get('volume', 0) or 0
    order_days = pending.get('days', 0) or 0
    
    # ✅ محاسبه expected_price
    expected_price = order_price if order_price > 0 else order_amount
    
    category_name = pending.get('category_name') or ''
    category_id = pending.get('category_id')
    package_id = pending.get('package_id')
    
    # ✅ اطلاعات بیشتر برای نمایش
    payment_method = pending.get('payment_method', '') or ''
    payment_label = pending.get('payment_label', '') or ''
    ip_limit = pending.get('ip_limit', 0) or 0
    inbound_ids = pending.get('inbound_id', []) or []
    
    # ✅ اطلاعات کوپن - با مقادیر امن
    coupon_code = pending.get('coupon_code') or ''
    coupon_discount = pending.get('coupon_discount', 0) or 0
    original_price = pending.get('original_price', 0) or 0
    
    # ✅ اطلاعات کاربر - امن
    user_display_name = message.from_user.first_name or ""
    user_username = message.from_user.username
    user_last_name = message.from_user.last_name or ""
    
    # ✅ دریافت نام از دیتابیس
    user_db = get_user(user_id)
    db_name = user_db.get('name', '') if user_db else ''
    
    # ✅ ساخت نام کامل
    telegram_full_name = ""
    if user_display_name:
        telegram_full_name = user_display_name
        if user_last_name:
            telegram_full_name += f" {user_last_name}"
    
    # ✅ انتخاب بهترین نام
    if db_name and db_name.strip() and not db_name.startswith('کاربر_'):
        display_name = db_name.strip()
    elif telegram_full_name and telegram_full_name.strip():
        display_name = telegram_full_name.strip()
    else:
        display_name = f'کاربر_{user_id}'
    
    # ✅ ساخت نمایش امن
    if user_username:
        user_display = f"@{html.escape(user_username)} ({html.escape(display_name)})"
    else:
        user_display = f"{html.escape(display_name)} (ID: {user_id})"
    
    date_escaped = html.escape(str(pending.get('date', 'نامشخص')))
    
    category_icon = "📦"
    if category_id:
        for cat in READY_PACKAGES.get('categories', []):
            if cat.get('id') == category_id:
                category_icon = cat.get('icon', '📦')
                break
    
    # ✅ ساخت متن ادمین
    admin_text = "💰 <b>فیش جدید</b>\n"
    admin_text += f"🆔 #{order_id} | 👤 {user_display}\n"
    admin_text += f"📅 {date_escaped}\n"
    admin_text += "━━━━━━━━━━━━━━━━━━━━━━\n"
    
    # ✅ نوع سفارش
    if is_extend:
        admin_text += f"🔄 <b>نوع: تمدید سرویس #{parent_order_id}</b>\n"
        
        parent_order = orders.get(str(parent_order_id))
        if parent_order:
            parent_volume = parent_order.get('volume', 0) or 0
            parent_days = parent_order.get('days', 0) or 0
            parent_email = parent_order.get('email', '') or ''
            
            parent_volume_display = "♾️ نامحدود" if parent_volume == 0 else f"{parent_volume}GB"
            
            admin_text += f"📦 <b>سرویس قبلی:</b> {parent_volume_display} | {parent_days} روز\n"
            
            if parent_email:
                admin_text += f"📧 <b>ایمیل:</b> <code>{html.escape(parent_email)}</code>\n"
            
            admin_text += "━━━━━━━━━━━━━━━━━━━━━━\n"
            
            if order_volume == 0:
                admin_text += "📦 <b>حجم اضافه:</b> ♾️ نامحدود\n"
            else:
                admin_text += f"📦 <b>حجم اضافه:</b> {order_volume}GB\n"
            
            admin_text += f"⏱ <b>روز اضافه:</b> {order_days} روز\n"
            
            if order_volume == 0:
                new_volume = 0
            else:
                new_volume = parent_volume + order_volume
            new_days = parent_days + order_days
            
            new_volume_display = "♾️ نامحدود" if new_volume == 0 else f"{new_volume}GB"
            admin_text += f"📊 <b>نتیجه:</b> {parent_volume_display} → {new_volume_display} | {parent_days} → {new_days} روز\n"
            
    elif order_type == 'balance_charge':
        admin_text += "💰 <b>نوع: شارژ حساب</b>\n"
        admin_text += f"💳 <b>مبلغ شارژ:</b> {expected_price:,} تومان\n"
        
    elif order_type in ['ready_package', 'category_purchase']:
        category_name_display = category_name or "بسته آماده"
        category_name_escaped = html.escape(category_name_display)
        
        admin_text += f"{category_icon} <b>نوع: بسته آماده - {category_name_escaped}</b>\n"
        admin_text += "━━━━━━━━━━━━━━━━━━━━━━\n"
        
        package_found = False
        if category_id and package_id:
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('id') == category_id:
                    for pkg in cat.get('packages', []):
                        if pkg.get('id') == package_id:
                            pkg_volume = pkg.get('volume', 0) or 0
                            pkg_days = pkg.get('days', 0) or 0
                            pkg_price = pkg.get('price', 0) or 0
                            
                            pkg_volume_display = "♾️ نامحدود" if pkg_volume == 0 else f"{pkg_volume}GB"
                            admin_text += f"📦 <b>حجم:</b> {pkg_volume_display}\n"
                            admin_text += f"⏱ <b>مدت:</b> {pkg_days} روز\n"
                            admin_text += f"💰 <b>قیمت اصلی:</b> {pkg_price:,} تومان\n"
                            package_found = True
                            break
                    break
        
        if not package_found:
            volume_display = "♾️ نامحدود" if order_volume == 0 else f"{order_volume}GB"
            admin_text += f"📦 <b>حجم:</b> {volume_display}\n"
            admin_text += f"⏱ <b>مدت:</b> {order_days} روز\n"
            if expected_price > 0:
                admin_text += f"💰 <b>قیمت:</b> {expected_price:,} تومان\n"
        
        has_discount = coupon_discount > 0 or (original_price > 0 and original_price != expected_price)
        if has_discount:
            admin_text += "━━━━━━━━━━━━━━━━━━━━━━\n"
            admin_text += "🏷️ <b>کوپن تخفیف:</b>\n"
            
            if coupon_code:
                admin_text += f"🎟 <b>کد:</b> <code>{html.escape(coupon_code)}</code>\n"
            
            if coupon_discount > 0:
                admin_text += f"📊 <b>درصد تخفیف:</b> {coupon_discount}%\n"
            
            if original_price > 0:
                admin_text += f"💰 <b>قیمت اصلی:</b> {original_price:,} تومان\n"
                admin_text += f"💎 <b>قیمت با تخفیف:</b> {expected_price:,} تومان\n"
                
                discount_amount = original_price - expected_price
                if discount_amount > 0:
                    admin_text += f"🔻 <b>مبلغ تخفیف:</b> {discount_amount:,} تومان\n"
            elif coupon_discount > 0 and expected_price > 0:
                try:
                    calculated_original = int(expected_price * 100 / (100 - coupon_discount))
                    admin_text += f"💰 <b>قیمت اصلی:</b> {calculated_original:,} تومان\n"
                    admin_text += f"💎 <b>قیمت با تخفیف:</b> {expected_price:,} تومان\n"
                    
                    discount_amount = calculated_original - expected_price
                    if discount_amount > 0:
                        admin_text += f"🔻 <b>مبلغ تخفیف:</b> {discount_amount:,} تومان\n"
                except ZeroDivisionError:
                    pass
        
    elif order_type == 'purchase':
        admin_text += "🛒 <b>نوع: خرید سفارشی</b>\n"
        admin_text += "━━━━━━━━━━━━━━━━━━━━━━\n"
        volume_display = "♾️ نامحدود" if order_volume == 0 else f"{order_volume}GB"
        admin_text += f"📦 <b>حجم:</b> {volume_display}\n"
        admin_text += f"⏱ <b>مدت:</b> {order_days} روز\n"
        
        has_discount = coupon_discount > 0 or (original_price > 0 and original_price != expected_price)
        if has_discount:
            admin_text += "━━━━━━━━━━━━━━━━━━━━━━\n"
            admin_text += "🏷️ <b>کوپن تخفیف:</b>\n"
            
            if coupon_code:
                admin_text += f"🎟 <b>کد:</b> <code>{html.escape(coupon_code)}</code>\n"
            
            if coupon_discount > 0:
                admin_text += f"📊 <b>درصد تخفیف:</b> {coupon_discount}%\n"
            
            if original_price > 0:
                admin_text += f"💰 <b>قیمت اصلی:</b> {original_price:,} تومان\n"
                admin_text += f"💎 <b>قیمت با تخفیف:</b> {expected_price:,} تومان\n"
                
                discount_amount = original_price - expected_price
                if discount_amount > 0:
                    admin_text += f"🔻 <b>مبلغ تخفیف:</b> {discount_amount:,} تومان\n"
            elif coupon_discount > 0 and expected_price > 0:
                try:
                    calculated_original = int(expected_price * 100 / (100 - coupon_discount))
                    admin_text += f"💰 <b>قیمت اصلی:</b> {calculated_original:,} تومان\n"
                    admin_text += f"💎 <b>قیمت با تخفیف:</b> {expected_price:,} تومان\n"
                    
                    discount_amount = calculated_original - expected_price
                    if discount_amount > 0:
                        admin_text += f"🔻 <b>مبلغ تخفیف:</b> {discount_amount:,} تومان\n"
                except ZeroDivisionError:
                    pass
        
    elif order_type == 'test':
        admin_text += "🧪 <b>نوع: تست رایگان</b>\n"
        admin_text += "━━━━━━━━━━━━━━━━━━━━━━\n"
        if order_volume < 1:
            volume_display = f"{order_volume * 1024:.1f}MB"
        else:
            volume_display = f"{order_volume}GB"
        admin_text += f"📦 <b>حجم:</b> {volume_display}\n"
        admin_text += f"⏱ <b>مدت:</b> {order_days} روز\n"
    else:
        admin_text += f"⚠️ <b>نوع: {html.escape(str(order_type))}</b>\n"
    
    # ✅ اطلاعات پرداخت
    if order_type != 'balance_charge':
        admin_text += "━━━━━━━━━━━━━━━━━━━━━━\n"
        
        has_discount = coupon_discount > 0 or (original_price > 0 and original_price != expected_price)
        if has_discount:
            admin_text += f"💎 <b>مبلغ نهایی (با تخفیف):</b> {expected_price:,} تومان\n"
        else:
            admin_text += f"💰 <b>مبلغ مورد انتظار:</b> {expected_price:,} تومان\n"
        
        if payment_label:
            admin_text += f"💳 <b>روش پرداخت:</b> {html.escape(payment_label)}\n"
        elif payment_method:
            payment_method_display = {
                'card': '💳 کارت به کارت',
                'balance': '💰 موجودی حساب',
                'balance_extend': '🔄 موجودی (تمدید)',
                'free_coupon': '🎁 رایگان (کوپن)',
                'free_coupon_extend': '🎁 رایگان (تمدید)',
                'sync_from_panel': '🔄 همگام‌سازی',
            }.get(payment_method, str(payment_method))
            admin_text += f"💳 <b>روش پرداخت:</b> {html.escape(payment_method_display)}\n"
        
        if ip_limit > 0:
            admin_text += f"👤 <b>محدودیت IP:</b> {ip_limit}\n"
        else:
            admin_text += "👤 <b>محدودیت IP:</b> نامحدود\n"
        
        if inbound_ids:
            if isinstance(inbound_ids, list):
                inbound_display = ', '.join(str(ib) for ib in inbound_ids if ib)
            else:
                inbound_display = str(inbound_ids)
            
            if inbound_display and inbound_display != 'None':
                admin_text += f"📡 <b>اینباند:</b> {inbound_display}\n"
    else:
        admin_text += "━━━━━━━━━━━━━━━━━━━━━━\n"
        admin_text += f"💰 <b>مبلغ شارژ:</b> {expected_price:,} تومان\n"
    
    admin_text += "━━━━━━━━━━━━━━━━━━━━━━\n"
    admin_text += "⏳ <b>در انتظار تایید</b>"
    
    admin_lang = get_user(ADMIN_ID_INT).get('lang', 'fa')
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t('approve_8e35ad3e33', admin_lang), callback_data=f"approve_receipt_{order_id}"),
            InlineKeyboardButton(text=t('custom_payment_36f7f89c87', admin_lang), callback_data=f"custom_payment_receipt_{order_id}")
        ],
        [
            InlineKeyboardButton(text=t('reject_6ed3999c19', admin_lang), callback_data=f"reject_receipt_{order_id}")
        ],
        [InlineKeyboardButton(text=t('i18n_back_close', admin_lang), callback_data="admin_close_msg")]
    ])
    
    try:
        await bot.send_photo(ADMIN_ID_INT, photo_id, caption=admin_text, parse_mode=ParseMode.HTML, reply_markup=admin_kb)
    except Exception as e:
        logger.error(f"Error sending receipt to admin: {e}")
        try:
            await bot.send_message(ADMIN_ID_INT, admin_text, parse_mode=ParseMode.HTML, reply_markup=admin_kb)
            await bot.send_photo(ADMIN_ID_INT, photo_id)
        except Exception as e2:
            logger.error(f"Error sending receipt to admin (second attempt): {e2}")
    
    # ✅ پیام به کاربر - بدون نمایش مبلغ
    if is_extend:
        success = t('b_extension_receipt_received_456c787127', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}",), en_parts=lambda: (f"{premium_emoji('success', '✅')}",))
        success += t('order_number_d0c5838dda', lang, fa_parts=lambda: (f"{premium_emoji('id', '🆔')}", f'{order_id}'), en_parts=lambda: (f"{premium_emoji('id', '🆔')}", f'{order_id}'))
        success += t('extending_service_c2ea7f5943', lang, fa_parts=lambda: (f'{parent_order_id}',), en_parts=lambda: (f'{parent_order_id}',))
        success += t('pending_approval_38c828600e', lang, fa_parts=lambda: (f"{premium_emoji('time', '⏳')}",), en_parts=lambda: (f"{premium_emoji('time', '⏳')}",))
    
    elif order_type == 'balance_charge':
        success = t('b_balance_charge_receipt_rec_896a988ac4', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}",), en_parts=lambda: (f"{premium_emoji('success', '✅')}",))
        success += t('order_number_d0c5838dda', lang, fa_parts=lambda: (f"{premium_emoji('id', '🆔')}", f'{order_id}'), en_parts=lambda: (f"{premium_emoji('id', '🆔')}", f'{order_id}'))
        success += t('pending_approval_38c828600e', lang, fa_parts=lambda: (f"{premium_emoji('time', '⏳')}",), en_parts=lambda: (f"{premium_emoji('time', '⏳')}",))
    else:
        success = t('b_receipt_received_b_3a455da3ea', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}",), en_parts=lambda: (f"{premium_emoji('success', '✅')}",))
        success += t('order_number_d0c5838dda', lang, fa_parts=lambda: (f"{premium_emoji('id', '🆔')}", f'{order_id}'), en_parts=lambda: (f"{premium_emoji('id', '🆔')}", f'{order_id}'))
        success += t('pending_approval_38c828600e', lang, fa_parts=lambda: (f"{premium_emoji('time', '⏳')}",), en_parts=lambda: (f"{premium_emoji('time', '⏳')}",))
    
    receipt_status_message = await message.reply(success, parse_mode=ParseMode.HTML)
    update_order(
        order_id,
        receipt_status_chat_id=receipt_status_message.chat.id,
        receipt_status_message_id=receipt_status_message.message_id,
        receipt_status_lang=lang,
    )
    
    if user_id in user_states:
        user_states[user_id]['awaiting_receipt'] = False
    
    is_admin = (user_id == ADMIN_ID_INT)
    
    # ✅ اصلاح: استفاده از message.reply به جای message.answer
    try:
        await message.reply(
            t('main_menu_252f54e1f9', lang),
            reply_markup=get_main_keyboard(is_admin, lang, user_id)
        )
    except Exception as e:
        logger.warning(f"Error sending the main menu: {e}")
        try:
            await bot.send_message(
                user_id,
                t('main_menu_252f54e1f9', lang),
                reply_markup=get_main_keyboard(is_admin, lang, user_id)
            )
        except Exception as e2:
            logger.error(f"Error sending main menu (second attempt): {e2}")
            

async def custom_payment_receipt_amount(message: Message):
    """دریافت مبلغ دلخواه - با هشدار کم بودن مبلغ"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_8a3eb8aae6', lang))
        return
    
    state = user_states.get(admin_id, {})
    oid = state.get('custom_payment_receipt_order_id')
    user_id = state.get('custom_payment_receipt_user_id')
    
    if not oid or not user_id:
        user_states.pop(admin_id, None)
        await message.reply(t('error_order_not_found_7b52287a25', lang))
        return
    
    order = orders.get(str(oid))
    if not order:
        user_states.pop(admin_id, None)
        await message.reply(t('error_order_not_found_02a4630d64', lang))
        return
    
    try:
        amount = int(message.text.replace(',', '').replace(' ', '').strip())
        
        if amount <= 0:
            await message.reply(t('amount_must_be_greater_than_5a8ae6becf', lang))
            return
        order_type = order.get('type', 'purchase')
        expected_amount = 0
        
        if order_type == 'balance_charge':
            expected_amount = order.get('amount', 0)
        elif order_type in ['ready_package', 'category_purchase']:
            expected_amount = order.get('price', 0)
            if expected_amount == 0:
                category_id = order.get('category_id')
                package_id = order.get('package_id')
                if category_id and package_id:
                    for cat in READY_PACKAGES.get('categories', []):
                        if cat.get('id') == category_id:
                            for pkg in cat.get('packages', []):
                                if pkg.get('id') == package_id:
                                    expected_amount = pkg.get('price', 0)
                                    break
                            break
        else:
            expected_amount = order.get('price', 0)
        user_states[admin_id] = {
            'awaiting_custom_payment_receipt_confirm': True,
            'custom_payment_receipt_order_id': oid,
            'custom_payment_receipt_user_id': user_id,
            'custom_payment_receipt_amount': amount,
            'custom_payment_receipt_expected': expected_amount,  # ذخیره مبلغ واقعی
        }
        
        target_user = get_user(user_id)
        current_balance = target_user.get('balance', 0)
        new_balance = current_balance + amount
        user_name = html.escape(str(target_user.get('name', 'کاربر')))
        warning_text = ""
        if expected_amount > 0 and amount < expected_amount:
            diff = expected_amount - amount
            warning_text = f"""
⚠️ <b>هشدار: مبلغ کمتر از مبلغ درخواستی است!</b>
💰 مبلغ درخواستی: {expected_amount:,} تومان
💰 مبلغ واریز شده: {amount:,} تومان
💰 کمبود: {diff:,} تومان

💡 کاربر باید {diff:,} تومان دیگر واریز کند.
━━━━━━━━━━━━━━━━━━━━━━
"""
        elif expected_amount > 0 and amount == expected_amount:
            warning_text = """
✅ <b>مبلغ دقیقاً مطابق درخواست است!</b>
━━━━━━━━━━━━━━━━━━━━━━
"""
        elif expected_amount > 0 and amount > expected_amount:
            diff = amount - expected_amount
            warning_text = f"""
✅ <b>مبلغ بیشتر از مبلغ درخواستی است!</b>
💰 مبلغ درخواستی: {expected_amount:,} تومان
💰 مبلغ واریز شده: {amount:,} تومان
💰 اضافه: {diff:,} تومان (به موجودی اضافه می‌شود)
━━━━━━━━━━━━━━━━━━━━━━
"""
        
        text = t('b_confirm_balance_charge_ord_03de7b7c35', lang, fa_parts=lambda: (f'{oid}', f'{user_name}', f'{user_id}', f'{amount:,}', f'{expected_amount:,}', f'{current_balance:,}', f'{new_balance:,}', f'{warning_text}'), en_parts=lambda: (f'{oid}', f'{user_name}', f'{user_id}', f'{amount:,}', f'{expected_amount:,}', f'{current_balance:,}', f'{new_balance:,}', f'{warning_text}'))
        buttons = [
            [InlineKeyboardButton(text=t('yes_add_a6e9702995', lang), callback_data="custom_payment_receipt_confirm", style="success")],
            [InlineKeyboardButton(text=t('edit_amount_2c183814be', lang), callback_data=f"custom_payment_receipt_{oid}")],
            [InlineKeyboardButton(text=t('cancel_4197bafba5', lang), callback_data="admin_close_msg", style="danger")]
        ]
        try:
            await message.delete()
        except Exception:
            pass
        
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
        
    except ValueError:
        await message.reply(t('please_enter_a_valid_number_afbbd0c0b3', lang))
    except Exception as e:
        logger.error(f"Error in custom_payment_receipt_amount: {e}", exc_info=True)
        await message.reply(f"❌ خطا: {html.escape(type(e).__name__)}")
        user_states.pop(admin_id, None)

@router.callback_query(F.data == "custom_payment_receipt_confirm")
@admin_only
async def custom_payment_receipt_confirm(callback: CallbackQuery):
    """تأیید نهایی پرداخت دلخواه - فقط شارژ موجودی با توضیح کامل"""
    
    state = user_states.get(callback.from_user.id, {})
    oid = state.get('custom_payment_receipt_order_id')
    user_id = state.get('custom_payment_receipt_user_id')
    amount = state.get('custom_payment_receipt_amount')
    expected_amount = state.get('custom_payment_receipt_expected', 0)
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not user_id or not oid or not amount:
        await callback.answer(t('error_invalid_data_92bd58b5f5', lang), show_alert=True)
        return
    
    order = orders.get(str(oid))
    if not order:
        await callback.answer(t('order_not_found_075d800b08', lang), show_alert=True)
        return
    order_type = order.get('type', 'purchase')
    volume = order.get('volume', 0)
    days = order.get('days', 0)
    price = order.get('price', 0)
    category_name = order.get('category_name', '')
    if order_type in ['ready_package', 'category_purchase'] and price == 0:
        category_id = order.get('category_id')
        package_id = order.get('package_id')
        if category_id and package_id:
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('id') == category_id:
                    for pkg in cat.get('packages', []):
                        if pkg.get('id') == package_id:
                            price = pkg.get('price', 0)
                            volume = pkg.get('volume', 0)
                            days = pkg.get('days', 0)
                            break
                    break
    target_user = get_user(user_id)
    old_balance = target_user.get('balance', 0)
    new_balance = old_balance + amount
    update_order(oid, 
                status='approved', 
                payment_method='custom_payment_receipt',
                amount=amount,
                approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"))
    await update_user_receipt_review_status(order, 'approved')
    add_balance(user_id, amount)
    if log_system:
        await log_system.log_balance_change(
            user_id=user_id,
            amount=amount,
            new_balance=new_balance,
            action="add",
            admin_id=callback.from_user.id,
            details=f"Balance top-up through custom payment (order #{oid})"
        )
    if order_type in ['ready_package', 'category_purchase'] and category_name:
        order_desc = f"بسته آماده '{category_name}'"
    elif order_type == 'purchase':
        order_desc = f"سرویس سفارشی {volume}GB/{days} روز"
    elif order_type == 'balance_charge':
        order_desc = "شارژ حساب"
    else:
        order_desc = f"سفارش #{oid}"
    diff = 0
    diff_text = ""
    if expected_amount > 0:
        diff = amount - expected_amount
        if diff > 0:
            diff_text = f"\n {diff:,} تومان بیشتر از مبلغ درخواستی پرداخت کرده‌اید (به موجودی اضافه شد)"
        elif diff < 0:
            diff_text = f"\n {abs(diff):,} تومان کمتر از مبلغ درخواستی پرداخت کرده‌اید"
        else:
            diff_text = "\n مبلغ پرداختی دقیقاً برابر مبلغ درخواستی است"
    user_lang = target_user.get('lang', 'fa')
    
    user_text = t('b_your_balance_has_been_char_ae334ac71c', user_lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('money', '💰')}", f'{amount:,}', f"{premium_emoji('note', '📋')}", f'{order_desc}', f"""{(f"{premium_emoji('wallet', '💰')} مبلغ درخواستی سفارش: {expected_amount:,} تومان" if expected_amount > 0 else '')}""", f'{diff_text}', f"{premium_emoji('wallet', '💳')}", f'{new_balance:,}', f"{premium_emoji('light', '💡')}"), en_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('money', '💰')}", f'{amount:,}', f"{premium_emoji('note', '📋')}", f'{order_desc}', f"""{(f"{premium_emoji('wallet', '💰')} Order requested amount: {expected_amount:,} Toman" if expected_amount > 0 else '')}""", f'{diff_text}', f"{premium_emoji('wallet', '💳')}", f'{new_balance:,}', f"{premium_emoji('light', '💡')}"))
    
    try:
        await bot.send_message(user_id, user_text, parse_mode=ParseMode.HTML)
        logger.info(f"Balance top-up message to user {user_id} sent")
    except Exception as e:
        logger.error(f"Error sending message to user {user_id}: {e}")
    user_name = html.escape(str(target_user.get('name', 'کاربر')))
    
    success_text = t('b_balance_charge_completed_s_a42a978403', lang, fa_parts=lambda: (f'{oid}', f'{user_name}', f'{user_id}', f'{order_desc}', f'{amount:,}', f"{(f'💰 مبلغ درخواستی: {expected_amount:,} تومان' if expected_amount > 0 else '')}", f"{(f'💰 اختلاف: {diff:+,} تومان' if expected_amount > 0 else '')}", f'{old_balance:,}', f'{new_balance:,}'), en_parts=lambda: (f'{oid}', f'{user_name}', f'{user_id}', f'{order_desc}', f'{amount:,}', f"{(f'💰 Requested amount: {expected_amount:,} Toman' if expected_amount > 0 else '')}", f"{(f'💰 Difference: {diff:+,} Toman' if expected_amount > 0 else '')}", f'{old_balance:,}', f'{new_balance:,}'))
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await callback.message.answer(
        success_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('back_to_orders_d29b01f5a2', lang),
                callback_data="admin_orders"
            )],
            [InlineKeyboardButton(
                text=t('admin_panel_bf28b6b107', lang),
                callback_data="admin_panel"
            )]
        ]),
        parse_mode=ParseMode.HTML
    )
    user_states.pop(callback.from_user.id, None)
    
    logger.info(f"✅ added balance to user {user_id} - order #{oid} - amount: {amount:,}tomans")
    
    await safe_answer(callback, t('balance_charged_successfully_a540f53aa9', lang))



@router.callback_query(F.data == "custom_payment_receipt_manual")
@admin_only
async def custom_payment_receipt_manual(callback: CallbackQuery):
    """تنظیم دستی حجم و روز از پیام فیش - فقط برای سفارشات خرید"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    current_state = user_states.get(callback.from_user.id, {})
    oid = current_state.get('custom_payment_receipt_order_id')
    if oid:
        order = orders.get(str(oid))
        if order and order.get('type') != 'purchase':
            await callback.answer(t('this_order_cannot_be_manuall_5384149cee', lang), show_alert=True)
            return
    
    if not current_state.get('custom_payment_receipt_order_id') or not current_state.get('custom_payment_receipt_user_id'):
        await callback.answer(t('invalid_data_please_try_agai_3195dce2a0', lang), show_alert=True)
        return
    user_states[callback.from_user.id] = {
        'awaiting_custom_payment_receipt_manual_volume': True,
        'custom_payment_receipt_order_id': current_state.get('custom_payment_receipt_order_id'),
        'custom_payment_receipt_user_id': current_state.get('custom_payment_receipt_user_id'),
        'custom_payment_receipt_amount': current_state.get('custom_payment_receipt_amount')
    }
    
    await callback.message.edit_text(
        t('b_manual_service_setup_b_ple_c1d1eb2b3c', lang),
        parse_mode=ParseMode.HTML
    )
    await safe_answer(callback)



@router.callback_query(F.data.startswith("custom_payment_receipt_"))
@admin_only
async def custom_payment_receipt(callback: CallbackQuery):
    """پرداخت دلخواه - با نمایش مبلغ درخواستی"""
    
    try:
        oid = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_order_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    order = orders.get(str(oid))
    if not order:
        return await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
    
    user_id = order['user_id']
    order_type = order.get('type', 'purchase')
    expected_amount = 0
    
    if order_type == 'balance_charge':
        expected_amount = order.get('amount', 0)
    elif order_type in ['ready_package', 'category_purchase']:
        expected_amount = order.get('price', 0)
        if expected_amount == 0:
            category_id = order.get('category_id')
            package_id = order.get('package_id')
            if category_id and package_id:
                for cat in READY_PACKAGES.get('categories', []):
                    if cat.get('id') == category_id:
                        for pkg in cat.get('packages', []):
                            if pkg.get('id') == package_id:
                                expected_amount = pkg.get('price', 0)
                                update_order(oid, price=expected_amount)
                                break
                        break
    else:
        expected_amount = order.get('price', 0)
    user_states[callback.from_user.id] = {
        'awaiting_custom_payment_receipt_amount': True,
        'custom_payment_receipt_order_id': oid,
        'custom_payment_receipt_user_id': user_id,
        'custom_payment_receipt_type': order_type,
    }
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    if expected_amount > 0:
        text = t('b_custom_payment_order_b_use_f95ec48eee', lang, fa_parts=lambda: (f'{oid}', f'{user_id}', f'{expected_amount:,}', f'{expected_amount}'), en_parts=lambda: (f'{oid}', f'{user_id}', f'{expected_amount:,}', f'{expected_amount}'))
    else:
        text = t('b_custom_payment_order_b_use_9b42716ff6', lang, fa_parts=lambda: (f'{oid}', f'{user_id}'), en_parts=lambda: (f'{oid}', f'{user_id}'))
    
    buttons = [[InlineKeyboardButton(
        text=t('cancel_a82655b92b', lang),
        callback_data="admin_close_msg",
        style="danger"
    )]]
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await callback.message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    
    await safe_answer(callback)
       
    
@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_custom_payment_receipt_manual_volume'))
async def custom_payment_receipt_manual_volume(message: Message):
    """دریافت حجم دستی از پیام فیش"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_8a3eb8aae6', lang))
        return
    
    try:
        volume = int(message.text.strip())
        if volume < 1 or volume > 100:
            await message.reply(t('volume_must_be_between_1_and_aefa9c9c84', lang))
            return
        state = user_states.get(admin_id, {})
        user_states[admin_id] = {
            'awaiting_custom_payment_receipt_manual_days': True,
            'custom_payment_receipt_order_id': state.get('custom_payment_receipt_order_id'),
            'custom_payment_receipt_user_id': state.get('custom_payment_receipt_user_id'),
            'custom_payment_receipt_amount': state.get('custom_payment_receipt_amount'),
            'custom_payment_receipt_manual_volume': volume
        }
        
        await message.reply(
            t('please_enter_b_duration_days_bd3ba63ba1', lang),
            parse_mode=ParseMode.HTML
        )
    except ValueError:
        await message.reply(t('please_enter_a_valid_number_afbbd0c0b3', lang))

@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_custom_payment_receipt_manual_days'))
async def custom_payment_receipt_manual_days(message: Message):
    """دریافت روز دستی و نمایش تأیید نهایی - فقط برای سفارشات خرید"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_8a3eb8aae6', lang))
        return
    
    state = user_states.get(admin_id, {})
    oid = state.get('custom_payment_receipt_order_id')
    user_id = state.get('custom_payment_receipt_user_id')
    amount = state.get('custom_payment_receipt_amount')
    volume = state.get('custom_payment_receipt_manual_volume')
    
    if not user_id or not oid or not volume:
        user_states.pop(admin_id, None)
        await message.reply(t('error_invalid_data_92bd58b5f5', lang))
        return
    order = orders.get(str(oid))
    if not order or order.get('type') != 'purchase':
        user_states.pop(admin_id, None)
        await message.reply(t('this_order_cannot_be_manuall_ebdb8d399b', lang))
        return
    
    try:
        days = int(message.text.strip())
        if days < 30 or days > 365 or days % 15 != 0:
            await message.reply(t('duration_must_be_between_30_e7cd27d7d1', lang))
            return
        
        final_price = calculate_price(volume, days)
        remaining_balance = amount - final_price
        
        if remaining_balance < 0:
            await message.reply(t('service_price_toman_exceeds_7ef5ab3089', lang, fa_parts=lambda: (f'{final_price:,}', f'{amount:,}'), en_parts=lambda: (f'{final_price:,}', f'{amount:,}')))
            return
        user_states[admin_id] = {
            'awaiting_custom_payment_receipt_confirm': True,
            'custom_payment_receipt_order_id': oid,
            'custom_payment_receipt_user_id': user_id,
            'custom_payment_receipt_amount': amount,
            'custom_payment_receipt_volume': volume,
            'custom_payment_receipt_days': days,
            'custom_payment_receipt_final_price': final_price,
            'custom_payment_receipt_remaining': remaining_balance
        }
        
        target_user = get_user(user_id)
        target_name = safe_html(target_user.get('name', f'کاربر_{user_id}'))
        
        text = t('b_custom_payment_confirmatio_f77afd9ab4', lang, fa_parts=lambda: (f'{oid}', f"{target_name}", f'{user_id}', f'{amount:,}', f'{volume}', f'{days}', f'{final_price:,}', f'{remaining_balance:,}'), en_parts=lambda: (f'{oid}', f"{target_name}", f'{user_id}', f'{amount:,}', f'{volume}', f'{days}', f'{final_price:,}', f'{remaining_balance:,}'))
        buttons = [
            [InlineKeyboardButton(text=t('yes_activate_1a69af5bc1', lang), callback_data="custom_payment_receipt_confirm", style="success")],
            [InlineKeyboardButton(text=t('edit_again_9b45a544fa', lang), callback_data="custom_payment_receipt_manual")],
            [InlineKeyboardButton(text=t('cancel_4197bafba5', lang), callback_data="admin_close_msg", style="danger")]
        ]
        
        await message.reply(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
        
    except ValueError:
        await message.reply(t('please_enter_a_valid_number_afbbd0c0b3', lang))


async def _build_inbound_summary(uid: int) -> str:
    """Resolve user/default inbound selection with real names (even if disabled) and prune missing panel IDs."""
    user_inbounds = get_user_inbound(uid)
    if isinstance(user_inbounds, list):
        selected_inbounds = [ib for ib in user_inbounds if ib is not None]
    elif user_inbounds is not None:
        selected_inbounds = [user_inbounds]
    else:
        selected_inbounds = []

    inbound_names = await get_inbound_display_names(include_disabled=True, force_refresh=False)

    def _format_list(ids: list) -> list[str]:
        items = []
        for ib_id in ids:
            try:
                norm_id = int(ib_id)
            except (TypeError, ValueError):
                norm_id = ib_id
            if norm_id in inbound_names:
                items.append(html.escape(inbound_names[norm_id]))
            elif not inbound_names:
                # Panel unreachable — show raw ID only when panel list could not be loaded
                items.append(f"ID: {ib_id}")
        return items

    if selected_inbounds:
        resolved = _format_list(selected_inbounds)
        if resolved:
            return "✅ اینباندهای انتخاب شده:\n" + "".join(f"  • {name}\n" for name in resolved)

    default_ids = configs_pool.get('default_inbound_ids', [])
    if default_ids:
        resolved_def = _format_list(default_ids)
        if resolved_def:
            return "📌 اینباندهای پیش‌فرض:\n" + "".join(f"  • {name}\n" for name in resolved_def)

    return "❌ هیچ اینباندی انتخاب نشده - از پیش‌فرض استفاده می‌شود"


@router.callback_query(F.data.startswith("approve_receipt_"))
@admin_only
async def approve_receipt(callback: CallbackQuery):
    """تایید رسید با امکان انتخاب اینباند - با تشخیص تمدید"""
    logger.critical(f"🔴 approve_receipt CALLED! data={callback.data}")
    
    
    admin_lang = get_user(callback.from_user.id).get('lang', 'fa')

    try:
        oid = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_order_process_error', admin_lang), show_alert=True)
        return
    
    order = orders.get(str(oid))
    if not order:
        return await callback.answer(t('i18n_order_not_found', admin_lang), show_alert=True)
    
    # ✅ بررسی قفل همزمانی تایید سفارش (Idempotency)
    if order_guard.is_in_progress(oid):
        logger.warning(f"⚠️ Order #{oid} approval is already in progress! Blocking duplicate concurrent call.")
        msg = (
            "⏳ این سفارش در حال حاضر در حال پردازش و تایید است..."
            if admin_lang == "fa"
            else "⏳ This order is already being processed and approved..."
        )
        return await callback.answer(msg, show_alert=True)

    # ✅✅✅ بررسی وضعیت قبلی سفارش - مهمترین بخش برای جلوگیری از دوبار پردازش
    current_status = order.get('status')
    
    # اگر قبلاً تایید شده باشد
    if current_status == 'approved':
        logger.warning(f"⚠️ Order #{oid} was already approved! Preventing duplicate approval")
        await callback.answer(t('i18n_order_already_approved', admin_lang), show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return
    
    # اگر قبلاً رد شده باشد
    if current_status in ['rejected', 'cancelled', 'deleted']:
        logger.warning(f"⚠️ Order #{oid} was already rejected/canceled! Status: {current_status}")
        await callback.answer(t('i18n_order_already_rejected', admin_lang), show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return
    
    # بررسی وجود کانفیگ برای سفارشات خرید
    if order.get('config_link') or order.get('email'):
        if current_status not in ['pending', 'pending_balance_charge', 'awaiting_payment']:
            logger.warning(f"⚠️ Order #{oid} has already been processed and the configuration has been created!")
            await callback.answer(t('i18n_order_already_processed', admin_lang), show_alert=True)
            try:
                await callback.message.delete()
            except Exception:
                pass
            return
    
    order_type = order.get('type', 'purchase')
    
    
    # ==================== بخش شارژ حساب ====================
    if order_type == 'balance_charge':
        # ✅ صدا زدن مستقیم تابع approve_balance با پارامترهای لازم
        # به جای تغییر callback.data، مستقیم تابع را صدا بزنید
        await approve_balance(callback, order_id=oid)
        if order.get('status') == 'approved':
            await update_user_receipt_review_status(order, 'approved')
        return
    
    # ==================== بخش خرید معمولی ====================
    if order_type == 'purchase':
        uid = order['user_id']
        vol = order.get('volume', 0)
        days = order.get('days', 30)
        price = order.get('price', 0)
        parent_order_id = order.get('parent_order_id')
        is_extend = parent_order_id is not None
        
        user_info = get_user(uid)
        user_name = html.escape(user_info.get('name', f'کاربر_{uid}'))
        lang = user_info.get('lang', 'fa')
        
        logger.info(f"📝 Approving order #{oid} - user: {uid} - {vol}GB/{days}days - amount: {price:,}tomans - renewal: {is_extend}")
        
        inbound_display_text = await _build_inbound_summary(uid)
        
        buttons = []
        buttons.append([InlineKeyboardButton(
            text=t('select_inbound_a2b9389177', lang),
            callback_data=f"select_user_inbound_{uid}_{oid}"
        )])
        
        if is_extend:
            approve_label = f"🔄 {t('approve_extend_799a68a8df', lang)}"
        else:
            approve_label = f"✅ {t('final_approve_7ef2812a6e', lang)}"
        
        buttons.append([
            InlineKeyboardButton(
                text=approve_label,
                callback_data=f"confirm_approve_{oid}",
                style="success"
            ),
            InlineKeyboardButton(
                text=f"❌ {t('reject_b13e3ecf20', lang)}",
                callback_data=f"reject_receipt_{oid}",
                style="danger"
            )
        ])
        
        buttons.append([InlineKeyboardButton(
            text=f"🔙 {t('back_to_orders_48b25f33c5', lang)}",
            callback_data="admin_orders"
        )])
        
        category_name = order.get('category_name') or ''
        category_name_en = order.get('category_name_en') or ''
        package_id = order.get('package_id')
        category_id = order.get('category_id')
        
        order_info = "🛒 سفارش معمولی"
        if category_name or category_name_en:
            # اگه یکی خالی بود، از READY_PACKAGES پر کن
            if (not category_name or not category_name_en) and category_id:
                for cat in READY_PACKAGES.get('categories', []):
                    if cat.get('id') == category_id:
                        if not category_name:
                            category_name = cat.get('name') or ''
                        if not category_name_en:
                            category_name_en = cat.get('name_en') or cat.get('name') or ''
                        break

            icon = "📦"
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('id') == category_id:
                    icon = cat.get('icon', '📦')
                    break

            # ✅ نمایش بر اساس زبان ادمین
            category_display = category_name if lang == 'fa' else category_name_en
            cat_name_escaped = html.escape(category_display or 'Ready Package')
            order_info = f"{icon} بسته آماده: {cat_name_escaped}"
        
        extend_status = "🔄 <b>تمدید سرویس</b>" if is_extend else "🆕 <b>خرید جدید</b>"
        parent_info = f"\n🆔 سفارش اصلی: #{parent_order_id}" if is_extend else ""
        
        text = f"""
✅ <b>تایید رسید سفارش #{oid}</b>

━━━━━━━━━━━━━━━━━━━━━━
👤 کاربر: {user_name} (ID: {uid})
📦 نوع: {order_info}
📦 حجم: {vol} GB
⏱ مدت: {days} روز
💰 قیمت: {price:,} تومان
📅 تاریخ: {html.escape(order.get('date', 'نامشخص'))}
📊 نوع سفارش: {extend_status}{parent_info}
━━━━━━━━━━━━━━━━━━━━━━

<b>اینباندها:</b>
{inbound_display_text}

💡 برای تغییر اینباندها، روی دکمه «انتخاب اینباند» کلیک کنید.
    """
        
        try:
            if callback.message.photo:
                await callback.message.edit_caption(
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )
            elif callback.message.text:
                await callback.message.edit_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )
            else:
                await callback.message.delete()
                await callback.message.answer(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )
        except Exception as e:
            logger.warning(f"⚠️ Error editing message: {e}")
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        
        await callback.answer(t('i18n_select_inbounds_please', admin_lang))
        return
        
    # ==================== بخش بسته آماده ====================
    elif order_type == 'ready_package' or order_type == 'category_purchase':
        uid = order['user_id']
        vol = order.get('volume', 0)
        days = order.get('days', 30)
        price = order.get('price', 0)
        inbound_id = order.get('inbound_id')
        package_id = order.get('package_id')
        category_id = order.get('category_id')
        payment_method = order.get('payment_method', '')
        payment_label = order.get('payment_label', '')
        parent_order_id = order.get('parent_order_id')
        is_extend = parent_order_id is not None

        user_info = get_user(uid)
        user_name = html.escape(user_info.get('name', f'کاربر_{uid}'))
        lang = user_info.get('lang', 'fa')

        # ✅ دریافت category_name با fallback + backfill
        category_name = order.get('category_name')
        if not category_name or not str(category_name).strip():
            category_name = get_order_category_name(order, lang)
            if category_name:
                try:
                    _oid = order.get('order_id')
                    if _oid:
                        backfill_order_category(int(_oid))
                        category_name = order.get('category_name') or category_name
                except Exception as e:
                    logger.warning(f"Error backfilling category: {e}")

        if not category_name:
            category_name = t('ready_package_272798b27e', lang)

        # ─── آیکون دسته ───
        icon = "📦"
        for cat in READY_PACKAGES.get('categories', []):
            if cat.get('id') == category_id:
                icon = cat.get('icon', '📦')
                break

        cat_name_escaped = html.escape(category_name)
        logger.info(
            f"📦 Ready package # approved{oid} - user: {uid} - "
            f"{vol}GB/{days}days - amount: {price:,} tomans - category: {category_name} - renewal: {is_extend}"
        )

        inbound_display_text = await _build_inbound_summary(uid)
        
        buttons = []
        buttons.append([InlineKeyboardButton(
            text=t('select_inbound_a2b9389177', lang),
            callback_data=f"select_user_inbound_{uid}_{oid}"
        )])
        
        if is_extend:
            approve_label = f"🔄 {t('approve_extend_799a68a8df', lang)}"
        else:
            approve_label = f"✅ {t('final_approve_7ef2812a6e', lang)}"
        
        buttons.append([
            InlineKeyboardButton(
                text=approve_label,
                callback_data=f"confirm_approve_package_{oid}",
                style="success"
            ),
            InlineKeyboardButton(
                text=f"❌ {t('reject_b13e3ecf20', lang)}",
                callback_data=f"reject_receipt_{oid}",
                style="danger"
            )
        ])
        
        buttons.append([InlineKeyboardButton(
            text=f"🔙 {t('back_to_orders_48b25f33c5', lang)}",
            callback_data="admin_orders"
        )])
        
        extend_status = "🔄 <b>تمدید سرویس</b>" if is_extend else "🆕 <b>خرید جدید</b>"
        parent_info = f"\n🆔 سفارش اصلی: #{parent_order_id}" if is_extend else ""
        
        text = f"""
📦 <b>تایید بسته آماده #{oid}</b>

━━━━━━━━━━━━━━━━━━━━━━
👤 کاربر: {user_name} (ID: {uid})
{icon} دسته: {cat_name_escaped}
📦 حجم: {vol} GB
⏱️ مدت: {days} روز
💰 قیمت: {price:,} تومان
🆔 بسته: #{package_id if package_id else 'نامشخص'}
📅 تاریخ: {html.escape(order.get('date', 'نامشخص'))}
📊 نوع سفارش: {extend_status}{parent_info}
━━━━━━━━━━━━━━━━━━━━━━

<b>اینباندها:</b>
{inbound_display_text}

💡 برای تغییر اینباندها، روی دکمه «انتخاب اینباند» کلیک کنید.
"""
        
        # ✅ ویرایش پیام ادمین با تشخیص نوع
        try:
            if callback.message.photo:
                await callback.message.edit_caption(
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )
            elif callback.message.text:
                await callback.message.edit_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )
            else:
                await callback.message.delete()
                await callback.message.answer(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )
        except Exception as e:
            logger.warning(f"⚠️ Error editing message: {e}")
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        
        await callback.answer(t('i18n_select_operation_please', admin_lang))
        return
    
    else:
        logger.warning(f"⚠️ Unknown order type for #{oid}: {order_type}")
        return await callback.answer(t('i18n_order_type_unknown', admin_lang), show_alert=True)
    
@router.callback_query(F.data.startswith("select_user_inbound_"))
@admin_only
async def select_user_inbound(callback: CallbackQuery):
    """انتخاب اینباند برای کاربر - با بارگذاری و فیلتر اینباندهای فعلی"""
    
    parts = callback.data.split("_")
    try:
        uid = int(parts[3])
        oid = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    # ✅ اولویت اول: اینباندهای سفارش
    current_inbounds = []
    order = orders.get(str(oid))
    if order:
        order_inbounds = order.get('inbound_id', [])
        if isinstance(order_inbounds, list):
            current_inbounds = [ib for ib in order_inbounds if ib]
        elif order_inbounds:
            current_inbounds = [order_inbounds]
    
    # ✅ اولویت دوم: انتخاب کاربر
    if not current_inbounds:
        user_inbounds = get_user_inbound(uid)
        if isinstance(user_inbounds, list):
            current_inbounds = user_inbounds.copy()
        elif user_inbounds:
            current_inbounds = [user_inbounds]
    
    # ✅ فیلتر نامعتبرها
    current_inbounds = await filter_valid_inbounds(current_inbounds)
    
    # ✅ اگه بعد از فیلتر خالی شد، پیش‌فرض بذار
    if not current_inbounds:
        default_ids = configs_pool.get('default_inbound_ids', [])
        if default_ids:
            current_inbounds = await filter_valid_inbounds(default_ids)
    
    # ✅ حالا بریز توی TEMP
    temp_key = f"{uid}_{oid}"
    TEMP_INBOUND_SELECTION[temp_key] = current_inbounds
    
    logger.info(f"📡 [select_user_inbound] filtered inbounds for user {uid} order #{oid}: {current_inbounds}")
    
    await show_inbound_selection(callback.message, uid, oid, callback.from_user.id)
    
    await safe_answer(callback)

@router.callback_query(F.data.startswith("set_user_inbound_default_"))
@admin_only
async def set_user_inbound_default(callback: CallbackQuery):
    """انتخاب اینباندهای پیش‌فرض برای کاربر"""
    
    parts = callback.data.split("_")
    try:
        uid = int(parts[3])
        oid = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    default_ids = configs_pool.get('default_inbound_ids', [])
    if default_ids:
        save_user_inbound_selection(uid, default_ids)
        await callback.answer(
            t('default_inbounds_selected_10c39e7354', lang),
            show_alert=True
        )
    else:
        await callback.answer(
            t('no_default_inbounds_set_ae9b684ee5', lang),
            show_alert=True
        )
    await show_inbound_selection(callback.message, uid, oid, callback.from_user.id)
    
@router.message(Command("fix_categories"), IsAdmin())
async def cmd_fix_categories(message: Message):
    """اصلاح یکجای category_name در همه سفارشات قدیمی"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return

    fixed = 0
    already_ok = 0
    no_category = []
    not_ready_package = 0

    for oid, order in orders.items():
        if not isinstance(order, dict):
            continue

        # فقط بسته‌های آماده
        if order.get('type') not in ('ready_package', 'category_purchase'):
            not_ready_package += 1
            continue

        if order.get('category_name') and str(order.get('category_name')).strip():
            already_ok += 1
            continue

        if backfill_order_category(int(oid)):
            fixed += 1
        else:
            no_category.append({
                'order_id': oid,
                'category_id': order.get('category_id'),
                'package_id': order.get('package_id'),
                'email': order.get('email', ''),
            })

    # ساخت گزارش
    text = (
        f"✅ <b>گزارش اصلاح category_name</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔧 اصلاح شد: {fixed}\n"
        f"✅ قبلاً درست بود: {already_ok}\n"
        f"❌ دسته پیدا نشد: {len(no_category)}\n"
        f"ℹ️ (غیر بسته آماده): {not_ready_package}\n"
    )

    if no_category:
        text += "\n<b>📋 لیست سفارش‌های بدون دسته:</b>\n"
        for item in no_category[:20]:
            text += (
                f"\n#{item['order_id']} - "
                f"cat_id: {item['category_id'] or '—'} - "
                f"pkg_id: {item['package_id'] or '—'}"
            )
        if len(no_category) > 20:
            text += f"\n\n... و {len(no_category) - 20} مورد دیگر"

    await message.reply(text, parse_mode=ParseMode.HTML)
    
     
@router.callback_query(F.data.startswith("set_user_inbound_"))
@admin_only
async def set_user_inbound(callback: CallbackQuery):
    """تنظیم اینباند برای کاربر (جایگزینی)"""
    
    parts = callback.data.split("_")
    if parts[3] == 'default':
        try:
            uid = int(parts[4])
            oid = int(parts[5])
        except (ValueError, IndexError):
            await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
            return
        
        lang = get_user(callback.from_user.id).get('lang', 'fa')
        default_ids = configs_pool.get('default_inbound_ids', [])
        if default_ids:
            save_user_inbound_selection(uid, default_ids)
            await callback.answer(
                t('default_inbounds_selected_bbb80d74cc', lang),
                show_alert=True
            )
        else:
            await callback.answer(
                t('no_default_inbounds_set_ae9b684ee5', lang),
                show_alert=True
            )
        await approve_receipt(callback)
        return
    
    try:
        uid = int(parts[3])
        inbound_id = int(parts[4])
        oid = int(parts[5])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    save_user_inbound_selection(uid, [inbound_id])
    
    await callback.answer(
        t('inbound_selected_2bd78065da', lang),
        show_alert=True
    )
    await approve_receipt(callback)
    
    
@router.callback_query(F.data.startswith("remove_user_inbound_"))
@admin_only
async def remove_user_inbound(callback: CallbackQuery):
    """حذف یک اینباند از لیست کاربر"""
    
    parts = callback.data.split("_")
    try:
        uid = int(parts[3])
        inbound_id = int(parts[4])
        oid = int(parts[5])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    current_inbounds = get_user_inbound(uid)
    if isinstance(current_inbounds, list):
        current_list = current_inbounds.copy()
    elif current_inbounds:
        current_list = [current_inbounds]
    else:
        current_list = []
    if inbound_id in current_list:
        current_list.remove(inbound_id)
        
        if current_list:
            save_user_inbound_selection(uid, current_list)
        else:
            default_ids = configs_pool.get('default_inbound_ids', [])
            if default_ids:
                save_user_inbound_selection(uid, default_ids)
            else:
                save_user_inbound_selection(uid, None)
        
        await callback.answer(
            t('inbound_removed_050fe3370e', lang),
            show_alert=True
        )
    else:
        await callback.answer(
            t('inbound_not_in_list_314a8d3d74', lang),
            show_alert=True
        )
    await approve_receipt(callback)
    
    
@router.callback_query(F.data.startswith("select_multiple_inbounds_"))
@admin_only
async def select_multiple_inbounds(callback: CallbackQuery):
    """انتخاب چندین اینباند برای کاربر (با فیلتر)"""
    
    parts = callback.data.split("_")
    try:
        uid = int(parts[3])
        oid = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    inbounds = await xui_get_inbounds()
    active_inbounds = [i for i in inbounds if i.get('enable', True)]
    
    if not active_inbounds:
        await callback.answer(t('i18n_no_active_inbounds', lang), show_alert=True)
        return
    
    # ✅ اینباندهای فعلی
    current_inbounds = get_user_inbound(uid)
    if isinstance(current_inbounds, list):
        current_list = current_inbounds.copy()
    elif current_inbounds:
        current_list = [current_inbounds]
    else:
        current_list = []
    
    # ✅ فیلتر نامعتبرها
    current_list = await filter_valid_inbounds(current_list)
    
    inbound_names = {}
    for ib in active_inbounds:
        inbound_id = ib.get('id')
        remark = ib.get('remark', f'ID:{inbound_id}')
        protocol = ib.get('protocol', '').upper()
        port = ib.get('port', '')
        inbound_names[inbound_id] = f"{remark} - {protocol}:{port}"
    
    current_names = [inbound_names.get(ib_id, f"ID: {ib_id}") for ib_id in current_list]
    
    text = t('b_select_multiple_inbounds_f_04120d28c6', lang, fa_parts=lambda: (f'{uid}', f"{(', '.join(current_names) if current_names else 'هیچ')}"), en_parts=lambda: (f'{uid}', f"{(', '.join(current_names) if current_names else 'None')}"))
    
    buttons = []
    for inbound in active_inbounds:
        inbound_id = inbound.get('id')
        ib_name = inbound_names.get(inbound_id, f"ID: {inbound_id}")
        
        is_selected = inbound_id in current_list
        label = f"{'✅' if is_selected else '⬜'} {ib_name}"
        
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"toggle_user_inbound_{uid}_{inbound_id}_{oid}",
            style="primary" if is_selected else None
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('save_settings_d9e3bd6fe8', lang),
        callback_data=f"save_user_inbounds_{uid}_{oid}",
        style="success"
    )])
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data=f"approve_receipt_{oid}"
    )])
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.debug(f"Failed to edit message in remove_user_inbound, sending new: {e}")
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
    
    await safe_answer(callback)
    
@router.callback_query(F.data.startswith("toggle_user_inbound_"))
@admin_only
async def toggle_user_inbound(callback: CallbackQuery):
    """تغییر وضعیت انتخاب یک اینباند (تیک زدن/برداشتن)"""
    
    parts = callback.data.split("_")
    try:
        uid = int(parts[3])
        inbound_id = int(parts[4])
        oid = int(parts[5])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    current_inbounds = get_user_inbound(uid)
    if isinstance(current_inbounds, list):
        current_list = current_inbounds.copy()
    elif current_inbounds:
        current_list = [current_inbounds]
    else:
        current_list = []
    if inbound_id in current_list:
        current_list.remove(inbound_id)
        await callback.answer(t('i18n_cancelled_one', get_user(callback.from_user.id).get('lang', 'fa')))
    else:
        current_list.append(inbound_id)
        await callback.answer("✅ انتخاب شد" if get_user(callback.from_user.id).get('lang', 'fa') == "fa" else "✅ Selected")
    if current_list:
        save_user_inbound_selection(uid, current_list)
    else:
        save_user_inbound_selection(uid, None)
    await show_inbound_selection(callback.message, uid, oid, callback.from_user.id)
    
    
      
async def show_inbound_selection(message: types.Message, uid: int, oid: int, admin_id: int, update_existing: bool = False):
    """نمایش صفحه انتخاب اینباند با دکمه‌های کلاسیک (با فیلتر اینباندهای نامعتبر)"""
    if admin_id != ADMIN_ID_INT:
        return
    
    lang = get_user(admin_id).get('lang', 'fa')
    inbounds = await xui_get_inbounds()
    active_inbounds = [i for i in inbounds if i.get('enable', True)]
    
    if not active_inbounds:
        await message.answer("❌ هیچ اینباند فعالی یافت نشد")
        return
    
    # ✅ لیست اعتبارسنجی اینباندهای فعال
    valid_ids = {ib.get('id') for ib in active_inbounds}
    
    temp_key = f"{uid}_{oid}"
    if temp_key in TEMP_INBOUND_SELECTION:
        current_list = TEMP_INBOUND_SELECTION[temp_key]
    else:
        current_inbounds = get_user_inbound(uid)
        if isinstance(current_inbounds, list):
            current_list = current_inbounds.copy()
        elif current_inbounds:
            current_list = [current_inbounds]
        else:
            current_list = []
        TEMP_INBOUND_SELECTION[temp_key] = current_list.copy()
    
    # ✅ فیلتر اینباندهای نامعتبر
    invalid_ids = [ib for ib in current_list if ib not in valid_ids]
    if invalid_ids:
        logger.warning(f"⚠️ [show_inbound_selection] Invalid inbounds removed: {invalid_ids}")
        current_list = [ib for ib in current_list if ib in valid_ids]
        TEMP_INBOUND_SELECTION[temp_key] = current_list
    
    inbound_names = {}
    for ib in active_inbounds:
        inbound_id = ib.get('id')
        remark = ib.get('remark', f'ID:{inbound_id}')
        protocol = ib.get('protocol', '').upper()
        port = ib.get('port', '')
        inbound_names[inbound_id] = f"{remark} - {protocol}:{port}"
    
    text = t('b_select_inbound_for_user_b_122c820fc7', lang, fa_parts=lambda: (f'{uid}', f'{len(current_list)}'), en_parts=lambda: (f'{uid}', f'{len(current_list)}'))
    
    buttons = []
    for inbound in active_inbounds:
        inbound_id = inbound.get('id')
        ib_name = inbound_names.get(inbound_id, f"ID: {inbound_id}")
        
        is_selected = inbound_id in current_list
        label = f"{'✅' if is_selected else '⬜'} {html.escape(ib_name)}"
        
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=OrderInboundCB(action="toggle", uid=int(uid), oid=int(oid), inbound_id=int(inbound_id)).pack(),
            style="success" if is_selected else None
        )])
    
    buttons.append([
        InlineKeyboardButton(
            text=t('select_all_9792663d71', lang),
            callback_data=OrderInboundCB(action="selectall", uid=int(uid), oid=int(oid)).pack(),
            style="success"
        ),
        InlineKeyboardButton(
            text=t('select_default_ea628ae037', lang),
            callback_data=OrderInboundCB(action="default", uid=int(uid), oid=int(oid)).pack(),
            style="primary"
        )
    ])
    buttons.append([
        InlineKeyboardButton(
            text=t('clear_all_565e888195', lang),
            callback_data=OrderInboundCB(action="clear", uid=int(uid), oid=int(oid)).pack(),
            style="danger"
        )
    ])
    
    buttons.append([
        InlineKeyboardButton(
            text=t('save_return_aeadc42bf2', lang),
            callback_data=OrderInboundCB(action="save", uid=int(uid), oid=int(oid)).pack(),
            style="success"
        ),
        InlineKeyboardButton(
            text=t('cancel_4197bafba5', lang),
            callback_data=OrderInboundCB(action="cancel", uid=int(uid), oid=int(oid)).pack(),
            style="danger"
        )
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    try:
        if update_existing:
            try:
                await message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            except Exception as e:
                if "message is not modified" in str(e):
                    try:
                        await message.edit_reply_markup(reply_markup=keyboard)
                    except Exception as e2:
                        if "message is not modified" not in str(e2):
                            logger.error(f"Error editing keyboard: {e2}")
                else:
                    raise
        else:
            await message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" in str(e):
            logger.debug('Message unchanged')
        else:
            try:
                await message.delete()
            except Exception:
                pass
            await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)            
            
            
            
@router.callback_query(OrderInboundCB.filter(F.action == "toggle"))
@router.callback_query(F.data.startswith("toggle_inbound_"))
@admin_only
async def toggle_inbound(callback: CallbackQuery, callback_data: Optional[OrderInboundCB] = None):
    """تغییر وضعیت یک اینباند (به‌روزرسانی محلی)"""
    
    if callback_data:
        uid = callback_data.uid
        inbound_id = callback_data.inbound_id
        oid = callback_data.oid
    else:
        parts = callback.data.split("_")
        try:
            uid = int(parts[2])
            inbound_id = int(parts[3])
            oid = int(parts[4])
        except (ValueError, IndexError):
            await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
            return
    temp_key = f"{uid}_{oid}"
    if temp_key not in TEMP_INBOUND_SELECTION:
        current_inbounds = get_user_inbound(uid)
        if isinstance(current_inbounds, list):
            TEMP_INBOUND_SELECTION[temp_key] = current_inbounds.copy()
        elif current_inbounds:
            TEMP_INBOUND_SELECTION[temp_key] = [current_inbounds]
        else:
            TEMP_INBOUND_SELECTION[temp_key] = []
    
    current_list = TEMP_INBOUND_SELECTION[temp_key]
    if inbound_id in current_list:
        current_list.remove(inbound_id)
        await callback.answer("❌ لغو شد", show_alert=False)
    else:
        current_list.append(inbound_id)
        await callback.answer("✅ انتخاب شد", show_alert=False)
    TEMP_INBOUND_SELECTION[temp_key] = current_list
    await show_inbound_selection(callback.message, uid, oid, callback.from_user.id, update_existing=True)
    
    
    
@router.callback_query(OrderInboundCB.filter(F.action == "default"))
@router.callback_query(F.data.startswith("default_inbounds_"))
@admin_only
async def default_inbounds(callback: CallbackQuery, callback_data: Optional[OrderInboundCB] = None):
    """انتخاب اینباندهای پیش‌فرض"""
    
    if callback_data:
        uid = callback_data.uid
        oid = callback_data.oid
    else:
        parts = callback.data.split("_")
        try:
            uid = int(parts[2])
            oid = int(parts[3])
        except (ValueError, IndexError):
            await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
            return
    
    default_ids = configs_pool.get('default_inbound_ids', [])
    if default_ids:
        temp_key = f"{uid}_{oid}"
        TEMP_INBOUND_SELECTION[temp_key] = default_ids.copy()
        await callback.answer(f"✅ {len(default_ids)} اینباند پیش‌فرض انتخاب شد", show_alert=True)
    else:
        await callback.answer("❌ هیچ اینباند پیش‌فرضی تنظیم نشده است", show_alert=True)
        return
    
    await show_inbound_selection(callback.message, uid, oid, callback.from_user.id, update_existing=True)
    
    
    
@router.callback_query(F.data == "apply_coupon")
async def apply_coupon_page(callback: CallbackQuery):
    """صفحه اعمال کوپن - با امکان ورودی مستقیم"""
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')

    # ✅ حفظ کوپن قبلی (اگه بود)
    user_state = user_states.get(user_id, {})
    prev_coupon_code = user_state.get('coupon_code')
    prev_coupon_discount = user_state.get('coupon_discount')
    prev_coupon_applied = user_state.get('coupon_applied', False)

    # ✅ بررسی کوپن فعال فعلی
    if user_state.get('coupon_applied'):
        coupon_code = user_state.get('coupon_code', '')
        coupon_discount = user_state.get('coupon_discount', 0)

        text = t('b_active_coupon_b_you_have_a_ea291da123', lang, fa_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{coupon_code}', f'{coupon_discount}'), en_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{coupon_code}', f'{coupon_discount}'))
        buttons = [
            [InlineKeyboardButton(
                text=t('cancel_coupon_733b72e7bd', lang),
                callback_data="cancel_coupon",
                style="danger"
            )],
            [InlineKeyboardButton(
                text=t('buy_service_21bce537d0', lang),
                callback_data="buy_service",
                style="success"
            )],
            [InlineKeyboardButton(
                text=t('main_menu_0cdd07a7cc', lang),
                callback_data="back_to_main"
            )]
        ]

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
        await safe_answer(callback)
        return

    # ══════════════════════════════════════════════
    # ✅ نمایش راهنما + تنظیم state برای دریافت کد
    # ══════════════════════════════════════════════
    text = (
        t('b_got_a_discount_code_b_send_096c2c5577', lang, fa_parts=lambda: (f"{premium_emoji('gift', '🏷️')}",), en_parts=lambda: (f"{premium_emoji('gift', '🏷️')}",))
    )
    back_btn_text = t('main_menu_0cdd07a7cc', lang)

    buttons = [
        [InlineKeyboardButton(
            text=back_btn_text,
            callback_data="back_to_main",
            style="danger"
        )]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )

    # ✅ تنظیم state برای دریافت کد کوپن
    if user_id not in user_states:
        user_states[user_id] = {}

    user_states[user_id]['awaiting_coupon_code'] = True
    user_states[user_id]['timestamp'] = now_tehran_iso()

    # ✅ حفظ کوپن قبلی (اگه بود)
    if prev_coupon_applied and prev_coupon_code:
        user_states[user_id]['coupon_code'] = prev_coupon_code
        user_states[user_id]['coupon_discount'] = prev_coupon_discount
        user_states[user_id]['coupon_applied'] = True

    await safe_answer(callback)
    
    
@router.callback_query(F.data == "cancel_coupon")
async def cancel_coupon(callback: CallbackQuery):
    """لغو کوپن فعال توسط کاربر (بدون لغو سفارش)"""
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    
    user_state = user_states.get(user_id, {})
    
    if not user_state.get('coupon_applied'):
        await callback.answer(t('you_have_no_active_coupon_d104f31440', lang), show_alert=True)
        return
    
    # ✅✅✅ حذف کامل از همه جا
    coupon_code = user_state.get('coupon_code')
    
    # حذف از user_states
    if user_id in user_states:
        user_states[user_id].pop('coupon_code', None)
        user_states[user_id].pop('coupon_discount', None)
        user_states[user_id].pop('coupon_applied', None)
    
    # حذف از دیتابیس
    uid = str(user_id)
    if uid in users:
        users[uid]['coupon_code'] = None
        users[uid]['coupon_discount'] = 0
        users[uid]['coupon_applied'] = False
        save_json(DB_FILES['users'], users)
    
    logger.info(f"🗑️ coupon {coupon_code} by user {user_id} cancelled")
    
    await callback.answer(t('coupon_cancelled_successfull_38f02fcee4', lang), show_alert=True)
    await callback.message.edit_text(
        t('coupon_cancelled_you_can_app_2b96e18d6c', lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=t('back_to_my_account_6a8c1c28bd', lang),
                callback_data="my_account",
            )
        ]]),
    )
    
    

@router.callback_query(OrderInboundCB.filter(F.action == "clear"))
@router.callback_query(F.data.startswith("clear_inbounds_"))
@admin_only
async def clear_inbounds(callback: CallbackQuery, callback_data: Optional[OrderInboundCB] = None):
    """پاک کردن همه اینباندها"""
    
    if callback_data:
        uid = callback_data.uid
        oid = callback_data.oid
    else:
        parts = callback.data.split("_")
        try:
            uid = int(parts[2])
            oid = int(parts[3])
        except (ValueError, IndexError):
            await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
            return
    
    temp_key = f"{uid}_{oid}"
    TEMP_INBOUND_SELECTION[temp_key] = []
    
    await callback.answer("🗑 همه اینباندها پاک شدند", show_alert=True)
    await show_inbound_selection(callback.message, uid, oid, callback.from_user.id, update_existing=True)
    
@router.callback_query(OrderInboundCB.filter(F.action == "selectall"))
@router.callback_query(F.data.startswith("select_all_inbounds_"))
@admin_only
async def select_all_inbounds(callback: CallbackQuery, callback_data: Optional[OrderInboundCB] = None):
    """انتخاب همه اینباندهای فعال برای کاربر"""
    
    if callback_data:
        uid = callback_data.uid
        oid = callback_data.oid
    else:
        parts = callback.data.split("_")
        try:
            uid = int(parts[3])
            oid = int(parts[4])
        except (ValueError, IndexError):
            await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
            return
    
    inbounds = await xui_get_inbounds(force_refresh=True)
    active_inbounds = [i for i in inbounds if i.get('enable', True)]
    all_ids = [int(i.get('id')) for i in active_inbounds if i.get('id') is not None]
    
    if not all_ids:
        await callback.answer("❌ هیچ اینباند فعالی یافت نشد", show_alert=True)
        return
    
    temp_key = f"{uid}_{oid}"
    TEMP_INBOUND_SELECTION[temp_key] = list(all_ids)
    
    await safe_answer(
        callback,
        f"✅ {len(all_ids)} اینباند انتخاب شد",
        alert=True
    )
    await show_inbound_selection(
        callback.message, uid, oid, callback.from_user.id,
        update_existing=True
    )
    
@router.callback_query(OrderInboundCB.filter(F.action == "save"))
@router.callback_query(F.data.startswith("save_inbounds_"))
@admin_only
async def save_inbounds(callback: CallbackQuery, callback_data: Optional[OrderInboundCB] = None):
    """ذخیره تنظیمات و بازگشت"""
    
    if callback_data:
        uid = callback_data.uid
        oid = callback_data.oid
    else:
        parts = callback.data.split("_")
        try:
            uid = int(parts[2])
            oid = int(parts[3])
        except (ValueError, IndexError):
            await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
            return
    
    temp_key = f"{uid}_{oid}"
    current_list = TEMP_INBOUND_SELECTION.get(temp_key, [])
    if current_list:
        save_user_inbound_selection(uid, current_list)
    else:
        save_user_inbound_selection(uid, None)
    if temp_key in TEMP_INBOUND_SELECTION:
        del TEMP_INBOUND_SELECTION[temp_key]
    
    await callback.answer(f"✅ {len(current_list)} اینباند ذخیره شد", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    text = t('b_inbound_settings_saved_b_i_a05ecc8b7f', lang, fa_parts=lambda: (f'{len(current_list)}', f'{uid}'), en_parts=lambda: (f'{len(current_list)}', f'{uid}'))
    
    await callback.message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('back_to_order_approval_b4451ee8d2', lang),
                callback_data=f"approve_receipt_{oid}",
                style="primary"
            )]
        ]),
        parse_mode=ParseMode.HTML
    )
    
@router.callback_query(OrderInboundCB.filter(F.action == "cancel"))
@router.callback_query(F.data.startswith("cancel_inbounds_"))
@admin_only
async def cancel_inbounds(callback: CallbackQuery, callback_data: Optional[OrderInboundCB] = None):
    """انصراف از تغییرات و بازگشت"""
    
    if callback_data:
        uid = callback_data.uid
        oid = callback_data.oid
    else:
        parts = callback.data.split("_")
        try:
            uid = int(parts[2])
            oid = int(parts[3])
        except (ValueError, IndexError):
            await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
            return
    temp_key = f"{uid}_{oid}"
    if temp_key in TEMP_INBOUND_SELECTION:
        del TEMP_INBOUND_SELECTION[temp_key]
    
    await callback.answer("❌ انصراف", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    text = t('b_changes_cancelled_b_your_c_2b0c9dda8e', lang)
    
    await callback.message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('back_to_order_approval_b4451ee8d2', lang),
                callback_data=f"approve_receipt_{oid}",
                style="primary"
            )]
        ]),
        parse_mode=ParseMode.HTML
    )
    
    


       
@router.callback_query(F.data.startswith("clear_user_inbounds_"))
@admin_only
async def clear_user_inbounds(callback: CallbackQuery):
    """پاک کردن همه اینباندهای انتخاب شده"""
    
    parts = callback.data.split("_")
    try:
        uid = int(parts[3])
        oid = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    save_user_inbound_selection(uid, None)
    
    await callback.answer(
        t('all_inbounds_cleared_b755a0a637', lang),
        show_alert=True
    )
    await show_inbound_selection(callback.message, uid, oid, callback.from_user.id)
    
    
    
@router.callback_query(F.data.startswith("save_user_inbounds_"))
@admin_only
async def save_user_inbounds(callback: CallbackQuery):
    """ذخیره تنظیمات و بازگشت به صفحه تایید"""
    
    parts = callback.data.split("_")
    try:
        uid = int(parts[3])
        oid = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    current_inbounds = get_user_inbound(uid)
    count = len(current_inbounds) if isinstance(current_inbounds, list) else (1 if current_inbounds else 0)
    
    await callback.answer(
        t('inbounds_saved_ebb4cebe43', lang, fa_parts=lambda: (f'{count}',), en_parts=lambda: (f'{count}',)),
        show_alert=True
    )
    await approve_receipt(callback)

@router.callback_query(F.data.startswith("change_package_inbound_"))
@admin_only
async def change_package_inbound(callback: CallbackQuery):
    """تغییر اینباند برای بسته آماده"""
    
    try:
        oid = int(callback.data.split("_")[3])
    except Exception:
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    order = orders.get(str(oid))
    if not order:
        return await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    await callback.message.edit_text("⏳ در حال دریافت لیست اینباندها...")
    
    inbounds = await xui_get_inbounds()
    active_inbounds = [i for i in inbounds if i.get('enable', True)]
    
    if not active_inbounds:
        await callback.message.edit_text(
            t('i18n_no_active_inbounds', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data=f"approve_receipt_{oid}")]
            ])
        )
        return
    
    current_inbound = order.get('inbound_id')
    
    text = t('b_change_inbound_for_order_b_2d0e93d68b', lang, fa_parts=lambda: (f'{oid}', f"{(current_inbound if current_inbound else '❌ تنظیم نشده (استفاده از پیش\u200cفرض)')}"), en_parts=lambda: (f'{oid}', f"{(current_inbound if current_inbound else '❌ Not set (using default)')}"))
    
    buttons = []
    buttons.append([InlineKeyboardButton(
        text=t('use_default_inbound_187be52afc', lang),
        callback_data=f"set_package_inbound_{oid}_default"  # فرمت صحیح
    )])
    
    for inbound in active_inbounds:
        inbound_id = inbound.get('id')
        remark = inbound.get('remark', f'Inbound {inbound_id}')
        protocol = inbound.get('protocol', 'unknown')
        port = inbound.get('port')
        
        if not inbound_id:
            continue
        
        is_selected = (inbound_id == current_inbound)
        label = f"{'✅' if is_selected else '  '} {remark} - {protocol.upper()}:{port}"
        
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"set_package_inbound_{oid}_{inbound_id}"  # فرمت صحیح
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data=f"approve_receipt_{oid}"
    )])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)

@router.callback_query(F.data.startswith("set_package_inbound_"))
@admin_only
async def set_package_inbound(callback: CallbackQuery):
    """تنظیم اینباند جدید برای بسته آماده"""
    logger.info(f"🔍 set_package_inbound CALLED: {callback.data}")
    try:
        parts = callback.data.split("_")
        
        oid = int(parts[3])              # ایندکس 3 = order_id
        inbound_value = parts[4]          # ایندکس 4 = inbound_id یا 'default'
        
        logger.info(f"✅ oid: {oid}, inbound_value: {inbound_value}")
        
    except (ValueError, IndexError) as e:
        logger.error(f"❌ Error extracting data: {e} - data: {callback.data}")
        await callback.answer("❌ خطا در پردازش داده‌ها", show_alert=True)
        return
    
    order = orders.get(str(oid))
    if not order:
        return await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if inbound_value == 'default':
        update_order(oid, inbound_id=None)
        await callback.answer(
            t('default_inbound_set_for_orde_a6f6cc13ac', lang, fa_parts=lambda: (f'{oid}',), en_parts=lambda: (f'{oid}',)),
            show_alert=True
        )
    else:
        try:
            inbound_id = int(inbound_value)
            update_order(oid, inbound_id=inbound_id)
            await callback.answer(
                t('inbound_set_for_order_f71086db79', lang, fa_parts=lambda: (f'{inbound_id}', f'{oid}'), en_parts=lambda: (f'{inbound_id}', f'{oid}')),
                show_alert=True
            )
        except ValueError:
            await callback.answer("❌ اینباند نامعتبر!", show_alert=True)
            return
    await approve_receipt(callback)
    
    



"""
routers/admin_orders.py
-----------------------
ماژول مدیریت و تایید سفارشات ادمین (فاز ۳.۴)
شامل:
- تایید نهایی بسته آماده و سرویس سفارشی (confirm_approve_package, confirm_approve_with_inbound)
- انتخاب اینباند برای سفارش (select_inbound_for_order)
- رد رسید و سفارش (reject_receipt, reject_direct, reject_order)
- تایید مستقیم سفارش (approve_direct, approve_order, fulfill_vpn_order)
- مشاهده سفارش و فیش واریزی (view_order, view_receipt, admin_orders)
- لغو سفارش توسط ادمین و بازگشت وجه (cancel_order_admin, confirm_cancel_order_admin)
- ابزارهای نام دسته و بک‌فیل (get_order_category_name, backfill_order_category)
"""

import html
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from aiogram import Bot, Router, F
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from config import SENAI_PANEL_ENABLED, is_senai_panel_enabled
from core.state_stores import user_states
from database import (
    orders,
    configs_pool,
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
    get_admin_id_int,
    consume_coupon,
    COUPONS,
    add_balance,
    release_coupon_on_cancel,
)
from routers.payments import approve_receipt, get_user_display_name
from routers.orders import extend_service, create_client_in_panel
from routers.configs_view import send_config_with_qr_option
from routers.admin_test import save_user_inbound_selection
from routers.support import handle_chat_message
from routers.admin_tools import admin_chat_reply
from services.panel_api import (
    xui_create_client_with_inbound,
    get_user_inbound,
    filter_valid_inbounds,
    get_client_inbounds,
)
from strings import t
from utils.guards import admin_only
from utils.helpers import premium_emoji, safe_answer, safe_html, safe_edit_message
from utils.payment_guard import order_guard, PaymentInProgressError

logger = logging.getLogger(__name__)

router = Router(name="admin_orders")

ADMIN_ID_INT = get_admin_id_int()

# ---------------------------------------------------------------------------
# Bot Reference & Proxy
# ---------------------------------------------------------------------------
_bot: Optional[Bot] = None

def set_bot(b: Bot):
    global _bot
    _bot = b

class _AdminOrdersBotProxy:
    def __getattr__(self, name):
        if _bot is not None:
            return getattr(_bot, name)
        import main
        main_bot = getattr(main, "bot", None)
        if main_bot is not None:
            return getattr(main_bot, name)
        raise RuntimeError("Bot instance not set in routers.admin_orders")

bot = _AdminOrdersBotProxy()

# ---------------------------------------------------------------------------
# Late-binding Proxies for functions still in main.py
# ---------------------------------------------------------------------------
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

async def check_referral_bonus(*args, **kwargs):
    import main
    if hasattr(main, "check_referral_bonus"):
        return await main.check_referral_bonus(*args, **kwargs)

async def update_user_receipt_review_status(*args, **kwargs):
    import main
    if hasattr(main, "update_user_receipt_review_status"):
        return await main.update_user_receipt_review_status(*args, **kwargs)

async def send_sticker(*args, **kwargs):
    import main
    if hasattr(main, "send_sticker"):
        return await main.send_sticker(*args, **kwargs)

async def block_unauthorized(*args, **kwargs):
    import main
    if hasattr(main, "block_unauthorized"):
        return await main.block_unauthorized(*args, **kwargs)
    return False

class _CustomLoggerProxy:
    @staticmethod
    def log_event(*args, **kwargs):
        import main
        if hasattr(main, "CustomLogger"):
            return main.CustomLogger.log_event(*args, **kwargs)
        logger.info(f"CustomLogger event: {args} {kwargs}")

CustomLogger = _CustomLoggerProxy()

class _AdminOrdersLogSystemProxy:
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

log_system = _AdminOrdersLogSystemProxy()

# ---------------------------------------------------------------------------
# Admin Orders Handlers & Operations
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("confirm_approve_package_"))
@admin_only
async def confirm_approve_package(callback: CallbackQuery):
    """تایید نهایی بسته آماده - با تشخیص کامل تمدید و فیلتر اینباندها"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    try:
        oid = int(callback.data.split("_")[3])
    except Exception:
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    try:
        async with order_guard.lock_order(oid):
            return await _confirm_approve_package_impl(callback, oid)
    except PaymentInProgressError:
        logger.warning(f"⚠️ Order #{oid} package approval already in progress! Blocking duplicate call.")
        msg = (
            "⏳ این سفارش در حال حاضر در حال پردازش و تایید است..."
            if lang == "fa"
            else "⏳ This order is already being processed and approved..."
        )
        return await callback.answer(msg, show_alert=True)


async def _confirm_approve_package_impl(callback: CallbackQuery, oid: int):
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    order = orders.get(str(oid))
    if not order:
        return await callback.answer(t('i18n_order_not_found', lang), show_alert=True)

    # ✅ بررسی وضعیت قبلی سفارش
    current_status = order.get('status')
    
    if current_status == 'approved':
        logger.warning(f"⚠️ Order #{oid} was already approved!")
        await callback.answer("⚠️ این سفارش قبلاً تایید شده است!", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return
    
    if current_status in ['rejected', 'cancelled', 'deleted']:
        logger.warning(f"⚠️ Order #{oid} was already rejected/canceled! Status: {current_status}")
        await callback.answer("⚠️ این سفارش قبلاً رد یا لغو شده است!", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return
    
    if order.get('is_extend'):
        if order.get('new_volume') and order.get('new_days'):
            logger.warning(f"⚠️ Renewal for order #{oid} has already been completed!")
            await callback.answer("⚠️ این تمدید قبلاً انجام شده است!", show_alert=True)
            try:
                await callback.message.delete()
            except Exception:
                pass
            return
    
    if not order.get('is_extend'):
        if order.get('config_link') or order.get('email'):
            logger.warning(f"⚠️ Order #{oid} has already been processed!")
            await callback.answer("⚠️ این سفارش قبلاً پردازش شده است!", show_alert=True)
            try:
                await callback.message.delete()
            except Exception:
                pass
            return
    
    parent_order_id = order.get('parent_order_id')
    if parent_order_id:
        for existing_oid, existing_order in orders.items():
            if str(existing_oid) != str(oid):
                if (existing_order.get('is_extend') and 
                    existing_order.get('parent_order_id') == parent_order_id and
                    existing_order.get('status') == 'approved' and
                    existing_order.get('new_volume')):
                    
                    approved_date_str = existing_order.get('approved_date', '')
                    if approved_date_str:
                        try:
                            approved_date = datetime.strptime(approved_date_str, "%Y-%m-%d %H:%M:%S")
                            ref_now = now_tehran().replace(tzinfo=None)
                            elapsed = (ref_now - approved_date).total_seconds()
                            
                            if 0 <= elapsed < 300:  # 5 دقیقه
                                await callback.answer(
                                    f"⚠️ این سرویس {int(elapsed)} ثانیه پیش تمدید شده است! لطفاً چند لحظه صبر کنید.",
                                    show_alert=True
                                )
                                return
                        except Exception as e:
                            logger.warning(f"Error parsing date: {e}")
    
    # ==================== ادامه کد اصلی ====================
    uid = order['user_id']
    vol = order.get('volume', 0)
    days = order.get('days', 30)
    price = order.get('price', 0)
    ip_limit = order.get('ip_limit', 0)
    is_extend = parent_order_id is not None
    user_state = user_states.get(uid, {})
    
    parent_order_id = order.get('parent_order_id')
    is_extend = order.get('is_extend', False) or (parent_order_id is not None)
    
    if not is_extend:
        user_state = user_states.get(uid, {})
        is_extend = user_state.get('is_extend', False)
        if is_extend and not parent_order_id:
            parent_order_id = user_state.get('extend_order_id')
    
    logger.info(f"🔍 [confirm_approve_package] is_extend={is_extend}, parent_order_id={parent_order_id}")
    
    payment_method = order.get('payment_method', 'unknown')
    order_type = order.get('type', 'purchase')
    
    PAYMENT_METHODS = {
        'card': {'label': '💳 کارت به کارت', 'emoji': '💳', 'type': 'card'},
        'awaiting_payment': {'label': '💳 کارت به کارت', 'emoji': '💳', 'type': 'card'},
        'receipt': {'label': '💳 کارت به کارت', 'emoji': '💳', 'type': 'card'},
        'balance': {'label': '💰 موجودی حساب', 'emoji': '💰', 'type': 'balance'},
        'balance_pool': {'label': '💰 موجودی حساب', 'emoji': '💰', 'type': 'balance'},
        'balance_extend': {'label': '🔄 موجودی (تمدید)', 'emoji': '🔄', 'type': 'balance_extend'},
        'balance_pool_extend': {'label': '🔄 موجودی (تمدید)', 'emoji': '🔄', 'type': 'balance_extend'},
        'free_coupon': {'label': '🎁 کوپن تخفیف', 'emoji': '🎁', 'type': 'free'},
        'free_coupon_extend': {'label': '🎁 کوپن تخفیف (تمدید)', 'emoji': '🎁', 'type': 'free_extend'},
        'test': {'label': '🧪 تست رایگان', 'emoji': '🧪', 'type': 'test'},
    }
    
    payment_info = PAYMENT_METHODS.get(payment_method, {'label': '❓ نامشخص', 'emoji': '❓', 'type': 'unknown'})
    
    if payment_method == 'unknown' or not payment_method:
        user_state_payment = user_states.get(uid, {})
        payment_type_from_state = user_state_payment.get('payment_type', '')
        
        if payment_type_from_state == 'balance':
            payment_info = {'label': '💰 موجودی حساب', 'emoji': '💰', 'type': 'balance'}
        elif payment_type_from_state in ['card', 'awaiting_payment']:
            payment_info = {'label': '💳 کارت به کارت', 'emoji': '💳', 'type': 'card'}
        elif payment_type_from_state == 'ready_package':
            payment_info = {'label': '📦 بسته آماده', 'emoji': '📦', 'type': 'ready_package'}
        elif payment_type_from_state == 'test':
            payment_info = {'label': '🧪 تست رایگان', 'emoji': '🧪', 'type': 'test'}
    
    if is_extend:
        if payment_info['type'] == 'balance':
            payment_info = {'label': '🔄 موجودی (تمدید)', 'emoji': '🔄', 'type': 'balance_extend'}
        elif payment_info['type'] == 'card':
            payment_info = {'label': '💳 کارت (تمدید)', 'emoji': '💳', 'type': 'card_extend'}
        elif payment_info['type'] == 'free':
            payment_info = {'label': '🎁 کوپن (تمدید)', 'emoji': '🎁', 'type': 'free_extend'}
    
    payment_label = payment_info['label']
    payment_emoji = payment_info['emoji']
    payment_type = payment_info['type']
    
    logger.info(f"💳 [confirm_approve_package] payment method: {payment_method} → {payment_type} ({payment_label})")
    
    # ============================================================
    # ✅ جمع‌آوری selected_inbounds از اولویت‌های مختلف
    # ============================================================
    selected_inbounds = get_user_inbound(uid)
    
    if not selected_inbounds:
        selected_inbounds = order.get('inbound_id', [])
        logger.info(f"📡 [confirm_approve_package] Inbounds from order: {selected_inbounds}")
    else:
        logger.info(f"📡 [confirm_approve_package] Selected inbounds from user_inbound_selection: {selected_inbounds}")
    
    if not selected_inbounds:
        category_id = order.get('category_id')
        if category_id:
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('id') == category_id:
                    cat_inbound_ids = cat.get('inbound_ids', [])
                    if cat_inbound_ids:
                        selected_inbounds = cat_inbound_ids if isinstance(cat_inbound_ids, list) else [cat_inbound_ids]
                    else:
                        cat_inbound = cat.get('inbound_id')
                        if cat_inbound:
                            selected_inbounds = cat_inbound if isinstance(cat_inbound, list) else [cat_inbound]
                    break
    
    if not selected_inbounds:
        default_ids = configs_pool.get('default_inbound_ids', [])
        if default_ids:
            selected_inbounds = default_ids
    
    if not isinstance(selected_inbounds, list):
        selected_inbounds = [selected_inbounds] if selected_inbounds else []
    
    # ✅ ✅ ✅ فیلتر اینباندهای نامعتبر
    selected_inbounds = await filter_valid_inbounds(selected_inbounds)
    
    if not selected_inbounds:
        default_ids = configs_pool.get('default_inbound_ids', [])
        selected_inbounds = await filter_valid_inbounds(default_ids)
        
        if not selected_inbounds:
            await callback.answer(
                "❌ هیچ اینباند معتبری یافت نشد! لطفاً ابتدا اینباندها را بررسی کنید.",
                show_alert=True
            )
            return
    
    logger.info(f"📡 [confirm_approve_package] final filtered inbounds: {selected_inbounds}")
    
    # ✅ category_name با fallback
    category_name = order.get('category_name')
    if not category_name or not str(category_name).strip():
        category_name = get_order_category_name(order, lang)
        if category_name:
            try:
                backfill_order_category(oid)
            except Exception:
                pass

    if not category_name:
        category_name = t('ready_package_272798b27e', lang)

    user_info = get_user(uid)
    user_name = user_info.get('name', f'کاربر_{uid}')
    balance = user_info.get('balance', 0)
    user_name_escaped = html.escape(user_name)
    category_name_escaped = html.escape(category_name)
    
    lang = user_info.get('lang', 'fa')
    
    logger.info(f"📦 [confirm_approve_package] order #{oid} - user: {uid} - renewal: {is_extend} - parent_order_id: {parent_order_id}")
    logger.info(f"📦 [confirm_approve_package] Volume: {vol}GB - Duration: {days}days - price: {price:,}tomans")
    logger.info(f"💳 [confirm_approve_package] payment method: {payment_label}")
    
    await safe_edit_message(
        callback,
        f"⏳ در حال پردازش بسته #{oid}...",
        reply_markup=None
    )
    
    try:
        if order_type in ['ready_package', 'category_purchase']:
            backfill_order_category(oid)
            order = orders.get(str(oid))
    except Exception as e:
        logger.warning(f"Error in backfill: {e}")
    
    # ✅✅✅ اینباندهای فیلترشده رو توی سفارش ذخیره کن
    update_order(
        oid,
        status='approved',
        approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
        inbound_id=selected_inbounds
    )
    await update_user_receipt_review_status(order, 'approved')
    
    await check_referral_bonus(uid)
    if order.get('discount_source') not in ('category', 'none'):
        coupon_consumed = consume_coupon(uid)
    else:
        coupon_consumed = False
        logger.info(f"🏷️ Coupon NOT consumed for order #{oid} (discount_source={order.get('discount_source')})")
    
    if coupon_consumed:
        logger.info(f"🏷️ Coupon for order #{oid} consumed")
    else:
        logger.info(f"ℹ️ No coupon for order #{oid} did not exist or was already consumed")
    
    # ==================== بخش تمدید ====================
    if is_extend and parent_order_id:
        logger.info(f"🔄 [confirm_approve_package] Starting service renewal #{parent_order_id} with package #{oid}")
        
        parent_order = orders.get(str(parent_order_id))
        if parent_order:
            old_volume = parent_order.get('volume', 0)
            old_days = parent_order.get('days', 0)
            old_email = parent_order.get('email', '')
            old_inbound = parent_order.get('inbound_id', [])
            logger.info(f"📊 [confirm_approve_package] Original order: data={old_volume}GB, duration={old_days}days")
        else:
            logger.warning(f"⚠️ [confirm_approve_package] Original order #{parent_order_id} not found!")
            old_volume = 0
            old_days = 0
            old_email = ''
            old_inbound = []
        
        current_inbounds = []
        if old_email:
            current_inbounds = await get_client_inbounds(old_email)
            if not current_inbounds:
                current_inbounds = old_inbound if isinstance(old_inbound, list) else [old_inbound] if old_inbound else []
            logger.info(f"📡 [confirm_approve_package] User\'s current inbounds: {current_inbounds}")
        else:
            current_inbounds = get_user_inbound(uid)
            if not isinstance(current_inbounds, list):
                current_inbounds = [current_inbounds] if current_inbounds else []
            logger.info(f"📡 [confirm_approve_package] Current inbounds from user_inbound_selection: {current_inbounds}")
        
        # ✅ اینباندهای نهایی = همون فیلترشده‌ها
        final_inbounds = selected_inbounds.copy()
        
        logger.info(f"📡 [confirm_approve_package] final filtered inbounds: {final_inbounds}")
        
        if final_inbounds:
            save_user_inbound_selection(uid, final_inbounds)
            logger.info(f"📡 [confirm_approve_package] Final inbounds for user {uid} saved: {final_inbounds}")
        
        _state = user_states.get(uid, {})
        _cat_id = order.get('category_id')
        _cat_name = order.get('category_name')
        _cat_name_en = order.get('category_name_en')
        _pkg_id = order.get('package_id')
        
        if _cat_id is None:
            _cat_id = _state.get('category_id')
        if not _cat_name:
            _cat_name = _state.get('category_name')
        if not _cat_name_en:
            _cat_name_en = _state.get('category_name_en')
        if _pkg_id is None:
            _pkg_id = _state.get('package_id')
        
        if not _cat_name and _cat_id:
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('id') == _cat_id:
                    _cat_name = cat.get('name')
                    _cat_name_en = cat.get('name_en', _cat_name)
                    logger.info(f"✅ category_name recovered from READY_PACKAGES: {_cat_name}")
                    break
        
        success = await extend_service(
            parent_order_id,
            uid,
            vol,
            days,
            new_inbounds=final_inbounds,      # ✅ اینباندهای فیلترشده
            new_ip_limit=ip_limit,
            new_category_id=_cat_id,
            new_category_name=_cat_name,
            new_category_name_en=_cat_name_en,
            new_package_id=_pkg_id,
        )
        
        if success:
            updated_parent = orders.get(str(parent_order_id))
            new_volume = updated_parent.get('volume', 0) if updated_parent else old_volume + vol
            new_days = updated_parent.get('days', 0) if updated_parent else old_days + days
            
            update_order(oid,
                        new_volume=new_volume,
                        new_days=new_days,
                        old_volume=old_volume,
                        old_days=old_days,
                        parent_volume=old_volume,
                        parent_days=old_days,
                        payment_type=payment_type,
                        payment_label=payment_label,
                        inbound_id=final_inbounds)
            
            if uid in user_states:
                user_states[uid].pop('is_extend', None)
                user_states[uid].pop('extend_order_id', None)
                user_states[uid].pop('current_volume', None)
                user_states[uid].pop('current_days', None)
            
            await send_admin_notification('extend', {
                'user_id': uid,
                'volume': vol,
                'days': days,
                'price': price,
                'order_id': oid,
                'parent_order_id': parent_order_id,
                'old_volume': old_volume,
                'old_days': old_days,
                'new_volume': new_volume,
                'new_days': new_days,
                'payment_type': payment_type,
                'payment_label': payment_label,
                'payment_emoji': payment_emoji,
                'balance_before': balance,
                'balance_after': balance,
                'category_name': category_name,
                'inbound_ids': final_inbounds,
                'is_extend': True,
            })
            
            try:
                await callback.message.delete()
            except Exception:
                pass
            
            await send_sticker(uid, 'order_approved', '✅')
            
            success_text = t('b_service_extended_successfu_220b88ae9b', lang)
            
            await bot.send_message(
                uid,
                success_text,
                parse_mode=ParseMode.HTML,
                reply_markup=get_extension_success_keyboard(parent_order_id, lang),
            )
            
            await callback.message.answer(
                f"✅ تمدید بسته آماده #{oid} با موفقیت انجام شد!\n{payment_emoji} {payment_label}\n📡 اینباندها: {final_inbounds}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t('back_to_orders_d29b01f5a2', lang),
                        callback_data="admin_orders"
                    )],
                    [InlineKeyboardButton(
                        text=t('view_user_686cebfd95', lang),
                        callback_data=f"admin_user_{uid}"
                    )]
                ])
            )
            
            logger.info(f"✅ Ready package renewal #{oid} completed successfully - original order: #{parent_order_id}")
            logger.info(f"   📊 Data: {old_volume}GB → {new_volume}GB (+{vol}GB)")
            logger.info(f"   ⏱ Duration: {old_days}days → {new_days}days (+{days}days)")
            logger.info(f"   💳 Payment method: {payment_label}")
            logger.info(f"   📡 Inbounds: {final_inbounds}")
            
            await callback.answer(t('extended_b750492d02', lang))
            return
        else:
            user = get_user(uid)
            update_user(uid, 'balance', user['balance'] + price)
            
            await safe_edit_message(
                callback,
                t('error_extending_service_bala_b1314a9a0e', lang, fa_parts=lambda: (f"{user['balance'] + price:,}", f'{payment_emoji}', f'{payment_label}'), en_parts=lambda: (f"{user['balance'] + price:,}", f'{payment_emoji}', f'{payment_label}')),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t('retry_5550d5f4fa', lang),
                        callback_data=f"confirm_approve_package_{oid}"
                    )],
                    [InlineKeyboardButton(
                        text=t('back_to_orders_d29b01f5a2', lang),
                        callback_data="admin_orders"
                    )]
                ])
            )
            await callback.answer("❌ خطا در تمدید", show_alert=True)
            return
    
    # ==================== بخش خرید جدید ====================
    if is_senai_panel_enabled():
        email = f"user{uid}_{int(datetime.now().timestamp())}"
        
        # ✅ از اینباندهای فیلترشده استفاده کن (نه چیز دیگه)
        sub = await xui_create_client_with_inbound(
            email, vol, days, user_name, uid,
            selected_inbounds,
            ip_limit=ip_limit
        )
        
        if sub:
            update_order(oid, config_link=sub, email=email, payment_method=payment_method, inbound_id=selected_inbounds)
            
            if log_system:
                await log_system.log_config_created(uid, oid, email, vol, days)
                await log_system.log_order_approved(oid, uid, vol, days, price)
            
            try:
                await callback.message.delete()
            except Exception:
                pass
            
            await send_config_with_qr_option(uid, oid, vol, days, price, sub, lang)
            
            try:
                await bot.send_message(
                    uid,
                    f"{premium_emoji('star', '⭐')} {t('please_rate_our_service_e52df3f954', lang)}",
                    reply_markup=get_feedback_keyboard(oid, lang)
                )
            except Exception as e:
                logger.error(f"Error sending feedback request: {e}")
            
            inbound_info = f"اینباندها: {selected_inbounds if selected_inbounds else 'پیش‌فرض'}"
            
            success_text = f"""
✅ بسته آماده #{oid} با موفقیت تایید شد!
👤 کاربر: {user_name_escaped} ({uid})
📦 {vol}GB / {days} روز
💰 قیمت: {price:,} تومان
{payment_emoji} روش پرداخت: {payment_label}
📡 دسته: {category_name_escaped}
📡 {inbound_info}
🔗 لینک: {sub[:40]}...
"""
            
            await callback.message.answer(
                success_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t('back_to_orders_d29b01f5a2', lang),
                        callback_data="admin_orders"
                    )],
                    [InlineKeyboardButton(
                        text=t('view_user_686cebfd95', lang),
                        callback_data=f"admin_user_{uid}"
                    )]
                ]),
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"✅ Ready package #{oid} approved successfully - inbounds: {selected_inbounds}")
            logger.info(f"   💳 Payment method: {payment_label}")
            
        else:
            user = get_user(uid)
            update_user(uid, 'balance', user['balance'] + price)
            
            await safe_edit_message(
                callback,
                t('error_creating_client_for_pa_8f60245c0a', lang, fa_parts=lambda: (f'{oid}', f"{user['balance'] + price:,}", f'{payment_emoji}', f'{payment_label}'), en_parts=lambda: (f'{oid}', f"{user['balance'] + price:,}", f'{payment_emoji}', f'{payment_label}')),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t('retry_5550d5f4fa', lang),
                        callback_data=f"confirm_approve_package_{oid}"
                    )],
                    [InlineKeyboardButton(
                        text=t('back_14968ad63f', lang),
                        callback_data="admin_orders"
                    )]
                ])
            )
            
            await callback.answer("❌ خطا در ساخت کلاینت", show_alert=True)
            return
    else:  # پنل غیرفعال
        user_states[callback.from_user.id] = {
            'awaiting_config': True,
            'order_id': oid,
            'user_id': uid,
            'volume': vol,
            'days': days,
            'price': price
        }
        
        # ✅ استفاده از safe_edit_message به جای edit_text
        await safe_edit_message(
            callback,
            f"⏳ منتظر کانفیگ از ادمین برای بسته #{oid}...\n"
            f"👤 کاربر: {user_name_escaped} ({uid})\n"
            f"📦 {vol}GB / {days} روز\n"
            f"{payment_emoji} روش پرداخت: {payment_label}\n"
            f"📡 دسته: {category_name_escaped}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('cancel_ed04d2e1eb', lang),
                    callback_data="admin_orders"
                )]
            ])
        )
        
        await callback.message.answer("📝 لطفاً لینک کانفیگ را برای این سفارش ارسال کنید:")
        await callback.answer("⏳ منتظر کانفیگ...")
        return
    
    await callback.answer("✅ بسته آماده تایید شد")
@router.callback_query(F.data.startswith("select_inbound_"))
@admin_only
async def select_inbound_for_order(callback: CallbackQuery):
    """انتخاب اینباند برای یک سفارش خاص"""
    
    parts = callback.data.split("_")
    
    try:
        oid = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_order_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    if len(parts) < 4:
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    inbound_value = parts[3]
    
    order = orders.get(str(oid))
    if not order:
        await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    uid = order['user_id']
    
    if inbound_value == "default":
        default_id = configs_pool.get('default_inbound_id')
        if default_id:
            save_user_inbound_selection(uid, default_id)
            await callback.answer(f"✅ اینباند پیش‌فرض ({default_id}) برای کاربر انتخاب شد", show_alert=True)
        else:
            await callback.answer("❌ اینباند پیش‌فرض تنظیم نشده است", show_alert=True)
            return
    else:
        try:
            inbound_id = int(inbound_value)
            save_user_inbound_selection(uid, inbound_id)
            await callback.answer(f"✅ اینباند {inbound_id} برای کاربر انتخاب شد", show_alert=True)
        except ValueError:
            await callback.answer("❌ اینباند نامعتبر", show_alert=True)
            return
    await approve_receipt(callback)
@router.callback_query(F.data.startswith("confirm_approve_"))
@admin_only
async def confirm_approve_with_inbound(callback: CallbackQuery):
    """تایید نهایی سفارش با اینباند انتخاب شده - با تشخیص تمدید و فیلتر اینباند"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    try:
        oid = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_order_process_error', lang), show_alert=True)
        return

    try:
        async with order_guard.lock_order(oid):
            return await _confirm_approve_with_inbound_impl(callback, oid)
    except PaymentInProgressError:
        logger.warning(f"⚠️ Order #{oid} inbound approval already in progress! Blocking duplicate call.")
        msg = (
            "⏳ این سفارش در حال حاضر در حال پردازش و تایید است..."
            if lang == "fa"
            else "⏳ This order is already being processed and approved..."
        )
        return await callback.answer(msg, show_alert=True)


async def _confirm_approve_with_inbound_impl(callback: CallbackQuery, oid: int):
    order = orders.get(str(oid))
    if not order:
        return await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)

    # ✅ جلوگیری از تایید مجدد
    if order.get('status') == 'approved':
        await callback.answer("⚠️ این سفارش قبلاً تایید شده است!", show_alert=True)
        return
    if order.get('status') in ['rejected', 'cancelled', 'deleted']:
        await callback.answer("⚠️ این سفارش قبلاً رد یا لغو شده است!", show_alert=True)
        return
    
    uid = order['user_id']
    vol = order.get('volume', 0)
    days = order.get('days', 30)
    price = order.get('price', 0)
    parent_order_id = order.get('parent_order_id')
    is_extend = parent_order_id is not None
    
    user_info = get_user(uid)
    raw_name = user_info.get('name', f'کاربر_{uid}')
    user_name_panel = raw_name          # برای کامنت پنل (خام)
    user_name = html.escape(raw_name)   # برای پیام HTML
    lang = user_info.get('lang', 'fa')
    
    await send_sticker(uid, 'order_approved', '✅')
    
    logger.info(f"📝 final approval of order #{oid} - user: {uid} - {vol}GB/{days}days - amount: {price:,}tomans - renewal: {is_extend}")
    
    # ============================================================
    # ✅ فیلتر اینباندها (قبل از هر کاری)
    # ============================================================
    inbound_id = get_user_inbound(uid)
    
    if isinstance(inbound_id, list):
        inbound_id = [ib for ib in inbound_id if ib]
    elif inbound_id:
        inbound_id = [inbound_id]
    else:
        inbound_id = []
    
    inbound_id = await filter_valid_inbounds(inbound_id)
    
    if not inbound_id:
        default_ids = configs_pool.get('default_inbound_ids', [])
        inbound_id = await filter_valid_inbounds(default_ids)
        
        if not inbound_id:
            await callback.answer(
                "❌ هیچ اینباند معتبری یافت نشد! لطفاً ابتدا اینباندها را بررسی کنید.",
                show_alert=True
            )
            return
    
    logger.info(f"📡 [confirm_approve_with_inbound] final inbounds: {inbound_id}")
    
    # ============================================================
    # به‌روزرسانی سفارش و کوپن و رفرال
    # ============================================================
    update_order(
        oid,
        status='approved',
        approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
        inbound_id=inbound_id,   # ✅ اینباندهای فیلترشده رو ذخیره کن
    )
    await update_user_receipt_review_status(order, 'approved')
    
    if order.get('discount_source') not in ('category', 'none'):
        coupon_consumed = consume_coupon(uid)
        if coupon_consumed:
            logger.info(f"🏷️ Coupon for order #{oid} consumed")
    else:
        logger.info(f"🏷️ Coupon NOT consumed for order #{oid} (discount_source={order.get('discount_source')})")
    
    if not is_extend:
        referral_result = await check_referral_bonus(uid)
        if referral_result:
            logger.info(f"✅ Referral reward for user {uid} applied")
            if log_system:
                await log_system.log_user_action(
                    uid,
                    "Received referral reward",
                    "For purchasing the first service"
                )
    
    # ============================================================
    # بخش تمدید
    # ============================================================
    if is_extend and parent_order_id:
        await safe_edit_message(
            callback,
            f"⏳ در حال تمدید سرویس #{parent_order_id}..."
        )
        
        _state = user_states.get(uid, {})
        _cat_id = order.get('category_id') or _state.get('category_id')
        _cat_name = order.get('category_name') or _state.get('category_name')
        _cat_name_en = order.get('category_name_en') or _state.get('category_name_en')
        _pkg_id = order.get('package_id') or _state.get('package_id')
        ip_limit = order.get('ip_limit', 0)
        
        try:
            success = await extend_service(
                parent_order_id,
                uid,
                vol,
                days,
                new_inbounds=inbound_id,      # ✅ اینباندهای فیلترشده پاس بده
                new_ip_limit=ip_limit,        # ✅ ip_limit هم پاس بده
                new_category_id=_cat_id,
                new_category_name=_cat_name,
                new_category_name_en=_cat_name_en,
                new_package_id=_pkg_id,
            )
        except Exception as e:
            logger.error(f"❌ Error in extend_service: {e}", exc_info=True)
            success = False
        
        if success:
            if uid in user_states:
                user_states[uid].pop('is_extend', None)
                user_states[uid].pop('extend_order_id', None)
                user_states[uid].pop('current_volume', None)
                user_states[uid].pop('current_days', None)
            
            try:
                await bot.send_message(
                    uid,
                    t('your_service_has_been_extend_c243fe1cc2', lang),
                    reply_markup=get_extension_success_keyboard(parent_order_id, lang),
                )
                logger.info(f"📨 Renewal confirmation message to user {uid} sent")
            except Exception as e:
                logger.error(f"❌ Error sending message to user {uid}: {e}")
            
            success_text = t('b_service_extended_successfu_96318ba4a3', lang, fa_parts=lambda: (f'{user_name}', f'{uid}', f'{parent_order_id}', f'{vol}', f'{days}', f'{price:,}', f"{', '.join(map(str, inbound_id))}"), en_parts=lambda: (f'{user_name}', f'{uid}', f'{parent_order_id}', f'{vol}', f'{days}', f'{price:,}', f"{', '.join(map(str, inbound_id))}"))
            
            await safe_edit_message(
                callback,
                success_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t('back_to_orders_d29b01f5a2', lang),
                        callback_data="admin_orders"
                    )]
                ])
            )
            
            logger.info(f"✅ Renewal for order #{oid} completed successfully - original order: #{parent_order_id}")
            await callback.answer(t('extended_b750492d02', lang))
            return
        else:
            user = get_user(uid)
            update_user(uid, 'balance', user['balance'] + price)
            
            try:
                await bot.send_message(
                    uid,
                    t('error_extending_service_amou_50b287b7b6', lang)
                )
            except Exception:
                pass
            
            await safe_edit_message(
                callback,
                t('error_extending_service_bala_295f673b6f', lang),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t('back_to_orders_d29b01f5a2', lang),
                        callback_data="admin_orders"
                    )]
                ])
            )
            await callback.answer("❌ خطا در تمدید", show_alert=True)
            return
    
    # ============================================================
    # بخش خرید جدید
    # ============================================================
    if is_senai_panel_enabled():
        await safe_edit_message(
            callback,
            f"⏳ در حال ساخت کلاینت برای سفارش #{oid}..."
        )
        
        email = f"user{uid}_{int(datetime.now().timestamp())}"
        ip_limit = order.get('ip_limit', 0)
        
        # ✅ دیگه inbound_id رو از get_user_inbound نمی‌گیریم - همون فیلترشده استفاده می‌کنیم
        sub = await xui_create_client_with_inbound(
            email, vol, days, user_name_panel, uid,
            inbound_id, ip_limit=ip_limit
        )
        
        if sub:
            update_order(oid, config_link=sub, email=email, payment_method='card')
            
            if log_system:
                await log_system.log_config_created(uid, oid, email, vol, days)
                await log_system.log_order_approved(oid, uid, vol, days, price)
            
            CustomLogger.log_event(
                'ORDER_APPROVED',
                f'Order #{oid} approved - {vol}GB/{days} days - {price:,} Toman - inbound: {inbound_id or "Default"}',
                uid
            )
            
            await send_config_with_qr_option(uid, oid, vol, days, price, sub, lang)
            
            try:
                await bot.send_message(
                    uid,
                    f"{premium_emoji('star', '⭐')} {t('please_rate_our_service_e52df3f954', lang)}",
                    reply_markup=get_feedback_keyboard(oid, lang)
                )
            except Exception as e:
                logger.error(f"Error sending feedback request: {e}")
            
            inbound_info = f"اینباند: {', '.join(map(str, inbound_id)) or 'پیش‌فرض'}"
            
            success_text = f"""
✅ سفارش #{oid} با موفقیت تایید شد!
👤 کاربر: {user_name} ({uid})
📦 {vol}GB / {days} روز
💰 قیمت: {price:,} تومان
📡 {inbound_info}
🔗 لینک: {sub[:40]}...
"""
            
            await safe_edit_message(
                callback,
                success_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t('back_to_orders_d29b01f5a2', lang),
                        callback_data="admin_orders"
                    )]
                ])
            )
            
            logger.info(f"✅ Order #{oid} approved successfully - client created")
        else:
            user = get_user(uid)
            update_user(uid, 'balance', user['balance'] + price)
            
            logger.error(f"❌ Error creating client for order #{oid}")
            if log_system:
                await log_system.log_error(
                    Exception("Failed to create client in panel"),
                    "confirm_approve_with_inbound",
                    uid
                )
            
            await safe_edit_message(
                callback,
                f"❌ خطا در ساخت کلاینت برای سفارش #{oid}\n"
                f"💰 موجودی کاربر برگشت داده شد.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t('retry_5550d5f4fa', lang),
                        callback_data=f"confirm_approve_{oid}"
                    )],
                    [InlineKeyboardButton(
                        text=t('back_14968ad63f', lang),
                        callback_data="admin_orders"
                    )]
                ])
            )
            
            await callback.answer("❌ خطا در ساخت کلاینت", show_alert=True)
            return
    else:
        user_states[callback.from_user.id] = {
            'awaiting_config': True,
            'order_id': oid,
            'user_id': uid,
            'volume': vol,
            'days': days,
            'price': price
        }
        
        await safe_edit_message(
            callback,
            f"⏳ منتظر کانفیگ از ادمین برای سفارش #{oid}...\n"
            f"👤 کاربر: {user_name} ({uid})\n"
            f"📦 {vol}GB / {days} روز",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('cancel_ed04d2e1eb', lang),
                    callback_data="admin_orders"
                )]
            ])
        )
        
        await callback.message.answer("📝 لطفاً لینک کانفیگ را برای این سفارش ارسال کنید:")
        await callback.answer("⏳ منتظر کانفیگ...")
        return
    
    await callback.answer("✅ سفارش تایید شد")




    
    
    
    
@router.callback_query(F.data.regexp(r"^reject_(?:receipt_)?\d+$"))
@admin_only(message='⛔ محدود!')
async def reject_receipt(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    
    parts = callback.data.split("_")
    if len(parts) < 2:
        await callback.answer(t('i18n_invalid_data_format', lang), show_alert=True)
        return
    
    try:
        if parts[1] == 'receipt' and len(parts) > 2:
            order_id = int(parts[2])
        elif len(parts) >= 2 and parts[1].isdigit():
            order_id = int(parts[1])
        else:
            await callback.answer(t('i18n_invalid_order_id', lang), show_alert=True)
            return
    except (ValueError, IndexError):
        await callback.answer(t('i18n_order_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    order = orders.get(str(order_id))
    if not order:
        await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return
    
    # ✅ بررسی وضعیت فعلی سفارش
    current_status = order.get('status')
    
    # اگر سفارش قبلاً تایید شده باشد
    if current_status == 'approved':
        await callback.answer(
            t('i18n_receipt_already_approved_cannot_reject', lang),
            show_alert=True
        )
        try:
            await callback.message.delete()
        except Exception:
            pass
        return
    
    # اگر سفارش قبلاً رد شده باشد
    if current_status in ['rejected', 'cancelled', 'deleted']:
        await callback.answer(t('i18n_order_already_rejected_only', lang), show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return
    
    # ✅ بررسی اینکه آیا کانفیگ ساخته شده است
    if order.get('config_link') or order.get('email'):
        await callback.answer(
            t('i18n_receipt_processed_config_exists', lang),
            show_alert=True
        )
        try:
            await callback.message.delete()
        except Exception:
            pass
        return
    
    # ✅ حالا می‌توانیم رد کنیم
    update_order(order_id, status='rejected')
    await update_user_receipt_review_status(order, 'rejected')
    user_id = order['user_id']
    user_lang = order.get('receipt_status_lang') or get_user(user_id).get('lang', 'fa')
    await send_sticker(user_id, 'order_rejected', '😭')
    rejection_text = (
        t('b_receipt_for_order_was_reje_641b06a5d2', user_lang, fa_parts=lambda: (f'{order_id}',), en_parts=lambda: (f'{order_id}',))
    )
    try:
        await bot.send_message(
            user_id,
            rejection_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=t('main_menu_0cdd07a7cc', user_lang),
                    callback_data="back_to_main",
                )
            ]]),
        )
    except Exception as e:
        logger.error(
            'Failed to send the receipt-rejection message for order #%s to user %s: %s',
            order_id,
            user_id,
            e,
            exc_info=True,
        )
    
    if log_system:
        await log_system.log_order_rejected(order_id, order['user_id'], "Invalid receipt")
    
    CustomLogger.log_event('ORDER_REJECTED', f'Order #{order_id} was rejected by an admin', order['user_id'])
    
    # ✅ حذف پیام از چت ادمین
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        try:
            if callback.message.photo:
                await callback.message.edit_caption(
                    caption=t('i18n_receipt_rejected_admin_caption', lang, fa_parts=lambda: (callback.message.caption, now_tehran().strftime('%H:%M:%S')), en_parts=lambda: (callback.message.caption, now_tehran().strftime('%H:%M:%S'))),
                    parse_mode=ParseMode.HTML,
                    reply_markup=None
                )
            else:
                await callback.message.edit_text(
                    t('i18n_receipt_rejected_admin_caption', lang, fa_parts=lambda: (callback.message.text, now_tehran().strftime('%H:%M:%S')), en_parts=lambda: (callback.message.text, now_tehran().strftime('%H:%M:%S'))),
                    parse_mode=ParseMode.HTML,
                    reply_markup=None
                )
        except Exception:
            pass
    
    await callback.answer(t('i18n_order_rejected_and_message_deleted', lang))

@router.callback_query(F.data == "admin_close_msg")
@admin_only(answer_on_denied=False)
async def admin_close_msg(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await safe_answer(callback)
    
    
@router.callback_query(F.data.startswith("approve_direct_"))
@admin_only(message='⛔ دسترسی محدود!', return_answer=False)
async def approve_direct(callback: CallbackQuery):
    """تایید مستقیم سفارش از پیام فیش"""
    admin_lang = get_user(callback.from_user.id).get('lang', 'fa')

    try:
        order_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_order_process_error', admin_lang), show_alert=True)
        return

    try:
        async with order_guard.lock_order(order_id):
            return await _approve_direct_impl(callback, order_id)
    except PaymentInProgressError:
        logger.warning(f"⚠️ Order #{order_id} direct approval already in progress! Blocking duplicate call.")
        msg = (
            "⏳ این سفارش در حال حاضر در حال پردازش و تایید است..."
            if admin_lang == "fa"
            else "⏳ This order is already being processed and approved..."
        )
        return await callback.answer(msg, show_alert=True)


async def _approve_direct_impl(callback: CallbackQuery, order_id: int):
    admin_lang = get_user(callback.from_user.id).get('lang', 'fa')
    order = orders.get(str(order_id))

    if not order:
        await callback.answer(t('i18n_order_not_found', admin_lang), show_alert=True)
        return

    if order.get('status') == 'approved':
        await callback.answer("⚠️ این سفارش قبلاً تایید شده است!", show_alert=True)
        return
    
    user_id = order['user_id']
    volume = order['volume']
    days = order['days']
    price = order['price']
    user_info = get_user(user_id)
    user_name = user_info.get('name', f'کاربر_{user_id}')
    
    await callback.answer(t('i18n_processing_please_wait', admin_lang))
    update_order(order_id, status='approved', approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"))
    await update_user_receipt_review_status(order, 'approved')
    if log_system:
        await log_system.log_order_approved(order_id, user_id)
    await check_referral_bonus(user_id)
    if is_senai_panel_enabled():
        timestamp = int(datetime.now().timestamp())
        email = f"user{user_id}_{timestamp}"
        sub_link = await xui_create_client_with_inbound(email, volume, days, user_name, user_id)
        
        if sub_link:
            update_order(order_id, config_link=sub_link, email=email, payment_method='card')
            lang = get_user(user_id).get('lang', 'fa')
            
            await send_config_with_qr_option(user_id, order_id, volume, days, price, sub_link, lang)
            
            try:
                await bot.send_message(user_id,
                    f"{premium_emoji('star', '⭐')} {t('please_rate_our_service_e52df3f954', lang)}",
                    reply_markup=get_feedback_keyboard(order_id, lang)
                )
            except Exception:
                pass
            new_text = callback.message.caption + f"\n\n✅ <b>تایید شد!</b>\n👤 {user_name}\n🔗 لینک: {sub_link[:40]}..."
            try:
                await callback.message.edit_caption(caption=new_text, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        else:
            await callback.answer(t('i18n_client_create_error', admin_lang), show_alert=True)
    else:
        await callback.answer(t('i18n_order_approved_send_config_manually', admin_lang), show_alert=True)
        
        
@router.callback_query(F.data.startswith("reject_direct_"))
@admin_only(message='⛔ دسترسی محدود!', return_answer=False)
async def reject_direct(callback: CallbackQuery):
    """رد مستقیم سفارش از پیام فیش"""
    
    order_id = int(callback.data.split("_")[2])
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    order = orders.get(str(order_id))
    
    if not order:
        await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    update_order(order_id, status='rejected')
    user_lang = get_user(order['user_id']).get('lang', 'fa')
    
    try:
        await bot.send_message(order['user_id'],
            f"{premium_emoji('danger', '❌')} {t('order_has_been_rejected_0b53a79310', user_lang, fa_format_args=lambda: ((order_id,), {}), en_parts=lambda: (f'{order_id}',))}"
        )
    except Exception:
        pass
    new_text = callback.message.caption + "\n\n❌ <b>رد شد!</b>"
    try:
        await callback.message.edit_caption(caption=new_text, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    
    await callback.answer(t('i18n_order_rejected_short', lang), show_alert=True)
@router.message(F.document)
@router.message(F.video)
@router.message(F.audio)
@router.message(F.voice)
@router.message(F.video_note)
@router.message(F.sticker)
@router.message(F.animation)
async def handle_wrong_file_type(message: Message):
    user_id = message.from_user.id
    user_state = user_states.get(user_id, {})
    if user_state.get('awaiting_chat'):
        await handle_chat_message(message)
        return
    if user_id == ADMIN_ID_INT and user_state.get('awaiting_chat_reply'):
        await admin_chat_reply(message)
        return
    if user_state.get('awaiting_receipt', False):
        lang = get_user(user_id).get('lang', 'fa')
        
        if await block_unauthorized(message, user_id):
            return
        
        await message.reply(
            t('b_only_receipt_photos_are_ac_fe09d74191', lang),
            parse_mode=ParseMode.HTML
        )
            
            
def get_order_category_name(order: dict, lang: str = "fa") -> str:
    """
    دریافت نام دسته برای یک سفارش - با fallback چند مرحله‌ای
    1. از category_name_en / category_name خود سفارش (بر اساس زبان)
    2. از READY_PACKAGES با category_id
    3. رشته خالی
    """
    # 1️⃣ مستقیم از سفارش (بر اساس زبان)
    if lang == "en":
        name_en = order.get('category_name_en')
        if name_en and str(name_en).strip():
            return str(name_en).strip()
        # fallback به فارسی اگه انگلیسی نبود
        name_fa = order.get('category_name')
        if name_fa and str(name_fa).strip():
            return str(name_fa).strip()
    else:
        name_fa = order.get('category_name')
        if name_fa and str(name_fa).strip():
            return str(name_fa).strip()
        # fallback به انگلیسی اگه فارسی نبود
        name_en = order.get('category_name_en')
        if name_en and str(name_en).strip():
            return str(name_en).strip()

    # 2️⃣ از READY_PACKAGES با category_id
    cat_id = order.get('category_id')
    if cat_id:
        for cat in READY_PACKAGES.get('categories', []):
            if cat.get('id') == cat_id:
                if lang == "en":
                    return cat.get('name_en') or cat.get('name') or ""
                return cat.get('name') or ""

    return ""


def backfill_order_category(order_id: int) -> bool:
    """
    پر کردن category_name و category_name_en در سفارش از روی category_id
    برمی‌گرداند True اگه چیزی تغییر کرد
    """
    order = orders.get(str(order_id))
    if not order:
        return False

    category_id = order.get('category_id')
    if not category_id:
        return False

    current_name = order.get('category_name')
    current_name_en = order.get('category_name_en')

    # ✅ اگه هر دو پر باشن → کاری نداریم
    if (current_name and str(current_name).strip()
        and current_name_en and str(current_name_en).strip()):
        return False

    # جستجو در READY_PACKAGES
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            name_fa = cat.get('name') or ""
            name_en = cat.get('name_en') or name_fa

            changed = False
            if not current_name or not str(current_name).strip():
                order['category_name'] = name_fa
                changed = True
            if not current_name_en or not str(current_name_en).strip():
                order['category_name_en'] = name_en
                changed = True

            if changed:
                order['updated_at'] = now_tehran_iso()
                save_json(DB_FILES['orders'], orders)
                logger.info(
                    f"✅ category_name / name_en for order #{order_id} was filled: "
                    f"{name_fa} / {name_en}"
                )
                return True

            return False

    return False



# [Phase 5] my_configs, show_all_my_configs, view_single_config, my_account, order_status, coupon_status, invite_friends, change_language, and support/ticket handlers moved to routers (configs_view, user_account, support)


@router.callback_query(F.data == "admin_orders")
@admin_only(answer_on_denied=False)
async def admin_orders(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    valid_orders = get_valid_orders()
    pending_purchase = [o for o in valid_orders.values() 
                        if o.get('type') == 'purchase' 
                        and o.get('status') == 'pending']
    pending_ready_package = [o for o in valid_orders.values() 
                             if o.get('type') in ['ready_package', 'category_purchase'] 
                             and o.get('status') == 'pending']
    pending_balance = [o for o in valid_orders.values() 
                       if o.get('type') == 'balance_charge' 
                       and o.get('status') == 'pending_balance_charge']
    total_pending = len(pending_purchase) + len(pending_ready_package) + len(pending_balance)
    
    logger.info(f"admin views order list - purchases: {len(pending_purchase)}, ready packages: {len(pending_ready_package)}, recharge: {len(pending_balance)}")
    
    if total_pending == 0:
        text = t('no_pending_orders_f1babe9ec9', lang)
        text += f"\n<code>🕐 {now_tehran().strftime('%H:%M:%S')}</code>"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('refresh_cda5094083', lang), callback_data="admin_orders")],
            [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
        ])
        await safe_edit_message(callback, text, reply_markup=keyboard)
        await safe_answer(callback)
        return
    
    buttons = []
    for o in pending_purchase:
        user_display = await get_user_display_name(o['user_id'])
        buttons.append([InlineKeyboardButton(
            text=f"🛒 📸 #{o['order_id']} - {user_display} - {o.get('price', 0):,}",
            callback_data=f"view_order_{o['order_id']}"
        )])
    for o in pending_ready_package:
        user_display = await get_user_display_name(o['user_id'])
        category_name = o.get('category_name', 'بسته')
        icon = "📦"
        category_id = o.get('category_id')
        if category_id:
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('id') == category_id:
                    icon = cat.get('icon', '📦')
                    break
        
        buttons.append([InlineKeyboardButton(
            text=f"{icon} 📸 #{o['order_id']} - {user_display} - {category_name} - {o.get('price', 0):,}",
            callback_data=f"view_order_{o['order_id']}"
        )])
    for o in pending_balance:
        user_display = await get_user_display_name(o['user_id'])
        buttons.append([InlineKeyboardButton(
            text=f"💰 📸 #{o['order_id']} - {user_display} - {o.get('amount', 0):,}",
            callback_data=f"view_balance_{o['order_id']}"
        )])
    buttons.append([InlineKeyboardButton(text=t('refresh_cda5094083', lang), callback_data="admin_orders")])
    buttons.append([InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")])
    
    text = t('b_pending_orders_b_eac487c5b8', lang, fa_parts=lambda: (f'{total_pending}',), en_parts=lambda: (f'{total_pending}',))
    text += t('purchase_package_top_up_5f2bc35060', lang, fa_parts=lambda: (f'{len(pending_purchase)}', f'{len(pending_ready_package)}', f'{len(pending_balance)}'), en_parts=lambda: (f'{len(pending_purchase)}', f'{len(pending_ready_package)}', f'{len(pending_balance)}'))
    text += f"<code>🕐 {now_tehran().strftime('%H:%M:%S')}</code>"
    text += t('only_orders_with_receipt_sen_406fcb7c40', lang)
    
    await safe_edit_message(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)

# ==================== ماژول‌های روتر فاز ۲.۴ (مدیریت بکاپ‌ها و بازگردانی) ====================
@router.callback_query(F.data.startswith("view_order_"))
@admin_only(answer_on_denied=False)
async def view_order(callback: CallbackQuery):
    """مشاهده جزئیات سفارش - با نمایش IP Limit و اطلاعات کامل"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    order_id = int(callback.data.split("_")[2])
    order = orders.get(str(order_id))
    
    if not order:
        logger.warning(f"Order #{order_id} not found")
        await callback.answer(t('order_not_found_075d800b08', lang), show_alert=True)
        return
    
    try:
        u = await bot.get_chat(order['user_id'])
        uname = html.escape(u.first_name or t('i18n_user_fallback_name_noarg', lang))
        username = html.escape(u.username or "")
    except Exception:
        uname = t('user_392d8d9d46', lang)
        username = ""

    logger.info(f"admin viewing order #{order_id}")

    # ✅ اطلاعات پایه
    ip_limit = order.get('ip_limit', 0)
    ip_display = t('i18n_ip_limit_display', lang, fa_parts=lambda: (f'{ip_limit}',), en_parts=lambda: (f'{ip_limit}',)) if ip_limit > 0 else t('i18n_ip_limit_unlimited', lang)
    order_type = order.get('type', 'purchase')
    order_status = order.get('status', t('i18n_unknown', lang))
    category_name = order.get('category_name')
    if not category_name or not str(category_name).strip():
        category_name = get_order_category_name(order, lang)
        if category_name:
            try:
                backfill_order_category(order_id)
            except Exception as e:
                logger.warning(f"Error backfilling category: {e}")
    category_id = order.get('category_id')
    package_id = order.get('package_id')
    payment_method = order.get('payment_method', '')
    payment_label = order.get('payment_label', '')
    created_at = order.get('created_at', '')
    updated_at = order.get('updated_at', '')
    approved_date = order.get('approved_date', '')
    email = order.get('email', '')
    sub_link = order.get('sub_link', '')
    config_link = order.get('config_link', '')
    notes = order.get('notes', '')
    is_active_in_panel = order.get('is_active_in_panel', False)
    is_test = order.get('is_test', False)
    inbound_details = order.get('inbound_details', [])
    inbound_id = order.get('inbound_id', [])
    parent_order_id = order.get('parent_order_id')
    is_extend = order.get('is_extend', False)
    volume_unit = order.get('volume_unit', 'GB')
    
    # ✅ تبدیل لیست اینباند به لیست اگر نیست
    if not isinstance(inbound_id, list):
        inbound_id = [inbound_id] if inbound_id else []
    
    # ✅ آیکون دسته‌بندی
    icon = "📦"
    if category_id:
        for cat in READY_PACKAGES.get('categories', []):
            if cat.get('id') == category_id:
                icon = cat.get('icon', '📦')
                break
    
    # ✅ اطلاعات پکیج
    package_info = ""
    if package_id and category_id:
        for cat in READY_PACKAGES.get('categories', []):
            if cat.get('id') == category_id:
                for pkg in cat.get('packages', []):
                    if pkg.get('id') == package_id:
                        package_info = t('i18n_package_volume_days', lang, fa_parts=lambda: (f"{pkg.get('volume', 0)}", f"{pkg.get('days', 0)}"), en_parts=lambda: (f"{pkg.get('volume', 0)}", f"{pkg.get('days', 0)}"))
                        break
                break
    
    # ✅ وضعیت‌ها
    status_emoji_fa = {
        'awaiting_payment': '⏳ در انتظار پرداخت',
        'pending': '📸 فیش ارسال شده',
        'pending_balance_charge': '📸 فیش ارسال شده (شارژ)',
        'approved': '✅ تایید شده',
        'rejected': '❌ رد شده',
        'cancelled': '🚫 لغو شده',
        'deleted': '🗑️ حذف شده'
    }
    status_emoji_en = {
        'awaiting_payment': '⏳ Waiting for payment',
        'pending': '📸 Receipt sent',
        'pending_balance_charge': '📸 Receipt sent (Top-up)',
        'approved': '✅ Approved',
        'rejected': '❌ Rejected',
        'cancelled': '🚫 Cancelled',
        'deleted': '🗑️ Deleted'
    }
    
    status_text = status_emoji_fa.get(order_status, f"⚠️ {order_status}") if lang == 'fa' else status_emoji_en.get(order_status, f"⚠️ {order_status}")
    
    # ✅ نمایش حجم
    volume = order.get('volume', 0)
    if volume == 0:
        volume_display = t('unlimited_b72dd6e126', lang)
    else:
        volume_display = f"{volume} {volume_unit}"
    
    # ✅ نمایش قیمت
    price = order.get('price', 0)
    if order_type == 'balance_charge':
        price = order.get('amount', 0)
    
    # ✅ متن اصلی
    if lang == "fa":
        text = t('b_order_b_b_user_b_467ac0c5fb', lang, fa_parts=lambda: (f"{premium_emoji('order_id', '🆔')}", f'{order_id}', f"{premium_emoji('user', '👤')}", f'{uname}'))
        if username:
            text += t('b_username_b_1bcbaa2361', lang, fa_parts=lambda: (f'{username}',))
        
        text += t('b_user_id_b_code_code_40d1d8fdd6', lang, fa_parts=lambda: (f"{order.get('user_id')}",))
        
        # ✅ نوع سفارش
        if order_type == 'balance_charge':
            amount = order.get('amount', 0)
            text += t('b_type_b_balance_top_up_b_am_46bbab34fd', lang, fa_parts=lambda: (f'{amount:,}',))
        elif order_type in ['ready_package', 'category_purchase']:
            text += t('b_type_b_ready_package_b_vol_29c4b2a112', lang, fa_parts=lambda: (f'{icon}', f"{category_name or t('i18n_unknown', lang)}", f'{package_info}', f'{volume_display}', f"{order.get('days', 0)}"))
        elif order_type == 'test':
            text += t('b_type_b_free_test_b_volume_6e4d71cb83', lang, fa_parts=lambda: (f'{volume_display}', f"{order.get('days', 0)}"))
        elif order_type == 'extend':
            text += t('b_type_b_service_extension_b_27afae67a6', lang, fa_parts=lambda: (f'{volume_display}', f"{order.get('days', 0)}"))
            if parent_order_id:
                text += t('b_parent_order_b_025ac7e2d8', lang, fa_parts=lambda: (f'{parent_order_id}',))
        else:
            text += t('b_type_b_regular_purchase_b_f4372d47fb', lang, fa_parts=lambda: (f'{volume_display}', f"{order.get('days', 0)}"))
        
        # ✅ اطلاعات پرداخت
        text += t('b_price_b_toman_105316ef7d', lang, fa_parts=lambda: (f'{price:,}',))
        
        if payment_label:
            text += t('b_payment_label_b_7e2a3ffe0a', lang, fa_parts=lambda: (f'{payment_label}',))
        
        if payment_method:
            text += t('b_payment_method_b_code_code_a57edcc61a', lang, fa_parts=lambda: (f'{payment_method}',))
        
        # ✅ اطلاعات زمانی
        text += t('b_date_b_079c921011', lang, fa_parts=lambda: (f"{order.get('date', t('i18n_unknown', lang))}",))
        
        if approved_date:
            text += t('b_approved_date_b_36134c745a', lang, fa_parts=lambda: (f'{approved_date}',))
        
        if created_at:
            text += t('b_created_b_776cd6d21d', lang, fa_parts=lambda: (f'{created_at}',))
        
        if updated_at and updated_at != created_at:
            text += t('b_last_updated_b_977d9738be', lang, fa_parts=lambda: (f'{updated_at}',))
        
        # ✅ وضعیت
        text += t('b_status_b_6bee95825a', lang, fa_parts=lambda: (f'{status_text}',))
        
        # ✅ IP Limit
        text += f"{ip_display}\n"
        
        # ✅ اطلاعات پنل
        if is_active_in_panel:
            text += t('b_panel_status_b_active_19c8fe7c10', lang)
        else:
            text += t('b_panel_status_b_inactive_b3f0de9dd2', lang)
        
        if is_test:
            text += t('b_test_b_yes_46b9b32b8f', lang)
        
        # ✅ اطلاعات کانفیگ
        if email:
            text += t('b_email_b_code_code_f6db0db8f1', lang, fa_parts=lambda: (f'{email}',))
        
        if config_link:
            text += t('b_config_b_sent_49488bd30e', lang)
            text += t('b_link_b_code_code_47ea8d4380', lang, fa_parts=lambda: (f'{config_link}',))
        
        if sub_link and sub_link != config_link:
            text += t('b_sub_link_b_code_code_145ba9e280', lang, fa_parts=lambda: (f'{sub_link}',))
        
        # ✅ اطلاعات اینباندها
        if inbound_details:
            text += t('b_inbounds_b_171c2bf755', lang, fa_parts=lambda: (f'{len(inbound_details)}',))
            for idx, inbound in enumerate(inbound_details, 1):
                remark = inbound.get('remark', t('unknown_e68c579791', lang))
                protocol = inbound.get('protocol', '')
                port = inbound.get('port', '')
                text += f"  {idx}. {remark}"
                if protocol:
                    text += f" - {protocol.upper()}"
                if port:
                    text += f" :{port}"
                text += "\n"
        elif inbound_id:
            text += t('b_inbounds_b_2291a4de56', lang, fa_parts=lambda: (f"{', '.join(map(str, inbound_id))}",))
        
        # ✅ اطلاعات اضافی
        if notes:
            text += t('b_notes_b_d3697ac0cd', lang, fa_parts=lambda: (f'{notes}',))
        
        if order.get('receipt_photo_id'):
            text += t('b_receipt_b_sent_6560da55c5', lang)
        
        if order.get('rejected_reason'):
            text += t('b_reject_reason_b_072713eba8', lang, fa_parts=lambda: (f"{order.get('rejected_reason')}",))
        
        if is_extend:
            text += t('b_this_is_an_extension_order_c682b9facf', lang)
    
    else:
        text = t('b_order_b_b_user_b_467ac0c5fb', lang, en_parts=lambda: (f"{premium_emoji('order_id', '🆔')}", f'{order_id}', f"{premium_emoji('user', '👤')}", f'{uname}'))
        if username:
            text += t('b_username_b_1bcbaa2361', lang, en_parts=lambda: (f'{username}',))
        
        text += t('b_user_id_b_code_code_40d1d8fdd6', lang, en_parts=lambda: (f"{order.get('user_id')}",))
        
        if order_type == 'balance_charge':
            amount = order.get('amount', 0)
            text += t('b_type_b_balance_top_up_b_am_46bbab34fd', lang, en_parts=lambda: (f'{amount:,}',))
        elif order_type in ['ready_package', 'category_purchase']:
            text += t('b_type_b_ready_package_b_vol_29c4b2a112', lang, en_parts=lambda: (f'{icon}', f"{category_name or t('i18n_unknown', lang)}", f'{package_info}', f'{volume_display}', f"{order.get('days', 0)}"))
        elif order_type == 'test':
            text += t('b_type_b_free_test_b_volume_6e4d71cb83', lang, en_parts=lambda: (f'{volume_display}', f"{order.get('days', 0)}"))
        elif order_type == 'extend':
            text += t('b_type_b_service_extension_b_27afae67a6', lang, en_parts=lambda: (f'{volume_display}', f"{order.get('days', 0)}"))
            if parent_order_id:
                text += t('b_parent_order_b_025ac7e2d8', lang, en_parts=lambda: (f'{parent_order_id}',))
        else:
            text += t('b_type_b_regular_purchase_b_f4372d47fb', lang, en_parts=lambda: (f'{volume_display}', f"{order.get('days', 0)}"))
        
        text += t('b_price_b_toman_105316ef7d', lang, en_parts=lambda: (f'{price:,}',))
        
        if payment_label:
            text += t('b_payment_label_b_7e2a3ffe0a', lang, en_parts=lambda: (f'{payment_label}',))
        
        if payment_method:
            text += t('b_payment_method_b_code_code_a57edcc61a', lang, en_parts=lambda: (f'{payment_method}',))
        
        text += t('b_date_b_079c921011', lang, en_parts=lambda: (f"{order.get('date', t('i18n_unknown', lang))}",))
        
        if approved_date:
            text += t('b_approved_date_b_36134c745a', lang, en_parts=lambda: (f'{approved_date}',))
        
        if created_at:
            text += t('b_created_b_776cd6d21d', lang, en_parts=lambda: (f'{created_at}',))
        
        if updated_at and updated_at != created_at:
            text += t('b_last_updated_b_977d9738be', lang, en_parts=lambda: (f'{updated_at}',))
        
        text += t('b_status_b_6bee95825a', lang, en_parts=lambda: (f'{status_text}',))
        
        text += f"{ip_display}\n"
        
        if is_active_in_panel:
            text += t('b_panel_status_b_active_19c8fe7c10', lang)
        else:
            text += t('b_panel_status_b_inactive_b3f0de9dd2', lang)
        
        if is_test:
            text += t('b_test_b_yes_46b9b32b8f', lang)
        
        if email:
            text += t('b_email_b_code_code_f6db0db8f1', lang, en_parts=lambda: (f'{email}',))
        
        if config_link:
            text += t('b_config_b_sent_49488bd30e', lang)
            text += t('b_link_b_code_code_47ea8d4380', lang, en_parts=lambda: (f'{config_link}',))
        
        if sub_link and sub_link != config_link:
            text += t('b_sub_link_b_code_code_145ba9e280', lang, en_parts=lambda: (f'{sub_link}',))
        
        if inbound_details:
            text += t('b_inbounds_b_171c2bf755', lang, en_parts=lambda: (f'{len(inbound_details)}',))
            for idx, inbound in enumerate(inbound_details, 1):
                remark = inbound.get('remark', t('unknown_e68c579791', lang))
                protocol = inbound.get('protocol', '')
                port = inbound.get('port', '')
                text += f"  {idx}. {remark}"
                if protocol:
                    text += f" - {protocol.upper()}"
                if port:
                    text += f" :{port}"
                text += "\n"
        elif inbound_id:
            text += t('b_inbounds_b_2291a4de56', lang, en_parts=lambda: (f"{', '.join(map(str, inbound_id))}",))
        
        if notes:
            text += t('b_notes_b_d3697ac0cd', lang, en_parts=lambda: (f'{notes}',))
        
        if order.get('receipt_photo_id'):
            text += t('b_receipt_b_sent_6560da55c5', lang)
        
        if order.get('rejected_reason'):
            text += t('b_reject_reason_b_072713eba8', lang, en_parts=lambda: (f"{order.get('rejected_reason')}",))
        
        if is_extend:
            text += t('b_this_is_an_extension_order_c682b9facf', lang)
    
    # ✅ دکمه‌ها
    buttons = []
    if order_status == 'awaiting_payment':
        buttons.append([
            InlineKeyboardButton(
                text=t('request_receipt_b1b52d30f8', lang),
                callback_data=f"request_receipt_{order_id}"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text=t('cancel_order_c553bd5588', lang),
                callback_data=f"cancel_order_admin_{order_id}"
            )
        ])
    elif order_status in ['pending', 'pending_balance_charge']:
        buttons.append([
            InlineKeyboardButton(
                text=t('approve_8e35ad3e33', lang),
                callback_data=f"approve_receipt_{order_id}"
            ),
            InlineKeyboardButton(
                text=t('custom_payment_36f7f89c87', lang),
                callback_data=f"custom_payment_receipt_{order_id}"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text=t('reject_6ed3999c19', lang),
                callback_data=f"reject_receipt_{order_id}"
            )
        ])
        if order.get('receipt_photo_id'):
            buttons.append([
                InlineKeyboardButton(
                    text=t('view_receipt_575648cc06', lang),
                    callback_data=f"view_receipt_{order_id}"
                )
            ])
    elif order_status == 'approved':
        if order_type != 'balance_charge' and order.get('config_link'):
            buttons.append([
                InlineKeyboardButton(
                    text=t('view_config_ad93d47d82', lang),
                    callback_data=f"admin_view_config_{order_id}"
                )
            ])
        if order_type != 'balance_charge':
            has_cat = bool(order.get('category_id') or order.get('category_name'))
            cat_btn_label = t('i18n_change_order_category', lang) if has_cat else t('i18n_set_order_category', lang)
            buttons.append([
                InlineKeyboardButton(
                    text=cat_btn_label,
                    callback_data=f"admin_set_order_cat_{order_id}"
                )
            ])
        
        
        
        buttons.append([
            InlineKeyboardButton(
                text=f"🔙 {t('back_to_user_1b3158f6df', lang)}",
                callback_data=f"admin_user_{order.get('user_id')}_0"
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text=f"🔙 {t('back_d35a19b459', lang)}",
                callback_data=f"admin_user_{order.get('user_id')}_0"
            )
        ])
    
    try:
        if callback.message.content_type in ['photo', 'document', 'video', 'audio', 'voice']:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode=ParseMode.HTML
            )
        else:
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        error_str = str(e)
        if "there is no text in the message to edit" in error_str:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode=ParseMode.HTML
            )
        else:
            logger.error(f"Error displaying order: {e}")
            await callback.answer(t('error_viewing_order_20f3d01752', lang), show_alert=True)
    
    await safe_answer(callback)
        
@router.callback_query(F.data.startswith("request_receipt_"))
@admin_only
async def request_receipt(callback: CallbackQuery):
    """درخواست ارسال فیش از کاربر توسط ادمین - با استایل یکپارچه"""
    
    order_id = int(callback.data.split("_")[2])
    order = orders.get(str(order_id))
    
    if not order:
        await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    # ✅ بررسی قفل همزمانی تایید مستقیم
    if order_guard.is_in_progress(order_id):
        logger.warning(f"⚠️ Order #{order_id} direct approval already in progress! Blocking duplicate call.")
        return await callback.answer("⏳ این سفارش در حال حاضر در حال پردازش و تایید است...", show_alert=True)

    if order.get('status') == 'approved':
        await callback.answer("⚠️ این سفارش قبلاً تایید شده است!", show_alert=True)
        return
    
    user_id = order['user_id']
    lang = get_user(user_id).get('lang', 'fa')
    
    try:
        text = build_receipt_text(order, lang, mode="reminder")
        
        cancel_btn = t('cancel_order_1abd144629', lang)
        
        await bot.send_message(
            user_id,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=cancel_btn, callback_data=f"cancel_order_{order_id}", style="danger")]
            ])
        )
        
        user_states[user_id] = {
            'awaiting_receipt': True,
            'current_order_id': order_id,
            'timestamp': now_tehran_iso()
        }
        
        await callback.answer(t('receipt_request_sent_ac5c993c2d', lang))
        
    except Exception as e:
        logger.error(f"Error sending receipt request to user {user_id}: {e}")
        await callback.answer("❌ خطا در ارسال پیام", show_alert=True)
    
    await view_order(callback)
    
@router.callback_query(F.data.startswith("view_receipt_"))
@admin_only
async def view_receipt(callback: CallbackQuery):
    """مشاهده فیش ارسال شده"""
    
    order_id = int(callback.data.split("_")[2])
    order = orders.get(str(order_id))
    
    if not order:
        await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    # ✅ بررسی قفل همزمانی تایید مستقیم
    if order_guard.is_in_progress(order_id):
        logger.warning(f"⚠️ Order #{order_id} direct approval already in progress! Blocking duplicate call.")
        return await callback.answer("⏳ این سفارش در حال حاضر در حال پردازش و تایید است...", show_alert=True)

    if order.get('status') == 'approved':
        await callback.answer("⚠️ این سفارش قبلاً تایید شده است!", show_alert=True)
        return
    
    photo_id = order.get('receipt_photo_id')
    if not photo_id:
        await callback.answer("❌ فیشی یافت نشد", show_alert=True)
        return
    
    try:
        await bot.send_photo(
            callback.message.chat.id,
            photo_id,
            caption=f"📸 <b>فیش سفارش #{order_id}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_to_order_756d7fac90', get_user(callback.from_user.id).get('lang', 'fa')),
                    callback_data=f"view_order_{order_id}"
                )]
            ])
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error sending receipt: {e}")
        await callback.answer("❌ خطا در نمایش فیش", show_alert=True)
        
@router.callback_query(F.data.startswith("cancel_order_admin_"))
@admin_only
async def cancel_order_admin(callback: CallbackQuery):
    """لغو سفارش توسط ادمین - با تاییدیه"""
    
    logger.info(f"🔴 [cancel_order_admin] CALLED: {callback.data}")
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    parts = callback.data.split("_")
    if len(parts) < 4:
        await callback.answer(t('i18n_invalid_callback_format', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    try:
        order_id = int(parts[3])
    except ValueError:
        await callback.answer(t('i18n_order_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    order = orders.get(str(order_id))
    if not order:
        await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    user_id = order['user_id']
    user_info = get_user(user_id)
    user_name_raw = user_info.get('name', f'کاربر_{user_id}')
    user_name_escaped = html.escape(user_name_raw)
    text = t('b_cancel_order_by_admin_b_us_78aa3d5d2f', lang, fa_parts=lambda: (f'{order_id}', f'{user_name_escaped}', f'{user_id}', f"{order.get('volume', 0)}", f"{order.get('days', 0)}", f"{order.get('price', 0):,}", f"{order.get('status', 'نامشخص')}"), en_parts=lambda: (f'{order_id}', f'{user_name_escaped}', f'{user_id}', f"{order.get('volume', 0)}", f"{order.get('days', 0)}", f"{order.get('price', 0):,}", f"{order.get('status', 'Unknown')}"))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=t('yes_cancel_ca835a3b81', lang),
                callback_data=f"confirm_cancel_order_admin_{order_id}",  # ✅ تغییر کلید برای جلوگیری از تداخل
                style="danger"
            ),
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data=f"view_order_{order_id}"
            )
        ]
    ])
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
    await safe_answer(callback)

@router.callback_query(F.data.startswith("confirm_cancel_order_admin_"))
@admin_only
async def confirm_cancel_order_admin(callback: CallbackQuery):
    """تایید نهایی لغو سفارش توسط ادمین"""
    
    logger.info(f"🔴 [confirm_cancel_order_admin] CALLED: {callback.data}")
    parts = callback.data.split("_")
    if len(parts) < 5:
        await callback.answer(t('i18n_invalid_callback_format', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    try:
        order_id = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_order_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    order = orders.get(str(order_id))
    if not order:
        await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    user_id = order['user_id']
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    user_info = get_user(user_id)
    user_name_raw = user_info.get('name', f'کاربر_{user_id}')
    user_name_escaped = html.escape(user_name_raw)
    coupon_code = None
    coupon_applied = False
    user_state = user_states.get(user_id, {})
    if user_state.get('coupon_applied'):
        coupon_code = user_state.get('coupon_code')
        coupon_applied = True
    old_status = order.get('status', 'unknown')
    price = order.get('price', 0)
    volume = order.get('volume', 0)
    days = order.get('days', 0)
    order_type = order.get('type', 'purchase')
    should_refund = False
    refund_amount = 0
    if old_status == 'approved':
        should_refund = True
        refund_amount = price
        logger.info(f"💰 Order #{order_id} had been approved - returned {price:,}tomans")
    
    elif old_status == 'pending':
        should_refund = True
        refund_amount = price
        logger.info(f"💰 Order #{order_id} awaiting approval (receipt sent) - refunded {price:,}tomans")
    
    elif old_status == 'pending_balance_charge':
        should_refund = True
        refund_amount = price
        logger.info(f"💰 Order #{order_id} top-up request - refund {price:,}tomans")
    elif old_status == 'awaiting_payment':
        should_refund = False
        refund_amount = 0
        logger.info(f"ℹ️ Order #{order_id} is awaiting payment - no balance will be refunded")
    update_order(order_id, status='cancelled')
    
    logger.info(f"🗑 order #{order_id} cleared by admin {callback.from_user.id} cancelled (previous status: {old_status})")
    if should_refund and refund_amount > 0:
        old_balance = get_user(user_id).get('balance', 0)
        new_balance = add_balance(user_id, refund_amount)
        logger.info(f"💰 User {user_id} balance refunded: {old_balance} -> {new_balance} ({refund_amount:,} toman)")
        if log_system:
            await log_system.log_balance_change(
                user_id=user_id,
                amount=refund_amount,
                new_balance=new_balance,
                action="add",
                admin_id=callback.from_user.id,
                details=f"Balance refunded because admin cancelled order #{order_id} (previous status: {old_status})"
            )
    else:
        if old_status == 'awaiting_payment':
            logger.info(f"ℹ️ Order #{order_id} was awaiting payment - balance was not refunded")
    if coupon_applied and coupon_code:
        coupon = COUPONS.get(coupon_code)
        coupon_consumed = False
        if coupon and user_id in coupon.get('used_by', []):
            coupon_consumed = True
        
        if not coupon_consumed:
            coupon_released = release_coupon_on_cancel(user_id)
            if coupon_released:
                logger.info(f"🏷️ coupon {coupon_code} for user {user_id} released (order canceled by admin)")
            else:
                logger.warning(f"⚠️ Coupon {coupon_code} for user {user_id} was not released")
        else:
            logger.info(f"ℹ️ Coupon {coupon_code} already used by user {user_id} had been used")
    try:
        user_lang = get_user(user_id).get('lang', 'fa')
        if old_status == 'awaiting_payment':
            await bot.send_message(
                user_id,
                t('order_has_been_expired_volum_a5109f3943', user_lang, fa_parts=lambda: (f"{premium_emoji('cancel', '❌')}", f'{order_id}', f"{premium_emoji('config', '📦')}", f'{volume}', f"{premium_emoji('time', '⏱')}", f'{days}'), en_parts=lambda: (f"{premium_emoji('cancel', '❌')}", f'{order_id}', f"{premium_emoji('config', '📦')}", f'{volume}', f"{premium_emoji('time', '⏱')}", f'{days}'))
            )
        else:
            refund_text = f"💰 مبلغ {refund_amount:,} تومان به حساب شما برگشت داده شد." if should_refund and refund_amount > 0 else ""
            coupon_text = f"🏷️ کوپن شما ({coupon_code}) {'آزاد شد' if coupon_applied and coupon_code else 'ندارد'}"
            
            await bot.send_message(
                user_id,
                t('order_has_been_cancelled_by_4817cb6bb8', user_lang, fa_parts=lambda: (f'{order_id}', f'{volume}', f'{days}', f'{refund_text}', f'{coupon_text}'), en_parts=lambda: (f'{order_id}', f'{volume}', f'{days}', f'{refund_text}', f'{coupon_text}'))
            )
        
        logger.info(f"📨 Order cancellation message sent to user {user_id} sent")
    except Exception as e:
        logger.error(f"Error sending order-cancellation message to user {user_id}: {e}")
    if log_system:
        await log_system.log_admin_action(
            callback.from_user.id,
            f"Cancelled order #{order_id}",
            target_user=user_id,
            details=f"Volume: {volume}GB | Duration: {days} days | Price: {price:,} Toman | Previous status: {old_status} | Balance refunded: {'yes' if should_refund else 'no'}"
        )
    
    CustomLogger.log_event('ORDER_CANCELLED_BY_ADMIN', 
        f'Order #{order_id} cancelled by admin - user: {user_name_escaped} ({user_id}) - previous status: {old_status} - balance refunded: {should_refund}', 
        user_id)
    if old_status == 'awaiting_payment':
        refund_status = "❌ کاربر هنوز پرداختی انجام نداده بود - موجودی برگشت داده نشد"
    elif should_refund:
        refund_status = f"✅ موجودی کاربر برگشت داده شد ({refund_amount:,} تومان)"
    else:
        refund_status = "ℹ️ بدون تغییر موجودی"
    
    text = t('b_order_cancelled_successful_28565bbf37', lang, fa_parts=lambda: (f'{order_id}', f'{user_name_escaped}', f'{user_id}', f'{volume}', f'{days}', f'{price:,}', f'{old_status}', f"{(f'💰 {refund_status}' if should_refund else f'ℹ️ {refund_status}')}", f"{('آزاد شد' if coupon_applied and coupon_code else 'ندارد')}"), en_parts=lambda: (f'{order_id}', f'{user_name_escaped}', f'{user_id}', f'{volume}', f'{days}', f'{price:,}', f'{old_status}', f"{(f'💰 {refund_status}' if should_refund else f'ℹ️ {refund_status}')}", f"{('Released' if coupon_applied and coupon_code else 'None')}"))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('back_to_orders_d29b01f5a2', lang),
            callback_data="admin_orders"
        )],
        [InlineKeyboardButton(
            text=t('view_user_686cebfd95', lang),
            callback_data=f"admin_user_{user_id}"
        )]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.debug(f"Failed to edit message in cancel_order_admin, sending new: {e}")
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
    await callback.answer(t('order_cancelled_ca913ee3c6', lang), show_alert=True)
           
async def fulfill_vpn_order(
    order_id: int,
    approved_by: str = "admin",
    payment_method: str = "card"
) -> Tuple[str, str]:
    """
    سرویس مرکزی تایید پرداخت و تحویل کانفیگ VPN (مستقل از CallbackQuery)
    Returns: ('fulfilled' | 'failed_pending_retry' | 'manual_fulfillment_required', error_message)
    """
    try:
        async with order_guard.lock_order(order_id):
            return await _fulfill_vpn_order_impl(order_id, approved_by=approved_by, payment_method=payment_method)
    except PaymentInProgressError:
        return "failed_pending_retry", "Order approval already in progress"


async def _fulfill_vpn_order_impl(
    order_id: int,
    approved_by: str = "admin",
    payment_method: str = "card"
) -> Tuple[str, str]:
    order = orders.get(str(order_id))
    if not order:
        return "failed_pending_retry", f"Order #{order_id} not found"

    # جلوگیری قطعی از تایید مجدد
    if order.get("status") == "approved":
        logger.warning(f"⚠️ Order #{order_id} was already approved; duplicate operation ignored.")
        return "fulfilled", "Already approved"

    user_id = order.get("user_id")
    volume = order.get("volume", 0)
    days = order.get("days", 0)
    price = order.get("price", 0)
    user_info = get_user(user_id)
    user_name = user_info.get("name", f"کاربر_{user_id}")
    lang = user_info.get("lang", "fa")

    # ۱. ثبت قطعی تایید پرداخت
    update_order(
        order_id,
        status="approved",
        approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
        payment_method=payment_method,
        payment_verified=True,
    )
    if order.get("discount_source") == "coupon" and not order.get("coupon_consumed"):
        if consume_coupon(user_id):
            update_order(order_id, coupon_consumed=True)
    await check_referral_bonus(user_id)

    # ۲. بررسی وضعیت پنل سنایی
    if not is_senai_panel_enabled():
        logger.info(f"ℹ️ Sanaei panel is disabled; order #{order_id} requires manual fulfillment.")
        return "manual_fulfillment_required", "Sanaei panel is disabled; manual fulfillment required"

    # ۳. ساخت کلاینت در پنل سنایی به صورت ایدم‌پوتنت
    email = order.get("email")
    if not email:
        timestamp = int(datetime.now().timestamp())
        email = f"user{user_id}_{timestamp}"

    sub_link = order.get("config_link") or order.get("sub_link")
    if not sub_link:
        sub_link = await create_client_in_panel(user_id, email, volume, days, user_name)

    if sub_link:
        update_order(order_id, config_link=sub_link, sub_link=sub_link, email=email)
        await send_config_with_qr_option(user_id, order_id, volume, days, price, sub_link, lang)
        try:
            await bot.send_message(
                user_id,
                f"{premium_emoji('star', '⭐')} {t('please_rate_our_service_e52df3f954', lang)}",
                reply_markup=get_feedback_keyboard(order_id, lang)
            )
        except Exception:
            pass
        return "fulfilled", ""
    else:
        logger.error(f"❌ Error creating client in the panel for order #{order_id}; payment is approved and ready to retry.")
        return "failed_pending_retry", "Failed to create client in Sanaei panel"


@router.callback_query(F.data.startswith("approve_order_"))
@admin_only(answer_on_denied=False)
async def approve_order(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    order_id = int(callback.data.split("_")[2])
    order = orders.get(str(order_id))

    if not order:
        logger.error(f"Order #{order_id} not found for approval")
        await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    if order.get("status") == "approved":
        await callback.answer(t('i18n_order_already_approved', lang), show_alert=True)
        return

    user_id = order['user_id']
    volume = order['volume']
    days = order['days']
    price = order['price']
    user_info = get_user(user_id)
    user_name = user_info.get('name', f'کاربر_{user_id}')
    logger.info(f"admin approved order #{order_id} started")
    await callback.message.edit_text(t('i18n_order_processing', lang, fa_parts=lambda: (order_id,), en_parts=lambda: (order_id,)))

    status_result, err_msg = await fulfill_vpn_order(order_id, approved_by="admin", payment_method="card")

    if status_result == "fulfilled":
        sub_link = orders[str(order_id)].get("config_link", "")
        await callback.message.edit_text(
            t('i18n_order_approved_admin', lang, fa_parts=lambda: (order_id, user_name, user_id, volume, days, sub_link[:40]), en_parts=lambda: (order_id, user_name, user_id, volume, days, sub_link[:40]))
        )
    elif status_result == "manual_fulfillment_required":
        user_states[callback.from_user.id] = {
            'awaiting_config': True,
            'order_id': order_id,
            'user_id': user_id,
            'volume': volume,
            'days': days,
            'price': price
        }
        await callback.message.answer(t('please_send_the_config_link_294d282898', lang))
    else:
        # خطای پنل سنایی؛ دکمه تلاش مجدد نمایش داده می‌شود
        await callback.message.edit_text(
            t('i18n_order_retry_needed', lang, fa_parts=lambda: (err_msg,), en_parts=lambda: (err_msg,)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=t('i18n_retry_delivery', lang), callback_data=f"sms_retry_{order_id}_0")
            ]]),
            parse_mode=ParseMode.HTML
        )

    await safe_answer(callback)

@router.callback_query(F.data.startswith("reject_order_"))
@admin_only(answer_on_denied=False)
async def reject_order(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    order_id = int(callback.data.split("_")[2])
    order = orders.get(str(order_id))
    if order:
        update_order(order_id, status='rejected')
        user_lang = get_user(order['user_id']).get('lang', 'fa')
        try:
            await bot.send_message(order['user_id'], 
                f"{premium_emoji('fail', '❌')} {t('order_has_been_rejected_c2786f4c23', user_lang, fa_parts=lambda: (f'{order_id}',), en_parts=lambda: (f'{order_id}',))}")
            logger.info(f"Order #{order_id} rejected - message sent to user")
        except Exception as e:
            logger.error(f"Error sending order rejection message: {e}")
        await callback.answer(t('order_rejected_4e32e0cc33', lang), show_alert=True)
    await admin_orders(callback)



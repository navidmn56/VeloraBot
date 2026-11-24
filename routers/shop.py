"""
routers/shop.py
---------------
روتر فروشگاه کاربر: وضعیت باز/بسته بودن فروشگاه، مرور دسته‌بندی‌ها و بسته‌های آماده،
انتخاب بسته و پرداخت بسته‌های آماده از موجودی حساب.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Union

from aiogram import Router, F, Bot, types
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.enums import ParseMode

from config import ADMIN_ID
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
)

ADMIN_ID_INT = get_admin_id_int()
from routers.admin_shop import (
    is_shop_open,
    get_shop_status_message,
)
from routers.admin_test import (
    save_user_inbound_selection,
)
from routers.force_join import check_membership
from services.panel_api import (
    xui_get_inbounds,
    xui_create_client_with_inbound,
    xui_get_client_traffic,
)
from strings import t
from emoji_sticker_system import premium_emoji
from utils.helpers import safe_answer, safe_edit_message, safe_html
from utils.rate_limiter import buy_rate_limiter
from utils.payment_guard import payment_guard, PaymentInProgressError

logger = logging.getLogger(__name__)

router = Router(name="shop")

bot: Optional[Bot] = None


def set_bot(b: Bot):
    global bot
    bot = b


def get_bot() -> Optional[Bot]:
    return bot


# ==============================================================================
# Late-binding proxies for shared main systems
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


def get_main_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_main_keyboard"):
        return main.get_main_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def get_purchase_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_purchase_keyboard"):
        return main.get_purchase_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def get_back_only_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_back_only_keyboard"):
        return main.get_back_only_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def get_feedback_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_feedback_keyboard"):
        return main.get_feedback_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def to_persian_digits(*args, **kwargs):
    import main
    if hasattr(main, "to_persian_digits"):
        return main.to_persian_digits(*args, **kwargs)
    return str(args[0]) if args else ""


async def notify_blacklisted_user(*args, **kwargs):
    import main
    if hasattr(main, "notify_blacklisted_user"):
        return await main.notify_blacklisted_user(*args, **kwargs)


async def check_referral_bonus(*args, **kwargs):
    import main
    if hasattr(main, "check_referral_bonus"):
        return await main.check_referral_bonus(*args, **kwargs)


def create_order(*args, **kwargs):
    import main
    if hasattr(main, "create_order"):
        return main.create_order(*args, **kwargs)


def record_purchase(*args, **kwargs):
    import main
    if hasattr(main, "record_purchase"):
        return main.record_purchase(*args, **kwargs)


def get_valid_orders(*args, **kwargs):
    import main
    if hasattr(main, "get_valid_orders"):
        return main.get_valid_orders(*args, **kwargs)
    return []


async def send_config_with_qr_option(*args, **kwargs):
    import main
    if hasattr(main, "send_config_with_qr_option"):
        return await main.send_config_with_qr_option(*args, **kwargs)


# ==============================================================================
# Shop Status Check
# ==============================================================================

async def check_shop_status_and_notify(
    user_id: int, 
    callback: CallbackQuery = None,
    short_alert: bool = False
) -> bool:
    """بررسی وضعیت فروش و ارسال پیام در صورت بسته بودن
    
    Args:
        user_id: آیدی کاربر
        callback: کال‌بک کوئری
        short_alert: اگه True باشه، فقط alert کوتاه نشون می‌ده (بدون ادیت/حذف پیام)
    
    Returns:
        True اگر فروش باز است، False اگر بسته است
    """
    if is_shop_open():
        return True
    
    lang = get_user(user_id).get('lang', 'fa')
    message = get_shop_status_message(lang)
    
    # ✅ حالت short_alert: فقط alert، هیچ پیامی ادیت/حذف نمی‌شه
    if callback and short_alert:
        title = t('shop_is_temporarily_closed_a6d66fcfcb', lang)
        
        # اگه پیام ادمین کوتاه بود، نشونش بده
        # محدودیت show_alert = 200 کاراکتر، عنوان ~30 کاراکتر
        if message and len(message) <= 150:
            alert_text = f"{title}\n\n{message}"
        else:
            alert_text = title
        
        try:
            await callback.answer(alert_text, show_alert=True)
        except Exception as e:
            logger.warning(f"Package sales alert error: {e}")
            try:
                await callback.answer(title, show_alert=True)
            except Exception:
                await safe_answer(callback)
        
        return False
    
    # ✅ حالت عادی: پیام کامل
    if callback:
        text = f"🛒 <b>{t('shop_is_temporarily_closed_c2da3aaaf1', lang)}</b>\n\n{message}"
        keyboard = get_back_only_keyboard(lang)
        
        try:
            if callback.message.text:
                await callback.message.edit_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
            elif callback.message.caption is not None:
                await callback.message.edit_caption(
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
            else:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer(
                    text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            error_str = str(e)
            if "message is not modified" in error_str:
                pass
            elif "there is no text in the message to edit" in error_str:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                try:
                    await callback.message.answer(
                        text,
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e2:
                    logger.error(f"❌ Error sending shop-closed message: {e2}")
            else:
                logger.warning(f"⚠️ Error in check_shop_status: {e}")
        
        await safe_answer(callback)
    
    return False


# ==============================================================================
# Helper Functions
# ==============================================================================

def format_package_volume(volume: Union[int, float], lang: str = "fa") -> str:
    """
    نمایش هوشمند حجم بسته به زبان انتخابی:
    - در زبان فارسی: اگر حجم کمتر از ۱ گیگ باشد به صورت «مگ» و اگر ۱ یا بیشتر باشد به صورت «گیگ» نمایش می‌دهد.
    - در زبان انگلیسی: به صورت GB یا MB نمایش می‌دهد.
    - مقدار 0 به عنوان نامحدود در نظر گرفته می‌شود.
    """
    if volume is None or volume == 0:
        return t('unlimited_b72dd6e126', lang)
    
    try:
        vol_float = float(volume)
    except (ValueError, TypeError):
        return t('gb_b755d45a80', lang, fa_parts=lambda: (f'{volume}',), en_parts=lambda: (f'{volume}',))
    
    if vol_float < 1:
        mb = vol_float * 1024
        mb_str = f"{int(round(mb))}" if abs(mb - round(mb)) < 0.01 else f"{mb:.1f}"
        return t('mb_4062381407', lang, fa_parts=lambda: (f'{mb_str}',), en_parts=lambda: (f'{mb_str}',))
    else:
        gb_str = f"{int(vol_float)}" if vol_float == int(vol_float) else f"{vol_float:.1f}"
        return t('gb_b755d45a80', lang, fa_parts=lambda: (f'{gb_str}',), en_parts=lambda: (f'{gb_str}',))


def get_user_last_purchased_package(user_id: int, target_order_id: Optional[int] = None):
    """
    یافتن آخرین بسته آماده خریداری شده توسط کاربر برای دکمه «همون همیشگی».
    در صورت مشخص بودن target_order_id (حالت تمدید)، ابتدا بسته همان سفارش بررسی می‌شود.
    تنها سفارش‌های موفق (خریداری شده) بررسی می‌شوند و سفارش‌های در انتظار پرداخت، لغو شده، رد شده یا تست نادیده گرفته می‌شوند.
    اگر کاربر قبلاً بسته‌ای نخریده باشد یا بسته در حال حاضر غیرفعال/حذف شده باشد، None بازمی‌گرداند.
    خروجی: تاپل (دسته_بندی, بسته) یا None
    """
    try:
        valid_orders = get_valid_orders()
        if not valid_orders:
            return None

        categories = READY_PACKAGES.get('categories', [])
        if not categories:
            return None

        def _resolve_order_package(order):
            if not isinstance(order, dict):
                return None
            cat_id = order.get('category_id')
            pkg_id = order.get('package_id')

            # 1) تطبیق مستقیم بر اساس category_id و package_id
            if cat_id is not None and pkg_id is not None:
                try:
                    c_id = int(cat_id)
                    p_id = int(pkg_id)
                    for cat in categories:
                        if cat.get('id') == c_id and cat.get('is_active', True):
                            for pkg in cat.get('packages', []):
                                if pkg.get('id') == p_id and pkg.get('is_active', True):
                                    return cat, pkg
                except (ValueError, TypeError):
                    pass

            # 2) انطباق ثانویه (fallback) بر اساس نام دسته، حجم و روز
            order_cat_name = order.get('category_name')
            order_vol = order.get('volume')
            order_days = order.get('days')

            if order_cat_name and order_vol is not None:
                for cat in categories:
                    if not cat.get('is_active', True):
                        continue
                    if cat.get('name') == order_cat_name or cat.get('name_en') == order_cat_name:
                        for pkg in cat.get('packages', []):
                            if not pkg.get('is_active', True):
                                continue
                            try:
                                pkg_vol = float(pkg.get('volume', 0))
                                ord_vol = float(order_vol)
                                if abs(pkg_vol - ord_vol) < 0.01:
                                    if order_days is not None:
                                        if int(pkg.get('days', 30)) == int(order_days):
                                            return cat, pkg
                                    else:
                                        return cat, pkg
                            except (ValueError, TypeError):
                                continue
            return None

        # ─── اولویت ۱: حالت تمدید یک سفارش خاص ───
        if target_order_id is not None:
            target_order = None
            for o in valid_orders:
                if str(o.get('order_id')) == str(target_order_id) or str(o.get('id')) == str(target_order_id):
                    target_order = o
                    break
            if target_order:
                res = _resolve_order_package(target_order)
                if res:
                    return res

        # ─── اولویت ۲: آخرین سفارش خریداری شده کاربر ───
        user_orders = []
        for o in valid_orders:
            if o.get('user_id') == user_id:
                # نادیده گرفتن اکانت‌های تست
                o_type = o.get('type', 'purchase')
                if o_type == 'test' or o.get('is_test', False) or (o.get('email', '') or '').startswith('test_'):
                    continue
                # نادیده گرفتن سفارش‌های لغو شده یا رد شده
                if o.get('status') in ['cancelled', 'rejected']:
                    continue
                user_orders.append(o)

        if not user_orders:
            return None

        def _get_order_sort_key(o):
            dt_str = o.get('approved_date') or o.get('date') or o.get('created_at') or ''
            try:
                oid = int(o.get('order_id') or o.get('id') or 0)
            except (ValueError, TypeError):
                oid = 0
            return (dt_str, oid)

        user_orders.sort(key=_get_order_sort_key, reverse=True)

        for o in user_orders:
            res = _resolve_order_package(o)
            if res:
                return res

        return None
    except Exception as e:
        logger.error(f"❌ Error in get_user_last_purchased_package: {e}")
        return None


# ==============================================================================
# Shop Catalog & Browsing Handlers
# ==============================================================================

@router.callback_query(F.data == "show_ready_categories")
async def show_ready_categories(callback: CallbackQuery):
    """نمایش دسته‌بندی‌های بسته‌های آماده - با پشتیبانی از دو زبان و حالت تمدید"""
    user_id = callback.from_user.id
    
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        await callback.answer(
            t('access_blocked_96a5fa848b', get_user(user_id).get('lang', 'fa')),
            show_alert=True
        )
        return
    
    if not await check_membership(user_id):
        lang = get_user(user_id).get('lang', 'fa')
        await callback.answer(
            t('please_verify_your_membershi_28b48b1f0b', lang),
            show_alert=True
        )
        return
    
    if not await check_shop_status_and_notify(user_id, callback):
        return
    
    lang = get_user(user_id).get('lang', 'fa')
    user_state = user_states.get(user_id, {})
    
    # ✅ بررسی حالت تمدید
    is_extend = user_state.get('is_extend', False)
    extend_order_id = user_state.get('extend_order_id')
    
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)
    
    # ✅ بررسی اعتبار کوپن
    if coupon_applied and coupon_code:
        is_valid, reason = is_coupon_valid_for_user(coupon_code, user_id)
        if not is_valid:
            logger.warning(f"⚠️ [show_ready_categories] Coupon {coupon_code} invalid: {reason}")
            coupon_applied = False
            coupon_code = None
            coupon_discount = 0
            if user_id in user_states:
                user_states[user_id].pop('coupon_code', None)
                user_states[user_id].pop('coupon_discount', None)
                user_states[user_id].pop('coupon_applied', None)
        else:
            logger.info(f"✅ [show_ready_categories] Coupon {coupon_code} is valid: {reason}")
    
    logger.info(f"🔍 [show_ready_categories] coupon: code={coupon_code}, applied={coupon_applied}, discount={coupon_discount}")
    logger.info(f"🔄 [show_ready_categories] renewal status: is_extend={is_extend}, extend_order_id={extend_order_id}")
    
    # ✅ اگر حالت تمدید است و محدودیت تمدید فقط در همان دسته فعال است:
    restrict_extend = READY_PACKAGES.get('restrict_extend_to_same_category', False)
    if is_extend and extend_order_id and restrict_extend:
        order = orders.get(str(extend_order_id))
        order_cat_id = order.get('category_id') if order else None
        order_cat_name = order.get('category_name') if order else None
        
        matching_cat = None
        for c in READY_PACKAGES.get('categories', []):
            if not c.get('is_active', True):
                continue
            if order_cat_id and int(c.get('id', -1)) == int(order_cat_id):
                matching_cat = c
                break
            elif order_cat_name and c.get('name') and str(c.get('name')).strip() == str(order_cat_name).strip():
                matching_cat = c
                break
        
        # اگه دسته با تطبیق مستقیم پیدا نشد، تلاش از روی اینباندها
        if not matching_cat and order:
            order_inbound = order.get('inbound_id')
            if order_inbound:
                order_inbounds_set = set(order_inbound if isinstance(order_inbound, list) else [order_inbound])
                for c in READY_PACKAGES.get('categories', []):
                    if not c.get('is_active', True):
                        continue
                    cat_inbounds = c.get('inbound_ids') or ([c.get('inbound_id')] if c.get('inbound_id') else [])
                    if set(cat_inbounds) == order_inbounds_set:
                        matching_cat = c
                        logger.info(f"✅ [show_ready_categories] Service category #{extend_order_id} identified from matching inbounds: {c.get('name')}")
                        break

        if matching_cat:
            active_pkgs = [p for p in matching_cat.get('packages', []) if p.get('is_active', True)]
            if not active_pkgs:
                cancel_text = f"🔙 {t('cancel_extension_904323bdf2', lang)}"
                await callback.message.edit_text(
                    t('renewal_category_disabled_msg', lang),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=cancel_text, callback_data=f"cancel_extend_{extend_order_id}", style="danger")]
                    ]),
                    parse_mode=ParseMode.HTML
                )
                await safe_answer(callback)
                return

            new_cb = callback.model_copy(update={'data': f"show_category_packages_{matching_cat['id']}"})
            await show_category_packages(new_cb)
            return

    # ✅ ذخیره وضعیت کوپن در دیتابیس
    if coupon_applied and coupon_code:
        save_coupon_to_user_db(user_id)
        logger.info(f"🏷️ [show_ready_categories] Coupon {coupon_code} in user_states for user {user_id} saved")
    else:
        logger.warning(f"⚠️ [show_ready_categories] No coupon for user {user_id} not found")
    
    # ─── عنوان صفحه ───
    if is_extend and extend_order_id:
        text = t('b_extend_service_b_category_218be0df6a', lang, fa_parts=lambda: (f'{extend_order_id}',), en_parts=lambda: (f'{extend_order_id}',))
    else:
        text = t('b_ready_packages_b_please_se_ad21074e40', lang)
    
    # ─── نمایش اطلاعات کوپن در متن ───
    if coupon_applied and coupon_code and coupon_discount:
        text += f"\n\n🏷️ <b>{t('active_coupon_code_percent_c13a3b5030', lang, fa_parts=lambda: (f'{coupon_code}', f'{coupon_discount}'), en_parts=lambda: (f'{coupon_code}', f'{coupon_discount}'))}</b>"
    
    buttons = []
    
    # ─── دکمه «همون همیشگی» (سفارش مجدد آخرین بسته خریداری شده) ───
    last_pkg_info = get_user_last_purchased_package(user_id, target_order_id=extend_order_id if is_extend else None)
    if last_pkg_info:
        last_cat, last_pkg = last_pkg_info
        last_vol_display = format_package_volume(last_pkg.get('volume', 0), lang)
        last_days = last_pkg.get('days', 30)
        
        repeat_label = (
            f"🔄 همون همیشگی ({last_vol_display} / {last_days} روزه)"
            if lang == "fa"
            else f"🔄 Usual Choice ({last_vol_display} / {last_days}d)"
        )
        buttons.append([
            InlineKeyboardButton(
                text=repeat_label,
                callback_data=f"buy_package_{last_cat.get('id')}_{last_pkg.get('id')}",
                style="success"
            )
        ])
    
    # ─── دکمه‌های دسته‌بندی‌ها ───
    active_categories = []
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('is_active', True):
            active_packages = [p for p in cat.get('packages', []) if p.get('is_active', True)]
            if active_packages:
                active_categories.append((cat, len(active_packages)))
    
    for cat, pkg_count in active_categories:
        cat_name = cat.get('name') if lang == "fa" else cat.get('name_en', cat.get('name'))
        icon = cat.get('icon', '📦')
        
        btn_text = f"{icon} {cat_name} ({pkg_count})"
        
        buttons.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"show_category_packages_{cat.get('id')}",
                style="primary"
            )
        ])
    
    # ─── دکمه بازگشت / انصراف ───
    if is_extend and extend_order_id:
        back_text = f"🔙 {t('cancel_extension_904323bdf2', lang)}"
        back_callback = f"cancel_extend_{extend_order_id}"
    else:
        back_text = f"🔙 {t('back_to_main_menu_67d29ceca0', lang)}"
        back_callback = "back_to_main"
    
    buttons.append([
        InlineKeyboardButton(
            text=back_text,
            callback_data=back_callback,
            style="danger"
        )
    ])
    
    # ─── بررسی وجود دسته‌بندی ───
    if not active_categories:
        empty_text = (
            t('b_packages_temporarily_unavai_0fba9dbdc4', lang)
        )
        try:
            await callback.message.edit_text(
                empty_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text=back_text,
                        callback_data=back_callback,
                        style="danger"
                    )
                ]]),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            if "message is not modified" not in str(e):
                logger.error(f"Error editing message: {e}")
        await callback.answer()
        return
    
    # ─── ارسال/ویرایش پیام ───
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        if "there is no text in the message to edit" in str(e):
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode=ParseMode.HTML
            )
        elif "message is not modified" in str(e):
            pass
        else:
            raise
    
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_extend_"))
async def cancel_extend(callback: CallbackQuery):
    """انصراف از تمدید سرویس - هشدار توست + بازگشت به منوی اصلی"""
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    
    try:
        extend_order_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return
    
    # ─── حفظ کوپن ───
    user_state = user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)
    
    # ─── پاک کردن state تمدید ───
    if user_id in user_states:
        user_states.pop(user_id, None)
    
    # ─── بازیابی کوپن ───
    if coupon_applied and coupon_code:
        user_states[user_id] = {
            'coupon_code': coupon_code,
            'coupon_discount': coupon_discount,
            'coupon_applied': True
        }
        logger.info(f"🏷️ [cancel_extend] Coupon {coupon_code} for user {user_id} preserved")
    
    # ─── هشدار توست ───
    toast_text = t('service_extension_cancelled_9c36ce4a57', lang)
    await safe_answer(callback, toast_text)
    
    # ─── بازگشت به منوی اصلی ───
    is_admin = (user_id == ADMIN_ID_INT)
    text = t('main_menu_c928863059', lang, fa_parts=lambda: (f"{premium_emoji('rocket', '🚀')}",), en_parts=lambda: (f"{premium_emoji('rocket', '🚀')}",))
    keyboard = get_main_keyboard(is_admin, lang, user_id)
    
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


@router.callback_query(F.data.startswith("show_category_packages_"))
async def show_category_packages(callback: CallbackQuery):
    """نمایش بسته‌های موجود در یک دسته - با پشتیبانی از حالت تمدید"""
    user_id = callback.from_user.id
    
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
    
    lang = get_user(user_id).get('lang', 'fa')
    
    try:
        category_id = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_category_not_found', lang), show_alert=True)
        return
    
    category = None
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            category = cat
            break
    
    if not category:
        await callback.answer(t('i18n_category_not_found', lang), show_alert=True)
        return
    
    # ✅ بررسی حالت تمدید از user_states
    user_state = user_states.get(user_id, {})
    is_extend = user_state.get('is_extend', False)
    extend_order_id = user_state.get('extend_order_id')
    current_volume = user_state.get('current_volume', 0)
    current_days = user_state.get('current_days', 0)
    
    # ✅ دریافت کوپن فعال از user_states
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)
    
    if coupon_applied and coupon_code:
        is_valid, reason = is_coupon_valid_for_user(coupon_code, user_id)
        if not is_valid:
            coupon_applied = False
            coupon_code = None
            coupon_discount = 0
            if user_id in user_states:
                user_states[user_id].pop('coupon_code', None)
                user_states[user_id].pop('coupon_discount', None)
                user_states[user_id].pop('coupon_applied', None)
    
    active_packages = [p for p in category.get('packages', []) if p.get('is_active', True)]
    
    if not active_packages:
        await callback.answer(
            t('no_active_packages_category_00e0b355ec', lang),
            show_alert=True
        )
        return
    
    cat_name = category.get('name') if lang == "fa" else category.get('name_en', category.get('name'))
    icon = category.get('icon', '📦')
    
    # ─── عنوان صفحه ───
    if is_extend and extend_order_id:
        text = t('b_extend_service_b_category_218be0df6a', lang, fa_parts=lambda: (f'{extend_order_id}',), en_parts=lambda: (f'{extend_order_id}',))
    else:
        text = t('b_packages_b_category_f5d165f126', lang, fa_parts=lambda: (f'{icon}', f'{cat_name}'), en_parts=lambda: (f'{icon}', f'{cat_name}'))
    
    # ─── نمایش کوپن فعال ───
    if coupon_applied and coupon_code and coupon_discount:
        text += f"\n\n🏷️ <b>{t('active_coupon_code_percent_c13a3b5030', lang, fa_parts=lambda: (f'{coupon_code}', f'{coupon_discount}'), en_parts=lambda: (f'{coupon_code}', f'{coupon_discount}'))}</b>"
    
    # ─── نمایش اطلاعات فعلی سرویس در حالت تمدید ───
    if is_extend and extend_order_id:
        order = orders.get(str(extend_order_id))
        if order:
            total_vol = order.get('volume', 0)
            email = order.get('email', '')
            used_vol_gb = 0
            
            if email:
                try:
                    traffic_info = await xui_get_client_traffic(email)
                    if traffic_info and isinstance(traffic_info, dict):
                        up = traffic_info.get('up', 0)
                        down = traffic_info.get('down', 0)
                        used_vol_gb = (up + down) / (1024**3)
                except Exception as e:
                    logger.warning(f"⚠️ [show_category_packages] Error retrieving client usage for renewal: {e}")
            
            if total_vol > 0:
                rem_vol = max(0, total_vol - used_vol_gb)
                rem_vol_str = f"{rem_vol:.1f}" if rem_vol != int(rem_vol) else f"{int(rem_vol)}"
            else:
                rem_vol_str = t('unlimited_b72dd6e126', lang)
            
            exp_date_str = order.get('expire_date') or order.get('expiry_time') or ''
            rem_days_str = str(current_days)
            if exp_date_str:
                try:
                    exp_dt = datetime.fromisoformat(exp_date_str.replace('Z', '+00:00'))
                    now_dt = now_tehran()
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=now_dt.tzinfo)
                    diff = (exp_dt - now_dt).days
                    rem_days_str = str(max(0, diff))
                except Exception:
                    pass
            
            total_vol_str = f"{total_vol:.1f}" if total_vol != int(total_vol) else f"{int(total_vol)}"
            if total_vol == 0:
                total_vol_str = t('unlimited_b72dd6e126', lang)
            else:
                total_vol_str += f" {t('gb_b755d45a80', lang, fa_parts=lambda: ('',), en_parts=lambda: ('',))}"
            
            if rem_vol_str != t('unlimited_b72dd6e126', lang):
                rem_vol_str += f" {t('gb_b755d45a80', lang, fa_parts=lambda: ('',), en_parts=lambda: ('',))}"
            
            text += f"\n\n📋 <b>{t('current_service_info_title', lang)}</b>"
            text += f"\n• {t('remaining_volume_label', lang)} <b>{rem_vol_str}</b> ({t('total_label', lang)} {total_vol_str})"
            text += f"\n• {t('remaining_days_label', lang)} <b>{rem_days_str} {t('days_unit', lang)}</b>"
            text += f"\n💡 <i>{t('renewal_addition_note', lang)}</i>"

    buttons = []
    
    for pkg in active_packages:
        vol = pkg.get('volume', 0)
        days = pkg.get('days', 30)
        orig_price = pkg.get('price', 0)
        ip_limit = pkg.get('ip_limit', 0)
        
        # محاسبه قیمت با تخفیف
        if coupon_applied and coupon_discount and coupon_discount > 0:
            final_price = orig_price - (orig_price * coupon_discount // 100)
            price_display = f"{final_price:,} {t('toman_06798679d6', lang)} ({coupon_discount}% {t('off_fba5efcba4', lang)})"
        else:
            price_display = f"{orig_price:,} {t('toman_06798679d6', lang)}"
        
        vol_display = format_package_volume(vol, lang)
        
        if ip_limit == 0:
            ip_text = t('users_unlimited_ff31ebd666', lang)
        elif ip_limit == 1:
            ip_text = t('users_1_device_f030aff7fa', lang)
        else:
            ip_text = t('users_devices_6344c0109b', lang, fa_parts=lambda: (f'{ip_limit}',), en_parts=lambda: (f'{ip_limit}',))
        
        btn_text = f"📦 {vol_display} | ⏱ {days} {t('days_931c818b26', lang)} | {ip_text} | 💰 {price_display}"
        
        buttons.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"buy_package_{category_id}_{pkg.get('id')}",
                style="primary"
            )
        ])
    
    # ─── دکمه بازگشت ───
    restrict_extend = READY_PACKAGES.get('restrict_extend_to_same_category', False)
    if is_extend and extend_order_id and restrict_extend:
        back_text = f"🔙 {t('cancel_extension_904323bdf2', lang)}"
        back_callback = f"cancel_extend_{extend_order_id}"
    else:
        back_text = f"🔙 {t('back_to_categories_246adfe129', lang)}"
        back_callback = "show_ready_categories"
    
    buttons.append([
        InlineKeyboardButton(
            text=back_text,
            callback_data=back_callback,
            style="danger"
        )
    ])
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        if "there is no text in the message to edit" in str(e):
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode=ParseMode.HTML
            )
        elif "message is not modified" in str(e):
            pass
        else:
            raise
    
    await safe_answer(callback)


@router.callback_query(F.data.startswith("buy_package_"))
async def buy_specific_package(callback: CallbackQuery):
    """خرید یک بسته مشخص از یک دسته با پشتیبانی از تمدید سرویس"""
    user_id = callback.from_user.id
    if buy_rate_limiter.is_rate_limited(user_id, action="buy_package", cooldown=1.5):
        lang = get_user(user_id).get('lang', 'fa')
        wait_msg = "⏳ لطفاً کمی صبر کنید..." if lang == "fa" else "⏳ Please wait a moment..."
        await safe_answer(callback, wait_msg, alert=False)
        return
    save_coupon_to_user_db(user_id)
    
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
        parts = callback.data.split("_")
        category_id = int(parts[2])
        package_id = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_package_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    category = None
    package = None
    
    for c in READY_PACKAGES.get('categories', []):
        if c.get('id') == category_id:
            category = c
            for p in c.get('packages', []):
                if p.get('id') == package_id:
                    package = p
                    break
            break
    
    if not category or not package:
        await callback.answer(t('i18n_package_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    if not category.get('is_active', True) or not package.get('is_active', True):
        await callback.answer(
            t('package_inactive_choose_another_9b2e0431b8', get_user(callback.from_user.id).get('lang', 'fa')),
            show_alert=True
        )
        return
    
    lang = get_user(user_id).get('lang', 'fa')
    user = get_user(user_id)
    
    # ✅ چک کردن محدودیت تمدید در صورت فعال بودن
    restrict_extend = READY_PACKAGES.get('restrict_extend_to_same_category', False)
    user_state_check = user_states.get(user_id, {})
    if user_state_check.get('is_extend') and user_state_check.get('extend_order_id'):
        extend_order_id = user_state_check.get('extend_order_id')
        logger.info(f"🔄 [buy_specific_package] User {user_id} is in renewal mode - original order: #{extend_order_id}")
        if restrict_extend:
            order = orders.get(str(extend_order_id))
            order_cat_id = order.get('category_id') if order else None
            order_cat_name = order.get('category_name') if order else None
            allowed = False
            if order_cat_id and int(order_cat_id) == int(category_id):
                allowed = True
            elif order_cat_name and category.get('name') and str(category.get('name')).strip() == str(order_cat_name).strip():
                allowed = True
            if not allowed:
                await callback.answer(
                    t('renewal_is_restricted_to_you_73698004e4', lang),
                    show_alert=True
                )
                return
    
    volume = package.get('volume', 0)
    days = package.get('days', 30)
    original_price = package.get('price', 0)
    ip_limit = package.get('ip_limit', 0)
    
    volume_display = format_package_volume(volume, lang)
    if ip_limit == 0:
        ip_display = t('users_unlimited_ff31ebd666', lang)
    elif ip_limit == 1:
        ip_display = t('users_1_device_f030aff7fa', lang)
    else:
        ip_display = t('users_devices_6344c0109b', lang, fa_parts=lambda: (f'{ip_limit}',), en_parts=lambda: (f'{ip_limit}',))
    
    user_state = user_states.get(user_id, {})
    discount_percent = 0
    final_price = original_price
    
    coupon_code = user_state.get('coupon_code')
    coupon_applied = user_state.get('coupon_applied', False)
    
    if coupon_applied and coupon_code:
        coupon = COUPONS.get(coupon_code)
        if coupon and coupon.get('status') == 'active':
            coupon_type = coupon.get('coupon_type', 'normal')
            coupon_valid = False
            
            if coupon_type == 'admin_special':
                locked_user_id = coupon.get('locked_user_id')
                user_usage = coupon.get('user_usage', {})
                user_used_count = user_usage.get(str(user_id), 0)
                max_usage = coupon.get('usage_limit', 1)
                
                if locked_user_id == user_id and user_used_count < max_usage:
                    coupon_valid = True
                    logger.info(f"✅ Admin coupon {coupon_code} is valid ({user_used_count}/{max_usage})")
                else:
                    logger.warning(f"⚠️ Admin coupon {coupon_code} is invalid - locked={locked_user_id}, usage={user_used_count}/{max_usage}")
            else:
                if user_id not in coupon.get('used_by', []):
                    coupon_valid = True
                else:
                    logger.warning(f"⚠️ Regular coupon {coupon_code} was already used")
            
            if coupon_valid:
                discount_percent = coupon.get('discount', 0)
                if discount_percent > 0:
                    final_price = original_price - (original_price * discount_percent // 100)
                    logger.info(f"🏷️ Discount {discount_percent}% on package {package_id} applied: {original_price:,} → {final_price:,}")
            else:
                if user_id in user_states:
                    user_states[user_id].pop('coupon_code', None)
                    user_states[user_id].pop('coupon_discount', None)
                    user_states[user_id].pop('coupon_applied', None)
                discount_percent = 0
                final_price = original_price
        else:
            logger.warning(f"⚠️ Coupon {coupon_code} is invalid or inactive")
            if user_id in user_states:
                user_states[user_id].pop('coupon_code', None)
                user_states[user_id].pop('coupon_discount', None)
                user_states[user_id].pop('coupon_applied', None)
            discount_percent = 0
            final_price = original_price
            
    category_inbound_ids = category.get('inbound_ids', [])
    
    if not category_inbound_ids:
        old_inbound = category.get('inbound_id')
        if old_inbound:
            category_inbound_ids = [old_inbound]
            category['inbound_ids'] = category_inbound_ids
            category['inbound_id'] = None
            READY_PACKAGES['last_updated'] = now_tehran_iso()
            configs_pool['ready_packages'] = READY_PACKAGES
            save_all()
    
    if not category_inbound_ids:
        default_ids = configs_pool.get('default_inbound_ids', [])
        if default_ids:
            category_inbound_ids = default_ids
            logger.info(f"📌 Using default inbounds for category {category.get('name')}: {category_inbound_ids}")
        else:
            inbounds = await xui_get_inbounds()
            category_inbound_ids = [i.get('id') for i in inbounds if i.get('enable', True)]
            logger.info(f"📡 Using all active inbounds for category {category.get('name')}: {category_inbound_ids}")
    
    logger.info(f"📦 user {user_id} package {package_id} from category {category.get('name')} selected {volume_display}/{days}days - original price: {original_price:,} - final price: {final_price:,}")
    logger.info(f"📡 category inbounds {category.get('name')}: {category_inbound_ids}")
    logger.info(f"User count: {ip_limit if ip_limit > 0 else 'unlimited'}")
    
    update_user(user_id, 'volume', volume if volume > 0 else 1)
    update_user(user_id, 'days', days)
    
    old_state = user_states.get(user_id, {})
    is_extend = old_state.get('is_extend', False)
    extend_order_id = old_state.get('extend_order_id')
    current_volume = old_state.get('current_volume', 0)
    current_days = old_state.get('current_days', 0)
    coupon_code_old = old_state.get('coupon_code')
    coupon_discount_old = old_state.get('coupon_discount')
    coupon_applied_old = old_state.get('coupon_applied', False)
    
    logger.info(f"🔍 [buy_specific_package] previous STATE: is_extend={is_extend}, extend_order_id={extend_order_id}")
    logger.info(f"🔍 [buy_specific_package] previous coupon: code={coupon_code_old}, applied={coupon_applied_old}")
    logger.info(f"🔍 [buy_specific_package] previous volume/days: {current_volume}GB / {current_days}days")
    
    if category_inbound_ids:
        save_user_inbound_selection(user_id, category_inbound_ids)
        logger.info(f"📡 Inbounds for {category_inbound_ids} for user {user_id} set (ready-made package)")
    
    user_states[user_id] = {
        'payment_type': 'ready_package',
        'category_id': category_id,
        'package_id': package_id,
        'volume': volume,
        'days': days,
        'price': final_price,
        'original_price': original_price,
        'discount_percent': discount_percent,
        'inbound_ids': category_inbound_ids,
        'category_name': category.get('name'),
        'category_name_en': category.get('name_en') or '',
        'is_ready_package': True,
        'category_icon': category.get('icon', '📦'),
        'current_page': 'package_payment',
        'ip_limit': ip_limit,
        'is_extend': is_extend,
        'extend_order_id': extend_order_id,
        'current_volume': current_volume,
        'current_days': current_days,
        'payment_ready': True,
        'timestamp': now_tehran_iso(),
    }
    
    if is_extend and extend_order_id:
        logger.info(f"🔄 [buy_specific_package] Renewal status saved in user_states: order_id={extend_order_id}")
        logger.info(f"   user_states[{user_id}]['is_extend'] = {user_states[user_id].get('is_extend')}")
        logger.info(f"   user_states[{user_id}]['extend_order_id'] = {user_states[user_id].get('extend_order_id')}")
    
    if coupon_applied_old and coupon_code_old:
        user_states[user_id]['coupon_code'] = coupon_code_old
        user_states[user_id]['coupon_applied'] = True
        user_states[user_id]['coupon_discount'] = coupon_discount_old or 0
        logger.info(f"🏷️ [buy_specific_package] Coupon {coupon_code_old} preserved")
    
    category_icon = category.get('icon', '📦')
    category_name = category.get('name') if lang == "fa" else category.get('name_en', category.get('name'))
    balance = user.get('balance', 0)
    
    discount_text = ""
    if discount_percent > 0 and final_price != original_price:
        discount_text = t('b_discounted_price_b_toman_o_17c3cb6633', lang, fa_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{final_price:,}', f'{discount_percent}'), en_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{final_price:,}', f'{discount_percent}'))
    
    if is_extend and extend_order_id:
        text = t('b_extend_service_b_category_c7328a6c0c', lang, fa_parts=lambda: (f'{extend_order_id}', f"{premium_emoji('config', '📦')}", f'{category_icon}', f'{category_name}', f"{premium_emoji('config', '📦')}", f'{volume_display}', f"{premium_emoji('time', '⏱')}", f'{days}', f'{ip_display}', f"{premium_emoji('money', '💰')}", f'{original_price:,}', f'{discount_text}', f"{premium_emoji('wallet', '💰')}", f'{balance:,}', f"{premium_emoji('info', '💡')}"), en_parts=lambda: (f'{extend_order_id}', f"{premium_emoji('config', '📦')}", f'{category_icon}', f'{category_name}', f"{premium_emoji('config', '📦')}", f'{volume_display}', f"{premium_emoji('time', '⏱')}", f'{days}', f'{ip_display}', f"{premium_emoji('money', '💰')}", f'{original_price:,}', f'{discount_text}', f"{premium_emoji('wallet', '💰')}", f'{balance:,}', f"{premium_emoji('info', '💡')}"))
    else:
        text = t('b_ready_package_b_volume_dur_3e43cc387f', lang, fa_parts=lambda: (f'{category_icon}', f'{category_name}', f"{premium_emoji('config', '📦')}", f'{volume_display}', f"{premium_emoji('time', '⏱')}", f'{days}', f'{ip_display}', f"{premium_emoji('money', '💰')}", f'{original_price:,}', f'{discount_text}', f"{premium_emoji('wallet', '💰')}", f'{balance:,}', f"{premium_emoji('info', '💡')}"), en_parts=lambda: (f'{category_icon}', f'{category_name}', f"{premium_emoji('config', '📦')}", f'{volume_display}', f"{premium_emoji('time', '⏱')}", f'{days}', f'{ip_display}', f"{premium_emoji('money', '💰')}", f'{original_price:,}', f'{discount_text}', f"{premium_emoji('wallet', '💰')}", f'{balance:,}', f"{premium_emoji('info', '💡')}"))
    
    buttons = [
        [
            InlineKeyboardButton(
                text=f"💳 {t('pay_by_card_8ef3792b24', lang)}",
                callback_data="pay_card",
                style="primary"
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
                callback_data=f"show_category_packages_{category_id}",
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
            logger.error(f"Error editing message: {e}")
    
    await safe_answer(callback)


@router.callback_query(F.data == "show_ready_categories_keep_coupon")
async def show_ready_categories_keep_coupon(callback: CallbackQuery):
    """نمایش دسته‌بندی بسته‌ها - با حفظ کوپن"""
    user_id = callback.from_user.id
    user_state = user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied')
    if user_id in user_states:
        user_states[user_id].pop('is_ready_package', None)
        user_states[user_id].pop('price', None)
        user_states[user_id].pop('inbound_id', None)
        user_states[user_id].pop('category_id', None)
        user_states[user_id].pop('package_id', None)
        user_states[user_id].pop('category_name', None)
        user_states[user_id].pop('current_page', None)
        if coupon_applied and coupon_code:
            user_states[user_id]['coupon_code'] = coupon_code
            user_states[user_id]['coupon_discount'] = coupon_discount
            user_states[user_id]['coupon_applied'] = True
            logger.info(f"🏷️ coupon {coupon_code} for user {user_id} was preserved when returning to packages")
    await show_ready_categories(callback)


@router.callback_query(F.data.startswith("pay_ready_package_balance_"))
async def pay_ready_package_balance(callback: CallbackQuery):
    """پرداخت از موجودی برای بسته آماده"""
    user_id = callback.from_user.id
    
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
            return await _process_pay_ready_package_balance(callback, user_id)
    except PaymentInProgressError:
        lang = get_user(user_id).get('lang', 'fa')
        msg = (
            "⏳ درخواست پرداخت شما در حال پردازش است، لطفاً شکیبا باشید."
            if lang == "fa"
            else "⏳ Your payment is already being processed, please wait."
        )
        await safe_answer(callback, msg, alert=True)
        return


async def _process_pay_ready_package_balance(callback: CallbackQuery, user_id: int):
    try:
        parts = callback.data.split("_")
        category_id = int(parts[3])
        package_id = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    category = None
    package = None
    
    for c in READY_PACKAGES.get('categories', []):
        if c.get('id') == category_id and c.get('is_active', True):
            category = c
            for p in c.get('packages', []):
                if p.get('id') == package_id and p.get('is_active', True):
                    package = p
                    break
            break
    
    if not category or not package:
        await callback.answer(t('package_not_found_1847864740', get_user(user_id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(user_id).get('lang', 'fa')
    user = get_user(user_id)
    
    volume = package.get('volume', 0)
    days = package.get('days', 30)
    price = package.get('price', 0)
    balance = user.get('balance', 0)
    inbound_id = category.get('inbound_id')
    
    if balance < price:
        await callback.answer(
            t('insufficient_balance_balance_4c0cf35f27', lang, fa_parts=lambda: (f'{balance:,}', f'{price:,}'), en_parts=lambda: (f'{balance:,}', f'{price:,}')),
            show_alert=True
        )
        return
    
    new_balance = balance - price
    update_user(user_id, 'balance', new_balance)

    await callback.message.edit_text(t('i18n_processing_please_wait', lang))
    
    order_id = create_order(user_id, volume, days, price, "ready_package")
    update_order(order_id, 
                status='approved',
                category_id=category_id,
                category_name=category.get('name'),
                package_id=package_id,
                inbound_id=inbound_id,
                payment_method='balance',
                approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"))
    
    record_purchase(user_id, price)
    await check_referral_bonus(user_id)
    
    await callback.message.edit_text(t('i18n_processing_config_in_panel', lang))
    
    timestamp = int(datetime.now().timestamp())
    email = f"user{user_id}_{timestamp}"
    user_name = user.get('name', f'کاربر_{user_id}')
    
    sub_link = await xui_create_client_with_inbound(email, volume, days, user_name, user_id, inbound_id)
    
    if sub_link:
        update_order(order_id, config_link=sub_link, sub_link=sub_link, email=email)
        
        await send_config_with_qr_option(user_id, order_id, volume, days, price, sub_link, lang)
        
        cat_name = category.get('name') if lang == "fa" else category.get('name_en', category.get('name'))
        
        success_text = t('b_purchase_successful_b_b_b_a8c4cea204', lang, fa_parts=lambda: (f"{category.get('icon', '📦')}", f'{cat_name}', f'{volume}', f'{days}', f'{price:,}', f'{new_balance:,}'), en_parts=lambda: (f"{category.get('icon', '📦')}", f'{cat_name}', f'{volume}', f'{days}', f'{price:,}', f'{new_balance:,}'))
        
        await callback.message.answer(
            success_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('view_configs_0ba48783cd', lang),
                    callback_data="my_configs"
                )],
                [InlineKeyboardButton(
                    text=t('main_menu_0cdd07a7cc', lang),
                    callback_data="back_to_main"
                )]
            ])
        )
        
        current_bot = bot or get_bot()
        if current_bot:
            try:
                await current_bot.send_message(
                    user_id,
                    f"{premium_emoji('star', '⭐')} {t('please_rate_our_service_e52df3f954', lang)}",
                    reply_markup=get_feedback_keyboard(order_id, lang)
                )
            except Exception as e:
                logger.error(f"Error sending feedback request: {e}")
        
        logger.info(f"✅ Ready-made package purchased for user {user_id} - order #{order_id} - {volume}GB/{days} days - {price:,}tomans")
        
        if log_system:
            await log_system.log_purchase(user_id, order_id, volume, days, price, f"Ready package - {cat_name}")
        
    else:
        update_user(user_id, 'balance', balance)
        
        error_msg = t('error_creating_config_your_b_3996a20cfc', lang)
        await callback.message.answer(
            error_msg,
            reply_markup=get_back_only_keyboard(lang)
        )
        logger.error(f"❌ Error creating client for user {user_id}")
    
    await safe_answer(callback)

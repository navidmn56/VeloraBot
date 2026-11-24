"""
routers/user_account.py
-----------------------
مدیریت حساب کاربری، استعلام وضعیت سفارش، کوپن تخفیف، لینک دعوت و تغییر زبان
"""

import html
import re
import sys
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from database import orders, configs_pool, referrals, BLACKLIST, get_valid_orders
from user_manager import (
    get_user,
    update_user,
    can_user_purchase,
    is_coupon_valid_for_user,
    load_coupon_from_user_db,
    clear_coupon_from_user_db,
    COUPONS,
    user_states,
)
from strings import t
from utils.helpers import (
    safe_answer,
    get_back_only_keyboard,
    notify_blacklisted_user,
    premium_emoji,
)
from daily_usage_system import gregorian_to_jalali, to_persian_digits
from emoji_sticker_system import send_sticker as _send_sticker_impl
from logger_system import logger
from routers.admin_packages import log_system
from routers.admin_packages import get_language_keyboard

router = Router(name="user_account")

_bot: Optional[Bot] = None


def set_bot(bot_instance: Bot):
    global _bot
    _bot = bot_instance


def get_bot() -> Optional[Bot]:
    global _bot
    if _bot is not None:
        return _bot
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "bot"):
        return getattr(main_mod, "bot")
    return None


async def send_sticker(
    chat_id: int,
    sticker_key: str,
    fallback_emoji: str = "📌",
    reply_markup: Any = None,
) -> bool:
    bot_inst = get_bot()
    if bot_inst is None:
        return False
    return await _send_sticker_impl(
        bot_inst,
        chat_id,
        sticker_key,
        fallback_emoji,
        reply_markup,
        logger,
    )


def _resolve_main_handler(name: str):
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, name):
        return getattr(main_mod, name)
    return None


@router.callback_query(F.data == "my_account")
async def my_account(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        lang = get_user(user_id).get('lang', 'fa')
        await callback.answer(t('access_blocked_96a5fa848b', lang), show_alert=True)
        return

    can_purchase, msg = can_user_purchase(user_id)
    if not can_purchase:
        lang = get_user(user_id).get('lang', 'fa')
        await callback.answer(msg if lang == "fa" else t('i18n_pending_admin_approval', lang), show_alert=True)
        return

    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    ref_count = len([r for r in referrals.values() if r.get('referrer') == user_id])
    valid_orders = get_valid_orders()
    user_orders = [o for o in valid_orders.values() if o.get('user_id') == user_id]
    test_orders = [o for o in user_orders if o.get('type') == 'test']
    real_orders = [o for o in user_orders if o.get('type') != 'test']
    purchase_orders = [o for o in real_orders if o.get('type') in ['purchase', 'ready_package', 'category_purchase']]
    approved_purchases = [o for o in purchase_orders if o.get('status') == 'approved']
    total_purchases = len(approved_purchases)

    active_configs = [
        o for o in approved_purchases
        if o.get('config_link') is not None
        and o.get('config_link') != ''
    ]

    extend_orders = [
        o for o in user_orders
        if o.get('is_extend', False) or o.get('parent_order_id') is not None
    ]
    approved_extends = [o for o in extend_orders if o.get('status') == 'approved']
    total_extends = len(approved_extends)

    total_tests = len(test_orders)

    # بررسی کوپن - با پشتیبانی از کوپن ادمین
    coupon_info = ""
    coupon_is_valid = False
    user_state = user_states.get(user_id, {})

    # اگر کوپن در user_states نبود، از دیتابیس لود کن
    if not user_state.get('coupon_applied'):
        coupon_data = load_coupon_from_user_db(user_id)
        if coupon_data.get('coupon_applied'):
            if user_id not in user_states:
                user_states[user_id] = {}
            user_states[user_id]['coupon_code'] = coupon_data.get('coupon_code')
            user_states[user_id]['coupon_discount'] = coupon_data.get('coupon_discount')
            user_states[user_id]['coupon_applied'] = True
            user_state = user_states[user_id]
            logger.info("🏷️ [my_account] Coupon loaded from database into user_states")

    # بررسی اعتبار با تابع کمکی
    if user_state.get('coupon_applied') and user_state.get('coupon_code'):
        coupon_code = user_state.get('coupon_code')
        coupon_discount = user_state.get('coupon_discount', 0)

        is_valid, reason = is_coupon_valid_for_user(coupon_code, user_id)

        if is_valid:
            coupon_is_valid = True
            coupon_obj = COUPONS.get(coupon_code)
            coupon_type = coupon_obj.get('coupon_type', 'normal') if coupon_obj else 'normal'

            if coupon_type == 'admin_special':
                user_usage = coupon_obj.get('user_usage', {})
                user_used_count = user_usage.get(str(user_id), 0)
                max_usage = coupon_obj.get('usage_limit', 1)

                coupon_info = t('b_active_admin_coupon_b_code_27ef7486d1', lang, fa_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{html.escape(coupon_code)}', f'{coupon_discount}'), en_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{html.escape(coupon_code)}', f'{coupon_discount}'))
                coupon_info += t('used_5caa8d1339', lang, fa_parts=lambda: (f'{user_used_count}', f'{max_usage}'), en_parts=lambda: (f'{user_used_count}', f'{max_usage}'))
            else:
                coupon_info = t('b_active_coupon_b_code_code_0363e7e7c5', lang, fa_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{html.escape(coupon_code)}', f'{coupon_discount}'), en_parts=lambda: (f"{premium_emoji('gift', '🏷️')}", f'{html.escape(coupon_code)}', f'{coupon_discount}'))
        else:
            logger.warning(f"⚠️ [my_account] Coupon {coupon_code} invalid: {reason}")
            if user_id in user_states:
                user_states[user_id].pop('coupon_code', None)
                user_states[user_id].pop('coupon_discount', None)
                user_states[user_id].pop('coupon_applied', None)
            clear_coupon_from_user_db(user_id)

    user_name_raw = user.get('name', f'کاربر_{user_id}')
    user_name_escaped = html.escape(user_name_raw)
    join_date_escaped = html.escape(user.get('join_date', 'نامشخص'))

    logger.debug(f"User {user_id} views their account - total purchases: {total_purchases}, active configs: {len(active_configs)}")

    if lang == "fa":
        RLM = "\u200F"  # Right-to-Left Mark

        text = (
            t('b_my_account_b_b_id_b_b_name_1389d533c6', lang, fa_parts=lambda: (f'{RLM}', f"{premium_emoji('user1', '👤')}", f'{RLM}', f'{RLM}', f"{premium_emoji('id', '🆔')}", f'{user_id}', f'{RLM}', f"{premium_emoji('user', '👤')}", f'{user_name_escaped}', f'{RLM}', f"{premium_emoji('wallet', '💰')}", f"{user.get('balance', 0):,}", f'{RLM}', f"{premium_emoji('invite', '👥')}", f'{ref_count}', f'{RLM}', f"{premium_emoji('config', '📦')}", f'{total_purchases}', f'{RLM}', f"{premium_emoji('renew', '🔄')}", f'{total_extends}', f'{RLM}', f"{premium_emoji('config', '🟢')}", f'{len(active_configs)}', f'{RLM}', f"{premium_emoji('calendar', '📅')}", f'{join_date_escaped}', f'{RLM}', f"{(coupon_info.lstrip() if coupon_info else '')}"))
        )
    else:
        text = t('b_my_account_b_b_id_b_b_name_1389d533c6', lang, en_parts=lambda: (f"{premium_emoji('user1', '👤')}", f"{premium_emoji('id', '🆔')}", f'{user_id}', f"{premium_emoji('user', '👤')}", f'{user_name_escaped}', f"{premium_emoji('wallet', '💰')}", f"{user.get('balance', 0):,}", f"{premium_emoji('invite', '👥')}", f'{ref_count}', f"{premium_emoji('config', '📦')}", f'{total_purchases}', f"{premium_emoji('renew', '🔄')}", f'{total_extends}', f"{premium_emoji('config', '🟢')}", f'{len(active_configs)}', f"{premium_emoji('calendar', '📅')}", f'{join_date_escaped}', f'{coupon_info}'))

    buttons = []
    if coupon_is_valid:
        buttons.append([
            InlineKeyboardButton(
                text=f"🏷️ {t('coupon_status_0aab90af2c', lang)}",
                callback_data="coupon_status",
                style="primary"
            ),
            InlineKeyboardButton(
                text=f"📊 {t('order_status_a1267047cf', lang)}",
                callback_data="order_status",
                style="primary"
            ),
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text=f"🏷️ {t('apply_coupon_ceb53d0236', lang)}",
                callback_data="apply_coupon",
                style="primary"
            ),
            InlineKeyboardButton(
                text=f"📊 {t('order_status_a1267047cf', lang)}",
                callback_data="order_status",
                style="primary"
            ),
        ])

    buttons.append([
        InlineKeyboardButton(
            text=f"➕ {t('charge_wallet_61243bab88', lang)}",
            callback_data="increase_balance",
            style="success"
        ),
        InlineKeyboardButton(
            text=f"🧾 {t('transactions_fb96851c75', lang)}",
            callback_data="my_transactions",
            style="primary"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text=f"🏠 {t('main_menu_9ae3456442', lang)}",
            callback_data="back_to_main",
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
        if "message is not modified" not in str(e):
            logger.error(f"Error editing message: {e}")
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


def _format_order_datetime(value: Any, lang: str) -> str:
    if not value:
        return "—"
    try:
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(value, tz=ZoneInfo("UTC"))
        else:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        iran_time = parsed.astimezone(ZoneInfo("Asia/Tehran"))
        if lang == "fa":
            year, month, day = gregorian_to_jalali(
                iran_time.year, iran_time.month, iran_time.day
            )
            return to_persian_digits(
                f"{year:04d}/{month:02d}/{day:02d} {iran_time:%H:%M}"
            )
        return iran_time.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return html.escape(str(value))


def _order_status_label(status: str, lang: str) -> str:
    labels = {
        "awaiting_payment": ("در انتظار پرداخت", "Awaiting payment"),
        "pending": ("در انتظار تأیید پرداخت", "Payment under review"),
        "pending_balance_charge": ("در انتظار تأیید شارژ کیف پول", "Wallet top-up under review"),
        "approved": ("تأیید و فعال‌شده", "Approved and active"),
        "rejected": ("ردشده", "Rejected"),
        "cancelled": ("لغوشده", "Cancelled"),
        "inactive": ("غیرفعال", "Inactive"),
        "deleted": ("حذف‌شده", "Deleted"),
    }
    fallback = html.escape(status or (t('unknown_e68c579791', lang)))
    return labels.get(status, (fallback, fallback))[0 if lang == "fa" else 1]


def _build_order_details_text(order: dict, lang: str) -> str:
    order_id = html.escape(str(order.get("order_id", "?")))
    status = str(order.get("status", ""))
    status_label = _order_status_label(status, lang)
    created_at = _format_order_datetime(order.get("created_at") or order.get("date"), lang)
    approved_at = _format_order_datetime(order.get("approved_date"), lang)
    order_type = str(order.get("type", "purchase"))
    payment_method_labels = {
        "card": ("کارت‌به‌کارت", "Bank transfer"),
        "cart": ("کارت‌به‌کارت", "Bank transfer"),
        "card_to_card": ("کارت‌به‌کارت", "Bank transfer"),
        "balance": ("کیف پول", "Wallet"),
        "balance_charge": ("کارت‌به‌کارت", "Bank transfer"),
        "balance_pool": ("کیف پول", "Wallet"),
        "test": ("سرویس خوشامد", "Welcome service"),
        "free_coupon": ("کوپن رایگان", "Free coupon"),
        "free_coupon_extend": ("کوپن رایگان", "Free coupon"),
        "free_extend": ("تمدید رایگان", "Free renewal"),
        "balance_extend": ("کیف پول", "Wallet"),
        "custom_payment_receipt": ("کارت‌به‌کارت", "Bank transfer"),
    }
    raw_payment_method = str(order.get("payment_method") or "").strip()
    if not raw_payment_method:
        if order_type == "balance_charge" or order.get("receipt_photo_id") or status == "pending_balance_charge":
            raw_payment_method = "card"

    if raw_payment_method in payment_method_labels:
        payment_method = payment_method_labels[raw_payment_method][0 if lang == "fa" else 1]
    else:
        payment_method = html.escape(str(
            order.get("payment_label") or raw_payment_method
            or ("کارت‌به‌کارت" if order_type == "balance_charge" else (t('unknown_e68c579791', lang)))
        ))
    try:
        price = int(order.get("price", 0) or 0)
    except (TypeError, ValueError):
        price = 0
    price_text = f"{price:,} {t('toman_94d5eb7aad', lang)}"

    if status == "approved" or status == "deleted" or (
        status == "inactive" and order.get("approved_date")
    ):
        payment_status = ("رایگان / تسویه‌شده", "Free / settled") if price == 0 else ("پرداخت تأیید شده", "Payment confirmed")
    elif status in ("pending", "pending_balance_charge"):
        payment_status = ("رسید ارسال‌شده؛ در انتظار بررسی", "Receipt submitted; under review")
    elif status == "awaiting_payment":
        payment_status = ("پرداخت انجام نشده", "Payment not received")
    elif status == "rejected":
        payment_status = ("پرداخت رد شده", "Payment rejected")
    elif status == "cancelled":
        payment_status = ("پرداخت لغو شده", "Payment cancelled")
    else:
        payment_status = ("—", "—")

    if status == "deleted":
        config_status = ("از پنل حذف شده", "Removed from panel")
    elif status == "inactive":
        config_status = ("غیرفعال", "Inactive")
    elif status == "approved" and order.get("config_link"):
        config_status = ("فعال", "Active")
    else:
        config_status = ("ایجاد نشده", "Not created")

    type_labels = {
        "test": ("سرویس خوشامد", "Welcome service"),
        "purchase": ("خرید سرویس", "Service purchase"),
        "ready_package": ("بستهٔ آماده", "Ready package"),
        "category_purchase": ("خرید بسته", "Package purchase"),
        "balance_charge": ("شارژ کیف پول", "Wallet top-up"),
    }
    type_label = type_labels.get(order_type, (order_type, order_type))[0 if lang == "fa" else 1]
    if order.get("is_extend") or order.get("parent_order_id") is not None:
        type_label = t('service_renewal_078e23b770', lang)
    volume = order.get("volume")
    if volume is None:
        volume_text = "—"
    elif volume == 0:
        volume_text = t('unlimited_0d936642fc', lang)
    else:
        try:
            volume_text = f"{float(volume):g} GB"
        except (TypeError, ValueError):
            volume_text = html.escape(str(volume))
    days = order.get("days")
    if days is None:
        days_text = "—"
    else:
        try:
            days_text = f"{int(days)} {t('days_7609a53ae9', lang)}"
        except (TypeError, ValueError):
            days_text = html.escape(str(days))
    receipt = bool(order.get("receipt_photo_id"))
    rejection = html.escape(str(order.get("rejected_reason") or ""))
    parent_order_id = order.get("parent_order_id")

    lines = [
        t('b_order_b_19cf963b6b', lang, fa_parts=lambda: (f'{order_id}',), en_parts=lambda: (f'{order_id}',)),
        t('b_created_b_iran_time_d5d5c19e5e', lang, fa_parts=lambda: (f'{created_at}',), en_parts=lambda: (f'{created_at}',)),
        t('b_order_stage_b_1ef9016e9e', lang, fa_parts=lambda: (f'{status_label}',), en_parts=lambda: (f'{status_label}',)),
        t('b_payment_status_b_d4b0ddf017', lang, fa_parts=lambda: (f'{payment_status[0]}',), en_parts=lambda: (f'{payment_status[1]}',)),
        t('b_amount_b_1e8fb45acb', lang, fa_parts=lambda: (f'{price_text}',), en_parts=lambda: (f'{price_text}',)),
        t('b_order_type_b_c236eee571', lang, fa_parts=lambda: (f'{html.escape(type_label)}',), en_parts=lambda: (f'{html.escape(type_label)}',)),
    ]
    if order_type != "balance_charge":
        lines.append(t('b_volume_b_6a2abdd400', lang, fa_parts=lambda: (f'{volume_text}',), en_parts=lambda: (f'{volume_text}',)))
        lines.append(t('b_duration_b_47bbc006d4', lang, fa_parts=lambda: (f'{days_text}',), en_parts=lambda: (f'{days_text}',)))
    lines.append(t('b_payment_method_b_c40179aa5d', lang, fa_parts=lambda: (f'{payment_method}',), en_parts=lambda: (f'{payment_method}',)))
    lines.append(t('b_receipt_b_ddff46b739', lang, fa_parts=lambda: (f"{('ارسال شده' if receipt else 'ثبت نشده')}",), en_parts=lambda: (f"{('Submitted' if receipt else 'Not submitted')}",)))
    lines.append(t('b_approved_b_d62b0021e2', lang, fa_parts=lambda: (f'{approved_at}',), en_parts=lambda: (f'{approved_at}',)))
    if parent_order_id:
        lines.append(t('b_renewal_for_b_cb99e241b4', lang, fa_parts=lambda: (f'{html.escape(str(parent_order_id))}',), en_parts=lambda: (f'{html.escape(str(parent_order_id))}',)))
    if rejection:
        lines.append(t('b_rejection_reason_b_e8ed3647cc', lang, fa_parts=lambda: (f'{rejection}',), en_parts=lambda: (f'{rejection}',)))
    if order_type != "balance_charge":
        lines.append(t('b_config_b_02b82e05a1', lang, fa_parts=lambda: (f'{config_status[0]}',), en_parts=lambda: (f'{config_status[1]}',)))
    text = "\n".join(lines)
    return text


@router.callback_query(F.data == "order_status")
async def show_order_status(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get("lang", "fa")
    if user_id in BLACKLIST:
        await callback.answer("⛔", show_alert=True)
        return

    user_orders = [
        order for order in orders.values()
        if isinstance(order, dict) and order.get("user_id") == user_id
    ]
    counts = {
        "approved": sum(order.get("status") == "approved" for order in user_orders),
        "pending": sum(order.get("status") in ("pending", "pending_balance_charge") for order in user_orders),
        "awaiting": sum(order.get("status") == "awaiting_payment" for order in user_orders),
        "rejected": sum(order.get("status") == "rejected" for order in user_orders),
        "cancelled": sum(order.get("status") == "cancelled" for order in user_orders),
    }
    text = (
        t('b_your_order_status_b_approv_71799a8609', lang, fa_parts=lambda: (f"{counts['approved']}", f"{counts['pending']}", f"{counts['awaiting']}", f"{counts['rejected']}", f"{counts['cancelled']}"), en_parts=lambda: (f"{counts['approved']}", f"{counts['pending']}", f"{counts['awaiting']}", f"{counts['rejected']}", f"{counts['cancelled']}"))
    )
    lookup_text, account_text = t('check_an_order_6846f4493e', lang), t('my_account_ded04b7927', lang)

    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=lookup_text, callback_data="my_order_status", style="primary"),
            InlineKeyboardButton(text=account_text, callback_data="my_account"),
        ]]),
    )
    await callback.answer()


@router.callback_query(F.data == "my_order_status")
async def request_order_number(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get("lang", "fa")
    user_states.setdefault(user_id, {})["awaiting_order_number"] = True
    text = (
        t('send_the_order_number_in_thi_3c64354e79', lang)
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=t('back_to_order_status_febe91c39a', lang),
                callback_data="order_status",
            )
        ]]),
    )
    await callback.answer()


@router.message(lambda message: (
    message.from_user is not None
    and message.text is not None
    and user_states.get(message.from_user.id, {}).get("awaiting_order_number")
))
async def handle_order_number_input(message: Message):
    user_id = message.from_user.id
    lang = get_user(user_id).get("lang", "fa")
    value = message.text.strip()
    if value.lower() == "/cancel":
        user_states[user_id].pop("awaiting_order_number", None)
        await message.answer(
            t('order_lookup_cancelled_d159d7ecd2', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=t('back_to_order_status_7a59378bd6', lang),
                    callback_data="order_status",
                )
            ]]),
        )
        return

    match = re.fullmatch(r"#([0-9]{1,12})", value)
    if not match:
        await message.reply(
            t('invalid_order_number_use_the_b59be81d8d', lang),
            parse_mode=ParseMode.HTML,
        )
        return

    user_states[user_id].pop("awaiting_order_number", None)
    order = orders.get(str(int(match.group(1))))
    if not isinstance(order, dict) or order.get("user_id") != user_id:
        await message.answer(
            t('no_order_found_with_that_num_19e6c294e7', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=t('back_to_order_status_7a59378bd6', lang),
                    callback_data="order_status",
                )
            ]]),
        )
        return

    await message.answer(
        _build_order_details_text(order, lang),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=t('back_to_order_status_febe91c39a', lang),
                callback_data="order_status",
            )
        ]]),
    )


@router.callback_query(F.data == "coupon_status")
async def coupon_status(callback: CallbackQuery):
    """نمایش وضعیت کوپن کاربر - با پشتیبانی از کوپن ادمین"""
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')

    user_state = user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied')

    # اگر در user_states نبود، از دیتابیس لود کن
    if not coupon_applied or not coupon_code:
        coupon_data = load_coupon_from_user_db(user_id)
        if coupon_data.get('coupon_applied'):
            if user_id not in user_states:
                user_states[user_id] = {}
            user_states[user_id]['coupon_code'] = coupon_data.get('coupon_code')
            user_states[user_id]['coupon_discount'] = coupon_data.get('coupon_discount')
            user_states[user_id]['coupon_applied'] = True
            coupon_code = coupon_data.get('coupon_code')
            coupon_discount = coupon_data.get('coupon_discount')
            coupon_applied = True
            logger.info(f"🏷️ [coupon_status] Coupon {coupon_code} loaded from database into user_states")

    if not coupon_applied or not coupon_code:
        text = t('you_have_no_active_coupon_5beedb6e2f', lang)

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_to_my_account_1bc257462c', lang),
                    callback_data="my_account"
                )]
            ])
        )
        await callback.answer()
        return

    coupon = COUPONS.get(coupon_code)
    if not coupon:
        text = t('your_coupon_is_invalid_pleas_93d5cc84b0', lang)

        if user_id in user_states:
            user_states[user_id].pop('coupon_code', None)
            user_states[user_id].pop('coupon_discount', None)
            user_states[user_id].pop('coupon_applied', None)
        clear_coupon_from_user_db(user_id)

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_to_my_account_1bc257462c', lang),
                    callback_data="my_account"
                )]
            ])
        )
        await callback.answer()
        return

    # بررسی اعتبار کوپن با تابع کمکی
    is_valid, reason = is_coupon_valid_for_user(coupon_code, user_id)

    if not is_valid:
        logger.warning(f"⚠️ [coupon_status] Coupon {coupon_code} invalid: {reason}")

        if user_id in user_states:
            user_states[user_id].pop('coupon_code', None)
            user_states[user_id].pop('coupon_discount', None)
            user_states[user_id].pop('coupon_applied', None)
        clear_coupon_from_user_db(user_id)

        text = t('your_coupon_is_invalid_reaso_cf717209d2', lang, fa_parts=lambda: (f'{reason}',), en_parts=lambda: (f'{reason}',))

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('apply_new_coupon_085aea99e9', lang),
                    callback_data="apply_coupon",
                    style="primary"
                )],
                [InlineKeyboardButton(
                    text=t('back_to_my_account_1bc257462c', lang),
                    callback_data="my_account"
                )]
            ])
        )
        await callback.answer()
        return

    coupon_type = coupon.get('coupon_type', 'normal')

    if coupon_type == 'admin_special':
        user_usage = coupon.get('user_usage', {})
        user_used_count = user_usage.get(str(user_id), 0)
        max_usage = coupon.get('usage_limit', 1)
        remaining = max_usage - user_used_count

        expiry_date = coupon.get('expiry_date')
        expiry_display = t('unlimited_0d936642fc', lang)
        if expiry_date:
            try:
                expiry_dt = datetime.fromisoformat(expiry_date)
                expiry_display = expiry_dt.strftime('%Y-%m-%d %H:%M') if lang == "fa" else expiry_dt.strftime('%Y-%m-%d %H:%M')
            except Exception:
                pass

        text = t('b_your_admin_coupon_status_b_155aaf2b71', lang, fa_parts=lambda: (f"{premium_emoji('note', '📝')}", f'{coupon_code}', f"{premium_emoji('card', '💳')}", f'{coupon_discount}', f"{premium_emoji('cubes', '🔢')}", f'{user_used_count}', f'{max_usage}', f"{premium_emoji('star', '🎁')}", f'{remaining}', f"{premium_emoji('amar', '📊')}", f"{premium_emoji('calendar', '📅')}", f'{expiry_display}', f"{premium_emoji('admin', '👑')}", f"{premium_emoji('light', '💡')}", f'{remaining}'), en_parts=lambda: (f"{premium_emoji('note', '📝')}", f'{coupon_code}', f"{premium_emoji('card', '💳')}", f'{coupon_discount}', f"{premium_emoji('cubes', '🔢')}", f'{user_used_count}', f'{max_usage}', f"{premium_emoji('star', '🎁')}", f'{remaining}', f"{premium_emoji('amar', '📊')}", f"{premium_emoji('calendar', '📅')}", f'{expiry_display}', f"{premium_emoji('admin', '👑')}", f"{premium_emoji('light', '💡')}", f'{remaining}'))

        buttons = [
            [InlineKeyboardButton(
                text=t('cancel_coupon_733b72e7bd', lang),
                callback_data="cancel_coupon",
                style="danger"
            )],
            [InlineKeyboardButton(
                text=t('back_to_my_account_1bc257462c', lang),
                callback_data="my_account"
            )]
        ]
    else:
        used_count = coupon.get('used_count', 0)
        usage_limit = coupon.get('usage_limit', 0)
        remaining = usage_limit - used_count if usage_limit > 0 else "نامحدود"
        is_used = user_id in coupon.get('used_by', [])

        expiry_date = coupon.get('expiry_date')
        expiry_display = t('unlimited_0d936642fc', lang)
        if expiry_date:
            try:
                expiry_dt = datetime.fromisoformat(expiry_date)
                expiry_display = expiry_dt.strftime('%Y-%m-%d %H:%M')
            except Exception:
                pass

        text = t('b_your_coupon_status_b_code_d70281ced3', lang, fa_parts=lambda: (f"{premium_emoji('note', '📝')}", f'{coupon_code}', f"{premium_emoji('card', '💳')}", f'{coupon_discount}', f"{premium_emoji('cubes', '🔢')}", f'{remaining}', f"{premium_emoji('amar', '📊')}", f"{('🟢 فعال' if not is_used else '🔴 استفاده شده')}", f"{premium_emoji('calendar', '📅')}", f'{expiry_display}', f"{premium_emoji('light', '💡')}"), en_parts=lambda: (f"{premium_emoji('note', '📝')}", f'{coupon_code}', f"{premium_emoji('card', '💳')}", f'{coupon_discount}', f"{premium_emoji('cubes', '🔢')}", f'{remaining}', f"{premium_emoji('amar', '📊')}", f"{('🟢 Active' if not is_used else '🔴 Used')}", f"{premium_emoji('calendar', '📅')}", f'{expiry_display}', f"{premium_emoji('light', '💡')}"))

        buttons = [
            [InlineKeyboardButton(
                text="❌ لغو کوپن" if not is_used else "❌ غیرفعال",
                callback_data="cancel_coupon" if not is_used else "noop",
                style="danger" if not is_used else None
            )],
            [InlineKeyboardButton(
                text=t('back_to_my_account_1bc257462c', lang),
                callback_data="my_account"
            )]
        ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )

    await safe_answer(callback)


@router.callback_query(F.data == "invite_friends")
async def invite_friends(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    await send_sticker(user_id, 'referral', '👥')
    lang = get_user(user_id).get('lang', 'fa')
    bot_inst = callback.bot or get_bot()
    bot_info = await bot_inst.get_me()
    link = f"https://t.me/{bot_info.username}?start={user_id}"
    ref_count = len([r for r in referrals.values() if r.get('referrer') == user_id])
    settings = configs_pool.get('price_settings', {})
    referral_bonus = settings.get('referral_bonus', 5000)
    if log_system:
        await log_system.log_user_action(user_id, "Viewed referral link", f"Referral count: {ref_count}")

    logger.debug(f"User {user_id} views their invite link - referral count: {ref_count} - reward: {referral_bonus:,}")

    text = t('b_invite_friends_b_your_invi_8b6ba2592b', lang, fa_parts=lambda: (f"{premium_emoji('invite', '👥')}", f"{premium_emoji('link', '🔗')}", f'{link}', f"{premium_emoji('gift', '🎁')}", f'{referral_bonus:,}', f"{premium_emoji('users', '👥')}", f'{ref_count}'), en_parts=lambda: (f"{premium_emoji('invite', '👥')}", f"{premium_emoji('link', '🔗')}", f'{link}', f"{premium_emoji('gift', '🎁')}", f'{referral_bonus:,}', f"{premium_emoji('users', '👥')}", f'{ref_count}'))
    try:
        await callback.message.delete()
    except Exception as e:
        logger.debug(f"Failed to delete the previous message: {e}")
    await callback.message.answer(text, reply_markup=get_back_only_keyboard(lang), parse_mode=ParseMode.HTML)

    await safe_answer(callback)


@router.callback_query(F.data == "change_language")
async def change_language(callback: CallbackQuery):
    user_id = callback.from_user.id
    logger.debug(f"User {user_id}changing language")

    await callback.message.edit_text(
        f"{premium_emoji('globe', '🌐')} زبان خود را انتخاب کنید / Select your language:",
        reply_markup=get_language_keyboard(user_id)
    )

    await safe_answer(callback)


@router.callback_query(F.data == "set_lang_fa")
async def set_lang_fa(callback: CallbackQuery):
    user_id = callback.from_user.id
    update_user(user_id, 'lang', 'fa')
    logger.info(f"user language {user_id} changed to Persian")

    await callback.answer("✅ زبان به فارسی تغییر کرد", show_alert=True)

    try:
        await callback.message.edit_text(
            f"{premium_emoji('globe', '🌐')} زبان خود را انتخاب کنید / Select your language:",
            reply_markup=get_language_keyboard(user_id)
        )
    except Exception:
        pass

    back_to_main = _resolve_main_handler("back_to_main")
    if back_to_main:
        await back_to_main(callback)


@router.callback_query(F.data == "set_lang_en")
async def set_lang_en(callback: CallbackQuery):
    user_id = callback.from_user.id
    update_user(user_id, 'lang', 'en')
    logger.info(f"user language {user_id} changed to English")

    await callback.answer("✅ Language changed to English", show_alert=True)

    try:
        await callback.message.edit_text(
            f"{premium_emoji('globe', '🌐')} زبان خود را انتخاب کنید / Select your language:",
            reply_markup=get_language_keyboard(user_id)
        )
    except Exception:
        pass

    back_to_main = _resolve_main_handler("back_to_main")
    if back_to_main:
        await back_to_main(callback)

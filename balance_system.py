"""
balance_system.py
-----------------
سیستم افزایش موجودی کاربران با پیشنهاد خودکار مبالغ
بر اساس ارزان‌ترین بسته هر دسته
"""

from strings import t
import html as html_module
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from database import TEHRAN_TZ, now_tehran, now_tehran_iso

from aiogram import F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CopyTextButton,
    ReplyKeyboardRemove,
)
from aiogram.enums import ParseMode
from utils.guards import admin_only
from utils.helpers import safe_answer


# ─────────────────────────────────────────────────────
# Context - ماژول اصلی از طریق register تزریق می‌شود
# ─────────────────────────────────────────────────────
_main: Any = None


def _get_current_admin_id() -> int:
    return getattr(_main, "ADMIN_ID_INT", 0)


def register_balance_handlers(dp, main_module):
    """
    ثبت تمام هندلرهای افزایش موجودی در دیسپچر
    
    Args:
        dp: Dispatcher (aiogram)
        main_module: ماژول اصلی ربات (bot.py)
    """
    global _main
    _main = main_module

    # ─── هندلرهای کاربر ───
    dp.callback_query.register(
        increase_balance, F.data == "increase_balance"
    )
    dp.callback_query.register(
        cancel_increase_balance, F.data == "cancel_increase_balance"
    )
    dp.callback_query.register(
        quick_amount_selected, F.data.startswith("quick_amount_")
    )
    dp.callback_query.register(
        custom_amount_input, F.data == "custom_amount_input"
    )

    # ─── هندلرهای ادمین ───
    dp.callback_query.register(
        admin_balance, F.data == "admin_balance"
    )
    dp.callback_query.register(
        view_balance, F.data.startswith("view_balance_")
    )
    dp.callback_query.register(
        approve_balance, F.data.startswith("approve_balance_")
    )
    dp.callback_query.register(
        reject_balance, F.data.startswith("reject_balance_")
    )

    # ⚠️ نکته: process_balance_amount به صورت دستی از
    # handle_text_messages در فایل اصلی فراخوانی می‌شود.

    logger = getattr(_main, 'logger', None)
    if logger:
        logger.info("Balance handlers registered successfully")

    return True


# ─────────────────────────────────────────────────────
# توابع کمکی داخلی
# ─────────────────────────────────────────────────────

def _get_log_system():
    """دریافت log_system از ماژول اصلی (همیشه مقدار فعلی)"""
    if _main is None:
        return None
    return getattr(_main, 'log_system', None)

def _build_balance_receipt_text(order: dict, lang: str = "fa", mode: str = "card") -> str:
    """
    ساخت متن درخواست رسید برای شارژ حساب
    - اگه تابع اصلی (build_receipt_text) در دسترس باشه، ازش استفاده می‌کنه
    - در غیر این صورت fallback می‌کنه به نسخه داخلی
    """
    # ✅ اولویت: استفاده از تابع اصلی
    if _main is not None:
        main_builder = getattr(_main, 'build_receipt_text', None)
        if callable(main_builder):
            try:
                return main_builder(order, lang, mode)
            except Exception as e:
                logger = getattr(_main, 'logger', None)
                if logger:
                    logger.warning(f"Error in build_receipt_text: {e} - fallback")
    
    # ─── fallback: نسخه داخلی (در صورت نبود تابع اصلی) ───
    return _build_balance_receipt_text_fallback(order, lang, mode)


def _build_balance_receipt_text_fallback(order: dict, lang: str = "fa", mode: str = "card") -> str:
    """نسخه fallback داخلی (فقط اگه build_receipt_text در دسترس نباشه)"""
    RLM = "\u200F"
    
    order_id = order.get('order_id', '?')
    amount = order.get('amount', 0) or order.get('price', 0)
    amount_display = t('toman_287614cf02', lang, fa_parts=lambda: (f'{amount:,}',), en_parts=lambda: (f'{amount:,}',))
    
    premium_emoji = getattr(_main, 'premium_emoji', lambda n, f: f)
    card_emoji = premium_emoji('card', '💳')
    money_emoji = premium_emoji('money', '💰')
    id_emoji = premium_emoji('id', '🆔')
    user_emoji = premium_emoji('user', '👤')
    star_emoji = premium_emoji('star', '🏦')
    note_emoji = premium_emoji('note', '📝')
    receipt_emoji = premium_emoji('receipt', '📸')
    info_emoji = premium_emoji('info', 'ℹ️')
    wallet_emoji = premium_emoji('wallet', '💰')
    
    support_username = getattr(_main, 'SUPPORT_USERNAME', '') or "@my_name_is_navid"
    support_display = support_username.strip() if support_username.strip() else "@my_name_is_navid"
    
    bank_card_number = getattr(_main, 'BANK_CARD_NUMBER', '')
    bank_card_holder = getattr(_main, 'BANK_CARD_HOLDER', '')
    bank_card_holder_en = (getattr(_main, 'BANK_CARD_HOLDER_EN', '') or '').strip() or bank_card_holder
    bank_name = getattr(_main, 'BANK_NAME', '')
    bank_name_en = (getattr(_main, 'BANK_NAME_EN', '') or '').strip() or bank_name
    
    card_num = ' '.join([bank_card_number[i:i+4] for i in range(0, 16, 4)])
    
    if mode == "reminder":
        return t('b_top_up_receipt_request_b_o_b50eff979a', lang, fa_parts=lambda: (f'{RLM}', f'{receipt_emoji}', f'{RLM}', f'{id_emoji}', f'{order_id}', f'{RLM}', f'{money_emoji}', f'{amount_display}', f'{RLM}', f'{note_emoji}', f'{RLM}', f'{order_id}', f'{RLM}', f'{receipt_emoji}'), en_parts=lambda: (f'{receipt_emoji}', f'{id_emoji}', f'{order_id}', f'{money_emoji}', f'{amount_display}', f'{note_emoji}', f'{order_id}', f'{receipt_emoji}'))
    
    # mode == "card"
    return t('b_balance_top_up_payment_b_o_ade33a7207', lang, fa_parts=lambda: (f'{RLM}', f'{wallet_emoji}', f'{RLM}', f'{id_emoji}', f'{order_id}', f'{RLM}', f'{money_emoji}', f'{amount_display}', f'{RLM}', f'{card_emoji}', f'{RLM}', f'{card_num}', f'{RLM}', f'{user_emoji}', f'{bank_card_holder}', f'{RLM}', f'{star_emoji}', f'{bank_name}', f'{RLM}', f'{info_emoji}', f'{support_display}', f'{RLM}', f'{note_emoji}', f'{RLM}', f'{RLM}', f'{order_id}', f'{RLM}', f'{receipt_emoji}'), en_parts=lambda: (f'{wallet_emoji}', f'{id_emoji}', f'{order_id}', f'{money_emoji}', f'{amount_display}', f'{card_emoji}', f'{card_num}', f'{user_emoji}', f'{bank_card_holder_en}', f'{star_emoji}', f'{bank_name_en}', f'{info_emoji}', f'{support_display}', f'{note_emoji}', f'{order_id}', f'{receipt_emoji}'))


def get_balance_quick_amounts() -> List[Dict[str, Any]]:
    """دریافت مبالغ پیشنهادی از ارزان‌ترین بسته هر دسته"""
    amounts: List[Dict[str, Any]] = []
    if _main is None:
        return amounts

    ready_packages = getattr(_main, 'READY_PACKAGES', {})
    categories = ready_packages.get('categories', [])

    for cat in categories:
        if not cat.get('is_active', True):
            continue

        active_packages = [
            p for p in cat.get('packages', [])
            if p.get('is_active', True)
        ]
        if not active_packages:
            continue

        cheapest = min(active_packages, key=lambda p: p.get('price', 0))
        price = cheapest.get('price', 0)
        if price <= 0:
            continue

        volume = cheapest.get('volume', 0)
        if volume == 0:
            volume_display = "∞"
        elif volume >= 100:
            volume_display = f"{volume}G"
        else:
            volume_display = f"{volume}GB"

        amounts.append({
            'amount': price,
            'category_name': cat.get('name', 'بسته'),
            'category_name_en': cat.get('name_en', cat.get('name', 'Package')),  # ✅ جدید
            'category_id': cat.get('id'),
            'package_id': cheapest.get('id'),
            'volume': volume,
            'volume_display': volume_display,
            'days': cheapest.get('days', 30),
        })

    return amounts


def get_most_expensive_package_amount() -> int:
    """گران‌ترین بسته فعال در همه دسته‌ها"""
    if _main is None:
        return 0

    max_amount = 0
    ready_packages = getattr(_main, 'READY_PACKAGES', {})

    for cat in ready_packages.get('categories', []):
        if not cat.get('is_active', True):
            continue
        for pkg in cat.get('packages', []):
            if pkg.get('is_active', True):
                price = pkg.get('price', 0)
                if price > max_amount:
                    max_amount = price

    return max_amount


def create_balance_order(user_id: int, amount: int) -> int:
    """ایجاد درخواست شارژ حساب"""
    if _main is None:
        return 0

    orders = _main.orders
    now = now_tehran()

    max_id = max(
        [o.get('order_id', 0) for o in orders.values() if isinstance(o, dict)],
        default=0
    )
    order_id = max_id + 1

    base_price = amount
    payable_amount = amount
    discount_offset = 0

    sms_manager = getattr(_main, 'sms_payment_manager', None)
    if sms_manager and sms_manager.is_enabled():
        try:
            window_min = sms_manager.get_window_minutes()
            payable_amount, discount_offset = sms_manager.db.reserve_unique_payable_amount(
                order_id=order_id,
                order_type='balance_charge',
                user_id=user_id,
                base_price=base_price,
                window_minutes=window_min
            )
        except Exception as e:
            logger_inst = getattr(_main, 'logger', None)
            if logger_inst:
                logger_inst.error(f"Error reserving unique top-up amount: {e}")
            raise RuntimeError(f"Could not reserve unique amount: {e}") from e

    orders[str(order_id)] = {
        'order_id': order_id,
        'user_id': user_id,
        'amount': payable_amount,
        'base_price': base_price,
        'payable_amount': payable_amount,
        'discount_offset': discount_offset,
        'volume': 0,
        'days': 0,
        'price': payable_amount,
        'type': 'balance_charge',
        'status': 'awaiting_payment',
        'date': now.strftime("%Y-%m-%d %H:%M:%S"),
        'receipt_photo_id': None,
        'config_link': None,
        'email': None,
        'payment_method': 'card',
        'rejected_reason': '',
        'created_at': now_tehran_iso(),
        'updated_at': now_tehran_iso()
    }

    _main.save_json(_main.DB_FILES['orders'], orders)

    logger = getattr(_main, 'logger', None)
    if logger:
        logger.info(f"Top-up request #{order_id} created for user {user_id} with amount {amount}")

    return order_id


# ─────────────────────────────────────────────────────
# هندلرهای کاربر
# ─────────────────────────────────────────────────────

async def increase_balance(callback: CallbackQuery):
    """نمایش صفحه افزایش موجودی با مبالغ پیشنهادی"""
    if _main is None:
        await callback.answer(t('i18n_system_error', 'fa'), show_alert=True)
        return

    user_id = callback.from_user.id

    # ─── چک لیست سیاه ───
    if user_id in _main.BLACKLIST:
        await _main.notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', _main.get_user(user_id).get('lang', 'fa')), show_alert=True)
        return

    # ─── چک تایید کاربر ───
    can_purchase, msg = _main.can_user_purchase(user_id)
    if not can_purchase:
        lang = _main.get_user(user_id).get('lang', 'fa')
        await callback.answer(
            msg if lang == "fa"
            else t('i18n_pending_admin_approval', lang),
            show_alert=True
        )
        return

    # ─── چک عضویت اجباری ───
    if not await _main.check_membership(user_id):
        lang = _main.get_user(user_id).get('lang', 'fa')
        await callback.answer(
            t('please_verify_your_membershi_28b48b1f0b', lang),
            show_alert=True
        )
        return

    user_state = _main.user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)

    await _main.send_sticker(user_id, 'money', '💰')

    lang = _main.get_user(user_id).get('lang', 'fa')
    settings = _main.configs_pool.get('price_settings', {})
    min_charge = settings.get('min_charge', 10000)
    max_charge = settings.get('max_charge', 5000000)

    quick_amounts = get_balance_quick_amounts()
    max_package_amount = get_most_expensive_package_amount()

    # ─── ساخت دکمه‌ها ───
    buttons = []
    seen_amounts = set()

    # ✅ دکمه‌های ارزان‌ترین بسته هر دسته
    for item in quick_amounts:
        amount = item['amount']
        if amount in seen_amounts:
            continue
        seen_amounts.add(amount)

        # انتخاب نام بر اساس زبان
        if lang == "fa":
            name = item['category_name']
            btn_text = t('enough_for_t_8b1a8ebe1b', lang, fa_parts=lambda: (f'{name}', f'{amount:,}'))
        else:
            name = item['category_name_en']
            btn_text = t('enough_for_t_8b1a8ebe1b', lang, en_parts=lambda: (f'{name}', f'{amount:,}'))

        buttons.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"quick_amount_{amount}",
            style="primary"
        )])

    # ✅ گران‌ترین بسته
    if max_package_amount > 0 and max_package_amount not in seen_amounts:
        btn_text = t('toman_287614cf02', lang, fa_parts=lambda: (f'{max_package_amount:,}',), en_parts=lambda: (f'{max_package_amount:,}',))

        buttons.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"quick_amount_{max_package_amount}",
            style="success"
        )])

    # ✅ مبلغ دلخواه
    buttons.append([InlineKeyboardButton(
        text=t('custom_amount_d9e883892b', lang),
        callback_data="custom_amount_input",
        style="primary"
    )])

    # ✅ منوی اصلی
    buttons.append([InlineKeyboardButton(
        text=t('main_menu_0cdd07a7cc', lang),
        callback_data="back_to_main",
        style="danger"
    )])

    # ─── متن پیام ───
    text = t('b_increase_balance_b_choose_af9dd9e091', lang, fa_parts=lambda: (f"{_main.premium_emoji('wallet', '💰')}", f"{_main.premium_emoji('note', '📝')}"), en_parts=lambda: (f"{_main.premium_emoji('wallet', '💰')}", f"{_main.premium_emoji('note', '📝')}"))

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.delete()
    except Exception as e:
        logger = getattr(_main, 'logger', None)
        if logger:
            logger.debug(f"Could not delete message: {e}")

    await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    # ─── state با حفظ کوپن ───
    _main.user_states[user_id] = {
        'awaiting_balance_selection': True,
        'timestamp': now_tehran_iso()
    }
    if coupon_applied and coupon_code:
        _main.user_states[user_id]['coupon_code'] = coupon_code
        _main.user_states[user_id]['coupon_discount'] = coupon_discount
        _main.user_states[user_id]['coupon_applied'] = True

    await safe_answer(callback)


def _build_balance_card_receipt_keyboard(
    order_id: int,
    payable_num: int,
    card_num_copy: str,
    lang: str,
    cancel_key: str = "cancel_payment_77ac7fd08e",
) -> InlineKeyboardMarkup:
    """Build inline keyboard for balance card receipts, including SMS check button when SMS auto-pay is ON."""
    rows = [
        [InlineKeyboardButton(
            text=f"📋 {t('copy_amount_in_rial_2426b59317', lang)} ({payable_num * 10:,})",
            copy_text=CopyTextButton(text=str(payable_num * 10))
        )],
        [InlineKeyboardButton(
            text=f"💳 {t('copy_card_number_0a73534ca5', lang)}",
            copy_text=CopyTextButton(text=card_num_copy)
        )],
    ]
    sms_mgr = getattr(_main, "sms_payment_manager", None) if _main is not None else None
    if sms_mgr and sms_mgr.is_enabled():
        rows.append([InlineKeyboardButton(
            text="✅ پرداخت کردم بررسی کن" if lang == "fa" else "✅ I Paid, Verify Now",
            callback_data=f"verify_sms_pay_{order_id}",
            style="success"
        )])
    rows.append([InlineKeyboardButton(
        text=f"❌ {t(cancel_key, lang)}",
        callback_data=f"cancel_order_{order_id}",
        style="danger"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def quick_amount_selected(callback: CallbackQuery):
    """انتخاب مبلغ پیشنهادی از دکمه‌ها"""
    if _main is None:
        await callback.answer(t('i18n_system_error', 'fa'), show_alert=True)
        return

    user_id = callback.from_user.id

    if user_id in _main.BLACKLIST:
        await _main.notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', _main.get_user(user_id).get('lang', 'fa')), show_alert=True)
        return

    try:
        amount = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', _main.get_user(user_id).get('lang', 'fa')), show_alert=True)
        return

    lang = _main.get_user(user_id).get('lang', 'fa')
    settings = _main.configs_pool.get('price_settings', {})
    min_charge = settings.get('min_charge', 10000)
    max_charge = settings.get('max_charge', 5000000)

    if amount < min_charge or amount > max_charge:
        await callback.answer(
            t('amount_must_be_between_and_t_f29ddc7a2e', lang, fa_parts=lambda: (f'{min_charge:,}', f'{max_charge:,}'), en_parts=lambda: (f'{min_charge:,}', f'{max_charge:,}')),
            show_alert=True
        )
        return

    # ─── حفظ کوپن ───
    user_state = _main.user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)

    # ─── ساخت سفارش ───
    try:
        order_id = create_balance_order(user_id, amount)
    except Exception as e:
        err_msg = (
            t('unable_to_issue_payment_invo_287f5f0d00', lang)
        )
        await callback.answer(err_msg, show_alert=True)
        return

    order = _main.orders.get(str(order_id))
    text = _build_balance_receipt_text(order, lang, mode="card")
    payable_num = order.get('payable_amount') or order.get('price') or amount

    # ✅ شماره کارت بدون فاصله برای کپی
    bank_card_number = getattr(_main, 'BANK_CARD_NUMBER', '')
    card_num_copy = bank_card_number.replace(' ', '').replace('-', '')

    keyboard = _build_balance_card_receipt_keyboard(
        order_id=order_id,
        payable_num=payable_num,
        card_num_copy=card_num_copy,
        lang=lang,
        cancel_key="cancel_payment_77ac7fd08e",
    )

    try:
        await callback.message.delete()
    except Exception:
        pass

    payment_message = await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    _main.update_order(order_id, payment_message_id=payment_message.message_id)

    # ─── state ───
    _main.user_states[user_id] = {
        'awaiting_receipt': True,
        'current_order_id': order_id,
        'timestamp': now_tehran_iso()
    }
    if coupon_applied and coupon_code:
        _main.user_states[user_id]['coupon_code'] = coupon_code
        _main.user_states[user_id]['coupon_applied'] = True
        _main.user_states[user_id]['coupon_discount'] = coupon_discount or 0

    await safe_answer(callback, t('order_created_56134af734', lang))


async def custom_amount_input(callback: CallbackQuery):
    """درخواست مبلغ دلخواه"""
    if _main is None:
        await callback.answer(t('i18n_system_error', 'fa'), show_alert=True)
        return

    user_id = callback.from_user.id

    if user_id in _main.BLACKLIST:
        await _main.notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', _main.get_user(user_id).get('lang', 'fa')), show_alert=True)
        return

    lang = _main.get_user(user_id).get('lang', 'fa')
    settings = _main.configs_pool.get('price_settings', {})
    min_charge = settings.get('min_charge', 10000)
    max_charge = settings.get('max_charge', 5000000)

    user_state = _main.user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)

    text = t('b_custom_amount_b_min_max_pl_1d56df4786', lang, fa_parts=lambda: (f"{_main.premium_emoji('wallet', '💰')}", f"{_main.premium_emoji('warning', '⚠️')}", f'{min_charge:,}', f'{max_charge:,}', f"{_main.premium_emoji('note', '📝')}"), en_parts=lambda: (f"{_main.premium_emoji('wallet', '💰')}", f"{_main.premium_emoji('warning', '⚠️')}", f'{min_charge:,}', f'{max_charge:,}', f"{_main.premium_emoji('note', '📝')}"))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('cancel_4197bafba5', lang),
            callback_data="cancel_increase_balance",
            style="danger"
        )]
    ])

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    _main.user_states[user_id] = {
        'awaiting_amount': True,
        'timestamp': now_tehran_iso()
    }
    if coupon_applied and coupon_code:
        _main.user_states[user_id]['coupon_code'] = coupon_code
        _main.user_states[user_id]['coupon_discount'] = coupon_discount
        _main.user_states[user_id]['coupon_applied'] = True

    await safe_answer(callback)


async def cancel_increase_balance(callback: CallbackQuery):
    """انصراف از افزایش موجودی - کوپن باقی می‌ماند"""
    if _main is None:
        await callback.answer(t('i18n_system_error', 'fa'), show_alert=True)
        return

    user_id = callback.from_user.id
    lang = _main.get_user(user_id).get('lang', 'fa')

    user_state = _main.user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)

    # ✅ چک واقعی کوپن
    has_real_coupon = bool(coupon_applied and coupon_code)

    if user_id in _main.user_states:
        _main.user_states.pop(user_id, None)

    if has_real_coupon:
        _main.user_states[user_id] = {
            'coupon_code': coupon_code,
            'coupon_discount': coupon_discount,
            'coupon_applied': True
        }

    try:
        await callback.message.delete()
    except Exception:
        pass

    is_admin = (user_id == _main.ADMIN_ID_INT)

    # ✅ ساخت متن - خط کوپن فقط اگه واقعاً کوپن داشت
    text = t('main_menu_c928863059', lang, fa_parts=lambda: (f"{_main.premium_emoji('rocket', '🚀')}",), en_parts=lambda: (f"{_main.premium_emoji('rocket', '🚀')}",))


    await callback.message.answer(
        text,
        reply_markup=_main.get_main_keyboard(is_admin, lang, user_id),
        parse_mode=ParseMode.HTML
    )

    await safe_answer(callback, t('cancelled_8a3eb8aae6', lang))


async def process_balance_amount(message: Message):
    """پردازش مبلغ وارد شده توسط کاربر (دستی از handle_text_messages صدا زده می‌شود)"""
    if _main is None:
        return

    user_id = message.from_user.id
    lang = _main.get_user(user_id).get('lang', 'fa')

    settings = _main.configs_pool.get('price_settings', {})
    min_charge = settings.get('min_charge', 10000)
    max_charge = settings.get('max_charge', 5000000)

    user_state = _main.user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)

    cancel_text = t('cancel_4197bafba5', lang)

    # ─── انصراف ───
    if message.text == cancel_text:
        if user_id in _main.user_states:
            _main.user_states.pop(user_id, None)

        if coupon_applied and coupon_code:
            _main.user_states[user_id] = {
                'coupon_code': coupon_code,
                'coupon_discount': coupon_discount,
                'coupon_applied': True
            }

        await message.reply(
            t('operation_cancelled_718e864eca', lang),
            reply_markup=ReplyKeyboardRemove()
        )

        is_admin = (user_id == _main.ADMIN_ID_INT)
        await message.answer(
            f"{_main.premium_emoji('rocket', '🚀')} "
            f"{t('main_menu_9ae3456442', lang)}",
            reply_markup=_main.get_main_keyboard(is_admin, lang, user_id)
        )
        return

    # ─── پردازش مبلغ ───
    try:
        amount = int(
            message.text.replace(',', '').replace('،', '').replace(' ', '').strip()
        )

        if min_charge <= amount <= max_charge:
            if user_id in _main.user_states:
                _main.user_states.pop(user_id, None)

            if coupon_applied and coupon_code:
                _main.user_states[user_id] = {
                    'coupon_code': coupon_code,
                    'coupon_discount': coupon_discount,
                    'coupon_applied': True
                }

            try:
                order_id = create_balance_order(user_id, amount)
            except Exception as e:
                err_msg = (
                    t('unable_to_issue_payment_invo_287f5f0d00', lang)
                )
                await message.reply(err_msg)
                return

            order = _main.orders.get(str(order_id))
            text = _build_balance_receipt_text(order, lang, mode="card")
            payable_num = order.get('payable_amount') or order.get('price') or amount

            # ✅ شماره کارت بدون فاصله برای کپی
            bank_card_number = getattr(_main, 'BANK_CARD_NUMBER', '')
            card_num_copy = bank_card_number.replace(' ', '').replace('-', '')

            keyboard = _build_balance_card_receipt_keyboard(
                order_id=order_id,
                payable_num=payable_num,
                card_num_copy=card_num_copy,
                lang=lang,
                cancel_key="cancel_payment_cfa1dce634",
            )

            payment_message = await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            _main.update_order(order_id, payment_message_id=payment_message.message_id)

            _main.user_states[user_id] = {
                'awaiting_receipt': True,
                'current_order_id': order_id,
                'timestamp': now_tehran_iso()
            }
            if coupon_applied and coupon_code:
                _main.user_states[user_id]['coupon_code'] = coupon_code
                _main.user_states[user_id]['coupon_applied'] = True
                _main.user_states[user_id]['coupon_discount'] = coupon_discount

        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"❌ {t('cancel_charge_bb568a81be', lang)}",
                    callback_data="cancel_increase_balance",
                    style="danger"
                )]
            ])

            await message.reply(
                t('amount_must_be_between_and_t_2da2e919b7', lang, fa_parts=lambda: (f"{_main.premium_emoji('danger', '❌')}", f'{min_charge:,}', f'{max_charge:,}', f"{_main.premium_emoji('note', '📝')}"), en_parts=lambda: (f"{_main.premium_emoji('danger', '❌')}", f'{min_charge:,}', f'{max_charge:,}', f"{_main.premium_emoji('note', '📝')}")),
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

    except ValueError:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"❌ {t('cancel_charge_bb568a81be', lang)}",
                callback_data="cancel_increase_balance",
                style="danger"
            )]
        ])

        await message.reply(
            t('please_enter_a_valid_number_aea53232ee', lang, fa_parts=lambda: (f"{_main.premium_emoji('note', '📝')}",), en_parts=lambda: (f"{_main.premium_emoji('note', '📝')}",)),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )


# ─────────────────────────────────────────────────────
# هندلرهای ادمین
# ─────────────────────────────────────────────────────

@admin_only(answer_on_denied=False, admin_id_getter=_get_current_admin_id)
async def admin_balance(callback: CallbackQuery):
    """لیست درخواست‌های شارژ برای ادمین"""
    if _main is None:
        return

    lang = _main.get_user(callback.from_user.id).get('lang', 'fa')
    valid_orders = _main.get_valid_orders()

    pending = [
        o for o in valid_orders.values()
        if o.get('type') == 'balance_charge'
        and o.get('status') == 'pending_balance_charge'
    ]

    if not pending:
        text = t('no_pending_balance_requests_17586ef2d6', lang)
        await callback.message.edit_text(
            text, reply_markup=_main.get_admin_keyboard(lang)
        )
        await safe_answer(callback)
        return

    buttons = []
    for o in pending:
        try:
            u = await _main.bot.get_chat(o['user_id'])
            name_raw = u.first_name or f"ID:{o['user_id']}"
            name_escaped = html_module.escape(name_raw[:15])
        except Exception:
            name_escaped = f"ID:{o['user_id']}"

        buttons.append([InlineKeyboardButton(
            text=f"💰 #{o['order_id']} - {name_escaped} - {o['amount']:,}",
            callback_data=f"view_balance_{o['order_id']}"
        )])

    buttons.append([InlineKeyboardButton(
        text=f"🔙 {t('back_d35a19b459', lang)}",
        callback_data="admin_panel"
    )])

    text = t('balance_requests_0db0f10b74', lang)
    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await safe_answer(callback)


@admin_only(answer_on_denied=False, admin_id_getter=_get_current_admin_id)
async def view_balance(callback: CallbackQuery):
    """مشاهده درخواست شارژ"""
    if _main is None:
        return

    lang = _main.get_user(callback.from_user.id).get('lang', 'fa')

    try:
        parts = callback.data.split("_")
        order_id = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    order = _main.orders.get(str(order_id))
    if not order:
        await callback.answer(t('i18n_order_not_found', lang), show_alert=True)
        return

    try:
        u = await _main.bot.get_chat(order['user_id'])
        uname = u.first_name or t('user_392d8d9d46', lang)
        uname_escaped = html_module.escape(uname)
    except Exception:
        uname_escaped = t('user_392d8d9d46', lang)

    date_escaped = html_module.escape(order.get('date', t('i18n_unknown', lang)))
    amount = order.get('amount', 0)
    status = order.get('status', 'unknown')

    text = t('b_balance_request_b_user_id_1f8586653d', lang, fa_parts=lambda: (f'{order_id}', f'{uname_escaped}', f"{order['user_id']}", f'{amount:,}', f'{date_escaped}', f'{status}'), en_parts=lambda: (f'{order_id}', f'{uname_escaped}', f"{order['user_id']}", f'{amount:,}', f'{date_escaped}', f'{status}'))

    buttons = []
    if status in ['pending_balance_charge', 'pending']:
        buttons.append([
            InlineKeyboardButton(
                text=t('approve_8e35ad3e33', lang),
                callback_data=f"approve_balance_{order_id}",
                style="success"
            ),
            InlineKeyboardButton(
                text=t('reject_6ed3999c19', lang),
                callback_data=f"reject_balance_{order_id}",
                style="danger"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text=t('custom_payment_36f7f89c87', lang),
                callback_data=f"custom_payment_receipt_{order_id}",
                style="primary"
            )
        ])
        if order.get('receipt_photo_id'):
            buttons.append([
                InlineKeyboardButton(
                    text=t('view_receipt_575648cc06', lang),
                    callback_data=f"view_receipt_{order_id}",
                    style="primary"
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            text=f"🔙 {t('back_d35a19b459', lang)}",
            callback_data="admin_balance"
        )
    ])

    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    await safe_answer(callback)


async def fulfill_balance_order(
    order_id: int,
    approved_by: str = "admin",
    payment_method: str = "card"
) -> Tuple[bool, str]:
    """
    سرویس مستقل تایید و افزایش موجودی کاربر (مستقل از CallbackQuery)
    با جلوگیری قطعی از شارژ مضاعف
    """
    if _main is None:
        return False, "Main module not initialized"

    order = _main.orders.get(str(order_id))
    if not order:
        return False, f"Order #{order_id} not found"

    if order.get('status') == 'approved':
        logger_inst = getattr(_main, "logger", None)
        if logger_inst:
            logger_inst.warning(f"Top-up order #{order_id} was already approved; duplicate operation rejected.")
        return True, "Already approved"

    user_id = order.get('user_id')
    amount = order.get('base_price') or order.get('amount', 0)
    lang = _main.get_user(user_id).get('lang', 'fa')

    # ─── مدیریت کوپن ───
    user_state = _main.user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)

    if not coupon_applied or not coupon_code:
        coupon_data = _main.load_coupon_from_user_db(user_id)
        if coupon_data.get('coupon_applied'):
            coupon_code = coupon_data.get('coupon_code')
            coupon_discount = coupon_data.get('coupon_discount')
            coupon_applied = True
            _main.user_states[user_id] = {
                'coupon_code': coupon_code,
                'coupon_discount': coupon_discount,
                'coupon_applied': True
            }

    try:
        _main.update_order(
            order_id,
            status='approved',
            approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
            payment_method=payment_method,
            payment_verified=True,
        )

        new_balance = _main.add_balance(user_id, amount)

        if coupon_applied and coupon_code:
            is_valid, reason = _main.is_coupon_valid_for_user(coupon_code, user_id)
            if is_valid:
                _main.save_coupon_to_user_db(user_id)
            else:
                _main.clear_coupon_from_user_db(user_id)
                if user_id in _main.user_states:
                    _main.user_states[user_id].pop('coupon_code', None)
                    _main.user_states[user_id].pop('coupon_discount', None)
                    _main.user_states[user_id].pop('coupon_applied', None)
        else:
            _main.clear_coupon_from_user_db(user_id)

        log_sys = _get_log_system()
        if log_sys:
            try:
                await log_sys.log_balance_charge_approved(order_id, user_id, amount)
            except Exception:
                pass

        try:
            _main.CustomLogger.log_event(
                'BALANCE_CHARGE_APPROVED',
                f'Top-up #{order_id} approved ({approved_by}) - user: {user_id} - {amount:,} Toman',
                user_id
            )
        except Exception:
            pass

        try:
            await _main.send_sticker(user_id, 'balance_added', '💰')
        except Exception:
            pass

        # ─── پیام به کاربر ───
        user_lang = _main.get_user(user_id).get('lang', 'fa')
        try:
            coupon_msg = ""
            await _main.bot.send_message(
                user_id,
                f"{_main.premium_emoji('success', '✅')} "
                f"{t('balance_request_approved_7d3ee8eb96', user_lang)}\n"
                f"{_main.premium_emoji('wallet', '💰')} {amount:,} "
                f"{t('toman_added_ad20fe0868', user_lang)}\n"
                f"{_main.premium_emoji('wallet', '💰')} "
                f"{t('new_balance_2b9f0edb74', user_lang)}: "
                f"{new_balance:,} {t('toman_94d5eb7aad', user_lang)}"
                f"{coupon_msg}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text=t('main_menu_0cdd07a7cc', user_lang),
                        callback_data="back_to_main",
                    )
                ]]),
            )
        except Exception as e:
            logger_inst = getattr(_main, 'logger', None)
            if logger_inst:
                logger_inst.error(f"Error sending top-up approval message: {e}")

        if log_sys:
            try:
                await log_sys.log_balance_change(
                    user_id, amount, new_balance, "add",
                    admin_id=_main.ADMIN_ID_INT if approved_by == "admin" else None,
                    details=f"Balance top-up (order #{order_id}) by {approved_by}"
                )
            except Exception:
                pass

        return True, ""
    except Exception as e:
        logger_inst = getattr(_main, 'logger', None)
        if logger_inst:
            logger_inst.error(f"Error approving top-up #{order_id}: {e}", exc_info=True)
        return False, str(e)


@admin_only(answer_on_denied=False, admin_id_getter=_get_current_admin_id)
async def approve_balance(callback: CallbackQuery, order_id: int = None):
    """تایید شارژ حساب (قابل فراخوانی از ادمین در تلگرام)"""
    if _main is None:
        return

    lang = _main.get_user(callback.from_user.id).get('lang', 'fa')

    if order_id is None:
        try:
            order_id = int(callback.data.split("_")[2])
        except (ValueError, IndexError):
            await callback.answer(t('i18n_order_process_error', lang), show_alert=True)
            return

    order = _main.orders.get(str(order_id))
    if not order:
        await callback.answer(t('i18n_order_not_found', lang), show_alert=True)
        return

    if order.get('status') == 'approved':
        await callback.answer(t('i18n_order_already_approved', lang), show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    if order.get('status') in ['rejected', 'cancelled', 'deleted']:
        await callback.answer(t('i18n_order_already_rejected', lang), show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    user_id = order['user_id']
    amount = order.get('base_price') or order.get('amount', 0)

    success, msg = await fulfill_balance_order(order_id, approved_by="admin", payment_method="card")

    if not success:
        await callback.answer(t('i18n_balance_approve_error', lang, fa_parts=lambda: (f'{msg[:40]}',), en_parts=lambda: (f'{msg[:40]}',)), show_alert=True)
        return

    # ─── ویرایش پیام ادمین ───
    user_info = _main.get_user(user_id)
    new_balance = user_info.get('balance', 0)
    try:
        success_text = t('i18n_balance_approved_admin', lang, fa_parts=lambda: (f'{order_id}', f'{amount:,}', f'{user_id}', f'{new_balance:,}', now_tehran().strftime('%Y-%m-%d %H:%M:%S')), en_parts=lambda: (f'{order_id}', f'{amount:,}', f'{user_id}', f'{new_balance:,}', now_tehran().strftime('%Y-%m-%d %H:%M:%S')))

        if callback.message.photo:
            await callback.message.edit_caption(
                caption=success_text, parse_mode=ParseMode.HTML, reply_markup=None
            )
        elif callback.message.document:
            await callback.message.edit_caption(
                caption=success_text, parse_mode=ParseMode.HTML, reply_markup=None
            )
        elif callback.message.text:
            await callback.message.edit_text(
                success_text, parse_mode=ParseMode.HTML, reply_markup=None
            )
        else:
            await callback.message.delete()
            await _main.bot.send_message(
                callback.message.chat.id, success_text, parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger = getattr(_main, 'logger', None)
        if logger:
            logger.warning(f"Error editing admin message: {e}")
        try:
            await callback.message.delete()
        except Exception:
            pass

    await callback.answer(
        t('balance_added_34c9e9c47c', lang),
        show_alert=True
    )


@admin_only(answer_on_denied=False, admin_id_getter=_get_current_admin_id)
async def reject_balance(callback: CallbackQuery):
    """رد درخواست شارژ"""
    if _main is None:
        return

    lang = _main.get_user(callback.from_user.id).get('lang', 'fa')

    try:
        parts = callback.data.split("_")
        order_id = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_invalid_callback_format', lang), show_alert=True)
        return

    order = _main.orders.get(str(order_id))
    if not order:
        await callback.answer(t('i18n_order_not_found', lang), show_alert=True)
        return

    _main.update_order(order_id, status='rejected')

    try:
        user_lang = _main.get_user(order['user_id']).get('lang', 'fa')
        amount = order.get('amount', 0)

        await _main.bot.send_message(
            order['user_id'],
            t('b_your_balance_request_was_r_14ccca2768', user_lang, fa_parts=lambda: (f"{_main.premium_emoji('fail', '❌')}", f"{_main.premium_emoji('id', '🆔')}", f'{order_id}', f"{_main.premium_emoji('wallet', '💰')}", f'{amount:,}'), en_parts=lambda: (f"{_main.premium_emoji('fail', '❌')}", f"{_main.premium_emoji('id', '🆔')}", f'{order_id}', f"{_main.premium_emoji('wallet', '💰')}", f'{amount:,}'))
        )
    except Exception as e:
        logger = getattr(_main, 'logger', None)
        if logger:
            logger.error(f"Error sending rejection message: {e}")

    log_sys = _get_log_system()
    if log_sys:
        try:
            await log_sys.log_admin_action(
                callback.from_user.id,
                f"Rejected top-up request #{order_id}",
                target_user=order['user_id'],
                details=f"Amount: {order.get('amount', 0):,} Toman"
            )
        except Exception:
            pass

    try:
        _main.CustomLogger.log_event(
            'BALANCE_REJECTED',
            f'Top-up #{order_id} rejected - user: {order["user_id"]}',
            order['user_id']
        )
    except Exception:
        pass

    await callback.answer(
        t('balance_request_rejected_41a1cb90f2', lang),
        show_alert=True
    )

    await admin_balance(callback)


# ─────────────────────────────────────────────────────
# exports
# ─────────────────────────────────────────────────────
__all__ = [
    'register_balance_handlers',
    'approve_balance',
    'fulfill_balance_order',
    'process_balance_amount',
    'create_balance_order',
    'get_balance_quick_amounts',
    'get_most_expensive_package_amount',
]
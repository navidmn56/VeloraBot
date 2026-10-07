"""
balance_system.py
-----------------
سیستم افزایش موجودی کاربران با پیشنهاد خودکار مبالغ
بر اساس ارزان‌ترین بسته هر دسته
"""

import html as html_module
from datetime import datetime
from typing import Optional, Dict, Any, List

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


# ─────────────────────────────────────────────────────
# Context - ماژول اصلی از طریق register تزریق می‌شود
# ─────────────────────────────────────────────────────
_main: Any = None


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
        logger.info("✅ Balance handlers registered successfully")

    return True


# ─────────────────────────────────────────────────────
# توابع کمکی داخلی
# ─────────────────────────────────────────────────────

def _get_log_system():
    """دریافت log_system از ماژول اصلی (همیشه مقدار فعلی)"""
    if _main is None:
        return None
    return getattr(_main, 'log_system', None)


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
    now = datetime.now()

    max_id = max(
        [o.get('order_id', 0) for o in orders.values() if isinstance(o, dict)],
        default=0
    )
    order_id = max_id + 1

    orders[str(order_id)] = {
        'order_id': order_id,
        'user_id': user_id,
        'amount': amount,
        'volume': 0,
        'days': 0,
        'price': amount,
        'type': 'balance_charge',
        'status': 'awaiting_payment',
        'date': now.strftime("%Y-%m-%d %H:%M:%S"),
        'receipt_photo_id': None,
        'config_link': None,
        'email': None,
        'payment_method': None,
        'rejected_reason': '',
        'created_at': now.isoformat(),
        'updated_at': now.isoformat()
    }

    _main.save_json(_main.DB_FILES['orders'], orders)

    logger = getattr(_main, 'logger', None)
    if logger:
        logger.info(f"💰 درخواست شارژ #{order_id} - کاربر: {user_id}, مبلغ: {amount}")

    return order_id


# ─────────────────────────────────────────────────────
# هندلرهای کاربر
# ─────────────────────────────────────────────────────

async def increase_balance(callback: CallbackQuery):
    """نمایش صفحه افزایش موجودی با مبالغ پیشنهادی"""
    if _main is None:
        await callback.answer("❌ خطا در سیستم", show_alert=True)
        return

    user_id = callback.from_user.id

    # ─── چک لیست سیاه ───
    if user_id in _main.BLACKLIST:
        await _main.notify_blacklisted_user(user_id)
        await callback.answer("⛔ دسترسی مسدود شده", show_alert=True)
        return

    # ─── چک تایید کاربر ───
    can_purchase, msg = _main.can_user_purchase(user_id)
    if not can_purchase:
        lang = _main.get_user(user_id).get('lang', 'fa')
        await callback.answer(
            msg if lang == "fa"
            else "⚠️ Your account is pending admin approval.",
            show_alert=True
        )
        return

    # ─── چک عضویت اجباری ───
    if not await _main.check_membership(user_id):
        lang = _main.get_user(user_id).get('lang', 'fa')
        await callback.answer(
            "❌ لطفاً ابتدا عضویت خود را تأیید کنید!" if lang == "fa"
            else "❌ Please verify your membership first!",
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
            btn_text = f"کافی برای {name} · {amount:,} ت"
        else:
            name = item['category_name_en']
            btn_text = f"Enough for {name} · {amount:,} T"

        buttons.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"quick_amount_{amount}",
            style="primary"
        )])

    # ✅ گران‌ترین بسته
    if max_package_amount > 0 and max_package_amount not in seen_amounts:
        if lang == "fa":
            btn_text = f"{max_package_amount:,} تومان"
        else:
            btn_text = f"{max_package_amount:,} Toman"

        buttons.append([InlineKeyboardButton(
            text=btn_text,
            callback_data=f"quick_amount_{max_package_amount}",
            style="success"
        )])

    # ✅ مبلغ دلخواه
    buttons.append([InlineKeyboardButton(
        text="✏️ مبلغ دلخواه" if lang == "fa" else "✏️ Custom Amount",
        callback_data="custom_amount_input",
        style="primary"
    )])

    # ✅ منوی اصلی
    buttons.append([InlineKeyboardButton(
        text="🏠 منوی اصلی" if lang == "fa" else "🏠 Main Menu",
        callback_data="back_to_main",
        style="danger"
    )])

    # ─── متن پیام ───
    if lang == "fa":
        text = (
            f"{_main.premium_emoji('wallet', '💰')} <b>افزایش موجودی</b>\n\n"
            f"<tg-emoji emoji-id=\"5334882760735598374\">📝</tg-emoji> "
            f"یکی از مبالغ زیر را انتخاب کنید یا مبلغ دلخواه وارد نمایید:\n\n"
            f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> "
            f"حداقل: {min_charge:,} | حداکثر: {max_charge:,} تومان"
        )
    else:
        text = (
            f"{_main.premium_emoji('wallet', '💰')} <b>Increase Balance</b>\n\n"
            f"<tg-emoji emoji-id=\"5334882760735598374\">📝</tg-emoji> "
            f"Choose an amount or enter custom:\n\n"
            f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> "
            f"Min: {min_charge:,} | Max: {max_charge:,} Toman"
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.delete()
    except Exception as e:
        logger = getattr(_main, 'logger', None)
        if logger:
            logger.debug(f"نتوانست پیام را حذف کند: {e}")

    await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    # ─── state با حفظ کوپن ───
    _main.user_states[user_id] = {
        'awaiting_balance_selection': True,
        'timestamp': datetime.now().isoformat()
    }
    if coupon_applied and coupon_code:
        _main.user_states[user_id]['coupon_code'] = coupon_code
        _main.user_states[user_id]['coupon_discount'] = coupon_discount
        _main.user_states[user_id]['coupon_applied'] = True

    try:
        await callback.answer()
    except Exception:
        pass


async def quick_amount_selected(callback: CallbackQuery):
    """انتخاب مبلغ پیشنهادی از دکمه‌ها"""
    if _main is None:
        await callback.answer("❌ خطا", show_alert=True)
        return

    user_id = callback.from_user.id

    if user_id in _main.BLACKLIST:
        await _main.notify_blacklisted_user(user_id)
        await callback.answer("⛔ دسترسی مسدود شده", show_alert=True)
        return

    try:
        amount = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("❌ خطا در پردازش", show_alert=True)
        return

    lang = _main.get_user(user_id).get('lang', 'fa')
    settings = _main.configs_pool.get('price_settings', {})
    min_charge = settings.get('min_charge', 10000)
    max_charge = settings.get('max_charge', 5000000)

    if amount < min_charge or amount > max_charge:
        await callback.answer(
            f"❌ مبلغ باید بین {min_charge:,} تا {max_charge:,} تومان باشد"
            if lang == "fa"
            else f"❌ Amount must be between {min_charge:,} and {max_charge:,} Toman",
            show_alert=True
        )
        return

    # ─── حفظ کوپن ───
    user_state = _main.user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)

    # ─── ساخت سفارش ───
    order_id = create_balance_order(user_id, amount)

    card_num = ' '.join([
        _main.BANK_CARD_NUMBER[i:i+4] for i in range(0, 16, 4)
    ])

    if lang == "fa":
        text = f"""
{_main.premium_emoji('card', '💳')} <b>پرداخت برای شارژ حساب</b>

{_main.premium_emoji('id', '🆔')} <b>شماره پیگیری:</b> #{order_id}
{_main.premium_emoji('money', '💰')} <b>مبلغ:</b> {amount:,} تومان

{_main.premium_emoji('card', '💳')} <b>شماره کارت:</b>
<code>{card_num}</code>

{_main.premium_emoji('user', '👤')} <b>به نام:</b> {_main.BANK_CARD_HOLDER}
{_main.premium_emoji('star', '🏦')} <b>بانک:</b> {_main.BANK_NAME}

{_main.premium_emoji('receipt', '📸')} لطفاً تصویر فیش واریزی را ارسال کنید
"""
    else:
        text = f"""
{_main.premium_emoji('card', '💳')} <b>Balance Top-up Payment</b>

{_main.premium_emoji('id', '🆔')} <b>Order Number:</b> #{order_id}
{_main.premium_emoji('money', '💰')} <b>Amount:</b> {amount:,} Toman

{_main.premium_emoji('card', '💳')} <b>Card Number:</b>
<code>{card_num}</code>

{_main.premium_emoji('user', '👤')} <b>Account Holder:</b> {_main.BANK_CARD_HOLDER}
{_main.premium_emoji('star', '🏦')} <b>Bank:</b> {_main.BANK_NAME}

{_main.premium_emoji('receipt', '📸')} Please send the receipt photo
"""

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📋 {'کپی مبلغ (ریال)' if lang=='fa' else 'Copy Amount (Rial)'} ({amount * 10:,})",
            copy_text=CopyTextButton(text=str(amount * 10))
        )],
        [
            InlineKeyboardButton(
                text=f"📸 {'ارسال فیش' if lang=='fa' else 'Send Receipt'}",
                callback_data=f"send_receipt_{order_id}",
                style="primary"
            ),
            InlineKeyboardButton(
                text=f"❌ {'انصراف' if lang=='fa' else 'Cancel'}",
                callback_data=f"cancel_order_{order_id}",
                style="danger"
            )
        ]
    ])

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    # ─── state ───
    _main.user_states[user_id] = {
        'awaiting_receipt': True,
        'current_order_id': order_id,
        'timestamp': datetime.now().isoformat()
    }
    if coupon_applied and coupon_code:
        _main.user_states[user_id]['coupon_code'] = coupon_code
        _main.user_states[user_id]['coupon_applied'] = True
        _main.user_states[user_id]['coupon_discount'] = coupon_discount or 0

    try:
        await callback.answer("✅ سفارش ایجاد شد" if lang == "fa" else "✅ Order created")
    except Exception:
        pass


async def custom_amount_input(callback: CallbackQuery):
    """درخواست مبلغ دلخواه"""
    if _main is None:
        await callback.answer("❌ خطا", show_alert=True)
        return

    user_id = callback.from_user.id

    if user_id in _main.BLACKLIST:
        await _main.notify_blacklisted_user(user_id)
        await callback.answer("⛔ دسترسی مسدود شده", show_alert=True)
        return

    lang = _main.get_user(user_id).get('lang', 'fa')
    settings = _main.configs_pool.get('price_settings', {})
    min_charge = settings.get('min_charge', 10000)
    max_charge = settings.get('max_charge', 5000000)

    user_state = _main.user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)

    if lang == "fa":
        text = (
            f"{_main.premium_emoji('wallet', '💰')} <b>مبلغ دلخواه</b>\n\n"
            f"<tg-emoji emoji-id=\"5334882760735598374\">📝</tg-emoji> "
            f"لطفاً مبلغ را به تومان وارد کنید:\n\n"
            f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> "
            f"حداقل: {min_charge:,} | حداکثر: {max_charge:,}"
        )
    else:
        text = (
            f"{_main.premium_emoji('wallet', '💰')} <b>Custom Amount</b>\n\n"
            f"<tg-emoji emoji-id=\"5334882760735598374\">📝</tg-emoji> "
            f"Please enter amount in Toman:\n\n"
            f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> "
            f"Min: {min_charge:,} | Max: {max_charge:,}"
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ انصراف" if lang == "fa" else "❌ Cancel",
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
        'timestamp': datetime.now().isoformat()
    }
    if coupon_applied and coupon_code:
        _main.user_states[user_id]['coupon_code'] = coupon_code
        _main.user_states[user_id]['coupon_discount'] = coupon_discount
        _main.user_states[user_id]['coupon_applied'] = True

    try:
        await callback.answer()
    except Exception:
        pass


async def cancel_increase_balance(callback: CallbackQuery):
    """انصراف از افزایش موجودی - کوپن باقی می‌ماند"""
    if _main is None:
        await callback.answer("❌ خطا", show_alert=True)
        return

    user_id = callback.from_user.id
    lang = _main.get_user(user_id).get('lang', 'fa')

    user_state = _main.user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)

    if user_id in _main.user_states:
        _main.user_states.pop(user_id, None)

    if coupon_applied and coupon_code:
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

    await callback.message.answer(
        f"{_main.premium_emoji('rocket', '🚀')} "
        f"{'منوی اصلی' if lang=='fa' else 'Main Menu'}",
        reply_markup=_main.get_main_keyboard(is_admin, lang),
        parse_mode=ParseMode.HTML
    )

    try:
        await callback.answer("❌ عملیات لغو شد" if lang == "fa" else "❌ Cancelled")
    except Exception:
        pass


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

    cancel_text = "❌ انصراف" if lang == "fa" else "❌ Cancel"

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
            "❌ عملیات لغو شد" if lang == "fa" else "❌ Operation cancelled",
            reply_markup=ReplyKeyboardRemove()
        )

        is_admin = (user_id == _main.ADMIN_ID_INT)
        await message.answer(
            f"{_main.premium_emoji('rocket', '🚀')} "
            f"{'منوی اصلی' if lang=='fa' else 'Main Menu'}",
            reply_markup=_main.get_main_keyboard(is_admin, lang)
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

            order_id = create_balance_order(user_id, amount)

            card_num = ' '.join([
                _main.BANK_CARD_NUMBER[i:i+4] for i in range(0, 16, 4)
            ])

            if lang == "fa":
                text = f"""
{_main.premium_emoji('card', '💳')} <b>پرداخت برای شارژ حساب</b>

{_main.premium_emoji('id', '🆔')} <b>شماره پیگیری:</b> #{order_id}
{_main.premium_emoji('money', '💰')} <b>مبلغ:</b> {amount:,} تومان

{_main.premium_emoji('card', '💳')} <b>شماره کارت:</b>
<code>{card_num}</code>

{_main.premium_emoji('user', '👤')} <b>به نام:</b> {_main.BANK_CARD_HOLDER}
{_main.premium_emoji('star', '🏦')} <b>بانک:</b> {_main.BANK_NAME}

{_main.premium_emoji('receipt', '📸')} لطفاً تصویر فیش واریزی را ارسال کنید
"""
            else:
                text = f"""
{_main.premium_emoji('card', '💳')} <b>Balance Top-up Payment</b>

{_main.premium_emoji('id', '🆔')} <b>Order Number:</b> #{order_id}
{_main.premium_emoji('money', '💰')} <b>Amount:</b> {amount:,} Toman

{_main.premium_emoji('card', '💳')} <b>Card Number:</b>
<code>{card_num}</code>

{_main.premium_emoji('user', '👤')} <b>Account Holder:</b> {_main.BANK_CARD_HOLDER}
{_main.premium_emoji('star', '🏦')} <b>Bank:</b> {_main.BANK_NAME}

{_main.premium_emoji('receipt', '📸')} Please send the receipt photo
"""

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"📋 {'کپی مبلغ (ریال)' if lang=='fa' else 'Copy Amount (Rial)'} ({amount * 10:,})",
                    copy_text=CopyTextButton(text=str(amount * 10))
                )],
                [
                    InlineKeyboardButton(
                        text=f"📸 {'ارسال فیش' if lang=='fa' else 'Send Receipt'}",
                        callback_data=f"send_receipt_{order_id}",
                        style="primary"
                    ),
                    InlineKeyboardButton(
                        text=f"❌ {'انصراف' if lang=='fa' else 'Cancel'}",
                        callback_data=f"cancel_order_{order_id}",
                        style="danger"
                    )
                ]
            ])

            await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

            _main.user_states[user_id] = {
                'awaiting_receipt': True,
                'current_order_id': order_id,
                'timestamp': datetime.now().isoformat()
            }
            if coupon_applied and coupon_code:
                _main.user_states[user_id]['coupon_code'] = coupon_code
                _main.user_states[user_id]['coupon_applied'] = True
                _main.user_states[user_id]['coupon_discount'] = coupon_discount

        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"❌ {'انصراف از شارژ' if lang=='fa' else 'Cancel Charge'}",
                    callback_data="cancel_increase_balance",
                    style="danger"
                )]
            ])

            await message.reply(
                f"{_main.premium_emoji('danger', '❌')} "
                f"مبلغ باید بین {min_charge:,} تا {max_charge:,} تومان باشد\n\n"
                f"{_main.premium_emoji('note', '📝')} لطفاً مجدداً مبلغ را وارد کنید:"
                if lang == "fa"
                else f"{_main.premium_emoji('danger', '❌')} "
                     f"Amount must be between {min_charge:,} and {max_charge:,} Toman\n\n"
                     f"{_main.premium_emoji('note', '📝')} Please enter again:",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

    except ValueError:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"❌ {'انصراف از شارژ' if lang=='fa' else 'Cancel Charge'}",
                callback_data="cancel_increase_balance",
                style="danger"
            )]
        ])

        await message.reply(
            f"❌ لطفاً یک عدد معتبر وارد کنید\n\n"
            f"{_main.premium_emoji('note', '📝')} مثال: 50000"
            if lang == "fa"
            else f"❌ Please enter a valid number\n\n"
                 f"{_main.premium_emoji('note', '📝')} Example: 50000",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )


# ─────────────────────────────────────────────────────
# هندلرهای ادمین
# ─────────────────────────────────────────────────────

async def admin_balance(callback: CallbackQuery):
    """لیست درخواست‌های شارژ برای ادمین"""
    if _main is None:
        return
    if callback.from_user.id != _main.ADMIN_ID_INT:
        return

    lang = _main.get_user(callback.from_user.id).get('lang', 'fa')
    valid_orders = _main.get_valid_orders()

    pending = [
        o for o in valid_orders.values()
        if o.get('type') == 'balance_charge'
        and o.get('status') == 'pending_balance_charge'
    ]

    if not pending:
        text = "✅ هیچ درخواست شارژی وجود ندارد" if lang == "fa" \
            else "✅ No pending balance requests"
        await callback.message.edit_text(
            text, reply_markup=_main.get_admin_keyboard(lang)
        )
        try:
            await callback.answer()
        except Exception:
            pass
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
        text=f"🔙 {'برگشت' if lang=='fa' else 'Back'}",
        callback_data="admin_panel"
    )])

    text = "💰 درخواست‌های شارژ" if lang == "fa" else "💰 Balance Requests"
    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    try:
        await callback.answer()
    except Exception:
        pass


async def view_balance(callback: CallbackQuery):
    """مشاهده درخواست شارژ"""
    if _main is None:
        return
    if callback.from_user.id != _main.ADMIN_ID_INT:
        return

    lang = _main.get_user(callback.from_user.id).get('lang', 'fa')

    try:
        parts = callback.data.split("_")
        order_id = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer("❌ خطا در پردازش", show_alert=True)
        return

    order = _main.orders.get(str(order_id))
    if not order:
        await callback.answer("❌ سفارش یافت نشد", show_alert=True)
        return

    try:
        u = await _main.bot.get_chat(order['user_id'])
        uname = u.first_name or "کاربر"
        uname_escaped = html_module.escape(uname)
    except Exception:
        uname_escaped = "کاربر" if lang == 'fa' else "User"

    date_escaped = html_module.escape(order.get('date', 'نامشخص'))
    amount = order.get('amount', 0)
    status = order.get('status', 'unknown')

    if lang == "fa":
        text = f"""
💰 <b>درخواست شارژ #{order_id}</b>

👤 کاربر: {uname_escaped} (ID: {order['user_id']})
💰 مبلغ: {amount:,} تومان
📅 تاریخ: {date_escaped}
📊 وضعیت: {status}
"""
    else:
        text = f"""
💰 <b>Balance Request #{order_id}</b>

👤 User: {uname_escaped} (ID: {order['user_id']})
💰 Amount: {amount:,} Toman
📅 Date: {date_escaped}
📊 Status: {status}
"""

    buttons = []
    if status in ['pending_balance_charge', 'pending']:
        buttons.append([
            InlineKeyboardButton(
                text="✅ تایید" if lang == 'fa' else "✅ Approve",
                callback_data=f"approve_balance_{order_id}",
                style="success"
            ),
            InlineKeyboardButton(
                text="❌ رد" if lang == 'fa' else "❌ Reject",
                callback_data=f"reject_balance_{order_id}",
                style="danger"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="💰 پرداخت دلخواه" if lang == 'fa' else "💰 Custom Payment",
                callback_data=f"custom_payment_receipt_{order_id}",
                style="primary"
            )
        ])
        if order.get('receipt_photo_id'):
            buttons.append([
                InlineKeyboardButton(
                    text="📸 مشاهده فیش" if lang == 'fa' else "📸 View Receipt",
                    callback_data=f"view_receipt_{order_id}",
                    style="primary"
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            text=f"🔙 {'برگشت' if lang=='fa' else 'Back'}",
            callback_data="admin_balance"
        )
    ])

    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    try:
        await callback.answer()
    except Exception:
        pass


async def approve_balance(callback: CallbackQuery, order_id: int = None):
    """تایید شارژ حساب (قابل import از فایل اصلی)"""
    if _main is None:
        return
    if callback.from_user.id != _main.ADMIN_ID_INT:
        return

    lang = _main.get_user(callback.from_user.id).get('lang', 'fa')

    if order_id is None:
        try:
            order_id = int(callback.data.split("_")[2])
        except (ValueError, IndexError):
            await callback.answer("❌ خطا در پردازش سفارش", show_alert=True)
            return

    order = _main.orders.get(str(order_id))
    if not order:
        await callback.answer("❌ سفارش یافت نشد", show_alert=True)
        return

    if order.get('status') == 'approved':
        await callback.answer("⚠️ این سفارش قبلاً تایید شده است!", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    if order.get('status') in ['rejected', 'cancelled', 'deleted']:
        await callback.answer("⚠️ این سفارش قبلاً رد یا لغو شده است!", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    user_id = order['user_id']
    amount = order.get('amount', 0)

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
            order_id, status='approved',
            approved_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            except Exception as e:
                logger = getattr(_main, 'logger', None)
                if logger:
                    logger.warning(f"خطا در لاگ: {e}")

        try:
            _main.CustomLogger.log_event(
                'BALANCE_CHARGE_APPROVED',
                f'شارژ #{order_id} تایید شد - کاربر: {user_id} - {amount:,} تومان',
                user_id
            )
        except Exception:
            pass

        await _main.send_sticker(user_id, 'balance_added', '💰')

        # ─── پیام به کاربر ───
        user_lang = _main.get_user(user_id).get('lang', 'fa')
        try:
            coupon_msg = ""
            if coupon_applied and coupon_code:
                coupon = _main.COUPONS.get(coupon_code)
                if coupon and coupon.get('status') == 'active':
                    if user_id not in coupon.get('used_by', []):
                        coupon_msg = f"\n\n🏷️ کوپن شما ({html_module.escape(coupon_code)}) همچنان معتبر است."

            await _main.bot.send_message(
                user_id,
                f"{_main.premium_emoji('success', '✅')} "
                f"{'درخواست شارژ شما تایید شد!' if user_lang == 'fa' else 'Balance request approved!'}\n"
                f"{_main.premium_emoji('wallet', '💰')} {amount:,} "
                f"{'تومان اضافه شد' if user_lang == 'fa' else 'Toman added'}\n"
                f"{_main.premium_emoji('wallet', '💰')} "
                f"{'موجودی جدید' if user_lang == 'fa' else 'New balance'}: "
                f"{new_balance:,} {'تومان' if user_lang == 'fa' else 'Toman'}"
                f"{coupon_msg}",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger = getattr(_main, 'logger', None)
            if logger:
                logger.error(f"خطا در ارسال پیام: {e}")

        if log_sys:
            try:
                await log_sys.log_balance_change(
                    user_id, amount, new_balance, "add",
                    admin_id=callback.from_user.id,
                    details=f"شارژ حساب (سفارش #{order_id})"
                )
            except Exception:
                pass

        # ─── ویرایش پیام ادمین ───
        try:
            success_text = (
                f"✅ <b>شارژ حساب #{order_id} تایید شد!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 مبلغ: {amount:,} تومان\n"
                f"👤 کاربر: {user_id}\n"
                f"💰 موجودی جدید: {new_balance:,} تومان\n"
                f"🕐 زمان: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

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
                logger.warning(f"⚠️ خطا در ویرایش پیام ادمین: {e}")
            try:
                await callback.message.delete()
            except Exception:
                pass

        await callback.answer(
            "✅ شارژ انجام شد" if lang == 'fa' else "✅ Balance added",
            show_alert=True
        )

    except Exception as e:
        logger = getattr(_main, 'logger', None)
        if logger:
            logger.error(f"❌ خطا در تایید شارژ: {e}", exc_info=True)

        if order.get('status') == 'approved':
            _main.update_order(order_id, status='pending_balance_charge')

        log_sys = _get_log_system()
        if log_sys:
            try:
                await log_sys.log_error(e, "approve_balance", user_id)
            except Exception:
                pass

        await callback.answer("❌ خطا در تایید شارژ", show_alert=True)


async def reject_balance(callback: CallbackQuery):
    """رد درخواست شارژ"""
    if _main is None:
        return
    if callback.from_user.id != _main.ADMIN_ID_INT:
        return

    lang = _main.get_user(callback.from_user.id).get('lang', 'fa')

    try:
        parts = callback.data.split("_")
        order_id = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer("❌ فرمت کالبک نامعتبر", show_alert=True)
        return

    order = _main.orders.get(str(order_id))
    if not order:
        await callback.answer("❌ سفارش یافت نشد", show_alert=True)
        return

    _main.update_order(order_id, status='rejected')

    try:
        user_lang = _main.get_user(order['user_id']).get('lang', 'fa')
        amount = order.get('amount', 0)

        if user_lang == "fa":
            await _main.bot.send_message(
                order['user_id'],
                f"{_main.premium_emoji('fail', '❌')} <b>درخواست شارژ شما رد شد!</b>\n\n"
                f"{_main.premium_emoji('id', '🆔')} سفارش: #{order_id}\n"
                f"{_main.premium_emoji('wallet', '💰')} مبلغ: {amount:,} تومان"
            )
        else:
            await _main.bot.send_message(
                order['user_id'],
                f"{_main.premium_emoji('fail', '❌')} <b>Your balance request was rejected!</b>\n\n"
                f"{_main.premium_emoji('id', '🆔')} Order: #{order_id}\n"
                f"{_main.premium_emoji('wallet', '💰')} Amount: {amount:,} Toman"
            )
    except Exception as e:
        logger = getattr(_main, 'logger', None)
        if logger:
            logger.error(f"خطا در ارسال پیام رد: {e}")

    log_sys = _get_log_system()
    if log_sys:
        try:
            await log_sys.log_admin_action(
                callback.from_user.id,
                f"رد درخواست شارژ #{order_id}",
                target_user=order['user_id'],
                details=f"مبلغ: {order.get('amount', 0):,} تومان"
            )
        except Exception:
            pass

    try:
        _main.CustomLogger.log_event(
            'BALANCE_REJECTED',
            f'شارژ #{order_id} رد شد - کاربر: {order["user_id"]}',
            order['user_id']
        )
    except Exception:
        pass

    await callback.answer(
        "✅ درخواست شارژ رد شد" if lang == 'fa' else "✅ Balance request rejected",
        show_alert=True
    )

    await admin_balance(callback)


# ─────────────────────────────────────────────────────
# exports
# ─────────────────────────────────────────────────────
__all__ = [
    'register_balance_handlers',
    'approve_balance',
    'process_balance_amount',
    'create_balance_order',
    'get_balance_quick_amounts',
    'get_most_expensive_package_amount',
]
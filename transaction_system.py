"""
transaction_system.py
---------------------
سیستم تراکنش‌ها - مستقیم از orders.json
بدون فایل جداگانه، بدون داده تکراری
"""

import logging
from datetime import datetime
from typing import Any, Optional, List, Dict, Tuple

from aiogram import F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.enums import ParseMode


# ─────────────────────────────────────────────────────
# Context
# ─────────────────────────────────────────────────────
_main: Any = None
logger = logging.getLogger(__name__)

PAGE_SIZE = 10


# ─────────────────────────────────────────────────────
# تاریخ شمسی (بدون کتابخانه)
# ─────────────────────────────────────────────────────
PERSIAN_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
]

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def _to_persian_digits(text) -> str:
    """تبدیل ارقام انگلیسی به فارسی"""
    return "".join(
        PERSIAN_DIGITS[int(ch)] if ch.isdigit() else ch
        for ch in str(text)
    )


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    """تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد)"""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]

    gy2 = gy + 1 if gm > 2 else gy

    days = (
        355666 + (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        + gd
        + g_d_m[gm - 1]
    )

    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461

    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)

    return jy, jm, jd


def format_jalali_date(dt: Optional[datetime] = None) -> str:
    """datetime → «۱۳ مهر ۱۴۰۵»"""
    if dt is None:
        dt = datetime.now()
    try:
        jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
        return _to_persian_digits(f"{jd} {PERSIAN_MONTHS[jm - 1]} {jy}")
    except Exception as e:
        logger.error(f"خطا در تبدیل تاریخ: {e}")
        return _to_persian_digits(dt.strftime("%Y-%m-%d"))


def _parse_order_date(order: Dict[str, Any]) -> Optional[datetime]:
    """پیدا کردن بهترین تاریخ از سفارش"""
    # اولویت: approved_date → date → created_at
    for key in ("approved_date", "date", "created_at"):
        val = order.get(key)
        if not val:
            continue
        try:
            # فرمت ISO
            return datetime.fromisoformat(str(val).replace(' ', 'T').split('.')[0])
        except Exception:
            try:
                # فرمت strftime
                return datetime.strptime(str(val), "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
    return None


# ─────────────────────────────────────────────────────
# استخراج تراکنش‌ها از orders
# ─────────────────────────────────────────────────────

# انواع سفارشی که به عنوان تراکنش نمایش داده می‌شن
CHARGE_TYPES = {"balance_charge"}
PURCHASE_TYPES = {"purchase", "ready_package", "category_purchase"}
EXTEND_MARKERS = {"extend"}  # type یا is_extend

# وضعیت‌هایی که تراکنش محسوب می‌شن
VALID_STATUSES = {"approved"}


def _classify_order(order: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """
    تعیین نوع تراکنش از سفارش
    Returns: (type_label, direction) یا None اگه تراکنش نیست
    """
    status = order.get("status", "")
    if status not in VALID_STATUSES:
        return None

    order_type = order.get("type", "purchase")
    is_extend = order.get("is_extend", False) or order.get("parent_order_id")

    # تمدید
    if is_extend or order_type in EXTEND_MARKERS:
        return ("تمدید سرویس", "out")

    # خرید
    if order_type in PURCHASE_TYPES:
        return ("خرید کانفیگ", "out")

    # شارژ
    if order_type in CHARGE_TYPES:
        return ("شارژ حساب", "in")

    # بقیه (test و غیره) → نمایش داده نمی‌شن
    return None


def get_user_transactions(user_id: int) -> List[Dict[str, Any]]:
    """
    استخراج تراکنش‌های کاربر از orders
    Returns: لیست تراکنش‌ها (جدیدترین اول)
    """
    if _main is None:
        return []

    orders = getattr(_main, 'orders', {})
    transactions = []

    for oid, order in orders.items():
        if not isinstance(order, dict):
            continue
        if order.get("user_id") != user_id:
            continue

        classification = _classify_order(order)
        if not classification:
            continue

        type_label, direction = classification

        # مبلغ: برای شارژ از amount، بقیه از price
        if order.get("type") == "balance_charge":
            amount = order.get("amount", 0) or order.get("price", 0)
        else:
            amount = order.get("price", 0)

        order_date = _parse_order_date(order)

        transactions.append({
            "order_id": order.get("order_id"),
            "type_label": type_label,
            "amount": abs(amount),
            "direction": direction,
            "date": order_date,
            "volume": order.get("volume", 0),
            "days": order.get("days", 0),
        })

    # جدیدترین اول
    transactions.sort(
        key=lambda t: t["date"] or datetime.min,
        reverse=True
    )
    return transactions


# ─────────────────────────────────────────────────────
# ساخت UI
# ─────────────────────────────────────────────────────

def _format_line(tx: Dict[str, Any], lang: str) -> str:
    """یک خط تراکنش"""
    amount = tx.get("amount", 0)
    direction = tx.get("direction", "in")
    label_fa = tx.get("type_label", "تراکنش")

    # ترجمه انگلیسی
    if lang == "en":
        en_map = {
            "خرید کانفیگ": "Purchase",
            "تمدید سرویس": "Extend",
            "شارژ حساب": "Charge",
        }
        label = en_map.get(label_fa, label_fa)
    else:
        label = label_fa

    # ایموجی و علامت
    if direction == "out":
        emoji = "➖"
        sign = "-"
    else:
        emoji = "➕"
        sign = "+"

    # تاریخ شمسی
    dt = tx.get("date")
    date_str = format_jalali_date(dt) if dt else "—"

    # فرمت مبلغ
    if lang == "fa":
        amount_str = _to_persian_digits(f"{amount:,}")
        return f"{emoji} <b>{sign}{amount_str} ت</b> · {label} · {date_str}"
    else:
        return f"{emoji} <b>{sign}{amount:,} T</b> · {label} · {date_str}"


def build_transactions_text(user_id: int, page: int = 0, lang: str = "fa") -> Tuple[str, int, int]:
    """ساخت متن صفحه تراکنش‌ها"""
    transactions = get_user_transactions(user_id)
    total = len(transactions)

    # خالی
    if total == 0:
        if lang == "fa":
            text = (
                "🧾 <b>تراکنش‌ها</b>\n\n"
                "📭 هنوز هیچ تراکنشی ثبت نشده است.\n\n"
                "💡 پس از اولین خرید یا شارژ، تراکنش‌ها اینجا نمایش داده می‌شوند."
            )
        else:
            text = (
                "🧾 <b>Transactions</b>\n\n"
                "📭 No transactions yet.\n\n"
                "💡 They will appear here after your first purchase or charge."
            )
        return text, 1, 0

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))

    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    page_items = transactions[start:end]

    if lang == "fa":
        header = "🧾 <b>تراکنش‌ها</b>\n\n"
    else:
        header = "🧾 <b>Transactions</b>\n\n"

    body = "\n".join(_format_line(tx, lang) for tx in page_items)

    if lang == "fa":
        footer = f"\n\n📊 مجموع: {_to_persian_digits(str(total))} تراکنش"
    else:
        footer = f"\n\n📊 Total: {total} transactions"

    return header + body + footer, total_pages, page


def build_transactions_keyboard(page: int, total_pages: int, lang: str = "fa") -> InlineKeyboardMarkup:
    """کیبورد صفحه‌بندی"""
    buttons = []

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text="◀️ قبلی" if lang == "fa" else "◀️ Prev",
                callback_data=f"tx_page_{page - 1}"
            ))

        page_text = _to_persian_digits(f"{page + 1}/{total_pages}") if lang == "fa" \
            else f"{page + 1}/{total_pages}"
        nav.append(InlineKeyboardButton(text=page_text, callback_data="noop"))

        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(
                text="بعدی ▶️" if lang == "fa" else "Next ▶️",
                callback_data=f"tx_page_{page + 1}"
            ))

        if nav:
            buttons.append(nav)

    buttons.append([InlineKeyboardButton(
        text="🔙 بازگشت به حساب کاربری" if lang == "fa" else "🔙 Back to Account",
        callback_data="my_account",
        style="danger"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─────────────────────────────────────────────────────
# هندلرها
# ─────────────────────────────────────────────────────

async def show_transactions(callback: CallbackQuery):
    """نمایش تراکنش‌ها - صفحه اول"""
    if _main is None:
        await callback.answer("❌ خطا", show_alert=True)
        return

    user_id = callback.from_user.id
    lang = _main.get_user(user_id).get('lang', 'fa')

    text, total_pages, page = build_transactions_text(user_id, page=0, lang=lang)
    keyboard = build_transactions_keyboard(page, total_pages, lang)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" not in str(e):
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    try:
        await callback.answer()
    except Exception:
        pass


async def transactions_page(callback: CallbackQuery):
    """جابه‌جایی بین صفحات"""
    if _main is None:
        await callback.answer("❌ خطا", show_alert=True)
        return

    user_id = callback.from_user.id
    lang = _main.get_user(user_id).get('lang', 'fa')

    try:
        page = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("❌ خطا", show_alert=True)
        return

    text, total_pages, page = build_transactions_text(user_id, page=page, lang=lang)
    keyboard = build_transactions_keyboard(page, total_pages, lang)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" not in str(e):
            pass

    try:
        await callback.answer()
    except Exception:
        pass


async def noop(callback: CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass


# ─────────────────────────────────────────────────────
# ثبت هندلرها
# ─────────────────────────────────────────────────────

def register_transaction_handlers(dp, main_module):
    """ثبت هندلرهای سیستم تراکنش"""
    global _main
    _main = main_module

    dp.callback_query.register(show_transactions, F.data == "my_transactions")
    dp.callback_query.register(transactions_page, F.data.startswith("tx_page_"))
    dp.callback_query.register(noop, F.data == "noop")

    logger.info("✅ Transaction handlers registered successfully")
    return True


__all__ = [
    'register_transaction_handlers',
    'get_user_transactions',
    'format_jalali_date',
    'gregorian_to_jalali',
]
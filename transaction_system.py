"""
transaction_system.py
---------------------
سیستم تراکنش‌ها - مستقیم از orders.json
- نمایش ۱۰ تای آخر با صفحه‌بندی
- دانلود کامل به صورت TXT
- تاریخ شمسی فارسی + انگلیسی
- پشتیبانی از approved / inactive / deleted (بدون نشانگر)
"""

from strings import t
import io
import logging
from datetime import datetime
from typing import Any, Optional, List, Dict, Tuple

from database import TEHRAN_TZ, now_tehran

from aiogram import F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BufferedInputFile,
)
from aiogram.enums import ParseMode
from utils.helpers import safe_answer


# ─────────────────────────────────────────────────────
# Context
# ─────────────────────────────────────────────────────
_main: Any = None
logger = logging.getLogger(__name__)

PAGE_SIZE = 10


# ─────────────────────────────────────────────────────
# وضعیت‌های مجاز (فقط برای فیلتر کردن - نمایش داده نمی‌شه)
# ─────────────────────────────────────────────────────
VALID_STATUSES = {"approved", "inactive", "deleted"}


# ─────────────────────────────────────────────────────
# تاریخ شمسی
# ─────────────────────────────────────────────────────
PERSIAN_MONTHS_FA = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
]

PERSIAN_MONTHS_EN = [
    "farvardin", "ordibehesht", "khordad", "tir", "mordad", "shahrivar",
    "mehr", "aban", "azar", "dey", "bahman", "esfand"
]

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def _to_persian_digits(text) -> str:
    """تبدیل ارقام انگلیسی به فارسی"""
    return "".join(
        PERSIAN_DIGITS[int(ch)] if ch.isdigit() else ch
        for ch in str(text)
    )


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    """تبدیل تاریخ میلادی به شمسی"""
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


def format_jalali_date(dt: Optional[datetime] = None, lang: str = "fa") -> str:
    """
    datetime → تاریخ شمسی (بدون زمان)
    - فارسی: «۱۳ مهر ۱۴۰۵»
    - انگلیسی: «15 mehr 1405»
    """
    if dt is None:
        dt = now_tehran()

    try:
        jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)

        if lang == "fa":
            month_name = PERSIAN_MONTHS_FA[jm - 1]
            return _to_persian_digits(f"{jd} {month_name} {jy}")
        else:
            month_name = PERSIAN_MONTHS_EN[jm - 1]
            return f"{jd} {month_name} {jy}"

    except Exception as e:
        logger.error(f"Error converting date: {e}")
        return _to_persian_digits(dt.strftime("%Y-%m-%d"))


def _parse_order_date(order: Dict[str, Any]) -> Optional[datetime]:
    """پیدا کردن بهترین تاریخ از سفارش"""
    for key in ("approved_date", "date", "created_at"):
        val = order.get(key)
        if not val:
            continue
        try:
            return datetime.fromisoformat(str(val).replace(' ', 'T').split('.')[0])
        except Exception:
            try:
                return datetime.strptime(str(val), "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
    return None


# ─────────────────────────────────────────────────────
# استخراج تراکنش‌ها
# ─────────────────────────────────────────────────────
CHARGE_TYPES = {"balance_charge"}
PURCHASE_TYPES = {"purchase", "ready_package", "category_purchase"}
EXTEND_MARKERS = {"extend"}


def _classify_order(order: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """تعیین نوع تراکنش"""
    status = order.get("status", "")
    if status not in VALID_STATUSES:
        return None

    order_type = order.get("type", "purchase")
    is_extend = order.get("is_extend", False) or order.get("parent_order_id")

    if is_extend or order_type in EXTEND_MARKERS:
        return ("تمدید سرویس", "out")
    if order_type in PURCHASE_TYPES:
        return ("خرید کانفیگ", "out")
    if order_type in CHARGE_TYPES:
        return ("شارژ حساب", "in")
    return None


def get_user_transactions(user_id: int) -> List[Dict[str, Any]]:
    """استخراج تراکنش‌های کاربر از orders"""
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
        })

    transactions.sort(key=lambda t: t["date"] or datetime.min, reverse=True)
    return transactions


# ─────────────────────────────────────────────────────
# فرمت‌ها
# ─────────────────────────────────────────────────────

def _get_en_label(fa_label: str) -> str:
    return {
        "خرید کانفیگ": "Purchase",
        "تمدید سرویس": "Extend",
        "شارژ حساب": "Charge",
    }.get(fa_label, fa_label)


def _format_line(tx: Dict[str, Any], lang: str) -> str:
    """یک خط تراکنش برای نمایش در بات و فایل"""
    amount = tx.get("amount", 0)
    direction = tx.get("direction", "in")
    label_fa = tx.get("type_label", "تراکنش")

    label = _get_en_label(label_fa) if lang == "en" else label_fa

    if direction == "out":
        emoji = "➖"
        sign = "-"
    else:
        emoji = "➕"
        sign = "+"

    dt = tx.get("date")
    date_str = format_jalali_date(dt, lang=lang) if dt else "—"

    if lang == "fa":
        amount_str = _to_persian_digits(f"{amount:,}")
        return t('b_t_b_47ab934499', lang, fa_parts=lambda: (f'{emoji}', f'{sign}', f'{amount_str}', f'{label}', f'{date_str}'))
    else:
        return t('b_t_b_47ab934499', lang, en_parts=lambda: (f'{emoji}', f'{sign}', f'{amount:,}', f'{label}', f'{date_str}'))


# ─────────────────────────────────────────────────────
# ساخت متن صفحه
# ─────────────────────────────────────────────────────

def build_transactions_text(user_id: int, page: int = 0, lang: str = "fa") -> Tuple[str, int, int]:
    """ساخت متن صفحه تراکنش‌ها"""
    transactions = get_user_transactions(user_id)
    total = len(transactions)

    if total == 0:
        text = t('b_transactions_b_no_transact_348970569d', lang)
        return text, 1, 0

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))

    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    page_items = transactions[start:end]

    header = t('b_transactions_b_8cf63ce8eb', lang)

    body = "\n".join(_format_line(tx, lang) for tx in page_items)

    if total <= PAGE_SIZE:
        footer = t('total_transactions_f070cc5f86', lang, fa_parts=lambda: (f'{_to_persian_digits(str(total))}',), en_parts=lambda: (f'{total}',))
    else:
        footer = (
            t('showing_to_of_use_download_a_288c0b817b', lang, fa_parts=lambda: (f'{_to_persian_digits(str(start + 1))}', f'{_to_persian_digits(str(end))}', f'{_to_persian_digits(str(total))}'), en_parts=lambda: (f'{start + 1}', f'{end}', f'{total}'))
        )

    return header + body + footer, total_pages, page


# ─────────────────────────────────────────────────────
# ساخت فایل TXT
# ─────────────────────────────────────────────────────

def build_transactions_file(user_id: int, lang: str = "fa") -> Optional[BufferedInputFile]:
    """ساخت فایل TXT با تمام تراکنش‌ها"""
    transactions = get_user_transactions(user_id)

    if not transactions:
        return None

    user = _main.get_user(user_id) if _main else {}
    user_name = user.get("name", f"user_{user_id}")

    # محاسبه خلاصه
    total_in = sum(t["amount"] for t in transactions if t["direction"] == "in")
    total_out = sum(t["amount"] for t in transactions if t["direction"] == "out")

    lines = []

    # ═══════════════════════════════════════
    # 🇮🇷 فارسی
    # ═══════════════════════════════════════
    if lang == "fa":
        lines.append("=" * 60)
        lines.append(t('transaction_history_46a97bd4c5', lang))
        lines.append("=" * 60)
        lines.append(t('user_b02c4b2ff7', lang, fa_parts=lambda: (f'{user_name}',)))
        lines.append(t('id_d9e4bfd210', lang, fa_parts=lambda: (f'{user_id}',)))
        lines.append(t('report_time_b2421132ee', lang, fa_parts=lambda: (f"{format_jalali_date(now_tehran(), 'fa')}",)))
        lines.append(t('total_transactions_c7459d1b55', lang, fa_parts=lambda: (f'{_to_persian_digits(str(len(transactions)))}',)))
        lines.append("=" * 60)
        lines.append("")

        # خلاصه
        lines.append(t('summary_216b1f99f9', lang))
        lines.append(t('total_in_t_056163a02c', lang, fa_parts=lambda: (f'{total_in:,}',)))
        lines.append(t('total_out_t_f259154f3a', lang, fa_parts=lambda: (f'{total_out:,}',)))
        lines.append("")
        lines.append("=" * 60)
        lines.append(t('transactions_6343e36e6e', lang))
        lines.append("=" * 60)
        lines.append("")

        for i, tx in enumerate(transactions, 1):
            amount = tx["amount"]
            direction = tx["direction"]
            label = tx["type_label"]
            dt = tx.get("date")
            date_str = format_jalali_date(dt, 'fa') if dt else "—"
            order_id = tx.get("order_id", "—")

            sign = "+" if direction == "in" else "-"

            lines.append(
                t('order_8bf572861a', lang, fa_parts=lambda: (f'{i}', f'{sign}', f'{amount:,}', f'{label}', f'{date_str}', f'{order_id}'))
            )

    # ═══════════════════════════════════════
    # 🇬🇧 انگلیسی
    # ═══════════════════════════════════════
    else:
        lines.append("=" * 60)
        lines.append(t('transaction_history_46a97bd4c5', lang))
        lines.append("=" * 60)
        lines.append(t('user_b02c4b2ff7', lang, en_parts=lambda: (f'{user_name}',)))
        lines.append(t('id_d9e4bfd210', lang, en_parts=lambda: (f'{user_id}',)))
        lines.append(t('report_time_b2421132ee', lang, en_parts=lambda: (f"{format_jalali_date(now_tehran(), 'en')}",)))
        lines.append(t('total_transactions_c7459d1b55', lang, en_parts=lambda: (f'{len(transactions)}',)))
        lines.append("=" * 60)
        lines.append("")

        lines.append(t('summary_216b1f99f9', lang))
        lines.append(t('total_in_t_056163a02c', lang, en_parts=lambda: (f'{total_in:,}',)))
        lines.append(t('total_out_t_f259154f3a', lang, en_parts=lambda: (f'{total_out:,}',)))
        lines.append("")
        lines.append("=" * 60)
        lines.append(t('transactions_6343e36e6e', lang))
        lines.append("=" * 60)
        lines.append("")

        for i, tx in enumerate(transactions, 1):
            amount = tx["amount"]
            direction = tx["direction"]
            label = _get_en_label(tx["type_label"])
            dt = tx.get("date")
            date_str = format_jalali_date(dt, 'en') if dt else "—"
            order_id = tx.get("order_id", "—")

            sign = "+" if direction == "in" else "-"

            lines.append(
                t('order_8bf572861a', lang, en_parts=lambda: (f'{i}', f'{sign}', f'{amount:,}', f'{label}', f'{date_str}', f'{order_id}'))
            )

    # Footer
    lines.append("")
    lines.append("=" * 60)
    lines.append("🤖 VeloraBot - Transaction Report")
    lines.append("=" * 60)

    text = "\n".join(lines)

    buf = io.BytesIO()
    buf.write(text.encode("utf-8"))
    buf.seek(0)

    filename = f"transactions_{user_id}_{now_tehran().strftime('%Y%m%d_%H%M%S')}.txt"

    return BufferedInputFile(buf.read(), filename=filename)


# ─────────────────────────────────────────────────────
# کیبورد
# ─────────────────────────────────────────────────────

def build_transactions_keyboard(
    page: int,
    total_pages: int,
    total_count: int,
    lang: str = "fa"
) -> InlineKeyboardMarkup:
    """کیبورد صفحه‌بندی + دانلود"""
    buttons = []

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text=t('prev_ad2dbc546b', lang),
                callback_data=f"tx_page_{page - 1}"
            ))

        page_text = (
            _to_persian_digits(f"{page + 1}/{total_pages}")
            if lang == "fa"
            else f"{page + 1}/{total_pages}"
        )
        nav.append(InlineKeyboardButton(text=page_text, callback_data="noop"))

        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(
                text=t('next_c99400f27f', lang),
                callback_data=f"tx_page_{page + 1}"
            ))

        if nav:
            buttons.append(nav)

    if total_count > PAGE_SIZE:
        buttons.append([InlineKeyboardButton(
            text=(
                t('download_all_bea292f08d', lang, fa_parts=lambda: (f'{_to_persian_digits(str(total_count))}',), en_parts=lambda: (f'{total_count}',))
            ),
            callback_data="tx_download_all",
            style="success"
        )])

    buttons.append([InlineKeyboardButton(
        text=t('back_to_account_1a988a1538', lang),
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
        await callback.answer("❌", show_alert=True)
        return

    user_id = callback.from_user.id
    lang = _main.get_user(user_id).get('lang', 'fa')

    transactions = get_user_transactions(user_id)
    total_count = len(transactions)

    text, total_pages, page = build_transactions_text(user_id, page=0, lang=lang)
    keyboard = build_transactions_keyboard(page, total_pages, total_count, lang)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" not in str(e):
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    await safe_answer(callback)


async def transactions_page(callback: CallbackQuery):
    """جابه‌جایی بین صفحات"""
    if _main is None:
        await callback.answer("❌", show_alert=True)
        return

    user_id = callback.from_user.id
    lang = _main.get_user(user_id).get('lang', 'fa')

    try:
        page = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("❌", show_alert=True)
        return

    transactions = get_user_transactions(user_id)
    total_count = len(transactions)

    text, total_pages, page = build_transactions_text(user_id, page=page, lang=lang)
    keyboard = build_transactions_keyboard(page, total_pages, total_count, lang)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" not in str(e):
            pass

    await safe_answer(callback)


async def download_transactions(callback: CallbackQuery):
    """دانلود کامل تراکنش‌ها"""
    if _main is None:
        await callback.answer("❌", show_alert=True)
        return

    user_id = callback.from_user.id
    lang = _main.get_user(user_id).get('lang', 'fa')

    await callback.answer(t('preparing_file_cb414d63a8', lang))

    file = build_transactions_file(user_id, lang=lang)

    if not file:
        await callback.answer(
            t('no_transactions_to_download_432666d21d', lang),
            show_alert=True
        )
        return

    caption = (
        t('b_full_transactions_file_b_t_1619dd5ac2', lang)
    )

    try:
        await _main.bot.send_document(
            chat_id=user_id,
            document=file,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('main_menu_0cdd07a7cc', lang),
                    callback_data="back_to_main",
                    style="primary"
                )]
            ])
        )
    except Exception as e:
        logger.error(f"Error sending transaction file: {e}")
        await callback.answer(
            t('error_sending_file_50b16f46c9', lang),
            show_alert=True
        )


async def noop(callback: CallbackQuery):
    await safe_answer(callback)


# ─────────────────────────────────────────────────────
# ثبت هندلرها
# ─────────────────────────────────────────────────────

def register_transaction_handlers(dp, main_module):
    """ثبت هندلرهای سیستم تراکنش"""
    global _main
    _main = main_module

    dp.callback_query.register(show_transactions, F.data == "my_transactions")
    dp.callback_query.register(transactions_page, F.data.startswith("tx_page_"))
    dp.callback_query.register(download_transactions, F.data == "tx_download_all")
    dp.callback_query.register(noop, F.data == "noop")

    logger.info("Transaction handlers registered successfully")
    return True


__all__ = [
    'register_transaction_handlers',
    'get_user_transactions',
    'format_jalali_date',
    'gregorian_to_jalali',
]
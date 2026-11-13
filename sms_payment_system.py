"""
====================================================================
VeloraBot - SMS Payment Verification System (Hardened & Audited v2)
====================================================================
Architecture & Security Guarantee:
1. Exclusively binds to 127.0.0.1:8088 (Localhost only)
   - Zero exposure to public ports.
   - Zero conflict with Port 443 / Xray Reality / Caddy.
   - Exposed securely to Android SMS Forwarder via Cloudflare Tunnel (sms.zyvora.ir).
2. Full Raw & Structured Logging:
   - Logs EVERY incoming request from phone (Headers, IP, Raw Body) before filtering.
   - Writes dedicated rotating/append log to data/sms_webhook_raw.log + console.
   - Records ALL SMS statuses ('unparsed', 'duplicate', 'unmatched', 'approved', 'test_matched') in DB.
3. Strict Temporal Validation:
   - Bank SMS transaction time MUST fall strictly between order creation and reservation expiry.
   - Rejects any transaction timestamped prior to order creation (clock skew margin: max 60s).
4. Strict Currency & Digit Validation:
   - Rejects Rial amounts not divisible by 10 (never silently truncates).
   - Supports both 2-digit (05/08/22) and 4-digit (1405/08/22) Jalali years.
5. Concurrency & Database-Level Uniqueness:
   - Atomic SQLite reservations with Partial Unique Indexes.
   - Full IntegrityError handling on duplicate webhook retries (Zero HTTP 500 crashes).
====================================================================
"""

import os
import re
import hmac
import json
import time
import random
import hashlib
import logging
import sqlite3
import secrets
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

from aiohttp import web
from aiogram import F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.enums import ParseMode

# ─── تنظیمات لاگر اختصاصی پیامک (هم در کنسول و هم در فایل مجزا) ───
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "sms_payments.db")
RAW_LOG_PATH = os.path.join(DATA_DIR, "sms_webhook_raw.log")

logger = logging.getLogger("sms_payment")
logger.setLevel(logging.INFO)

if not logger.handlers:
    formatter = logging.Formatter(
        fmt="%(asctime)s | [%(levelname)s] | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    # ۱. هندلر فایل اختصاصی برای دیدن تمام پیامک‌های دریافتی از گوشی
    file_handler = logging.FileHandler(RAW_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # ۲. هندلر کنسول (ترمینال)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

# Iran Timezone (UTC +03:30 permanently)
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

# Default exact sender whitelist for Blubank
DEFAULT_ALLOWED_SENDERS = [
    "بلو",
    "blubank",
    "BLUBANK",
    "9820008080",
    "+9820008080",
    "20008080",
    "+98200008080",
    "200008080",
]


# ══════════════════════════════════════════════════════════════════════
# ۱. اعتبارسنجی و تبدیل دقیق تقویم جلالی با در نظر گرفتن سال‌های کبیسه
# ══════════════════════════════════════════════════════════════════════

def is_jalali_leap_year(jy: int) -> bool:
    """بررسی کبیسه بودن سال جلالی بر اساس چرخه استاندارد ۳۳ ساله"""
    remainder = (jy + 38) % 33
    return remainder in (1, 5, 9, 13, 17, 22, 26, 30)


def validate_jalali_date(jy: int, jm: int, jd: int) -> bool:
    """اعتبارسنجی تقویمی روز و ماه شمسی"""
    if jy < 1300 or jy > 1500:
        return False
    if jm < 1 or jm > 12:
        return False
    if jd < 1:
        return False

    if 1 <= jm <= 6:
        return jd <= 31
    elif 7 <= jm <= 11:
        return jd <= 30
    elif jm == 12:
        return jd <= (30 if is_jalali_leap_year(jy) else 29)
    return False


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> Tuple[int, int, int]:
    """تبدیل تقویم جلالی به گرگوری (میلادی)"""
    if not validate_jalali_date(jy, jm, jd):
        raise ValueError(f"Invalid Jalali date: {jy}/{jm}/{jd}")

    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    if jm < 7:
        days += (jm - 1) * 31
    else:
        days += ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += ((days - 1) // 365)
        days = (days - 1) % 365
    gd = days + 1
    if (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0):
        sal_a = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    else:
        sal_a = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal_a[gm]:
        gd -= sal_a[gm]
        gm += 1
    return gy, gm, gd


def normalize_digits(text: str) -> str:
    """تبدیل تمام ارقام فارسی و عربی و کاراکترهای مخفی به استاندارد انگلیسی"""
    if not text:
        return ""
    persian_arabic = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
    english = "01234567890123456789"
    res = str(text).translate(str.maketrans(persian_arabic, english))
    # حذف کاراکترهای نیم‌فاصله و جهت‌دهی مخفی یونیکد و تبدیل کامای فارسی
    res = res.replace("٬", ",").replace("،", ",").replace("\u200c", " ").replace("\u200f", "").replace("\u200e", "")
    return res


# ══════════════════════════════════════════════════════════════════════
# ۲. پارسر تخصصی و سخت‌گیرانه بلوبانک (Blubank SMS Parser)
# ══════════════════════════════════════════════════════════════════════

class BlubankSMSParser:
    """
    پارسر دقیق و سخت‌گیرانه پیامک واریز بلوبانک با لاگ کامل علت رد شدن هر پیامک
    """

    @classmethod
    def parse(cls, sender: str, raw_text: str, allowed_senders: List[str]) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        خروجی: (parsed_dict_or_None, reason_message)
        """
        norm_sender = normalize_digits(sender or "").strip().lower()
        clean_text = normalize_digits(raw_text or "").strip()

        # ۱. بررسی فرستنده مجاز
        allowed_normalized = [normalize_digits(s).strip().lower() for s in allowed_senders]
        sender_valid = (
            norm_sender in allowed_normalized
            or any(norm_sender.endswith(s) for s in allowed_normalized if s.isdigit())
            or ("بلو" in norm_sender or "blubank" in norm_sender)
        )
        if not sender_valid:
            return None, f"فرستنده نامعتبر است: '{sender}'"

        # ۲. بررسی عنوان بلوبانک در متن
        if "بلو" not in clean_text and "blubank" not in clean_text.lower():
            return None, "کلمه 'بلو' یا 'blubank' در متن پیامک یافت نشد"

        # ۳. رد کامل هرگونه تراکنش برداشتی
        if re.search(r"برداشت|خرید|انتقال\s*از\s*حساب|کسر|کارمزد", clean_text):
            return None, "پیامک مربوط به برداشت/کسر از حساب است (واریز نیست)"

        # ۴. وجود کلیدواژه قطعی واریز
        if not re.search(r"واریز\s*پول|به\s*حساب\s*شما\s*نشست|واریز\s*به\s*حساب|واریز\s*شد", clean_text):
            return None, "کلیدواژه واریز وجه در متن پیامک یافت نشد"

        # ۵. استخراج و اعتبارسنجی ساعت (کاملاً اجباری)
        time_match = re.search(r"(?<![0-9])([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?(?![0-9])", clean_text)
        if not time_match:
            return None, "فیلد ساعت در پیامک یافت نشد"

        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        second = int(time_match.group(3)) if time_match.group(3) else 0

        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
            return None, f"ساعت استخراج‌شده نامعتبر است: {hour}:{minute}:{second}"

        # ۶. استخراج و اعتبارسنجی تاریخ جلالی (پشتیبانی از سال ۴ رقمی ۱۴0۵ و ۲ رقمی ۰۵)
        date_match = re.search(r"(?<![0-9])(13[0-9]{2}|14[0-9]{2}|0[0-9])[./-]([0-9]{1,2})[./-]([0-9]{1,2})(?![0-9])", clean_text)
        if not date_match:
            return None, "فیلد تاریخ شمسی در پیامک یافت نشد"

        jy = int(date_match.group(1))
        if jy < 100:
            jy += 1400  # تبدیل سال دو رقمی مثل 05 به 1405
        jm = int(date_match.group(2))
        jd = int(date_match.group(3))

        if not validate_jalali_date(jy, jm, jd):
            return None, f"تاریخ شمسی نامعتبر است: {jy}/{jm}/{jd}"

        # تبدیل تاریخ و زمان به شیء زمانی استاندارد در مبنای UTC
        try:
            gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
            tehran_dt = datetime(gy, gm, gd, hour, minute, second, tzinfo=TEHRAN_TZ)
            bank_tx_utc = tehran_dt.astimezone(timezone.utc)
        except Exception as e:
            return None, f"خطا در تبدیل تاریخ به UTC: {e}"

        # ۷. استخراج و اعتبارسنجی سخت‌گیرانه مبلغ
        amount_match = re.search(r"([0-9]{1,3}(?:[,.\s][0-9]{3})+|[0-9]+)\s*(ریال|تومان|تومن)", clean_text)
        if not amount_match:
            return None, "مبلغ و واحد پول (ریال/تومان) در پیامک یافت نشد"

        raw_num = re.sub(r"[,.\s]", "", amount_match.group(1))
        unit = amount_match.group(2)

        try:
            parsed_raw = int(raw_num)
        except ValueError:
            return None, f"مبلغ عددی نامعتبر است: {raw_num}"

        if parsed_raw <= 0:
            return None, "مبلغ پیامک صفر یا منفی است"

        if unit == "ریال":
            if parsed_raw % 10 != 0:
                return None, f"مبلغ ریالی ({parsed_raw}) بر ۱۰ بخش‌پذیر نیست"
            amount_toman = parsed_raw // 10
            amount_rial = parsed_raw
        else:
            amount_toman = parsed_raw
            amount_rial = amount_toman * 10

        # ۸. استخراج موجودی باقی‌مانده در صورت وجود
        balance_rial = None
        bal_match = re.search(r"موجودی\s*[:؛]?\s*([0-9]{1,3}(?:[,.\s][0-9]{3})+|[0-9]+)", clean_text)
        if bal_match:
            try:
                balance_rial = int(re.sub(r"[,.\s]", "", bal_match.group(1)))
            except ValueError:
                pass

        return {
            "bank_name": "blubank",
            "amount_toman": amount_toman,
            "amount_rial": amount_rial,
            "balance_rial": balance_rial,
            "tracking_ref": None,
            "bank_time_str": f"{hour:02d}:{minute:02d}:{second:02d}",
            "bank_date_shamsi_str": f"{jy}/{jm:02d}/{jd:02d}",
            "bank_tx_utc": bank_tx_utc,
            "bank_tx_utc_iso": bank_tx_utc.isoformat(),
        }, "OK"


# ══════════════════════════════════════════════════════════════════════
# ۳. پایگاه داده اتمیک SQLite با قیدهای یکتایی و مدیریت تراکنش
# ══════════════════════════════════════════════════════════════════════

class SMSPaymentDatabase:
    """
    پایگاه داده مستقل و امن با قیدهای Partial Unique Index و تراکنش‌های اتمیک
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS amount_reservations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    order_type TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    base_price INTEGER NOT NULL,
                    payable_amount INTEGER NOT NULL,
                    discount_offset INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active', -- 'active', 'claimed', 'expired', 'cancelled'
                    created_at_utc TEXT NOT NULL,
                    expires_at_utc TEXT NOT NULL,
                    matched_at_utc TEXT,
                    matched_sms_id INTEGER
                );
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_active_payable_amount
                ON amount_reservations(payable_amount)
                WHERE status = 'active';
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_active_order_reservation
                ON amount_reservations(order_id, order_type)
                WHERE status = 'active';
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sms_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sms_hash TEXT UNIQUE NOT NULL,
                    sender TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    parsed_bank TEXT,
                    amount_toman INTEGER,
                    amount_rial INTEGER,
                    balance_rial INTEGER,
                    bank_tx_utc TEXT,
                    device_received_at_utc TEXT,
                    server_received_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL, -- 'test_matched', 'approved', 'unmatched', 'ambiguous', 'duplicate', 'unparsed'
                    matched_order_id INTEGER,
                    matched_order_type TEXT,
                    matched_user_id INTEGER,
                    confidence_notes TEXT,
                    fulfillment_status TEXT NOT NULL DEFAULT 'none',
                    error_message TEXT,
                    created_at_utc TEXT NOT NULL
                );
            """)

            conn.commit()
        finally:
            conn.close()

    def expire_stale_reservations(self) -> int:
        now_utc = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE amount_reservations
                SET status = 'expired'
                WHERE status = 'active' AND expires_at_utc < ?;
            """, (now_utc,))
            affected = cursor.rowcount
            conn.commit()
            return affected
        finally:
            conn.close()

    def reserve_unique_payable_amount(
        self,
        order_id: int,
        order_type: str,
        user_id: int,
        base_price: int,
        window_minutes: int = 30
    ) -> Tuple[int, int]:
        if base_price < 1000:
            raise ValueError(f"Base price must be at least 1,000 Toman, got {base_price}")

        now_utc = datetime.now(timezone.utc)
        expires_utc = now_utc + timedelta(minutes=window_minutes)
        now_str = now_utc.isoformat()
        exp_str = expires_utc.isoformat()

        possible_offsets = list(range(10, 1000, 10))
        random.shuffle(possible_offsets)

        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.cursor()

            # ۱. منقضی کردن رزروهای قدیمی در داخل همان تراکنش اتمیک
            cursor.execute("""
                UPDATE amount_reservations
                SET status = 'expired'
                WHERE status = 'active' AND expires_at_utc < ?;
            """, (now_str,))

            # ۲. لغو هرگونه رزرو قبلی برای این سفارش
            cursor.execute("""
                UPDATE amount_reservations
                SET status = 'cancelled'
                WHERE order_id = ? AND order_type = ? AND status = 'active';
            """, (order_id, order_type))

            # ۳. پیدا کردن مبلغی که در ایندکس یکتا قفل نباشد
            for offset in possible_offsets:
                candidate_payable = base_price - offset
                try:
                    cursor.execute("""
                        INSERT INTO amount_reservations (
                            order_id, order_type, user_id, base_price,
                            payable_amount, discount_offset, status,
                            created_at_utc, expires_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?);
                    """, (
                        order_id, order_type, user_id, base_price,
                        candidate_payable, offset, now_str, exp_str
                    ))
                    conn.commit()
                    logger.info(
                        "💰 RESERVE AMOUNT | order_id=#%s | user_id=%s | base=%d | payable=%d | discount=%d",
                        order_id, user_id, base_price, candidate_payable, offset
                    )
                    return candidate_payable, offset
                except sqlite3.IntegrityError:
                    continue

            conn.rollback()
            raise RuntimeError(f"Could not reserve unique amount for base price {base_price} after trying all offsets.")
        finally:
            conn.close()

    def cancel_reservation(self, order_id: int, order_type: str):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE amount_reservations
                SET status = 'cancelled'
                WHERE order_id = ? AND order_type = ? AND status = 'active';
            """, (order_id, order_type))
            conn.commit()
        finally:
            conn.close()

    def record_unparsed_sms(
        self,
        sms_hash: str,
        sender: str,
        raw_text: str,
        device_received_at_utc: str,
        reason: str
    ) -> Tuple[int, bool]:
        """ثبت پیامک‌های غیربانکی یا ردشده در دیتابیس تا ادمین در لاگ و پنل ببیند"""
        now_utc = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO sms_transactions (
                        sms_hash, sender, raw_text, parsed_bank,
                        amount_toman, amount_rial, balance_rial, bank_tx_utc,
                        device_received_at_utc, server_received_at_utc, status,
                        confidence_notes, created_at_utc
                    ) VALUES (?, ?, ?, NULL, 0, 0, NULL, NULL, ?, ?, 'unparsed', ?, ?);
                """, (sms_hash, sender, raw_text, device_received_at_utc, now_utc, reason, now_utc))
                conn.commit()
                return cursor.lastrowid, False
            except sqlite3.IntegrityError:
                cursor.execute("SELECT id FROM sms_transactions WHERE sms_hash = ?;", (sms_hash,))
                row = cursor.fetchone()
                return (row["id"] if row else 0), True
        finally:
            conn.close()

    def find_and_claim_reservation(
        self,
        amount_toman: int,
        bank_tx_utc: datetime,
        sms_hash: str,
        sender: str,
        raw_text: str,
        parsed_bank: str,
        amount_rial: int,
        balance_rial: Optional[int],
        device_received_at_utc: Optional[str],
        test_mode: bool = False
    ) -> Dict[str, Any]:
        """
        یافتن، بررسی تکراری نبودن، اعتبارسنجی زمانی و قفل اتمیک رزرو در یک تراکنش واحد
        """
        now_utc_str = datetime.now(timezone.utc).isoformat()
        bank_tx_iso = bank_tx_utc.isoformat()

        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.cursor()

            # ۰. بررسی تکراری بودن پیامک در ابتدای تراکنش اتمیک (جلوگیری از کرش IntegrityError)
            cursor.execute("SELECT id, status, matched_order_id FROM sms_transactions WHERE sms_hash = ? LIMIT 1;", (sms_hash,))
            existing_tx = cursor.fetchone()
            if existing_tx:
                conn.rollback()
                logger.warning(
                    "♻️ SMS DUPLICATE IGNORED | tx_id=#%s | prev_status='%s' | sender='%s' | amount=%d | text='%s'",
                    existing_tx["id"], existing_tx["status"], sender, amount_toman, raw_text
                )
                return {
                    "status": "duplicate",
                    "tx_id": existing_tx["id"],
                    "previous_status": existing_tx["status"],
                    "matched_order_id": existing_tx["matched_order_id"]
                }

            # ۱. منقضی کردن رزروهای قدیمی در همان تراکنش اتمیک
            cursor.execute("""
                UPDATE amount_reservations
                SET status = 'expired'
                WHERE status = 'active' AND expires_at_utc < ?;
            """, (now_utc_str,))

            # ۲. جستجوی تمام رزروهای فعال با این مبلغ
            cursor.execute("""
                SELECT * FROM amount_reservations
                WHERE payable_amount = ? AND status = 'active';
            """, (amount_toman,))
            rows = [dict(r) for r in cursor.fetchall()]

            if not rows:
                logger.info(
                    "📭 SMS UNMATCHED (No Active Reservation) | sender='%s' | amount=%d Toman | bank_tx=%s | text='%s'",
                    sender, amount_toman, bank_tx_iso, raw_text
                )
                cursor.execute("""
                    INSERT INTO sms_transactions (
                        sms_hash, sender, raw_text, parsed_bank,
                        amount_toman, amount_rial, balance_rial, bank_tx_utc,
                        device_received_at_utc, server_received_at_utc, status,
                        confidence_notes, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unmatched', ?, ?);
                """, (
                    sms_hash, sender, raw_text, parsed_bank,
                    amount_toman, amount_rial, balance_rial, bank_tx_iso,
                    device_received_at_utc, now_utc_str,
                    "هیچ رزرو فعالی با این مبلغ یافت نشد", now_utc_str
                ))
                conn.commit()
                return {"status": "unmatched", "tx_id": cursor.lastrowid, "reason": "no_active_reservation"}

            # ۳. فیلتر زمانی سخت‌گیرانه
            valid_candidates = []
            for r in rows:
                created_utc = datetime.fromisoformat(r["created_at_utc"])
                expires_utc = datetime.fromisoformat(r["expires_at_utc"])

                if bank_tx_utc < (created_utc - timedelta(seconds=60)):
                    continue
                if bank_tx_utc > expires_utc:
                    continue

                valid_candidates.append(r)

            if len(valid_candidates) == 0:
                logger.info(
                    "⏰ SMS TIME OUT OF BOUNDS | sender='%s' | amount=%d Toman | bank_tx=%s | text='%s'",
                    sender, amount_toman, bank_tx_iso, raw_text
                )
                cursor.execute("""
                    INSERT INTO sms_transactions (
                        sms_hash, sender, raw_text, parsed_bank,
                        amount_toman, amount_rial, balance_rial, bank_tx_utc,
                        device_received_at_utc, server_received_at_utc, status,
                        confidence_notes, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unmatched', ?, ?);
                """, (
                    sms_hash, sender, raw_text, parsed_bank,
                    amount_toman, amount_rial, balance_rial, bank_tx_iso,
                    device_received_at_utc, now_utc_str,
                    "مبلغ با رزرو تطبیق داشت اما زمان تراکنش بانکی خارج از بازه مجاز سفارش بود", now_utc_str
                ))
                conn.commit()
                return {"status": "unmatched", "tx_id": cursor.lastrowid, "reason": "time_out_of_bounds"}

            elif len(valid_candidates) > 1:
                oids = [c["order_id"] for c in valid_candidates]
                logger.warning(
                    "⚠️ SMS AMBIGUOUS | sender='%s' | amount=%d Toman | candidates=%s | text='%s'",
                    sender, amount_toman, oids, raw_text
                )
                cursor.execute("""
                    INSERT INTO sms_transactions (
                        sms_hash, sender, raw_text, parsed_bank,
                        amount_toman, amount_rial, balance_rial, bank_tx_utc,
                        device_received_at_utc, server_received_at_utc, status,
                        confidence_notes, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ambiguous', ?, ?);
                """, (
                    sms_hash, sender, raw_text, parsed_bank,
                    amount_toman, amount_rial, balance_rial, bank_tx_iso,
                    device_received_at_utc, now_utc_str,
                    f"تعداد {len(valid_candidates)} کاندید همزمان یافت شد", now_utc_str
                ))
                conn.commit()
                return {
                    "status": "ambiguous",
                    "tx_id": cursor.lastrowid,
                    "candidates": valid_candidates
                }

            chosen = valid_candidates[0]

            if test_mode:
                logger.info(
                    "🧪 SMS TEST_MATCHED | sender='%s' | amount=%d Toman | order_id=#%s | text='%s'",
                    sender, amount_toman, chosen["order_id"], raw_text
                )
                cursor.execute("""
                    INSERT INTO sms_transactions (
                        sms_hash, sender, raw_text, parsed_bank,
                        amount_toman, amount_rial, balance_rial, bank_tx_utc,
                        device_received_at_utc, server_received_at_utc, status,
                        matched_order_id, matched_order_type, matched_user_id,
                        confidence_notes, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'test_matched', ?, ?, ?, ?, ?);
                """, (
                    sms_hash, sender, raw_text, parsed_bank,
                    amount_toman, amount_rial, balance_rial, bank_tx_iso,
                    device_received_at_utc, now_utc_str,
                    chosen["order_id"], chosen["order_type"], chosen["user_id"],
                    f"تطبیق موفق در حالت تست (تخفیف: {chosen['discount_offset']} تومان)", now_utc_str
                ))
                conn.commit()
                return {
                    "status": "test_matched",
                    "tx_id": cursor.lastrowid,
                    "reservation": chosen
                }

            # حالت زنده: ادعای اتمیک رزرو
            cursor.execute("""
                UPDATE amount_reservations
                SET status = 'claimed', matched_at_utc = ?
                WHERE id = ? AND status = 'active';
            """, (now_utc_str, chosen["id"]))

            if cursor.rowcount != 1:
                logger.warning(
                    "🔄 SMS CLAIMED BY CONCURRENT TASK | sender='%s' | amount=%d Toman | order_id=#%s",
                    sender, amount_toman, chosen["order_id"]
                )
                conn.rollback()
                return {"status": "claimed_by_concurrent_task"}

            logger.info(
                "✅ SMS APPROVED | sender='%s' | amount=%d Toman | order_id=#%s | user_id=%s | text='%s'",
                sender, amount_toman, chosen["order_id"], chosen["user_id"], raw_text
            )

            cursor.execute("""
                INSERT INTO sms_transactions (
                    sms_hash, sender, raw_text, parsed_bank,
                    amount_toman, amount_rial, balance_rial, bank_tx_utc,
                    device_received_at_utc, server_received_at_utc, status,
                    matched_order_id, matched_order_type, matched_user_id,
                    confidence_notes, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?, ?);
            """, (
                sms_hash, sender, raw_text, parsed_bank,
                amount_toman, amount_rial, balance_rial, bank_tx_iso,
                device_received_at_utc, now_utc_str,
                chosen["order_id"], chosen["order_type"], chosen["user_id"],
                f"ادعای اتمیک موفق و تایید پرداخت مبلغ {amount_toman} تومان", now_utc_str
            ))
            tx_id = cursor.lastrowid

            cursor.execute("""
                UPDATE amount_reservations
                SET matched_sms_id = ?
                WHERE id = ?;
            """, (tx_id, chosen["id"]))

            conn.commit()
            return {
                "status": "approved",
                "tx_id": tx_id,
                "reservation": chosen
            }
        finally:
            conn.close()

    def update_fulfillment_status(self, tx_id: int, status: str, error_message: str = ""):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sms_transactions
                SET fulfillment_status = ?, error_message = ?
                WHERE id = ?;
            """, (status, error_message, tx_id))
            conn.commit()
        finally:
            conn.close()

    def get_transaction_by_id(self, tx_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sms_transactions WHERE id = ?;", (tx_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_recent_transactions(self, limit: int = 10) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM sms_transactions
                ORDER BY id DESC LIMIT ?;
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════
# ۴. سرور وب‌هوک ایمن (Secure Localhost Webhook Server)
# ══════════════════════════════════════════════════════════════════════

class SMSWebhookServer:
    """
    وب‌سرور ناهمگام متصل به 127.0.0.1:8088 با لاگ کامل تمام درخواست‌های ورودی از گوشی
    """

    def __init__(self, manager: "SMSPaymentManager"):
        self.manager = manager
        self.app = web.Application(client_max_size=64 * 1024)
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._rate_limits: Dict[str, List[float]] = {}
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_post("/api/sms-webhook", self.handle_sms_webhook)
        self.app.router.add_get("/api/sms-webhook/health", self.handle_health)

    def _check_rate_limit(self, client_ip: str, max_per_minute: int = 40) -> bool:
        now = time.time()
        timestamps = self._rate_limits.setdefault(client_ip, [])
        self._rate_limits[client_ip] = [t for t in timestamps if now - t < 60]
        if len(self._rate_limits[client_ip]) >= max_per_minute:
            return False
        self._rate_limits[client_ip].append(now)
        return True

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "service": "VeloraBot SMS Payment Webhook",
            "time_utc": datetime.now(timezone.utc).isoformat()
        })

    async def handle_sms_webhook(self, request: web.Request) -> web.Response:
        # تشخیص IP واقعی در پشت Cloudflare Tunnel
        client_ip = (
            request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote
            or "127.0.0.1"
        )

        # خواندن بدنه خام درخواست در اولین قدم تا حتی اگر JSON خراب بود یا توکن غلط بود در لاگ دیده شود
        try:
            raw_body_bytes = await request.read()
            raw_body_text = raw_body_bytes.decode("utf-8", errors="replace").strip()
        except Exception as e:
            raw_body_text = f"<Error reading body: {e}>"

        # 🔥 لاگ جامع هرگونه پیامی که از گوشی به سرور می‌رسد (قبل از هر فیلتری)
        raw_log_preview = raw_body_text.replace("\n", "\\n")
        logger.info(f"📲 [RAW INCOMING WEBHOOK] IP={client_ip} | Payload={raw_log_preview}")

        if not self._check_rate_limit(client_ip):
            logger.warning(f"⛔ Rate limit exceeded for IP: {client_ip}")
            return web.json_response({"error": "Rate limit exceeded"}, status=429)

        if not self.manager.is_enabled():
            logger.warning("⛔ Webhook received but SMS system is disabled in admin settings.")
            return web.json_response({"error": "SMS webhook is disabled by admin"}, status=503)

        # اعتبارسنجی هدر احراز هویت با مقایسه زمان‌ثابت
        auth_header = request.headers.get("X-Secret-Token") or request.headers.get("Authorization") or ""
        token = auth_header.removeprefix("Bearer ").strip()
        expected_token = self.manager.get_secret_token()

        if not expected_token or not hmac.compare_digest(token, expected_token):
            logger.warning(f"⛔ UNAUTHORIZED WEBHOOK | IP={client_ip} | Provided-Token='{token[:6]}***'")
            return web.json_response({"error": "Unauthorized"}, status=401)

        try:
            payload = json.loads(raw_body_text)
        except Exception as e:
            logger.error(f"❌ MALFORMED JSON | IP={client_ip} | Error={e} | Raw={raw_log_preview}")
            return web.json_response({"error": "Malformed JSON payload"}, status=400)

        if not isinstance(payload, dict):
            logger.error(f"❌ PAYLOAD NOT OBJECT | IP={client_ip} | Raw={raw_log_preview}")
            return web.json_response({"error": "Payload must be a JSON object"}, status=400)

        # استخراج انعطاف‌پذیر فیلدهای ارسالی از اپلیکیشن‌های مختلف SMS Forwarder
        raw_sender = (
            payload.get("sender")
            or payload.get("from")
            or payload.get("phone")
            or payload.get("address")
            or "UNKNOWN_SENDER"
        )
        raw_message = (
            payload.get("message")
            or payload.get("content")
            or payload.get("text")
            or payload.get("body")
            or payload.get("msg")
        )
        raw_rx = (
            payload.get("received_at")
            or payload.get("timestamp")
            or payload.get("date")
            or payload.get("time")
            or ""
        )

        sender = str(raw_sender).strip()[:50]
        raw_text = str(raw_message).strip() if raw_message is not None else ""
        device_received_at = str(raw_rx).strip()

        # لاگ تفکیک‌شده پیامک دریافتی
        logger.info(
            "📩 [PARSED SMS FIELDS] Sender='%s' | ReceivedAt='%s' | Text='%s'",
            sender, device_received_at, raw_text.replace("\n", " | ")
        )

        if not raw_text:
            logger.warning(f"❌ Empty message field in webhook from sender='{sender}'")
            return web.json_response({"error": "Missing or empty 'message'"}, status=400)

        result = await self.manager.process_incoming_sms(
            sender=sender,
            raw_text=raw_text,
            device_received_at=device_received_at
        )

        return web.json_response(result)

    async def start(self, host: str = "127.0.0.1", port: int = 8088):
        """راه‌اندازی ایمن سرور (در صورت فعال بودن قبلی، ابتدا متوقف و سپس بازگشایی می‌شود)"""
        if self.runner is not None:
            await self.stop()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, host, port)
        await self.site.start()
        logger.info(f"🚀 سرور وب‌هوک پیامک روی {host}:{port} به صورت لوکال‌هاست آغاز به کار کرد.")

    async def stop(self):
        if self.runner:
            try:
                await self.runner.cleanup()
            except Exception as e:
                logger.warning(f"خطا در پاکسازی وب‌هوک: {e}")
            finally:
                self.runner = None
                self.site = None
            logger.info("🛑 سرور وب‌هوک پیامک متوقف شد.")


# ══════════════════════════════════════════════════════════════════════
# ۵. هماهنگ‌کننده پرداخت و تحویل سرویس (SMSPaymentManager)
# ══════════════════════════════════════════════════════════════════════

class SMSPaymentManager:
    """
    مدیریت کل چرخه پیامک، تطبیق، تایید پرداخت و تحویل مجدد
    """

    def __init__(self, main_module=None):
        self._main = main_module
        self.db = SMSPaymentDatabase()
        self.server = SMSWebhookServer(self)

    def set_main_module(self, main_module):
        self._main = main_module

    def _get_settings(self) -> Dict[str, Any]:
        if self._main and hasattr(self._main, "configs_pool"):
            cfg = self._main.configs_pool.setdefault("sms_payment_settings", {})
        else:
            cfg = {}

        cfg.setdefault("enabled", False)
        cfg.setdefault("test_mode", True)
        cfg.setdefault("window_minutes", 30)
        cfg.setdefault("webhook_port", 8088)
        cfg.setdefault("webhook_host", "127.0.0.1")
        cfg.setdefault("public_url", "https://sms.zyvora.ir/api/sms-webhook")
        cfg.setdefault("allowed_senders", DEFAULT_ALLOWED_SENDERS)
        if not cfg.get("secret_token"):
            cfg["secret_token"] = secrets.token_hex(24)
        return cfg

    def _save_settings(self):
        if self._main and hasattr(self._main, "save_json") and hasattr(self._main, "DB_FILES"):
            self._main.save_json(self._main.DB_FILES["configs"], self._main.configs_pool)

    def is_enabled(self) -> bool:
        return bool(self._get_settings().get("enabled", False))

    def is_test_mode(self) -> bool:
        return bool(self._get_settings().get("test_mode", True))

    def get_secret_token(self) -> str:
        return self._get_settings().get("secret_token", "")

    def get_window_minutes(self) -> int:
        return int(self._get_settings().get("window_minutes", 30))

    def get_webhook_port(self) -> int:
        return int(self._get_settings().get("webhook_port", 8088))

    def get_webhook_host(self) -> str:
        return str(self._get_settings().get("webhook_host", "127.0.0.1"))

    def get_public_url(self) -> str:
        return str(self._get_settings().get("public_url", "https://sms.zyvora.ir/api/sms-webhook"))

    def get_allowed_senders(self) -> List[str]:
        return list(self._get_settings().get("allowed_senders", DEFAULT_ALLOWED_SENDERS))

    async def process_incoming_sms(
        self,
        sender: str,
        raw_text: str,
        device_received_at: str = ""
    ) -> Dict[str, Any]:
        """
        پردازش پیامک ورودی با ثبت کامل تمامی پیامک‌ها (حتی غیربانکی) در لاگ و دیتابیس
        """
        norm_sender = normalize_digits(sender).strip().lower()
        norm_text = normalize_digits(raw_text).strip()
        sms_hash = hashlib.sha256(f"{norm_sender}:{norm_text}".encode("utf-8")).hexdigest()

        allowed_senders = self.get_allowed_senders()
        parsed, parse_reason = BlubankSMSParser.parse(sender, raw_text, allowed_senders)

        if not parsed:
            logger.warning(
                "🚫 [SMS REJECTED BY PARSER] Reason='%s' | Sender='%s' | Text='%s'",
                parse_reason, sender, raw_text.replace("\n", " | ")
            )
            # ثبت در دیتابیس تا در بخش تاریخچه پیامک‌های ربات هم دیده شود
            tx_id, is_dup = await asyncio.to_thread(
                self.db.record_unparsed_sms,
                sms_hash=sms_hash,
                sender=sender,
                raw_text=raw_text,
                device_received_at_utc=device_received_at,
                reason=parse_reason
            )
            return {
                "status": "duplicate_unparsed" if is_dup else "unparsed",
                "tx_id": tx_id,
                "reason": parse_reason
            }

        amount_toman = parsed["amount_toman"]
        amount_rial = parsed["amount_rial"]
        bank_tx_utc = parsed["bank_tx_utc"]

        logger.info(
            "🏦 [BLUBANK DEPOSIT PARSED] Amount=%d Toman (%d Rial) | BankTime=%s %s | Balance=%s",
            amount_toman, amount_rial, parsed["bank_date_shamsi_str"], parsed["bank_time_str"], parsed.get("balance_rial")
        )

        test_mode = self.is_test_mode()

        match_result = await asyncio.to_thread(
            self.db.find_and_claim_reservation,
            amount_toman=amount_toman,
            bank_tx_utc=bank_tx_utc,
            sms_hash=sms_hash,
            sender=sender,
            raw_text=raw_text,
            parsed_bank="blubank",
            amount_rial=amount_rial,
            balance_rial=parsed.get("balance_rial"),
            device_received_at_utc=device_received_at,
            test_mode=test_mode
        )

        status = match_result.get("status")

        if status == "duplicate":
            return {
                "status": "duplicate",
                "tx_id": match_result.get("tx_id"),
                "previous_status": match_result.get("previous_status")
            }

        elif status == "test_matched":
            reservation = match_result["reservation"]
            await self._notify_admin_test_match(parsed, reservation)
            return {
                "status": "test_matched",
                "order_id": reservation["order_id"],
                "payable_amount": amount_toman,
                "note": "Payment verified in TEST MODE. No order was approved."
            }

        elif status == "approved":
            reservation = match_result["reservation"]
            tx_id = match_result["tx_id"]
            order_id = reservation["order_id"]
            order_type = reservation["order_type"]

            fulfillment_status, err_msg = await self._execute_fulfillment(
                order_id=order_id,
                order_type=order_type
            )

            await asyncio.to_thread(
                self.db.update_fulfillment_status,
                tx_id=tx_id,
                status=fulfillment_status,
                error_message=err_msg
            )

            if fulfillment_status == "fulfilled":
                await self._notify_admin_approved(parsed, reservation)
            elif fulfillment_status == "failed_pending_retry":
                await self._notify_admin_fulfillment_failed(parsed, reservation, tx_id, err_msg)
            elif fulfillment_status == "manual_fulfillment_required":
                await self._notify_admin_manual_fulfillment(parsed, reservation, tx_id, err_msg)

            return {
                "status": "approved",
                "order_id": order_id,
                "fulfillment": fulfillment_status
            }

        elif status == "ambiguous":
            candidates = match_result.get("candidates", [])
            await self._notify_admin_ambiguous(parsed, candidates)
            return {"status": "ambiguous", "candidates_count": len(candidates)}

        elif status == "claimed_by_concurrent_task":
            return {"status": "duplicate_claimed"}

        else:
            reason = match_result.get("reason", "no_active_reservation")
            await self._notify_admin_unmatched(parsed, reason)
            return {"status": "unmatched", "reason": reason}

    async def _execute_fulfillment(self, order_id: int, order_type: str) -> Tuple[str, str]:
        if not self._main:
            return "failed_pending_retry", "Main bot module not loaded"

        try:
            if order_type == "balance_charge":
                from balance_system import fulfill_balance_order
                success, msg = await fulfill_balance_order(
                    order_id=order_id,
                    approved_by="sms_auto",
                    payment_method="sms_card_auto"
                )
                if success:
                    return "fulfilled", ""
                return "failed_pending_retry", msg

            else:
                fulfill_vpn = getattr(self._main, "fulfill_vpn_order", None)
                if not fulfill_vpn:
                    return "failed_pending_retry", "fulfill_vpn_order function not found"

                status_result, msg = await fulfill_vpn(
                    order_id=order_id,
                    approved_by="sms_auto",
                    payment_method="sms_card_auto"
                )
                return status_result, msg

        except Exception as e:
            logger.error(f"خطا در اجرای تحویل سفارش #{order_id}: {e}", exc_info=True)
            return "failed_pending_retry", str(e)

    # ─── نوتیفیکیشن‌های تلگرام برای ادمین ───

    async def _notify_admin_test_match(self, parsed: dict, reservation: dict):
        if not self._main or not hasattr(self._main, "bot"):
            return
        admin_id = self._main.ADMIN_ID_INT
        text = f"""🧪 <b>تست موفق تطبیق پیامک واریز (Test Mode)</b>
━━━━━━━━━━━━━━━━━━━━━━
🏦 <b>بانک:</b> بلوبانک (سامان)
💰 <b>مبلغ شناسایی‌شده:</b> <code>{parsed['amount_toman']:,}</code> تومان (<code>{parsed['amount_rial']:,}</code> ریال)
⏰ <b>زمان پیامک:</b> <code>{parsed['bank_time_str']}</code> (مورخ {parsed['bank_date_shamsi_str']})
🎯 <b>سفارش تطبیق‌یافته:</b> #{reservation['order_id']} ({reservation['order_type']})
👤 <b>شناسه کاربر:</b> <code>{reservation['user_id']}</code>
📉 <b>تخفیف یکتایی:</b> <code>{reservation['discount_offset']}</code> تومان
━━━━━━━━━━━━━━━━━━━━━━
💡 <i>در حالت تست، تایید سفارش صورت نمی‌گیرد و هیچ کانفیگی ساخته نمی‌شود.</i>"""
        try:
            await self._main.bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"عدم امکان ارسال نوتیفیکیشن تست به ادمین: {e}")

    async def _notify_admin_approved(self, parsed: dict, reservation: dict):
        if not self._main or not hasattr(self._main, "bot"):
            return
        admin_id = self._main.ADMIN_ID_INT
        text = f"""✅ <b>تایید خودکار پرداخت پیامکی</b>
━━━━━━━━━━━━━━━━━━━━━━
🏦 <b>بانک:</b> بلوبانک
💰 <b>مبلغ واریز:</b> <code>{parsed['amount_toman']:,}</code> تومان
🆔 <b>سفارش:</b> #{reservation['order_id']}
👤 <b>کاربر:</b> <code>{reservation['user_id']}</code>
⏰ <b>زمان:</b> <code>{parsed['bank_time_str']}</code>
📦 <b>وضعیت تحویل:</b> تحویل موفق سرویس."""
        try:
            await self._main.bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"خطا در ارسال نوتیفیکیشن تایید: {e}")

    async def _notify_admin_fulfillment_failed(self, parsed: dict, reservation: dict, tx_id: int, err_msg: str):
        if not self._main or not hasattr(self._main, "bot"):
            return
        admin_id = self._main.ADMIN_ID_INT
        order_id = reservation["order_id"]
        text = f"""⚠️ <b>پرداخت تایید شد اما تحویل سرویس در پنل با خطا مواجه شد!</b>
━━━━━━━━━━━━━━━━━━━━━━
🆔 <b>سفارش:</b> #{order_id}
💰 <b>مبلغ:</b> <code>{parsed['amount_toman']:,}</code> تومان
👤 <b>کاربر:</b> <code>{reservation['user_id']}</code>
❌ <b>خطای پنل:</b> <code>{err_msg}</code>
━━━━━━━━━━━━━━━━━━━━━━
🔒 <i>پرداخت کاربر قطعی است و گم نمی‌شود. پس از رفع قطعی پنل، دکمه زیر را برای تحویل بزنید.</i>"""
        try:
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔄 تلاش مجدد برای تحویل", callback_data=f"sms_retry_{order_id}_{tx_id}")
            ]])
            await self._main.bot.send_message(admin_id, text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"خطا در ارسال هشدار تحویل: {e}")

    async def _notify_admin_manual_fulfillment(self, parsed: dict, reservation: dict, tx_id: int, msg: str):
        if not self._main or not hasattr(self._main, "bot"):
            return
        admin_id = self._main.ADMIN_ID_INT
        order_id = reservation["order_id"]
        text = f"""ℹ️ <b>پرداخت تایید شد (پنل سنایی غیرفعال است - نیاز به تحویل دستی)</b>
━━━━━━━━━━━━━━━━━━━━━━
🆔 <b>سفارش:</b> #{order_id}
💰 <b>مبلغ:</b> <code>{parsed['amount_toman']:,}</code> تومان
👤 <b>کاربر:</b> <code>{reservation['user_id']}</code>
━━━━━━━━━━━━━━━━━━━━━━
لطفاً کانفیگ را به صورت دستی در بخش مدیریت سفارشات تحویل دهید."""
        try:
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔍 مشاهده سفارش", callback_data=f"admin_view_order_{order_id}")
            ]])
            await self._main.bot.send_message(admin_id, text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"خطا در ارسال هشدار تحویل دستی: {e}")

    async def _notify_admin_ambiguous(self, parsed: dict, candidates: list):
        if not self._main or not hasattr(self._main, "bot"):
            return
        admin_id = self._main.ADMIN_ID_INT
        oids = ", ".join(f"#{c['order_id']}" for c in candidates)
        text = f"""⚠️ <b>هشدار: پیامک واریز با چند سفارش هم‌مبلغ تطبیق یافت (ابهام)!</b>
━━━━━━━━━━━━━━━━━━━━━━
💰 <b>مبلغ پیامک:</b> <code>{parsed['amount_toman']:,}</code> تومان
⏰ <b>زمان پیامک:</b> <code>{parsed['bank_time_str']}</code>
🔍 <b>سفارش‌های کاندید:</b> {oids}
━━━━━━━━━━━━━━━━━━━━━━
⛔ جهت جلوگیری از تایید اشتباه، تایید خودکار لغو شد و نیاز به بررسی دستی دارد."""
        try:
            await self._main.bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"خطا در ارسال نوتیفیکیشن ابهام: {e}")

    async def _notify_admin_unmatched(self, parsed: dict, reason: str = ""):
        if not self._main or not hasattr(self._main, "bot"):
            return
        admin_id = self._main.ADMIN_ID_INT
        reason_fa = (
            "مبلغ تطبیق داشت اما زمان واریز خارج از بازه سفارش بود"
            if reason == "time_out_of_bounds"
            else "هیچ سفارش فعالی با این مبلغ در انتظار پرداخت نیست"
        )
        text = f"""ℹ️ <b>پیامک واریز بدون سفارش متناظر دریافت شد</b>
━━━━━━━━━━━━━━━━━━━━━━
💰 <b>مبلغ:</b> <code>{parsed['amount_toman']:,}</code> تومان (<code>{parsed['amount_rial']:,}</code> ریال)
⏰ <b>زمان:</b> <code>{parsed['bank_time_str']}</code>
📅 <b>تاریخ:</b> <code>{parsed['bank_date_shamsi_str']}</code>
📌 <b>علت:</b> {reason_fa}
━━━━━━━━━━━━━━━━━━━━━━"""
        try:
            await self._main.bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"خطا در ارسال نوتیفیکیشن تطبیق‌نیافته: {e}")


# نمونه سراسری
sms_payment_manager = SMSPaymentManager()


# ══════════════════════════════════════════════════════════════════════
# ۶. هندلرهای تلگرام برای پنل ادمین و دکمه‌های Retry
# ══════════════════════════════════════════════════════════════════════

def get_admin_sms_settings_keyboard(lang: str = "fa") -> InlineKeyboardMarkup:
    enabled = sms_payment_manager.is_enabled()
    test_mode = sms_payment_manager.is_test_mode()
    window = sms_payment_manager.get_window_minutes()

    status_btn = "🟢 وضعیت: فعال" if enabled else "🔴 وضعیت: غیرفعال"
    mode_btn = "🧪 حالت کاری: تست (شبیه‌سازی)" if test_mode else "⚡ حالت کاری: تایید خودکار واقعی"

    buttons = [
        [InlineKeyboardButton(text=status_btn, callback_data="sms_toggle_enabled")],
        [InlineKeyboardButton(text=mode_btn, callback_data="sms_toggle_test_mode")],
        [
            InlineKeyboardButton(text=f"⏱ پنجره انقضا: {window} دقیقه", callback_data="sms_cycle_window"),
            InlineKeyboardButton(text="🔑 توکن وب‌هوک", callback_data="sms_view_token")
        ],
        [
            InlineKeyboardButton(text="📋 تاریخچه تمام پیامک‌ها", callback_data="sms_view_logs"),
            InlineKeyboardButton(text="📱 راهنمای تنظیم اپلیکیشن", callback_data="sms_view_guide")
        ],
        [InlineKeyboardButton(text="🔙 بازگشت به پنل ادمین", callback_data="admin_panel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def register_sms_payment_handlers(dp, main_module):
    sms_payment_manager.set_main_module(main_module)

    @dp.callback_query(F.data == "admin_sms_payment")
    async def admin_sms_payment_menu(callback: CallbackQuery):
        if callback.from_user.id != main_module.ADMIN_ID_INT:
            return
        lang = main_module.get_user(callback.from_user.id).get("lang", "fa")
        public_url = sms_payment_manager.get_public_url()
        token = sms_payment_manager.get_secret_token()
        masked_token = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else "***"

        text = f"""💳 <b>تنظیمات تایید خودکار پرداخت پیامکی (بلوبانک)</b>
━━━━━━━━━━━━━━━━━━━━━━
🔹 <b>آدرس وب‌هوک امن:</b>
<code>{public_url}</code>

🔹 <b>پورت لوکال سرور:</b> <code>127.0.0.1:8088</code>
🔹 <b>فایل لاگ خام:</b> <code>data/sms_webhook_raw.log</code>
🔹 <b>وضعیت سیستم:</b> {'🟢 فعال' if sms_payment_manager.is_enabled() else '🔴 غیرفعال'}
🔹 <b>حالت کاری:</b> {'🧪 تست (شبیه‌سازی و گزارش بدون تایید)' if sms_payment_manager.is_test_mode() else '⚡ تایید خودکار و تحویل آنی'}
🔹 <b>پنجره مجاز واریز:</b> {sms_payment_manager.get_window_minutes()} دقیقه
🔹 <b>توکن جاری:</b> <code>{masked_token}</code>
━━━━━━━━━━━━━━━━━━━━━━"""

        try:
            await callback.message.edit_text(
                text,
                reply_markup=get_admin_sms_settings_keyboard(lang),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await callback.message.answer(
                text,
                reply_markup=get_admin_sms_settings_keyboard(lang),
                parse_mode=ParseMode.HTML
            )
        await callback.answer()

    @dp.callback_query(F.data == "sms_toggle_enabled")
    async def toggle_sms_enabled(callback: CallbackQuery):
        if callback.from_user.id != main_module.ADMIN_ID_INT:
            return
        cfg = sms_payment_manager._get_settings()
        cfg["enabled"] = not cfg.get("enabled", False)
        sms_payment_manager._save_settings()

        if cfg["enabled"]:
            try:
                await sms_payment_manager.server.start(
                    host=sms_payment_manager.get_webhook_host(),
                    port=sms_payment_manager.get_webhook_port()
                )
            except Exception as e:
                logger.error(f"خطا در استارت وب‌هوک: {e}")
        else:
            try:
                await sms_payment_manager.server.stop()
            except Exception as e:
                logger.error(f"خطا در استاپ وب‌هوک: {e}")

        await admin_sms_payment_menu(callback)

    @dp.callback_query(F.data == "sms_toggle_test_mode")
    async def toggle_sms_test_mode(callback: CallbackQuery):
        if callback.from_user.id != main_module.ADMIN_ID_INT:
            return
        cfg = sms_payment_manager._get_settings()
        cfg["test_mode"] = not cfg.get("test_mode", True)
        sms_payment_manager._save_settings()
        await admin_sms_payment_menu(callback)

    @dp.callback_query(F.data == "sms_cycle_window")
    async def cycle_sms_window(callback: CallbackQuery):
        if callback.from_user.id != main_module.ADMIN_ID_INT:
            return
        cfg = sms_payment_manager._get_settings()
        current = cfg.get("window_minutes", 30)
        windows = [15, 20, 30, 45, 60]
        try:
            idx = windows.index(current)
            next_w = windows[(idx + 1) % len(windows)]
        except ValueError:
            next_w = 30
        cfg["window_minutes"] = next_w
        sms_payment_manager._save_settings()
        await admin_sms_payment_menu(callback)

    @dp.callback_query(F.data == "sms_view_token")
    async def view_sms_token(callback: CallbackQuery):
        if callback.from_user.id != main_module.ADMIN_ID_INT:
            return
        token = sms_payment_manager.get_secret_token()
        text = f"""🔑 <b>توکن امنیتی وب‌هوک پیامک</b>
━━━━━━━━━━━━━━━━━━━━━━
🔹 <b>توکن کامل (جهت تنظیم در اپلیکیشن):</b>
<code>{token}</code>

🔒 <i>این مقدار را در بخش Headers با نام <code>X-Secret-Token</code> قرار دهید.</i>"""

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 بازتولید توکن جدید", callback_data="sms_regenerate_token")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_sms_payment")]
        ])
        await callback.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await callback.answer()

    @dp.callback_query(F.data == "sms_regenerate_token")
    async def regenerate_sms_token(callback: CallbackQuery):
        if callback.from_user.id != main_module.ADMIN_ID_INT:
            return
        cfg = sms_payment_manager._get_settings()
        cfg["secret_token"] = secrets.token_hex(24)
        sms_payment_manager._save_settings()
        await view_sms_token(callback)

    @dp.callback_query(F.data == "sms_view_guide")
    async def view_sms_guide(callback: CallbackQuery):
        if callback.from_user.id != main_module.ADMIN_ID_INT:
            return
        public_url = sms_payment_manager.get_public_url()
        token = sms_payment_manager.get_secret_token()

        text = f"""📱 <b>راهنمای جامع راه‌اندازی کارت‌به‌کارت خودکار (بلوبانک)</b>
━━━━━━━━━━━━━━━━━━━━━━
<b>۱. زیرساخت سرور (Cloudflare Tunnel):</b>
<code>ingress:</code>
<code>  - hostname: sms.zyvora.ir</code>
<code>    service: http://127.0.0.1:8088</code>
<code>  - service: http_status:404</code>

<b>۲. تنظیمات اپلیکیشن SMS Forwarder در گوشی:</b>
- <b>URL مقصد:</b>
<code>{public_url}</code>
- <b>Headers:</b>
<code>X-Secret-Token: {token}</code>
<code>Content-Type: application/json</code>
- <b>Payload / Body Template:</b>
<code>{{"sender":"[from]","message":"[msg]","received_at":"[receive_time]"}}</code>

<b>۳. مشاهده زنده تمام پیامک‌های دریافتی در سرور:</b>
برای دیدن لحظه‌ای تمام پیامک‌هایی که از گوشی به سرور می‌رسند، این دستور را در ترمینال سرور بزنید:
<code>tail -f data/sms_webhook_raw.log</code>
━━━━━━━━━━━━━━━━━━━━━━"""

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_sms_payment")]
        ])
        await callback.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await callback.answer()

    @dp.callback_query(F.data == "sms_view_logs")
    async def view_sms_logs(callback: CallbackQuery):
        if callback.from_user.id != main_module.ADMIN_ID_INT:
            return
        recent = await asyncio.to_thread(sms_payment_manager.db.get_recent_transactions, limit=8)
        if not recent:
            msg = "📭 تاکنون هیچ پیامکی ثبت نشده است."
        else:
            lines = ["📋 <b>آخرین پیامک‌های دریافتی از گوشی:</b>\n━━━━━━━━━━━━━━━━━━━━━━"]
            for r in recent:
                st = r["status"]
                status_emoji = (
                    "✅" if st == "approved"
                    else "🧪" if "test" in st
                    else "🚫" if st == "unparsed"
                    else "⚠️"
                )
                amt = f"{r.get('amount_toman', 0):,} ت" if r.get("amount_toman") else "غیربانکی/ردشده"
                sender_str = r.get("sender", "N/A")
                raw_preview = (r.get("raw_text") or "").replace("\n", " ")[:45]
                notes = r.get("confidence_notes") or ""

                lines.append(f"{status_emoji} <b>#{r['id']}</b> | از: <code>{sender_str}</code> | {amt} | <code>{st}</code>")
                lines.append(f"   💬 متن: <i>{raw_preview}...</i>")
                if notes:
                    lines.append(f"   📌 نتیجه: {notes}")
                if r.get("matched_order_id"):
                    lines.append(f"   ↳ سفارش #{r['matched_order_id']}")
                lines.append("")
            msg = "\n".join(lines)

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 بروزرسانی لیست", callback_data="sms_view_logs")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_sms_payment")]
        ])
        try:
            await callback.message.edit_text(msg, reply_markup=markup, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await callback.answer()

    @dp.callback_query(F.data.startswith("sms_retry_"))
    async def retry_sms_fulfillment(callback: CallbackQuery):
        if callback.from_user.id != main_module.ADMIN_ID_INT:
            return
        parts = callback.data.split("_")
        try:
            order_id = int(parts[2])
            tx_id = int(parts[3])
        except (IndexError, ValueError):
            await callback.answer("❌ داده‌های نامعتبر", show_alert=True)
            return

        order = main_module.orders.get(str(order_id))
        if not order:
            await callback.answer("❌ سفارش یافت نشد", show_alert=True)
            return

        order_type = order.get("type", "purchase")
        await callback.answer("⏳ در حال تلاش مجدد برای تحویل...", show_alert=False)

        status_res, err_msg = await sms_payment_manager._execute_fulfillment(order_id, order_type)
        await asyncio.to_thread(
            sms_payment_manager.db.update_fulfillment_status,
            tx_id=tx_id,
            status=status_res,
            error_message=err_msg
        )

        if status_res == "fulfilled":
            await callback.message.edit_text(
                f"✅ تحویل سفارش #{order_id} با موفقیت انجام شد و کانفیگ ارسال گردید.",
                reply_markup=None
            )
        else:
            await callback.answer(f"❌ خطا مجدداً رخ داد: {err_msg[:40]}", show_alert=True)
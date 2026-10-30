"""
====================================================================
VeloraBot - Daily Internet Usage Statistics & Chart Module
====================================================================
Features:
- Transactional, ACID-compliant SQLite storage for traffic snapshots & daily aggregations.
- Service-level granularity (per unique client/email/uuid, supporting multi-config orders).
- Strict midnight-crossing handling with time-weighted allocation across calendar days.
- Sanaei counter reset detection: avoids negative usage, records reset events, resets baseline.
- On-demand live snapshot recording with duplicate/spam debouncing.
- Sanity check & auto-healing: validates recorded traffic against panel reality, preventing inflated stats.
- Accurate Solar Hijri (Shamsi / Jalali) date conversion for Persian language.
- True Right-to-Left (RTL) chart layout for Persian (reversed X-axis, right-positioned Y-axis).
- Intelligent auto-detection of MB and GB units in charts and captions.
- Full backup and restore support (both in JSON backup archive and SQLite database copy).
- Modern dark-themed dashboard chart generator (Matplotlib, Vazirmatn font, isolated Figure, non-blocking).
- Scheduled background collector using panel inbounds clientStats.
- Transparent notification when history is limited (showing Shamsi start date).
"""

import os
import io
import re
import json
import time
import math
import shutil
import logging
import sqlite3
import asyncio
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any

# Data visualization & RTL shaping
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import matplotlib.font_manager as fm
import matplotlib.ft2font as ft2font
import arabic_reshaper
from bidi.algorithm import get_display

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, CallbackQuery
from aiogram.enums import ParseMode

from config import DATA_DIR

logger = logging.getLogger("daily_usage")

# Local Tehran Timezone (UTC +03:30)
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

DB_PATH = os.path.join(DATA_DIR, "daily_usage.db")

# مسیر فونت‌های فارسی اختصاصی وزیرمتن
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
REGULAR_FONT_PATH = os.path.join(FONTS_DIR, "Vazirmatn-Regular.ttf")
BOLD_FONT_PATH = os.path.join(FONTS_DIR, "Vazirmatn-Bold.ttf")

# بررسی وجود موتور چیدمان متن پیشرفته libraqm (HarfBuzz & FriBidi) در Matplotlib
HAS_RAQM = getattr(ft2font, '__libraqm_version__', None) is not None and hasattr(ft2font.FT2Font, '_layout')


def get_font_properties(is_bold: bool = False, size: float = 11.0) -> fm.FontProperties:
    """
    دریافت مشخصات فونت اختصاصی وزیرمتن با بررسی دقیق وجود فایل فونت.
    در صورت عدم وجود فونت، خطای واضح FileNotFoundError ایجاد می‌کند تا از رندر خراب جلوگیری شود.
    """
    font_path = BOLD_FONT_PATH if is_bold else REGULAR_FONT_PATH
    if not os.path.exists(font_path):
        raise FileNotFoundError(
            f"فایل فونت فارسی مورد نیاز یافت نشد: {font_path}\n"
            f"لطفاً مطمئن شوید فونت‌های Vazirmatn-Regular.ttf و Vazirmatn-Bold.ttf در مسیر {FONTS_DIR} قرار دارند."
        )
    prop = fm.FontProperties(fname=font_path)
    prop.set_size(size)
    return prop


PERSIAN_WEEKDAYS = {
    0: "دوشنبه",
    1: "سه‌شنبه",
    2: "چهارشنبه",
    3: "پنج‌شنبه",
    4: "جمعه",
    5: "شنبه",
    6: "یک‌شنبه"
}

ENGLISH_WEEKDAYS = {
    0: "Mon",
    1: "Tue",
    2: "Wed",
    3: "Thu",
    4: "Fri",
    5: "Sat",
    6: "Sun"
}


# ====================================================================
# Date & Text Utilities (Shamsi / Jalali, Persian Digits, Auto Units)
# ====================================================================

def to_persian_digits(text: Any) -> str:
    """تبدیل اعداد انگلیسی به فارسی"""
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    result = []
    for char in str(text):
        if '0' <= char <= '9':
            result.append(persian_digits[ord(char) - ord('0')])
        else:
            result.append(char)
    return "".join(result)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    """تبدیل تقویم میلادی به هجری شمسی (جلالی) دقیق بدون وابستگی خارجی"""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy if gm > 2 else gy - 1
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
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


def format_date_persian(date_str: str) -> str:
    """تبدیل رشته تاریخ میلادی YYYY-MM-DD به تاریخ شمسی YYYY/MM/DD با اعداد فارسی"""
    if not date_str:
        return ""
    try:
        parts = [int(p) for p in str(date_str).split("-")]
        if len(parts) == 3:
            jy, jm, jd = gregorian_to_jalali(parts[0], parts[1], parts[2])
            shamsi_str = f"{jy:04d}/{jm:02d}/{jd:02d}"
            return to_persian_digits(shamsi_str)
    except Exception:
        pass
    return to_persian_digits(date_str)


def format_short_date(date_str: str, lang: str = "fa") -> str:
    """تبدیل تاریخ به فرمت کوتاه MM/DD (شمسی برای فارسی، میلادی برای انگلیسی)"""
    if not date_str:
        return ""
    try:
        parts = [int(p) for p in str(date_str).split("-")]
        if len(parts) == 3:
            if lang == "fa":
                _, jm, jd = gregorian_to_jalali(parts[0], parts[1], parts[2])
                return to_persian_digits(f"{jm:02d}/{jd:02d}")
            else:
                return f"{parts[1]:02d}/{parts[2]:02d}"
    except Exception:
        pass
    return to_persian_digits(date_str) if lang == "fa" else date_str


def format_traffic_auto(bytes_val: int, lang: str = "fa") -> str:
    """
    تشخیص و فرمت هوشمند حجم بر اساس مگابایت یا گیگابایت:
    - کمتر از 1 گیگابایت: مگابایت (MB)
    - 1 گیگابایت و بالاتر: گیگابایت (GB)
    """
    bytes_val = max(0, int(bytes_val or 0))
    gb_val = bytes_val / (1024 ** 3)
    mb_val = bytes_val / (1024 ** 2)

    if lang == "fa":
        if gb_val >= 1.0:
            return f"{to_persian_digits(f'{gb_val:.2f}')} گیگابایت"
        elif mb_val >= 1.0:
            return f"{to_persian_digits(f'{mb_val:.1f}')} مگابایت"
        elif bytes_val > 0:
            return f"{to_persian_digits(f'{mb_val:.2f}')} مگابایت"
        else:
            return "۰ مگابایت"
    else:
        if gb_val >= 1.0:
            return f"{gb_val:.2f} GB"
        elif mb_val >= 1.0:
            return f"{mb_val:.1f} MB"
        elif bytes_val > 0:
            return f"{mb_val:.2f} MB"
        else:
            return "0 MB"


_reshaper_instance = None

def _get_reshaper():
    global _reshaper_instance
    if _reshaper_instance is None:
        _reshaper_instance = arabic_reshaper.ArabicReshaper(configuration={
            'delete_harakat': True,
            'support_ligatures': True,
            'language': 'Persian',
        })
    return _reshaper_instance

PERSIAN_CHARS_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')

def is_persian(text: Any) -> bool:
    """بررسی وجود حروف فارسی یا عربی در متن"""
    return bool(PERSIAN_CHARS_RE.search(str(text or "")))


def format_persian_text(text: str) -> str:
    """
    شکل‌دهی متمرکز متون فارسی، انگلیسی و اعداد برای رندر بی‌نقص در Matplotlib.
    
    1. در صورت وجود موتور libraqm در Matplotlib (پشتیبانی استاندارد از HarfBuzz و FriBidi):
       متون با کاراکترهای استاندارد یونیکد باقی می‌مانند تا اتصالات OpenType فونت وزیرمتن
       به صورت طبیعی انجام شوند و متون ترکیبی با نشانگرهای جهت‌دار Bidi تنظیم شوند.
       
    2. در صورت نبود libraqm (محیط‌های فاقد HarfBuzz):
       از arabic_reshaper و python-bidi برای شکل‌دهی اشکال متصل و برعکس‌سازی LTR استفاده می‌شود.
    """
    if text is None:
        return ""
    text = str(text)
    if not text.strip():
        return text

    if HAS_RAQM:
        # مدیریت متون دوزبانه تفکیک‌شده با Pipe (مانند Upload: 2.5 GB | دانلود: 5 GB)
        if is_persian(text) and ' | ' in text:
            parts = text.split(' | ')
            processed = [f"\u202b{p}\u202c" if is_persian(p) else p for p in parts]
            return ' | '.join(processed)
        return text
    else:
        try:
            reshaped = _get_reshaper().reshape(text)
            return get_display(reshaped)
        except Exception:
            logger.exception("Persian text fallback formatting failed")
            return text


# ====================================================================
# 1. SQLite Storage Engine (ACID, Transactional, WAL Mode)
# ====================================================================

class DailyUsageStore:
    """
    موتور ذخیره‌سازی داده‌های مصرف و اسنپ‌شات‌ها در SQLite
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = asyncio.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        """ایجاد جداول و ایندکس‌ها در دیتابیس"""
        dirname = os.path.dirname(self.db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # جدول سرویس‌ها
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS services (
                    service_id TEXT PRIMARY KEY,
                    order_id TEXT,
                    user_id INTEGER,
                    email TEXT,
                    title TEXT,
                    created_at REAL,
                    updated_at REAL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_services_order ON services(order_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_services_user ON services(user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_services_email ON services(email);")

            # جدول اسنپ‌شات‌های ترافیک تجمعی
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS traffic_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    recorded_at TEXT NOT NULL,
                    up_bytes INTEGER NOT NULL,
                    down_bytes INTEGER NOT NULL,
                    total_bytes INTEGER NOT NULL,
                    is_reset INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(service_id) REFERENCES services(service_id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_service_time ON traffic_snapshots(service_id, timestamp);")

            # جدول مصرف تفکیک‌شده روزانه
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id TEXT NOT NULL,
                    usage_date TEXT NOT NULL, -- 'YYYY-MM-DD'
                    up_bytes INTEGER NOT NULL DEFAULT 0,
                    down_bytes INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    UNIQUE(service_id, usage_date),
                    FOREIGN KEY(service_id) REFERENCES services(service_id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_service_date ON daily_usage(service_id, usage_date);")

            # جدول ثبت رویدادهای ریست شدن شمارنده‌های پنل
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reset_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    previous_up INTEGER NOT NULL,
                    previous_down INTEGER NOT NULL,
                    previous_total INTEGER NOT NULL,
                    new_up INTEGER NOT NULL,
                    new_down INTEGER NOT NULL,
                    new_total INTEGER NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_resets_service ON reset_events(service_id);")

            conn.commit()
            logger.info("✅ دیتابیس مصرف روزانه SQLite با موفقیت آماده‌سازی شد: %s", self.db_path)

    def register_service(
        self,
        service_id: str,
        order_id: Optional[str] = None,
        user_id: Optional[int] = None,
        email: Optional[str] = None,
        title: Optional[str] = None
    ):
        """ثبت یا به‌روزرسانی مشخصات یک سرویس"""
        if not service_id:
            return
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO services (service_id, order_id, user_id, email, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_id) DO UPDATE SET
                    order_id = COALESCE(excluded.order_id, services.order_id),
                    user_id = COALESCE(excluded.user_id, services.user_id),
                    email = COALESCE(excluded.email, services.email),
                    title = COALESCE(excluded.title, services.title),
                    updated_at = excluded.updated_at;
            """, (str(service_id), str(order_id) if order_id else None, user_id, email, title, now, now))
            conn.commit()

    def get_latest_snapshot(self, service_id: str) -> Optional[dict]:
        """دریافت آخرین اسنپ‌شات ثبت‌شده برای یک سرویس"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, up_bytes, down_bytes, total_bytes, is_reset
                FROM traffic_snapshots
                WHERE service_id = ?
                ORDER BY timestamp DESC LIMIT 1;
            """, (str(service_id),))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def record_snapshot(
        self,
        service_id: str,
        up_bytes: int,
        down_bytes: int,
        timestamp: Optional[float] = None,
        min_interval: float = 30.0
    ) -> bool:
        """
        ثبت اسنپ‌شات جدید ترافیک به صورت تراکنشی و همگام‌سازی مصرف روزانه
        """
        if not service_id:
            return False

        up_bytes = max(0, int(up_bytes or 0))
        down_bytes = max(0, int(down_bytes or 0))
        total_bytes = up_bytes + down_bytes

        now = timestamp if timestamp is not None else time.time()
        now_dt = datetime.fromtimestamp(now, TEHRAN_TZ)
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # بررسی وجود سرویس، در صورت عدم وجود ثبت اولیه
            cursor.execute("SELECT service_id FROM services WHERE service_id = ?;", (str(service_id),))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO services (service_id, email, created_at, updated_at)
                    VALUES (?, ?, ?, ?);
                """, (str(service_id), str(service_id), now, now))

            # بررسی آخرین اسنپ‌شات
            cursor.execute("""
                SELECT timestamp, up_bytes, down_bytes, total_bytes
                FROM traffic_snapshots
                WHERE service_id = ?
                ORDER BY timestamp DESC LIMIT 1;
            """, (str(service_id),))
            last = cursor.fetchone()

            is_reset = 0
            delta_up = 0
            delta_down = 0
            delta_total = 0

            if last:
                last_time = last["timestamp"]
                last_up = last["up_bytes"]
                last_down = last["down_bytes"]
                last_total = last["total_bytes"]

                # شرط 5: جلوگیری از اسنپ‌شات تکراری
                if last_up == up_bytes and last_down == down_bytes:
                    return False

                if (now - last_time) < min_interval:
                    return False

                # شرط 4: بررسی ریست شدن شمارنده‌ها (Counter Reset)
                # در صورت ریست واقعی پنل، ترافیک کل (total_bytes) کاهش می‌یابد.
                if total_bytes < last_total:
                    is_reset = 1
                    cursor.execute("""
                        INSERT INTO reset_events (
                            service_id, timestamp, previous_up, previous_down, previous_total,
                            new_up, new_down, new_total, notes, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        str(service_id), now, last_up, last_down, last_total,
                        up_bytes, down_bytes, total_bytes, "Counter reset detected in Sanaei panel", now_str
                    ))
                    logger.warning(
                        "⚠️ ریست شمارنده برای %s ثبت شد: قبلی=%d, جدید=%d",
                        service_id, last_total, total_bytes
                    )
                    # در صورت ریست، مصرف جدید معادل همان مقدار جدید کنتور است (نه تفریق منفی!)
                    delta_up = up_bytes
                    delta_down = down_bytes
                    delta_total = total_bytes
                else:
                    delta_total = total_bytes - last_total
                    delta_up = max(0, up_bytes - last_up)
                    delta_down = max(0, down_bytes - last_down)
                    if delta_total > 0 and (delta_up + delta_down) == 0:
                        delta_down = delta_total
            else:
                # اولین اسنپ‌شات برای این سرویس:
                # به عنوان نقطه صفر ثبت می‌شود تا مبنای محاسبات بعدی باشد، اما کل حجم تجمعی گذشته مصرف امروز تلقی نمی‌شود.
                delta_up = 0
                delta_down = 0
                delta_total = 0

            # ثبت اسنپ‌شات جدید
            cursor.execute("""
                INSERT INTO traffic_snapshots (
                    service_id, timestamp, recorded_at, up_bytes, down_bytes, total_bytes, is_reset
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (str(service_id), now, now_str, up_bytes, down_bytes, total_bytes, is_reset))

            # شرط 3: تخصیص مصرف روزانه با مدیریت عبور از نیمه‌شب
            if delta_total > 0 and last:
                last_time = last["timestamp"]
                last_dt = datetime.fromtimestamp(last_time, TEHRAN_TZ)
                
                # توزیع دلتا بین روزهای تقویمی
                day_slices = self._split_interval_across_days(last_dt, now_dt)
                total_duration = max(1.0, (now_dt - last_dt).total_seconds())

                for target_date, slice_seconds in day_slices:
                    fraction = min(1.0, max(0.0, slice_seconds / total_duration))
                    slice_up = int(round(delta_up * fraction))
                    slice_down = int(round(delta_down * fraction))
                    slice_tot = int(round(delta_total * fraction))

                    if slice_tot <= 0 and slice_up <= 0 and slice_down <= 0:
                        continue

                    cursor.execute("""
                        INSERT INTO daily_usage (service_id, usage_date, up_bytes, down_bytes, total_bytes, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(service_id, usage_date) DO UPDATE SET
                            up_bytes = daily_usage.up_bytes + excluded.up_bytes,
                            down_bytes = daily_usage.down_bytes + excluded.down_bytes,
                            total_bytes = daily_usage.total_bytes + excluded.total_bytes,
                            updated_at = excluded.updated_at;
                    """, (str(service_id), target_date, slice_up, slice_down, slice_tot, now))

            conn.commit()
            return True

    def sanitize_service_usage(self, service_id: str, panel_total_bytes: int):
        """
        راستی‌آزمایی و اعتبارسنجی مصرف ثبت‌شده در برابر کل مصرف واقعی کلاینت در پنل:
        اگر مجموع ترافیک ثبت‌شده برای این سرویس در دیتابیس بیشتر از کل مصرف مادام‌العمر در پنل باشد،
        نشان‌دهنده ناهنجاری قبلی (False Resets) است و داده‌های معیوب گذشته بلافاصله اصلاح و همگام می‌شوند.
        """
        if not service_id or panel_total_bytes <= 0:
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT SUM(total_bytes) as db_total
                FROM daily_usage
                WHERE service_id = ?;
            """, (str(service_id),))
            row = cursor.fetchone()
            db_total = row["db_total"] or 0

            if db_total > panel_total_bytes:
                logger.warning(
                    "⚠️ ناهنجاری مصرف در سرویس %s شناسایی شد (دیتابیس=%d، پنل واقعی=%d). در حال اصلاح و راستی‌آزمایی...",
                    service_id, db_total, panel_total_bytes
                )
                ratio = panel_total_bytes / db_total
                cursor.execute("""
                    UPDATE daily_usage
                    SET up_bytes = CAST(ROUND(up_bytes * ?) AS INTEGER),
                        down_bytes = CAST(ROUND(down_bytes * ?) AS INTEGER),
                        total_bytes = CAST(ROUND(total_bytes * ?) AS INTEGER)
                    WHERE service_id = ?;
                """, (ratio, ratio, ratio, str(service_id)))

                cursor.execute("""
                    UPDATE traffic_snapshots
                    SET up_bytes = CAST(ROUND(up_bytes * ?) AS INTEGER),
                        down_bytes = CAST(ROUND(down_bytes * ?) AS INTEGER),
                        total_bytes = CAST(ROUND(total_bytes * ?) AS INTEGER)
                    WHERE service_id = ?;
                """, (ratio, ratio, ratio, str(service_id)))

                conn.commit()
                logger.info("✅ مصرف سرویس %s با موفقیت راستی‌آزمایی و با پنل همگام شد.", service_id)
            else:
                cursor.execute("""
                    UPDATE traffic_snapshots
                    SET up_bytes = MIN(up_bytes, ?),
                        down_bytes = MIN(down_bytes, ?),
                        total_bytes = MIN(total_bytes, ?)
                    WHERE service_id = ? AND total_bytes > ?;
                """, (panel_total_bytes, panel_total_bytes, panel_total_bytes, str(service_id), panel_total_bytes))
                conn.commit()

    @staticmethod
    def _split_interval_across_days(start_dt: datetime, end_dt: datetime) -> List[Tuple[str, float]]:
        """
        تقسیم یک بازه زمانی بین روزهای تقویمی بر اساس نیمه‌شب محلی
        خروجی: لیستی از (تاریخ 'YYYY-MM-DD', ثانیه‌های سپری‌شده در آن روز)
        """
        if end_dt <= start_dt:
            return [(end_dt.strftime("%Y-%m-%d"), 1.0)]

        start_date = start_dt.date()
        end_date = end_dt.date()

        if start_date == end_date:
            duration = (end_dt - start_dt).total_seconds()
            return [(start_date.strftime("%Y-%m-%d"), max(1.0, duration))]

        slices: List[Tuple[str, float]] = []
        curr_dt = start_dt

        while curr_dt < end_dt:
            curr_date = curr_dt.date()
            next_midnight = datetime(
                curr_date.year, curr_date.month, curr_date.day,
                0, 0, 0, tzinfo=TEHRAN_TZ
            ) + timedelta(days=1)

            slice_end = min(end_dt, next_midnight)
            slice_duration = (slice_end - curr_dt).total_seconds()
            if slice_duration > 0:
                slices.append((curr_date.strftime("%Y-%m-%d"), slice_duration))

            curr_dt = slice_end

        return slices

    def get_services_by_order(self, order_id: str) -> List[str]:
        """یافتن تمام شناسه‌های سرویس مرتبط با یک سفارش"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT service_id FROM services WHERE order_id = ?;
            """, (str(order_id),))
            rows = cursor.fetchall()
            return [r["service_id"] for r in rows]

    def get_service_history_info(self, service_ids: List[str]) -> Tuple[Optional[str], int]:
        """
        دریافت اولین تاریخ ثبت‌شده و تعداد کل روزهای دارای سابقه
        """
        if not service_ids:
            return None, 0

        placeholders = ",".join("?" for _ in service_ids)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT MIN(usage_date) as first_date, COUNT(DISTINCT usage_date) as day_count
                FROM daily_usage
                WHERE service_id IN ({placeholders});
            """, service_ids)
            row = cursor.fetchone()
            if row and row["first_date"]:
                return row["first_date"], row["day_count"]
        return None, 0

    def get_daily_usage_for_services(self, service_ids: List[str], days: int = 7) -> Dict[str, Dict[str, int]]:
        """
        دریافت مصرف روزانه تجمیع‌شده برای لیستی از سرویس‌ها
        خروجی دیکشنری بر اساس تاریخ: {'YYYY-MM-DD': {'up': ..., 'down': ..., 'total': ...}}
        """
        if not service_ids:
            return {}

        now_dt = datetime.now(TEHRAN_TZ)
        start_date = (now_dt.date() - timedelta(days=days - 1)).strftime("%Y-%m-%d")

        placeholders = ",".join("?" for _ in service_ids)
        query = f"""
            SELECT usage_date,
                   SUM(up_bytes) as total_up,
                   SUM(down_bytes) as total_down,
                   SUM(total_bytes) as total_tot
            FROM daily_usage
            WHERE service_id IN ({placeholders}) AND usage_date >= ?
            GROUP BY usage_date
            ORDER BY usage_date ASC;
        """
        params = list(service_ids) + [start_date]

        result = {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            for row in cursor.fetchall():
                result[row["usage_date"]] = {
                    "up": row["total_up"] or 0,
                    "down": row["total_down"] or 0,
                    "total": row["total_tot"] or 0,
                }
        return result

    def get_statistics(self, service_ids: List[str], days: int = 7, lang: str = "fa") -> dict:
        """
        محاسبه آمار کامل ۷ روز اخیر بر اساس داده‌های واقعی
        بدون ساخت داده جعلی!
        """
        now_dt = datetime.now(TEHRAN_TZ)
        today = now_dt.date()

        date_list = [today - timedelta(days=i) for i in reversed(range(days))]
        recorded_map = self.get_daily_usage_for_services(service_ids, days=days)
        first_date, total_historical_days = self.get_service_history_info(service_ids)

        days_data = []
        total_bytes = 0
        peak_bytes = 0
        peak_date_str = ""
        peak_day_name = ""
        days_with_traffic = 0

        for d in date_list:
            d_str = d.strftime("%Y-%m-%d")
            weekday_idx = d.weekday()
            day_name = PERSIAN_WEEKDAYS.get(weekday_idx, "") if lang == "fa" else ENGLISH_WEEKDAYS.get(weekday_idx, "")

            rec = recorded_map.get(d_str, {"up": 0, "down": 0, "total": 0})
            day_total = rec["total"]
            total_bytes += day_total

            if day_total > 0:
                days_with_traffic += 1

            if day_total > peak_bytes:
                peak_bytes = day_total
                peak_date_str = d_str
                peak_day_name = day_name

            # تبدیل تاریخ به فرمت کوتاه شمسی در صورت زبان فارسی
            short_date = format_short_date(d_str, lang=lang)

            days_data.append({
                "date": d_str,
                "short_date": short_date,
                "day_name": day_name,
                "weekday_idx": weekday_idx,
                "up_bytes": rec["up"],
                "down_bytes": rec["down"],
                "total_bytes": day_total,
                "up_gb": rec["up"] / (1024 ** 3),
                "down_gb": rec["down"] / (1024 ** 3),
                "total_gb": day_total / (1024 ** 3),
                "has_data": d_str in recorded_map
            })

        total_gb = total_bytes / (1024 ** 3)
        peak_gb = peak_bytes / (1024 ** 3)

        # بررسی کافی بودن تاریخچه و محاسبه دقیق تعداد روزهای مؤثر برای میانگین
        has_sufficient_history = True
        history_note = ""
        effective_days = days

        if not first_date:
            has_sufficient_history = False
            effective_days = 1
            history_note = "ثبت آمار این سرویس به تازگی آغاز شده است." if lang == "fa" else "Stats collection just started for this service."
        else:
            first_dt = datetime.strptime(first_date, "%Y-%m-%d").date()
            recorded_span_days = max(1, (today - first_dt).days + 1)
            # در صورتی که عمر سرویس کمتر از ۷ روز باشد، میانگین بر تعداد روزهای واقعی سپری‌شده تقسیم می‌شود نه عدد ۷
            effective_days = min(days, max(1, recorded_span_days))

            if recorded_span_days < days or total_historical_days < days:
                has_sufficient_history = False
                shamsi_start = format_date_persian(first_date) if lang == "fa" else first_date
                history_note = (
                    f"آمار مربوط به {to_persian_digits(total_historical_days)} روز ثبت‌شده است (شروع ثبت: {shamsi_start})."
                    if lang == "fa" else
                    f"Showing {total_historical_days} recorded days (started: {first_date})."
                )

        avg_gb = total_gb / effective_days if effective_days > 0 else 0.0
        avg_bytes = int(round(total_bytes / effective_days)) if effective_days > 0 else 0

        return {
            "days_data": days_data,
            "total_bytes": total_bytes,
            "peak_bytes": peak_bytes,
            "avg_bytes": avg_bytes,
            "effective_days": effective_days,
            "total_gb": total_gb,
            "avg_gb": avg_gb,
            "peak_gb": peak_gb,
            "peak_day_name": peak_day_name or ("-" if lang == "fa" else "-"),
            "peak_date": peak_date_str or ("-" if lang == "fa" else "-"),
            "days_with_traffic": days_with_traffic,
            "has_sufficient_history": has_sufficient_history,
            "history_note": history_note,
            "first_recorded_date": first_date
        }

    def export_backup_data(self) -> dict:
        """خروجی گرفتن از تمام اطلاعات دیتابیس SQLite برای فایل بکاپ کامل ربات"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            tables = ["services", "traffic_snapshots", "daily_usage", "reset_events"]
            backup = {}
            for tbl in tables:
                cursor.execute(f"SELECT * FROM {tbl};")
                rows = cursor.fetchall()
                backup[tbl] = [dict(r) for r in rows]
            return backup

    def import_backup_data(self, backup_dict: dict) -> bool:
        """بازگردانی داده‌های بکاپ به درون دیتابیس SQLite"""
        if not backup_dict or not isinstance(backup_dict, dict):
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for tbl, rows in backup_dict.items():
                if not isinstance(rows, list) or not rows:
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    cols = list(row.keys())
                    placeholders = ",".join("?" for _ in cols)
                    col_names = ",".join(cols)
                    cursor.execute(f"""
                        INSERT OR REPLACE INTO {tbl} ({col_names})
                        VALUES ({placeholders});
                    """, list(row.values()))
            conn.commit()
            logger.info("✅ دیتابیس مصرف روزانه با موفقیت از فایل بکاپ بازگردانی شد.")
            return True


# ====================================================================
# 2. Modern Dashboard Chart Generator (Matplotlib, Vazirmatn, RTL)
# ====================================================================

class DailyUsageChartRenderer:
    """
    تولیدکننده نمودار مصرف با ظاهر داشبورد تیره پریمیوم
    طراحی شده برای مشاهده با کیفیت بالا روی موبایل تلگرام
    پشتیبانی کامل از چیدمان راست‌به‌چپ (RTL) و تشخیص خودکار واحدهای مگابایت و گیگابایت
    """

    @classmethod
    def render(cls, stats: dict, lang: str = "fa") -> bytes:
        """
        رسم نمودار در حافظه و بازگرداندن بایت‌های PNG
        """
        days_data = stats.get("days_data", [])
        total_gb = stats.get("total_gb", 0.0)
        avg_gb = stats.get("avg_gb", 0.0)
        peak_gb = stats.get("peak_gb", 0.0)
        peak_day = stats.get("peak_day_name", "-")
        history_note = stats.get("history_note", "")

        is_rtl = (lang == "fa")

        # تشخیص خودکار مقیاس بر اساس اوج مصرف (اگر کل روزها زیر 1 گیگابایت باشد، بر حسب مگابایت رسم می‌شود)
        max_val_gb = max((d["total_gb"] for d in days_data), default=0.0)
        use_mb = (max_val_gb < 1.0)

        # ساخت شیء ایزوله Figure و Canvas بدون استفاده از وضعیت گلوبال pyplot
        fig = Figure(figsize=(10, 5.8), dpi=140)
        canvas = FigureCanvasAgg(fig)
        ax = fig.add_subplot(1, 1, 1)

        # اعمال چیدمان راست‌به‌چپ (RTL) در زبان فارسی
        if is_rtl:
            ax.invert_xaxis()
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position("right")

        # رنگ‌بندی تیره مدرن داشبورد
        fig_bg = "#0B0F19"
        card_bg = "#111827"
        grid_color = "#334155"
        text_light = "#F8FAFC"
        text_muted = "#94A3B8"
        cyan_primary = "#06B6D4"
        cyan_accent = "#38BDF8"
        peak_color = "#10B981"  # رنگ سبز زمردی برای اوج مصرف

        fig.patch.set_facecolor(fig_bg)
        ax.set_facecolor(card_bg)

        # خطوط راهنمای افقی
        ax.grid(axis='y', linestyle='--', alpha=0.3, color=grid_color, zorder=1)
        ax.set_axisbelow(True)

        x_indices = list(range(len(days_data)))

        if use_mb:
            usage_values = [d["total_gb"] * 1024 for d in days_data]
            max_val = max(usage_values) if usage_values else 100.0
            y_max = max(max_val * 1.30, 50.0)
            y_unit_label = "مگابایت" if is_rtl else "MB"
        else:
            usage_values = [d["total_gb"] for d in days_data]
            max_val = max_val_gb if max_val_gb else 1.0
            y_max = max(max_val * 1.30, 0.5)
            y_unit_label = "گیگابایت" if is_rtl else "GB"

        # ساخت رنگ میله‌ها (میله اوج مصرف برجسته می‌شود)
        colors = []
        edge_colors = []
        for v in usage_values:
            if v > 0 and math.isclose(v, max_val, rel_tol=1e-3):
                colors.append(peak_color)
                edge_colors.append("#34D399")
            else:
                colors.append(cyan_primary)
                edge_colors.append(cyan_accent)

        bars = ax.bar(
            x_indices,
            usage_values,
            width=0.48,
            color=colors,
            edgecolor=edge_colors,
            linewidth=1.2,
            zorder=3,
            alpha=0.92
        )

        # برچسب حجم بالای هر میله با تشخیص خودکار MB و GB
        bar_fp = get_font_properties(is_bold=True, size=9.5)
        for bar, d, val in zip(bars, days_data, usage_values):
            height = bar.get_height()
            gb = d["total_gb"]
            if gb <= 0:
                lbl = "۰" if is_rtl else "0"
            elif gb < 1.0:
                mb = gb * 1024
                lbl = f"{to_persian_digits(f'{mb:.0f}')} مگ" if is_rtl else f"{mb:.0f} MB"
            else:
                lbl = f"{to_persian_digits(f'{gb:.2f}')} گیگ" if is_rtl else f"{gb:.2f} GB"

            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                height + max(y_max * 0.025, 0.03),
                lbl,
                fontproperties=bar_fp,
                ha='center', va='bottom',
                color=text_light,
                zorder=4
            )

        # برچسب محور X (روز هفته + تاریخ شمسی در فارسی)
        x_labels = [
            f"{format_persian_text(d['day_name'])}\n{to_persian_digits(d['short_date']) if is_rtl else d['short_date']}"
            for d in days_data
        ]

        xtick_fp = get_font_properties(is_bold=False, size=10.0)
        ax.set_xticks(x_indices)
        ax.set_xticklabels(x_labels, fontproperties=xtick_fp, color=text_muted)
        for tick in ax.get_xticklabels():
            tick.set_fontproperties(xtick_fp)
            tick.set_color(text_muted)

        # محور Y و برچسب واحد خودکار
        ytick_fp = get_font_properties(is_bold=False, size=9.0)
        ax.tick_params(axis='y', colors=text_muted, labelsize=9)
        for tick in ax.get_yticklabels():
            tick.set_fontproperties(ytick_fp)
            tick.set_color(text_muted)

        ylabel_fp = get_font_properties(is_bold=False, size=10.5)
        y_label_text = format_persian_text(f"مصرف اینترنت ({y_unit_label})") if is_rtl else f"Internet Usage ({y_unit_label})"
        ax.set_ylabel(y_label_text, fontproperties=ylabel_fp, color=text_muted, labelpad=12)
        ax.set_ylim(0, y_max)

        # زیباسازی حاشیه‌ها
        for spine in ['top', 'left' if is_rtl else 'right']:
            ax.spines[spine].set_visible(False)
        for spine in ['right' if is_rtl else 'left', 'bottom']:
            ax.spines[spine].set_color(grid_color)
            ax.spines[spine].set_linewidth(1.0)

        # عنوان داشبورد
        title_fp = get_font_properties(is_bold=True, size=14.5)
        title = format_persian_text("نمودار مصرف روزانه اینترنت (۷ روز اخیر)") if is_rtl else "Daily Internet Usage (Last 7 Days)"
        fig.text(0.5, 0.94, title, fontproperties=title_fp, ha='center', va='top', color=text_light)

        # کارت آماری بالای نمودار با تشخیص خودکار مگابایت و گیگابایت
        def _fmt_brief(gb_val):
            if gb_val >= 1.0:
                return f"{to_persian_digits(f'{gb_val:.2f}')} گیگ" if is_rtl else f"{gb_val:.2f} GB"
            else:
                mb = gb_val * 1024
                if mb >= 10:
                    return f"{to_persian_digits(f'{mb:.1f}')} مگ" if is_rtl else f"{mb:.1f} MB"
                elif mb > 0:
                    return f"{to_persian_digits(f'{mb:.2f}')} مگ" if is_rtl else f"{mb:.2f} MB"
                else:
                    return "۰ مگ" if is_rtl else "0 MB"

        tot_str = _fmt_brief(total_gb)
        avg_str = _fmt_brief(avg_gb) + ("/روز" if is_rtl else "/day")
        peak_str = _fmt_brief(peak_gb) + (f" ({peak_day})" if peak_day != "-" else "")

        if is_rtl:
            summary_raw = f"مجموع: {tot_str}  •  میانگین: {avg_str}  •  اوج: {peak_str}"
            summary_text = format_persian_text(summary_raw)
        else:
            summary_text = f"Total: {tot_str}  •  Average: {avg_str}  •  Peak: {peak_str}"

        summary_fp = get_font_properties(is_bold=True, size=10.5)
        fig.text(0.5, 0.88, summary_text, fontproperties=summary_fp, ha='center', va='top', color=cyan_accent)

        # یادداشت شفافیت تاریخی (با تاریخ شمسی در فارسی)
        if history_note:
            note_display = format_persian_text(history_note) if is_rtl else history_note
            note_fp = get_font_properties(is_bold=False, size=9.0)
            fig.text(0.5, 0.02, note_display, fontproperties=note_fp, ha='center', va='bottom', color="#EAB308")

        fig.subplots_adjust(top=0.82, bottom=0.15, left=0.08 if is_rtl else 0.10, right=0.92 if is_rtl else 0.96)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', facecolor=fig.get_facecolor(), edgecolor='none', bbox_inches='tight')

        return buf.getvalue()


# نمونه یکتای سراسری از استور
usage_store = DailyUsageStore()


# ====================================================================
# 3. Unified Traffic Fetcher & Background Collector
# ====================================================================

async def fetch_client_total_traffic(
    email: str,
    get_inbounds_func=None,
    get_client_traffic_func=None
) -> Optional[Dict[str, int]]:
    """
    دریافت ترافیک دقیق کلاینت از پنل 3X-UI.
    در 3X-UI، جدول client_traffics برای هر ایمیل سراسری و یکتا است.
    این تابع تضمین می‌کند هم تسک پس‌زمینه و هم درخواست لحظه‌ای کاربر،
    دقیقاً از داده همسان استفاده کنند و ترافیک در صورت وجود در چند اینباند ضرب نشود.
    """
    if not email:
        return None

    email_str = str(email).strip()

    # ۱. اولویت اول: استعلام مستقیم از API ترافیک تک کلاینت (/panel/api/clients/traffic/{email})
    # این متد منبع اصلی و معتبر داده در 3X-UI است و مقدار واقعی سراسری را بدون ضرب اینباندی برمی‌گرداند.
    if get_client_traffic_func:
        try:
            live_traff = await get_client_traffic_func(email_str)
            if live_traff and isinstance(live_traff, dict):
                up = int(live_traff.get("up", 0) or 0)
                down = int(live_traff.get("down", 0) or 0)
                return {'up': up, 'down': down, 'total': up + down}
        except Exception as e:
            logger.debug(f"خطا در استعلام ترافیک کلاینت {email}: {e}")

    # ۲. فال‌بک: در صورت عدم دسترسی به API تک کلاینت، استعلام از لیست اینباندها
    if get_inbounds_func:
        try:
            inbounds = await get_inbounds_func(include_disabled=True)
            if inbounds and isinstance(inbounds, list):
                max_up = 0
                max_down = 0
                found = False

                for inbound in inbounds:
                    client_stats = inbound.get('clientStats', [])
                    if isinstance(client_stats, str):
                        try:
                            client_stats = json.loads(client_stats)
                        except Exception:
                            client_stats = []

                    if isinstance(client_stats, list):
                        for stat in client_stats:
                            if stat.get('email') and str(stat['email']).strip() == email_str:
                                try:
                                    up = int(stat.get('up', 0) or 0)
                                    down = int(stat.get('down', 0) or 0)
                                    # در 3X-UI ترافیک کلاینت‌ها سراسری (Global per email) است
                                    # و نباید در صورت عضویت کلاینت در چندین اینباند، با هم جمع شوند!
                                    max_up = max(max_up, up)
                                    max_down = max(max_down, down)
                                    found = True
                                except (TypeError, ValueError):
                                    pass

                if found:
                    return {'up': max_up, 'down': max_down, 'total': max_up + max_down}
        except Exception as e:
            logger.debug(f"خطا در دریافت ترافیک از اینباندها برای {email}: {e}")

    return None


class DailyUsageCollector:
    """
    تسک پس‌زمینه جمع‌آوری دوره‌ای ترافیک از پنل Sanaei
    با استفاده از یک درخواست بهینه به inbounds
    """

    def __init__(self, store: DailyUsageStore = usage_store):
        self.store = store
        self._running = False

    async def start(self, get_inbounds_func, get_approved_emails_func, interval_seconds: int = 1800):
        """
        اجرای تسک دوره‌ای در پس‌زمینه بدون بلاک کردن ربات
        """
        self._running = True
        logger.info("🚀 تسک جمع‌آوری دوره‌ای مصرف روزانه آغاز شد (بازه: %d ثانیه)", interval_seconds)

        while self._running:
            try:
                await self.collect_all(get_inbounds_func, get_approved_emails_func)
            except asyncio.CancelledError:
                logger.info("تسک جمع‌آوری مصرف روزانه لغو شد.")
                break
            except Exception as e:
                logger.error(f"❌ خطا در تسک جمع‌آوری دوره‌ای مصرف: {e}", exc_info=True)

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

    async def collect_all(self, get_inbounds_func, get_approved_emails_func) -> int:
        """
        یک نوبت استعلام از تمام اینباندها و ثبت اسنپ‌شات کلاینت‌ها
        """
        try:
            inbounds = await get_inbounds_func(include_disabled=True)
            if not inbounds:
                return 0

            approved_emails = set(get_approved_emails_func() or [])

            # تجمیع مصرف بر اساس email در صورتی که کلاینت در چند اینباند باشد
            client_traffics: Dict[str, Dict[str, int]] = {}

            for inbound in inbounds:
                client_stats = inbound.get('clientStats', [])
                if isinstance(client_stats, str):
                    try:
                        client_stats = json.loads(client_stats)
                    except Exception:
                        client_stats = []

                if isinstance(client_stats, list):
                    for stat in client_stats:
                        email = stat.get('email')
                        if not email:
                            continue

                        email_str = str(email).strip()
                        if approved_emails and email_str not in approved_emails:
                            continue

                        try:
                            up = int(stat.get('up', 0) or 0)
                            down = int(stat.get('down', 0) or 0)
                        except (TypeError, ValueError):
                            continue

                        # در 3X-UI هر ایمیل رکورد یکتا در client_traffics دارد.
                        # اگر کلاینت در چند اینباند عضو باشد، نباید ترافیک آن ضرب شود.
                        if email_str not in client_traffics:
                            client_traffics[email_str] = {'up': up, 'down': down}
                        else:
                            client_traffics[email_str]['up'] = max(client_traffics[email_str]['up'], up)
                            client_traffics[email_str]['down'] = max(client_traffics[email_str]['down'], down)

            updated_count = 0
            now = time.time()
            for email, traff in client_traffics.items():
                recorded = self.store.record_snapshot(
                    service_id=email,
                    up_bytes=traff['up'],
                    down_bytes=traff['down'],
                    timestamp=now
                )
                if recorded:
                    updated_count += 1

            if updated_count > 0:
                logger.info("📊 ثبت اسنپ‌شات دوره‌ای مصرف: %d کلاینت به‌روزرسانی شد.", updated_count)
            return updated_count

        except Exception as e:
            logger.error(f"خطا در collect_all مصرف روزانه: {e}")
            return 0


usage_collector = DailyUsageCollector(usage_store)


# ====================================================================
# 4. Telegram UI & Presentation Handler
# ====================================================================

async def handle_daily_usage_request(
    callback: CallbackQuery,
    order_id: int,
    from_view: int = 0,
    get_order_func=None,
    get_inbounds_func=None,
    get_client_traffic_func=None,
    lang: str = "fa"
):
    """
    هندلر اختصاصی کلیک روی دکمه '📊 آمار مصرف روزانه'
    - دریافت اسنپ‌شات لحظه‌ای با استفاده از تابع تجمیعی همسان
    - راستی‌آزمایی ترافیک مصرفی در برابر مصرف کل پنل جهت رفع خطاهای احتمالی
    - استخراج آمار واقعی ۷ روز اخیر (با تاریخ شمسی برای فارسی)
    - رندر نمودار داشبوردی راست‌به‌چپ با تفکیک هوشمند MB و GB
    - ارسال تصویر همراه با کپشن تفصیلی و راست‌به‌چپ
    """
    user_id = callback.from_user.id

    if not get_order_func:
        await callback.answer("خطا در بازیابی سفارش", show_alert=True)
        return

    order = get_order_func(str(order_id))
    if not order or order.get('user_id') != user_id:
        await callback.answer(
            "❌ سفارش یافت نشد" if lang == "fa" else "❌ Order not found",
            show_alert=True
        )
        return

    await callback.answer(
        "📊 در حال تحلیل و آماده‌سازی آمار مصرف..." if lang == "fa" else "📊 Generating daily usage chart...",
        show_alert=False
    )

    # شناسایی سرویس‌ها
    email = order.get('email', '')
    service_ids = []
    if email and str(email).strip():
        service_ids.append(str(email).strip())

    # استخراج سرویس‌های دیگر سفارش در صورت وجود چند کانفیگ
    for ib in order.get('inbound_details', []):
        if isinstance(ib, dict):
            ib_email = ib.get('email')
            if ib_email and str(ib_email).strip() not in service_ids:
                service_ids.append(str(ib_email).strip())

    if not service_ids:
        service_ids = [f"order_{order_id}"]

    # ثبت سرویس‌ها در دیتابیس SQLite
    for s_id in service_ids:
        usage_store.register_service(
            service_id=s_id,
            order_id=str(order_id),
            user_id=user_id,
            email=email or s_id,
            title=f"Order #{order_id}"
        )

    # دریافت لحظه‌ای ترافیک دقیق با استفاده از منطق تجمیعی یکپارچه
    live_traffic_data = None
    if email:
        live_traffic_data = await fetch_client_total_traffic(
            email=email,
            get_inbounds_func=get_inbounds_func,
            get_client_traffic_func=get_client_traffic_func
        )
        if live_traffic_data:
            # گام ۱: راستی‌آزمایی قبل از ثبت اسنپ‌شات جدید جهت جلوگیری از False Reset و اصلاح مقادیر گذشته
            usage_store.sanitize_service_usage(email, live_traffic_data['total'])
            # گام ۲: ثبت اسنپ‌شات
            usage_store.record_snapshot(email, live_traffic_data['up'], live_traffic_data['down'])
            # گام ۳: راستی‌آزمایی نهایی
            usage_store.sanitize_service_usage(email, live_traffic_data['total'])

    # محاسبه آمار ۷ روز گذشته
    stats = usage_store.get_statistics(service_ids, days=7, lang=lang)

    # رندر نمودار در ترد مجزا تا Event Loop ربات بلاک نشود
    chart_png = await asyncio.to_thread(DailyUsageChartRenderer.render, stats, lang)

    # ساخت کپشن پیام با تشخیص خودکار مگابایت و گیگابایت و نشانگر جهت راست‌به‌چپ
    total_bytes = stats.get("total_bytes", 0)
    peak_bytes = stats.get("peak_bytes", 0)
    avg_bytes = stats.get("avg_bytes", total_bytes)
    peak_day = stats.get("peak_day_name", "-")
    history_note = stats.get("history_note", "")

    if lang == "fa":
        tot_text = format_traffic_auto(total_bytes, lang="fa")
        avg_text = format_traffic_auto(avg_bytes, lang="fa")
        peak_text = f"{format_traffic_auto(peak_bytes, lang='fa')} ({peak_day})" if peak_bytes > 0 else "ثبت نشده"
        
        # استفاده از نشانگر یونیکد RLM (\u200f) در ابتدای هر خط برای تضمین رندر راست‌به‌چپ در تلگرام
        caption = f"""\u200f📊 <b>گزارش مصرف روزانه اینترنت</b>

\u200f📦 <b>مجموع مصرف:</b> {tot_text}
\u200f📈 <b>میانگین روزانه:</b> {avg_text}
\u200f🔥 <b>بیشترین مصرف:</b> {peak_text}

\u200f🗓 <b>بازه:</b> ۷ روز گذشته
"""
        if history_note:
            caption += f"\n\u200fℹ️ <i>{history_note}</i>\n"
    else:
        tot_text = format_traffic_auto(total_bytes, lang="en")
        avg_text = format_traffic_auto(avg_bytes, lang="en")
        peak_text = f"{format_traffic_auto(peak_bytes, lang='en')} ({peak_day})" if peak_bytes > 0 else "None"

        caption = f"""📊 <b>Daily Internet Usage Report</b>

📦 <b>Total Usage:</b> {tot_text}
📈 <b>Daily Average:</b> {avg_text}
🔥 <b>Peak Usage:</b> {peak_text}

🗓 <b>Period:</b> Last 7 days
"""
        if history_note:
            caption += f"\nℹ️ <i>{history_note}</i>\n"

    # ساخت کیبورد بازگشت
    back_callback = f"view_config_{order_id}" if from_view != 2 else f"show_text_{order_id}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت به کانفیگ" if lang == "fa" else "🔙 Back to Config",
                    callback_data=back_callback,
                    style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 منوی اصلی" if lang == "fa" else "🏠 Main Menu",
                    callback_data="back_to_main",
                    style="danger"
                )
            ]
        ]
    )

    photo_file = BufferedInputFile(chart_png, filename=f"daily_usage_{order_id}.png")

    try:
        try:
            await callback.message.delete()
        except Exception:
            pass

        await callback.message.answer_photo(
            photo=photo_file,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"خطا در ارسال نمودار مصرف روزانه: {e}")
        await callback.message.answer(
            caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )

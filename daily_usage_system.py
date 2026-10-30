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
- Modern dark-themed dashboard chart generator (Matplotlib, Persian RTL shaping, non-blocking).
- Scheduled background collector using panel inbounds clientStats.
- No fake/fabricated historical data; transparent notification when history is limited.
"""

import os
import io
import time
import math
import logging
import sqlite3
import asyncio
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any

# Data visualization & RTL shaping
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import arabic_reshaper
from bidi.algorithm import get_display

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, CallbackQuery
from aiogram.enums import ParseMode

from config import DATA_DIR

logger = logging.getLogger("daily_usage")

# Local Tehran Timezone (UTC +03:30)
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

DB_PATH = os.path.join(DATA_DIR, "daily_usage.db")

PERSIAN_WEEKDAYS = {
    0: "دوشنبه",
    1: "سه‌شنبه",
    2: "چهارشنبه",
    3: "پنج‌شنبه",
    4: "جمعه",
    5: "شنبه",
    6: "یکشنبه"
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


def format_persian_text(text: str) -> str:
    """شکل‌دهی صحیح متون فارسی برای نمایش در Matplotlib (RTL + Glyphs)"""
    if not text:
        return ""
    try:
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)
    except Exception:
        return str(text)


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

        ویژگی‌ها:
        1. جلوگیری از داده تکراری و Debounce (اگر ترافیک تغییر نکرده باشد یا فاصله < 30 ثانیه باشد).
        2. شناسایی هوشمند ریست شمارنده (Counter Reset) بدون تولید مقادیر منفی و لاگ رویداد.
        3. مدیریت دقیق عبور از نیمه‌شب با تقسیم زمانی متناسب بین روزهای تقویمی.
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
                if total_bytes < last_total or up_bytes < last_up or down_bytes < last_down:
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
                    delta_up = up_bytes - last_up
                    delta_down = down_bytes - last_down
                    delta_total = total_bytes - last_total
            else:
                # اولین اسنپ‌شات برای این سرویس:
                # اسنپ‌شات ثبت می‌شود تا مبنای محاسبات بعدی باشد، اما کل حجم تجمعی گذشته را به عنوان مصرف امروز حساب نمی‌کنیم!
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

            days_data.append({
                "date": d_str,
                "short_date": d.strftime("%m/%d"),
                "day_name": day_name,
                "weekday_idx": weekday_idx,
                "up_gb": rec["up"] / (1024 ** 3),
                "down_gb": rec["down"] / (1024 ** 3),
                "total_gb": day_total / (1024 ** 3),
                "has_data": d_str in recorded_map
            })

        total_gb = total_bytes / (1024 ** 3)
        peak_gb = peak_bytes / (1024 ** 3)
        avg_gb = total_gb / days if days > 0 else 0.0

        # بررسی کافی بودن تاریخچه (شرط 7)
        has_sufficient_history = True
        history_note = ""

        if not first_date:
            has_sufficient_history = False
            history_note = "ثبت آمار این سرویس به تازگی آغاز شده است." if lang == "fa" else "Stats collection just started for this service."
        else:
            first_dt = datetime.strptime(first_date, "%Y-%m-%d").date()
            recorded_span_days = (today - first_dt).days + 1
            if recorded_span_days < days or total_historical_days < days:
                has_sufficient_history = False
                history_note = (
                    f"آمار مربوط به {to_persian_digits(total_historical_days)} روز ثبت‌شده است (شروع ثبت: {to_persian_digits(first_date)})."
                    if lang == "fa" else
                    f"Showing {total_historical_days} recorded days (started: {first_date})."
                )

        return {
            "days_data": days_data,
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


# ====================================================================
# 2. Modern Dashboard Chart Generator (Matplotlib, Persian RTL, Dark UI)
# ====================================================================

class DailyUsageChartRenderer:
    """
    تولیدکننده نمودار مصرف با ظاهر داشبورد تیره پریمیوم
    طراحی شده برای مشاهده با کیفیت بالا روی موبایل تلگرام
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

        # فونت‌های پیشنهادی سیستم
        plt.rcParams['font.sans-serif'] = ['Vazir', 'Segoe UI', 'Segoe UI Emoji', 'Tahoma', 'Arial']
        plt.rcParams['axes.unicode_minus'] = False

        fig, ax = plt.subplots(figsize=(10, 5.8), dpi=140)

        # رنگ‌بندی تیره مدرن
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
        usage_values = [d["total_gb"] for d in days_data]

        max_val = max(usage_values) if usage_values else 1.0
        y_max = max(max_val * 1.30, 0.5)

        # ساخت رنگ میله‌ها (میله اوج مصرف برجسته می‌شود)
        colors = []
        edge_colors = []
        for v in usage_values:
            if v > 0 and math.isclose(v, peak_gb, rel_tol=1e-3):
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

        # افزودن برچسب حجم بالای هر میله
        for bar, val in zip(bars, usage_values):
            height = bar.get_height()
            if val >= 0.1:
                label = f"{val:.2f} GB"
            elif val > 0:
                mb_val = val * 1024
                label = f"{mb_val:.0f} MB"
            else:
                label = "۰" if lang == "fa" else "0"

            if lang == "fa":
                label = to_persian_digits(label)

            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                height + max(y_max * 0.025, 0.03),
                label,
                ha='center', va='bottom',
                fontsize=9.5, fontweight='bold',
                color=text_light,
                zorder=4
            )

        # برچسب محور X (روز هفته + تاریخ)
        x_labels = []
        for d in days_data:
            day_text = format_persian_text(d["day_name"]) if lang == "fa" else d["day_name"]
            date_text = to_persian_digits(d["short_date"]) if lang == "fa" else d["short_date"]
            x_labels.append(f"{day_text}\n{date_text}")

        ax.set_xticks(x_indices)
        ax.set_xticklabels(x_labels, color=text_muted, fontsize=10, fontweight='500')

        # برچسب محور Y
        ax.tick_params(axis='y', colors=text_muted, labelsize=9)
        y_label_text = format_persian_text("مصرف اینترنت (گیگابایت)") if lang == "fa" else "Internet Usage (GB)"
        ax.set_ylabel(y_label_text, color=text_muted, fontsize=10.5, labelpad=8)
        ax.set_ylim(0, y_max)

        # زیباسازی حاشیه‌ها
        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']:
            ax.spines[spine].set_color(grid_color)
            ax.spines[spine].set_linewidth(1.0)

        # عنوان داشبورد
        title = format_persian_text("نمودار مصرف روزانه اینترنت (۷ روز اخیر)") if lang == "fa" else "Daily Internet Usage (Last 7 Days)"
        fig.text(0.5, 0.94, title, ha='center', va='top', fontsize=14.5, fontweight='bold', color=text_light)

        # کارت آماری بالای نمودار
        if lang == "fa":
            tot_str = to_persian_digits(f"{total_gb:.2f}")
            avg_str = to_persian_digits(f"{avg_gb:.2f}")
            peak_str = to_persian_digits(f"{peak_gb:.2f}")
            peak_day_shw = format_persian_text(peak_day)
            summary_text = format_persian_text(f"مجموع: {tot_str} گیگ  •  میانگین: {avg_str} گیگ/روز  •  اوج: {peak_str} گیگ ({peak_day_shw})")
        else:
            summary_text = f"Total: {total_gb:.2f} GB  •  Average: {avg_gb:.2f} GB/day  •  Peak: {peak_gb:.2f} GB ({peak_day})"

        fig.text(0.5, 0.88, summary_text, ha='center', va='top', fontsize=10.5, color=cyan_accent, fontweight='600')

        # یادداشت شفافیت تاریخی (اگر سابقه کمتر از ۷ روز باشد)
        if history_note:
            note_display = format_persian_text(history_note) if lang == "fa" else history_note
            fig.text(0.5, 0.02, note_display, ha='center', va='bottom', fontsize=9, color="#EAB308", fontweight='500')

        plt.subplots_adjust(top=0.82, bottom=0.15, left=0.10, right=0.96)

        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor=fig.get_facecolor(), edgecolor='none', bbox_inches='tight')
        plt.close(fig)

        return buf.getvalue()


# نمونه یکتای سراسری از استور
usage_store = DailyUsageStore()


# ====================================================================
# 3. Background Scheduled Collector Task (Zero-Lag, Panel Inbounds)
# ====================================================================

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

            import json
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
                        # اگر ایمیل‌های تایید شده مشخص باشد فیلتر می‌کنیم
                        if approved_emails and email_str not in approved_emails:
                            continue

                        try:
                            up = int(stat.get('up', 0) or 0)
                            down = int(stat.get('down', 0) or 0)
                        except (TypeError, ValueError):
                            continue

                        if email_str not in client_traffics:
                            client_traffics[email_str] = {'up': 0, 'down': 0}
                        client_traffics[email_str]['up'] += up
                        client_traffics[email_str]['down'] += down

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
    get_client_traffic_func=None,
    lang: str = "fa"
):
    """
    هندلر اختصاصی کلیک روی دکمه '📊 آمار مصرف روزانه'
    - دریافت اسنپ‌شات لحظه‌ای (Live) بدون تکرار
    - استخراج آمار واقعی ۷ روز اخیر
    - رندر نمودار داشبوردی به صورت غیربلاک‌کننده (Thread Pool)
    - ارسال تصویر همراه با کپشن تفصیلی و دکمه‌های بازگشت
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

    # شرط 5 & 6: استعلام لحظه‌ای از پنل برای اطمینان از به‌روز بودن دقیق آمار
    if get_client_traffic_func and email:
        try:
            live_traff = await get_client_traffic_func(email)
            if live_traff and isinstance(live_traff, dict):
                up = live_traff.get("up", 0)
                down = live_traff.get("down", 0)
                usage_store.record_snapshot(email, up, down)
        except Exception as e:
            logger.debug(f"خطا در استعلام لحظه‌ای ترافیک برای {email}: {e}")

    # محاسبه آمار ۷ روز گذشته
    stats = usage_store.get_statistics(service_ids, days=7, lang=lang)

    # رندر نمودار در ترد مجزا تا Event Loop ربات بلاک نشود
    chart_png = await asyncio.to_thread(DailyUsageChartRenderer.render, stats, lang)

    # ساخت کپشن پیام
    total_gb = stats["total_gb"]
    avg_gb = stats["avg_gb"]
    peak_gb = stats["peak_gb"]
    peak_day = stats["peak_day_name"]
    history_note = stats.get("history_note", "")

    if lang == "fa":
        tot_text = f"{to_persian_digits(f'{total_gb:.2f}')} گیگابایت"
        avg_text = f"{to_persian_digits(f'{avg_gb:.2f}')} گیگابایت"
        peak_text = f"{to_persian_digits(f'{peak_gb:.2f}')} گیگابایت ({peak_day})" if peak_gb > 0 else "ثبت نشده"
        
        caption = f"""📊 <b>گزارش مصرف روزانه اینترنت</b>

📦 <b>مجموع مصرف:</b> {tot_text}
📈 <b>میانگین روزانه:</b> {avg_text}
🔥 <b>بیشترین مصرف:</b> {peak_text}

🗓 <b>بازه:</b> ۷ روز گذشته
"""
        if history_note:
            caption += f"\nℹ️ <i>{history_note}</i>\n"
    else:
        caption = f"""📊 <b>Daily Internet Usage Report</b>

📦 <b>Total Usage:</b> {total_gb:.2f} GB
📈 <b>Daily Average:</b> {avg_gb:.2f} GB
🔥 <b>Peak Usage:</b> {peak_gb:.2f} GB ({peak_day})

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
        # در صورت امکان پیام متنی قبلی حذف و عکس جدید فرستاده شود
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

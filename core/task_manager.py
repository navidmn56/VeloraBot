"""
core/task_manager.py
--------------------
Central background task metadata registry, runtime state tracking, dynamic enable/disable
controls, persistent interval configuration, and interruptible sleep helpers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Metadata definitions for all periodic background tasks
TASK_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "id": "server_guard",
        "essential": True,
        "default_interval": 120,
        "min_interval": 30,
        "max_interval": 3600,
        "presets": [30, 60, 120, 300, 600],
        "icon": "🛡️",
        "name_fa": "نگهبان سرور و امنیت",
        "name_en": "Server & Security Guard",
        "desc_fa": "بررسی مداوم CPU، رم، دیسک، اتصال پنل و شناسایی اسپم/ریکوعست زیاد IP روی سرور و ارسال به بات لاگ.",
        "desc_en": "Continuously monitors CPU, RAM, disk, panel connectivity, and IP flood/spam; reports to Log Bot.",
        "impact_fa": "بسیار کم (اجرای سبک؛ حیاتی برای پایداری و امنیت سرور)",
        "impact_en": "Very low (essential for server stability & security alerts)",
    },
    {
        "id": "memory_monitor",
        "essential": True,
        "default_interval": 900,
        "min_interval": 120,
        "max_interval": 86400,
        "presets": [120, 300, 600, 900, 1800, 3600],
        "icon": "🧠",
        "name_fa": "مدیریت و آزادسازی حافظه (RAM)",
        "name_en": "Memory & GC Monitor",
        "desc_fa": "پایش مصرف رم ربات و آزادسازی کش و حافظه اضافه برای جلوگیری از کرش سرور.",
        "desc_en": "Monitors bot RSS memory usage and clears caches / runs GC to avoid OOM.",
        "impact_fa": "ضروری برای کنترل مصرف رم روی سرور",
        "impact_en": "Essential to prevent memory bloat",
    },
    {
        "id": "cleanup_expired_states",
        "essential": True,
        "default_interval": 1800,
        "min_interval": 300,
        "max_interval": 86400,
        "presets": [300, 900, 1800, 3600, 10800],
        "icon": "🧹",
        "name_fa": "پاکسازی وضعیت‌های منقضی کاربران",
        "name_en": "Expired FSM State Cleanup",
        "desc_fa": "حذف وضعیت‌های قدیمی، نشست‌های نیمه‌کاره و کش‌های موقت منقضی از حافظه.",
        "desc_en": "Prunes stale user FSM states and expired temporary caches from memory.",
        "impact_fa": "ضروری برای جلوگیری از رشد بی‌رویه رم",
        "impact_en": "Essential to keep in-memory state bounded",
    },
    {
        "id": "log_rotation",
        "essential": True,
        "default_interval": 604800,
        "min_interval": 3600,
        "max_interval": 2592000,
        "presets": [21600, 43200, 86400, 259200, 604800],
        "icon": "📜",
        "name_fa": "چرخش خودکار فایل‌های لاگ",
        "name_en": "Log File Rotation",
        "desc_fa": "چرخش فایل‌های لاگ بزرگ‌تر از ۵۰ مگابایت و حذف فایل‌های `.old` قدیمی.",
        "desc_en": "Rotates oversized log files (>50MB) and deletes archived logs older than 30 days.",
        "impact_fa": "ضروری برای جلوگیری از پر شدن فضای دیسک",
        "impact_en": "Essential to prevent disk exhaustion",
    },
    {
        "id": "alert_worker",
        "essential": False,
        "default_interval": 300,
        "min_interval": 60,
        "max_interval": 86400,
        "presets": [60, 180, 300, 600, 900, 1800, 3600],
        "icon": "🔔",
        "name_fa": "بررسی هشدار حجم و انقضای سرویس‌ها",
        "name_en": "Service Quota & Expiry Alerts",
        "desc_fa": "استعلام وضعیت سرویس‌های فعال از پنل و ارسال هشدار حجم/انقضا به کاربران.",
        "desc_en": "Polls active services and notifies users before data volume or expiry limits.",
        "impact_fa": "متوسط (در سرورهای شلوغ افزایش بازه به ۵ تا ۱۵ دقیقه توصیه می‌شود)",
        "impact_en": "Moderate (increase interval to 5-15m on low-resource servers)",
    },
    {
        "id": "daily_usage_collector",
        "essential": False,
        "default_interval": 300,
        "min_interval": 60,
        "max_interval": 86400,
        "presets": [120, 300, 600, 900, 1800, 3600],
        "icon": "📊",
        "name_fa": "جمع‌آوری آمار مصرف روزانه",
        "name_en": "Daily Usage Collector",
        "desc_fa": "ثبت دوره‌ای ترافیک مصرفی کلاینت‌ها در دیتابیس SQLite برای رسم نمودار مصرف.",
        "desc_en": "Records client traffic snapshots in SQLite for daily usage charts.",
        "impact_fa": "متوسط (در سرور ضعیف می‌توانید بازه را ۱۰ تا ۳۰ دقیقه کنید یا خاموش کنید)",
        "impact_en": "Moderate (raise to 10-30m or disable on very weak servers)",
    },
    {
        "id": "auto_backup",
        "essential": False,
        "default_interval": 21600,
        "min_interval": 600,
        "max_interval": 604800,
        "presets": [3600, 10800, 21600, 43200, 86400],
        "icon": "💾",
        "name_fa": "بکاپ خودکار دیتابیس",
        "name_en": "Auto Database Backup",
        "desc_fa": "تهیه نسخه پشتیبان کامل از فایل‌های JSON و دیتابیس‌های SQLite.",
        "desc_en": "Creates scheduled full backups of JSON stores and SQLite databases.",
        "impact_fa": "کم تا متوسط (تأثیر لحظه‌ای روی دیسک هنگام تهیه بکاپ)",
        "impact_en": "Low to moderate (brief disk I/O during backup)",
    },
    {
        "id": "sync_deleted_configs",
        "essential": False,
        "default_interval": 21600,
        "min_interval": 300,
        "max_interval": 604800,
        "presets": [1800, 3600, 10800, 21600, 43200],
        "icon": "🔄",
        "name_fa": "همگام‌سازی خودکار پنل و حذف‌شده‌ها",
        "name_en": "Panel Config Sync",
        "desc_fa": "تطبیق وضعیت سرویس‌ها بین دیتابیس ربات و پنل 3X-UI.",
        "desc_en": "Syncs deleted/updated client statuses between 3X-UI panel and bot database.",
        "impact_fa": "متوسط (درخواست به پنل + ذخیره دیتابیس)",
        "impact_en": "Moderate (queries panel & updates database)",
    },
    {
        "id": "auto_log_cleanup",
        "essential": False,
        "default_interval": 259200,
        "min_interval": 3600,
        "max_interval": 2592000,
        "presets": [21600, 43200, 86400, 172800, 259200, 604800],
        "icon": "✂️",
        "name_fa": "پاکسازی خودکار لاگ‌ها و گزارش",
        "name_en": "Auto Log Trimmer",
        "desc_fa": "نگهداری ۵۰۰ خط آخر فایل‌های لاگ و ارسال گزارش آزادسازی فضا به بات لاگ.",
        "desc_en": "Trims log files to last 500 lines and sends cleanup report to Log Bot.",
        "impact_fa": "بسیار کم",
        "impact_en": "Very low",
    },
    {
        "id": "weekly_cleanup",
        "essential": False,
        "default_interval": 604800,
        "min_interval": 3600,
        "max_interval": 2592000,
        "presets": [86400, 259200, 604800],
        "icon": "🗑️",
        "name_fa": "بهینه‌سازی دوره‌ای دیتابیس",
        "name_en": "Periodic DB Optimization",
        "desc_fa": "پاکسازی سفارش‌های لغو/ردشده قدیمی (>۳۰ روز)، کاربران غیرفعال (>۹۰ روز) و بکاپ‌های کهنه.",
        "desc_en": "Prunes old cancelled/rejected orders, inactive users, and aged backups.",
        "impact_fa": "کم (اجرای هفتگی به‌صورت پیش‌فرض یکشنبه‌ها)",
        "impact_en": "Low (runs weekly on Sundays by default)",
    },
    {
        "id": "health_monitor",
        "essential": False,
        "default_interval": 57600,
        "min_interval": 300,
        "max_interval": 604800,
        "presets": [3600, 21600, 43200, 57600, 86400, 172800],
        "icon": "❤️",
        "name_fa": "گزارش سلامت ربات به ادمین",
        "name_en": "Bot Health Report (DM)",
        "desc_fa": "ارسال گزارش وضعیت کامل دیتابیس، مالی، پنل و دیسک به پیام خصوصی ادمین.",
        "desc_en": "Sends periodic bot health summary to admin DM.",
        "impact_fa": "کم (یک تست اتصال پنل و بررسی دیسک)",
        "impact_en": "Low",
    },
    {
        "id": "disk_space_monitor",
        "essential": False,
        "default_interval": 172800,
        "min_interval": 600,
        "max_interval": 604800,
        "presets": [3600, 21600, 43200, 86400, 172800],
        "icon": "💽",
        "name_fa": "پایش فضای دیسک (هشدار ادمین)",
        "name_en": "Disk Space Warning (DM)",
        "desc_fa": "بررسی فضای آزاد دیسک و ارسال پیام خصوصی به ادمین در صورت کمتر بودن از ۱ گیگ.",
        "desc_en": "Checks free disk space and warns admin via DM if below 1 GB.",
        "impact_fa": "بسیار کم",
        "impact_en": "Very low",
    },
    {
        "id": "weekly_detailed_report",
        "essential": False,
        "default_interval": 604800,
        "min_interval": 3600,
        "max_interval": 2592000,
        "presets": [259200, 604800],
        "icon": "📈",
        "name_fa": "گزارش جامع هفتگی ربات",
        "name_en": "Weekly Detailed Report",
        "desc_fa": "ارسال گزارش کامل مالی، کاربران، رفرال و پنل یکشنبه‌ها به ادمین و ثبت در لاگ.",
        "desc_en": "Sends comprehensive weekly financial/users/panel report every Sunday.",
        "impact_fa": "کم",
        "impact_en": "Low",
    },
    {
        "id": "config_pool_monitor",
        "essential": False,
        "default_interval": 3600,
        "min_interval": 300,
        "max_interval": 604800,
        "presets": [1800, 3600, 10800, 21600, 43200],
        "icon": "📦",
        "name_fa": "پایش مخزن کانفیگ دستی",
        "name_en": "Offline Config Pool Monitor",
        "desc_fa": "در حالت غیرفعال بودن پنل سنایی، موجودی مخزن کانفیگ‌ها را بررسی و هشدار می‌دهد.",
        "desc_en": "Checks manual config pool count when Senai panel mode is disabled.",
        "impact_fa": "بسیار کم",
        "impact_en": "Very low",
    },
    {
        "id": "panel_limits_reset",
        "essential": False,
        "default_interval": 86400,
        "min_interval": 3600,
        "max_interval": 604800,
        "presets": [21600, 43200, 86400],
        "icon": "🔓",
        "name_fa": "ریست دوره‌ای محدودیت‌های پنل",
        "name_en": "Panel Rate-Limit Reset",
        "desc_fa": "ریست کردن شمارنده‌های داخلی محدودیت نرخ پنل به‌صورت دوره‌ای.",
        "desc_en": "Periodically resets internal panel rate-limiter counters.",
        "impact_fa": "بسیار کم",
        "impact_en": "Very low",
    },
]

_TASK_DEF_MAP: Dict[str, Dict[str, Any]] = {t["id"]: t for t in TASK_DEFINITIONS}

# Live runtime telemetry and wake events per task
_TASK_RUNTIME: Dict[str, Dict[str, Any]] = {}
_TASK_WAKE_EVENTS: Dict[str, Tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}
_FORCE_RUN_TASKS: set[str] = set()


def get_all_task_definitions() -> List[Dict[str, Any]]:
    return TASK_DEFINITIONS


def get_task_definition(task_id: str) -> Optional[Dict[str, Any]]:
    return _TASK_DEF_MAP.get(task_id)


def _get_store() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from database import configs_pool
    tasks_cfg = configs_pool.setdefault("background_tasks_settings", {})
    if not isinstance(tasks_cfg, dict):
        tasks_cfg = {}
        configs_pool["background_tasks_settings"] = tasks_cfg
    return configs_pool, tasks_cfg


def _persist_task_settings() -> None:
    try:
        from core.save_scheduler import schedule_file_save
        schedule_file_save("configs", delay=1.0)
    except Exception:
        try:
            from db_storage import DB_FILES, save_json
            from database import configs_pool
            save_json(DB_FILES["configs"], configs_pool)
        except Exception:
            pass


def _get_wake_event(task_id: str) -> asyncio.Event:
    loop = asyncio.get_running_loop()
    entry = _TASK_WAKE_EVENTS.get(task_id)
    if entry is not None and entry[0] is loop and not entry[0].is_closed():
        return entry[1]
    ev = asyncio.Event()
    _TASK_WAKE_EVENTS[task_id] = (loop, ev)
    return ev


def wake_task(task_id: str) -> None:
    """Wake a sleeping background task immediately so setting changes apply without restart."""
    entry = _TASK_WAKE_EVENTS.get(task_id)
    if entry is None:
        return
    loop, ev = entry
    try:
        if loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
            if running is loop:
                ev.set()
                return
        except RuntimeError:
            pass
        loop.call_soon_threadsafe(ev.set)
    except Exception:
        pass


def is_task_enabled(task_id: str) -> bool:
    meta = _TASK_DEF_MAP.get(task_id)
    if not meta:
        return False
    if meta.get("essential"):
        return True

    configs_pool, tasks_cfg = _get_store()
    entry = tasks_cfg.get(task_id)
    if isinstance(entry, dict) and "enabled" in entry:
        return bool(entry["enabled"])

    # Mirror legacy settings for backwards compatibility
    if task_id == "alert_worker":
        return bool(configs_pool.get("alert_settings", {}).get("enabled", True))
    if task_id == "auto_backup":
        return bool(configs_pool.get("auto_backup_settings", {}).get("backup_enabled", True))
    if task_id == "sync_deleted_configs":
        return bool(configs_pool.get("auto_backup_settings", {}).get("sync_enabled", True))
    return True


def get_task_interval(task_id: str) -> int:
    meta = _TASK_DEF_MAP.get(task_id)
    if not meta:
        return 300
    default_sec = int(meta["default_interval"])
    min_sec = int(meta.get("min_interval", 30))
    max_sec = int(meta.get("max_interval", 2592000))

    configs_pool, tasks_cfg = _get_store()
    entry = tasks_cfg.get(task_id)
    val = None
    if isinstance(entry, dict) and entry.get("interval_seconds") is not None:
        val = entry.get("interval_seconds")
    elif task_id == "alert_worker":
        val = configs_pool.get("alert_settings", {}).get("check_interval")
    elif task_id == "auto_backup":
        hrs = configs_pool.get("auto_backup_settings", {}).get("backup_interval_hours")
        if hrs is not None:
            val = float(hrs) * 3600
    elif task_id == "sync_deleted_configs":
        hrs = configs_pool.get("auto_backup_settings", {}).get("sync_interval_hours")
        if hrs is not None:
            val = float(hrs) * 3600

    try:
        sec = int(float(val)) if val is not None else default_sec
    except (TypeError, ValueError):
        sec = default_sec
    return max(min_sec, min(max_sec, sec))


def set_task_enabled(task_id: str, enabled: bool) -> bool:
    meta = _TASK_DEF_MAP.get(task_id)
    if not meta:
        return False
    if meta.get("essential"):
        # Essential tasks cannot be disabled
        return True

    configs_pool, tasks_cfg = _get_store()
    entry = tasks_cfg.setdefault(task_id, {})
    entry["enabled"] = bool(enabled)

    if task_id == "alert_worker":
        alert_cfg = configs_pool.setdefault("alert_settings", {})
        alert_cfg["enabled"] = bool(enabled)
        try:
            import sys
            for mod_name in ("main", "routers.admin_packages"):
                mod = sys.modules.get(mod_name)
                if mod is not None:
                    alt = getattr(mod, "alert_system", None)
                    if alt is not None and hasattr(alt, "enabled"):
                        alt.enabled = bool(enabled)
        except Exception:
            pass
    elif task_id == "auto_backup":
        configs_pool.setdefault("auto_backup_settings", {})["backup_enabled"] = bool(enabled)
    elif task_id == "sync_deleted_configs":
        configs_pool.setdefault("auto_backup_settings", {})["sync_enabled"] = bool(enabled)

    _persist_task_settings()
    wake_task(task_id)
    return bool(entry["enabled"])


def set_task_interval(task_id: str, interval_seconds: int) -> Optional[int]:
    meta = _TASK_DEF_MAP.get(task_id)
    if not meta:
        return None
    min_sec = int(meta.get("min_interval", 30))
    max_sec = int(meta.get("max_interval", 2592000))
    clamped = max(min_sec, min(max_sec, int(interval_seconds)))

    configs_pool, tasks_cfg = _get_store()
    entry = tasks_cfg.setdefault(task_id, {})
    entry["interval_seconds"] = clamped

    if task_id == "alert_worker":
        configs_pool.setdefault("alert_settings", {})["check_interval"] = clamped
        try:
            import sys
            for mod_name in ("main", "routers.admin_packages"):
                mod = sys.modules.get(mod_name)
                if mod is not None:
                    alt = getattr(mod, "alert_system", None)
                    if alt is not None and hasattr(alt, "check_interval"):
                        alt.check_interval = clamped
        except Exception:
            pass
    elif task_id == "auto_backup":
        configs_pool.setdefault("auto_backup_settings", {})["backup_interval_hours"] = round(clamped / 3600, 3)
    elif task_id == "sync_deleted_configs":
        configs_pool.setdefault("auto_backup_settings", {})["sync_interval_hours"] = round(clamped / 3600, 3)

    _persist_task_settings()
    wake_task(task_id)
    return clamped


def sync_legacy_task_setting(task_id: str, enabled: Optional[bool] = None, interval_seconds: Optional[int] = None) -> None:
    """Keep background_tasks_settings aligned when modified from legacy menus."""
    meta = _TASK_DEF_MAP.get(task_id)
    if not meta:
        return
    _, tasks_cfg = _get_store()
    entry = tasks_cfg.setdefault(task_id, {})
    if enabled is not None and not meta.get("essential"):
        entry["enabled"] = bool(enabled)
    if interval_seconds is not None:
        min_sec = int(meta.get("min_interval", 30))
        max_sec = int(meta.get("max_interval", 2592000))
        entry["interval_seconds"] = max(min_sec, min(max_sec, int(interval_seconds)))
    wake_task(task_id)


def request_task_run_now(task_id: str) -> None:
    if task_id in _TASK_DEF_MAP:
        _FORCE_RUN_TASKS.add(task_id)
        wake_task(task_id)


def is_force_run_requested(task_id: str) -> bool:
    return task_id in _FORCE_RUN_TASKS


def consume_force_run(task_id: str) -> bool:
    if task_id in _FORCE_RUN_TASKS:
        _FORCE_RUN_TASKS.discard(task_id)
        return True
    return False


async def sleep_interruptible(task_id: str, timeout_seconds: float) -> bool:
    """
    Sleep up to `timeout_seconds`, waking immediately if wake_task(task_id) is called.
    Returns True if woken early, False if timed out normally.
    """
    if timeout_seconds <= 0:
        return False
    ev = _get_wake_event(task_id)
    if ev.is_set():
        ev.clear()
        return True
    try:
        await asyncio.wait_for(ev.wait(), timeout=timeout_seconds)
        ev.clear()
        return True
    except asyncio.TimeoutError:
        return False


async def wait_until_task_enabled(task_id: str, poll_fallback: float = 3600.0) -> bool:
    """
    Suspend a disabled task using zero CPU until re-enabled or force-run.
    Leaves the force-run flag intact so the caller's consume_force_run() sees it.
    Returns True if woken via force-run, False if enabled normally.
    """
    while not is_task_enabled(task_id):
        if is_force_run_requested(task_id):
            return True
        await sleep_interruptible(task_id, poll_fallback)
        if is_force_run_requested(task_id):
            return True
    return False


def record_task_start(task_id: str) -> float:
    st = _TASK_RUNTIME.setdefault(task_id, {
        "run_count": 0,
        "running": False,
        "last_run_at": None,
        "last_duration_ms": None,
        "last_error": None,
    })
    st["running"] = True
    return time.monotonic()


def record_task_finish(task_id: str, started_mono: float, error: Optional[str] = None) -> None:
    elapsed_ms = int((time.monotonic() - started_mono) * 1000)
    st = _TASK_RUNTIME.setdefault(task_id, {})
    st["running"] = False
    st["run_count"] = int(st.get("run_count", 0)) + 1
    st["last_duration_ms"] = elapsed_ms
    try:
        from database import TEHRAN_TZ
        st["last_run_at"] = datetime.now(TEHRAN_TZ).strftime("%H:%M:%S")
    except Exception:
        st["last_run_at"] = datetime.now().strftime("%H:%M:%S")
    if error:
        st["last_error"] = str(error)[:120]
    else:
        st["last_error"] = None


def get_task_runtime(task_id: str) -> Dict[str, Any]:
    return dict(_TASK_RUNTIME.get(task_id, {
        "run_count": 0,
        "running": False,
        "last_run_at": None,
        "last_duration_ms": None,
        "last_error": None,
    }))


def format_interval_human(seconds: int, lang: str = "fa") -> str:
    sec = max(1, int(seconds))
    if lang == "en":
        if sec < 60:
            return f"{sec}s"
        if sec % 86400 == 0:
            return f"{sec // 86400}d"
        if sec >= 86400 and sec % 3600 == 0:
            days = sec // 86400
            rem_h = (sec % 86400) // 3600
            return f"{days}d {rem_h}h"
        if sec % 3600 == 0:
            return f"{sec // 3600}h"
        if sec >= 3600 and sec % 60 == 0:
            hrs = sec // 3600
            rem_m = (sec % 3600) // 60
            return f"{hrs}h {rem_m}m"
        if sec % 60 == 0:
            return f"{sec // 60}m"
        return f"{sec // 60}m {sec % 60}s"

    if sec < 60:
        return f"{sec} ثانیه"
    if sec % 86400 == 0:
        return f"{sec // 86400} روز"
    if sec >= 86400 and sec % 3600 == 0:
        days = sec // 86400
        rem_h = (sec % 86400) // 3600
        return f"{days} روز و {rem_h} ساعت"
    if sec % 3600 == 0:
        return f"{sec // 3600} ساعت"
    if sec >= 3600 and sec % 60 == 0:
        hrs = sec // 3600
        rem_m = (sec % 3600) // 60
        return f"{hrs} ساعت و {rem_m} دقیقه"
    if sec % 60 == 0:
        return f"{sec // 60} دقیقه"
    return f"{sec // 60} دقیقه و {sec % 60} ثانیه"

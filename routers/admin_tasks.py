"""
routers/admin_tasks.py
----------------------
پنل مدیریت وظایف پس‌زمینه (Task Manager) و پایش لحظه‌ای وضعیت سرور برای ادمین:
- نمایش تمامی تسک‌های پس‌زمینه با صفحه‌بندی
- امکان روشن/خاموش کردن تسک‌های اختیاری (برای تسک‌های ضروری دکمه خاموش نمایش داده نمی‌شود)
- تغییر بازه زمانی با دکمه‌های آماده یا ورود مقدار دلخواه
- اجرای دستی فوری هر تسک و بررسی لحظه‌ای وضعیت سرور و امنیت
"""

from __future__ import annotations

import html
import logging
import re
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core.task_manager import (
    format_interval_human,
    get_all_task_definitions,
    get_task_definition,
    get_task_interval,
    get_task_runtime,
    is_task_enabled,
    request_task_run_now,
    set_task_enabled,
    set_task_interval,
)
from services.server_guard import run_server_guard_check
from user_manager import get_user, user_states
from utils.filters import IsAdmin
from utils.guards import admin_only
from utils.helpers import safe_answer

logger = logging.getLogger(__name__)
router = Router()

bot: Optional[Bot] = None

TASKS_PER_PAGE = 8

_DIGIT_TRANS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TASK_BACK_TARGET: dict[int, str] = {}


def set_bot(bot_instance: Bot) -> None:
    global bot
    bot = bot_instance


def get_bot() -> Optional[Bot]:
    return bot


async def _safe_edit(callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        try:
            await callback.message.answer(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        except Exception as inner_e:
            logger.debug(f"Failed sending fallback message in admin_tasks: {inner_e}")


def _task_page_index(task_id: str) -> int:
    defs = get_all_task_definitions()
    for idx, d in enumerate(defs):
        if d["id"] == task_id:
            return idx // TASKS_PER_PAGE
    return 0


def parse_interval_input(raw_text: str) -> Optional[int]:
    """
    پارس ورودی بازه زمانی:
    - '45s' یا '45 ثانیه' -> 45 ثانیه
    - '10m' یا '10 دقیقه' یا عدد خالی '10' -> 10 دقیقه (600 ثانیه)
    - '2h' یا '2 ساعت' -> 2 ساعت (7200 ثانیه)
    - '1d' یا '1 روز' -> 1 روز (86400 ثانیه)
    """
    if not raw_text:
        return None
    cleaned = raw_text.strip().translate(_DIGIT_TRANS).lower()
    cleaned = re.sub(r"\s+", "", cleaned)

    match = re.fullmatch(r"(\d+(?:\.\d+)?)(s|sec|secs|second|seconds|ث|ثانیه|m|min|mins|minute|minutes|د|دقیقه|h|hr|hrs|hour|hours|س|ساعت|d|day|days|ر|روز)?", cleaned)
    if not match:
        return None

    try:
        val = float(match.group(1))
    except ValueError:
        return None
    if val <= 0:
        return None

    unit = match.group(2) or "m"
    if unit in ("s", "sec", "secs", "second", "seconds", "ث", "ثانیه"):
        mult = 1
    elif unit in ("h", "hr", "hrs", "hour", "hours", "س", "ساعت"):
        mult = 3600
    elif unit in ("d", "day", "days", "ر", "روز"):
        mult = 86400
    else:
        mult = 60

    seconds = int(round(val * mult))
    return seconds if seconds > 0 else None


def build_task_list_view(lang: str = "fa", page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    defs = get_all_task_definitions()
    total = len(defs)
    total_pages = max(1, (total + TASKS_PER_PAGE - 1) // TASKS_PER_PAGE)
    page = max(0, min(total_pages - 1, int(page)))

    essential_cnt = sum(1 for d in defs if d.get("essential"))
    active_cnt = sum(1 for d in defs if is_task_enabled(d["id"]))
    paused_cnt = total - active_cnt

    if lang == "en":
        text = (
            "⚙️ <b>Background Task Manager</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Total:</b> {total} | 🟢 <b>Active:</b> {active_cnt} | 🔴 <b>Paused:</b> {paused_cnt} | 🛡️ <b>Essential:</b> {essential_cnt}\n\n"
            "💡 On low-resource servers, slow down intervals or disable optional tasks to save CPU & RAM.\n"
            "🛡️ <b>Essential tasks</b> protect RAM/Disk/Security and cannot be turned off (only interval-tuned).\n\n"
            "Select a task to configure:"
        )
    else:
        text = (
            "⚙️ <b>مدیریت وظایف پس‌زمینه</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>کل وظایف:</b> {total} | 🟢 <b>فعال:</b> {active_cnt} | 🔴 <b>خاموش:</b> {paused_cnt} | 🛡️ <b>ضروری:</b> {essential_cnt}\n\n"
            "💡 اگر ربات روی سرور ضعیف اجرا می‌شود، بازه زمانی تسک‌ها را بیشتر کنید یا تسک‌های غیراضروری را خاموش کنید.\n"
            "🛡️ وظایف <b>ضروری</b> روی پایداری و امنیت ربات اثر مستقیم دارند و فقط بازه زمانی آن‌ها قابل تغییر است.\n\n"
            "برای مدیریت هر وظیفه روی آن کلیک کنید:"
        )

    start = page * TASKS_PER_PAGE
    end = min(total, start + TASKS_PER_PAGE)
    rows = []

    for meta in defs[start:end]:
        tid = meta["id"]
        essential = bool(meta.get("essential"))
        enabled = is_task_enabled(tid)
        interval = get_task_interval(tid)
        name = meta["name_en"] if lang == "en" else meta["name_fa"]

        if essential:
            badge = "🛡️"
            tail = format_interval_human(interval, lang)
        elif enabled:
            badge = "🟢"
            tail = format_interval_human(interval, lang)
        else:
            badge = "🔴"
            tail = "Off" if lang == "en" else "خاموش"

        rows.append([
            InlineKeyboardButton(
                text=f"{badge} {name} • {tail}",
                callback_data=f"task_mgr_view:{tid}",
            )
        ])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text="◀️ Prev" if lang == "en" else "◀️ قبلی",
                callback_data=f"task_mgr_page:{page - 1}",
            ))
        nav.append(InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data="task_mgr_noop",
        ))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(
                text="Next ▶️" if lang == "en" else "بعدی ▶️",
                callback_data=f"task_mgr_page:{page + 1}",
            ))
        rows.append(nav)

    rows.append([
        InlineKeyboardButton(
            text="🛡️ Live Server & Security Check" if lang == "en" else "🛡️ بررسی لحظه‌ای سرور و امنیت",
            callback_data="task_mgr_server_check",
            style="primary",
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text="🔙 Admin Panel" if lang == "en" else "🔙 بازگشت به پنل ادمین",
            callback_data="admin_panel",
            style="danger",
        )
    ])

    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def build_task_detail_view(
    task_id: str,
    lang: str = "fa",
    admin_id: Optional[int] = None,
) -> tuple[str, InlineKeyboardMarkup]:
    meta = get_task_definition(task_id)
    if not meta:
        return build_task_list_view(lang, 0)

    essential = bool(meta.get("essential"))
    enabled = is_task_enabled(task_id)
    interval = get_task_interval(task_id)
    min_sec = int(meta.get("min_interval", 30))
    max_sec = int(meta.get("max_interval", 2592000))
    rt = get_task_runtime(task_id)

    name = meta["name_en"] if lang == "en" else meta["name_fa"]
    desc = meta["desc_en"] if lang == "en" else meta["desc_fa"]
    impact = meta["impact_en"] if lang == "en" else meta["impact_fa"]
    interval_human = format_interval_human(interval, lang)
    min_human = format_interval_human(min_sec, lang)
    max_human = format_interval_human(max_sec, lang)

    if lang == "en":
        if essential:
            status_line = "🛡️ <b>Type:</b> Essential (Always active — disable button hidden for stability)"
        elif enabled:
            status_line = "🟢 <b>Status:</b> Active"
        else:
            status_line = "🔴 <b>Status:</b> Disabled (Zero CPU usage)"

        last_run = rt.get("last_run_at") or "Not yet"
        dur = f"{rt['last_duration_ms']}ms" if rt.get("last_duration_ms") is not None else "-"
        run_cnt = rt.get("run_count", 0)
        running_flag = " (Running now ⏳)" if rt.get("running") else ""
        err_line = f"\n⚠️ <b>Last Error:</b> <code>{html.escape(str(rt['last_error']))}</code>" if rt.get("last_error") else ""

        text = (
            f"{meta.get('icon', '⚙️')} <b>{html.escape(name)}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{status_line}\n"
            f"⏱ <b>Current Interval:</b> <code>{html.escape(interval_human)}</code> ({interval}s)\n"
            f"📏 <b>Allowed Range:</b> {html.escape(min_human)} – {html.escape(max_human)}\n"
            f"⚡ <b>Server Impact:</b> {html.escape(impact)}\n"
            f"📝 <b>Description:</b> {html.escape(desc)}\n\n"
            f"📈 <b>Runtime:</b> Runs: <code>{run_cnt}</code> | Last: <code>{html.escape(str(last_run))}</code> | Duration: <code>{dur}</code>{running_flag}"
            f"{err_line}\n\n"
            "👇 Choose a new interval or action:"
        )
    else:
        if essential:
            status_line = "🛡️ <b>نوع وظیفه:</b> ضروری و حیاتی (قابل خاموش کردن نیست؛ فقط بازه زمانی قابل تغییر است)"
        elif enabled:
            status_line = "🟢 <b>وضعیت:</b> روشن و فعال"
        else:
            status_line = "🔴 <b>وضعیت:</b> خاموش (بدون مصرف CPU و رم)"

        last_run = rt.get("last_run_at") or "هنوز اجرا نشده"
        dur = f"{rt['last_duration_ms']}ms" if rt.get("last_duration_ms") is not None else "-"
        run_cnt = rt.get("run_count", 0)
        running_flag = " (در حال اجرا ⏳)" if rt.get("running") else ""
        err_line = f"\n⚠️ <b>آخرین خطا:</b> <code>{html.escape(str(rt['last_error']))}</code>" if rt.get("last_error") else ""

        text = (
            f"{meta.get('icon', '⚙️')} <b>{html.escape(name)}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{status_line}\n"
            f"⏱ <b>بازه زمانی فعلی:</b> <code>{html.escape(interval_human)}</code> ({interval:,} ثانیه)\n"
            f"📏 <b>محدوده مجاز:</b> {html.escape(min_human)} تا {html.escape(max_human)}\n"
            f"⚡ <b>تأثیر روی پرفورمنس:</b> {html.escape(impact)}\n"
            f"📝 <b>توضیح:</b> {html.escape(desc)}\n\n"
            f"📈 <b>آمار اجرا:</b> تعداد: <code>{run_cnt}</code> | آخرین اجرا: <code>{html.escape(str(last_run))}</code> | زمان: <code>{dur}</code>{running_flag}"
            f"{err_line}\n\n"
            "👇 بازه زمانی مورد نظر را انتخاب کنید:"
        )

    rows = []

    # Crucial rule: NEVER show On/Off toggle button for essential tasks
    if not essential:
        if enabled:
            rows.append([
                InlineKeyboardButton(
                    text="🔴 Disable Task" if lang == "en" else "🔴 خاموش کردن وظیفه",
                    callback_data=f"task_mgr_toggle:{task_id}",
                    style="danger",
                )
            ])
        else:
            rows.append([
                InlineKeyboardButton(
                    text="🟢 Enable Task" if lang == "en" else "🟢 روشن کردن وظیفه",
                    callback_data=f"task_mgr_toggle:{task_id}",
                    style="success",
                )
            ])

    # Preset interval buttons (3 per row)
    presets = list(meta.get("presets") or [])
    preset_row = []
    for sec in presets:
        sec_int = int(sec)
        prefix = "✅ " if sec_int == interval else "⏱ "
        preset_row.append(
            InlineKeyboardButton(
                text=f"{prefix}{format_interval_human(sec_int, lang)}",
                callback_data=f"task_mgr_set:{task_id}:{sec_int}",
            )
        )
        if len(preset_row) == 3:
            rows.append(preset_row)
            preset_row = []
    if preset_row:
        rows.append(preset_row)

    rows.append([
        InlineKeyboardButton(
            text="✏️ Custom Interval" if lang == "en" else "✏️ بازه دلخواه",
            callback_data=f"task_mgr_custom:{task_id}",
        ),
        InlineKeyboardButton(
            text="▶️ Run Now" if lang == "en" else "▶️ اجرای دستی اکنون",
            callback_data=f"task_mgr_run:{task_id}",
            style="primary",
        ),
    ])

    page = _task_page_index(task_id)
    rows.append([
        InlineKeyboardButton(
            text="🔄 Refresh" if lang == "en" else "🔄 بروزرسانی",
            callback_data=f"task_mgr_view:{task_id}",
        ),
        InlineKeyboardButton(
            text="🔙 Task List" if lang == "en" else "🔙 لیست وظایف",
            callback_data=f"task_mgr_page:{page}",
        ),
    ])
    if admin_id and _TASK_BACK_TARGET.get(admin_id) == "admin_manage_backups":
        rows.append([
            InlineKeyboardButton(
                text="🔙 Back to Backup Manager" if lang == "en" else "🔙 بازگشت به مدیریت بکاپ‌ها",
                callback_data="admin_manage_backups",
                style="danger",
            )
        ])

    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin_task_manager")
@admin_only
async def admin_task_manager(callback: CallbackQuery):
    admin_id = callback.from_user.id
    user_states.pop(admin_id, None)
    _TASK_BACK_TARGET.pop(admin_id, None)
    lang = get_user(admin_id).get("lang", "fa")
    text, kb = build_task_list_view(lang, page=0)
    await _safe_edit(callback, text, kb)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("task_mgr_page:"))
@admin_only
async def task_mgr_page(callback: CallbackQuery):
    admin_id = callback.from_user.id
    user_states.pop(admin_id, None)
    _TASK_BACK_TARGET.pop(admin_id, None)
    lang = get_user(admin_id).get("lang", "fa")
    try:
        page = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        page = 0
    text, kb = build_task_list_view(lang, page=page)
    await _safe_edit(callback, text, kb)
    await safe_answer(callback)


@router.callback_query(F.data == "task_mgr_noop")
@admin_only
async def task_mgr_noop(callback: CallbackQuery):
    await safe_answer(callback)


@router.callback_query(F.data.startswith("task_mgr_view:"))
@admin_only
async def task_mgr_view(callback: CallbackQuery):
    admin_id = callback.from_user.id
    user_states.pop(admin_id, None)
    lang = get_user(admin_id).get("lang", "fa")
    parts = callback.data.split(":")
    task_id = parts[1] if len(parts) > 1 else ""
    src = parts[2] if len(parts) > 2 else ""
    if src == "backup":
        _TASK_BACK_TARGET[admin_id] = "admin_manage_backups"
    elif task_id != "auto_backup":
        _TASK_BACK_TARGET.pop(admin_id, None)
    text, kb = build_task_detail_view(task_id, lang, admin_id=admin_id)
    await _safe_edit(callback, text, kb)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("task_mgr_toggle:"))
@admin_only
async def task_mgr_toggle(callback: CallbackQuery):
    admin_id = callback.from_user.id
    user_states.pop(admin_id, None)
    lang = get_user(admin_id).get("lang", "fa")
    task_id = callback.data.split(":", 1)[1]
    meta = get_task_definition(task_id)
    if not meta:
        await safe_answer(callback, "Task not found" if lang == "en" else "وظیفه یافت نشد", alert=True)
        return

    if meta.get("essential"):
        msg = (
            "🛡️ Essential tasks cannot be disabled."
            if lang == "en"
            else "🛡️ این وظیفه ضروری است و برای پایداری سرور قابل خاموش کردن نیست."
        )
        await safe_answer(callback, msg, alert=True)
        text, kb = build_task_detail_view(task_id, lang, admin_id=admin_id)
        await _safe_edit(callback, text, kb)
        return

    new_enabled = not is_task_enabled(task_id)
    set_task_enabled(task_id, new_enabled)

    try:
        from services.background_tasks import get_log_system
        log_sys = get_log_system()
        if log_sys is not None:
            await log_sys.log_admin_action(
                admin_id,
                f"{'Enabled' if new_enabled else 'Disabled'} background task: {task_id}",
            )
    except Exception:
        pass

    toast = (
        ("🟢 Task enabled." if new_enabled else "🔴 Task disabled.")
        if lang == "en"
        else ("🟢 وظیفه روشن شد." if new_enabled else "🔴 وظیفه خاموش شد.")
    )
    await safe_answer(callback, toast, alert=True)
    text, kb = build_task_detail_view(task_id, lang, admin_id=admin_id)
    await _safe_edit(callback, text, kb)


@router.callback_query(F.data.startswith("task_mgr_set:"))
@admin_only
async def task_mgr_set(callback: CallbackQuery):
    admin_id = callback.from_user.id
    user_states.pop(admin_id, None)
    lang = get_user(admin_id).get("lang", "fa")
    parts = callback.data.split(":")
    if len(parts) < 3:
        await safe_answer(callback, "Invalid request" if lang == "en" else "درخواست نامعتبر", alert=True)
        return
    task_id = parts[1]
    try:
        requested = int(parts[2])
    except ValueError:
        await safe_answer(callback, "Invalid interval" if lang == "en" else "بازه نامعتبر", alert=True)
        return

    applied = set_task_interval(task_id, requested)
    if applied is None:
        await safe_answer(callback, "Task not found" if lang == "en" else "وظیفه یافت نشد", alert=True)
        return

    try:
        from services.background_tasks import get_log_system
        log_sys = get_log_system()
        if log_sys is not None:
            await log_sys.log_admin_action(
                admin_id,
                f"Changed task interval: {task_id} -> {applied}s",
            )
    except Exception:
        pass

    human = format_interval_human(applied, lang)
    toast = (
        f"✅ Interval set to {human}"
        if lang == "en"
        else f"✅ بازه زمانی روی {human} تنظیم شد"
    )
    await safe_answer(callback, toast, alert=True)
    text, kb = build_task_detail_view(task_id, lang, admin_id=admin_id)
    await _safe_edit(callback, text, kb)


@router.callback_query(F.data.startswith("task_mgr_run:"))
@admin_only
async def task_mgr_run(callback: CallbackQuery):
    admin_id = callback.from_user.id
    lang = get_user(admin_id).get("lang", "fa")
    task_id = callback.data.split(":", 1)[1]
    meta = get_task_definition(task_id)
    if not meta:
        await safe_answer(callback, "Task not found" if lang == "en" else "وظیفه یافت نشد", alert=True)
        return

    request_task_run_now(task_id)
    toast = (
        "▶️ Immediate execution triggered!"
        if lang == "en"
        else "▶️ اجرای فوری وظیفه زمان‌بندی شد و تا لحظاتی دیگر انجام می‌شود."
    )
    await safe_answer(callback, toast, alert=True)
    text, kb = build_task_detail_view(task_id, lang, admin_id=admin_id)
    await _safe_edit(callback, text, kb)


@router.callback_query(F.data.startswith("task_mgr_custom:"))
@admin_only
async def task_mgr_custom(callback: CallbackQuery):
    admin_id = callback.from_user.id
    lang = get_user(admin_id).get("lang", "fa")
    task_id = callback.data.split(":", 1)[1]
    meta = get_task_definition(task_id)
    if not meta:
        await safe_answer(callback, "Task not found" if lang == "en" else "وظیفه یافت نشد", alert=True)
        return

    min_human = format_interval_human(int(meta.get("min_interval", 30)), lang)
    max_human = format_interval_human(int(meta.get("max_interval", 2592000)), lang)
    name = meta["name_en"] if lang == "en" else meta["name_fa"]

    user_states[admin_id] = {
        "awaiting_task_interval": True,
        "task_id": task_id,
    }

    if lang == "en":
        prompt = (
            f"✏️ <b>Custom Interval for:</b> {html.escape(name)}\n"
            f"📏 <b>Allowed Range:</b> {html.escape(min_human)} to {html.escape(max_human)}\n\n"
            "Send your desired interval, e.g.:\n"
            "• <code>45s</code> (seconds)\n"
            "• <code>15m</code> or just <code>15</code> (minutes)\n"
            "• <code>2h</code> (hours)\n"
            "• <code>1d</code> (days)\n\n"
            "Send /cancel to abort."
        )
    else:
        prompt = (
            f"✏️ <b>تعیین بازه دلخواه برای:</b> {html.escape(name)}\n"
            f"📏 <b>بازه مجاز:</b> {html.escape(min_human)} تا {html.escape(max_human)}\n\n"
            "لطفاً مقدار بازه جدید را ارسال کنید، مثال:\n"
            "• <code>45s</code> (۴۵ ثانیه)\n"
            "• <code>15m</code> یا عدد خالی <code>15</code> (۱۵ دقیقه)\n"
            "• <code>2h</code> (۲ ساعت)\n"
            "• <code>1d</code> (۱ روز)\n\n"
            "برای لغو /cancel را بفرستید."
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="❌ Cancel" if lang == "en" else "❌ لغو",
            callback_data=f"task_mgr_view:{task_id}",
            style="danger",
        )
    ]])
    await _safe_edit(callback, prompt, kb)
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: bool(user_states.get(m.from_user.id, {}).get("awaiting_task_interval")))
async def handle_custom_task_interval(message: Message):
    admin_id = message.from_user.id
    state = user_states.get(admin_id) or {}
    task_id = state.get("task_id")
    lang = get_user(admin_id).get("lang", "fa")

    raw = (message.text or "").strip()
    if raw.lower() in ("/cancel", "cancel", "لغو", "❌ لغو"):
        user_states.pop(admin_id, None)
        text, kb = build_task_detail_view(task_id or "", lang, admin_id=admin_id)
        await message.reply(
            ("❌ Cancelled.\n\n" if lang == "en" else "❌ ویرایش بازه لغو شد.\n\n") + text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
        return

    seconds = parse_interval_input(raw)
    if seconds is None:
        await message.reply(
            "⚠️ Invalid format! Examples: <code>45s</code>, <code>10m</code>, <code>2h</code>, <code>1d</code> or /cancel"
            if lang == "en"
            else "⚠️ فرمت نامعتبر است! مثال: <code>45s</code> یا <code>10m</code> یا <code>2h</code> یا <code>1d</code> (یا /cancel)",
            parse_mode=ParseMode.HTML,
        )
        return

    meta = get_task_definition(task_id or "")
    if not meta:
        user_states.pop(admin_id, None)
        return

    user_states.pop(admin_id, None)
    applied = set_task_interval(task_id, seconds)
    if applied is None:
        return

    try:
        from services.background_tasks import get_log_system
        log_sys = get_log_system()
        if log_sys is not None:
            await log_sys.log_admin_action(
                admin_id,
                f"Set custom task interval: {task_id} -> {applied}s",
            )
    except Exception:
        pass

    human = format_interval_human(applied, lang)
    note = ""
    if applied != seconds:
        req_human = format_interval_human(seconds, lang)
        note = (
            f"ℹ️ Clamped from {html.escape(req_human)} to allowed range.\n\n"
            if lang == "en"
            else f"ℹ️ مقدار <code>{html.escape(req_human)}</code> به محدوده مجاز ({html.escape(human)}) تنظیم شد.\n\n"
        )
    else:
        note = (
            f"✅ Interval saved: <b>{html.escape(human)}</b>\n\n"
            if lang == "en"
            else f"✅ بازه زمانی جدید ذخیره شد: <b>{html.escape(human)}</b>\n\n"
        )

    text, kb = build_task_detail_view(task_id, lang, admin_id=admin_id)
    await message.reply(note + text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "task_mgr_server_check")
@admin_only
async def task_mgr_server_check(callback: CallbackQuery):
    admin_id = callback.from_user.id
    lang = get_user(admin_id).get("lang", "fa")

    try:
        res = await run_server_guard_check(bot=get_bot(), force_summary=True)
        m = res["metrics"]
        p = res["panel"]
        net = m["network"]
        issues_cnt = res.get("issues_count", 0)

        if p.get("enabled") and p.get("ok"):
            panel_txt = f"🟢 OK ({p['latency_ms']}ms)"
        elif not p.get("enabled"):
            panel_txt = "🔴 OFF" if lang == "en" else "🔴 غیرفعال"
        else:
            panel_txt = f"🔴 {p.get('error')}"

        top_ips_lines = []
        for idx, item in enumerate((net.get("top_ips") or [])[:5], 1):
            if lang == "en":
                top_ips_lines.append(
                    f"  {idx}. <code>{html.escape(item['ip'])}</code> — {item['count']} conns (SYN: {item['syn']})"
                )
            else:
                top_ips_lines.append(
                    f"  \u200F{idx}. \u200E<code>{html.escape(item['ip'])}</code> — {item['count']} اتصال (SYN: {item['syn']})"
                )
        top_ips_block = "\n".join(top_ips_lines) if top_ips_lines else ("  • None" if lang == "en" else "  • مورد مشکوکی ثبت نشده")

        nginx = m.get("nginx")
        nginx_block = ""
        if nginx and nginx.get("hot_ips"):
            if lang == "en":
                nginx_lines = [
                    f"  • <code>{html.escape(h['ip'])}</code>: {h['count']} reqs (<code>{html.escape(h['top_path'])}</code>)"
                    for h in nginx["hot_ips"]
                ]
                nginx_block = "\n🌐 <b>Nginx Hot IPs (90s):</b>\n" + "\n".join(nginx_lines) + "\n"
            else:
                nginx_lines = [
                    f"  \u200F• \u200E<code>{html.escape(h['ip'])}</code>: {h['count']} درخواست (<code>{html.escape(h['top_path'])}</code>)"
                    for h in nginx["hot_ips"]
                ]
                nginx_block = "\n🌐 <b>آی‌پی‌های پرترافیک Nginx (۹۰ ثانیه):</b>\n" + "\n".join(nginx_lines) + "\n"

        if lang == "en":
            text = (
                "🛡️ <b>Live Server & Security Snapshot</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🖥 <b>CPU:</b> <code>{m['cpu_percent']:.1f}%</code> | Load: <code>{m['load1']}</code> ({m['cpu_count']} cores)\n"
                f"🧠 <b>RAM:</b> <code>{m['ram_used_gb']:.2f}/{m['ram_total_gb']:.2f} GB ({m['ram_percent']:.1f}%)</code>\n"
                f"🤖 <b>Bot RSS:</b> <code>{m['bot_rss_mb']:.1f} MB</code> | Free RAM: <code>{m['ram_avail_mb']:.0f} MB</code>\n"
                f"💽 <b>Disk:</b> <code>{m['disk_free_gb']:.2f}/{m['disk_total_gb']:.1f} GB free ({m['disk_percent']:.1f}% used)</code>\n"
                f"🔌 <b>3X-UI Panel:</b> <code>{html.escape(str(panel_txt))}</code>\n"
                f"🌐 <b>TCP Conns:</b> <code>{net.get('total_conns', 0)}</code> | <b>SYN_RECV:</b> <code>{net.get('total_syn', 0)}</code>\n"
                f"⚠️ <b>Active Issues:</b> <code>{issues_cnt}</code>\n\n"
                f"🔍 <b>Top External IPs:</b>\n{top_ips_block}\n"
                f"{nginx_block}\n"
                "📋 English report sent to Log Bot (admin @username is tagged only on critical issues)."
            )
        else:
            RLM = "\u200F"
            text = (
                "🛡️ <b>وضعیت لحظه‌ای سرور و امنیت</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{RLM}🖥 <b>مصرف CPU:</b> <code>{m['cpu_percent']:.1f}%</code> | لود: <code>{m['load1']}</code> ({m['cpu_count']} هسته)\n"
                f"🧠 <b>رم سرور:</b> <code>{m['ram_used_gb']:.2f}/{m['ram_total_gb']:.2f} GB ({m['ram_percent']:.1f}%)</code>\n"
                f"🤖 <b>رم ربات:</b> <code>{m['bot_rss_mb']:.1f} MB</code> | آزاد: <code>{m['ram_avail_mb']:.0f} MB</code>\n"
                f"💽 <b>دیسک:</b> <code>{m['disk_free_gb']:.2f}/{m['disk_total_gb']:.1f} GB آزاد ({m['disk_percent']:.1f}% پر)</code>\n"
                f"🔌 <b>پنل 3X-UI:</b> <code>{html.escape(str(panel_txt))}</code>\n"
                f"🌐 <b>اتصالات TCP:</b> <code>{net.get('total_conns', 0)}</code> | <b>SYN_RECV:</b> <code>{net.get('total_syn', 0)}</code>\n"
                f"⚠️ <b>مشکلات فعال:</b> <code>{issues_cnt}</code>\n\n"
                f"🔍 <b>پرمصرف‌ترین IPهای خارجی:</b>\n{top_ips_block}\n"
                f"{nginx_block}\n"
                "📋 این گزارش به بات لاگ ارسال شد (تگ \u200E@username\u200F ادمین فقط در مشکلات واقعی انجام می‌شود)."
            )
    except Exception as e:
        logger.error(f"Error in manual server guard check: {e}", exc_info=True)
        err_lbl = "❌ Error:" if lang == "en" else "❌ خطا:"
        text = f"{err_lbl} <code>{html.escape(str(e))}</code>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔄 Check Again" if lang == "en" else "🔄 بررسی مجدد",
                callback_data="task_mgr_server_check",
                style="primary",
            ),
            InlineKeyboardButton(
                text="🔙 Task List" if lang == "en" else "🔙 لیست وظایف",
                callback_data="admin_task_manager",
            ),
        ]
    ])
    await _safe_edit(callback, text, kb)
    await safe_answer(callback)

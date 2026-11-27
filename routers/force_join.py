"""
routers/force_join.py
---------------------
مدیریت عضویت اجباری کاربران در کانال‌های تلگرام (Force Join)
شامل تنظیمات ادمین، بررسی عضویت، تایید عضویت و نمایش صفحه عضویت
"""

import html
import logging
import re
import time
from typing import Optional, List, Dict, Any

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.enums import ParseMode
from aiogram import Bot

from config import ADMIN_ID
from database import users, configs_pool, save_all, now_tehran_iso
from db_storage import save_json, DB_FILES
from core.save_scheduler import schedule_save, schedule_file_save
from user_manager import user_states, get_user, get_admin_id_int
from strings import t
from emoji_sticker_system import premium_emoji
from utils.filters import IsAdmin
from utils.guards import admin_only
from utils.helpers import safe_answer

logger = logging.getLogger(__name__)

router = Router(name="force_join")

_bot: Optional[Bot] = None


def set_bot(b: Bot):
    """تنظیم شیء Bot برای استفاده در توابع مستقل از هندلر"""
    global _bot
    _bot = b


def get_bot() -> Optional[Bot]:
    """دریافت شیء Bot فعال"""
    global _bot
    if _bot is not None:
        return _bot
    try:
        return Bot.get_current()
    except Exception:
        pass
    try:
        import main
        return getattr(main, "bot", None)
    except Exception:
        return None


def _get_admin_id() -> int:
    try:
        aid = get_admin_id_int()
        if aid:
            return aid
    except Exception:
        pass
    try:
        return int(ADMIN_ID)
    except Exception:
        return 0


def _get_main_keyboard(is_admin: bool = False, lang: str = "fa", user_id: Optional[int] = None):
    try:
        import main
        return main.get_main_keyboard(is_admin, lang, user_id)
    except Exception:
        return None


def _get_log_system():
    try:
        import main
        return getattr(main, "log_system", None)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Handlers: ادمین — تنظیمات عضویت اجباری
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_force_join")
@admin_only
async def admin_force_join_settings(callback: CallbackQuery):
    """تنظیمات عضویت اجباری در کانال"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    settings = configs_pool.get('force_join_settings', {})
    enabled = settings.get('enabled', False)
    channels = settings.get('channels', [])
    
    status_text = t('i18n_status_active', lang) if enabled else t('i18n_status_inactive', lang)

    opt = settings.get('optional_channel', {}) or {}
    opt_status = (
        f"🟢 {opt.get('title') or opt.get('url', '-')}"
        if opt.get('enabled') and opt.get('url')
        else ("🔴 غیرفعال" if lang == "fa" else "🔴 Inactive")
    )

    if lang == "fa":
        text = t('b_force_join_channels_b_stat_11f9df3575', lang, fa_parts=lambda: (f'{status_text}', f'{len(channels)}'))
        for ch in channels:
            ch_line = f"• {ch.get('name', ch.get('id'))} (`{ch.get('id')}`)"
            custom_parts = []
            if ch.get('title_fa'):
                custom_parts.append(f"FA: {ch['title_fa']}")
            if ch.get('title_en'):
                custom_parts.append(f"EN: {ch['title_en']}")
            if custom_parts:
                ch_line += f" [{', '.join(custom_parts)}]"
            text += ch_line + "\n"
        
        if not channels:
            text += t('no_channels_registered_e17f438d71', lang)
        
        text += t('users_must_join_all_above_ch_880bcba8c2', lang)
        text += t('after_joining_click_the_veri_963c4ada02', lang)
        text += f"\n📣 کانال اختیاری: {opt_status}\n"
        
        buttons = [
            [InlineKeyboardButton(text=t('enable_disable_d7aad0bd90', lang), callback_data="force_join_toggle")],
            [InlineKeyboardButton(text=t('add_channel_c1ed5f0e64', lang), callback_data="force_join_add")],
            [InlineKeyboardButton(text=t('remove_channel_6636beb744', lang), callback_data="force_join_remove")],
            [InlineKeyboardButton(text=t('force_join_edit_titles_btn', lang), callback_data="force_join_titles")],
            [InlineKeyboardButton(text=t('force_join_optional_btn', lang), callback_data="force_join_optional_menu", style="primary")],
            [InlineKeyboardButton(text=t('check_my_membership_ce061badb3', lang), callback_data="force_join_check")],
            [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
        ]
    else:
        text = t('b_force_join_channels_b_stat_11f9df3575', lang, en_parts=lambda: (f'{status_text}', f'{len(channels)}'))
        for ch in channels:
            ch_line = f"• {ch.get('name', ch.get('id'))} (`{ch.get('id')}`)"
            custom_parts = []
            if ch.get('title_fa'):
                custom_parts.append(f"FA: {ch['title_fa']}")
            if ch.get('title_en'):
                custom_parts.append(f"EN: {ch['title_en']}")
            if custom_parts:
                ch_line += f" [{', '.join(custom_parts)}]"
            text += ch_line + "\n"
        
        if not channels:
            text += t('no_channels_registered_e17f438d71', lang)
        
        text += t('users_must_join_all_above_ch_880bcba8c2', lang)
        text += t('after_joining_click_the_veri_963c4ada02', lang)
        text += f"\n📣 Optional Channel: {opt_status}\n"
        
        buttons = [
            [InlineKeyboardButton(text=t('enable_disable_d7aad0bd90', lang), callback_data="force_join_toggle")],
            [InlineKeyboardButton(text=t('add_channel_c1ed5f0e64', lang), callback_data="force_join_add")],
            [InlineKeyboardButton(text=t('remove_channel_6636beb744', lang), callback_data="force_join_remove")],
            [InlineKeyboardButton(text=t('force_join_edit_titles_btn', lang), callback_data="force_join_titles")],
            [InlineKeyboardButton(text=t('force_join_optional_btn', lang), callback_data="force_join_optional_menu", style="primary")],
            [InlineKeyboardButton(text=t('check_my_membership_ce061badb3', lang), callback_data="force_join_check")],
            [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
        ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


_OPT_STYLE_LABELS = {
    None: ("پیش‌فرض", "Default"),
    "primary": ("🔵 آبی", "🔵 Blue"),
    "success": ("🟢 سبز", "🟢 Green"),
    "danger": ("🔴 قرمز", "🔴 Red"),
}

_OPT_MEMBER_CACHE: Dict[int, tuple] = {}
_OPT_MEMBER_CACHE_TTL = 45.0


def _set_opt_member_cache(user_id: int, now_ts: float, is_joined: bool) -> None:
    if len(_OPT_MEMBER_CACHE) >= 2000:
        expired = [
            uid for uid, (ts, _) in _OPT_MEMBER_CACHE.items()
            if (now_ts - ts) >= _OPT_MEMBER_CACHE_TTL
        ]
        for uid in expired:
            _OPT_MEMBER_CACHE.pop(uid, None)
        if len(_OPT_MEMBER_CACHE) >= 2000:
            for uid in list(_OPT_MEMBER_CACHE.keys())[:len(_OPT_MEMBER_CACHE) - 1500]:
                _OPT_MEMBER_CACHE.pop(uid, None)
    _OPT_MEMBER_CACHE[user_id] = (now_ts, is_joined)


def _strip_join_prefix(raw: str) -> str:
    cleaned = (raw or "").strip()
    cleaned = re.sub(r'^[\U0001F300-\U0001FAFF\u2600-\u27BF]+\s*', '', cleaned).strip()
    cleaned = re.sub(r'^(?:عضویت\s+در\s+کانال|عضویت\s+در|Join\s+Channel|Join)\s*', '', cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _format_force_join_button_label(ch: dict, lang: str) -> str:
    raw_custom = (ch.get('title_fa' if lang == 'fa' else 'title_en') or '').strip()
    if raw_custom:
        if ord(raw_custom[0]) > 0x2000:
            return raw_custom
        lower = raw_custom.lower()
        if raw_custom.startswith('عضویت') or lower.startswith('join '):
            return f"📢 {raw_custom}"
        return f"📢 عضویت در {raw_custom}" if lang == "fa" else f"📢 Join {raw_custom}"
    channel_name = ch.get('name', 'کانال' if lang == 'fa' else 'Channel')
    return f"📢 عضویت در {channel_name}" if lang == "fa" else f"📢 Join {channel_name}"


def _extract_public_chat_ref(url: Optional[str]) -> Optional[str]:
    if not url or not isinstance(url, str):
        return None
    cleaned = url.strip()
    m = re.match(r'^https?://t\.me/([A-Za-z0-9_]{4,})(?:[/?].*)?$', cleaned)
    if not m:
        return None
    slug = m.group(1)
    if slug.lower() in ('joinchat', 'c', 's'):
        return None
    return f"@{slug}"


def _ensure_opt_emoji(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned
    if ord(cleaned[0]) > 0x2000:
        return cleaned
    return f"📣 {cleaned}"


def _resolve_optional_channel_name_only(opt: dict, lang: str) -> str:
    raw_name = (opt.get('name_fa' if lang == 'fa' else 'name_en') or '').strip()
    if raw_name:
        return _ensure_opt_emoji(raw_name)

    raw_title = (
        opt.get('title_fa' if lang == 'fa' else 'title_en')
        or opt.get('title')
        or ''
    ).strip()
    if raw_title and raw_title not in ("📣 Join Channel", "📣 عضویت در کانال"):
        stripped = _strip_join_prefix(raw_title)
        if stripped and stripped not in ("کانال", "Channel"):
            return _ensure_opt_emoji(stripped)

    chat_title = (opt.get('chat_title') or '').strip()
    if chat_title:
        return _ensure_opt_emoji(chat_title)
    return "📣 کانال ما" if lang == "fa" else "📣 Our Channel"


def _resolve_optional_channel_title(opt: dict, lang: str, joined_or_forced: bool = False) -> str:
    if joined_or_forced:
        return _resolve_optional_channel_name_only(opt, lang)

    raw = (
        opt.get('title_fa' if lang == 'fa' else 'title_en')
        or opt.get('title')
        or ''
    ).strip()
    if raw and raw not in ("📣 Join Channel", "📣 عضویت در کانال"):
        return _ensure_opt_emoji(raw)

    raw_name = (opt.get('name_fa' if lang == 'fa' else 'name_en') or '').strip()
    if raw_name:
        plain = _strip_join_prefix(raw_name) or raw_name
        return f"📣 عضویت در {plain}" if lang == "fa" else f"📣 Join {plain}"

    return "📣 عضویت در کانال" if lang == "fa" else "📣 Join Channel"


async def refresh_optional_channel_membership(user_id: int, force: bool = False) -> bool:
    """بی‌صدا وضعیت عضویت کاربر در کانال اختیاری را بررسی و ذخیره می‌کند (بدون هیچ پیامی)."""
    if not user_id:
        return False
    settings = configs_pool.get('force_join_settings', {}) or {}
    opt = settings.get('optional_channel', {}) or {}
    if not (opt.get('enabled') and opt.get('url')):
        return False

    now_ts = time.time()
    cached = _OPT_MEMBER_CACHE.get(user_id)
    if not force and cached and (now_ts - cached[0]) < _OPT_MEMBER_CACHE_TTL:
        return cached[1]

    chat_ref = opt.get('chat_id') or opt.get('chat_ref') or _extract_public_chat_ref(opt.get('url'))
    uid = str(user_id)
    prev_joined = bool((users.get(uid) or {}).get('optional_channel_joined', False))
    if not chat_ref:
        _set_opt_member_cache(user_id, now_ts, prev_joined)
        return prev_joined

    bot_inst = get_bot()
    if not bot_inst:
        return prev_joined

    try:
        member = await bot_inst.get_chat_member(chat_id=chat_ref, user_id=user_id)
        is_joined = member.status in ('member', 'administrator', 'creator')
        _set_opt_member_cache(user_id, now_ts, is_joined)
        if uid in users and bool(users[uid].get('optional_channel_joined', False)) != is_joined:
            users[uid]['optional_channel_joined'] = is_joined
            users[uid]['updated_at'] = now_tehran_iso()
            schedule_file_save('users', delay=1.0)
        return is_joined
    except Exception as e:
        logger.debug(f"Optional channel silent check failed for user {user_id} ({chat_ref}): {e}")
        _set_opt_member_cache(user_id, now_ts, prev_joined)
        return prev_joined


async def _render_optional_channel_menu(target, lang: str, is_edit: bool = True):
    settings = configs_pool.setdefault('force_join_settings', {})
    opt = settings.setdefault('optional_channel', {})
    enabled = bool(opt.get('enabled', False)) and bool(opt.get('url'))
    status_str = t('i18n_status_active', lang) if enabled else t('i18n_status_inactive', lang)
    join_preview = _resolve_optional_channel_title(opt, lang, joined_or_forced=False) if opt.get('url') else "-"
    joined_preview = _resolve_optional_channel_title(opt, lang, joined_or_forced=True) if opt.get('url') else "-"
    ch_str = (
        f"<a href=\"{html.escape(opt.get('url', ''))}\">{html.escape(join_preview)}</a>"
        if opt.get('url')
        else ("ثبت نشده" if lang == "fa" else "Not set")
    )
    cur_style = opt.get('style')
    if cur_style not in _OPT_STYLE_LABELS:
        cur_style = None
    style_lbl = _OPT_STYLE_LABELS[cur_style][0 if lang == "fa" else 1]

    text = t(
        'force_join_optional_menu_title',
        lang,
        fa_parts=lambda: (status_str, ch_str, style_lbl),
        en_parts=lambda: (status_str, ch_str, style_lbl),
    )
    if opt.get('url'):
        if lang == "fa":
            text += (
                f"\n\n👀 <b>پیش‌نمایش دکمه:</b>\n"
                f"• قبل عضویت: <code>{html.escape(join_preview)}</code>\n"
                f"• بعد عضویت / با عضویت اجباری: <code>{html.escape(joined_preview)}</code>"
            )
        else:
            text += (
                f"\n\n👀 <b>Button Preview:</b>\n"
                f"• Before join: <code>{html.escape(join_preview)}</code>\n"
                f"• After join / with Force-Join: <code>{html.escape(joined_preview)}</code>"
            )

    color_row = [
        InlineKeyboardButton(
            text=f"{'✅ ' if cur_style == st else ''}{lbls[0 if lang == 'fa' else 1]}",
            callback_data=f"force_join_optional_style:{st or 'default'}",
            style=st,
        )
        for st, lbls in _OPT_STYLE_LABELS.items()
    ]
    buttons = [
        [InlineKeyboardButton(
            text=t('enable_disable_d7aad0bd90', lang),
            callback_data="force_join_optional_toggle",
            style="danger" if enabled else "success",
        )],
        [InlineKeyboardButton(
            text=t('force_join_optional_set_btn', lang),
            callback_data="force_join_optional_set",
            style="primary",
        )],
    ]
    if opt.get('url'):
        buttons.append([
            InlineKeyboardButton(
                text=t('force_join_opt_title_fa_btn', lang),
                callback_data="force_join_optional_field:title_fa",
            ),
            InlineKeyboardButton(
                text=t('force_join_opt_title_en_btn', lang),
                callback_data="force_join_optional_field:title_en",
            ),
        ])
        buttons.append([
            InlineKeyboardButton(
                text=t('force_join_opt_name_fa_btn', lang),
                callback_data="force_join_optional_field:name_fa",
            ),
            InlineKeyboardButton(
                text=t('force_join_opt_name_en_btn', lang),
                callback_data="force_join_optional_field:name_en",
            ),
        ])
    buttons.append(color_row)
    if opt.get('url'):
        buttons.append([InlineKeyboardButton(
            text=t('force_join_optional_remove_btn', lang),
            callback_data="force_join_optional_remove",
            style="danger",
        )])
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_force_join",
    )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if is_edit:
        await target.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        await target.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@router.callback_query(F.data == "force_join_optional_menu")
@admin_only
async def force_join_optional_menu(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    await _render_optional_channel_menu(callback.message, lang, is_edit=True)
    await safe_answer(callback)


@router.callback_query(F.data == "force_join_optional_toggle")
@admin_only
async def force_join_optional_toggle(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    settings = configs_pool.setdefault('force_join_settings', {})
    opt = settings.setdefault('optional_channel', {})
    if not opt.get('url'):
        await safe_answer(callback, t('force_join_optional_need_channel', lang), alert=True)
        return
    opt['enabled'] = not opt.get('enabled', False)
    _OPT_MEMBER_CACHE.clear()
    settings['last_updated'] = now_tehran_iso()
    schedule_save(2.0)
    await _render_optional_channel_menu(callback.message, lang, is_edit=True)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("force_join_optional_style:"))
@admin_only
async def force_join_optional_style(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    chosen = callback.data.split(":", 1)[1]
    style_val = None if chosen == "default" else chosen
    if style_val not in (None, "primary", "success", "danger"):
        style_val = None
    settings = configs_pool.setdefault('force_join_settings', {})
    opt = settings.setdefault('optional_channel', {})
    opt['style'] = style_val
    settings['last_updated'] = now_tehran_iso()
    schedule_save(2.0)
    await _render_optional_channel_menu(callback.message, lang, is_edit=True)
    await safe_answer(callback)


@router.callback_query(F.data == "force_join_optional_remove")
@admin_only
async def force_join_optional_remove(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    settings = configs_pool.setdefault('force_join_settings', {})
    settings.pop('optional_channel', None)
    _OPT_MEMBER_CACHE.clear()
    settings['last_updated'] = now_tehran_iso()
    schedule_save(2.0)
    await safe_answer(callback, t('force_join_optional_removed', lang), alert=True)
    await _render_optional_channel_menu(callback.message, lang, is_edit=True)


@router.callback_query(F.data == "force_join_optional_set")
@admin_only
async def force_join_optional_set_start(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    user_states[callback.from_user.id] = {'awaiting_optional_channel': True}
    await callback.message.answer(t('force_join_optional_set_prompt', lang), parse_mode=ParseMode.HTML)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("force_join_optional_field:"))
@admin_only
async def force_join_optional_field_start(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    field_key = callback.data.split(":", 1)[1]
    if field_key not in ("title_fa", "title_en", "name_fa", "name_en"):
        await safe_answer(callback)
        return
    user_states[callback.from_user.id] = {'awaiting_optional_field': field_key}
    prompt_key = (
        'force_join_opt_title_prompt'
        if field_key.startswith('title_')
        else 'force_join_opt_name_prompt'
    )
    field_label = {
        'title_fa': ('تایتل عضویت فارسی', 'Persian Join Title'),
        'title_en': ('تایتل عضویت انگلیسی', 'English Join Title'),
        'name_fa': ('اسم کانال فارسی', 'Persian Channel Name'),
        'name_en': ('اسم کانال انگلیسی', 'English Channel Name'),
    }[field_key][0 if lang == 'fa' else 1]
    await callback.message.answer(
        t(prompt_key, lang, fa_parts=lambda: (field_label,), en_parts=lambda: (field_label,)),
        parse_mode=ParseMode.HTML,
    )
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: bool(user_states.get(m.from_user.id, {}).get('awaiting_optional_field')))
async def force_join_optional_field_save(message: Message):
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    raw = (message.text or "").strip()
    field_key = user_states.get(admin_id, {}).get('awaiting_optional_field')
    if raw == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_8a3eb8aae6', lang))
        return
    if not raw or field_key not in ("title_fa", "title_en", "name_fa", "name_en"):
        user_states.pop(admin_id, None)
        return
    settings = configs_pool.setdefault('force_join_settings', {})
    opt = settings.setdefault('optional_channel', {})
    cleaned = "" if raw in ("-", "clear", "پاک") else raw[:48]
    opt[field_key] = cleaned
    if field_key == 'title_fa' and cleaned:
        opt['title'] = cleaned
    settings['last_updated'] = now_tehran_iso()
    schedule_save(2.0)
    user_states.pop(admin_id, None)
    await message.reply(t('force_join_opt_field_saved', lang))
    await _render_optional_channel_menu(message, lang, is_edit=False)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_optional_channel'))
async def force_join_optional_set_save(message: Message):
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    raw = (message.text or "").strip()
    if raw == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_8a3eb8aae6', lang))
        return

    custom_title = None
    explicit_chat_id = None
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) >= 3 and parts[0] and parts[1].lstrip('-').isdigit() and parts[2]:
        custom_title = parts[0][:48]
        explicit_chat_id = int(parts[1])
        target_ref = parts[2]
    elif len(parts) == 2 and parts[0] and parts[1]:
        if parts[0].lstrip('-').isdigit():
            explicit_chat_id = int(parts[0])
        else:
            custom_title = parts[0][:48]
        target_ref = parts[1]
    else:
        target_ref = raw

    url = None
    title = custom_title
    chat_ref = None
    chat_id = explicit_chat_id
    chat_title = None
    bot_inst = message.bot or get_bot()

    if target_ref.startswith('@'):
        uname = target_ref.lstrip('@').strip()
        if not uname:
            await message.reply(t('force_join_optional_invalid_link', lang))
            return
        url = f"https://t.me/{uname}"
        chat_ref = f"@{uname}"
    elif target_ref.startswith('https://t.me/') or target_ref.startswith('http://t.me/'):
        url = target_ref.replace('http://t.me/', 'https://t.me/', 1)
        chat_ref = _extract_public_chat_ref(url)
    elif target_ref.startswith('t.me/'):
        url = f"https://{target_ref}"
        chat_ref = _extract_public_chat_ref(url)
    else:
        await message.reply(t('force_join_optional_invalid_link', lang))
        return

    if bot_inst and (chat_id or chat_ref):
        try:
            chat = await bot_inst.get_chat(chat_id or chat_ref)
            chat_id = chat.id
            chat_title = (chat.title or chat_ref or "")[:48]
        except Exception:
            pass

    settings = configs_pool.setdefault('force_join_settings', {})
    prev_opt = settings.get('optional_channel', {}) or {}
    name_val = ""
    if title:
        stripped = _strip_join_prefix(title)
        if stripped and stripped != title.strip():
            title_fa = title
            title_en = title
            name_val = stripped
        else:
            name_val = title
            title_fa = f"📣 عضویت در {name_val}"
            title_en = f"📣 Join {name_val}"
    else:
        title_fa = "📣 عضویت در کانال"
        title_en = "📣 Join Channel"
        name_val = chat_title or ""

    display_title = title_fa if lang == "fa" else title_en
    settings['optional_channel'] = {
        'enabled': True,
        'title': display_title,
        'title_fa': title_fa,
        'title_en': title_en,
        'name_fa': name_val,
        'name_en': name_val,
        'chat_id': chat_id,
        'chat_ref': chat_ref,
        'chat_title': chat_title or name_val,
        'url': url,
        'style': prev_opt.get('style', 'primary'),
    }
    _OPT_MEMBER_CACHE.clear()
    settings['last_updated'] = now_tehran_iso()
    schedule_save(2.0)
    user_states.pop(admin_id, None)

    await message.reply(t('force_join_optional_saved', lang, fa_parts=lambda: (display_title,), en_parts=lambda: (display_title,)))
    await _render_optional_channel_menu(message, lang, is_edit=False)


# ─────────────────────────────────────────────────────────────
# Handlers: ادمین — ویرایش عنوان دکمه‌های عضویت اجباری (FA / EN)
# ─────────────────────────────────────────────────────────────

async def _render_force_join_titles_list(target, lang: str, is_edit: bool = True):
    settings = configs_pool.get('force_join_settings', {})
    channels = settings.get('channels', [])
    if not channels:
        if is_edit:
            await target.edit_text(
                t('no_channels_e03f533a13', lang),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_force_join")]
                ]),
            )
        return
    buttons = []
    for ch in channels:
        ch_id = ch.get('id')
        ch_name = ch.get('name', str(ch_id))
        buttons.append([InlineKeyboardButton(
            text=f"✏️ {ch_name}",
            callback_data=f"force_join_title_menu:{ch_id}",
        )])
    buttons.append([InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_force_join")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = t('force_join_titles_select_channel', lang)
    if is_edit:
        await target.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await target.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def _render_force_join_channel_title_menu(target, channel_id_str: str, lang: str, is_edit: bool = True):
    settings = configs_pool.get('force_join_settings', {})
    channels = settings.get('channels', [])
    ch = next((c for c in channels if str(c.get('id')) == str(channel_id_str)), None)
    if not ch:
        await _render_force_join_titles_list(target, lang, is_edit=is_edit)
        return

    ch_name = html.escape(str(ch.get('name', ch.get('id'))))
    preview_fa = html.escape(_format_force_join_button_label(ch, "fa"))
    preview_en = html.escape(_format_force_join_button_label(ch, "en"))
    text = t(
        'force_join_title_detail',
        lang,
        fa_parts=lambda: (ch_name, preview_fa, preview_en),
        en_parts=lambda: (ch_name, preview_fa, preview_en),
    )
    ch_id = ch.get('id')
    buttons = [
        [
            InlineKeyboardButton(
                text=t('force_join_title_fa_btn', lang),
                callback_data=f"force_join_title_prompt:fa:{ch_id}",
            ),
            InlineKeyboardButton(
                text=t('force_join_title_en_btn', lang),
                callback_data=f"force_join_title_prompt:en:{ch_id}",
            ),
        ],
    ]
    if ch.get('title_fa') or ch.get('title_en'):
        buttons.append([InlineKeyboardButton(
            text=t('force_join_title_reset_btn', lang),
            callback_data=f"force_join_title_reset:{ch_id}",
            style="danger",
        )])
    buttons.append([InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="force_join_titles")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if is_edit:
        await target.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await target.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "force_join_titles")
@admin_only
async def force_join_titles_list(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    settings = configs_pool.get('force_join_settings', {})
    if not settings.get('channels'):
        await callback.answer(t('no_channels_e03f533a13', lang), show_alert=True)
        return
    await _render_force_join_titles_list(callback.message, lang, is_edit=True)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("force_join_title_menu:"))
@admin_only
async def force_join_title_menu(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    ch_id = callback.data.split(":", 1)[1]
    await _render_force_join_channel_title_menu(callback.message, ch_id, lang, is_edit=True)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("force_join_title_prompt:"))
@admin_only
async def force_join_title_prompt(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    _, lang_key, ch_id = callback.data.split(":", 2)
    if lang_key not in ("fa", "en"):
        await safe_answer(callback)
        return
    user_states[callback.from_user.id] = {
        'awaiting_fj_channel_title': {'channel_id': ch_id, 'lang_key': lang_key}
    }
    lang_label = ("فارسی" if lang_key == "fa" else "انگلیسی") if lang == "fa" else ("Persian" if lang_key == "fa" else "English")
    await callback.message.answer(
        t('force_join_title_enter_prompt', lang, fa_parts=lambda: (lang_label,), en_parts=lambda: (lang_label,)),
        parse_mode=ParseMode.HTML,
    )
    await safe_answer(callback)


@router.callback_query(F.data.startswith("force_join_title_reset:"))
@admin_only
async def force_join_title_reset(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    ch_id = callback.data.split(":", 1)[1]
    settings = configs_pool.get('force_join_settings', {})
    for ch in settings.get('channels', []):
        if str(ch.get('id')) == str(ch_id):
            ch.pop('title_fa', None)
            ch.pop('title_en', None)
            settings['last_updated'] = now_tehran_iso()
            schedule_save(2.0)
            break
    await safe_answer(callback, t('force_join_title_reset_done', lang), alert=True)
    await _render_force_join_channel_title_menu(callback.message, ch_id, lang, is_edit=True)


@router.message(IsAdmin(), lambda m: bool(user_states.get(m.from_user.id, {}).get('awaiting_fj_channel_title')))
async def force_join_title_save(message: Message):
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    pending = user_states.get(admin_id, {}).get('awaiting_fj_channel_title') or {}
    ch_id = pending.get('channel_id')
    lang_key = pending.get('lang_key')
    raw = (message.text or "").strip()

    if raw == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_8a3eb8aae6', lang))
        return
    if not raw or lang_key not in ("fa", "en"):
        user_states.pop(admin_id, None)
        return

    settings = configs_pool.get('force_join_settings', {})
    for ch in settings.get('channels', []):
        if str(ch.get('id')) == str(ch_id):
            if raw in ("-", "clear", "پاک"):
                ch.pop(f"title_{lang_key}", None)
            else:
                ch[f"title_{lang_key}"] = raw[:48]
            settings['last_updated'] = now_tehran_iso()
            schedule_save(2.0)
            break
    user_states.pop(admin_id, None)
    await message.reply(t('force_join_title_saved', lang))
    await _render_force_join_channel_title_menu(message, str(ch_id), lang, is_edit=False)


@router.callback_query(F.data == "force_join_toggle")
@admin_only
async def force_join_toggle(callback: CallbackQuery):
    """فعال/غیرفعال کردن عضویت اجباری"""
    settings = configs_pool.get('force_join_settings', {})
    settings['enabled'] = not settings.get('enabled', False)
    settings['last_updated'] = now_tehran_iso()
    configs_pool['force_join_settings'] = settings
    schedule_save(2.0)
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    status = "فعال" if settings['enabled'] else "غیرفعال"
    await callback.answer(t('force_join_d_71f1993a3c', lang, fa_parts=lambda: (f'{status}',), en_parts=lambda: (f'{status}',)), show_alert=True)
    
    await admin_force_join_settings(callback)


@router.callback_query(F.data == "force_join_add")
@admin_only
async def force_join_add_start(callback: CallbackQuery):
    """شروع افزودن کانال جدید"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    user_states[callback.from_user.id] = {'awaiting_channel_id': True}
    
    await callback.message.answer(
        t('b_add_new_channel_b_please_s_e67d77b719', lang),
        parse_mode=ParseMode.HTML
    )
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_channel_id'))
async def force_join_add_channel(message: Message):
    """دریافت و افزودن کانال"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    bot_inst = message.bot or get_bot()
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_8a3eb8aae6', lang))
        return
    
    channel_input = message.text.strip()
    
    try:
        if channel_input.startswith('@'):
            chat = await bot_inst.get_chat(channel_input)
            channel_id = chat.id
            channel_name = chat.title or channel_input
            channel_username = channel_input  # ذخیره یوزرنیم
        else:
            channel_id = int(channel_input)
            try:
                chat = await bot_inst.get_chat(channel_id)
                channel_name = chat.title or str(channel_id)
                channel_username = chat.username if chat.username else None  # ذخیره یوزرنیم اگر وجود دارد
            except Exception:
                channel_name = str(channel_id)
                channel_username = None
        
        bot_member = await bot_inst.get_chat_member(channel_id, bot_inst.id)
        if bot_member.status not in ['administrator', 'creator']:
            await message.reply(t('bot_is_not_admin_7534fd6f64', lang))
            user_states.pop(admin_id, None)
            return
            
        settings = configs_pool.get('force_join_settings', {})
        channels = settings.get('channels', [])
        
        existing = [c for c in channels if c.get('id') == channel_id or c.get('id') == channel_input]
        if existing:
            await message.reply(t('channel_already_exists_e1506ee085', lang))
            user_states.pop(admin_id, None)
            return
        
        channels.append({
            'id': channel_id,
            'name': channel_name,
            'username': channel_username,  # ذخیره یوزرنیم
            'added_at': now_tehran_iso()
        })
        
        settings['channels'] = channels
        settings['last_updated'] = now_tehran_iso()
        configs_pool['force_join_settings'] = settings
        schedule_save(2.0)
        
        await message.reply(t('channel_added_e1dac60031', lang, fa_parts=lambda: (f'{channel_name}',), en_parts=lambda: (f'{channel_name}',)))
        
        log_sys = _get_log_system()
        if log_sys:
            await log_sys.log_admin_action(admin_id, "Added required-membership channel", details=f"Channel: {channel_name}")
        
    except ValueError:
        await message.reply(t('invalid_channel_id_0ab0822c4d', lang))
    except Exception as e:
        logger.error(f"Error adding channel: {e}", exc_info=True)
        err_type = html.escape(type(e).__name__)
        await message.reply(t('error_30ed4c9bcc', lang, fa_parts=lambda: (err_type,), en_parts=lambda: (err_type,)))
    
    user_states.pop(admin_id, None)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t('back_to_settings_36dae17fa8', lang), callback_data="admin_force_join")]
    ])
    await message.reply("🔄" if lang=="fa" else "🔄", reply_markup=keyboard)


@router.callback_query(F.data == "force_join_remove")
@admin_only
async def force_join_remove_start(callback: CallbackQuery):
    """نمایش لیست کانال‌ها برای حذف"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    settings = configs_pool.get('force_join_settings', {})
    channels = settings.get('channels', [])
    
    if not channels:
        await callback.answer(t('no_channels_e03f533a13', lang), show_alert=True)
        return
    
    buttons = []
    for ch in channels:
        display_name = ch.get('name', ch.get('id'))
        buttons.append([InlineKeyboardButton(
            text=f"🗑 {display_name}",
            callback_data=f"force_join_remove_channel_{ch.get('id')}"
        )])
    
    buttons.append([InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_force_join")])
    
    await callback.message.edit_text(
        t('select_channel_to_remove_78119abe14', lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await safe_answer(callback)


@router.callback_query(F.data.startswith("force_join_remove_channel_"))
@admin_only
async def force_join_remove_channel(callback: CallbackQuery):
    """حذف کانال از لیست"""
    channel_id = int(callback.data.split("_")[-1])
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    settings = configs_pool.get('force_join_settings', {})
    channels = settings.get('channels', [])
    
    removed = None
    for ch in channels:
        if ch.get('id') == channel_id:
            removed = ch
            channels.remove(ch)
            break
    
    if removed:
        settings['channels'] = channels
        settings['last_updated'] = now_tehran_iso()
        configs_pool['force_join_settings'] = settings
        schedule_save(2.0)
        
        await callback.answer(t('channel_removed_24a4a9b088', lang, fa_parts=lambda: (f"{removed.get('name')}",), en_parts=lambda: (f"{removed.get('name')}",)), show_alert=True)
        
        log_sys = _get_log_system()
        if log_sys:
            await log_sys.log_admin_action(
                callback.from_user.id,
                "Removed required-membership channel",
                details=f"Channel: {removed.get('name')} (ID: {channel_id})"
            )
    else:
        await callback.answer(t('channel_not_found_8faadce1ce', lang), show_alert=True)
    
    await admin_force_join_settings(callback)


@router.callback_query(F.data == "force_join_check")
async def force_join_check_membership(callback: CallbackQuery):
    """بررسی عضویت کاربر فعلی"""
    user_id = callback.from_user.id
    admin_id_int = _get_admin_id()
    if user_id == admin_id_int:
        await callback.answer(t('i18n_your_admin', get_user(user_id).get('lang', 'fa')), show_alert=True)
        return
    
    settings = configs_pool.get('force_join_settings', {})
    
    if not settings.get('enabled', False):
        await callback.answer(t('force_join_is_disabled_635701ce9a', get_user(user_id).get('lang', 'fa')), show_alert=True)
        return
    
    channels = settings.get('channels', [])
    
    if not channels:
        await callback.answer(t('no_channels_registered_d09eb3a893', get_user(user_id).get('lang', 'fa')), show_alert=True)
        return
    
    not_joined = []
    bot_inst = callback.bot or get_bot()
    
    for ch in channels:
        try:
            member = await bot_inst.get_chat_member(ch.get('id'), user_id)
            if member.status in ['left', 'kicked']:
                not_joined.append(ch)
        except Exception as e:
            logger.error(f"Error checking channel membership {ch.get('id')}: {e}")
            not_joined.append(ch)
    
    lang = get_user(user_id).get('lang', 'fa')
    
    if not_joined:
        text = t('you_are_not_a_member_of_81635040b7', lang)
        for ch in not_joined:
            text += f"• {ch.get('name', ch.get('id'))}\n"
        text += t('please_join_first_then_try_a_ae4f1527dd', lang)
        await callback.answer(text, show_alert=True)
    else:
        await callback.answer(t('you_are_a_member_of_all_requ_e1fde2d090', lang), show_alert=True)


# ─────────────────────────────────────────────────────────────
# Utility Functions: بررسی عضویت
# ─────────────────────────────────────────────────────────────

async def check_membership_detailed(user_id: int) -> dict:
    """
    بررسی دقیق عضویت کاربر در همه کانال‌ها
    """
    logger.info(f"🔍 starting check of user membership {user_id}")
    admin_id_int = _get_admin_id()
    
    if user_id == admin_id_int:
        logger.info(f"👑 user {user_id} is admin")
        return {
            'is_all_joined': True,
            'not_joined': [],
            'left_channels': [],
            'kicked_channels': [],
            'details': []
        }
    
    settings = configs_pool.get('force_join_settings', {})
    
    if not settings.get('enabled', False):
        logger.info("ℹ️ mandatory membership is disabled")
        return {
            'is_all_joined': True,
            'not_joined': [],
            'left_channels': [],
            'kicked_channels': [],
            'details': []
        }
    
    channels = settings.get('channels', [])
    
    if not channels:
        logger.info("ℹ️ no channels registered")
        return {
            'is_all_joined': True,
            'not_joined': [],
            'left_channels': [],
            'kicked_channels': [],
            'details': []
        }
    
    result = {
        'is_all_joined': True,
        'not_joined': [],
        'left_channels': [],
        'kicked_channels': [],
        'details': []
    }
    
    bot_inst = get_bot()
    if not bot_inst:
        logger.error("❌ Bot instance not available for check_membership_detailed")
        return result
    
    for ch in channels:
        channel_id = ch.get('id')
        channel_name = ch.get('name', channel_id)
        try:
            logger.info(f"📢 Checking channel {channel_name} (ID: {channel_id})")
            if isinstance(channel_id, str) and channel_id.startswith('@'):
                chat_id = channel_id
            elif isinstance(channel_id, str) and channel_id.lstrip('-').isdigit():
                chat_id = int(channel_id)
            elif isinstance(channel_id, int):
                chat_id = channel_id
            else:
                logger.error(f"❌ Invalid channel_id format: {channel_id}")
                result['is_all_joined'] = False
                result['not_joined'].append(ch)
                result['details'].append({
                    'channel_id': channel_id,
                    'channel_name': channel_name,
                    'status': 'invalid_format',
                    'is_member': False
                })
                continue
            
            member = await bot_inst.get_chat_member(chat_id=chat_id, user_id=user_id)
            status = member.status
            
            logger.info(f"📊 User status in {channel_name}: {status}")
            
            channel_detail = {
                'channel_id': channel_id,
                'channel_name': channel_name,
                'status': status,
                'is_member': status in ['member', 'administrator', 'creator']
            }
            
            result['details'].append(channel_detail)
            
            if status not in ['member', 'administrator', 'creator']:
                result['is_all_joined'] = False
                result['not_joined'].append(ch)
                
                if status == 'left':
                    result['left_channels'].append(channel_name)
                    logger.warning(f"🚪 User left {channel_name} left")
                elif status == 'kicked':
                    result['kicked_channels'].append(channel_name)
                    logger.warning(f"⛔ User banned from {channel_name} was banned")
                    
        except Exception as e:
            logger.error(f"❌ Error checking user membership {user_id} in channel {channel_id}: {e}")
            result['is_all_joined'] = False
            result['not_joined'].append(ch)
            result['details'].append({
                'channel_id': channel_id,
                'channel_name': channel_name,
                'status': 'error',
                'is_member': False
            })
    
    logger.info(f"📋 final check result: is_all_joined={result['is_all_joined']}")
    return result


async def check_membership(user_id: int) -> bool:
    """
    بررسی کامل عضویت کاربر در کانال‌های اجباری
    """
    admin_id_int = _get_admin_id()
    if user_id == admin_id_int:
        return True
    
    settings = configs_pool.get('force_join_settings', {})
    
    if not settings.get('enabled', False):
        return True
    
    channels = settings.get('channels', [])
    
    if not channels:
        return True
    
    bot_inst = get_bot()
    if not bot_inst:
        logger.error("❌ Bot instance not available for check_membership")
        return True
    
    # بررسی واقعی عضویت
    for ch in channels:
        channel_id = ch.get('id')
        try:
            member = await bot_inst.get_chat_member(channel_id, user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            logger.error(f"Error checking user membership {user_id} in channel {channel_id}: {e}")
            return False
    
    return True


@router.callback_query(F.data == "verify_membership")
async def process_verify_membership(callback: CallbackQuery):
    """
    بررسی عضویت کاربر بعد از کلیک روی دکمه تایید
    """
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    
    try:
        # بررسی دقیق عضویت با جزئیات
        membership_report = await check_membership_detailed(user_id)
        
        if membership_report['is_all_joined']:
            # کاربر عضو همه کانال‌هاست - ثبت وضعیت
            user = get_user(user_id)
            if user:
                user['verified'] = True
                user['updated_at'] = now_tehran_iso()
                schedule_file_save('users', delay=1.0)
                logger.info(f"✅ user {user_id} membership in all channels confirmed")
            
            success_text = t('b_membership_confirmed_b_wel_053135e07b', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('rocket', '🚀')}"), en_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('rocket', '🚀')}"))
            await refresh_optional_channel_membership(user_id, force=True)

            pending_deep_link = None
            user_state = user_states.get(user_id)
            if isinstance(user_state, dict):
                pending_deep_link = user_state.pop('pending_deep_link', None)
                if not user_state:
                    user_states.pop(user_id, None)

            try:
                await callback.message.delete()
            except Exception:
                pass

            if pending_deep_link:
                await safe_answer(
                    callback,
                    "✅ عضویت تایید شد!" if lang == "fa" else "✅ Membership verified!"
                )
                try:
                    import main
                    if hasattr(main, "handle_start_deep_link"):
                        handled = await main.handle_start_deep_link(
                            callback.message,
                            user_id,
                            pending_deep_link,
                            from_user=callback.from_user,
                        )
                        if handled:
                            return
                except Exception as dl_err:
                    logger.error(f"❌ Error continuing pending deep link for user {user_id}: {dl_err}")

            await callback.message.answer(
                success_text,
                parse_mode=ParseMode.HTML,
                reply_markup=_get_main_keyboard(False, lang, user_id)
            )
            
        else:
            # کاربر عضو همه کانال‌ها نیست
            not_joined = membership_report['not_joined']
            left_channels = membership_report['left_channels']
            kicked_channels = membership_report['kicked_channels']
            
            # ساخت پیام خطا با جزئیات
            warning_text = t('b_membership_incomplete_b_f06ae84523', lang, fa_parts=lambda: (f"{premium_emoji('danger', '⚠️')}",), en_parts=lambda: (f"{premium_emoji('danger', '⚠️')}",))
            if left_channels:
                warning_text += t('b_left_channels_b_716c2f65bf', lang, fa_parts=lambda: (f"{premium_emoji('exit', '🚪')}", f"{chr(10).join([f'• {ch}' for ch in left_channels])}"), en_parts=lambda: (f"{premium_emoji('exit', '🚪')}", f"{chr(10).join([f'• {ch}' for ch in left_channels])}"))

            if kicked_channels:
                warning_text += t('b_kicked_from_b_031156a8d6', lang, fa_parts=lambda: (f"{premium_emoji('ban', '⛔')}", f"{chr(10).join([f'• {ch}' for ch in kicked_channels])}"), en_parts=lambda: (f"{premium_emoji('ban', '⛔')}", f"{chr(10).join([f'• {ch}' for ch in kicked_channels])}"))

            warning_text += t('please_join_all_channels_fir_ade48fbd7f', lang, fa_parts=lambda: (f"{premium_emoji('info', 'ℹ️')}",), en_parts=lambda: (f"{premium_emoji('info', 'ℹ️')}",))
            
            # به‌روزرسانی وضعیت verified به False
            user = get_user(user_id)
            if user and user.get('verified', False):
                user['verified'] = False
                user['updated_at'] = now_tehran_iso()
                schedule_file_save('users', delay=1.0)
                logger.warning(f"⚠️ user {user_id} left the channel; verified changed to False")
            
            await callback.answer(t('i18n_not_joined_yet', lang), show_alert=True)
            
            # نمایش مجدد صفحه عضویت با لینک‌ها
            try:
                await callback.message.delete()
            except Exception:
                pass
            
            await show_verification_page(callback.message, user_id, lang)
            
    except Exception as e:
        logger.error(f"❌ Error checking membership: {e}")
        await callback.answer(t('i18n_check_error_try_again', lang), show_alert=True)


async def show_verification_page(message: Message, user_id: int, lang: str = "fa"):
    """نمایش صفحه تایید عضویت با لینک کانال‌ها"""
    settings = configs_pool.get('force_join_settings', {})
    channels = settings.get('channels', [])
    buttons = []
    
    for ch in channels:
        channel_username = ch.get('username')
        
        # ساخت لینک مناسب
        if channel_username and channel_username.startswith('@'):
            channel_link = f"https://t.me/{channel_username[1:]}"
        elif channel_username:
            channel_link = f"https://t.me/{channel_username}"
        else:
            channel_id = ch.get('id')
            if isinstance(channel_id, int) and channel_id < 0:
                # برای کانال‌های خصوصی
                channel_id_str = str(channel_id).replace('-100', '')
                channel_link = f"https://t.me/c/{channel_id_str}"
            else:
                channel_link = f"https://t.me/{channel_id}"
        
        join_btn_text = _format_force_join_button_label(ch, lang)
        buttons.append([InlineKeyboardButton(
            text=join_btn_text,
            url=channel_link
        )])
    
    verify_btn_text = (
        "✅ تایید عضویت"
        if lang == "fa"
        else "✅ Verify Membership"
    )
    buttons.append([InlineKeyboardButton(
        text=verify_btn_text,
        callback_data="verify_membership",
        style="success"
    )])
    
    text = t('b_membership_verification_b_75a29c9935', lang)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

"""
routers/force_join.py
---------------------
مدیریت عضویت اجباری کاربران در کانال‌های تلگرام (Force Join)
شامل تنظیمات ادمین، بررسی عضویت، تایید عضویت و نمایش صفحه عضویت
"""

import html
import logging
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
            text += f"• {ch.get('name', ch.get('id'))} (`{ch.get('id')}`)\n"
        
        if not channels:
            text += t('no_channels_registered_e17f438d71', lang)
        
        text += t('users_must_join_all_above_ch_880bcba8c2', lang)
        text += t('after_joining_click_the_veri_963c4ada02', lang)
        text += f"\n📣 کانال اختیاری: {opt_status}\n"
        
        buttons = [
            [InlineKeyboardButton(text=t('enable_disable_d7aad0bd90', lang), callback_data="force_join_toggle")],
            [InlineKeyboardButton(text=t('add_channel_c1ed5f0e64', lang), callback_data="force_join_add")],
            [InlineKeyboardButton(text=t('remove_channel_6636beb744', lang), callback_data="force_join_remove")],
            [InlineKeyboardButton(text=t('force_join_optional_btn', lang), callback_data="force_join_optional_menu", style="primary")],
            [InlineKeyboardButton(text=t('check_my_membership_ce061badb3', lang), callback_data="force_join_check")],
            [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
        ]
    else:
        text = t('b_force_join_channels_b_stat_11f9df3575', lang, en_parts=lambda: (f'{status_text}', f'{len(channels)}'))
        for ch in channels:
            text += f"• {ch.get('name', ch.get('id'))} (`{ch.get('id')}`)\n"
        
        if not channels:
            text += t('no_channels_registered_e17f438d71', lang)
        
        text += t('users_must_join_all_above_ch_880bcba8c2', lang)
        text += t('after_joining_click_the_veri_963c4ada02', lang)
        text += f"\n📣 Optional Channel: {opt_status}\n"
        
        buttons = [
            [InlineKeyboardButton(text=t('enable_disable_d7aad0bd90', lang), callback_data="force_join_toggle")],
            [InlineKeyboardButton(text=t('add_channel_c1ed5f0e64', lang), callback_data="force_join_add")],
            [InlineKeyboardButton(text=t('remove_channel_6636beb744', lang), callback_data="force_join_remove")],
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


def _resolve_optional_channel_title(opt: dict, lang: str) -> str:
    raw = (
        opt.get('title_fa' if lang == 'fa' else 'title_en')
        or opt.get('title')
        or ''
    ).strip()
    if not raw or raw in ("📣 Join Channel", "📣 عضویت در کانال"):
        return "📣 عضویت در کانال" if lang == "fa" else "📣 Join Channel"
    return raw


async def _render_optional_channel_menu(target, lang: str, is_edit: bool = True):
    settings = configs_pool.setdefault('force_join_settings', {})
    opt = settings.setdefault('optional_channel', {})
    enabled = bool(opt.get('enabled', False)) and bool(opt.get('url'))
    status_str = t('i18n_status_active', lang) if enabled else t('i18n_status_inactive', lang)
    display_title = _resolve_optional_channel_title(opt, lang) if opt.get('url') else ""
    ch_str = (
        f"<a href=\"{html.escape(opt.get('url', ''))}\">{html.escape(display_title or opt.get('url', ''))}</a>"
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
        color_row,
    ]
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
    settings['last_updated'] = now_tehran_iso()
    save_all()
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
    save_all()
    await _render_optional_channel_menu(callback.message, lang, is_edit=True)
    await safe_answer(callback)


@router.callback_query(F.data == "force_join_optional_remove")
@admin_only
async def force_join_optional_remove(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    settings = configs_pool.setdefault('force_join_settings', {})
    settings.pop('optional_channel', None)
    settings['last_updated'] = now_tehran_iso()
    save_all()
    await safe_answer(callback, t('force_join_optional_removed', lang), alert=True)
    await _render_optional_channel_menu(callback.message, lang, is_edit=True)


@router.callback_query(F.data == "force_join_optional_set")
@admin_only
async def force_join_optional_set_start(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    user_states[callback.from_user.id] = {'awaiting_optional_channel': True}
    await callback.message.answer(t('force_join_optional_set_prompt', lang), parse_mode=ParseMode.HTML)
    await safe_answer(callback)


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
    target_ref = raw
    if "|" in raw:
        left, right = (p.strip() for p in raw.split("|", 1))
        if left and right:
            custom_title = left[:48]
            target_ref = right

    url = None
    title = custom_title
    bot_inst = message.bot or get_bot()

    if target_ref.startswith('@'):
        uname = target_ref.lstrip('@').strip()
        if not uname:
            await message.reply(t('force_join_optional_invalid_link', lang))
            return
        url = f"https://t.me/{uname}"
        if not title and bot_inst:
            try:
                chat = await bot_inst.get_chat(f"@{uname}")
                title = (chat.title or f"@{uname}")[:48]
            except Exception:
                title = f"@{uname}"
    elif target_ref.startswith('https://t.me/') or target_ref.startswith('http://t.me/'):
        url = target_ref.replace('http://t.me/', 'https://t.me/', 1)
    elif target_ref.startswith('t.me/'):
        url = f"https://{target_ref}"
    else:
        await message.reply(t('force_join_optional_invalid_link', lang))
        return

    settings = configs_pool.setdefault('force_join_settings', {})
    prev_opt = settings.get('optional_channel', {}) or {}
    if title:
        title_fa = title
        title_en = title
    else:
        title_fa = "📣 عضویت در کانال"
        title_en = "📣 Join Channel"
    display_title = title_fa if lang == "fa" else title_en
    settings['optional_channel'] = {
        'enabled': True,
        'title': display_title,
        'title_fa': title_fa,
        'title_en': title_en,
        'url': url,
        'style': prev_opt.get('style', 'primary'),
    }
    settings['last_updated'] = now_tehran_iso()
    save_all()
    user_states.pop(admin_id, None)

    await message.reply(t('force_join_optional_saved', lang, fa_parts=lambda: (display_title,), en_parts=lambda: (display_title,)))
    await _render_optional_channel_menu(message, lang, is_edit=False)


@router.callback_query(F.data == "force_join_toggle")
@admin_only
async def force_join_toggle(callback: CallbackQuery):
    """فعال/غیرفعال کردن عضویت اجباری"""
    settings = configs_pool.get('force_join_settings', {})
    settings['enabled'] = not settings.get('enabled', False)
    settings['last_updated'] = now_tehran_iso()
    configs_pool['force_join_settings'] = settings
    save_all()
    
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
        save_all()
        
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
        save_all()
        
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
                save_json(DB_FILES['users'], users)
                logger.info(f"✅ user {user_id} membership in all channels confirmed")
            
            success_text = t('b_membership_confirmed_b_wel_053135e07b', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('rocket', '🚀')}"), en_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('rocket', '🚀')}"))
            
            await callback.message.delete()
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
                save_json(DB_FILES['users'], users)
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
        channel_name = ch.get('name', 'کانال')
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
        
        buttons.append([InlineKeyboardButton(
            text=f"📢 عضویت در {channel_name}",
            url=channel_link
        )])
    
    buttons.append([InlineKeyboardButton(
        text="✅ تایید عضویت",
        callback_data="verify_membership",
        style="primary"
    )])
    
    text = t('b_membership_verification_b_75a29c9935', lang, fa_parts=lambda: (f"{premium_emoji('warning', '⚠️')}",), en_parts=lambda: (f"{premium_emoji('warning', '⚠️')}",))
    for ch in channels:
        text += f"• {ch.get('name', ch.get('id'))}\n"

    text += t('click_the_button_of_each_cha_1e8aa8608a', lang, fa_parts=lambda: (f"{premium_emoji('link', '🔗')}", f"{premium_emoji('info', 'ℹ️')}"), en_parts=lambda: (f"{premium_emoji('link', '🔗')}", f"{premium_emoji('info', 'ℹ️')}"))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

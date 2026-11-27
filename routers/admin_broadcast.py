"""
routers/admin_broadcast.py
--------------------------
سیستم ارسال پیام همگانی (Broadcast) توسط ادمین
پشتیبانی از انواع پیام (متن، عکس، ویدیو، داکیومنت، صوت، ویس)،
دکمه‌های شیشه‌ای اختصاصی و ناوبری، پیش‌نمایش قبل از ارسال و گزارش ارسال.
"""

import asyncio
import html
import logging
import re
import uuid
from typing import Optional, List, Dict, Tuple, Any

from yarl import URL
from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.enums import ParseMode

from config import ADMIN_ID
from database import (
    users,
    BLACKLIST,
    now_tehran,
    now_tehran_iso,
    configs_pool,
    save_all,
    get_test_service_display,
)
from core.save_scheduler import schedule_save
from user_manager import user_states, get_user, get_admin_id_int
from strings import t
from emoji_sticker_system import premium_emoji
from utils.filters import IsAdmin
from utils.guards import admin_only
from utils.helpers import safe_answer

logger = logging.getLogger(__name__)

router = Router(name="admin_broadcast")

_bot: Optional[Bot] = None


def set_bot(b: Bot):
    """تنظیم شیء Bot برای استفاده در متدهای ارسال برودکست"""
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


def _get_ready_packages() -> dict:
    try:
        import main
        if hasattr(main, "READY_PACKAGES") and isinstance(main.READY_PACKAGES, dict):
            return main.READY_PACKAGES
    except Exception:
        pass
    return configs_pool.get("ready_packages", {})


def detect_safe_parse_mode(text: str) -> Optional[ParseMode]:
    """تشخیص اینکه متن حاوی HTML معتبر است یا خیر"""
    if not text:
        return None
    supported_tags = (
        "b|strong|i|em|u|ins|s|strike|del|span|tg-spoiler|tg-emoji|"
        "a|code|pre|blockquote"
    )
    tag_pattern = rf"</?(?:{supported_tags})(?:\s|>|/)"
    if not re.search(tag_pattern, text, re.IGNORECASE):
        return None
    if text.count('<') != text.count('>'):
        return None
    invalid_pattern = r'[^\w\s<>/="\']<[^\w\s<>/="\']'
    if re.search(invalid_pattern, text):
        return None
    open_tags = re.findall(r'<([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*>', text)
    close_tags = re.findall(r'</([a-zA-Z][a-zA-Z0-9-]*)\s*>', text)
    if len(open_tags) != len(close_tags):
        return None
    return ParseMode.HTML


# ─────────────────────────────────────────────────────────────
# Actions & Helpers
# ─────────────────────────────────────────────────────────────

_BROADCAST_ACTIONS = {
    # ─── دکمه‌های اصلی ربات (مطابق منوی پیش‌فرض) ───
    "buy": ("🛒 خرید سرویس", "🛒 Buy Service", "buy_service"),
    "configs": ("🌐 کانفیگ‌های من", "🌐 My Configs", "my_configs"),
    "account": ("👤 حساب کاربری", "👤 My Account", "my_account"),
    "balance": ("💰 افزایش موجودی", "💰 Increase Balance", "increase_balance"),
    "coupon": ("🏷️ اعمال کوپن", "🏷️ Apply coupon", "apply_coupon"),
    "invite": ("👥 دعوت از دوستان", "👥 Invite Friends", "invite_friends"),
    "ai": ("🤖 پشتیبانی هوشمند", "🤖 Smart Support", "ai_chat"),
    "test": ("🎁 کانفیگ خوش‌آمد", "🎁 Welcome Config", "get_test_service"),
    "language": ("🌎 تغییر زبان", "🌎 Change Language", "change_language"),
    "home": ("🏠 منوی اصلی", "🏠 Main Menu", "broadcast_back_to_main"),
    
    # ─── سایر بخش‌های کاربردی ربات (دقیقاً هم‌نام با صفحات بات) ───
    "packages": ("📦 خرید از بسته‌های آماده", "📦 Buy Ready Packages", "show_ready_categories"),
    "renew": ("🔄 تمدید سرویس", "🔄 Extend Service", "my_configs"),
    "all_configs": ("🌐 نمایش تمام ساب‌ها", "🌐 Show All Configs", "show_all_my_configs"),
    "order_status": ("📊 وضعیت سفارش‌ها", "📊 Order Status", "order_status"),
    "coupon_status": ("🏷️ وضعیت کوپن", "🏷️ Coupon Status", "coupon_status"),
    "support": ("🎫 ارتباط با پشتیبانی", "🎫 Contact Support", "support_create_ticket"),
    "ai_advisor": ("🛍 انتخاب هوشمند", "🛍 Smart Choice", "ai_purchase_advisor_start"),
}


def get_broadcast_actions() -> Dict[str, Tuple[str, str, str]]:
    """دریافت تمامی دکمه‌های ناوبری برودکست به همراه دسته‌بندی‌های کانفیگ"""
    actions = _BROADCAST_ACTIONS.copy()
    fa_e, fa_n = get_test_service_display('fa')
    en_e, en_n = get_test_service_display('en')
    actions["test"] = (f"{fa_e} {fa_n}", f"{en_e} {en_n}", "get_test_service")
    ready_pkgs = _get_ready_packages()
    categories = ready_pkgs.get('categories', []) if isinstance(ready_pkgs, dict) else []
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        cat_id = cat.get('id')
        if cat_id is None:
            continue
        icon = cat.get('icon', '📦')
        raw_name_fa = (cat.get('name') or f"دسته {cat_id}").strip()
        raw_name_en = (cat.get('name_en') or raw_name_fa).strip()
        
        if not raw_name_fa.startswith("سرویس") and not raw_name_fa.startswith("کانفیگ"):
            fa_text = f"{icon} سرویس {raw_name_fa}"
        else:
            fa_text = f"{icon} {raw_name_fa}"
            
        if not raw_name_en.lower().startswith("service") and not raw_name_en.lower().endswith("service"):
            en_text = f"{icon} {raw_name_en} Service"
        else:
            en_text = f"{icon} {raw_name_en}"
            
        actions[f"category_{cat_id}"] = (fa_text, en_text, f"show_category_packages_{cat_id}")
    return actions


def _is_safe_broadcast_url(raw_url: str) -> bool:
    if not isinstance(raw_url, str) or len(raw_url) > 2048:
        return False
    if any(ord(char) < 32 for char in raw_url):
        return False
    try:
        parsed_url = URL(raw_url)
    except (TypeError, ValueError):
        return False
    return bool(
        (
            parsed_url.scheme == "https"
            and parsed_url.host
            and not parsed_url.user
            and not parsed_url.password
        )
        or (parsed_url.scheme == "tg" and parsed_url.host)
    )


def _broadcast_recipient_ids() -> list:
    recipient_ids = []
    for stored_id, user_data in users.items():
        try:
            user_id = int(stored_id)
        except (TypeError, ValueError):
            continue
        if user_id <= 0 or user_id in BLACKLIST or str(user_id) in BLACKLIST:
            continue
        if isinstance(user_data, dict):
            if user_data.get("is_active") is False:
                continue
            if user_data.get("registration_status") in {"cancelled", "rejected"}:
                continue
        recipient_ids.append(user_id)
    return list(dict.fromkeys(recipient_ids))


def _broadcast_keyboard(
    buttons: list,
    lang: str,
    layout: str = "single",
    broadcast_id: Optional[str] = None,
    view_lang: Optional[str] = None,
    has_en_version: bool = False,
) -> Optional[InlineKeyboardMarkup]:
    """Build only registered navigation buttons and validated external links."""
    items = []
    broadcast_actions = get_broadcast_actions()
    effective_lang = view_lang or lang
    for button in buttons:
        if not isinstance(button, dict):
            continue
        action = button.get("action")
        style = button.get("style")
        if style not in {None, "primary", "success", "danger"}:
            style = None
        if action == "translate_fa":
            # دکمه ترجمه فقط زمانی که پیام انگلیسی موجود باشد و در چرخه EN <-> FA هستیم نمایش داده می‌شود
            if has_en_version and broadcast_id:
                if effective_lang == "en":
                    items.append((
                        InlineKeyboardButton(
                            text=t('broadcast_translate_to_fa_btn', 'fa'),
                            callback_data=f"broadcast_translate:{broadcast_id}:fa",
                            style=style,
                        ),
                        True,
                    ))
                elif view_lang == "fa":
                    items.append((
                        InlineKeyboardButton(
                            text=t('broadcast_translate_to_en_btn', 'en'),
                            callback_data=f"broadcast_translate:{broadcast_id}:en",
                            style=style,
                        ),
                        True,
                    ))
            continue
        if action in broadcast_actions:
            fa_text, en_text, callback_data = broadcast_actions[action]
            items.append((
                InlineKeyboardButton(
                    text=fa_text if effective_lang == "fa" else en_text,
                    callback_data=callback_data,
                    style=style,
                ),
                False
            ))
        elif action == "url":
            label = button.get("label")
            url = button.get("url")
            if (
                isinstance(label, str)
                and 1 <= len(label) <= 64
                and _is_safe_broadcast_url(url)
            ):
                items.append((
                    InlineKeyboardButton(
                        text=label,
                        url=url,
                        style=style,
                    ),
                    len(label) > 22
                ))
    if not items:
        return None

    rows = []
    if layout == "double":
        row = []
        for btn, is_wide in items:
            if is_wide:
                if row:
                    rows.append(row)
                    row = []
                rows.append([btn])
            else:
                row.append(btn)
                if len(row) == 2:
                    rows.append(row)
                    row = []
        if row:
            rows.append(row)
    else:
        for btn, _ in items:
            rows.append([btn])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ensure_broadcast_translation_record(broadcast_data: dict) -> Optional[str]:
    """ذخیره متن فارسی/انگلیسی برودکست برای پشتیبانی از دکمه ترجمه کاربران"""
    if not broadcast_data.get("en_caption"):
        return None
    broadcast_id = broadcast_data.get("broadcast_id") or uuid.uuid4().hex[:8]
    broadcast_data["broadcast_id"] = broadcast_id
    store = configs_pool.setdefault("broadcast_translations", {})
    store[broadcast_id] = {
        "type": broadcast_data.get("type", "text"),
        "fa_caption": broadcast_data.get("caption") or "",
        "fa_html": broadcast_data.get("parse_mode") == ParseMode.HTML,
        "en_caption": broadcast_data.get("en_caption") or "",
        "en_html": broadcast_data.get("en_parse_mode") == ParseMode.HTML,
        "buttons": list(broadcast_data.get("buttons", [])),
        "layout": broadcast_data.get("layout", "single"),
        "created_at": now_tehran_iso(),
    }
    if len(store) > 20:
        for old_key in list(store.keys())[:-20]:
            store.pop(old_key, None)
    return broadcast_id


async def _send_broadcast_message(
    chat_id: int,
    broadcast_data: dict,
    lang: str,
):
    layout = broadcast_data.get("layout", "single")
    has_en = bool(broadcast_data.get("en_caption"))
    use_en = (lang == "en" and has_en)
    broadcast_id = _ensure_broadcast_translation_record(broadcast_data) if has_en else None
    keyboard = _broadcast_keyboard(
        broadcast_data.get("buttons", []),
        lang,
        layout,
        broadcast_id=broadcast_id,
        view_lang=("en" if use_en else None),
        has_en_version=has_en,
    )
    bot_inst = get_bot()
    if not bot_inst:
        raise RuntimeError("Bot instance is not configured for broadcasting")

    if use_en:
        caption = str(broadcast_data.get("en_caption") or "")
        pm = broadcast_data.get("en_parse_mode")
        broadcast_type = broadcast_data.get("type")
        if broadcast_type == "text":
            if pm == ParseMode.HTML:
                return await bot_inst.send_message(
                    chat_id, caption, parse_mode=ParseMode.HTML, reply_markup=keyboard
                )
            if broadcast_data.get("en_source_chat_id") and broadcast_data.get("en_source_message_id"):
                return await bot_inst.copy_message(
                    chat_id,
                    broadcast_data["en_source_chat_id"],
                    broadcast_data["en_source_message_id"],
                    reply_markup=keyboard,
                )
            return await bot_inst.send_message(chat_id, caption, reply_markup=keyboard)
        media = broadcast_data.get("media")
        if not media:
            raise ValueError("شناسهٔ رسانهٔ برودکست موجود نیست")
        if broadcast_type == "photo":
            return await bot_inst.send_photo(
                chat_id, media, caption=caption or None, parse_mode=pm, reply_markup=keyboard
            )
        if broadcast_type == "file":
            send_file = bot_inst.send_video if broadcast_data.get("media_kind") == "video" else bot_inst.send_document
            return await send_file(
                chat_id, media, caption=caption or None, parse_mode=pm, reply_markup=keyboard
            )
        if broadcast_type == "audio":
            send_audio = bot_inst.send_voice if broadcast_data.get("subtype") == "voice" else bot_inst.send_audio
            return await send_audio(
                chat_id, media, caption=caption or None, parse_mode=pm, reply_markup=keyboard
            )
        raise ValueError(f"نوع برودکست پشتیبانی نمی‌شود: {broadcast_type}")

    if broadcast_data.get("parse_mode") == ParseMode.HTML:
        caption = broadcast_data.get("caption", "")
        if caption is None:
            caption = ""
        caption = str(caption)
        media = broadcast_data.get("media")
        broadcast_type = broadcast_data.get("type")
        if broadcast_type == "text":
            return await bot_inst.send_message(
                chat_id, caption, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
        if not media:
            raise ValueError("شناسهٔ رسانهٔ برودکست موجود نیست")
        if broadcast_type == "photo":
            return await bot_inst.send_photo(
                chat_id, media, caption=caption or None,
                parse_mode=ParseMode.HTML, reply_markup=keyboard,
            )
        if broadcast_type == "file":
            send_file = bot_inst.send_video if broadcast_data.get("media_kind") == "video" else bot_inst.send_document
            return await send_file(
                chat_id, media, caption=caption or None,
                parse_mode=ParseMode.HTML, reply_markup=keyboard,
            )
        if broadcast_type == "audio":
            send_audio = bot_inst.send_voice if broadcast_data.get("subtype") == "voice" else bot_inst.send_audio
            return await send_audio(
                chat_id, media, caption=caption or None,
                parse_mode=ParseMode.HTML, reply_markup=keyboard,
            )
        raise ValueError(f"نوع برودکست پشتیبانی نمی‌شود: {broadcast_type}")

    return await bot_inst.copy_message(
        chat_id,
        broadcast_data["source_chat_id"],
        broadcast_data["source_message_id"],
        reply_markup=keyboard,
    )


def _broadcast_button_setup_markup(
    buttons: list,
    lang: str,
    button_styles: Optional[dict] = None,
    layout: str = "single",
    has_en_version: bool = False,
) -> InlineKeyboardMarkup:
    button_styles = button_styles or {}
    selected = {
        button.get("action"): button
        for button in buttons
        if isinstance(button, dict) and isinstance(button.get("action"), str) and button.get("action") != "url"
    }
    style_labels = {
        None: t('default_ab8ef75ec1', lang),
        "primary": t('blue_1fcaaaf81f', lang),
        "success": t('green_463860e044', lang),
        "danger": t('red_5c24b04043', lang),
    }
    rows = []
    broadcast_actions = get_broadcast_actions()
    for key, (fa_text, en_text, _) in broadcast_actions.items():
        item = selected.get(key)
        style = item.get("style") if item else button_styles.get(key)
        if style not in {None, "primary", "success", "danger"}:
            style = None
        rows.append([
            InlineKeyboardButton(
                text=f"{'✅ ' if item else ''}{fa_text if lang == 'fa' else en_text}",
                callback_data=f"broadcast_button_toggle:{key}",
                style=style,
            ),
            InlineKeyboardButton(
                text=style_labels.get(style, style_labels[None]),
                callback_data=f"broadcast_button_style:{key}",
            ),
        ])

    # ─── دکمه‌های لینک اختصاصی (پشتیبانی از چندین دکمه) ───
    url_buttons = [
        b for b in buttons
        if isinstance(b, dict) and b.get("action") == "url"
    ]
    for idx, ub in enumerate(url_buttons):
        u_id = ub.get("url_id") or f"url_{idx}"
        ub["url_id"] = u_id
        u_label = ub.get("label", "لینک")
        u_style = ub.get("style")
        if u_style not in style_labels:
            u_style = None
        rows.append([
            InlineKeyboardButton(
                text=f"🔗 {u_label[:14]}",
                callback_data=f"broadcast_url_info:{u_id}",
                style=u_style,
            ),
            InlineKeyboardButton(
                text=style_labels.get(u_style, style_labels[None]),
                callback_data=f"broadcast_url_style:{u_id}",
            ),
            InlineKeyboardButton(
                text="🗑️",
                callback_data=f"broadcast_url_delete:{u_id}",
            ),
        ])

    if has_en_version:
        tr_item = selected.get("translate_fa")
        tr_style = tr_item.get("style") if tr_item else button_styles.get("translate_fa")
        if tr_style not in style_labels:
            tr_style = None
        rows.append([
            InlineKeyboardButton(
                text=f"{'✅ ' if tr_item else ''}{t('broadcast_translate_btn_setup', lang)}",
                callback_data="broadcast_button_toggle:translate_fa",
                style=tr_style,
            ),
            InlineKeyboardButton(
                text=style_labels.get(tr_style, style_labels[None]),
                callback_data="broadcast_button_style:translate_fa",
            ),
        ])

    layout_toggle_label = (t('2_columns_293ed635ba', lang) if layout == 'double' else t('1_column_d1aafb2e7c', lang))
    rows.extend([
        [
            InlineKeyboardButton(
                text=f"📐 چیدمان: {layout_toggle_label}",
                callback_data="broadcast_layout_toggle",
            ),
            InlineKeyboardButton(
                text=t('clear_all_e4034fc52e', lang),
                callback_data="broadcast_buttons_clear",
            ),
        ],
        [InlineKeyboardButton(
            text=t('add_custom_url_button_fe32cdcf53', lang),
            callback_data="broadcast_button_add_url",
        )],
        [InlineKeyboardButton(
            text=t('continue_to_preview_618e9bee8d', lang),
            callback_data="broadcast_buttons_done",
            style="success",
        )],
        [InlineKeyboardButton(
            text=t('cancel_broadcast_19a887c8b6', lang),
            callback_data="cancel_broadcast",
            style="danger",
        )],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _update_broadcast_setup_message(callback: CallbackQuery, admin_id: int):
    state = user_states.get(admin_id, {})
    broadcast_data = state.get("broadcast_data", {})
    lang = get_user(admin_id).get("lang", "fa")
    buttons = broadcast_data.setdefault("buttons", [])
    layout = broadcast_data.get("layout", "single")
    button_styles = broadcast_data.setdefault("button_styles", {})

    selected_count = len(buttons)
    layout_name = (t('2_columns_293ed635ba', lang) if layout == 'double' else t('1_column_d1aafb2e7c', lang))

    text = t('b_configure_broadcast_button_794d7b35de', lang, fa_parts=lambda: (f'{selected_count}', f'{layout_name}'), en_parts=lambda: (f'{selected_count}', f'{layout_name}'))
    has_en = bool(broadcast_data.get("en_caption"))
    markup = _broadcast_button_setup_markup(buttons, lang, button_styles, layout, has_en_version=has_en)
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            try:
                await callback.message.edit_reply_markup(reply_markup=markup)
            except Exception:
                pass


async def _show_broadcast_button_setup(message: Message, admin_id: int):
    state = user_states[admin_id]
    lang = get_user(admin_id).get("lang", "fa")
    broadcast_data = state["broadcast_data"]
    buttons = broadcast_data.setdefault("buttons", [])
    layout = broadcast_data.get("layout", "single")
    button_styles = broadcast_data.setdefault("button_styles", {})
    has_en = bool(broadcast_data.get("en_caption"))

    selected_count = len(buttons)
    layout_name = (t('2_columns_293ed635ba', lang) if layout == 'double' else t('1_column_d1aafb2e7c', lang))

    text = t('b_configure_broadcast_button_794d7b35de', lang, fa_parts=lambda: (f'{selected_count}', f'{layout_name}'), en_parts=lambda: (f'{selected_count}', f'{layout_name}'))
    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=_broadcast_button_setup_markup(
            buttons, lang, button_styles, layout, has_en_version=has_en
        ),
    )


async def _is_admin_broadcasting(message: Message) -> bool:
    """چک می‌کنه که ادمین در حالت broadcast هست یا نه"""
    admin_id_int = _get_admin_id()
    if not getattr(message, "from_user", None) or message.from_user.id != admin_id_int:
        return False
    return bool(user_states.get(message.from_user.id, {}).get('awaiting_broadcast'))


# ─────────────────────────────────────────────────────────────
# Handlers: برودکست
# ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_broadcast")
@admin_only
async def admin_broadcast_start(callback: CallbackQuery):
    """شروع ارسال پیام همگانی با انتخاب نوع"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    text = t('b_broadcast_message_b_select_be5f0d2a0f', lang)
    
    buttons = [
        [InlineKeyboardButton(text=t('text_f2e36ab0e8', lang), callback_data="broadcast_type_text")],
        [InlineKeyboardButton(text=t('photo_b8d47e3a2a', lang), callback_data="broadcast_type_photo")],
        [InlineKeyboardButton(text=t('file_86a40c11c8', lang), callback_data="broadcast_type_file")],
        [InlineKeyboardButton(text=t('audio_f6dac719fd', lang), callback_data="broadcast_type_audio")],
        [InlineKeyboardButton(text=t('cancel_ed04d2e1eb', lang), callback_data="admin_panel")]
    ]
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    await safe_answer(callback)


@router.callback_query(F.data.startswith("broadcast_type_"))
@admin_only
async def broadcast_type_selected(callback: CallbackQuery):
    """انتخاب نوع پیام همگانی"""
    broadcast_type = callback.data.replace("broadcast_type_", "")
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    user_states[callback.from_user.id] = {
        'awaiting_broadcast': True,
        'broadcast_type': broadcast_type,
        'timestamp': now_tehran_iso()
    }
    
    type_names = {
        'text': (t('text_1ddeb1ca57', lang)),
        'photo': (t('photo_3359ead312', lang)),
        'file': (t('file_55e418fe3a', lang)),
        'audio': (t('audio_6ead3a919b', lang))
    }
    
    type_name = type_names.get(broadcast_type, broadcast_type)
    
    await callback.message.answer(
        t('b_broadcast_b_please_send_yo_14fe6bfe06', lang, fa_parts=lambda: (f'{type_name}', f"{('متن' if broadcast_type == 'text' else 'فایل')}", f"{('قالب بندی تلگرام و تگ های HTML پشتیبانی می شوند.' if broadcast_type == 'text' else '')}"), en_parts=lambda: (f'{type_name}', f"{('text' if broadcast_type == 'text' else 'file')}", f"{('Telegram formatting and HTML tags are supported.' if broadcast_type == 'text' else '')}")),
        parse_mode=ParseMode.HTML
    )
    await safe_answer(callback)


@router.callback_query(
    F.data.startswith("broadcast_button_")
    | F.data.startswith("broadcast_url_")
    | F.data.in_({"broadcast_layout_toggle", "broadcast_buttons_clear", "broadcast_buttons_done", "cancel_broadcast"})
)
@admin_only
async def configure_broadcast_buttons(callback: CallbackQuery):
    admin_id = callback.from_user.id
    lang = get_user(admin_id).get("lang", "fa")
    state = user_states.get(admin_id, {})
    broadcast_data = state.get("broadcast_data")
    action = callback.data

    if action == "cancel_broadcast":
        user_states.pop(admin_id, None)
        await callback.message.edit_text(t('broadcast_cancelled_1a86cd82b1', lang))
        await callback.answer()
        return

    if not state.get("awaiting_broadcast_button_setup") or not isinstance(broadcast_data, dict):
        return await callback.answer(t('this_request_has_expired_3208870b44', lang), show_alert=True)

    selected = broadcast_data.setdefault("buttons", [])

    if action == "broadcast_buttons_clear":
        selected.clear()
        broadcast_data.setdefault("button_styles", {}).clear()
        await _update_broadcast_setup_message(callback, admin_id)
        await callback.answer(t('all_buttons_cleared_51d1c7349d', lang))
        return

    if action == "broadcast_layout_toggle":
        current_layout = broadcast_data.get("layout", "single")
        broadcast_data["layout"] = "double" if current_layout == "single" else "single"
        await _update_broadcast_setup_message(callback, admin_id)
        layout_name = (t('2_columns_293ed635ba', lang) if broadcast_data['layout'] == 'double' else t('1_column_d1aafb2e7c', lang))
        await callback.answer(f"📐 {layout_name}")
        return

    if action.startswith("broadcast_url_info:"):
        u_id = action.split(":", 1)[1]
        ub = next((b for b in selected if isinstance(b, dict) and b.get("url_id") == u_id), None)
        if ub:
            await callback.answer(f"🔗 {ub.get('label')}\n🌐 {ub.get('url')}", show_alert=True)
        else:
            await callback.answer(t('link_not_found_2cee3add07', lang))
        return

    if action.startswith("broadcast_url_delete:"):
        u_id = action.split(":", 1)[1]
        ub = next((b for b in selected if isinstance(b, dict) and b.get("url_id") == u_id), None)
        if ub:
            selected.remove(ub)
        await _update_broadcast_setup_message(callback, admin_id)
        await callback.answer(t('url_button_removed_8b977c2064', lang))
        return

    if action.startswith("broadcast_url_style:"):
        u_id = action.split(":", 1)[1]
        ub = next((b for b in selected if isinstance(b, dict) and b.get("url_id") == u_id), None)
        if ub:
            styles = [None, "primary", "success", "danger"]
            current = ub.get("style")
            next_style = styles[(styles.index(current) + 1) % len(styles)] if current in styles else None
            ub["style"] = next_style
            await _update_broadcast_setup_message(callback, admin_id)
            await callback.answer()
        return

    if action == "broadcast_button_add_url":
        if len(selected) >= 10:
            return await callback.answer(
                t('maximum_10_buttons_allowed_347f6e2a23', lang),
                show_alert=True,
            )
        state["awaiting_broadcast_button_setup"] = False
        state["awaiting_broadcast_url"] = True
        await callback.message.answer(
            t('send_the_label_and_url_on_on_77d74cf055', lang),
            parse_mode=ParseMode.HTML,
        )
        await callback.answer()
        return

    if action.startswith("broadcast_button_toggle:"):
        button_name = action.split(":", 1)[1]
        valid_keys = set(get_broadcast_actions().keys()) | {"translate_fa"}
        if button_name not in valid_keys:
            return await callback.answer(t('invalid_button_24d4583f1c', lang), show_alert=True)
        item = next(
            (button for button in selected
             if isinstance(button, dict) and button.get("action") == button_name),
            None,
        )
        if item:
            selected.remove(item)
        elif len(selected) >= 10:
            return await callback.answer(t('maximum_10_buttons_allowed_347f6e2a23', lang), show_alert=True)
        else:
            selected.append({
                "action": button_name,
                "style": broadcast_data.setdefault("button_styles", {}).get(button_name),
            })
        await _update_broadcast_setup_message(callback, admin_id)
        await callback.answer()
        return

    if action.startswith("broadcast_button_style:"):
        button_name = action.split(":", 1)[1]
        valid_keys = set(get_broadcast_actions().keys()) | {"translate_fa"}
        if button_name not in valid_keys:
            return await callback.answer(t('invalid_button_24d4583f1c', lang), show_alert=True)
        styles = [None, "primary", "success", "danger"]
        style_map = broadcast_data.setdefault("button_styles", {})
        item = next(
            (button for button in selected
             if isinstance(button, dict) and button.get("action") == button_name),
            None,
        )
        current = item.get("style") if item else style_map.get(button_name)
        next_style = styles[(styles.index(current) + 1) % len(styles)] if current in styles else None
        style_map[button_name] = next_style
        if item:
            item["style"] = next_style
        await _update_broadcast_setup_message(callback, admin_id)
        await callback.answer()
        return

    if action == "broadcast_buttons_done":
        state["awaiting_broadcast_button_setup"] = False
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        return await preview_broadcast(callback)

    return await callback.answer(
        t('invalid_button_request_c4a4e3c9fb', lang),
        show_alert=True,
    )


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_broadcast'))
async def admin_broadcast_send(message: Message):
    """ارسال پیام همگانی با پشتیبانی از انواع مختلف فایل"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_59fa2371a6', lang))
        return
    
    state = user_states.get(admin_id, {})
    broadcast_type = state.get('broadcast_type', 'text')
    media_content = None
    media_kind = None
    caption = None
    parse_mode = None
    file_name = None
    
    if broadcast_type == 'text':
        if not message.text:
            await message.reply(t('please_send_text_458c698cac', lang))
            return
        caption = message.text
        parse_mode = None if message.entities else detect_safe_parse_mode(caption)
    
    elif broadcast_type == 'photo':
        if not message.photo:
            await message.reply(t('please_send_a_photo_fa1eec7955', lang))
            return
        media_content = message.photo[-1].file_id
        media_kind = "photo"
        caption = message.caption or ""
        parse_mode = None if message.caption_entities else detect_safe_parse_mode(caption)
        file_name = f"photo_{now_tehran().strftime('%Y%m%d_%H%M%S')}.jpg"
        logger.info('📸 Broadcast image media received')
    
    elif broadcast_type == 'file':
        if not message.document and not message.video:
            await message.reply(t('please_send_a_file_8c2f649568', lang))
            return
        
        if message.document:
            media_content = message.document.file_id
            media_kind = "document"
            file_name = message.document.file_name or f"file_{now_tehran().strftime('%Y%m%d_%H%M%S')}"
        elif message.video:
            media_content = message.video.file_id
            media_kind = "video"
            file_name = message.video.file_name or f"video_{now_tehran().strftime('%Y%m%d_%H%M%S')}"
        
        caption = message.caption or ""
        parse_mode = None if message.caption_entities else detect_safe_parse_mode(caption)
        logger.info('📄 Broadcast file received')
    
    elif broadcast_type == 'audio':
        if not message.audio and not message.voice:
            await message.reply(t('please_send_an_audio_file_046acf5d1a', lang))
            return
        
        audio_subtype = None
        if message.audio:
            media_content = message.audio.file_id
            media_kind = "audio"
            file_name = message.audio.file_name or f"audio_{now_tehran().strftime('%Y%m%d_%H%M%S')}"
            audio_subtype = 'audio'
        elif message.voice:
            media_content = message.voice.file_id
            media_kind = "voice"
            file_name = f"voice_{now_tehran().strftime('%Y%m%d_%H%M%S')}.ogg"
            audio_subtype = 'voice'
        
        caption = message.caption or ""
        parse_mode = None if message.caption_entities else detect_safe_parse_mode(caption)
        logger.info(f"🎵 Broadcast audio received - subtype: {audio_subtype}")
    
    else:
        await message.reply(t('unknown_message_type_8e34c38996', lang))
        return
        
    recipient_count = len(_broadcast_recipient_ids())
    audio_subtype_value = locals().get('audio_subtype', None)

    broadcast_data = {
        'type': broadcast_type,
        'media': media_content,
        'caption': caption,
        'parse_mode': parse_mode,
        'file_name': file_name,
        'media_kind': media_kind,
        'subtype': audio_subtype_value,
        'source_chat_id': message.chat.id,
        'source_message_id': message.message_id,
        'buttons': [],
    }
    
    user_states[admin_id] = {
        'awaiting_broadcast_en_choice': True,
        'broadcast_data': broadcast_data,
        'users_count': recipient_count,
    }
    await message.reply(
        t('broadcast_ask_en_prompt', lang),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('broadcast_ask_en_yes', lang), callback_data="broadcast_ask_en_yes", style="primary")],
            [InlineKeyboardButton(text=t('broadcast_ask_en_no', lang), callback_data="broadcast_ask_en_no", style="success")],
            [InlineKeyboardButton(text=t('cancel_broadcast_19a887c8b6', lang), callback_data="cancel_broadcast", style="danger")],
        ]),
    )


@router.callback_query(F.data == "broadcast_ask_en_no")
@admin_only
async def broadcast_ask_en_no(callback: CallbackQuery):
    admin_id = callback.from_user.id
    lang = get_user(admin_id).get("lang", "fa")
    state = user_states.get(admin_id, {})
    if not state.get("broadcast_data"):
        return await callback.answer(t('broadcast_state_expired_bc67a6d440', lang), show_alert=True)
    state["awaiting_broadcast_en_choice"] = False
    state["awaiting_broadcast_en"] = False
    state["awaiting_broadcast_button_setup"] = True
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_broadcast_button_setup(callback.message, admin_id)
    await safe_answer(callback)


@router.callback_query(F.data == "broadcast_ask_en_yes")
@admin_only
async def broadcast_ask_en_yes(callback: CallbackQuery):
    admin_id = callback.from_user.id
    lang = get_user(admin_id).get("lang", "fa")
    state = user_states.get(admin_id, {})
    if not state.get("broadcast_data"):
        return await callback.answer(t('broadcast_state_expired_bc67a6d440', lang), show_alert=True)
    state["awaiting_broadcast_en_choice"] = False
    state["awaiting_broadcast_en"] = True
    await callback.message.edit_text(t('broadcast_send_en_text', lang), parse_mode=ParseMode.HTML)
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get("awaiting_broadcast_en"))
async def admin_broadcast_receive_en(message: Message):
    admin_id = message.from_user.id
    lang = get_user(admin_id).get("lang", "fa")
    state = user_states.get(admin_id, {})
    broadcast_data = state.get("broadcast_data")
    if message.text and message.text.strip().lower() == "/cancel":
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_59fa2371a6', lang))
        return
    if not isinstance(broadcast_data, dict):
        user_states.pop(admin_id, None)
        await message.reply(t('broadcast_state_expired_bc67a6d440', lang))
        return

    en_caption = message.text or message.caption or ""
    if not en_caption.strip():
        await message.reply(t('message_cannot_be_empty_9669d7f21e', lang))
        return

    entities = message.entities if message.text else message.caption_entities
    broadcast_data["en_caption"] = en_caption
    broadcast_data["en_parse_mode"] = None if entities else detect_safe_parse_mode(en_caption)
    if message.text:
        broadcast_data["en_source_chat_id"] = message.chat.id
        broadcast_data["en_source_message_id"] = message.message_id

    state["awaiting_broadcast_en"] = False
    state["awaiting_broadcast_button_setup"] = True
    await _show_broadcast_button_setup(message, admin_id)


@router.callback_query(F.data.startswith("broadcast_translate:"))
async def broadcast_translate_toggle(callback: CallbackQuery):
    """تغییر زبان پیام برودکست بین فارسی و انگلیسی هنگام کلیک کاربر روی دکمه ترجمه"""
    user_id = callback.from_user.id
    user_lang = get_user(user_id).get("lang", "fa")
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer(t('broadcast_translate_not_found', user_lang), show_alert=True)
        return
    _, broadcast_id, target_lang = parts[0], parts[1], parts[2]
    record = (configs_pool.get("broadcast_translations", {}) or {}).get(broadcast_id)
    if not isinstance(record, dict):
        await callback.answer(t('broadcast_translate_not_found', user_lang), show_alert=True)
        return

    if target_lang == "fa":
        new_text = record.get("fa_caption") or ""
        pm = ParseMode.HTML if record.get("fa_html") else None
    else:
        new_text = record.get("en_caption") or record.get("fa_caption") or ""
        pm = ParseMode.HTML if record.get("en_html") else None

    markup = _broadcast_keyboard(
        record.get("buttons", []),
        user_lang,
        record.get("layout", "single"),
        broadcast_id=broadcast_id,
        view_lang=target_lang,
        has_en_version=bool(record.get("en_caption")),
    )
    try:
        if callback.message.text is not None:
            await callback.message.edit_text(new_text, parse_mode=pm, reply_markup=markup)
        else:
            await callback.message.edit_caption(caption=new_text, parse_mode=pm, reply_markup=markup)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"Broadcast translate edit failed: {e}")
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get("awaiting_broadcast_url"))
async def admin_broadcast_add_url_button(message: Message):
    admin_id = message.from_user.id
    lang = get_user(admin_id).get("lang", "fa")
    state = user_states.get(admin_id, {})
    if message.text and message.text.strip().lower() == "/cancel":
        state["awaiting_broadcast_url"] = False
        state["awaiting_broadcast_button_setup"] = True
        await message.reply(t('adding_a_url_was_cancelled_e7993caab9', lang))
        await _show_broadcast_button_setup(message, admin_id)
        return

    if not message.text or "|" not in message.text:
        await message.reply(
            t('invalid_format_example_code_6fc866530d', lang),
            parse_mode=ParseMode.HTML,
        )
        return

    label, raw_url = (part.strip() for part in message.text.split("|", 1))
    if not 1 <= len(label) <= 64 or not _is_safe_broadcast_url(raw_url):
        await message.reply(
            t('button_text_must_be_1_64_cha_998ed4f9df', lang)
        )
        return

    broadcast_data = state.get("broadcast_data")
    if not isinstance(broadcast_data, dict):
        user_states.pop(admin_id, None)
        await message.reply(t('broadcast_state_expired_bc67a6d440', lang))
        return
    buttons = broadcast_data.setdefault("buttons", [])
    if len(buttons) >= 10:
        await message.reply(t('maximum_10_buttons_allowed_b57797b27b', lang))
        return

    url_id = f"url_{uuid.uuid4().hex[:6]}"
    url_data = {"action": "url", "url_id": url_id, "label": label, "url": str(URL(raw_url)), "style": None}
    buttons.append(url_data)
    state["awaiting_broadcast_url"] = False
    state["awaiting_broadcast_button_setup"] = True
    await message.reply(t('url_button_added_successfull_6583453e94', lang))
    await _show_broadcast_button_setup(message, admin_id)


@router.callback_query(F.data == "preview_broadcast")
@admin_only
async def preview_broadcast(callback: CallbackQuery):
    """پیش‌نمایش پیام همگانی - فقط به ادمین"""
    admin_id = callback.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    state = user_states.get(admin_id, {})
    broadcast_data = state.get('broadcast_data', {})
    users_count = state.get('users_count', 0)
    
    if not broadcast_data:
        await callback.answer(
            t('no_data_b55e98bf03', lang),
            show_alert=True
        )
        return
    state["broadcast_preview_verified"] = False
    
    broadcast_type = broadcast_data.get('type', 'text')
    subtype = broadcast_data.get('subtype')
    
    type_display = {
        'text': '📝 متن',
        'photo': '🖼️ عکس',
        'file': '📄 فایل',
        'audio': '🎵 موزیک' if subtype != 'voice' else '🎤 ویس'
    }.get(broadcast_type, broadcast_type)
    
    preview_header = t('b_broadcast_preview_b_target_836ad052b6', lang, fa_parts=lambda: (f'{users_count}', f'{type_display}'), en_parts=lambda: (f'{users_count}', f'{type_display}'))
    
    bot_inst = callback.bot or get_bot()
    try:
        await bot_inst.send_message(admin_id, preview_header, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error sending preview header: {e}")
    
    preview_sent = False
    try:
        await _send_broadcast_message(admin_id, broadcast_data, "fa")
        if broadcast_data.get("en_caption"):
            await _send_broadcast_message(admin_id, broadcast_data, "en")
        preview_sent = True
        state["broadcast_preview_verified"] = True
    
    except Exception as e:
        logger.error(f"❌ Error sending preview: {e}", exc_info=True)
        err_msg = html.escape(str(e)[:150])
        await bot_inst.send_message(
            admin_id,
            t('preview_error_code_code_5c3a6b9155', lang, fa_parts=lambda: (err_msg,), en_parts=lambda: (err_msg,)),
            parse_mode=ParseMode.HTML
        )
        return
    
    if preview_sent:
        action_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('send_to_users_dd1bcbc90b', lang, fa_parts=lambda: (f'{users_count}',), en_parts=lambda: (f'{users_count}',)),
                callback_data="confirm_broadcast",
                style="success"
            )],
            [InlineKeyboardButton(
                text=t('preview_again_ff637d6ad5', lang),
                callback_data="preview_broadcast",
                style="primary"
            )],
            [InlineKeyboardButton(
                text=t('cancel_0784ed286e', lang),
                callback_data="cancel_broadcast",
                style="danger"
            )]
        ])
        
        footer = t('i_preview_completed_i_send_t_6348153d1f', lang)
        
        try:
            await bot_inst.send_message(
                admin_id,
                footer,
                reply_markup=action_keyboard,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error sending preview footer: {e}")
    
    await safe_answer(callback, t('preview_sent_77ab54200b', lang))


@router.callback_query(F.data == "broadcast_back_to_main")
async def broadcast_back_to_main(callback: CallbackQuery):
    """بازگشت به منوی اصلی از پیام همگانی - پیام برودکست پاک می‌شه"""
    user_id = callback.from_user.id
    
    try:
        await callback.message.delete()
    except Exception as e:
        logger.debug(f"Failed to delete broadcast message: {e}")
    
    lang = get_user(user_id).get('lang', 'fa')
    admin_id_int = _get_admin_id()
    is_admin = (user_id == admin_id_int)
    
    text = t('main_menu_c928863059', lang, fa_parts=lambda: (f"{premium_emoji('rocket', '🚀')}",), en_parts=lambda: (f"{premium_emoji('rocket', '🚀')}",))
    
    bot_inst = callback.bot or get_bot()
    try:
        await callback.message.answer(
            text,
            reply_markup=_get_main_keyboard(is_admin, lang, user_id)
        )
    except Exception as e:
        logger.error(f"Error displaying the main menu after broadcast: {e}")
        try:
            await bot_inst.send_message(
                user_id, text,
                reply_markup=_get_main_keyboard(is_admin, lang, user_id)
            )
        except Exception:
            pass
    
    await safe_answer(callback)


@router.callback_query(F.data == "retry_broadcast_failed")
@admin_only
async def retry_broadcast_failed(callback: CallbackQuery):
    """ارسال مجدد به کاربرانی که پیام را دریافت نکرده‌اند"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    await callback.message.edit_text(
        t('retrying_failed_users_509d890b44', lang)
    )
    
    await callback.message.edit_text(
        t('retry_for_failed_users_is_un_8b9d5ec43b', lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('back_to_panel_63039f103a', lang),
                callback_data="admin_panel"
            )]
        ])
    )
    await safe_answer(callback)


@router.callback_query(F.data == "confirm_broadcast")
@admin_only
async def confirm_broadcast(callback: CallbackQuery):
    """تأیید نهایی و ارسال پیام همگانی"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    state = user_states.get(callback.from_user.id, {})
    broadcast_data = state.get('broadcast_data', {})
    
    if not broadcast_data:
        await callback.answer(t('no_data_to_send_254950488c', lang), show_alert=True)
        return
    if not state.get("broadcast_preview_verified"):
        await callback.answer(
            t('please_review_a_successful_p_7f38e3de11', lang),
            show_alert=True,
        )
        return
    if state.get("broadcast_sending"):
        await callback.answer(t('broadcast_is_already_running_297a2bb5bc', lang), show_alert=True)
        return
    if "source_chat_id" not in broadcast_data or "source_message_id" not in broadcast_data:
        await callback.answer(t('the_source_message_is_unavai_c395fdfd89', lang), show_alert=True)
        return
        
    state["broadcast_sending"] = True
    if broadcast_data.get("en_caption"):
        _ensure_broadcast_translation_record(broadcast_data)
        schedule_save(2.0)
    logger.info("📢 starting broadcast message:")
    logger.info(f" - type: {broadcast_data.get('type')}")
    logger.info(f" - user count: {len(users)}")
    status_msg = await callback.message.answer(
        t('sending_broadcast_29efaf198e', lang)
    )
    logger.info(f"✅ status message with message_id={status_msg.message_id} sent")
    sent_count = 0
    failed_count = 0
    failed_users = []
    users_list = _broadcast_recipient_ids()
    total_users = len(users_list)
    
    broadcast_type = broadcast_data.get('type', 'text')
    
    for i, uid in enumerate(users_list):
        try:
            user_id = uid
            user_lang = get_user(user_id).get('lang', 'fa')
            await _send_broadcast_message(user_id, broadcast_data, user_lang)
            
            sent_count += 1
            if (i + 1) % 10 == 0:
                progress_text = t('sending_cbe104fdfd', lang, fa_parts=lambda: (f'{i + 1}', f'{total_users}'), en_parts=lambda: (f'{i + 1}', f'{total_users}'))
                try:
                    await status_msg.edit_text(progress_text)
                except Exception as e:
                    logger.warning(f"⚠️ Error updating status message: {e}")
                    try:
                        await status_msg.delete()
                    except Exception:
                        pass
                    status_msg = await callback.message.answer(progress_text)
            
            await asyncio.sleep(0.1)
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"❌ Error sending to user {uid}: {error_str}")
            failed_count += 1
            failed_users.append(str(uid))
            
    user_states.pop(callback.from_user.id, None)
    try:
        if status_msg:
            await status_msg.delete()
            logger.info(f"✅ status message with message_id={status_msg.message_id} deleted")
        else:
            logger.warning('⚠️ Status message does not exist')
    except Exception as e:
        logger.warning(f"⚠️ Error deleting status message: {e}")
        try:
            if "message to delete not found" in str(e):
                logger.info('ℹ️ Status message had already been deleted')
            else:
                logger.error(f"❌ Error deleting status message: {e}")
        except Exception:
            pass
            
    failed_preview = ', '.join(str(u) for u in failed_users[:10])
    result_text = f"""
✅ <b>پیام همگانی ارسال شد!</b>

📤 موفق: {sent_count}
❌ ناموفق: {failed_count}
📊 تعداد کل: {total_users}
📝 نوع: {broadcast_type}
🕐 زمان: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}

{f"❌ کاربران ناموفق: {failed_preview}" if failed_users else ""}
{f"⚠️ {len(failed_users) - 10} کاربر دیگر..." if len(failed_users) > 10 else ""}
"""
    keyboard_rows = []
    
    if failed_users:
        keyboard_rows.append([
            InlineKeyboardButton(
                text=t('retry_failed_users_aa0c952865', lang),
                callback_data="retry_broadcast_failed",
                style="primary"
            )
        ])
    
    keyboard_rows.append([
        InlineKeyboardButton(
            text=t('new_broadcast_ec3bfc5416', lang),
            callback_data="admin_broadcast",
            style="primary"
        )
    ])
    
    keyboard_rows.append([
        InlineKeyboardButton(
            text=t('back_to_panel_63039f103a', lang),
            callback_data="admin_panel"
        )
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    try:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(result_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        logger.info('✅ Report sent')
    except Exception as e:
        logger.error(f"❌ Error sending report: {e}")
        await callback.message.answer(result_text, parse_mode=ParseMode.HTML)
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_broadcast_test")
@admin_only
async def admin_broadcast_test(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    admin_id_int = _get_admin_id()
    
    await callback.message.edit_text(t('i18n_broadcast_test_sending', lang))
    try:
        test_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('main_menu_0cdd07a7cc', lang),
                callback_data="broadcast_back_to_main",
                style="primary"
            )]
        ])
        
        bot_inst = callback.bot or get_bot()
        await bot_inst.send_message(
            admin_id_int,
            t('i18n_broadcast_test_message', lang),
            reply_markup=test_keyboard
        )
        await callback.message.edit_text(
            t('i18n_broadcast_test_success', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('send_to_all_47129fb8fa', lang), callback_data="admin_broadcast")],
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
            ])
        )
    except Exception:
        await callback.message.edit_text(t('i18n_broadcast_test_failed', lang))
    
    await safe_answer(callback)

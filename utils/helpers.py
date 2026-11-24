"""Helpers shared by callback handlers."""

import html
import logging
from typing import Any, Optional
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)


async def safe_answer(callback: CallbackQuery, text: str = "", alert: bool = False) -> None:
    """Answer a callback while ignoring failures from expired or answered queries."""
    try:
        await callback.answer(text, show_alert=alert)
    except Exception:
        pass


def safe_html(value: Any, fallback: str = "—", max_length: Optional[int] = None) -> str:
    """Safely escape a value for inclusion in HTML-formatted messages."""
    if value is None:
        return fallback
    s = str(value).strip()
    if not s:
        return fallback
    if max_length is not None and len(s) > max_length:
        s = s[:max_length] + "..."
    s = ''.join(c for c in s if c.isprintable() or c in ' \t\n')
    return html.escape(s, quote=True)


def premium_emoji(name: str, fallback: str = "📌") -> str:
    """دریافت ایموجی پرمیوم با fallback ایمن"""
    try:
        from emoji_sticker_system import premium_emoji as _pe
        return _pe(name, fallback)
    except Exception:
        return fallback


async def safe_edit_message(
    callback: CallbackQuery,
    text: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = ParseMode.HTML,
) -> None:
    """ویرایش امن پیام با پشتیبانی از انواع پیام و HTML"""
    try:
        message = callback.message
        if not message:
            return

        # بررسی نوع پیام
        has_caption = any([
            getattr(message, "photo", None),
            getattr(message, "document", None),
            getattr(message, "video", None),
            getattr(message, "audio", None),
            getattr(message, "animation", None),
        ])

        if has_caption:
            if text:
                await message.edit_caption(
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            elif reply_markup:
                await message.edit_reply_markup(reply_markup=reply_markup)
        elif getattr(message, "text", None):
            if text and reply_markup:
                await message.edit_text(
                    text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
            elif reply_markup:
                await message.edit_reply_markup(reply_markup=reply_markup)
            elif text:
                await message.edit_text(
                    text,
                    parse_mode=parse_mode,
                )
        else:
            try:
                await message.delete()
            except Exception:
                pass
            if text:
                await message.answer(
                    text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
    except Exception as e:
        error_str = str(e)
        if "message is not modified" in error_str:
            logger.debug(f"Message not modified for user {callback.from_user.id}")
            return
        elif "there is no text in the message to edit" in error_str:
            logger.warning("⚠️ Message cannot be edited; deleting and sending a new one...")
            try:
                if callback.message:
                    await callback.message.delete()
            except Exception:
                pass
            if text and callback.message:
                try:
                    await callback.message.answer(
                        text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                    )
                except Exception as e2:
                    logger.error(f"Error sending new message: {e2}")
            return
        elif "message to edit not found" in error_str:
            logger.warning("⚠️ Message not found; sending a new message...")
            if text and callback.message:
                try:
                    await callback.message.answer(
                        text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                    )
                except Exception as e2:
                    logger.error(f"Error sending new message: {e2}")
            return
        elif "message can't be edited" in error_str:
            logger.warning("⚠️ Message cannot be edited (it may be outdated)")
            try:
                if callback.message:
                    await callback.message.delete()
            except Exception:
                pass
            if text and callback.message:
                try:
                    await callback.message.answer(
                        text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                    )
                except Exception as e2:
                    logger.error(f"Error sending new message: {e2}")
            return
        else:
            logger.error(f"Error in safe_edit_message: {e}")


def get_back_only_keyboard(lang: str = "fa") -> InlineKeyboardMarkup:
    """ساخت کیبورد تک‌دکمه بازگشت به منوی اصلی"""
    from aiogram.types import InlineKeyboardButton
    from strings import t
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🏠 {t('main_menu_9ae3456442', lang)}", callback_data="back_to_main", style="danger")]
    ])


async def notify_blacklisted_user(user_id: int, message=None):
    """ارسال پیام به کاربر مسدود شده"""
    import sys
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "notify_blacklisted_user"):
        return await main_mod.notify_blacklisted_user(user_id, message)
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from strings import t
    from user_manager import get_user
    from config import SUPPORT_USERNAME
    try:
        lang = get_user(user_id).get('lang', 'fa')
        support_contact = SUPPORT_USERNAME.strip() if SUPPORT_USERNAME and SUPPORT_USERNAME.strip() else "@my_name_is_navid"
        emoji_result = premium_emoji('access_denied', '⛔')
        text = t('b_access_blocked_b_you_are_b_fdd3221c25', lang, fa_parts=lambda: (f'{emoji_result}', f'{support_contact}'), en_parts=lambda: (f'{emoji_result}', f'{support_contact}'))
        support_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t('contact_support_7f7c200a77', lang), callback_data="support_create_ticket")
        ]])
        if message:
            await message.reply(text, reply_markup=support_keyboard, parse_mode=ParseMode.HTML)
        elif main_mod and hasattr(main_mod, "bot"):
            await main_mod.bot.send_message(user_id, text, reply_markup=support_keyboard, parse_mode=ParseMode.HTML)
        return True
    except Exception as e:
        logger.error(f"❌ Error sending message to blocked user {user_id}: {e}")
        return False


def get_order_category_name(order: dict, lang: str = "fa") -> str:
    """دریافت نام دسته برای یک سفارش با fallback چند مرحله‌ای"""
    from database import READY_PACKAGES
    if lang == "en":
        name_en = order.get('category_name_en')
        if name_en and str(name_en).strip():
            return str(name_en).strip()
        name_fa = order.get('category_name')
        if name_fa and str(name_fa).strip():
            return str(name_fa).strip()
    else:
        name_fa = order.get('category_name')
        if name_fa and str(name_fa).strip():
            return str(name_fa).strip()
        name_en = order.get('category_name_en')
        if name_en and str(name_en).strip():
            return str(name_en).strip()

    cat_id = order.get('category_id')
    if cat_id:
        for cat in READY_PACKAGES.get('categories', []):
            if cat.get('id') == cat_id:
                if lang == "en":
                    return cat.get('name_en') or cat.get('name') or ""
                return cat.get('name') or ""
    return ""


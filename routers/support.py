"""
routers/support.py
------------------
سیستم تیکت‌های پشتیبانی، چت دوطرفه با ادمین، ثبت بازخورد و کنترل وضعیت ورودی
"""

import asyncio
import html
import sys
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.enums import ParseMode

from config import ADMIN_ID_INT
from database import (
    chats,
    feedbacks,
    save_all,
    get_valid_orders,
    now_tehran,
    now_tehran_iso,
    BLACKLIST,
)
from user_manager import get_user, user_states
from strings import t
from utils.helpers import (
    safe_answer,
    get_back_only_keyboard,
    get_order_category_name,
    notify_blacklisted_user,
    premium_emoji,
)
from logger_system import logger
from routers.admin_packages import log_system

router = Router(name="support")

_bot: Optional[Bot] = None


def set_bot(bot_instance: Bot):
    global _bot
    _bot = bot_instance


def get_bot() -> Optional[Bot]:
    global _bot
    if _bot is not None:
        return _bot
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "bot"):
        return getattr(main_mod, "bot")
    return None


def _get_main_keyboard(is_admin: bool = False, lang: str = "fa", user_id: Optional[int] = None) -> InlineKeyboardMarkup:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "get_main_keyboard"):
        return main_mod.get_main_keyboard(is_admin, lang, user_id)
    return InlineKeyboardMarkup(inline_keyboard=[])


async def block_unauthorized(message: Message, user_id: int) -> bool:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "block_unauthorized"):
        return await main_mod.block_unauthorized(message, user_id)
    state = user_states.get(user_id, {})
    if state.get('awaiting_receipt') or state.get('awaiting_chat') or user_id == ADMIN_ID_INT:
        return False
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id, message)
        return True
    return False


def create_chat(
    user_id: int,
    feedback_id: Optional[int] = None,
    config_order_id: Optional[int] = None,
) -> int:
    """ایجاد چت جدید"""
    chat_id = max((int(chat.get('id', 0)) for chat in chats.values()), default=0) + 1
    chats[str(chat_id)] = {
        'id': chat_id,
        'user_id': user_id,
        'feedback_id': feedback_id,
        'config_order_id': config_order_id,
        'kind': 'ticket' if feedback_id is None else 'feedback',
        'user_input_enabled': True,
        'status': 'open',  # open, closed
        'messages': [],
        'created_at': now_tehran_iso(),
        'updated_at': now_tehran_iso()
    }
    save_all()
    return chat_id


def add_message(chat_id: int, sender: str, text: str):
    """اضافه کردن پیام به چت"""
    cid = str(chat_id)
    if cid in chats:
        chats[cid]['messages'].append({
            'sender': sender,  # 'admin' یا 'user'
            'text': text,
            'time': now_tehran().strftime('%Y-%m-%d %H:%M:%S')
        })
        chats[cid]['updated_at'] = now_tehran_iso()
        save_all()


async def close_chat(chat_id: int, closed_by: str = "user", notify_other: bool = True):
    """بستن چت و اطلاع‌رسانی به طرف مقابل."""
    cid = str(chat_id)
    bot = get_bot()

    chat = chats.get(cid)
    if chat and chat.get('status') != 'closed':
        user_id = chat.get('user_id')
        is_ticket = chat.get('kind') == 'ticket'
        if log_system and user_id:
            asyncio.create_task(log_system.log_chat_closed(chat_id, user_id, closed_by))
        chat['status'] = 'closed'
        chat['closed_by'] = closed_by
        chat['closed_at'] = now_tehran_iso()
        chat['updated_at'] = now_tehran_iso()
        if is_ticket and user_id:
            _clear_ticket_input_state(user_id, chat_id)
        save_all()
        if notify_other and user_id and bot:
            if closed_by == "user":
                # کاربر تیکت را بسته است. فقط در صورتی به ادمین پیام بده که کاربر خود ادمین نباشد
                if user_id != ADMIN_ID_INT:
                    admin_lang = get_user(ADMIN_ID_INT).get('lang', 'fa')
                    notification = (t('ticket_has_been_successfully_5a5aa318b8', admin_lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',)) if is_ticket else t('conversation_has_been_succes_ef08ceb631', admin_lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',)))
                    try:
                        await bot.send_message(
                            ADMIN_ID_INT,
                            notification,
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="👤 مشاهده کاربر", callback_data=f"admin_user_{user_id}"),
                                InlineKeyboardButton(text="💬 چت‌های فعال", callback_data="admin_chats"),
                            ]]),
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception as e:
                        logger.error(f"Error sending ticket-closure notification to admin: {e}")
            elif closed_by == "admin":
                # ادمین تیکت را بسته است. فقط در صورتی به کاربر پیام بده که کاربر خود ادمین نباشد
                if user_id != ADMIN_ID_INT:
                    recipient_lang = get_user(user_id).get('lang', 'fa')
                    notification = (t('ticket_has_been_successfully_5a5aa318b8', recipient_lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',)) if is_ticket else t('conversation_has_been_succes_ef08ceb631', recipient_lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',)))
                    try:
                        await bot.send_message(
                            user_id,
                            notification,
                            reply_markup=ReplyKeyboardRemove(),
                        )
                        msg_text = f"{premium_emoji('rocket', '🚀')} <b>{t('main_menu_9ae3456442', recipient_lang)}</b>"
                        await bot.send_message(
                            user_id,
                            msg_text,
                            reply_markup=_get_main_keyboard(False, recipient_lang, user_id),
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception as e:
                        logger.error(f"Error sending ticket-closure notification to user {user_id}: {e}")

        logger.info(f"chat #{chat_id} closed - by: {closed_by}")
        return True

    logger.warning(f"chat #{chat_id} not found to close")
    return False


TICKET_PAUSE_BUTTON_FA = "🔵 توقف ارسال"
TICKET_PAUSE_BUTTON_EN = "🔵 Pause sending"
TICKET_CLOSE_BUTTON_FA = "🔴 بستن تیکت"
TICKET_CLOSE_BUTTON_EN = "🔴 Close ticket"

TICKET_PAUSE_BUTTONS = {
    TICKET_PAUSE_BUTTON_FA, TICKET_PAUSE_BUTTON_EN,
    "🔵 توقف ارسال", "⏸ توقف ارسال", "توقف ارسال",
    "🔵 Pause sending", "⏸ Pause sending", "Pause sending",
}
TICKET_CLOSE_BUTTONS = {
    TICKET_CLOSE_BUTTON_FA, TICKET_CLOSE_BUTTON_EN,
    "🔴 بستن تیکت", "🔒 بستن تیکت", "بستن تیکت",
    "🔴 Close ticket", "🔒 Close ticket", "Close ticket",
    "/end",
}


def _clear_ticket_input_state(user_id: int, chat_id: int) -> None:
    state = user_states.get(user_id, {})
    if str(state.get('chat_id')) != str(chat_id):
        return

    for key in ('awaiting_chat', 'chat_id', 'timestamp'):
        state.pop(key, None)
    if not state:
        user_states.pop(user_id, None)


async def auto_pause_user_ticket_if_active(user_id: int) -> bool:
    """اگر کاربر در حالت ارسال پیام به تیکت باشد، ارسال را خودکار متوقف کرده و کیبورد تیکت را می‌بندد"""
    state = user_states.get(user_id, {})
    had_state = bool(state.get('awaiting_chat'))
    chat_id = state.get('chat_id')
    has_active_input_ticket = False

    for chat in get_active_chats():
        if chat.get('user_id') == user_id and chat.get('kind') == 'ticket' and chat.get('user_input_enabled'):
            chat['user_input_enabled'] = False
            chat['updated_at'] = now_tehran_iso()
            has_active_input_ticket = True
            if not chat_id:
                chat_id = chat.get('id')

    if not (had_state or has_active_input_ticket):
        return False

    if chat_id is not None:
        _clear_ticket_input_state(user_id, chat_id)
    else:
        state.pop('awaiting_chat', None)
        state.pop('chat_id', None)
        state.pop('timestamp', None)
        if not state:
            user_states.pop(user_id, None)
    save_all()

    lang = get_user(user_id).get('lang', 'fa')
    notice = (t('sending_messages_to_ticket_p_ddd1ea699a', lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',)) if chat_id else t('sending_messages_to_support_5bddcf5434', lang))
    bot = get_bot()
    if bot:
        try:
            await bot.send_message(user_id, notice, reply_markup=ReplyKeyboardRemove())
        except Exception as e:
            logger.debug(f"Error closing the ticket keyboard: {e}")

    logger.info(f"⏸ sending message to ticket #{chat_id} for user {user_id} auto-stopped.")
    return True


async def auto_pause_ticket_on_callback_middleware(handler, event: CallbackQuery, data: dict):
    user_id = event.from_user.id if event.from_user else None
    if user_id and user_states.get(user_id, {}).get('awaiting_chat'):
        cb_data = event.data or ""
        ticket_callbacks = (
            "ticket_pause_user_",
            "ticket_close_user_",
            "ticket_continue_",
        )
        if not any(cb_data.startswith(prefix) for prefix in ticket_callbacks):
            await auto_pause_user_ticket_if_active(user_id)
    return await handler(event, data)


async def auto_pause_ticket_on_message_middleware(handler, event: Message, data: dict):
    user_id = event.from_user.id if event.from_user else None
    if user_id and user_states.get(user_id, {}).get('awaiting_chat'):
        text = (event.text or "").strip()
        if text.startswith('/') and text != '/end':
            await auto_pause_user_ticket_if_active(user_id)
    return await handler(event, data)


def get_user_ticket_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(text=TICKET_PAUSE_BUTTON_FA if lang == "fa" else TICKET_PAUSE_BUTTON_EN),
            KeyboardButton(text=TICKET_CLOSE_BUTTON_FA if lang == "fa" else TICKET_CLOSE_BUTTON_EN),
        ]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_active_chats() -> list:
    """دریافت چت‌های فعال"""
    return [c for c in chats.values() if c.get('status') == 'open']


def get_user_support_configs(user_id: int) -> list:
    """دریافت سرویس‌های فعال، غیرفعال یا حذف‌شده کاربر برای پشتیبانی."""
    return [
        order
        for order in get_valid_orders().values()
        if order.get('user_id') == user_id
        and order.get('status') in ('approved', 'inactive', 'deleted')
        and (order.get('config_link') or order.get('email'))
    ]


def format_ticket_user_details(user_id: int, selected_order_id: Optional[int] = None) -> str:
    user = get_user(user_id)
    username = user.get('telegram_username') or user.get('username') or ''
    details = [
        f"👤 <b>{html.escape(str(user.get('name') or 'کاربر'))}</b> (ID: <code>{user_id}</code>)",
        f"🔗 نام کاربری: @{html.escape(str(username).lstrip('@')) if username else 'ندارد'}",
        f"💰 موجودی: {user.get('balance', 0)}",
        f"🛒 تعداد خرید: {user.get('total_purchases', 0)}",
    ]
    user_configs = get_user_support_configs(user_id)
    details.append(f"\n📦 <b>کانفیگ‌های کاربر ({len(user_configs)}):</b>")
    for order in user_configs[:5]:
        order_id = order.get('order_id')
        selected_mark = "✅ " if selected_order_id is not None and str(order_id) == str(selected_order_id) else ""
        config_name = html.escape(str(order.get('email') or f"سفارش {order_id}"))
        status = html.escape(str(order.get('status', 'نامشخص')))
        details.append(
            f"{selected_mark}#{order_id} — {config_name} | "
            f"{order.get('volume', '?')}GB / {order.get('days', '?')} روز | {status}"
        )
        link = str(order.get('config_link') or '')
        if link:
            details.append(f"<code>{html.escape(link[:220])}</code>")
    if len(user_configs) > 5:
        details.append(f"و {len(user_configs) - 5} کانفیگ دیگر")
    if selected_order_id is not None:
        selected_order = next(
            (order for order in user_configs if str(order.get('order_id')) == str(selected_order_id)),
            None,
        )
        if selected_order:
            details.append(f"\n🎯 کانفیگ مرتبط با تیکت: <b>#{selected_order_id}</b>")
    else:
        details.append("\n🎯 کانفیگ مرتبط: انتخاب نشده / مشکل مربوط به کانفیگ نیست")
    return "\n".join(details)


async def open_support_ticket(callback: CallbackQuery, config_order_id: Optional[int] = None):
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    state = user_states.get(user_id, {})
    if state.get('ticket_selection_message_id') == callback.message.message_id:
        await callback.answer(
            t('to_open_another_ticket_start_c42857735b', lang),
            show_alert=True,
        )
        return
    if config_order_id is not None and not any(
        str(order.get('order_id')) == str(config_order_id)
        and order.get('status') in ("approved", "inactive")
        and order.get('config_link')
        for order in get_valid_orders().values()
        if order.get('user_id') == user_id
    ):
        await callback.answer(
            t('this_config_does_not_belong_74d0df2742', lang),
            show_alert=True,
        )
        return

    existing_state = user_states.get(user_id, {})
    for existing_chat in get_active_chats():
        if existing_chat.get('user_id') == user_id and existing_chat.get('kind') == 'ticket':
            existing_chat['user_input_enabled'] = False
            existing_chat['updated_at'] = now_tehran_iso()
    chat_id = create_chat(user_id, config_order_id=config_order_id)
    state = {
        'awaiting_chat': True,
        'chat_id': chat_id,
        'timestamp': now_tehran_iso(),
        'ticket_selection_message_id': callback.message.message_id,
    }
    for key in ('coupon_code', 'coupon_discount', 'coupon_applied'):
        if key in existing_state:
            state[key] = existing_state[key]
    user_states[user_id] = state
    chats[str(chat_id)]['user_input_enabled'] = True
    save_all()
    bot = get_bot()
    try:
        if bot:
            await bot.send_message(
                ADMIN_ID_INT,
                f"🎫 <b>تیکت جدید #{chat_id}</b>\n\n"
                f"{format_ticket_user_details(user_id, config_order_id)}\n\n"
                f"برای پاسخ، تیکت را باز کنید.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="💬 مشاهده و پاسخ", callback_data=f"admin_chat_{chat_id}"),
                        InlineKeyboardButton(text="👤 مشاهده کاربر", callback_data=f"admin_user_{user_id}"),
                    ]
                ]),
            )
    except Exception as e:
        logger.error(f"Error notifying about ticket #{chat_id} to admin: {e}", exc_info=True)
        await close_chat(chat_id, closed_by="admin", notify_other=False)
        user_states.pop(user_id, None)
        await callback.message.answer(
            t('could_not_open_a_ticket_plea_c7f70ab1fa', lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        await callback.answer()
        return

    try:
        await callback.message.edit_text(
            t('ticket_opened_937e4e42e0', lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',)),
            reply_markup=None,
        )
    except Exception as e:
        logger.warning(f"Error editing the ticket-selection message: {e}")

    prompt_text = (
        t('write_and_send_your_message_6c2a2f525f', lang)
    )

    await callback.message.answer(
        prompt_text,
        reply_markup=get_user_ticket_keyboard(lang),
    )
    await callback.answer()


@router.callback_query(F.data == "support_create_ticket")
async def support_create_ticket(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    state = user_states.get(user_id, {})
    state.pop('ticket_selection_message_id', None)
    if not state:
        user_states.pop(user_id, None)
    configs = [
        order for order in get_valid_orders().values()
        if order.get('user_id') == user_id
        and order.get('status') in ("approved", "inactive")
        and order.get('config_link')
        and order.get('order_id') is not None
    ]
    configs.sort(key=lambda order: str(order.get('date') or ''), reverse=True)
    buttons = []
    for order in configs[:20]:
        category = get_order_category_name(order, lang).strip()
        if lang == "fa":
            category = category.removeprefix(t('config_71a8425641', lang)).lstrip(" ·-—:")
            category = category if category.startswith(t('subscription_32b8faf1f0', lang)) else t('sub_9c78dcd277', lang, fa_parts=lambda: (f'{category}',)).strip()
            volume_gb = order.get('volume', 0) or 0
            if volume_gb == 0:
                volume = "∞"
            elif volume_gb < 1:
                volume = t('mb_4062381407', lang, fa_parts=lambda: (f'{round(volume_gb * 1024)}',))
            else:
                volume = t('gb_b755d45a80', lang, fa_parts=lambda: (f'{volume_gb:.0f}',))
            duration = t('days_a6a4667661', lang, fa_parts=lambda: (f"{order.get('days')}",)) if order.get('days') else ""
            status_icon = "💳" if order.get('status') == "approved" else "🔴"
        else:
            category = category.removeprefix(t('config_71a8425641', lang)).lstrip(" ·-—:")
            category = category if category.lower().endswith(("sub", "subscription")) else t('sub_9c78dcd277', lang, en_parts=lambda: (f'{category}',)).strip()
            volume_gb = order.get('volume', 0) or 0
            if volume_gb == 0:
                volume = "∞"
            elif volume_gb < 1:
                volume = t('mb_4062381407', lang, en_parts=lambda: (f'{round(volume_gb * 1024)}',))
            else:
                volume = t('gb_b755d45a80', lang, en_parts=lambda: (f'{volume_gb:.0f}',))
            duration = t('days_a6a4667661', lang, en_parts=lambda: (f"{order.get('days')}",)) if order.get('days') else ""
            status_icon = "💳" if order.get('status') == "approved" else "🔴"
        category = category[:20]
        label_parts = [part for part in (category, volume, duration, f"#{order.get('order_id')}") if part]
        prefix = "\u200f" if lang == "fa" else "\u200e"
        label = f"{prefix}{status_icon} " + " · ".join(label_parts)
        if len(label) > 64:
            suffix = f" · #{order.get('order_id')}"
            label = f"{prefix}{status_icon} {category[:12]} · {volume} · {duration}" + suffix
            label = label[:64]
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"ticket_config_{order.get('order_id')}",
            style="success" if order.get('status') == "approved" else "danger",
        )])
    buttons.append([InlineKeyboardButton(
        text=t('my_issue_is_not_config_relat_e25cea93b5', lang),
        callback_data="ticket_no_config",
    )])
    buttons.append([InlineKeyboardButton(
        text=t('back_460da353ef', lang),
        callback_data="ai_chat",
    )])
    await callback.message.edit_text(
        (
            t('b_open_a_support_ticket_b_se_8c3a25af39', lang)
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data == "ticket_no_config")
async def ticket_no_config(callback: CallbackQuery):
    await open_support_ticket(callback)


@router.callback_query(F.data.startswith("ticket_config_"))
async def ticket_config_selected(callback: CallbackQuery):
    try:
        order_id = int(callback.data.rsplit("_", 1)[1])
    except (TypeError, ValueError):
        lang = get_user(callback.from_user.id).get('lang', 'fa')
        await callback.answer(t('i18n_invalid_order', lang), show_alert=True)
        return
    await open_support_ticket(callback, order_id)


@router.callback_query(F.data.startswith("ticket_close_user_"))
async def user_close_ticket(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    try:
        chat_id = int(callback.data.rsplit("_", 1)[1])
    except (TypeError, ValueError):
        await callback.answer(t('i18n_invalid_ticket', lang), show_alert=True)
        return
    chat = chats.get(str(chat_id))
    if not chat or chat.get('user_id') != user_id or chat.get('status') != 'open':
        await callback.answer(t('i18n_ticket_not_found', lang), show_alert=True)
        return
    await close_chat(chat_id, closed_by="user")
    is_admin = (user_id == ADMIN_ID_INT)
    msg_text = (
        t('ticket_has_been_successfully_be5134995b', lang, fa_parts=lambda: (f'{chat_id}', f"{premium_emoji('rocket', '🚀')}"), en_parts=lambda: (f'{chat_id}', f"{premium_emoji('rocket', '🚀')}"))
    )
    await callback.message.edit_text(
        msg_text,
        reply_markup=_get_main_keyboard(is_admin, lang, user_id),
        parse_mode=ParseMode.HTML,
    )
    bot = get_bot()
    if bot:
        try:
            await bot.send_message(
                user_id,
                t('ticket_has_been_successfully_5a5aa318b8', lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',)),
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception as e:
            logger.debug(f"Error sending ticket-closure confirmation to user: {e}")
    await callback.answer()


@router.callback_query(F.data.startswith("ticket_pause_user_"))
async def user_pause_ticket_input(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    try:
        chat_id = int(callback.data.rsplit("_", 1)[1])
    except (TypeError, ValueError):
        await callback.answer(t('i18n_invalid_ticket', lang), show_alert=True)
        return
    chat = chats.get(str(chat_id))
    if not chat or chat.get('user_id') != user_id or chat.get('status') != 'open':
        await callback.answer(t('i18n_no_active_ticket', lang), show_alert=True)
        return

    chat['user_input_enabled'] = False
    chat['updated_at'] = now_tehran_iso()
    _clear_ticket_input_state(user_id, chat_id)
    save_all()

    is_admin = (user_id == ADMIN_ID_INT)
    pause_text = (
        t('sending_messages_to_ticket_h_2deb178b61', lang, fa_parts=lambda: (f'{chat_id}', f"{premium_emoji('rocket', '🚀')}"), en_parts=lambda: (f'{chat_id}', f"{premium_emoji('rocket', '🚀')}"))
    )
    await callback.message.edit_text(
        pause_text,
        reply_markup=_get_main_keyboard(is_admin, lang, user_id),
        parse_mode=ParseMode.HTML,
    )
    bot = get_bot()
    if bot:
        try:
            await bot.send_message(
                user_id,
                t('sending_messages_to_ticket_p_ddd1ea699a', lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',)),
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception as e:
            logger.debug(f"Error sending ticket-stop notification to user: {e}")
    await callback.answer(t('input_paused_6edaea11e9', lang))


@router.callback_query(F.data.startswith("ticket_continue_"))
async def user_continue_ticket(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    try:
        chat_id = int(callback.data.rsplit("_", 1)[1])
    except (TypeError, ValueError):
        await callback.answer(t('i18n_invalid_ticket', lang), show_alert=True)
        return
    chat = chats.get(str(chat_id))
    if not chat or chat.get('user_id') != user_id or chat.get('status') != 'open':
        await callback.answer(t('i18n_no_active_ticket', lang), show_alert=True)
        return
    state = {
        'awaiting_chat': True,
        'chat_id': chat_id,
        'timestamp': now_tehran_iso(),
    }
    existing_state = user_states.get(user_id, {})
    for key in ('coupon_code', 'coupon_discount', 'coupon_applied'):
        if key in existing_state:
            state[key] = existing_state[key]
    user_states[user_id] = state
    for existing_chat in get_active_chats():
        if (
            existing_chat.get('user_id') == user_id
            and existing_chat.get('kind') == 'ticket'
            and existing_chat.get('id') != chat_id
        ):
            existing_chat['user_input_enabled'] = False
            existing_chat['updated_at'] = now_tehran_iso()
    chat['user_input_enabled'] = True
    chat['updated_at'] = now_tehran_iso()
    save_all()
    prompt_text = (
        t('continue_ticket_write_and_se_b5b9545eba', lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',))
    )
    await callback.message.answer(
        prompt_text,
        reply_markup=get_user_ticket_keyboard(lang),
    )
    await callback.answer()


def support_message_description(message: Message) -> str:
    content = message.text or message.caption
    if content:
        return content
    content_type = getattr(message, 'content_type', 'message')
    file_name = None
    for attribute in ('document', 'video', 'audio', 'animation'):
        media = getattr(message, attribute, None)
        if media and getattr(media, 'file_name', None):
            file_name = media.file_name
            break
    suffix = f": {file_name}" if file_name else ""
    return f"[{content_type}{suffix}]"


async def relay_support_message(
    message: Message,
    destination_id: int,
    chat_id: int,
    sender_label: str,
):
    bot = get_bot()
    description = support_message_description(message)
    lang = get_user(destination_id).get('lang', 'fa')
    title = (
        f"💬 پیام از پشتیبانی · تیکت #{chat_id}"
        if sender_label == "admin"
        else f"💬 پیام کاربر {message.from_user.id} · تیکت #{chat_id}"
    )
    if lang == "en":
        title = (
            f"💬 Support message · ticket #{chat_id}"
            if sender_label == "admin"
            else f"💬 Message from user {message.from_user.id} · ticket #{chat_id}"
        )
    if bot:
        if message.text:
            await bot.send_message(
                destination_id,
                f"{title}\n\n{html.escape(message.text)}",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.copy_to(destination_id)
            try:
                await bot.send_message(
                    destination_id,
                    f"{title}\n{html.escape(description)}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.error(
                    'Media message for ticket #%s was sent, but sending the caption failed: %s',
                    chat_id,
                    e,
                )
    return description


@router.message(F.text.in_(TICKET_PAUSE_BUTTONS | TICKET_CLOSE_BUTTONS))
async def handle_ticket_button_press(message: Message):
    """مدیریت دکمه‌های بستن و توقف تیکت در هر شرایطی (حتی بعد از ری‌استارت ربات) با بستن قطعی کیبورد."""
    user_id = message.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    is_admin = (user_id == ADMIN_ID_INT)
    text = (message.text or "").strip()

    state = user_states.get(user_id, {})
    chat_id = state.get('chat_id')
    if not chat_id:
        for chat in get_active_chats():
            if chat.get('user_id') == user_id and chat.get('kind') == 'ticket':
                chat_id = chat.get('id')
                break

    if text in TICKET_PAUSE_BUTTONS:
        if chat_id:
            chat = chats.get(str(chat_id))
            if chat:
                chat['user_input_enabled'] = False
                chat['updated_at'] = now_tehran_iso()
            _clear_ticket_input_state(user_id, chat_id)
            save_all()
            pause_notice = (
                t('sending_messages_to_ticket_h_20a507a432', lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',))
            )
        else:
            state.pop('awaiting_chat', None)
            state.pop('chat_id', None)
            if not state:
                user_states.pop(user_id, None)
            save_all()
            pause_notice = (
                t('sending_messages_to_support_5bddcf5434', lang)
            )

        await message.answer(pause_notice, reply_markup=ReplyKeyboardRemove())
        menu_text = (
            f"{premium_emoji('rocket', '🚀')} <b>{t('main_menu_9ae3456442', lang)}</b>"
        )
        await message.answer(
            menu_text,
            reply_markup=_get_main_keyboard(is_admin, lang, user_id),
            parse_mode=ParseMode.HTML,
        )
        return

    # بستن تیکت
    if chat_id:
        await close_chat(chat_id, closed_by="user")
        _clear_ticket_input_state(user_id, chat_id)
        close_notice = (
            t('ticket_has_been_successfully_5a5aa318b8', lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',))
        )
    else:
        state.pop('awaiting_chat', None)
        state.pop('chat_id', None)
        if not state:
            user_states.pop(user_id, None)
        save_all()
        close_notice = (
            t('ticket_controls_were_closed_aa691a710d', lang)
        )

    await message.answer(close_notice, reply_markup=ReplyKeyboardRemove())
    menu_text = (
        f"{premium_emoji('rocket', '🚀')} <b>{t('main_menu_9ae3456442', lang)}</b>"
    )
    await message.answer(
        menu_text,
        reply_markup=_get_main_keyboard(is_admin, lang, user_id),
        parse_mode=ParseMode.HTML,
    )


@router.message(lambda m: user_states.get(m.from_user.id, {}).get('awaiting_chat', False))
async def handle_chat_message(message: Message):
    """دریافت و انتقال متن و رسانه کاربر در تیکت پشتیبانی."""
    user_id = message.from_user.id

    state = user_states.get(user_id, {})
    chat_id = state.get('chat_id')
    lang = get_user(user_id).get('lang', 'fa')

    if not chat_id:
        state.pop('awaiting_chat', None)
        state.pop('chat_id', None)
        state.pop('timestamp', None)
        if not state:
            user_states.pop(user_id, None)
        return

    chat = chats.get(str(chat_id))
    if not chat or chat.get('status') == 'closed':
        _clear_ticket_input_state(user_id, chat_id)
        save_all()
        return

    text = (message.text or "").strip()
    if text in (TICKET_PAUSE_BUTTONS | TICKET_CLOSE_BUTTONS):
        await handle_ticket_button_press(message)
        return

    if not chat.get('user_input_enabled', True):
        _clear_ticket_input_state(user_id, chat_id)
        save_all()
        return
    try:
        text_content = await relay_support_message(
            message,
            ADMIN_ID_INT,
            chat_id,
            sender_label="user",
        )
    except Exception as e:
        logger.error(f"Error forwarding user message to ticket #{chat_id}: {e}", exc_info=True)
        await message.reply("❌ ارسال پیام به پشتیبانی ناموفق بود. لطفاً دوباره تلاش کنید.")
        return
    add_message(chat_id, 'user', text_content)
    bot = get_bot()
    if bot:
        try:
            await bot.send_message(
                ADMIN_ID_INT,
                f"برای پاسخ به تیکت #{chat_id} دکمه را بزنید.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="💬 پاسخ", callback_data=f"admin_chat_{chat_id}"),
                    InlineKeyboardButton(text="👤 مشاهده کاربر", callback_data=f"admin_user_{user_id}"),
                ]]),
            )
        except Exception as e:
            logger.error(f"Ticket message #{chat_id} sent, but the reply button could not be sent: {e}")

    await message.reply(t('message_sent_f0e3adda45', lang))


async def save_feedback(user_id: int, order_id: int, rating: str, comment: str = ""):
    """ذخیره بازخورد"""
    fid = len(feedbacks) + 1
    feedbacks[str(fid)] = {
        'id': fid,
        'user_id': user_id,
        'order_id': order_id,
        'rating': rating,
        'comment': comment,
        'date': now_tehran().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_all()
    user = get_user(user_id)
    user_name_escaped = html.escape(str(user.get('name') or f'کاربر_{user_id}'))
    comment_escaped = html.escape(str(comment)) if comment else 'بدون نظر'
    text = f"""
{premium_emoji('note', '📝')} <b>بازخورد جدید</b>

{premium_emoji('user', '👤')} کاربر: {user_name_escaped} (ID: {user_id})
{premium_emoji('order_id', '🆔')} سفارش: #{order_id}
{premium_emoji('star', '⭐')} امتیاز: {rating}
{premium_emoji('chat', '💬')} نظر: {comment_escaped}
{premium_emoji('calendar', '📅')} تاریخ: {feedbacks[str(fid)]['date']}
"""
    bot = get_bot()
    if bot:
        try:
            await bot.send_message(ADMIN_ID_INT, text, parse_mode=ParseMode.HTML)
            logger.info(f"new feedback from user {user_id} for order #{order_id} saved")
        except Exception as e:
            logger.error(f"Error sending feedback to admin: {e}")


@router.callback_query(F.data.startswith("feedback_"))
async def handle_feedback(callback: CallbackQuery):
    parts = callback.data.split("_")
    rating = parts[1]
    order_id = int(parts[2]) if len(parts) > 2 else 0
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')

    logger.info(f"User {user_id}feedback {rating} for order #{order_id} registered")

    if rating == "nocomment":
        await save_feedback(user_id, order_id, t('no_comment_aab6ac81cb', lang), "")
        await callback.message.edit_text(t('thank_you_for_your_feedback_ce654e7019', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}",), en_parts=lambda: (f"{premium_emoji('success', '✅')}",)), reply_markup=get_back_only_keyboard(lang))
        await safe_answer(callback)
        return

    rating_map_fa = {"good": "😊 عالی", "medium": "😐 متوسط", "bad": "😞 بد"}
    rating_map_en = {"good": "😊 Excellent", "medium": "😐 Average", "bad": "😞 Bad"}
    rating_text = rating_map_fa.get(rating, t('no_comment_aab6ac81cb', lang)) if lang == 'fa' else rating_map_en.get(rating, t('no_comment_aab6ac81cb', lang))
    if log_system:
        await log_system.log_feedback(user_id, order_id, rating_text)
    fid = len(feedbacks) + 1
    feedbacks[str(fid)] = {
        'id': fid,
        'user_id': user_id,
        'order_id': order_id,
        'rating': rating,
        'comment': '',
        'date': now_tehran().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_all()
    # Notify admin about new feedback (no chat created)
    bot = get_bot()
    if bot:
        try:
            user = get_user(user_id)
            user_name_escaped = html.escape(str(user.get('name') or 'کاربر'))
            await bot.send_message(
                ADMIN_ID_INT,
                f"📝 <b>بازخورد جدید</b>\n\n"
                f"👤 {user_name_escaped} (ID: {user_id})\n"
                f"⭐ {rating_text}\n"
                f"📦 سفارش #{order_id}",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    thanks_text = (
        t('your_rating_thank_you_for_yo_4ddd9ef28e', lang, fa_parts=lambda: (f"{premium_emoji('star', '⭐')}", f'{rating_text}', f"{premium_emoji('success', '✅')}"), en_parts=lambda: (f"{premium_emoji('star', '⭐')}", f'{rating_text}', f"{premium_emoji('success', '✅')}"))
    )
    feedback_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t('open_ticket_ee8b4c6c58', lang), callback_data="support_create_ticket", style="primary")],
        [InlineKeyboardButton(text=t('main_menu_0cdd07a7cc', lang), callback_data="back_to_main", style="danger")],
    ])
    await callback.message.edit_text(
        thanks_text,
        reply_markup=feedback_keyboard,
        parse_mode=ParseMode.HTML,
    )
    await safe_answer(callback)


@router.message(lambda m: user_states.get(m.from_user.id, {}).get('awaiting_feedback_comment'))
async def handle_feedback_comment(message: Message):
    user_id = message.from_user.id
    if await block_unauthorized(message, message.from_user.id):
        return

    lang = get_user(user_id).get('lang', 'fa')
    state = user_states.get(user_id, {})
    order_id = state.get('feedback_order', 0)
    rating = state.get('feedback_rating', t('no_comment_aab6ac81cb', lang))
    comment = message.text
    if log_system:
        await log_system.log_feedback(user_id, order_id, comment)

    logger.info(f"User {user_id}left their comment for order #{order_id}registered: {comment}")

    await save_feedback(user_id, order_id, rating, comment)
    await message.reply(t('thank_you_for_your_feedback_ce654e7019', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}",), en_parts=lambda: (f"{premium_emoji('success', '✅')}",)), reply_markup=get_back_only_keyboard(lang))
    user_states.pop(user_id, None)

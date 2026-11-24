"""
routers/admin_tools.py
----------------------
ابزارهای مدیریت پنل ادمین: همگام‌سازی کانفیگ‌ها، بازسازی لینک‌های ساب، مدیریت بکاپ‌ها،
بررسی لاگ‌ها و کاهش/ریست دستی موجودی کاربران
"""

import os
import re
import glob
import json
import time
import html
import shutil
import asyncio
import logging
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urlparse
from io import BytesIO
from typing import Optional, List, Dict, Any, Tuple, Union

import aiohttp
from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BufferedInputFile,
)
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import (
    ADMIN_ID,
    LOG_BOT_TOKEN,
    LOG_CHANNEL_ID,
    SENAI_PANEL_URL,
    SENAI_PANEL_ENABLED,
    is_senai_panel_enabled,
    set_senai_panel_enabled,
)
from db_storage import (
    DATA_DIR,
    DB_FILES,
    save_json,
    load_json,
    _db_cache,
    _db_modified,
)
from database import (
    users,
    orders,
    chats,
    referrals,
    configs_pool,
    save_all,
    now_tehran,
    now_tehran_iso,
    BLACKLIST,
    READY_PACKAGES,
    SHOP_STATUS,
    TEST_SERVICE_STATUS,
    USER_TEST_USAGE,
    feedbacks,
    add_config_to_pool,
    update_order,
)
from user_manager import (
    user_states,
    get_user,
    get_admin_id_int,
    COUPONS,
    save_coupon_to_user_db,
    clear_coupon_from_user_db,
    add_balance,
    reduce_balance,
    reset_balance,
)
from core.state_stores import (
    USER_INBOUND_SELECTION,
)
from strings import t
from utils.filters import IsAdmin
from utils.guards import admin_only
from utils.helpers import safe_answer, safe_edit_message

logger = logging.getLogger(__name__)

router = Router(name="admin_tools")

ADMIN_ID_INT = get_admin_id_int()

_bot: Optional[Bot] = None


def set_bot(b: Bot):
    global _bot
    _bot = b


def get_bot() -> Optional[Bot]:
    global _bot
    if _bot is not None:
        return _bot
    try:
        import main
        return getattr(main, "bot", None)
    except Exception:
        return None


class _BotProxy:
    def __getattr__(self, name):
        b = get_bot()
        if b is not None:
            return getattr(b, name)
        raise RuntimeError("Bot instance not set")


bot = _BotProxy()


class _LogSystemProxy:
    def __bool__(self):
        try:
            import main
            return bool(getattr(main, "log_system", None))
        except Exception:
            return False

    def __getattr__(self, name):
        import main
        ls = getattr(main, "log_system", None)
        if ls is not None:
            return getattr(ls, name)
        raise AttributeError(name)


log_system = _LogSystemProxy()


class _UsageStoreProxy:
    def __getattr__(self, name):
        import main
        return getattr(main.usage_store, name)


usage_store = _UsageStoreProxy()


class CustomLogger:
    @staticmethod
    def log_event(*args, **kwargs):
        import main
        if hasattr(main, "CustomLogger"):
            main.CustomLogger.log_event(*args, **kwargs)


def format_size(bytes_val):
    if not isinstance(bytes_val, (int, float)):
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"


def add_message(*args, **kwargs):
    import main
    if hasattr(main, "add_message"):
        return main.add_message(*args, **kwargs)


async def close_chat(*args, **kwargs):
    import main
    if hasattr(main, "close_chat"):
        return await main.close_chat(*args, **kwargs)


async def test_panel_connection(*args, **kwargs):
    import main
    if hasattr(main, "test_panel_connection"):
        return await main.test_panel_connection(*args, **kwargs)
    return {}


def build_sub_link_from_client(*args, **kwargs):
    import main
    if hasattr(main, "build_sub_link_from_client"):
        return main.build_sub_link_from_client(*args, **kwargs)
    return ""


def get_active_chats(*args, **kwargs):
    import main
    if hasattr(main, "get_active_chats"):
        return main.get_active_chats(*args, **kwargs)
    return []


async def relay_support_message(*args, **kwargs):
    import main
    if hasattr(main, "relay_support_message"):
        return await main.relay_support_message(*args, **kwargs)


def format_ticket_user_details(*args, **kwargs):
    import main
    if hasattr(main, "format_ticket_user_details"):
        return main.format_ticket_user_details(*args, **kwargs)
    return ""


from services.panel_api import (
    xui_login,
    xui_get_inbounds,
    xui_get_csrf_token,
    ensure_sub_base_url,
    get_sub_base_url,
    xui_delete_client,
)


def get_valid_orders(*args, **kwargs):
    import main
    if hasattr(main, "get_valid_orders"):
        return main.get_valid_orders(*args, **kwargs)
    return []


def get_available_configs_count(*args, **kwargs):
    import main
    if hasattr(main, "get_available_configs_count"):
        return main.get_available_configs_count(*args, **kwargs)
    return 0


def get_next_order_id(*args, **kwargs):
    import main
    if hasattr(main, "get_next_order_id"):
        return main.get_next_order_id(*args, **kwargs)
    return 1


def get_receipt_status_metadata(*args, **kwargs):
    import main
    if hasattr(main, "get_receipt_status_metadata"):
        return main.get_receipt_status_metadata(*args, **kwargs)
    return {}


async def get_user_info_from_telegram(*args, **kwargs):
    import main
    if hasattr(main, "get_user_info_from_telegram"):
        return await main.get_user_info_from_telegram(*args, **kwargs)
    return {}


async def smart_ping(*args, **kwargs):
    import main
    if hasattr(main, "smart_ping"):
        return await main.smart_ping(*args, **kwargs)
    return None


def get_admin_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_admin_keyboard"):
        return main.get_admin_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


@router.callback_query(F.data.startswith("admin_reduce_balance_"))
@admin_only(answer_on_denied=False)
async def admin_reduce_balance_cmd(callback: CallbackQuery):
    """شروع فرآیند کاهش موجودی"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    target_id = int(callback.data.split("_")[3])
    target = get_user(target_id)
    target_name_raw = target.get('name', f'کاربر_{target_id}')
    target_name_escaped = html.escape(target_name_raw)
    
    user_states[callback.from_user.id] = {
        'awaiting_manual_balance': True, 
        'manual_balance_target': target_id,
        'balance_action': 'reduce'
    }
    
    await callback.message.answer(
        t('current_balance_for_toman_pl_cb7d8108f9', lang, fa_parts=lambda: (f'{target_name_escaped}', f"{target.get('balance', 0):,}"), en_parts=lambda: (f'{target_name_escaped}', f"{target.get('balance', 0):,}"))
    )
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_reset_balance_"))
@admin_only(answer_on_denied=False)
async def admin_reset_balance_cmd(callback: CallbackQuery):
    """صفر کردن موجودی کاربر (بدون حذف کانفیگ‌ها)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    target_id = int(callback.data.split("_")[3])
    target = get_user(target_id)
    old_balance = target.get('balance', 0)
    target_name_raw = target.get('name', f'کاربر_{target_id}')
    target_name_escaped = html.escape(target_name_raw)
    text = t('b_confirm_balance_reset_b_us_cd09e0b014', lang, fa_parts=lambda: (f'{target_name_escaped}', f'{target_id}', f'{old_balance:,}'), en_parts=lambda: (f'{target_name_escaped}', f'{target_id}', f'{old_balance:,}'))
    
    buttons = [
        [
            InlineKeyboardButton(
                text=t('yes_reset_455b80801b', lang),
                callback_data=f"confirm_reset_balance_{target_id}",
                style="danger"
            ),
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data=f"admin_user_{target_id}"
            )
        ]
    ]
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    
    await safe_answer(callback)

    
    



    
    

@router.callback_query(F.data.startswith("confirm_reset_balance_"))
@admin_only(answer_on_denied=False)
async def confirm_reset_balance(callback: CallbackQuery):
    """تایید و اجرای صفر کردن موجودی (بدون حذف کانفیگ‌ها)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    target_id = int(callback.data.split("_")[3])
    target = get_user(target_id)
    old_balance = target.get('balance', 0)
    target_name_raw = target.get('name', f'کاربر_{target_id}')
    target_name_escaped = html.escape(target_name_raw)
    new_balance = reset_balance(target_id)
    target_lang = get_user(target_id).get('lang', 'fa')
    try:
        msg = t('your_balance_has_been_reset_a4a3508202', target_lang, fa_parts=lambda: (f'{old_balance:,}', f'{new_balance:,}'), en_parts=lambda: (f'{old_balance:,}', f'{new_balance:,}'))
        await bot.send_message(target_id, msg)
    except Exception:
        pass
    
    text = t('balance_reset_for_0_toman_us_4e863ecf06', lang, fa_parts=lambda: (f'{target_name_escaped}', f'{old_balance:,}'), en_parts=lambda: (f'{target_name_escaped}', f'{old_balance:,}'))
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('back_14968ad63f', lang),
                callback_data=f"admin_user_{target_id}"
            )]
        ])
    )
    
    logger.info(f"user balance {target_id} reached zero (configs not deleted)")
    await callback.answer(t('done_32a21c5da0', lang), show_alert=True)


@router.callback_query(F.data == "admin_chats")
@admin_only(answer_on_denied=False)
async def admin_chats_list(callback: CallbackQuery):
    """لیست چت‌های فعال"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    active = get_active_chats()
    
    if not active:
        text = t('no_active_chats_ce00e1bd0b', lang)
        text += f"\n<code>🕐 {now_tehran().strftime('%H:%M:%S')}</code>"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('refresh_cda5094083', lang), callback_data="admin_chats")],
            [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        await safe_answer(callback)
        return
    
    buttons = []
    for chat in active:
        user = get_user(chat['user_id'])
        user_name_escaped = html.escape(user.get('name', 'User'))  # ✅
        msg_count = len(chat['messages'])
        buttons.append([InlineKeyboardButton(
            text=t('msg_a729bc3831', lang, fa_parts=lambda: (f'{user_name_escaped}', f'{msg_count}'), en_parts=lambda: (f'{user_name_escaped}', f'{msg_count}')),
            callback_data=f"admin_chat_{chat['id']}"
        )])
    
    buttons.append([InlineKeyboardButton(text=t('refresh_cda5094083', lang), callback_data="admin_chats")])
    buttons.append([InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")])
    
    text = f"💬 <b>{t('active_chats_2538cb069a', lang)}</b> ({len(active)})\n<code>🕐 {now_tehran().strftime('%H:%M:%S')}</code>"
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_chat_"))
@admin_only(answer_on_denied=False)
async def admin_chat_view(callback: CallbackQuery):
    """مشاهده و پاسخ به چت - با بررسی بسته بودن"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    chat_id = int(callback.data.split("_")[2])
    chat = chats.get(str(chat_id))
    
    if not chat:
        await callback.answer(t('i18n_chat_not_found', lang), show_alert=True)
        return
    if chat.get('status') == 'closed':
        await callback.message.edit_text(
            t('this_chat_is_closed_chat_use_c1f021ba6f', lang, fa_parts=lambda: (f'{chat_id}', f"{get_user(chat['user_id']).get('name', 'نامشخص')}", f"{chat.get('closed_at', 'نامشخص')}"), en_parts=lambda: (f'{chat_id}', f"{get_user(chat['user_id']).get('name', 'Unknown')}", f"{chat.get('closed_at', 'Unknown')}")),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_chats")]
            ])
        )
        await callback.answer()
        return
    selected_order_id = chat.get('config_order_id')
    title = "تیکت" if chat.get('kind') == 'ticket' else "چت بازخورد"
    text = (
        f"🎫 <b>{title} #{chat_id}</b>\n"
        f"{format_ticket_user_details(chat['user_id'], selected_order_id)}\n\n"
        "━━━━━━━━━━━━━━━━━━\n<b>گفتگو:</b>\n"
    )
    
    for msg in chat['messages'][-8:]:
        sender = "👤 کاربر" if msg['sender'] == 'user' else "👑 ادمین"
        text += f"{sender}: {html.escape(str(msg.get('text', ''))[:180])}\n"
    user_states[callback.from_user.id] = {'awaiting_chat_reply': True, 'chat_id': chat_id}
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('user_profile_and_orders_03211a20d3', lang),
            callback_data=f"admin_user_{chat['user_id']}",
        )],
        [InlineKeyboardButton(text=t('close_chat_8a1d3cb5a7', lang), callback_data=f"close_chat_{chat_id}")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_chats")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    
    await callback.message.answer(t('write_your_message_cancel_to_039426bb3a', lang))
    
    await safe_answer(callback)


@router.callback_query(F.data.startswith("close_chat_"))
@admin_only(answer_on_denied=False)
async def admin_close_chat(callback: CallbackQuery):
    """بستن چت توسط ادمین"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    chat_id = int(callback.data.split("_")[2])
    
    chat = chats.get(str(chat_id))
    if not chat or chat.get('status') != 'open':
        await callback.answer(t('active_ticket_not_found_6ed5914747', lang), show_alert=True)
        return
    
    await close_chat(chat_id, closed_by="admin")
    if chat and chat.get('user_id') in user_states:
        user_states.pop(chat['user_id'], None)
    if callback.from_user.id in user_states:
        user_states.pop(callback.from_user.id, None)
    
    
    await callback.message.edit_text(t('ticket_has_been_successfully_5a5aa318b8', lang, fa_parts=lambda: (f'{chat_id}',), en_parts=lambda: (f'{chat_id}',)), reply_markup=get_admin_keyboard(lang))
    
    await safe_answer(callback)

@router.callback_query(F.data == "admin_sync_configs")
@admin_only(answer_on_denied=False)
async def admin_sync_configs(callback: CallbackQuery):
    """همگام‌سازی دستی کانفیگ‌ها (فقط ادمین)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    await callback.message.edit_text(t('i18n_syncing', lang))
    stats = await sync_deleted_configs()
    text = t('b_sync_with_panel_completed_14a0d89142', lang, fa_parts=lambda: (f"{stats.get('approved', 0)}", f"{stats.get('inactive', 0)}", f"{stats.get('deleted', 0)}", f"{stats.get('errors', 0)}", f"{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}"), en_parts=lambda: (f"{stats.get('approved', 0)}", f"{stats.get('inactive', 0)}", f"{stats.get('deleted', 0)}", f"{stats.get('errors', 0)}", f"{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}"))
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('refresh_025e4ab936', lang), callback_data="admin_sync_configs")],
            [InlineKeyboardButton(text=t('back_to_panel_63039f103a', lang), callback_data="admin_panel")]
        ])
    )
    
    await safe_answer(callback)
    
    
@router.callback_query(F.data == "admin_clear_logs")
@admin_only(answer_on_denied=False)
async def admin_clear_logs_confirm(callback: CallbackQuery):
    """تایید پاک کردن لاگ‌ها"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    text = t('b_clear_logs_b_this_will_del_d2d155d887', lang)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t('yes_clear_b88e2e9da4', lang), callback_data="confirm_clear_logs", style="success"),
            InlineKeyboardButton(text=t('cancel_4197bafba5', lang), callback_data="admin_panel", style="danger")
        ]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await safe_answer(callback)


@router.callback_query(F.data == "confirm_clear_logs")
@admin_only
async def confirm_clear_logs(callback: CallbackQuery):
    """اجرای پاکسازی لاگ‌ها و داده‌های موقت"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    await callback.message.edit_text(t('i18n_cleaning_up', lang))

    cleared_items = []
    errors = []
    try:
        log_files = ['bot_debug.log', 'bot_error.log', 'bot.log']
        for log_file in log_files:
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    last_lines = lines[-100:] if len(lines) > 100 else lines

                with open(log_file, 'w', encoding='utf-8') as f:
                    f.write(f"=== Log cleared at: {now_tehran_iso()} ===\n")
                    f.write("=== Last 100 lines before cleanup ===\n")
                    f.writelines(last_lines)

                cleared_items.append(f"📄 {os.path.basename(log_file)}")
        logger.info('✅ Log files deleted')
    except Exception as e:
        err_str = str(e)[:50]
        error_msg = t('i18n_log_cleanup_error', lang, fa_parts=lambda: (err_str,), en_parts=lambda: (err_str,))
        errors.append(error_msg)
        logger.error(f"❌ {error_msg}")
    global chats
    try:
        closed_count = 0
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        
        for cid in list(chats.keys()):
            chat = chats[cid]
            if chat.get('status') == 'closed':
                closed_at = chat.get('closed_at', chat.get('updated_at', ''))
                if closed_at and closed_at < cutoff:
                    del chats[cid]
                    closed_count += 1
        
        if closed_count > 0:
            cleared_items.append(t('i18n_old_closed_chats', lang, fa_parts=lambda: (f'{closed_count}',), en_parts=lambda: (f'{closed_count}',)))
            save_json(DB_FILES['chats'], chats)
            logger.info(f"✅ {closed_count} old closed chat deleted")
    except Exception as e:
        err_str = str(e)[:50]
        error_msg = t('i18n_chats_cleanup_error', lang, fa_parts=lambda: (err_str,), en_parts=lambda: (err_str,))
        errors.append(error_msg)
        logger.error(f"❌ {error_msg}")
    global feedbacks
    try:
        if len(feedbacks) > 100:
            sorted_feedbacks = sorted(
                feedbacks.items(),
                key=lambda x: x[1].get('date', ''),
                reverse=True
            )
            feedbacks = dict(sorted_feedbacks[:50])
            cleared_items.append(t('i18n_feedback_entries', lang, fa_parts=lambda: (f'{len(feedbacks)}',), en_parts=lambda: (f'{len(feedbacks)}',)))
            save_json(DB_FILES['feedback'], feedbacks)
            logger.info(f"✅ Old feedback entries deleted - {len(feedbacks)} entries remaining")
    except Exception as e:
        err_str = str(e)[:50]
        error_msg = t('i18n_feedback_cleanup_error', lang, fa_parts=lambda: (err_str,), en_parts=lambda: (err_str,))
        errors.append(error_msg)
        logger.error(f"❌ {error_msg}")
    global orders
    try:
        cancelled_count = 0
        cutoff_30days = (datetime.now() - timedelta(days=30)).isoformat()
        
        for oid in list(orders.keys()):
            order = orders[oid]
            if isinstance(order, dict):
                status = order.get('status', '')
                if status in ['cancelled', 'awaiting_payment']:
                    created_at = order.get('created_at', order.get('date', ''))
                    if created_at and created_at < cutoff_30days:
                        del orders[oid]
                        cancelled_count += 1
        
        if cancelled_count > 0:
            cleared_items.append(t('i18n_old_pending_orders', lang, fa_parts=lambda: (f'{cancelled_count}',), en_parts=lambda: (f'{cancelled_count}',)))
            save_json(DB_FILES['orders'], orders)
            logger.info(f"✅ {cancelled_count} old pending order deleted")
    except Exception as e:
        err_str = str(e)[:50]
        error_msg = t('i18n_orders_cleanup_error', lang, fa_parts=lambda: (err_str,), en_parts=lambda: (err_str,))
        errors.append(error_msg)
        logger.error(f"❌ {error_msg}")
    global _db_cache, _db_modified
    try:
        cache_size = len(_db_cache)
        _db_cache.clear()
        _db_modified.clear()
        cleared_items.append(t('i18n_db_cache_items', lang, fa_parts=lambda: (f'{cache_size}',), en_parts=lambda: (f'{cache_size}',)))
        logger.info(f"✅ Database cache cleared - {cache_size} items")
    except Exception as e:
        err_str = str(e)[:50]
        error_msg = t('i18n_cache_cleanup_error', lang, fa_parts=lambda: (err_str,), en_parts=lambda: (err_str,))
        errors.append(error_msg)
    global user_states
    try:
        states_count = len(user_states)
        user_states.clear()
        cleared_items.append(t('i18n_user_states_items', lang, fa_parts=lambda: (f'{states_count}',), en_parts=lambda: (f'{states_count}',)))
        logger.info(f"✅ User states cleared - {states_count} entries")
    except Exception as e:
        err_str = str(e)[:50]
        error_msg = t('i18n_states_cleanup_error', lang, fa_parts=lambda: (err_str,), en_parts=lambda: (err_str,))
        errors.append(error_msg)
    text = t('b_cleanup_completed_b_c64cb8b016', lang)
    if cleared_items:
        text += t('b_cleared_items_b_867084f98a', lang)
        for item in cleared_items:
            text += f"• {item}\n"

    if errors:
        text += t('b_errors_b_384fcde119', lang)
        for error in errors:
            text += f"• {error}\n"
    text += "\n━━━━━━━━━━━━━━━━━━\n"
    text += t('b_current_status_b_0501933a58', lang)
    text += t('users_d605f5759a', lang, fa_parts=lambda: (f'{len(users)}',), en_parts=lambda: (f'{len(users)}',))
    text += t('orders_c46a275ddd', lang, fa_parts=lambda: (f'{len(orders)}',), en_parts=lambda: (f'{len(orders)}',))
    text += t('chats_419ad51595', lang, fa_parts=lambda: (f'{len(chats)}',), en_parts=lambda: (f'{len(chats)}',))
    text += t('feedbacks_dcec5527a4', lang, fa_parts=lambda: (f'{len(feedbacks)}',), en_parts=lambda: (f'{len(feedbacks)}',))
    text += t('blacklisted_246ce6ae8d', lang, fa_parts=lambda: (f'{len(BLACKLIST)}',), en_parts=lambda: (f'{len(BLACKLIST)}',))
    text += f"\n🕐 <code>{now_tehran().strftime('%H:%M:%S')}</code>"

    buttons = [
        [InlineKeyboardButton(text=t('cleanup_again_dfa4b0053a', lang), callback_data="confirm_clear_logs")],
        [InlineKeyboardButton(text=t('back_to_panel_63039f103a', lang), callback_data="admin_panel")]
    ]
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer(t('cleanup_completed_e6a46e0634', lang), show_alert=True)

admin_clear_logs_execute = confirm_clear_logs

async def auto_log_cleanup():
    """پاکسازی خودکار فایل‌های لاگ هر 72 ساعت - ارسال گزارش به بات لاگ"""
    
    # از LOG_BOT_TOKEN و LOG_CHANNEL_ID استفاده کنید
    if not LOG_BOT_TOKEN or not LOG_CHANNEL_ID:
        logger.warning('⚠️ Log bot is not configured! Logs will be sent to the main bot.')
        log_bot = bot
        log_chat_id = ADMIN_ID_INT
    else:
        log_bot = Bot(token=LOG_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        log_chat_id = LOG_CHANNEL_ID
    
    logger.info("🧹 Auto log cleanup task started (every 72 hours)")
    
    await asyncio.sleep(300)
    
    try:
        while True:
            try:
                await asyncio.sleep(259200)  # 72 hours = 259200
                
                logger.info("🧹 Starting automatic log file cleanup...")
                
                # Calculate disk space before cleanup
                total_before, used_before, free_before = shutil.disk_usage(".")
                
                cleaned_files = []
                errors = []
                total_lines_before = 0
                total_lines_after = 0
                total_size_freed = 0  # Freed space in bytes
                
                log_files = ['bot_debug.log', 'bot_error.log', 'bot.log', 'events.log']
                
                for log_file in log_files:
                    if os.path.exists(log_file):
                        try:
                            # Get file size before cleanup
                            size_before = os.path.getsize(log_file)
                            
                            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                                lines = f.readlines()
                            
                            lines_before = len(lines)
                            total_lines_before += lines_before
                            
                            keep_lines = 500
                            last_lines = lines[-keep_lines:] if len(lines) > keep_lines else lines
                            lines_after = len(last_lines)
                            total_lines_after += lines_after
                            
                            with open(log_file, 'w', encoding='utf-8') as f:
                                f.write(f"=== Log auto cleaned: {now_tehran_iso()} ===\n")
                                f.write(f"=== {lines_after} last lines kept ===\n\n")
                                f.writelines(last_lines)
                            
                            # Get file size after cleanup
                            size_after = os.path.getsize(log_file)
                            size_freed = size_before - size_after
                            total_size_freed += size_freed
                            
                            cleaned_files.append({
                                'name': log_file,
                                'before': lines_before,
                                'after': lines_after,
                                'size_before': size_before,
                                'size_after': size_after,
                                'size_freed': size_freed
                            })
                            
                            logger.info(f"✅ File {log_file} cleaned ({lines_before} → {lines_after} lines, {size_freed / 1024:.1f} KB freed)")
                            
                        except Exception as e:
                            error_msg = f"Error cleaning {log_file}: {str(e)[:50]}"
                            errors.append(error_msg)
                            logger.error(f"❌ {error_msg}")
                
                # Calculate disk space after cleanup
                total_after, used_after, free_after = shutil.disk_usage(".")
                free_gained_mb = (free_after - free_before) / (1024 * 1024)
                
                # Helper function for formatting size
                def format_size(size_bytes):
                    if size_bytes >= 1024 * 1024:  # Larger than 1 MB
                        return f"{size_bytes / (1024 * 1024):.2f} MB"
                    elif size_bytes >= 1024:  # Larger than 1 KB
                        return f"{size_bytes / 1024:.1f} KB"
                    else:
                        return f"{size_bytes} B"
                
                # Send report to log bot
                if cleaned_files:
                    # Format total freed space
                    total_freed_display = format_size(total_size_freed)
                    
                    report = f"""
🧹 <b>Auto Log Cleanup Completed!</b>

🕐 Time: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}
📁 Files cleaned: {len(cleaned_files)}
📊 Lines removed: {total_lines_before - total_lines_after:,}
💾 Space freed: {total_freed_display}

<b>File Details:</b>
"""
                    for f in cleaned_files:
                        size_before_display = format_size(f['size_before'])
                        size_after_display = format_size(f['size_after'])
                        
                        if f['size_freed'] > 0:
                            freed_display = f"-{format_size(f['size_freed'])}"
                        else:
                            freed_display = "No change"
                        
                        report += f"• {f['name']}: {f['before']:,} → {f['after']:,} lines | {size_before_display} → {size_after_display} ({freed_display})\n"
                    
                    # Only show total freed space
                    report += f"\n💾 Total space freed: {free_gained_mb:.2f} MB"
                    
                    if errors:
                        report += "\n\n⚠️ <b>Errors:</b>\n"
                        for err in errors:
                            report += f"• {err}\n"
                    
                    try:
                        await log_bot.send_message(log_chat_id, report, parse_mode=ParseMode.HTML)
                        logger.info("✅ Auto cleanup report sent to log bot")
                    except Exception as e:
                        logger.error(f"❌ Error sending report to log bot: {e}")
                        try:
                            await bot.send_message(ADMIN_ID_INT, 
                                f"⚠️ Error sending to log bot: {e}\n\n{report[:500]}", 
                                parse_mode=ParseMode.HTML)
                        except Exception:
                            pass
                
            except asyncio.CancelledError:
                logger.info("❌ Auto log cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in auto log cleanup: {e}", exc_info=True)
                await asyncio.sleep(3600)
    finally:
        if LOG_BOT_TOKEN and LOG_CHANNEL_ID:
            try:
                await log_bot.session.close()
            except Exception:
                pass
                
@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_chat_reply'))
async def admin_chat_reply(message: Message):
    """پاسخ ادمین به چت - با بررسی بسته بودن چت"""
    
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    state = user_states.get(admin_id, {})
    chat_id = state.get('chat_id')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_cancelled_short', lang))
        return
    
    if not chat_id:
        return
    chat = chats.get(str(chat_id))
    if not chat:
        await message.reply(t('i18n_chat_not_found', lang))
        user_states.pop(admin_id, None)
        return
    
    if chat.get('status') == 'closed':
        await message.reply(
            t('i18n_admin_chat_closed', lang)
        )
        user_states.pop(admin_id, None)
        return
    try:
        reply_text = await relay_support_message(
            message,
            chat['user_id'],
            chat_id,
            sender_label="admin",
        )
    except Exception as e:
        logger.error(f"Error sending reply to ticket #{chat_id} to user {chat['user_id']}: {e}")
        await message.reply(t('i18n_reply_send_failed', lang))
        return
    add_message(chat_id, 'admin', reply_text)
    if log_system:
        await log_system.log_chat_message(chat['user_id'], chat_id, reply_text, "admin")
    await message.reply(t('i18n_message_sent_continue_or_cancel', lang))



@router.message(Command("check_user_coupon"), IsAdmin())
async def cmd_check_user_coupon(message: Message):
    """بررسی کوپن کاربر در دیتابیس (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    parts = message.text.split()
    lang = get_user(message.from_user.id).get('lang', 'fa')
    if len(parts) < 2:
        target_id = message.from_user.id
        target_name = t('i18n_admin_self', lang)
    else:
        try:
            target_id = int(parts[1])
            target_name = t('i18n_user_with_id', lang, fa_parts=lambda: (f'{target_id}',), en_parts=lambda: (f'{target_id}',))
        except ValueError:
            await message.reply(t('i18n_enter_valid_numeric_id', lang))
            return
    uid = str(target_id)

    if uid not in users:
        await message.reply(t('i18n_user_not_found_in_db_short', lang, fa_parts=lambda: (f'{target_id}',), en_parts=lambda: (f'{target_id}',)))
        return
    
    user = users[uid]
    coupon_code = user.get('coupon_code')
    coupon_applied = user.get('coupon_applied', False)
    coupon_discount = user.get('coupon_discount', 0)
    user_state = user_states.get(target_id, {})
    state_code = user_state.get('coupon_code')
    state_applied = user_state.get('coupon_applied', False)
    state_discount = user_state.get('coupon_discount', 0)
    coupon_valid = False
    coupon_status = None
    is_used = False
    
    if coupon_code and coupon_code in COUPONS:
        coupon = COUPONS[coupon_code]
        coupon_valid = True
        coupon_status = coupon.get('status', 'unknown')
        coupon_used_by = coupon.get('used_by', [])
        is_used = target_id in coupon_used_by
    user_info = await get_user_info_from_telegram(target_id)
    
    yes = '✅'
    no = '❌'
    text = t('i18n_coupon_check_title', lang, fa_parts=lambda: (f"{user_info['full_name']}", f'{target_name}', f'{target_id}', f"{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}", yes if coupon_applied else no, f"{(coupon_code if coupon_code else t('i18n_none', lang))}", f'{coupon_discount}', yes if state_applied else no, f"{(state_code if state_code else t('i18n_none', lang))}", f'{state_discount}', yes if coupon_valid else no, f"{(coupon_status if coupon_status else t('i18n_unknown', lang))}", yes if is_used else no), en_parts=lambda: (f"{user_info['full_name']}", f'{target_name}', f'{target_id}', f"{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}", yes if coupon_applied else no, f"{(coupon_code if coupon_code else t('i18n_none', lang))}", f'{coupon_discount}', yes if state_applied else no, f"{(state_code if state_code else t('i18n_none', lang))}", f'{state_discount}', yes if coupon_valid else no, f"{(coupon_status if coupon_status else t('i18n_unknown', lang))}", yes if is_used else no))
    
    if coupon_code and coupon_code in COUPONS:
        coupon = COUPONS[coupon_code]
        text += t('i18n_coupon_check_extra', lang, fa_parts=lambda: (f"{coupon.get('used_count', 0)}", f"{coupon.get('usage_limit', t('i18n_unlimited', lang))}", f"{coupon.get('expiry_date', t('i18n_unlimited', lang))}"), en_parts=lambda: (f"{coupon.get('used_count', 0)}", f"{coupon.get('usage_limit', t('i18n_unlimited', lang))}", f"{coupon.get('expiry_date', t('i18n_unlimited', lang))}"))

    if coupon_applied == state_applied and coupon_code == state_code:
        sync_note = t('i18n_coupon_sync_ok', lang)
    else:
        sync_note = t('i18n_coupon_sync_mismatch', lang)
    text += t('i18n_coupon_check_note', lang, fa_parts=lambda: (f'{sync_note}',), en_parts=lambda: (f'{sync_note}',))
    
    await message.reply(text, parse_mode=ParseMode.HTML)
    
    
 
@router.callback_query(F.data == "panel_test")
@admin_only
async def admin_test_panel(callback: CallbackQuery):
    """تست کامل پنل + پینگ به سرورهای معروف"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    await callback.message.edit_text(t('i18n_testing_connection', lang))
    panel_result = await test_panel_connection()
    dns_targets = [
        ('Google DNS', '8.8.8.8'),
        ('Cloudflare DNS', '1.1.1.1'),
        ('Quad9', '9.9.9.9'),
        ('OpenDNS', '208.67.222.222'),
    ]

    ping_tasks = [
        smart_ping(ip)
        for _, ip in dns_targets
    ]

    ping_values = await asyncio.gather(*ping_tasks)

    ping_results = {}

    for (name, ip), value in zip(dns_targets, ping_values):
        if value is not None:
            ping_results[f'🟢 {name}'] = f'{value:.1f}ms'
        else:
            ping_results[f'🔴 {name}'] = 'Timeout'
    http_targets = [
        ('Google', 'https://www.google.com'),
        ('YouTube', 'https://www.youtube.com'),
        ('Telegram', 'https://telegram.org'),
        ('GitHub', 'https://github.com'),
    ]
    
    for name, url in http_targets:
        try:
            start = time.time()
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    elapsed = int((time.time() - start) * 1000)
                    ping_results[f'🌐 {name}'] = f'{elapsed}ms'
        except Exception:
            ping_results[f'🔴 {name}'] = 'Timeout'
    panel_enabled = is_senai_panel_enabled()
    text = t('b_panel_status_b_304021a725', lang)
    text += t('url_tg_spoiler_tg_spoiler_ef9094e90d', lang, fa_parts=lambda: (f'{html.escape(SENAI_PANEL_URL)}',), en_parts=lambda: (f'{html.escape(SENAI_PANEL_URL)}',))
    text += t('status_2e5ef52720', lang, fa_parts=lambda: (f"{t('i18n_status_active', lang) if panel_enabled else t('i18n_status_inactive', lang)}",), en_parts=lambda: (f"{t('i18n_status_active', lang) if panel_enabled else t('i18n_status_inactive', lang)}",))

    if panel_enabled:
        ping_display = f"{panel_result['ping']}ms" if panel_result['ping'] is not None else "❌"
        text += t('ping_5cdf6bfeca', lang, fa_parts=lambda: (f'{ping_display}',), en_parts=lambda: (f'{ping_display}',))

        text += t('login_d10a75bf05', lang, fa_parts=lambda: (f"{('✅' if panel_result['login'] else '❌')}",), en_parts=lambda: (f"{('✅' if panel_result['login'] else '❌')}",))
        if panel_result['login']:
            text += t('inbounds_c9ab901235', lang, fa_parts=lambda: (f"{panel_result['inbounds']}",), en_parts=lambda: (f"{panel_result['inbounds']}",))
        if panel_result['error']:
            text += f"⚠️ {panel_result['error']}\n"
        text += "\n"

    text += t('b_dns_ping_b_1d1181eeef', lang)
    for key in ping_results:
        if 'DNS' in key:
            text += f"  {key}: <code>{ping_results[key]}</code>\n"

    text += t('b_site_ping_b_ad11a9eab8', lang)
    for key in ping_results:
        if '🌐' in key or '🔴' in key:
            text += f"  {key}: <code>{ping_results[key]}</code>\n"
    
    text += f"\n<code>🕐 {now_tehran().strftime('%H:%M:%S')}</code>"
    buttons = [[InlineKeyboardButton(text=t('retest_d4ef8a8e93', lang), callback_data="panel_test")]]
    
    if panel_enabled:
        buttons.append([InlineKeyboardButton(text=t('disable_51235c0132', lang), callback_data="admin_toggle_panel")])
    else:
        buttons.append([InlineKeyboardButton(text=t('enable_bd8a5598cc', lang), callback_data="admin_toggle_panel")])
    
    buttons.append([InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data == "admin_toggle_panel")
@admin_only
async def admin_toggle_panel(callback: CallbackQuery):
    """روشن/خاموش کردن پنل"""
    
    new_state = set_senai_panel_enabled(not is_senai_panel_enabled())
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if new_state:
        await callback.answer(t('panel_enabled_704ac41a36', lang), show_alert=True)
    else:
        await callback.answer(t('panel_disabled_faf082c855', lang), show_alert=True)
    
    await admin_test_panel(callback)
    


def clean_comment_text(comment: str) -> str:
    """
    پاکسازی کامنت از تگ‌های HTML و کاراکترهای یونیکد فانتزی
    """
    if not comment:
        return ""
    
    # حذف تگ‌های HTML
    comment = re.sub(r'<[^>]+>', '', comment)
    
    # تبدیل HTML entities
    comment = html.unescape(comment)
    
    # نرمال‌سازی یونیکد (تبدیل کاراکترهای فانتزی به ASCII)
    comment = unicodedata.normalize('NFKD', comment)
    comment = comment.encode('ascii', 'ignore').decode('ascii')
    
    # حذف فاصله‌های اضافی
    comment = ' '.join(comment.split())
    
    return comment

def extract_user_info_from_comment(comment: str):
    """
    استخراج ID و نام کاربر از کامنت
    Returns: (user_id, user_name, is_bot_client, order_type)
    """
    if not comment:
        return None, None, False, 'purchase'
    
    # پاکسازی کامنت
    cleaned_comment = clean_comment_text(comment)
    
    if not cleaned_comment:
        return None, None, False, 'purchase'
    
    user_id = None
    user_name = None
    is_bot_client = False
    order_type = 'purchase'
    
    # الگوهای مختلف برای شناسایی ID
    id_patterns = [
        r'\(ID[:=](\d+)\)',
        r'ID\s*[:=]\s*(\d+)',
        r'\|\s*ID\s*[:=]\s*(\d+)',
        r'user\s*(\d+)',
        r'کاربر\s*(\d+)',
        r'\(\s*(\d{6,})\s*\)',
        r'(?:^|\s)(\d{9,})(?:\s|$)',
    ]
    
    for pattern in id_patterns:
        match = re.search(pattern, cleaned_comment, re.IGNORECASE)
        if match:
            user_id = int(match.group(1))
            is_bot_client = True
            break
    
    # اگر ID پیدا نشد، جستجوی اعداد طولانی
    if not user_id:
        numbers = re.findall(r'\d+', cleaned_comment)
        if numbers:
            long_numbers = [n for n in numbers if len(n) >= 6]
            if long_numbers:
                user_id = int(max(long_numbers, key=len))
                is_bot_client = True
    
    # استخراج نام کاربر
    if user_id and is_bot_client:
        name_part = cleaned_comment
        name_part = re.sub(r'\(ID[:=]\d+\)', '', name_part)
        name_part = re.sub(r'ID\s*[:=]\s*\d+', '', name_part)
        name_part = re.sub(r'\|\s*ID\s*[:=]\s*\d+', '', name_part)
        name_part = re.sub(r'user\s*\d+', '', name_part)
        name_part = re.sub(r'کاربر\s*\d+', '', name_part)
        name_part = re.sub(r'\(\s*\d{6,}\s*\)', '', name_part)
        name_part = re.sub(r'\d{9,}', '', name_part)
        
        name_part = name_part.strip()
        name_part = re.sub(r'[\s\|\(\)\[\]\.]+$', '', name_part)
        name_part = name_part.strip()
        
        if name_part and len(name_part) >= 1:
            user_name = name_part
        else:
            user_name = f'کاربر_{user_id}'
        
        # تشخیص تست
        if 'test' in cleaned_comment.lower() or 'تست' in cleaned_comment.lower():
            order_type = 'test'
    
    return user_id, user_name, is_bot_client, order_type 
async def sync_deleted_configs(batch_size: int = 20, max_retries: int = 3):
    """
    همگام‌سازی کامل با پنل
    
    - کانفیگ‌های فعال در پنل → approved
    - کانفیگ‌های غیرفعال در پنل → inactive
    - کانفیگ‌های حذف شده از پنل → deleted
    - ✅ کانفیگ‌های جدید در پنل → ایجاد سفارش جدید
    - کاربران بدون کانفیگ حذف نمی‌شوند
    """
    if not is_senai_panel_enabled():
        logger.info('📴 Panel is disabled - synchronization skipped')
        return {'approved': 0, 'inactive': 0, 'deleted': 0, 'new': 0, 'total_checked': 0}
    
    logger.info('🔄 starting sync with panel...')
    
    try:
        user_balances = {}
        user_coupons = {}
        
        for uid, user_data in users.items():
            user_balances[uid] = user_data.get('balance', 0)
            user_coupons[uid] = {
                'coupon_code': user_data.get('coupon_code'),
                'coupon_discount': user_data.get('coupon_discount', 0),
                'coupon_applied': user_data.get('coupon_applied', False)
            }
        
        logger.info(f"💰 Information for {len(user_balances)} user saved")
        logger.info('📡 Fetching information from the panel...')
        
        inbounds = await xui_get_inbounds()
        if not inbounds:
            logger.error('❌ No inbounds found')
            return {'approved': 0, 'inactive': 0, 'deleted': 0, 'new': 0, 'total_checked': 0}
        clients_dict = {}
        skipped_clients = 0
        bot_clients = 0
        users_with_configs = set()
        
        for inbound in inbounds:
            inbound_id = inbound.get('id')
            remark = inbound.get('remark', f'Inbound_{inbound_id}')
            protocol = inbound.get('protocol', 'unknown')
            port = inbound.get('port', '')
            settings = inbound.get('settings', {})
            inbound_clients = settings.get('clients', [])
            
            for client in inbound_clients:
                email = client.get('email', '')
                if not email:
                    continue
                is_bot_client = False
                user_id = None
                order_type = 'purchase'
                comment = client.get('comment', '')
                is_active = client.get('enable', True)
                
                if email.startswith('t') and '_' in email:
                    match = re.search(r't(\d+)_\d+', email)
                    if match:
                        user_id = int(match.group(1))
                        is_bot_client = True
                        order_type = 'test'
                elif email.startswith('u') and '_' in email:
                    match = re.search(r'u(\d+)_\d+', email)
                    if match:
                        user_id = int(match.group(1))
                        is_bot_client = True
                        order_type = 'purchase'
                elif email.startswith('test_'):
                    parts = email.split('_')
                    if len(parts) >= 2 and parts[1].isdigit():
                        user_id = int(parts[1])
                        is_bot_client = True
                        order_type = 'test'
                elif email.startswith('user'):
                    match = re.search(r'user(\d+)', email)
                    if match:
                        user_id = int(match.group(1))
                        is_bot_client = True
                        order_type = 'purchase'
                if not is_bot_client and comment:
                    try:
                        user_id, extracted_name, is_bot_client, order_type = extract_user_info_from_comment(comment)
                        
                        if is_bot_client and user_id:
                            logger.info(f"✅ user {user_id} identified from comment: {comment[:50]}...")
                            
                            # ذخیره نام کاربر اگر موجود بود
                            if extracted_name and extracted_name != f'کاربر_{user_id}':
                                uid_temp = str(user_id)
                                if uid_temp in users:
                                    if not users[uid_temp].get('name') or users[uid_temp]['name'].startswith('کاربر'):
                                        users[uid_temp]['name'] = extracted_name
                                        logger.info(f"📝 User name {user_id} to \'{extracted_name}\' was updated")
                    except Exception as e:
                        logger.error(f"❌ Error extracting information from comment: {e}")
                        user_id = None
                        is_bot_client = False
                
                if is_bot_client and user_id:
                    bot_clients += 1
                    users_with_configs.add(user_id)
                    
                    if email not in clients_dict:
                        clients_dict[email] = {
                            'email': email,
                            'totalGB': client.get('totalGB', 0),
                            'expiryTime': client.get('expiryTime', 0),
                            'enable': is_active,
                            'user_id': user_id,
                            'comment': comment,
                            'order_type': order_type,
                            'inbound_ids': [],
                            'inbound_details': [],
                            'ip_limit': client.get('limitIp', 0),
                            'subId': client.get('subId', '') or email
                        }
                    
                    clients_dict[email]['inbound_ids'].append(inbound_id)
                    clients_dict[email]['inbound_details'].append({
                        'inbound_id': inbound_id,
                        'remark': remark,
                        'protocol': protocol,
                        'port': port
                    })
                    
                    status_text = "🟢 فعال" if is_active else "🔴 غیرفعال"
                    logger.debug(f"✅ Client: {email} (User: {user_id}) - {status_text}")
                else:
                    skipped_clients += 1
        
        clients = list(clients_dict.values())
        
        logger.info(f"✅ {len(clients)} unique client found")
        logger.info(f"👥 {len(users_with_configs)} user with config")
        
        if not clients:
            logger.warning('⚠️ No clients found in the panel')
            return {'approved': 0, 'inactive': 0, 'deleted': 0, 'new': 0, 'total_checked': 0}
        logger.info('👤 Updating users...')
        
        for user_id in users_with_configs:
            uid = str(user_id)
            if uid in users:
                users[uid]['has_purchased'] = True
                users[uid]['updated_at'] = now_tehran_iso()
            else:
                # اول تلاش برای دریافت از تلگرام
                user_name = f'کاربر_{user_id}'
                telegram_username = ''
                
                try:
                    user_info = await get_user_info_from_telegram(user_id)
                    if user_info:
                        full_name = user_info.get('full_name', '')
                        if full_name and full_name.strip():
                            user_name = full_name
                        telegram_username = user_info.get('username', '')
                except Exception as e:
                    logger.warning(f"⚠️ Error retrieving Telegram information for {user_id}: {e}")
                
                # اگر نام از تلگرام نگرفتیم، از کامنت‌های موجود استفاده کن
                if user_name == f'کاربر_{user_id}':
                    for client_data in clients_dict.values():
                        if client_data.get('user_id') == user_id:
                            comment_text = client_data.get('comment', '')
                            if comment_text:
                                _, extracted_name, _, _ = extract_user_info_from_comment(comment_text)
                                if extracted_name and extracted_name != f'کاربر_{user_id}':
                                    user_name = extracted_name
                                    break                
                users[uid] = {
                    'id': user_id,
                    'name': user_name,
                    'username': '',
                    'telegram_username': '',
                    'balance': 0,
                    'volume': 1,
                    'days': 30,
                    'lang': 'fa',
                    'referred_by': None,
                    'has_purchased': True,
                    'join_date': now_tehran().strftime('%Y/%m/%d'),
                    'total_purchases': 0,
                    'total_spent': 0,
                    'last_purchase_date': now_tehran().strftime('%Y-%m-%d %H:%M:%S'),
                    'is_active': True,
                    'verified': False,
                    'notes': f'ایجاد شده از همگام‌سازی - {now_tehran().strftime("%Y-%m-%d %H:%M:%S")}',
                    'created_at': now_tehran_iso(),
                    'updated_at': now_tehran_iso(),
                    'coupon_code': None,
                    'coupon_discount': 0,
                    'coupon_applied': False,
                    'approved_by_admin': True,
                    'approved_date': now_tehran_iso(),
                    'requested_approval': False,
                    'registration_status': 'approved'
                }
        for uid, balance in user_balances.items():
            if uid in users:
                users[uid]['balance'] = balance
                if uid in user_coupons:
                    users[uid]['coupon_code'] = user_coupons[uid]['coupon_code']
                    users[uid]['coupon_discount'] = user_coupons[uid]['coupon_discount']
                    users[uid]['coupon_applied'] = user_coupons[uid]['coupon_applied']
        
        logger.info(f"💰 Balance for {len(user_balances)} user preserved")
        logger.info('💾 Saving previous order data from the database...')
        old_order_info = {}
        existing_emails = set()
        
        for oid, order in orders.items():
            if isinstance(order, dict):
                email = order.get('email')
                if email:
                    old_order_info[email] = {
                        'order_id': order.get('order_id'),
                        'date': order.get('date', now_tehran().strftime("%Y-%m-%d %H:%M:%S")),
                        'days': order.get('days', 30),
                        'price': order.get('price', 0),
                        'volume': order.get('volume', 0),
                        'status': order.get('status', 'approved'),
                        'type': order.get('type', 'purchase'),
                        'payment_method': order.get('payment_method', 'sync_from_panel'),
                        'payment_label': order.get('payment_label', ''),
                        'receipt_photo_id': order.get('receipt_photo_id'),
                        **get_receipt_status_metadata(order),
                        'config_id': order.get('config_id'),
                        'notes': order.get('notes', ''),
                        'created_at': order.get('created_at', now_tehran_iso()),
                        # ✅ اینا رو اضافه کن - اطلاعات بسته آماده
                        'category_id': order.get('category_id'),
                        'category_name': order.get('category_name'),
                        'category_name_en': order.get('category_name_en'),
                        'package_id': order.get('package_id'),
                        'parent_order_id': order.get('parent_order_id'),
                        'is_extend': order.get('is_extend', False),
                        'ip_limit': order.get('ip_limit', 0),
                    }
                    existing_emails.add(email)
        
        logger.info(f"📋 Information for {len(old_order_info)} previous order saved from the database")
        logger.info('📝 Updating orders based on the panel...')
        
        stats = {
            'approved': 0,
            'inactive': 0,
            'deleted': 0,
            'new': 0,
            'total_checked': len(clients)
        }
        for client in clients:
            email = client.get('email', '')
            user_id = client.get('user_id')
            order_type = client.get('order_type', 'purchase')
            comment = client.get('comment', '')
            ip_limit = client.get('ip_limit', 0)
            is_active = client.get('enable', True)
            total_gb_from_panel = client.get('totalGB', 0) / (1024**3)
            total_gb_from_panel = round(total_gb_from_panel, 6)
            
            sub_link = build_sub_link_from_client(email, client)
            sub_id_value = client.get('subId', '') or email
            inbound_ids = client.get('inbound_ids', [])
            is_test = order_type == 'test' or email.startswith('test_') or email.startswith('t')
            old_info = old_order_info.get(email)
            
            if old_info:
                order_id = old_info['order_id']
                original_date = old_info['date']
                days = old_info['days']
                price = old_info['price']
                volume_gb = old_info['volume']
                order_type = old_info['type']
                payment_method = old_info['payment_method']
                receipt_photo_id = old_info['receipt_photo_id']
                config_id = old_info['config_id']
                notes = old_info.get('notes', '')
                created_at = old_info.get('created_at', now_tehran_iso())
                if is_active:
                    status = 'approved'
                    stats['approved'] += 1
                else:
                    status = 'inactive'
                    stats['inactive'] += 1
                    
                logger.debug(f"🔄 Order update #{order_id} - {email} - Status: {status}")
                
            else:
                order_id = get_next_order_id()
                original_date = now_tehran().strftime("%Y-%m-%d %H:%M:%S")
                days = 30
                price = 0
                volume_gb = total_gb_from_panel
                payment_method = 'sync_from_panel'
                receipt_photo_id = None
                config_id = None
                notes = f'ایجاد شده از همگام‌سازی - {now_tehran().strftime("%Y-%m-%d %H:%M:%S")}'
                created_at = now_tehran_iso()
                
                if is_active:
                    status = 'approved'
                    stats['approved'] += 1
                else:
                    status = 'inactive'
                    stats['inactive'] += 1
                
                stats['new'] += 1
                logger.info(f"🆕 New order #{order_id} - {email} - user {user_id}")
            # ✅ اگه سفارش قبلی داشت، این فیلدها رو نگه دار
            preserved_category_id = None
            preserved_category_name = None
            preserved_category_name_en = None
            preserved_package_id = None
            preserved_parent_order_id = None
            preserved_is_extend = False
            preserved_ip_limit = ip_limit
            preserved_payment_label = ''

            if old_info:
                preserved_category_id = old_info.get('category_id')
                preserved_category_name = old_info.get('category_name')
                preserved_category_name_en = old_info.get('category_name_en')
                preserved_package_id = old_info.get('package_id')
                preserved_parent_order_id = old_info.get('parent_order_id')
                preserved_is_extend = old_info.get('is_extend', False)
                preserved_ip_limit = old_info.get('ip_limit', ip_limit)
                preserved_payment_label = old_info.get('payment_label', '')

            orders[str(order_id)] = {
                'order_id': order_id,
                'user_id': user_id,
                'volume': volume_gb,
                'days': days,
                'price': price,
                'type': order_type,
                'status': status,
                'date': original_date,
                'approved_date': old_info.get('date') if old_info and old_info['status'] == 'approved' else (now_tehran().strftime("%Y-%m-%d %H:%M:%S") if is_active else None),
                'config_link': sub_link,
                'config_id': config_id,
                'receipt_photo_id': receipt_photo_id,
                **get_receipt_status_metadata(old_info or {}),
                'email': email,
                'sub_id': sub_id_value,
                'sub_link': sub_link,
                'panel_client_id': None,
                'payment_method': payment_method,
                'payment_label': preserved_payment_label,
                'rejected_reason': '',
                'inbound_id': inbound_ids,
                'inbound_details': client.get('inbound_details', []),
                'created_at': created_at,
                'updated_at': now_tehran_iso(),
                'notes': notes,
                'ip_limit': preserved_ip_limit,
                'is_active_in_panel': is_active,
                'is_test': is_test,
                'volume_unit': 'GB',
                # ✅ اینا رو اضافه کن - اطلاعات بسته آماده
                'category_id': preserved_category_id,
                'category_name': preserved_category_name,
                'category_name_en': preserved_category_name_en,
                'package_id': preserved_package_id,
                'parent_order_id': preserved_parent_order_id,
                'is_extend': preserved_is_extend,
            }
            if is_test and volume_gb < 1:
                display_volume = f"{volume_gb * 1024:.1f}MB"
            else:
                display_volume = f"{volume_gb:.2f}GB"
            
            status_icon = "🟢" if is_active else "🔴"
            logger.info(f"📝 Order #{order_id} - user {user_id} - {display_volume}/{days} days - {price} tomans - {status_icon}")
        deleted_configs = []
        for oid, order in orders.items():
            email = order.get('email')
            if order.get('status') in ['approved', 'inactive'] and email and email not in clients_dict:
                deleted_configs.append(order)

        for order in deleted_configs:
            orders[str(order['order_id'])]['status'] = 'deleted'
            stats['deleted'] += 1
            logger.info(f"🗑 Config #{order['order_id']} deleted from the panel - status changed to deleted")        
        save_all()
        logger.info('✅ Database saved successfully')
        logger.info("=" * 60)
        logger.info("📊 Synchronization result:")
        logger.info(f"  🟢 Active: {stats['approved']}")
        logger.info(f"  🔴 Inactive: {stats['inactive']}")
        logger.info(f"  🆕 New: {stats['new']}")
        logger.info(f"  🗑 Deleted: {stats['deleted']}")
        logger.info(f"  📋 Total: {stats['total_checked']}")
        logger.info("=" * 60)
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Error during synchronization: {e}", exc_info=True)
        return {'approved': 0, 'inactive': 0, 'deleted': 0, 'new': 0, 'total_checked': 0}


async def sync_user_configs(user_id: int) -> dict:
    """
    همگام‌سازی کامل یک کاربر با پنل — دقیقاً مثل sync_deleted_configs
    ولی فقط روی سفارش‌های همین کاربر.
    - کانفیگ جدید در پنل → سفارش جدید ساخته می‌شه
    - کانفیگ حذف شده → status=deleted
    - کانفیگ غیرفعال → status=inactive
    - inbound_ids/inbound_details/volume/days آپدیت می‌شن
    """
    if not is_senai_panel_enabled():
        return {'approved': 0, 'inactive': 0, 'deleted': 0, 'new': 0, 'total_checked': 0}

    uid_str = str(user_id)

    # ─── 1. حفظ موجودی و کوپن کاربر ───
    user_balance = None
    user_coupon = None
    if uid_str in users:
        user_balance = users[uid_str].get('balance', 0)
        user_coupon = {
            'coupon_code': users[uid_str].get('coupon_code'),
            'coupon_discount': users[uid_str].get('coupon_discount', 0),
            'coupon_applied': users[uid_str].get('coupon_applied', False),
        }

    # ─── 2. دریافت اینباندها (با force_refresh) ───
    inbounds = await xui_get_inbounds(force_refresh=True)
    if not inbounds:
        logger.error(f"❌ [sync_user_configs] user={user_id}: No inbounds found")
        return {'approved': 0, 'inactive': 0, 'deleted': 0, 'new': 0, 'total_checked': 0}

    # ─── 3. جمع‌آوری فقط کلاینت‌های همین کاربر ───
    clients_dict = {}
    user_has_configs = False

    for inbound in inbounds:
        inbound_id = inbound.get('id')
        remark = inbound.get('remark', f'Inbound_{inbound_id}')
        protocol = inbound.get('protocol', 'unknown')
        port = inbound.get('port', '')
        settings = inbound.get('settings', {})

        for client in settings.get('clients', []):
            email = client.get('email', '')
            if not email:
                continue

            # شناسایی user_id از email
            extracted_uid = None
            extracted_type = 'purchase'
            comment = client.get('comment', '')

            if email.startswith('t') and '_' in email:
                m = re.search(r't(\d+)_\d+', email)
                if m:
                    extracted_uid = int(m.group(1)); extracted_type = 'test'
            elif email.startswith('u') and '_' in email:
                m = re.search(r'u(\d+)_\d+', email)
                if m:
                    extracted_uid = int(m.group(1)); extracted_type = 'purchase'
            elif email.startswith('test_'):
                parts = email.split('_')
                if len(parts) >= 2 and parts[1].isdigit():
                    extracted_uid = int(parts[1]); extracted_type = 'test'
            elif email.startswith('user'):
                m = re.search(r'user(\d+)', email)
                if m:
                    extracted_uid = int(m.group(1)); extracted_type = 'purchase'

            if extracted_uid is None and comment:
                try:
                    cid, _, is_bot, ctype = extract_user_info_from_comment(comment)
                    if is_bot and cid:
                        extracted_uid = cid; extracted_type = ctype
                except Exception:
                    pass

            # ✅ فقط همین کاربر
            if extracted_uid != user_id:
                continue

            user_has_configs = True
            is_active = client.get('enable', True)

            if email not in clients_dict:
                clients_dict[email] = {
                    'email': email,
                    'totalGB': client.get('totalGB', 0),
                    'expiryTime': client.get('expiryTime', 0),
                    'enable': is_active,
                    'user_id': user_id,
                    'comment': comment,
                    'order_type': extracted_type,
                    'inbound_ids': [],
                    'inbound_details': [],
                    'ip_limit': client.get('limitIp', 0),
                    'subId': client.get('subId', '') or email,
                }

            clients_dict[email]['inbound_ids'].append(inbound_id)
            clients_dict[email]['inbound_details'].append({
                'inbound_id': inbound_id,
                'remark': remark,
                'protocol': protocol,
                'port': port,
            })

    clients = list(clients_dict.values())
    logger.info(f"📊 [sync_user_configs] user={user_id}: {len(clients)} client in panel")

    # ─── 4. آپدیت has_purchased ───
    if user_has_configs and uid_str in users:
        users[uid_str]['has_purchased'] = True
        users[uid_str]['updated_at'] = now_tehran_iso()

    # ─── 5. بازگرداندن موجودی و کوپن ───
    if user_balance is not None and uid_str in users:
        users[uid_str]['balance'] = user_balance
        if user_coupon:
            users[uid_str]['coupon_code'] = user_coupon['coupon_code']
            users[uid_str]['coupon_discount'] = user_coupon['coupon_discount']
            users[uid_str]['coupon_applied'] = user_coupon['coupon_applied']

    # ─── 6. ذخیره اطلاعات سفارشات قبلی این کاربر ───
    old_order_info = {}
    for oid, order in orders.items():
        if not isinstance(order, dict):
            continue
        if order.get('user_id') != user_id:
            continue
        email = order.get('email')
        if not email:
            continue
        old_order_info[email] = {
            'order_id': order.get('order_id'),
            'date': order.get('date', now_tehran().strftime("%Y-%m-%d %H:%M:%S")),
            'days': order.get('days', 30),
            'price': order.get('price', 0),
            'volume': order.get('volume', 0),
            'status': order.get('status', 'approved'),
            'type': order.get('type', 'purchase'),
            'payment_method': order.get('payment_method', 'sync_from_panel'),
            'payment_label': order.get('payment_label', ''),
            'receipt_photo_id': order.get('receipt_photo_id'),
            **get_receipt_status_metadata(order),
            'config_id': order.get('config_id'),
            'notes': order.get('notes', ''),
            'created_at': order.get('created_at', now_tehran_iso()),
            'category_id': order.get('category_id'),
            'category_name': order.get('category_name'),
            'category_name_en': order.get('category_name_en'),
            'package_id': order.get('package_id'),
            'parent_order_id': order.get('parent_order_id'),
            'is_extend': order.get('is_extend', False),
            'ip_limit': order.get('ip_limit', 0),
        }

    # ─── 7. آپدیت / ساخت سفارش ───
    stats = {'approved': 0, 'inactive': 0, 'deleted': 0, 'new': 0, 'total_checked': len(clients)}

    for client in clients:
        email = client.get('email', '')
        order_type = client.get('order_type', 'purchase')
        ip_limit = client.get('ip_limit', 0)
        is_active = client.get('enable', True)
        total_gb = round(client.get('totalGB', 0) / (1024 ** 3), 6)

        sub_link = build_sub_link_from_client(email, client)
        sub_id_value = client.get('subId', '') or email
        inbound_ids = client.get('inbound_ids', [])
        is_test = order_type == 'test' or email.startswith('test_') or email.startswith('t')
        old_info = old_order_info.get(email)

        if old_info:
            order_id = old_info['order_id']
            days = old_info['days']
            price = old_info['price']
            volume_gb = old_info['volume']
            order_type = old_info['type']
            original_date = old_info['date']
            payment_method = old_info['payment_method']
            receipt_photo_id = old_info['receipt_photo_id']
            config_id = old_info['config_id']
            notes = old_info['notes']
            created_at = old_info['created_at']
            status = 'approved' if is_active else 'inactive'
            stats[status] += 1
        else:
            # ✅ سفارش جدید از کلاینت یتیم پنل
            order_id = get_next_order_id()
            days = 30
            price = 0
            volume_gb = total_gb
            original_date = now_tehran().strftime("%Y-%m-%d %H:%M:%S")
            payment_method = 'sync_from_panel'
            receipt_photo_id = None
            config_id = None
            notes = f'ایجاد شده از همگام‌سازی کاربر - {now_tehran().strftime("%Y-%m-%d %H:%M:%S")}'
            created_at = now_tehran_iso()
            status = 'approved' if is_active else 'inactive'
            stats[status] += 1
            stats['new'] += 1
            logger.info(f"🆕 [sync_user_configs] New order #{order_id} for user {user_id} - {email}")

        orders[str(order_id)] = {
            'order_id': order_id,
            'user_id': user_id,
            'volume': volume_gb,
            'days': days,
            'price': price,
            'type': order_type,
            'status': status,
            'date': original_date,
            'approved_date': (
                old_info['date'] if old_info and old_info['status'] == 'approved'
                else (now_tehran().strftime("%Y-%m-%d %H:%M:%S") if is_active else None)
            ),
            'config_link': sub_link,
            'config_id': config_id,
            'receipt_photo_id': receipt_photo_id,
            **get_receipt_status_metadata(old_info or {}),
            'email': email,
            'sub_id': sub_id_value,
            'sub_link': sub_link,
            'panel_client_id': None,
            'payment_method': payment_method,
            'payment_label': old_info.get('payment_label', '') if old_info else '',
            'rejected_reason': '',
            'inbound_id': inbound_ids,
            'inbound_details': client.get('inbound_details', []),
            'created_at': created_at,
            'updated_at': now_tehran_iso(),
            'notes': notes,
            'ip_limit': old_info.get('ip_limit', ip_limit) if old_info else ip_limit,
            'is_active_in_panel': is_active,
            'is_test': is_test,
            'volume_unit': 'GB',
            'category_id': old_info.get('category_id') if old_info else None,
            'category_name': old_info.get('category_name') if old_info else None,
            'category_name_en': old_info.get('category_name_en') if old_info else None,
            'package_id': old_info.get('package_id') if old_info else None,
            'parent_order_id': old_info.get('parent_order_id') if old_info else None,
            'is_extend': old_info.get('is_extend', False) if old_info else False,
        }

    # ─── 8. تشخیص کانفیگ‌های حذف‌شده (فقط این کاربر) ───
    for oid, order in list(orders.items()):
        if not isinstance(order, dict):
            continue
        if order.get('user_id') != user_id:
            continue
        email = order.get('email')
        if order.get('status') in ['approved', 'inactive'] and email and email not in clients_dict:
            orders[str(order['order_id'])]['status'] = 'deleted'
            stats['deleted'] += 1
            logger.info(f"🗑 [sync_user_configs] Order #{order['order_id']} (user {user_id}) → deleted")

    # ─── 9. ذخیره ───
    save_all()
    logger.info(f"✅ [sync_user_configs] user={user_id} stats={stats}")
    return stats

     
@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_new_config'))
async def add_new_config(message: Message):
    
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    if (message.text or "").strip() == "/cancel":
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_cancel_add_config', lang))
        return
    try:
        parts = message.text.split('|')
        if len(parts) == 3:
            vol, days, link = int(parts[0]), int(parts[1]), parts[2].strip()
            if 1 <= vol <= 100 and 30 <= days <= 365:
                cid = add_config_to_pool(vol, days, link)
                await message.reply(t('config_added_gb_days_availab_a6f9984d3c', lang, fa_parts=lambda: (f'{cid}', f'{vol}', f'{days}', f'{get_available_configs_count()}'), en_parts=lambda: (f'{cid}', f'{vol}', f'{days}', f'{get_available_configs_count()}')))
                logger.info(f"New config #{cid} added by admin")
            else:
                await message.reply(t('volume_1_100_or_days_30_365_07dac33c8f', lang))
        else:
            await message.reply(t('invalid_format_format_volume_bc9f694f0a', lang), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error adding new configuration: {e}")
        await message.reply(t('processing_error_67db81edf7', lang))
    user_states.pop(admin_id, None)  
    
@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_manual_balance'))
async def add_balance_manual(message: Message):
    """افزایش/کاهش موجودی دستی - با حفظ کامل کوپن کاربر در دیتابیس"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    if (message.text or "").strip() == "/cancel":
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_cancel_balance_change', lang))
        return
    full_state = user_states.get(admin_id, {})
    
    target_id = full_state.get('manual_balance_target')
    action = full_state.get('balance_action', 'add')
    target_coupon_code = full_state.get('target_coupon_code')
    target_coupon_discount = full_state.get('target_coupon_discount')
    target_coupon_applied = full_state.get('target_coupon_applied', False)
    
    logger.info(f"🔍 [add_balance_manual] starting - target={target_id}, action={action}")
    logger.info(f"🔍 [add_balance_manual] user coupon from admin state: code={target_coupon_code}, applied={target_coupon_applied}")
    
    if not target_id:
        await message.reply("❌ خطا: کاربر هدف یافت نشد")
        user_states.pop(admin_id, None)
        return
    
    target = get_user(target_id)
    target_name_raw = target.get('name', f'کاربر_{target_id}')
    target_name_escaped = html.escape(target_name_raw)
    
    try:
        text = message.text.strip().replace(',', '').replace('،', '').replace(' ', '')
        amount = int(text)
        
        if amount <= 0:
            await message.reply(t('amount_must_be_greater_than_18abd5dfcd', lang))
            return
        
        if action == 'reduce':
            if amount > target.get('balance', 0):
                await message.reply(
                    t('amount_toman_is_more_than_us_61f3bb6249', lang, fa_parts=lambda: (f'{amount:,}', f"{target.get('balance', 0):,}"), en_parts=lambda: (f'{amount:,}', f"{target.get('balance', 0):,}"))
                )
                return
            
            new_balance = reduce_balance(target_id, amount)
            if log_system:
                await log_system.log_balance_change(
                    user_id=target_id,
                    amount=-amount,
                    new_balance=new_balance,
                    action="reduce",
                    admin_id=admin_id
                )
            CustomLogger.log_event('BALANCE_REDUCE', 
                f'Balance decreased for user {target_id}: {amount:,} Toman - new balance: {new_balance:,}', 
                target_id)
            target_lang = get_user(target_id).get('lang', 'fa')
            try:
                coupon_msg = ""
                
                await bot.send_message(target_id,
                    t('amount_toman_deducted_by_adm_0f9c156f0c', target_lang, fa_parts=lambda: (f'{amount:,}', f'{new_balance:,}', f'{coupon_msg}'), en_parts=lambda: (f'{amount:,}', f'{new_balance:,}', f'{coupon_msg}'))
                )
            except Exception as e:
                logger.error(f"Error sending message to user {target_id}: {e}")
            await message.reply(
                t('amount_toman_deducted_from_i_4f23ad9c28', lang, fa_parts=lambda: (f'{amount:,}', f'{target_name_escaped}', f'{target_id}', f"{target.get('balance', 0) + amount:,}", f'{new_balance:,}'), en_parts=lambda: (f'{amount:,}', f'{target_name_escaped}', f'{target_id}', f"{target.get('balance', 0) + amount:,}", f'{new_balance:,}'))
            )
            
            logger.info(f"Admin deducted/added amount {amount} from user account {target_id} deducted")
            
        else:
            new_balance = add_balance(target_id, amount)
            if log_system:
                await log_system.log_balance_change(
                    user_id=target_id,
                    amount=amount,
                    new_balance=new_balance,
                    action="add",
                    admin_id=admin_id
                )
            CustomLogger.log_event('BALANCE_ADD', 
                f'Balance increased for user {target_id}: {amount:,} Toman - new balance: {new_balance:,}', 
                target_id)
            target_lang = get_user(target_id).get('lang', 'fa')
            try:
                coupon_msg = ""
                
                await bot.send_message(target_id,
                    t('amount_toman_added_by_admin_953e396b72', target_lang, fa_parts=lambda: (f'{amount:,}', f'{new_balance:,}', f'{coupon_msg}'), en_parts=lambda: (f'{amount:,}', f'{new_balance:,}', f'{coupon_msg}'))
                )
            except Exception as e:
                logger.error(f"Error sending message to user {target_id}: {e}")
            await message.reply(
                t('amount_toman_added_to_id_new_110c218971', lang, fa_parts=lambda: (f'{amount:,}', f'{target_name_escaped}', f'{target_id}', f'{new_balance:,}'), en_parts=lambda: (f'{amount:,}', f'{target_name_escaped}', f'{target_id}', f'{new_balance:,}'))
            )
            
            logger.info(f"Admin deducted/added amount {amount} to user account {target_id} added")
        if target_coupon_applied and target_coupon_code:
            coupon = COUPONS.get(target_coupon_code)
            if coupon and coupon.get('status') == 'active':
                if target_id not in coupon.get('used_by', []):
                    user_states[target_id] = {
                        'coupon_code': target_coupon_code,
                        'coupon_applied': True,
                        'coupon_discount': target_coupon_discount if target_coupon_discount else 0
                    }
                    save_coupon_to_user_db(target_id)
                    logger.info(f"🏷️ [add_balance_manual] Coupon {target_coupon_code} for user {target_id} saved in the database")
                else:
                    logger.warning(f"⚠️ [add_balance_manual] Coupon {target_coupon_code} already used by user {target_id} has been used")
                    clear_coupon_from_user_db(target_id)
                    if target_id in user_states:
                        user_states[target_id].pop('coupon_code', None)
                        user_states[target_id].pop('coupon_discount', None)
                        user_states[target_id].pop('coupon_applied', None)
            else:
                logger.warning(f"⚠️ [add_balance_manual] Coupon {target_coupon_code} is invalid")
                clear_coupon_from_user_db(target_id)
                if target_id in user_states:
                    user_states[target_id].pop('coupon_code', None)
                    user_states[target_id].pop('coupon_discount', None)
                    user_states[target_id].pop('coupon_applied', None)
        else:
            logger.info(f"ℹ️ [add_balance_manual] User {target_id} has no active coupon")
            clear_coupon_from_user_db(target_id)
        if log_system:
            await log_system.log_admin_action(
                admin_id=admin_id,
                action=f"{'Decrease' if action == 'reduce' else 'Increase'} balance",
                details=f"User: {target_id} - Amount: {amount:,} Toman"
            )
        final_state = user_states.get(target_id, {})
        logger.info(f"🔍 [add_balance_manual] Final status of user {target_id}: {final_state}")
        user_states.pop(admin_id, None)
        
    except ValueError:
        await message.reply(t('please_enter_a_valid_number_81a8ff099c', lang, fa_parts=lambda: (f'{html.escape(message.text)}',), en_parts=lambda: (f'{html.escape(message.text)}',)))
    except Exception as e:
        logger.error(f"Error in add_balance_manual: {e}", exc_info=True)
        
        if log_system:
            await log_system.log_error(e, "add_balance_manual", target_id if 'target_id' in locals() else None)
        CustomLogger.log_event('ERROR', f'Error in add_balance_manual: {e}', admin_id)
        
        await message.reply(f"❌ خطای غیرمنتظره: {html.escape(type(e).__name__)}")
        user_states.pop(admin_id, None)
    

logger = logging.getLogger(__name__)

async def rebuild_sub_links_in_database():
    """
    بازسازی لینک‌های ساب در دیتابیس بر اساس SENAI_SUB_URL جدید از config.py
    
    ویژگی‌ها:
    - فقط لینک‌های معتبر (شروع با http) را بروزرسانی می‌کند
    - لینک‌های نامعتبر (مثل Goz) را دست نمی‌زند
    - با هر دامنه‌ای کار می‌کند (مثل sub.example.com یا vpn.example.net)
    - فرمت لینک را حفظ می‌کند
    - پورت را به درستی مدیریت می‌کند
    
    Returns:
        dict: شامل آمار و لیست سفارشات بروزرسانی شده
    """
    current_sub_base = await ensure_sub_base_url()
    if not current_sub_base:
        logger.error('❌ Subscription URL is not specified (neither in config.py nor in the panel)!')
        return {
            'success': False,
            'error': 'SENAI_SUB_URL not configured',
            'updated_count': 0,
            'updated_orders': []
        }

    logger.info(f"🔄 starting subscription link rebuild with new address: {current_sub_base}")
    
    updated_orders = []
    failed_orders = []
    skipped_orders = []
    invalid_links_skipped = []  # لینک‌های نامعتبری که دست نخوردند
    valid_orders = get_valid_orders()
    
    if not valid_orders:
        logger.info('📭 No orders found in the database')
        return {
            'success': True,
            'updated_count': 0,
            'updated_orders': [],
            'message': 'No orders found'
        }
    
    logger.info(f"📊 total orders: {len(valid_orders)}")
    
    for order_id, order in valid_orders.items():
        try:
            config_link = order.get('config_link')
            sub_link = order.get('sub_link')
            email = order.get('email')
            if not config_link and not sub_link:
                skipped_orders.append({
                    'order_id': order_id,
                    'reason': 'No links found'
                })
                continue
            def is_valid_link(link: str) -> bool:
                """بررسی اینکه لینک معتبر است یا نه"""
                if not link:
                    return False
                if link.startswith('http://') or link.startswith('https://'):
                    return True
                if link.startswith('//'):
                    return True
                if link.startswith('sub.'):
                    return True
                return False
            def rebuild_link(link: str) -> str:
                """بازسازی یک لینک ساب (فقط برای لینک‌های معتبر)"""
                if not link:
                    return None
                if not is_valid_link(link):
                    return None
                base_sub = get_sub_base_url()
                if '/sub/' in link:
                    sub_path = link.split('/sub/')[-1]
                    if sub_path:
                        return f"{base_sub}/{sub_path}"
                if link.startswith('//'):
                    link_with_protocol = f"https:{link}"
                    return rebuild_link(link_with_protocol)
                if link.startswith('sub.'):
                    parts = link.split('/')
                    if len(parts) >= 2:
                        path = '/' + '/'.join(parts[1:])
                        return f"{base_sub}{path}"
                    return f"{base_sub}/{link}"
                try:
                    parsed = urlparse(link)
                    if parsed.scheme and parsed.netloc:
                        parts = parsed.path.rstrip('/').split('/')
                        sub_id = parts[-1] if parts else ''
                        if sub_id:
                            new_link = f"{base_sub}/{sub_id}"
                            query = parsed.query or ''
                            if query:
                                new_link += f"?{query}"
                            return new_link
                except Exception as e:
                    logger.warning(f"⚠️ Error parsing link: {e}")
                if is_valid_link(link):
                    try:
                        parts = link.rstrip('/').split('/')
                        if parts and parts[-1]:
                            return f"{base_sub}/{parts[-1]}"
                    except Exception:
                        return None

                return None
            new_config_link = None
            new_sub_link = None
            if config_link:
                if is_valid_link(config_link):
                    new_config_link = rebuild_link(config_link)
                    if new_config_link:
                        logger.info(f"📝 config_link for order #{order_id} was rebuilt")
                    else:
                        logger.warning(f"⚠️ config_link for order #{order_id} was not rebuilt")
                        failed_orders.append({
                            'order_id': order_id,
                            'old_link': config_link,
                            'reason': 'Rebuild failed for valid link'
                        })
                else:
                    invalid_links_skipped.append({
                        'order_id': order_id,
                        'link': config_link,
                        'reason': 'Invalid link (skipped)'
                    })
                    logger.info(f"⏭️ config_link for order #{order_id} is invalid and was left unchanged")
            if sub_link:
                if is_valid_link(sub_link):
                    new_sub_link = rebuild_link(sub_link)
                    if new_sub_link:
                        logger.info(f"📝 sub_link for order #{order_id} was rebuilt")
                    else:
                        logger.warning(f"⚠️ sub_link for order #{order_id} was not rebuilt")
                        failed_orders.append({
                            'order_id': order_id,
                            'old_link': sub_link,
                            'reason': 'Rebuild failed for valid link'
                        })
                else:
                    invalid_links_skipped.append({
                        'order_id': order_id,
                        'link': sub_link,
                        'reason': 'Invalid link (skipped)'
                    })
                    logger.info(f"⏭️ sub_link for order #{order_id} is invalid and was left unchanged")
            update_data = {}
            if new_config_link and new_config_link != config_link:
                update_data['config_link'] = new_config_link
            
            if new_sub_link and new_sub_link != sub_link:
                update_data['sub_link'] = new_sub_link
            
            if update_data:
                update_data['updated_at'] = now_tehran_iso()
                update_order(order_id, **update_data)
                
                updated_orders.append({
                    'order_id': order_id,
                    'email': email,
                    'old_config_link': config_link,
                    'new_config_link': new_config_link,
                    'old_sub_link': sub_link,
                    'new_sub_link': new_sub_link
                })
                logger.info(f"✅ Order #{order_id} was updated")
            else:
                if config_link and sub_link:
                    skipped_orders.append({
                        'order_id': order_id,
                        'reason': 'No changes needed'
                    })
                else:
                    skipped_orders.append({
                        'order_id': order_id,
                        'reason': 'No valid links to update'
                    })
                
        except Exception as e:
            logger.error(f"❌ Error updating order #{order_id}: {e}")
            failed_orders.append({
                'order_id': order_id,
                'error': str(e)
            })
    result = {
        'success': True,
        'total_orders': len(valid_orders),
        'updated_count': len(updated_orders),
        'failed_count': len(failed_orders),
        'skipped_count': len(skipped_orders),
        'invalid_links_skipped': len(invalid_links_skipped),
        'updated_orders': updated_orders,
        'failed_orders': failed_orders,
        'invalid_links': invalid_links_skipped,
        'new_base_url': get_sub_base_url(),
        'timestamp': now_tehran_iso()
    }

    logger.info("=" * 60)
    logger.info("✅ subscription link rebuild complete!")
    logger.info(f"📊 total orders: {result['total_orders']}")
    logger.info(f"✅ updated: {result['updated_count']}")
    logger.info(f"❌ error: {result['failed_count']}")
    logger.info(f"⏭️ no change: {result['skipped_count']}")
    logger.info(f"⏭️ invalid links untouched: {result['invalid_links_skipped']}")
    logger.info(f"🌐 new address: {get_sub_base_url()}")
    logger.info("=" * 60)
    
    return result


async def rebuild_single_order_sub_link(order_id: int):
    """
    بازسازی لینک ساب برای یک سفارش خاص (فقط لینک‌های معتبر)
    
    Args:
        order_id: شناسه سفارش
        
    Returns:
        dict: نتیجه عملیات
    """
    order = orders.get(str(order_id))
    if not order:
        return {
            'success': False,
            'error': f'Order #{order_id} not found'
        }

    await ensure_sub_base_url()
    config_link = order.get('config_link')
    sub_link = order.get('sub_link')
    def is_valid_link(link: str) -> bool:
        if not link:
            return False
        return (link.startswith('http://') or 
                link.startswith('https://') or 
                link.startswith('//') or 
                link.startswith('sub.'))
    
    if config_link and not is_valid_link(config_link):
        return {
            'success': True,
            'order_id': order_id,
            'message': f'Link is invalid (skipped): {config_link}',
            'config_link': config_link,
            'sub_link': sub_link
        }
    
    if sub_link and not is_valid_link(sub_link):
        return {
            'success': True,
            'order_id': order_id,
            'message': f'Link is invalid (skipped): {sub_link}',
            'config_link': config_link,
            'sub_link': sub_link
        }
    def rebuild_link(link: str) -> str:
        if not link:
            return None

        base_sub = get_sub_base_url()
        if '/sub/' in link:
            sub_path = link.split('/sub/')[-1]
            if sub_path:
                return f"{base_sub}/{sub_path}"

        try:
            parsed = urlparse(link)
            if parsed.scheme and parsed.netloc:
                parts = parsed.path.rstrip('/').split('/')
                sub_id = parts[-1] if parts else ''
                if sub_id:
                    new_link = f"{base_sub}/{sub_id}"
                    query = parsed.query or ''
                    if query:
                        new_link += f"?{query}"
                    return new_link
        except Exception:
            pass

        return None
    
    new_config_link = rebuild_link(config_link) if config_link else None
    new_sub_link = rebuild_link(sub_link) if sub_link else None
    
    update_data = {}
    if new_config_link and new_config_link != config_link:
        update_data['config_link'] = new_config_link
    if new_sub_link and new_sub_link != sub_link:
        update_data['sub_link'] = new_sub_link
    
    if update_data:
        update_data['updated_at'] = now_tehran_iso()
        update_order(order_id, **update_data)
        return {
            'success': True,
            'order_id': order_id,
            'old_config_link': config_link,
            'new_config_link': new_config_link,
            'old_sub_link': sub_link,
            'new_sub_link': new_sub_link
        }
    else:
        return {
            'success': True,
            'order_id': order_id,
            'message': 'No changes needed',
            'config_link': config_link,
            'sub_link': sub_link
        }


@router.message(Command("rebuild_links"), IsAdmin())
async def cmd_rebuild_links(message: Message):
    """دستور بازسازی لینک‌های ساب در دیتابیس (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    status_msg = await message.reply(
        "⏳ در حال بازسازی لینک‌های ساب...\n\n"
        "⏱ این عملیات ممکن است چند ثانیه طول بکشد.\n"
        "⚠️ لینک‌های نامعتبر (مثل Goz) دست نخورده باقی می‌مانند."
    )
    
    try:
        result = await rebuild_sub_links_in_database()
        
        if result['success']:
            report = f"""
✅ <b>بازسازی لینک‌های ساب با موفقیت انجام شد!</b>

━━━━━━━━━━━━━━━━━━━━━━
📊 <b>آمار:</b>
• کل سفارشات: {result['total_orders']}
• ✅ بروزرسانی شده: {result['updated_count']}
• ❌ خطا: {result['failed_count']}
• ⏭️ بدون تغییر: {result['skipped_count']}
• ⏭️ لینک‌های نامعتبر دست نخورده: {result['invalid_links_skipped']}
━━━━━━━━━━━━━━━━━━━━━━
🌐 آدرس جدید: <code>{result['new_base_url']}</code>
🕐 زمان: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}

{f"📋 <b>سفارشات بروزرسانی شده:</b>" if result['updated_orders'] else ""}
"""
            for i, order in enumerate(result['updated_orders'][:10], 1):
                report += f"\n{i}. #{order['order_id']} - {order.get('email', 'بدون ایمیل')}"
                if order.get('old_config_link') != order.get('new_config_link'):
                    old_link = order.get('old_config_link', '')
                    new_link = order.get('new_config_link', '')
                    old_short = old_link[:50] + '...' if len(old_link) > 50 else old_link
                    new_short = new_link[:50] + '...' if len(new_link) > 50 else new_link
                    report += f"\n   📝 config_link: {old_short} → {new_short}"
            
            if len(result['updated_orders']) > 10:
                report += f"\n\n... و {len(result['updated_orders']) - 10} سفارش دیگر"
            
            if result['invalid_links']:
                report += "\n\n⏭️ <b>لینک‌های نامعتبر دست نخورده:</b>"
                for inv in result['invalid_links'][:5]:
                    report += f"\n• #{inv['order_id']}: <code>{inv['link']}</code>"
                if len(result['invalid_links']) > 5:
                    report += f"\n• ... و {len(result['invalid_links']) - 5} مورد دیگر"
            
            if result['failed_orders']:
                report += "\n\n⚠️ <b>خطاها:</b>"
                for fail in result['failed_orders']:
                    report += f"\n• #{fail['order_id']}: {fail.get('reason', 'نامشخص')}"
            
            buttons = [
                [InlineKeyboardButton(
                    text="📋 مشاهده کامل لیست",
                    callback_data="show_rebuild_results"
                )],
                [InlineKeyboardButton(
                    text="🔙 برگشت به پنل",
                    callback_data="admin_panel"
                )]
            ]
            
            await status_msg.edit_text(
                report,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"✅ Links rebuilt by admin {message.from_user.id} completed")
            
        else:
            await status_msg.edit_text(
                f"❌ خطا در بازسازی لینک‌ها:\n{result.get('error', 'خطای نامشخص')}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 برگشت", callback_data="admin_panel")]
                ])
            )
            
    except Exception as e:
        logger.error(f"Error rebuilding links: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ خطا: {html.escape(type(e).__name__)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 برگشت", callback_data="admin_panel")]
            ])
        )


@router.callback_query(F.data == "show_rebuild_results")
@admin_only(answer_on_denied=False)
async def show_rebuild_results(callback: CallbackQuery):
    """نمایش جزئیات کامل بازسازی لینک‌ها"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    result = await rebuild_sub_links_in_database()
    
    report_lines = [
        "📋 گزارش بازسازی لینک‌های ساب",
        "=" * 60,
        f"🕐 زمان: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}",
        f"🌐 آدرس جدید: {get_sub_base_url()}",
        "=" * 60,
        f"📊 کل سفارشات: {result['total_orders']}",
        f"✅ بروزرسانی شده: {result['updated_count']}",
        f"❌ خطا: {result['failed_count']}",
        f"⏭️ بدون تغییر: {result['skipped_count']}",
        f"⏭️ لینک‌های نامعتبر دست نخورده: {result['invalid_links_skipped']}",
        "=" * 60,
        "\n📋 لیست سفارشات بروزرسانی شده:",
        "-" * 40
    ]
    
    for order in result['updated_orders']:
        report_lines.append(f"\n🆔 سفارش #{order['order_id']}")
        report_lines.append(f"   📧 ایمیل: {order.get('email', 'بدون ایمیل')}")
        if order.get('old_config_link') != order.get('new_config_link'):
            report_lines.append(f"   📝 config_link: {order.get('new_config_link', 'ندارد')}")
        if order.get('old_sub_link') != order.get('new_sub_link'):
            report_lines.append(f"   📝 sub_link: {order.get('new_sub_link', 'ندارد')}")
    
    if result['invalid_links']:
        report_lines.append("\n\n⏭️ لینک‌های نامعتبر دست نخورده:")
        report_lines.append("-" * 40)
        for inv in result['invalid_links']:
            report_lines.append(f"   #{inv['order_id']}: {inv['link']}")
    
    if result['failed_orders']:
        report_lines.append("\n\n❌ سفارشات با خطا:")
        report_lines.append("-" * 40)
        for fail in result['failed_orders']:
            report_lines.append(f"   #{fail['order_id']}: {fail.get('reason', 'نامشخص')}")
    
    report_text = "\n".join(report_lines)
    
    file_buffer = BytesIO()
    file_buffer.write(report_text.encode('utf-8'))
    file_buffer.seek(0)
    
    input_file = BufferedInputFile(
        file_buffer.read(), 
        filename=f"rebuild_links_report_{now_tehran().strftime('%Y%m%d_%H%M%S')}.txt"
    )
    
    await callback.message.delete()
    await callback.message.answer_document(
        document=input_file,
        caption=t('i18n_rebuild_results_caption', lang, fa_parts=lambda: (result['updated_count'], result['invalid_links_skipped']), en_parts=lambda: (result['updated_count'], result['invalid_links_skipped'])),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('back_to_panel_63039f103a', lang), callback_data="admin_panel")]
        ])
    )
    
    await safe_answer(callback)


@router.message(Command("rebuild_single"), IsAdmin())
async def cmd_rebuild_single(message: Message):
    """بازسازی لینک یک سفارش خاص (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply(
            "❌ لطفاً آیدی سفارش را وارد کنید:\n"
            "<code>/rebuild_single 14</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    try:
        order_id = int(parts[1])
    except ValueError:
        await message.reply("❌ آیدی سفارش نامعتبر است")
        return
    
    result = await rebuild_single_order_sub_link(order_id)
    
    if result['success']:
        if result.get('message'):
            await message.reply(
                f"ℹ️ {result['message']}\n"
                f"🆔 سفارش: #{order_id}",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.reply(
                f"✅ سفارش #{order_id} با موفقیت بروزرسانی شد!\n"
                f"📝 config_link: {result.get('new_config_link', 'ندارد')}\n"
                f"📝 sub_link: {result.get('new_sub_link', 'ندارد')}",
                parse_mode=ParseMode.HTML
            )
    else:
        await message.reply(f"❌ {result.get('error', 'خطا')}")




def get_backup_list() -> list:
    """دریافت لیست تمام فایل‌های بکاپ موجود"""
    backup_dir = os.path.join(DATA_DIR, 'backups')
    
    logger.info(f"🔍 backup search in: {os.path.abspath(backup_dir)}")
    
    if not os.path.exists(backup_dir):
        logger.warning(f"⚠️ Backup folder does not exist: {backup_dir}")
        os.makedirs(backup_dir, exist_ok=True)
        return []
    
    backups = []
    for f in os.listdir(backup_dir):
        if f.endswith('.json') or f.endswith('.backup'):
            file_path = os.path.join(backup_dir, f)
            logger.info(f"📁 Found: {f}")
            timestamp_str = ""
            if f.startswith('full_backup_'):
                timestamp_str = f.replace('full_backup_', '').replace('.json', '')
            elif f.startswith('before_restore_'):
                timestamp_str = f.replace('before_restore_', '').replace('.json', '')
            else:
                pass
            
            try:
                if timestamp_str:
                    backup_time = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                else:
                    backup_time = datetime.fromtimestamp(os.path.getmtime(file_path))
            except Exception:
                backup_time = datetime.fromtimestamp(os.path.getmtime(file_path))
            
            size = os.path.getsize(file_path)
            backup_type = "unknown"
            if f.startswith('full_backup_'):
                backup_type = "full_backup"
            elif f.startswith('before_restore_'):
                backup_type = "before_restore"
            elif f.endswith('.backup'):
                backup_type = "auto_backup"
            
            backups.append({
                'filename': f,
                'path': file_path,
                'timestamp': timestamp_str,
                'date': backup_time,
                'size': size,
                'size_mb': size / (1024 * 1024),
                'type': backup_type
            })
    backups.sort(key=lambda x: x['date'], reverse=True)
    
    logger.info(f"📊 found backup count: {len(backups)}")
    for b in backups[:5]:
        logger.info(f"  - {b['filename']} ({b['type']}) - {b['date'].strftime('%Y-%m-%d %H:%M:%S')}")
    
    return backups




def get_backup_info(backup_file: str) -> Optional[dict]:
    """دریافت اطلاعات یک فایل بکاپ بدون بارگذاری کامل"""
    try:
        with open(backup_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        backup_info = data.get('backup_info', {})
        stats = backup_info.get('stats', {})
        ready_packages = data.get('ready_packages', {})
        categories_count = len(ready_packages.get('categories', []))
        test_service = data.get('test_service', {})
        test_inbounds = test_service.get('inbound_ids', [])
        
        return {
            'timestamp': backup_info.get('timestamp', 'N/A'),
            'date': backup_info.get('date', 'N/A'),
            'users_count': len(data.get('users', {})),
            'orders_count': len(data.get('orders', {})),
            'configs_count': len(data.get('configs', {}).get('configs', [])),
            'blacklist_count': len(data.get('blacklist', {}).get('users', [])),
            'total_revenue': stats.get('total_revenue', 0),
            'packages_count': categories_count,
            'test_inbounds': test_inbounds,
            'version': backup_info.get('version', '1.0')
        }
    except Exception as e:
        logger.error(f"Error reading backup information {backup_file}: {e}")
        return None


async def restore_from_backup(backup_file: str, restore_panel: bool = False) -> dict:
    """بازگردانی کامل از فایل بکاپ با پشتیبانی از IP Limit"""
    result = {
        'success': False,
        'restored_users': 0,
        'restored_orders': 0,
        'restored_configs': 0,
        'restored_packages': 0,
        'restored_test_settings': False,
        'errors': []
    }
    
    logger.info("=" * 60)
    logger.info('🔄 starting backup restore process')
    logger.info(f"📁 backup file: {backup_file}")
    
    try:
        logger.info('📂 Loading backup file...')
        data = load_json(backup_file, use_cache=False)
        
        if not data:
            result['errors'].append("فایل بکاپ نامعتبر است یا خالی می‌باشد")
            logger.error('❌ Invalid backup file')
            return result
        
        logger.info('📊 Backup file contents:')
        logger.info(f"  - users: {len(data.get('users', {}))} user")
        logger.info(f"  - orders: {len(data.get('orders', {}))} orders")
        logger.info(f"  - referrals: {len(data.get('referrals', {}))} referrals")
        logger.info(f"  - configs: {len(data.get('configs', {}).get('configs', []))} configs")
        logger.info(f"  - ready_packages: {len(data.get('ready_packages', {}).get('categories', []))} category")
        logger.info(f"  - test_service: {data.get('test_service', {}).get('inbound_ids', [])}")
        logger.info('💾 Backing up the current state before restore...')
        current_backup = os.path.join(DATA_DIR, 'backups', f'before_restore_{now_tehran().strftime("%Y%m%d_%H%M%S")}.json')
        daily_usage_before = {}
        try:
            daily_usage_before = usage_store.export_backup_data()
        except Exception:
            pass

        full_backup = {
            'users': users,
            'orders': orders,
            'referrals': referrals,
            'configs': configs_pool,
            'feedback': feedbacks,
            'chats': chats,
            'blacklist': {'users': list(BLACKLIST)},
            'ready_packages': READY_PACKAGES,
            'test_service': TEST_SERVICE_STATUS,
            'user_inbound_selection': USER_INBOUND_SELECTION,
            'user_test_usage': USER_TEST_USAGE,
            'shop_status': SHOP_STATUS,
            'daily_usage': daily_usage_before,
            'backup_info': {
                'timestamp': now_tehran().strftime('%Y%m%d_%H%M%S'),
                'date': now_tehran_iso(),
                'reason': 'before_restore'
            }
        }
        
        if save_json(current_backup, full_backup):
            logger.info(f"✅ Backup of current state saved: {current_backup}")
        else:
            logger.warning("⚠️ Error saving backup of current state")
        logger.info('👥 Restoring users...')
        backup_users = data.get('users', {})
        result['restored_users'] = len(backup_users)
        users.clear()
        users.update(backup_users)
        logger.info(f"✅ {result['restored_users']} user restored")
        logger.info('📋 Restoring orders...')
        backup_orders = data.get('orders', {})
        for oid, order_data in backup_orders.items():
            if isinstance(order_data, dict):
                if 'ip_limit' not in order_data:
                    order_data['ip_limit'] = 0
                    logger.info(f"📝 Added ip_limit field with value 0 to order {oid} added")
        
        result['restored_orders'] = len(backup_orders)
        orders.clear()
        orders.update(backup_orders)
        logger.info(f"✅ {result['restored_orders']} order restored")
        logger.info('🎁 Restoring referrals...')
        backup_referrals = data.get('referrals', {})
        referrals.clear()
        referrals.update(backup_referrals)
        logger.info(f"✅ {len(backup_referrals)} referral restored")
        logger.info('📦 Restoring configs and settings...')
        backup_configs = data.get('configs', {})
        result['restored_configs'] = len(backup_configs.get('configs', []))
        
        configs_pool.clear()
        configs_pool.update(backup_configs)
        logger.info(f"✅ {result['restored_configs']} config restored")
        logger.info('📦 Restoring ready-made packages...')
        backup_ready = data.get('ready_packages', {})
        if backup_ready and backup_ready.get('categories'):
            READY_PACKAGES.clear()
            READY_PACKAGES.update(backup_ready)
            result['restored_packages'] = len(READY_PACKAGES.get('categories', []))
            logger.info(f"✅ {result['restored_packages']} ready-package category restored")
            
            for cat in READY_PACKAGES.get('categories', []):
                inbound_ids = cat.get('inbound_ids', [])
                logger.info(f"  📡 {cat.get('name')}: inbounds = {inbound_ids if inbound_ids else 'default'}")
        else:
            logger.warning('⚠️ No ready packages found in the backup')
        logger.info('🧪 Restoring test settings...')
        backup_test = data.get('test_service', {})
        if backup_test:
            TEST_SERVICE_STATUS.clear()
            TEST_SERVICE_STATUS.update(backup_test)
            result['restored_test_settings'] = True
            logger.info(f"✅ Test settings restored: inbounds = {TEST_SERVICE_STATUS.get('inbound_ids', [])}")
        else:
            logger.warning('⚠️ Test settings not found in the backup')
        logger.info("📡 Restoring users' inbound selections...")
        backup_inbound_selection = data.get('user_inbound_selection', {})
        if backup_inbound_selection:
            USER_INBOUND_SELECTION.clear()
            USER_INBOUND_SELECTION.update(backup_inbound_selection)
            logger.info(f"✅ Inbound selections {len(USER_INBOUND_SELECTION)} user restored")
        logger.info('🧪 Restoring user tests...')
        backup_test_usage = data.get('user_test_usage', {})
        if backup_test_usage:
            USER_TEST_USAGE.clear()
            USER_TEST_USAGE.update(backup_test_usage)
            logger.info(f"✅ Test {len(USER_TEST_USAGE)} user restored")
        logger.info('🛒 Restoring sales status...')
        backup_shop = data.get('shop_status', {})
        if backup_shop:
            SHOP_STATUS.clear()
            SHOP_STATUS.update(backup_shop)
            logger.info(f"✅ Sales status restored: {'open' if SHOP_STATUS.get('open') else 'closed'}")
        logger.info('📝 Restoring feedback...')
        backup_feedbacks = data.get('feedback', {})
        feedbacks.clear()
        feedbacks.update(backup_feedbacks)
        logger.info(f"✅ {len(backup_feedbacks)} feedback restored")
        logger.info('💬 Restoring chats...')
        backup_chats = data.get('chats', {})
        chats.clear()
        chats.update(backup_chats)
        logger.info(f"✅ {len(backup_chats)} chat restored")
        logger.info('🚫 Restoring blacklist...')
        backup_blacklist = data.get('blacklist', {})
        BLACKLIST.clear()
        BLACKLIST.update(set(backup_blacklist.get('users', [])))
        logger.info(f"✅ {len(BLACKLIST)} user restored to the blacklist")
        
        logger.info('📊 Restoring daily usage statistics...')
        backup_daily_usage = data.get('daily_usage', {})
        if backup_daily_usage:
            try:
                usage_store.import_backup_data(backup_daily_usage)
                logger.info('✅ Daily usage statistics successfully restored from backup file')
            except Exception as ex_du:
                logger.error(f"❌ Error restoring daily usage statistics: {ex_du}")
        
        logger.info('💾 Final database save...')
        
        configs_pool['ready_packages'] = READY_PACKAGES
        configs_pool['test_service'] = TEST_SERVICE_STATUS
        configs_pool['shop_status'] = SHOP_STATUS
        
        save_all()
        logger.info('✅ Database saved')
        logger.info('🔍 Final verification:')
        logger.info(f"  - Ready-made packages: {len(READY_PACKAGES.get('categories', []))} category")
        for cat in READY_PACKAGES.get('categories', []):
            inbound_ids = cat.get('inbound_ids', [])
            logger.info(f"    📡 {cat.get('name')}: inbounds = {inbound_ids if inbound_ids else 'default'}")
        logger.info(f"  - Test settings: inbounds = {TEST_SERVICE_STATUS.get('inbound_ids', [])}")
        
        result['success'] = True
        logger.info("=" * 60)
        logger.info("✅ Backup restored successfully!")
        logger.info(f"  📊 Users: {result['restored_users']}")
        logger.info(f"  📋 Orders: {result['restored_orders']}")
        logger.info(f"  📦 Configs: {result['restored_configs']}")
        logger.info(f"  📦 Ready-made packages: {result['restored_packages']}")
        logger.info(f"  🧪 Test settings: {'restored' if result['restored_test_settings'] else 'not found'}")
        logger.info("=" * 60)
        
        result['warning'] = "⚠️ فقط دیتابیس ربات بازگردانی شد. کانفیگ‌های پنل به قوت خود باقی هستند."
        
        return result
        
    except FileNotFoundError as e:
        logger.error(f"❌ Backup file not found: {e}")
        result['errors'].append(f"فایل بکاپ یافت نشد: {str(e)}")
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ Error decoding JSON: {e}")
        result['errors'].append(f"فایل بکاپ خراب است: {str(e)}")
        return result
        
    except Exception as e:
        logger.error(f"❌ Error restoring backup: {e}", exc_info=True)
        result['errors'].append(str(e))
        return result
    
    
@router.message(Command("check_backup"), IsAdmin())
async def cmd_check_backup(message: Message):
    """بررسی محتویات آخرین بکاپ (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    backup_dir = os.path.join(DATA_DIR, 'backups')
    backups = sorted(glob.glob(os.path.join(backup_dir, 'full_backup_*.json')), reverse=True)
    
    if not backups:
        await message.reply("❌ هیچ بکاپی یافت نشد!")
        return
    
    latest = backups[0]
    
    with open(latest, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    force_settings = data.get('configs', {}).get('force_join_settings', {})
    channels = force_settings.get('channels', [])
    
    text = f"""
📁 <b>آخرین بکاپ:</b> <code>{os.path.basename(latest)}</code>
📅 <b>تاریخ:</b> {datetime.fromtimestamp(os.path.getmtime(latest)).strftime('%Y-%m-%d %H:%M:%S')}
💾 <b>حجم:</b> {os.path.getsize(latest) / 1024:.1f} KB

📊 <b>محتوای بکاپ:</b>
• 👥 کاربران: {len(data.get('users', {}))}
• 📋 سفارشات: {len(data.get('orders', {}))}
• 📦 کانفیگ‌ها: {len(data.get('configs', {}).get('configs', []))}

🔒 <b>عضویت اجباری:</b>
• وضعیت: {'🟢 فعال' if force_settings.get('enabled') else '🔴 غیرفعال'}
• تعداد کانال‌ها: {len(channels)}

<b>کانال‌ها:</b>
"""
    if channels:
        for ch in channels:
            text += f"• {ch.get('name', 'نامشخص')} - <code>{ch.get('id')}</code>\n"
    else:
        text += "• ❌ هیچ کانالی ذخیره نشده است!\n"
    
    await message.reply(text, parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "admin_restore_backup")
@admin_only
async def admin_restore_backup_menu(callback: CallbackQuery):
    """نمایش منوی ریستور بکاپ با لیست بکاپ‌های موجود"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    backups = get_backup_list()
    
    if not backups:
        text = t('b_no_backups_found_b_use_the_49eac74d05', lang)
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
            ])
        )
        await safe_answer(callback)
        return
    text = t('b_restore_from_backup_b_back_1e0a3124ce', lang, fa_parts=lambda: (f'{len(backups)}',), en_parts=lambda: (f'{len(backups)}',))
    text += t('please_select_a_backup_9a9b5092f8', lang)
    text += t('b_note_b_this_will_replace_c_5ba0eac4ff', lang)
    
    buttons = []
    for backup in backups[:10]:
        date_str = backup['date'].strftime('%Y-%m-%d %H:%M')
        size_str = format_size(backup['size'])
        
        type_icon = {
            'full_backup': '📦',
            'before_restore': '🔄',
            'auto_backup': '🤖',
            'unknown': '📄'
        }.get(backup.get('type', 'unknown'), '📄')
        
        label = f"{type_icon} {date_str} - {size_str}"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"restore_backup_{backup['filename']}"
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_panel"
    )])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data.startswith("restore_backup_"))
@admin_only
async def admin_restore_backup_confirm(callback: CallbackQuery):
    """نمایش اطلاعات بکاپ و تأیید ریستور"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    filename = callback.data.replace("restore_backup_", "")
    backups = get_backup_list()
    backup = None
    for b in backups:
        if b['filename'] == filename:
            backup = b
            break
    
    if not backup:
        await callback.answer(t('backup_not_found_05b76432fc', lang), show_alert=True)
        return
    info = get_backup_info(backup['path'])
    text = t('b_confirm_restore_backup_b_b_4ef7d37caf', lang, fa_parts=lambda: (f"{backup['filename']}", f"{backup['date'].strftime('%Y-%m-%d %H:%M:%S')}", f"{format_size(backup['size'])}", f"{(info.get('version', '1.0') if info else 'نامشخص')}", f"{(info['users_count'] if info else 'نامشخص')}", f"{(info['orders_count'] if info else 'نامشخص')}", f"{(info['configs_count'] if info else 'نامشخص')}", f"{(info['blacklist_count'] if info else 'نامشخص')}", f"{(info['packages_count'] if info else 'نامشخص')}", f"{(info['test_inbounds'] if info else 'نامشخص')}"), en_parts=lambda: (f"{backup['filename']}", f"{backup['date'].strftime('%Y-%m-%d %H:%M:%S')}", f"{format_size(backup['size'])}", f"{(info.get('version', '1.0') if info else 'Unknown')}", f"{(info['users_count'] if info else 'Unknown')}", f"{(info['orders_count'] if info else 'Unknown')}", f"{(info['configs_count'] if info else 'Unknown')}", f"{(info['blacklist_count'] if info else 'Unknown')}", f"{(info['packages_count'] if info else 'Unknown')}", f"{(info['test_inbounds'] if info else 'Unknown')}"))
    buttons = [
        [
            InlineKeyboardButton(
                text=t('yes_restore_e6002a5d56', lang),
                callback_data=f"confirm_restore_{backup['filename']}",
                style="danger"
            ),
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data="admin_restore_backup"
            )
        ],
        [
            InlineKeyboardButton(
                text=t('view_full_details_556b9610f3', lang),
                callback_data=f"restore_details_{backup['filename']}",
                style="primary"
            )
        ]
    ]
    
    await callback.message.edit_text(
        text, 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)

@router.callback_query(F.data.startswith("restore_details_"))
@admin_only
async def restore_details(callback: CallbackQuery):
    """نمایش جزئیات کامل بکاپ"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    filename = callback.data.replace("restore_details_", "")
    backups = get_backup_list()
    backup = None
    for b in backups:
        if b['filename'] == filename:
            backup = b
            break
    
    if not backup:
        await callback.answer(t('backup_not_found_05b76432fc', lang), show_alert=True)
        return
    
    try:
        with open(backup['path'], 'r', encoding='utf-8') as f:
            data = json.load(f)
        ready_packages = data.get('ready_packages', {})
        test_service = data.get('test_service', {})
        user_inbound_selection = data.get('user_inbound_selection', {})
        user_test_usage = data.get('user_test_usage', {})
        shop_status = data.get('shop_status', {})
        
        parts = (f"{backup['filename']}", f"{backup['date'].strftime('%Y-%m-%d %H:%M:%S')}", f"{len(data.get('users', {}))}", f"{len(data.get('orders', {}))}", f"{len(data.get('referrals', {}))}", f"{len(data.get('configs', {}).get('configs', []))}", f"{len(data.get('blacklist', {}).get('users', []))}")
        text = t('b_full_backup_details_b_b_fi_6f509ab102', lang, fa_parts=lambda: parts, en_parts=lambda: parts)
        for cat in ready_packages.get('categories', []):
            inbound_ids = cat.get('inbound_ids', [])
            cat_name = cat.get('name', '') if lang == 'fa' else cat.get('name_en', cat.get('name'))
            text += f"  • {cat.get('icon', '📦')} {cat_name}: "
            text += t('inbounds_96c3218ab4', lang, fa_parts=lambda: (f"{(inbound_ids if inbound_ids else t('i18n_backup_default', lang))}",), en_parts=lambda: (f"{(inbound_ids if inbound_ids else t('i18n_backup_default', lang))}",))
            text += t('packages_608c71b148', lang, fa_parts=lambda: (f"{len(cat.get('packages', []))}",), en_parts=lambda: (f"{len(cat.get('packages', []))}",))

        test_parts = (f"{(t('i18n_backup_active', lang) if test_service.get('enabled') else t('i18n_backup_inactive', lang))}", f"{test_service.get('volume', 5)}", f"{test_service.get('days', 3)}", f"{test_service.get('inbound_ids', [])}", f'{len(user_inbound_selection)}', f'{len(user_test_usage)}', f"{(t('i18n_backup_open', lang) if shop_status.get('open') else t('i18n_backup_closed', lang))}", f"{shop_status.get('message', t('i18n_backup_none', lang))}", f"{len(data.get('chats', {}))}", f"{len(data.get('feedback', {}))}")
        text += t('b_test_settings_b_status_vol_1dd36faea6', lang, fa_parts=lambda: test_parts, en_parts=lambda: test_parts)
        
        buttons = [
            [InlineKeyboardButton(
                text=t('back_460da353ef', lang),
                callback_data=f"restore_backup_{backup['filename']}"
            )],
            [InlineKeyboardButton(
                text=t('restore_backup_b22e5e2b4f', lang),
                callback_data=f"confirm_restore_{backup['filename']}",
                style="success"
            )]
        ]
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Error displaying backup details: {e}")
        await callback.answer(t('error_showing_details_7b929c0cb5', lang), show_alert=True)
    
    await safe_answer(callback)
        

@router.callback_query(F.data.startswith("confirm_restore_"))
@admin_only
async def confirm_restore(callback: CallbackQuery):
    """تأیید و اجرای ریستور بکاپ"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    filename = callback.data.replace("confirm_restore_", "")
    backups = get_backup_list()
    backup = None
    for b in backups:
        if b['filename'] == filename:
            backup = b
            break
    
    if not backup:
        await callback.answer(t('backup_not_found_05b76432fc', lang), show_alert=True)
        return
    await callback.message.edit_text(
        t('i18n_restoring_backup_wait', lang),
        reply_markup=None
    )
    result = await restore_from_backup(backup['path'], restore_panel=False)

    if result['success']:
        test_settings_label = t('i18n_backup_settings_restored', lang) if result['restored_test_settings'] else t('i18n_backup_settings_not_found', lang)
        text = t('b_backup_restored_successful_783253bf90', lang, fa_parts=lambda: (f"{result['restored_users']}", f"{result['restored_orders']}", f"{result['restored_configs']}", f"{result['restored_packages']}", f"{test_settings_label}", f"{result.get('warning', '')}"), en_parts=lambda: (f"{result['restored_users']}", f"{result['restored_orders']}", f"{result['restored_configs']}", f"{result['restored_packages']}", f"{test_settings_label}", f"{result.get('warning', '')}"))
        
        buttons = [
            [InlineKeyboardButton(
                text=t('back_to_admin_panel_676a1cf43f', lang),
                callback_data="admin_panel",
                style="primary"
            )],
            [InlineKeyboardButton(
                text=t('view_orders_bdec673bda', lang),
                callback_data="admin_orders"
            )],
            [InlineKeyboardButton(
                text=t('check_ready_packages_14155c334f', lang),
                callback_data="admin_ready_packages"
            )]
        ]
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
        
    else:
        text = t('b_error_restoring_backup_b_e3279b3674', lang)
        for err in result['errors']:
            text += f"• {err}\n"
        text += t('please_check_the_logs_b79c331f79', lang)
        
        buttons = [
            [InlineKeyboardButton(
                text=t('back_14968ad63f', lang),
                callback_data="admin_restore_backup"
            )]
        ]
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
    
    await safe_answer(callback)

@router.callback_query(F.data == "admin_manage_backups")
@admin_only
async def admin_manage_backups(callback: CallbackQuery):
    """مدیریت بکاپ‌ها (حذف بکاپ‌های قدیمی و پاکسازی کامل)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    backups = get_backup_list()
    full_backups = [b for b in backups if b.get('type') == 'full_backup']
    before_restore = [b for b in backups if b.get('type') == 'before_restore']
    auto_backups = [b for b in backups if b.get('type') == 'auto_backup']
    
    total_size = sum(b['size'] for b in backups)
    total_size_str = format_size(total_size)
    
    text = t('b_backup_manager_b_97db6a0dd5', lang)
    text += t('b_backup_statistics_b_8ff1e435b6', lang)
    text += t('full_backups_af04569bd7', lang, fa_parts=lambda: (f'{len(full_backups)}',), en_parts=lambda: (f'{len(full_backups)}',))
    text += t('before_restore_backups_8fa581c1ff', lang, fa_parts=lambda: (f'{len(before_restore)}',), en_parts=lambda: (f'{len(before_restore)}',))
    text += t('auto_backups_09978f1ce0', lang, fa_parts=lambda: (f'{len(auto_backups)}',), en_parts=lambda: (f'{len(auto_backups)}',))
    text += t('total_size_a2498f0931', lang, fa_parts=lambda: (f'{total_size_str}',), en_parts=lambda: (f'{total_size_str}',))

    if backups:
        text += t('b_recent_backups_last_10_b_c34f4b5240', lang)
        for backup in backups[:10]:
            date_str = backup['date'].strftime('%Y-%m-%d %H:%M')
            size_str = format_size(backup['size'])
            type_icon = {
                'full_backup': '📦',
                'before_restore': '🔄',
                'auto_backup': '🤖'
            }.get(backup.get('type'), '📄')
            text += f"{type_icon} {date_str} - {size_str} - {backup['filename']}\n"
        if len(backups) > 10:
            text += t('and_more_887de27f47', lang, fa_parts=lambda: (f'{len(backups) - 10}',), en_parts=lambda: (f'{len(backups) - 10}',))
    else:
        text += t('b_no_backups_found_b_41d9548cce', lang)
        text += t('tips_0ffc51bcc6', lang)
        text += t('use_the_backup_button_to_cre_806fc71112', lang)

    text += t('select_an_operation_c1a5464279', lang)

    buttons = [
        [InlineKeyboardButton(text="⚙️ تنظیمات بکاپ و آپدیت خودکار", callback_data="admin_auto_backup_settings")],
        [InlineKeyboardButton(text=t('delete_all_backups_2d37586fa6', lang), callback_data="delete_all_backups_confirm", style="danger")],
        [InlineKeyboardButton(text=t('delete_old_before_restore_7_fec346871f', lang), callback_data="delete_old_before_restore")],
        [InlineKeyboardButton(text=t('delete_old_backups_30_days_17f6abe3a9', lang), callback_data="delete_old_backups")],
        [InlineKeyboardButton(text=t('list_all_backups_8e68df44ee', lang), callback_data="list_all_backups")],
        [InlineKeyboardButton(text=t('back_to_panel_63039f103a', lang), callback_data="admin_panel")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data == "admin_auto_backup_settings")
@admin_only
async def admin_auto_backup_settings(callback: CallbackQuery):
    """منوی تنظیمات بکاپ و همگام‌سازی خودکار دیتابیس و پنل"""
    settings = configs_pool.setdefault('auto_backup_settings', {
        'backup_enabled': True,
        'backup_interval_hours': 6,
        'last_backup_time': None,
        'sync_enabled': True,
        'sync_interval_hours': 6,
        'last_sync_time': None,
    })

    backup_enabled = settings.get('backup_enabled', True)
    backup_int = settings.get('backup_interval_hours', 6)
    last_bk = settings.get('last_backup_time', 'هنوز اجرا نشده')
    if last_bk and last_bk != 'هنوز اجرا نشده':
        try:
            last_bk = last_bk[:19].replace('T', ' ')
        except Exception:
            pass

    sync_enabled = settings.get('sync_enabled', True)
    sync_int = settings.get('sync_interval_hours', 6)
    last_sy = settings.get('last_sync_time', 'هنوز اجرا نشده')
    if last_sy and last_sy != 'هنوز اجرا نشده':
        try:
            last_sy = last_sy[:19].replace('T', ' ')
        except Exception:
            pass

    text = f"""⚙️ <b>تنظیمات بکاپ و آپدیت خودکار</b>
──────────────────────
💾 <b>بکاپ خودکار دیتابیس:</b>
• وضعیت: {'🟢 روشن (فعال)' if backup_enabled else '🔴 خاموش (غیرفعال)'}
• بازه زمانی زمان‌بندی: <b>هر {backup_int} ساعت</b>
• آخرین بکاپ خودکار: <code>{last_bk}</code>

🔄 <b>آپدیت خودکار کانفیگ‌ها از پنل:</b>
• وضعیت: {'🟢 روشن (فعال)' if sync_enabled else '🔴 خاموش (غیرفعال)'}
• بازه زمانی زمان‌بندی: <b>هر {sync_int} ساعت</b>
• آخرین همگام‌سازی: <code>{last_sy}</code>
──────────────────────
💡 <i>برای روشن/خاموش کردن یا تغییر ساعت هر بخش روی دکمه‌های زیر کلیک کنید:</i>"""

    buttons = [
        [
            InlineKeyboardButton(
                text=f"💾 بکاپ خودکار: {'🟢 روشن' if backup_enabled else '🔴 خاموش'}",
                callback_data="toggle_auto_backup"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'🔘 ' if backup_int == 3 else ''}۳ ساعته",
                callback_data="set_auto_backup_int_3"
            ),
            InlineKeyboardButton(
                text=f"{'🔘 ' if backup_int == 6 else ''}۶ ساعته",
                callback_data="set_auto_backup_int_6"
            ),
            InlineKeyboardButton(
                text=f"{'🔘 ' if backup_int == 12 else ''}۱۲ ساعته",
                callback_data="set_auto_backup_int_12"
            ),
            InlineKeyboardButton(
                text=f"{'🔘 ' if backup_int == 24 else ''}۲۴ ساعته",
                callback_data="set_auto_backup_int_24"
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"🔄 آپدیت خودکار پنل: {'🟢 روشن' if sync_enabled else '🔴 خاموش'}",
                callback_data="toggle_auto_sync"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'🔘 ' if sync_int == 1 else ''}۱ ساعته",
                callback_data="set_auto_sync_int_1"
            ),
            InlineKeyboardButton(
                text=f"{'🔘 ' if sync_int == 3 else ''}۳ ساعته",
                callback_data="set_auto_sync_int_3"
            ),
            InlineKeyboardButton(
                text=f"{'🔘 ' if sync_int == 6 else ''}۶ ساعته",
                callback_data="set_auto_sync_int_6"
            ),
            InlineKeyboardButton(
                text=f"{'🔘 ' if sync_int == 12 else ''}۱۲ ساعته",
                callback_data="set_auto_sync_int_12"
            ),
        ],
        [
            InlineKeyboardButton(text="⚡ تهیه بکاپ همین الان", callback_data="run_auto_backup_now"),
            InlineKeyboardButton(text="⚡ همگام‌سازی همین الان", callback_data="run_auto_sync_now"),
        ],
        [
            InlineKeyboardButton(text="🔙 بازگشت به مدیریت بکاپ‌ها", callback_data="admin_manage_backups")
        ]
    ]

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data == "toggle_auto_backup")
@admin_only
async def toggle_auto_backup(callback: CallbackQuery):
    settings = configs_pool.setdefault('auto_backup_settings', {})
    cur = settings.get('backup_enabled', True)
    settings['backup_enabled'] = not cur
    save_all()
    status_str = "روشن شد 🟢" if not cur else "خاموش شد 🔴"
    await safe_answer(callback, f"بکاپ خودکار {status_str}", alert=True)
    await admin_auto_backup_settings(callback)


@router.callback_query(F.data.startswith("set_auto_backup_int_"))
@admin_only
async def set_auto_backup_int(callback: CallbackQuery):
    hours = int(callback.data.split("_")[-1])
    settings = configs_pool.setdefault('auto_backup_settings', {})
    settings['backup_interval_hours'] = hours
    save_all()
    await safe_answer(callback, f"بازه بکاپ خودکار به {hours} ساعت تغییر یافت ✅", alert=True)
    await admin_auto_backup_settings(callback)


@router.callback_query(F.data == "toggle_auto_sync")
@admin_only
async def toggle_auto_sync(callback: CallbackQuery):
    settings = configs_pool.setdefault('auto_backup_settings', {})
    cur = settings.get('sync_enabled', True)
    settings['sync_enabled'] = not cur
    save_all()
    status_str = "روشن شد 🟢" if not cur else "خاموش شد 🔴"
    await safe_answer(callback, f"آپدیت خودکار پنل {status_str}", alert=True)
    await admin_auto_backup_settings(callback)


@router.callback_query(F.data.startswith("set_auto_sync_int_"))
@admin_only
async def set_auto_sync_int(callback: CallbackQuery):
    hours = int(callback.data.split("_")[-1])
    settings = configs_pool.setdefault('auto_backup_settings', {})
    settings['sync_interval_hours'] = hours
    save_all()
    await safe_answer(callback, f"بازه آپدیت پنل به {hours} ساعت تغییر یافت ✅", alert=True)
    await admin_auto_backup_settings(callback)


@router.callback_query(F.data == "run_auto_backup_now")
@admin_only
async def run_auto_backup_now(callback: CallbackQuery):
    await callback.answer("⏳ در حال تهیه بکاپ خودکار...", show_alert=False)
    try:
        from main import create_auto_backup
        success = create_auto_backup()
        if success:
            settings = configs_pool.setdefault('auto_backup_settings', {})
            settings['last_backup_time'] = datetime.now().isoformat()
            save_all()
            await safe_answer(callback, "✅ بکاپ خودکار با موفقیت تهیه شد!", alert=True)
        else:
            await safe_answer(callback, "❌ خطا در ذخیره بکاپ!", alert=True)
    except Exception as e:
        await safe_answer(callback, f"❌ خطا: {e}", alert=True)
    await admin_auto_backup_settings(callback)


@router.callback_query(F.data == "run_auto_sync_now")
@admin_only
async def run_auto_sync_now(callback: CallbackQuery):
    await callback.answer("⏳ در حال همگام‌سازی با پنل...", show_alert=False)
    try:
        from routers.admin_tools import sync_deleted_configs
        res = await sync_deleted_configs(batch_size=20)
        settings = configs_pool.setdefault('auto_backup_settings', {})
        settings['last_sync_time'] = datetime.now().isoformat()
        save_all()
        del_count = res.get('deleted', 0) if isinstance(res, dict) else (res if isinstance(res, int) else 0)
        await safe_answer(callback, f"✅ همگام‌سازی پنل انجام شد ({del_count} کانفیگ بررسی/حذف شد)", alert=True)
    except Exception as e:
        await safe_answer(callback, f"❌ خطا در همگام‌سازی: {e}", alert=True)
    await admin_auto_backup_settings(callback)


@router.callback_query(F.data == "list_all_backups")
@admin_only
async def admin_list_all_backups(callback: CallbackQuery):
    """نمایش لیست کامل همه بکاپ‌ها با امکان حذف تکی"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    backups = get_backup_list()
    
    if not backups:
        await callback.answer(t('no_backups_ccaa6d3538', lang), show_alert=True)
        return
    
    text = t('b_all_backups_list_b_count_d206148090', lang, fa_parts=lambda: (f'{len(backups)}',), en_parts=lambda: (f'{len(backups)}',))
    text += t('click_on_a_backup_to_delete_45ee565939', lang)
    
    buttons = []
    for backup in backups:
        date_str = backup['date'].strftime('%Y-%m-%d %H:%M:%S')
        size_str = format_size(backup['size'])
        type_icon = {
            'full_backup': '📦',
            'before_restore': '🔄',
            'auto_backup': '🤖'
        }.get(backup.get('type'), '📄')
        
        buttons.append([InlineKeyboardButton(
            text=f"❌ {type_icon} {date_str} - {size_str}",
            callback_data=f"delete_single_backup_{backup['timestamp']}"
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('delete_all_backups_2d37586fa6', lang),
        callback_data="delete_all_backups_confirm",
        style="danger"
    )])
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_manage_backups"
    )])
    if len(buttons) > 15:
        buttons = buttons[:20]
        text += t('only_last_20_backups_are_sho_f215d64282', lang)
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data == "delete_all_backups_confirm")
@admin_only
async def admin_delete_all_backups_confirm(callback: CallbackQuery):
    """تأیید حذف همه بکاپ‌ها"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    backups = get_backup_list()
    total_size_str = format_size(sum(b['size'] for b in backups))
    
    text = t('b_warning_delete_all_backups_17fa76f2a2', lang, fa_parts=lambda: (f'{len(backups)}', f'{total_size_str}'), en_parts=lambda: (f'{len(backups)}', f'{total_size_str}'))
    buttons = [
        [
            InlineKeyboardButton(text=t('yes_delete_all_b5b9a2f4c7', lang), callback_data="delete_all_backups_execute", style="danger"),
            InlineKeyboardButton(text=t('cancel_4197bafba5', lang), callback_data="admin_manage_backups")
        ]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data == "delete_all_backups_execute")
@admin_only
async def admin_delete_all_backups_execute(callback: CallbackQuery):
    """اجرای حذف همه بکاپ‌ها"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    backups = get_backup_list()
    
    await callback.message.edit_text(t('deleting_all_backups_7648a078ed', lang))
    
    deleted_count = 0
    failed_count = 0
    total_freed_size = 0
    
    for backup in backups:
        try:
            size = backup['size']
            os.remove(backup['path'])
            deleted_count += 1
            total_freed_size += size
            logger.info(f"🗑 Backup deleted: {backup['filename']}")
        except Exception as e:
            failed_count += 1
            logger.error(f"❌ Error deleting backup {backup['filename']}: {e}")
    
    total_freed_str = format_size(total_freed_size)
    if log_system:
        await log_system.log_admin_action(
            callback.from_user.id,
            "Deleted all backups",
            details=f"Deleted: {deleted_count} | Freed space: {total_freed_str}"
        )
    
    text = t('b_backup_deletion_completed_82e2f36ddc', lang, fa_parts=lambda: (f'{deleted_count}', f'{failed_count}', f'{total_freed_str}'), en_parts=lambda: (f'{deleted_count}', f'{failed_count}', f'{total_freed_str}'))
    
    buttons = [[InlineKeyboardButton(
        text=t('back_to_panel_63039f103a', lang),
        callback_data="admin_panel"
    )]]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data.startswith("delete_single_backup_"))
@admin_only
async def admin_delete_single_backup(callback: CallbackQuery):
    """حذف یک بکاپ خاص"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    timestamp = callback.data.replace("delete_single_backup_", "")
    
    backups = get_backup_list()
    backup = None
    for b in backups:
        if b['timestamp'] == timestamp:
            backup = b
            break
    
    if not backup:
        await callback.answer(t('backup_not_found_05b76432fc', lang), show_alert=True)
        return
    
    try:
        size_str = format_size(backup['size'])
        os.remove(backup['path'])
        
        if log_system:
            await log_system.log_admin_action(
                callback.from_user.id,
                "Deleted single backup",
                details=f"File: {backup['filename']} | Size: {size_str}"
            )
        
        await callback.answer(
            t('backup_deleted_42abafc548', lang, fa_parts=lambda: (f'{size_str}',), en_parts=lambda: (f'{size_str}',)),
            show_alert=True
        )
        await admin_list_all_backups(callback)
        
    except Exception as e:
        logger.error(f"Error deleting backup: {e}", exc_info=True)
        err_type = html.escape(type(e).__name__)
        await callback.answer(t('error_30ed4c9bcc', lang, fa_parts=lambda: (err_type,), en_parts=lambda: (err_type,)), show_alert=True)


@router.callback_query(F.data == "delete_old_backups")
@admin_only
async def admin_delete_old_backups(callback: CallbackQuery):
    """حذف بکاپ‌های قدیمی (بیشتر از 30 روز)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    await callback.message.edit_text(t('i18n_checking_old_backups', lang))
    
    backups = get_backup_list()
    cutoff = datetime.now() - timedelta(days=30)
    
    deleted_count = 0
    failed_count = 0
    total_freed_mb = 0
    deleted_files = []
    
    for backup in backups:
        if backup['date'] < cutoff:
            try:
                size_mb = backup['size_mb']
                os.remove(backup['path'])
                deleted_count += 1
                total_freed_mb += size_mb
                deleted_files.append(backup['filename'])
                logger.info(f"🗑 Old backup deleted: {backup['filename']}")
            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Error deleting backup {backup['filename']}: {e}")
    if log_system:
        await log_system.log_admin_action(
            callback.from_user.id,
            "Deleted old backups",
            details=f"Deleted: {deleted_count} | Space freed: {total_freed_mb:.1f} MB"
        )
    
    text = t('b_old_backups_deleted_b_b_re_3fdf0e7fc7', lang, fa_parts=lambda: (f'{deleted_count}', f'{failed_count}', f'{total_freed_mb:.1f}', f"{(f'📋 <b>فایل\u200cهای حذف شده:</b>' if deleted_files else '')}"), en_parts=lambda: (f'{deleted_count}', f'{failed_count}', f'{total_freed_mb:.1f}', f"{(f'📋 <b>Deleted files:</b>' if deleted_files else '')}"))
    for f in deleted_files[:5]:
        text += f"• {f}\n"
    if len(deleted_files) > 5:
        text += t('and_more_89a633a3b5', lang, fa_parts=lambda: (f'{len(deleted_files) - 5}',), en_parts=lambda: (f'{len(deleted_files) - 5}',))
    
    buttons = [[InlineKeyboardButton(
        text=t('back_to_manager_36a93bc9a4', lang),
        callback_data="admin_manage_backups"
    )]]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)
 
    

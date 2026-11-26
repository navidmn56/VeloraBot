"""
routers/admin_shop.py
---------------------
مدیریت وضعیت فروشگاه، تایید دستی کاربران و نظارت بر اینباندهای پنل ادمین
"""

import os
import json
import time
import html
import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Union

from aiogram import Router, F, Bot, types
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.enums import ParseMode

from config import ADMIN_ID
from db_storage import DATA_DIR, save_json, DB_FILES
from database import (
    users,
    orders,
    chats,
    referrals,
    configs_pool,
    save_all,
    now_tehran_iso,
    SHOP_STATUS,
    BLACKLIST,
    USER_TEST_USAGE,
    save_test_usage,
)
from user_manager import user_states, get_user, get_user_safe, get_admin_id_int
from core.state_stores import (
    USER_INBOUND_SELECTION,
    USER_TEST_SETTINGS,
)
from routers.admin_test import (
    save_user_test_settings,
    invalidate_test_users_cache,
)
from strings import t
from emoji_sticker_system import premium_emoji
from utils.filters import IsAdmin
from utils.guards import admin_only
from utils.helpers import safe_answer

logger = logging.getLogger(__name__)

router = Router(name="admin_shop")

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


def save_blacklist() -> bool:
    import main
    if hasattr(main, "save_blacklist"):
        return main.save_blacklist()
    try:
        blacklist_file = os.path.join(DATA_DIR, "blacklist.json")
        blacklist_data = {
            'users': list(BLACKLIST),
            'last_updated': now_tehran_iso(),
            'count': len(BLACKLIST)
        }
        with open(blacklist_file, 'w', encoding='utf-8') as f:
            json.dump(blacklist_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving blacklist: {e}")
        return False


from services.panel_api import (
    xui_get_inbounds,
    xui_get_client_info,
    xui_get_client_traffic,
)


def is_shop_open() -> bool:
    """بررسی وضعیت فروش"""
    return SHOP_STATUS.get('open', True)

def get_shop_status_message(lang: str = 'fa') -> str:
    """دریافت پیام وضعیت فروش"""
    if lang == 'fa':
        return SHOP_STATUS.get('message', t('the_shop_is_temporarily_clos_7fe29d7f30', lang))
    return SHOP_STATUS.get('message_en') or t('the_shop_is_temporarily_clos_7fe29d7f30', lang)


def _build_shop_management_view(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    is_open = is_shop_open()
    manual_approval = configs_pool.get('manual_approval_settings', {})
    enabled = manual_approval.get('enabled', False)
    status_text = t('i18n_status_open', lang) if is_open else t('i18n_status_closed', lang)
    approval_status = t('i18n_status_active', lang) if enabled else t('i18n_status_inactive', lang)
    msg_fa = SHOP_STATUS.get('message', '')
    msg_en = SHOP_STATUS.get('message_en') or t('the_shop_is_temporarily_clos_7fe29d7f30', 'en')

    text = t(
        'b_shop_management_b_shop_sta_9b96631079',
        lang,
        fa_parts=lambda: (f'{status_text}', f'{approval_status}', f"{premium_emoji('note', '📝')}", f"{msg_fa}", f"{SHOP_STATUS.get('last_updated', 'N/A')}"),
        en_parts=lambda: (f'{status_text}', f'{approval_status}', f"{premium_emoji('note', '📝')}", f"{msg_en}", f"{SHOP_STATUS.get('last_updated', 'N/A')}"),
    )
    en_label = "📝 <b>پیام انگلیسی:</b>" if lang == "fa" else "📝 <b>Persian Message:</b>"
    extra_msg = msg_en if lang == "fa" else msg_fa
    text += f"\n\n{en_label}\n{html.escape(str(extra_msg))}"

    buttons = [
        [InlineKeyboardButton(
            text=t('i18n_close_shop_label', lang) if lang == "fa" and is_open else (t('close_shop_1d9d2610f0', lang) if is_open else t('open_shop_3662a56cc4', lang)),
            callback_data="admin_toggle_shop",
            style="danger" if is_open else "success"
        )],
        [InlineKeyboardButton(
            text=t('manual_approval_for_new_user_35afcb8a4a', lang, fa_parts=lambda: (f"{('غیرفعال کردن' if enabled else 'فعال کردن')}",), en_parts=lambda: (f"{('Disable' if enabled else 'Enable')}",)),
            callback_data="admin_toggle_manual_approval",
            style="danger" if enabled else "success"
        )],
        [InlineKeyboardButton(
            text=t('pending_approval_users_ddbdf20f2c', lang),
            callback_data="admin_pending_users",
            style="primary"
        )],
        [
            InlineKeyboardButton(
                text=t('shop_edit_message_fa_btn', lang),
                callback_data="admin_shop_message"
            ),
            InlineKeyboardButton(
                text=t('shop_edit_message_en_btn', lang),
                callback_data="admin_shop_message_en"
            ),
        ],
        [InlineKeyboardButton(
            text=t('back_14968ad63f', lang),
            callback_data="admin_panel"
        )]
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def set_shop_status(open_status: bool, message: str = None):
    """تنظیم وضعیت فروش"""
    global SHOP_STATUS
    SHOP_STATUS['open'] = open_status
    if message:
        SHOP_STATUS['message'] = message
    SHOP_STATUS['last_updated'] = now_tehran_iso()
    configs_pool['shop_status'] = SHOP_STATUS
    save_all()
    logger.info(f"Sales status changed: {'open' if open_status else 'closed'}")
    
    
@router.callback_query(F.data == "admin_shop_settings")
@admin_only
async def admin_shop_settings(callback: CallbackQuery):
    """تنظیمات فروشگاه در پنل ادمین"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    text, kb = _build_shop_management_view(lang)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await safe_answer(callback)

@router.callback_query(F.data == "admin_toggle_manual_approval")
@admin_only
async def admin_toggle_manual_approval(callback: CallbackQuery):
    """فعال/غیرفعال کردن تایید دستی کاربران جدید"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    manual_approval = configs_pool.get('manual_approval_settings', {})
    manual_approval['enabled'] = not manual_approval.get('enabled', False)
    manual_approval['last_updated'] = now_tehran_iso()
    configs_pool['manual_approval_settings'] = manual_approval
    save_all()
    
    status = t('i18n_status_active', lang) if manual_approval['enabled'] else t('i18n_status_inactive', lang)
    await callback.answer(
        t('manual_approval_d_04acdf0939', lang, fa_parts=lambda: (f'{status}',), en_parts=lambda: (f'{status}',)),
        show_alert=True
    )
    await admin_shop_settings(callback)


class ConfigCache:
    """کش تنظیمات/کانفیگ‌های کاربر با انقضای خودکار TTL"""

    def __init__(self, ttl: int = 120):
        self._cache: dict[int, tuple[float, list]] = {}
        self.cache_duration = ttl

    def get(self, user_id: int) -> list | None:
        """دریافت کانفیگ‌ها از کش در صورت معتبر بودن"""
        item = self._cache.get(user_id)
        if not item:
            return None
        exp, configs = item
        if time.monotonic() > exp:
            self._cache.pop(user_id, None)
            return None
        return configs

    def set(self, user_id: int, configs: list) -> None:
        """ذخیره کانفیگ‌ها در کش با زمان انقضا"""
        if self.cache_duration > 0:
            self._cache[user_id] = (time.monotonic() + self.cache_duration, configs)

    def clear(self, user_id: int = None) -> None:
        """پاک کردن کش یک کاربر یا کل کش"""
        if user_id is not None:
            self._cache.pop(user_id, None)
        else:
            self.clear_all()

    def clear_all(self) -> None:
        """پاک کردن همه کش"""
        self._cache.clear()

    def get_stats(self) -> dict:
        """دریافت آمار کش"""
        now = time.monotonic()
        active_items = {k: v for k, (exp, v) in self._cache.items() if exp > now}
        total_configs = sum(len(c) for c in active_items.values() if isinstance(c, list))
        return {
            'total_users': len(active_items),
            'total_configs': total_configs,
            'cache_duration': self.cache_duration
        }


config_cache = ConfigCache(ttl=120)
SYNC_IN_PROGRESS = False


@router.callback_query(F.data == "admin_pending_users")
@admin_only
async def admin_pending_users(callback: CallbackQuery):
    """نمایش لیست کاربران در انتظار تایید"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    pending_users = []
    for uid, user_data in users.items():
        if (user_data.get('requested_approval', False) and 
            not user_data.get('approved_by_admin', False) and
            user_data.get('registration_status') == 'requested' and
            int(uid) != ADMIN_ID_INT):
            pending_users.append({
                'id': int(uid),
                'name': user_data.get('name', t('i18n_user_fallback_name', lang, fa_parts=lambda: (f'{uid}',), en_parts=lambda: (f'{uid}',))),
                'join_date': user_data.get('join_date', t('i18n_unknown', lang)),
                'username': user_data.get('username', ''),
                'requested_date': user_data.get('requested_date', t('i18n_unknown', lang))
            })
    
    if not pending_users:
        await callback.answer(
            t('no_new_users_pending_approva_7cbde22c5c', lang),
            show_alert=True
        )
        return
    
    text = t('b_users_pending_approval_b_c_11b9b23e7b', lang, fa_parts=lambda: (f'{len(pending_users)}',), en_parts=lambda: (f'{len(pending_users)}',))
    
    buttons = []
    for user in pending_users[:20]:
        name = html.escape(user['name'][:20])
        username = f" @{html.escape(user['username'])}" if user['username'] else ""
        requested_date = user.get('requested_date', '')
        if requested_date and requested_date != t('i18n_unknown', lang):
            try:
                date_obj = datetime.fromisoformat(requested_date)
                date_str = date_obj.strftime('%H:%M')
            except Exception:
                date_str = ''
        else:
            date_str = ''
        
        label = f"🆕 {name}{username} - ID: {user['id']} {date_str}"
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"admin_approve_user_{user['id']}"
        )])
    
    if len(pending_users) > 20:
        buttons.append([InlineKeyboardButton(
            text=t('and_more_users_40bc87e65b', lang, fa_parts=lambda: (f'{len(pending_users) - 20}',), en_parts=lambda: (f'{len(pending_users) - 20}',)),
            callback_data="noop"
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_to_shop_settings_69923bf15f', lang),
        callback_data="admin_shop_settings"
    )])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_approve_user_"))
@admin_only
async def admin_approve_user(callback: CallbackQuery):
    """نمایش صفحه تایید/رد کاربر"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        target_id = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    target = get_user(target_id)
    
    if not target:
        await callback.answer(t('i18n_user_not_found_bang', lang), show_alert=True)
        return
    if not target.get('requested_approval', False) or target.get('registration_status') != 'requested':
        await callback.answer(t('i18n_user_did_not_request_approval', lang), show_alert=True)
        return
    name_escaped = html.escape(target.get('name', t('i18n_user_fallback_name', lang, fa_parts=lambda: (f'{target_id}',), en_parts=lambda: (f'{target_id}',))))
    username = target.get('username', '')
    username_display = f"@{html.escape(username)}" if username else t('i18n_none', lang)
    join_date = html.escape(target.get('join_date', t('i18n_unknown', lang)))
    requested_date = target.get('requested_date', t('i18n_unknown', lang))
    if requested_date and requested_date != t('i18n_unknown', lang):
        try:
            date_obj = datetime.fromisoformat(requested_date)
            requested_date = date_obj.strftime('%Y-%m-%d %H:%M')
        except Exception:
            pass
    
    text = t('b_approve_new_user_b_id_code_dd67ecf5d3', lang, fa_parts=lambda: (f'{target_id}', f'{name_escaped}', f'{username_display}', f'{join_date}', f'{requested_date}'), en_parts=lambda: (f'{target_id}', f'{name_escaped}', f'{username_display}', f'{join_date}', f'{requested_date}'))
    buttons = [
        [
            InlineKeyboardButton(
                text=t('approve_activate_9ba6fecc6d', lang),
                callback_data=f"confirm_approve_user_{target_id}",
                style="success"
            ),
            InlineKeyboardButton(
                text=t('reject_delete_fee9cd958a', lang),
                callback_data=f"confirm_reject_user_{target_id}",
                style="danger"
            )
        ],
        [InlineKeyboardButton(
            text=t('back_to_list_eca8a9c338', lang),
            callback_data="admin_pending_users"
        )]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_reject_user_"))
@admin_only
async def admin_reject_user(callback: CallbackQuery):
    """رد کاربر توسط ادمین - حذف کامل از دیتابیس"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        target_id = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    target = get_user(target_id)
    
    if not target:
        await callback.answer(t('i18n_user_not_found_bang', lang), show_alert=True)
        return
    target_name_escaped = html.escape(target.get('name', t('i18n_user_fallback_name', lang, fa_parts=lambda: (f'{target_id}',), en_parts=lambda: (f'{target_id}',))))
    username = target.get('username', '')
    username_display = f"@{html.escape(username)}" if username else t('i18n_none', lang)
    
    text = t('b_reject_delete_user_b_name_af39abd735', lang, fa_parts=lambda: (f'{target_name_escaped}', f'{target_id}', f'{username_display}'), en_parts=lambda: (f'{target_name_escaped}', f'{target_id}', f'{username_display}'))
    buttons = [
        [
            InlineKeyboardButton(
                text=t('yes_reject_delete_179b8f9aba', lang),
                callback_data=f"confirm_reject_user_{target_id}",
                style="danger"
            ),
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data="admin_pending_users",
                style="primary"
            )
        ]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
    
    await safe_answer(callback)
    
    

@router.callback_query(F.data == "admin_toggle_shop")
@admin_only
async def admin_toggle_shop(callback: CallbackQuery):
    """تغییر وضعیت فروش (باز/بسته)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    is_open = is_shop_open()
    
    set_shop_status(not is_open)
    
    await callback.answer(
        t('shop_bff0a50d70', lang, fa_parts=lambda: (f"{('باز شد' if not is_open else 'بسته شد')}",), en_parts=lambda: (f"{('opened' if not is_open else 'closed')}",)),
        show_alert=True
    )
    
    await admin_shop_settings(callback)


@router.callback_query(F.data == "admin_shop_message")
@admin_only
async def admin_shop_message_start(callback: CallbackQuery):
    """شروع ویرایش پیام فروش"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {'awaiting_shop_message': True}
    
    text = t('b_edit_shop_message_b_curren_92ad62f6e8', lang, fa_parts=lambda: (f"{premium_emoji('note', '📝')}", f"{SHOP_STATUS.get('message', '')}"), en_parts=lambda: (f"{premium_emoji('note', '📝')}", f"{SHOP_STATUS.get('message', '')}"))
    
    await callback.message.answer(text, parse_mode=ParseMode.HTML)
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_shop_message'))
async def admin_shop_message_save(message: Message):
    """ذخیره پیام جدید فروش"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_42e9c22038', lang))
        return
    
    new_message = message.text or message.caption or ""
    
    if not new_message.strip():
        await message.reply(t('message_cannot_be_empty_9669d7f21e', lang))
        return
    
    SHOP_STATUS['message'] = new_message
    SHOP_STATUS['last_updated'] = now_tehran_iso()
    configs_pool['shop_status'] = SHOP_STATUS
    save_all()
    
    user_states.pop(admin_id, None)
    await message.reply(
        t('shop_message_updated_success_ba08396b29', lang)
    )
    text, kb = _build_shop_management_view(lang)
    await message.answer(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "admin_shop_message_en")
@admin_only
async def admin_shop_message_en_start(callback: CallbackQuery):
    """شروع ویرایش پیام انگلیسی فروشگاه"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    user_states[callback.from_user.id] = {'awaiting_shop_message_en': True}
    cur_en = SHOP_STATUS.get('message_en') or t('the_shop_is_temporarily_clos_7fe29d7f30', 'en')
    await callback.message.answer(
        t('shop_edit_message_en_prompt', lang, fa_parts=lambda: (html.escape(str(cur_en)),), en_parts=lambda: (html.escape(str(cur_en)),)),
        parse_mode=ParseMode.HTML,
    )
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_shop_message_en'))
async def admin_shop_message_en_save(message: Message):
    """ذخیره پیام انگلیسی جدید فروشگاه"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_42e9c22038', lang))
        return

    new_message = message.text or message.caption or ""
    if not new_message.strip():
        await message.reply(t('message_cannot_be_empty_9669d7f21e', lang))
        return

    SHOP_STATUS['message_en'] = new_message.strip()
    SHOP_STATUS['last_updated'] = now_tehran_iso()
    configs_pool['shop_status'] = SHOP_STATUS
    save_all()
    user_states.pop(admin_id, None)

    await message.reply(t('shop_message_en_updated', lang))
    text, kb = _build_shop_management_view(lang)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@router.callback_query(F.data.startswith("confirm_approve_user_"))
@admin_only
async def confirm_approve_user(callback: CallbackQuery):
    """تایید و فعال‌سازی کاربر"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        target_id = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    target = get_user(target_id)
    
    if not target:
        await callback.answer(t('i18n_user_not_found_bang', lang), show_alert=True)
        return
    uid = str(target_id)
    if uid in users:
        pending_deep_link = users[uid].pop('pending_deep_link', None)
        users[uid]['approved_by_admin'] = True
        users[uid]['approved_date'] = now_tehran_iso()
        users[uid]['registration_status'] = 'approved'
        users[uid]['updated_at'] = now_tehran_iso()
        save_json(DB_FILES['users'], users)
        try:
            user_lang = target.get('lang', 'fa')
            approve_reply_markup = None
            if pending_deep_link:
                try:
                    bot_info = await bot.get_me()
                    if getattr(bot_info, 'username', None):
                        approve_reply_markup = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(
                                text=t('deeplink_continue_after_approval', user_lang),
                                url=f"https://t.me/{bot_info.username}?start={pending_deep_link}",
                            )
                        ]])
                except Exception as dl_btn_err:
                    logger.debug(f"Could not attach deep-link continue button for user {target_id}: {dl_btn_err}")
            await bot.send_message(
                target_id,
                t('b_your_account_has_been_appr_ab66b5881a', user_lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}",), en_parts=lambda: (f"{premium_emoji('success', '✅')}",)),
                reply_markup=approve_reply_markup,
            )
        except Exception as e:
            logger.error(f"Error sending confirmation message to user {target_id}: {e}")
        if log_system:
            await log_system.log_admin_action(
                callback.from_user.id,
                f"Approved new user {target_id}",
                details=f"Name: {target.get('name')}"
            )
        
        name_escaped = html.escape(target.get('name', t('i18n_user_fallback_name', lang, fa_parts=lambda: (f'{target_id}',), en_parts=lambda: (f'{target_id}',))))
        try:
            await callback.message.delete()
        except Exception:
            pass
        
        text = t('b_user_approved_successfully_e9ea76f779', lang, fa_parts=lambda: (f'{name_escaped}', f'{target_id}', f"{html.escape(target.get('username', ''))}"), en_parts=lambda: (f'{name_escaped}', f'{target_id}', f"{html.escape(target.get('username', ''))}"))
        
        buttons = [
            [InlineKeyboardButton(
                text=t('back_to_list_17f317f77e', lang),
                callback_data="admin_pending_users"
            )],
            [InlineKeyboardButton(
                text=t('admin_panel_bf28b6b107', lang),
                callback_data="admin_panel"
            )]
        ]
        
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
        
        await callback.answer()
    else:
        await callback.answer(t('i18n_user_not_found_in_db', lang), show_alert=True)


@router.callback_query(F.data.startswith("confirm_reject_user_"))
@admin_only
async def confirm_reject_user(callback: CallbackQuery):
    """اجرای رد و حذف کاربر از دیتابیس"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        target_id = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    target = get_user(target_id)
    
    if not target:
        await callback.answer(t('i18n_user_not_found_bang', lang), show_alert=True)
        return
    
    target_name_escaped = html.escape(target.get('name', t('i18n_user_fallback_name', lang, fa_parts=lambda: (f'{target_id}',), en_parts=lambda: (f'{target_id}',))))
    try:
        user_lang = target.get('lang', 'fa')
        await bot.send_message(
            target_id,
            t('b_your_request_has_been_reje_ac68dee0c0', user_lang, fa_parts=lambda: (f"{premium_emoji('fail', '❌')}",), en_parts=lambda: (f"{premium_emoji('fail', '❌')}",))
        )
        logger.info(f"📨 rejection message to user {target_id} sent")
    except Exception as e:
        logger.error(f"❌ Error sending rejection message to user {target_id}: {e}")
    uid = str(target_id)
    if uid in users:
        del users[uid]
        logger.info(f"🗑 user {target_id} removed from database")
    deleted_orders = 0
    for oid in list(orders.keys()):
        if isinstance(orders[oid], dict) and orders[oid].get('user_id') == target_id:
            del orders[oid]
            deleted_orders += 1
    deleted_refs = 0
    for key in list(referrals.keys()):
        if referrals[key].get('referrer') == target_id or referrals[key].get('referred') == target_id:
            del referrals[key]
            deleted_refs += 1
    deleted_chats = 0
    for cid in list(chats.keys()):
        if chats[cid].get('user_id') == target_id:
            del chats[cid]
            deleted_chats += 1
    if target_id in BLACKLIST:
        BLACKLIST.discard(target_id)
    if target_id in user_states:
        del user_states[target_id]
    config_cache.clear(target_id)
    logger.info(f"🧹 user cache {target_id} cleared because user deleted")
    if uid in USER_TEST_USAGE:
        del USER_TEST_USAGE[uid]
    if uid in USER_TEST_SETTINGS:
        del USER_TEST_SETTINGS[uid]
    save_all()
    save_blacklist()
    save_test_usage()
    invalidate_test_users_cache()
    save_user_test_settings()
    logger.info(f"🗑 user {target_id} ({target_name_escaped}) with {deleted_orders} order and {deleted_refs} referral reset")
    
    if log_system:
        await log_system.log_admin_action(
            callback.from_user.id,
            f"Rejected and deleted user {target_id}",
            details=f"Name: {target_name_escaped} | Orders: {deleted_orders} | Referrals: {deleted_refs} | Chats: {deleted_chats}"
        )
    text = t('b_user_rejected_and_deleted_0b55bc2db6', lang, fa_parts=lambda: (f'{target_name_escaped}', f'{target_id}', f'{deleted_orders}', f'{deleted_refs}', f'{deleted_chats}'), en_parts=lambda: (f'{target_name_escaped}', f'{target_id}', f'{deleted_orders}', f'{deleted_refs}', f'{deleted_chats}'))
    
    buttons = [
        [InlineKeyboardButton(
            text=t('pending_users_47b5e3a6de', lang),
            callback_data="admin_pending_users",
            style="primary"
        )],
        [InlineKeyboardButton(
            text=t('admin_panel_bf28b6b107', lang),
            callback_data="admin_panel"
        )]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
    
    await safe_answer(callback, t('user_deleted_520372cec4', lang), alert=True)
    
@router.callback_query(F.data == "admin_inbounds")
@admin_only
async def admin_inbounds_list(callback: CallbackQuery):
    """نمایش لیست اینباندهای پنل با نشان دادن اینباندهای پیش‌فرض"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    await callback.message.edit_text(t('i18n_loading_inbounds', lang))

    inbounds = await xui_get_inbounds()
    default_ids = configs_pool.get('default_inbound_ids', [])
    
    if not inbounds:
        text = t('no_inbounds_found_or_panel_c_c0e6c4d0a4', lang)
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('retry_5550d5f4fa', lang), callback_data="admin_inbounds")],
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
            ])
        )
        return
    text = t('b_panel_inbounds_b_count_31693c4d5d', lang, fa_parts=lambda: (f'{len(inbounds)}',), en_parts=lambda: (f'{len(inbounds)}',))
    text += t('default_inbounds_d123d69ab5', lang, fa_parts=lambda: (f"{(default_ids if default_ids else t('i18n_not_set', lang))}",), en_parts=lambda: (f"{(default_ids if default_ids else t('i18n_not_set', lang))}",))
    
    buttons = []
    for inbound in inbounds:
        inbound_id = inbound.get('id')
        port = inbound.get('port')
        protocol = inbound.get('protocol', 'unknown')
        remark = inbound.get('remark', f'Inbound {inbound_id}')
        enable = inbound.get('enable', True)
        
        status_icon = "🟢" if enable else "🔴"
        is_default = "⭐" if inbound_id in default_ids else "  "
        
        label = f"{is_default} {status_icon} {remark} - {protocol.upper()} :{port}"
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"admin_inbound_detail_{inbound_id}"
        )])
    buttons.append([InlineKeyboardButton(
        text=t('set_default_inbounds_f346badc1a', lang),
        callback_data="admin_inbound_default"
    )])
    
    buttons.append([InlineKeyboardButton(
        text=t('refresh_cda5094083', lang),
        callback_data="admin_inbounds"
    )])
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_panel"
    )])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)

def migrate_inbound_data():
    """مهاجرت داده‌های اینباند از تک به چندتایی"""
    if 'default_inbound_id' in configs_pool:
        old_default = configs_pool.get('default_inbound_id')
        if old_default and 'default_inbound_ids' not in configs_pool:
            configs_pool['default_inbound_ids'] = [old_default]
            logger.info(f"✅ Default inbound migration: {old_default} -> {configs_pool['default_inbound_ids']}")
        del configs_pool['default_inbound_id']
        save_all()

@router.callback_query(F.data.startswith("admin_inbound_detail_"))
@admin_only
async def admin_inbound_detail(callback: CallbackQuery):
    """نمایش جزئیات یک اینباند و تنظیم آن برای کاربران"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    parts = callback.data.split("_")
    
    try:
        if len(parts) >= 4 and parts[3] == 'default':
            inbound_id = configs_pool.get('default_inbound_id')
            if not inbound_id:
                await callback.answer(t('i18n_no_default_inbound_set_bang', lang), show_alert=True)
                return
        else:
            inbound_id = int(parts[3]) if len(parts) > 3 else None
    except (ValueError, IndexError):
        inbound_id = configs_pool.get('default_inbound_id')
        if not inbound_id:
            await callback.answer(t('i18n_no_valid_inbound_found_bang', lang), show_alert=True)
            return
    
    if not inbound_id:
        await callback.answer(t('i18n_no_valid_inbound_found_bang', lang), show_alert=True)
        return
    
    inbounds = await xui_get_inbounds()
    inbound = None
    for i in inbounds:
        if i.get('id') == inbound_id:
            inbound = i
            break
    
    if not inbound:
        await callback.answer(t('i18n_inbound_not_found', lang), show_alert=True)
        return
    user_count = 0
    for uid, ib_id in USER_INBOUND_SELECTION.items():
        if isinstance(ib_id, list):
            if inbound_id in ib_id:
                user_count += 1
        else:
            if int(ib_id) == inbound_id:
                user_count += 1
    port = inbound.get('port')
    protocol = inbound.get('protocol', 'unknown')
    remark = inbound.get('remark', f'Inbound {inbound_id}')
    enable = inbound.get('enable', True)
    settings = inbound.get('settings', {})
    clients = settings.get('clients', [])
    
    text = t('b_inbound_details_b_id_name_ae640925ae', lang, fa_parts=lambda: (f'{inbound_id}', f'{remark}', f'{protocol.upper()}', f'{port}', t('i18n_status_active', lang) if enable else t('i18n_status_inactive', lang), f'{user_count}', f'{len(clients)}', f"{settings.get('ipLimit', t('i18n_unknown', lang))}", f"{settings.get('expiryTime', t('i18n_unknown', lang))}"), en_parts=lambda: (f'{inbound_id}', f'{remark}', f'{protocol.upper()}', f'{port}', t('i18n_status_active', lang) if enable else t('i18n_status_inactive', lang), f'{user_count}', f'{len(clients)}', f"{settings.get('ipLimit', t('i18n_unknown', lang))}", f"{settings.get('expiryTime', t('i18n_unknown', lang))}"))
    buttons = [
        [InlineKeyboardButton(text=t('view_clients_d9f439ff7a', lang), callback_data=f"admin_inbound_clients_{inbound_id}")],
        [InlineKeyboardButton(text=t('view_users_ea6de3ff4d', lang), callback_data=f"admin_inbound_users_{inbound_id}")],
    ]

    default_id = configs_pool.get('default_inbound_id')
    if default_id == inbound_id:
        buttons.append([InlineKeyboardButton(text=t('current_default_6efdf1acd5', lang), callback_data="noop", style="primary")])
    else:
        buttons.append([InlineKeyboardButton(text=t('set_as_default_8698a1dc7f', lang), callback_data=f"admin_inbound_set_default_{inbound_id}", style="primary")])

    buttons.append([InlineKeyboardButton(text=t('back_to_list_eca8a9c338', lang), callback_data="admin_inbounds")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)

@router.callback_query(F.data.startswith("admin_inbound_clients_"))
@admin_only
async def admin_inbound_clients(callback: CallbackQuery):
    """مشاهده کلاینت‌های یک اینباند"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        inbound_id = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    await callback.message.edit_text(t('i18n_loading_info', lang))
    inbounds = await xui_get_inbounds()
    inbound = None
    for i in inbounds:
        if i.get('id') == inbound_id:
            inbound = i
            break

    if not inbound:
        await callback.answer(t('i18n_inbound_not_found', lang), show_alert=True)
        return
    settings = inbound.get('settings', {})
    clients = settings.get('clients', [])
    
    if not clients:
        text = t('b_clients_of_inbound_b_no_cl_d0fe12c613', lang, fa_parts=lambda: (f'{inbound_id}',), en_parts=lambda: (f'{inbound_id}',))
        
        buttons = [[InlineKeyboardButton(
            text=t('back_14968ad63f', lang),
            callback_data=f"admin_inbound_detail_{inbound_id}"
        )]]
        
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return
    text = t('b_clients_of_inbound_b_count_24d40eb2eb', lang, fa_parts=lambda: (f'{inbound_id}', f'{len(clients)}'), en_parts=lambda: (f'{inbound_id}', f'{len(clients)}'))
    
    buttons = []
    for client in clients[:20]:  # حداکثر 20 تا نمایش داده شود
        email = client.get('email', t('i18n_unknown', lang))
        enable = client.get('enable', True)
        total_gb = client.get('totalGB', 0) / (1024**3) if client.get('totalGB') else 0
        
        status_icon = "🟢" if enable else "🔴"
        label = f"{status_icon} {email} - {total_gb:.0f}GB"
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"admin_client_detail_{email}_{inbound_id}"
        )])
    
    if len(clients) > 20:
        buttons.append([InlineKeyboardButton(
            text=t('and_more_clients_5ed8a78fa7', lang, fa_parts=lambda: (f'{len(clients) - 20}',), en_parts=lambda: (f'{len(clients) - 20}',)),
            callback_data="noop"
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data=f"admin_inbound_detail_{inbound_id}"
    )])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)
        
        
        
@router.callback_query(F.data.startswith("admin_inbound_users_"))
@admin_only
async def admin_inbound_users(callback: CallbackQuery):
    """مشاهده کاربرانی که این اینباند را انتخاب کرده‌اند"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        inbound_id = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    users_with_inbound = []
    for uid, ib_id in USER_INBOUND_SELECTION.items():
        is_selected = False
        if isinstance(ib_id, list):
            if inbound_id in ib_id:
                is_selected = True
        else:
            if int(ib_id) == inbound_id:
                is_selected = True
        
        if is_selected:
            user_info = get_user_safe(uid)
            raw_name = user_info.get('name', f'کاربر_{uid}') if user_info else f'کاربر_{uid}'
            balance = user_info.get('balance', 0) if user_info else 0
            users_with_inbound.append({
                'id': int(uid) if uid.isdigit() else uid,
                'name': raw_name,
                'balance': balance
            })
    
    if not users_with_inbound:
        text = t('b_users_with_inbound_b_no_us_ae4a67d147', lang, fa_parts=lambda: (f'{inbound_id}',), en_parts=lambda: (f'{inbound_id}',))
        
        buttons = [[InlineKeyboardButton(
            text=t('back_14968ad63f', lang),
            callback_data=f"admin_inbound_detail_{inbound_id}"
        )]]
        
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return
    text = t('b_users_with_inbound_b_count_317b4547c5', lang, fa_parts=lambda: (f'{inbound_id}', f'{len(users_with_inbound)}'), en_parts=lambda: (f'{inbound_id}', f'{len(users_with_inbound)}'))
    
    buttons = []
    for user in users_with_inbound[:20]:
        label = f"👤 {user['name']} (ID: {user['id']}) - 💰 {user['balance']:,}"
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"admin_user_{user['id']}"
        )])
    
    if len(users_with_inbound) > 20:
        buttons.append([InlineKeyboardButton(
            text=t('and_more_users_40bc87e65b', lang, fa_parts=lambda: (f'{len(users_with_inbound) - 20}',), en_parts=lambda: (f'{len(users_with_inbound) - 20}',)),
            callback_data="noop"
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data=f"admin_inbound_detail_{inbound_id}"
    )])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)
        
        
@router.callback_query(F.data.startswith("admin_inbound_set_default_"))
@admin_only
async def admin_inbound_set_default(callback: CallbackQuery):
    """تنظیم اینباند پیش‌فرض"""
    parts = callback.data.split("_")
    try:
        inbound_id = int(parts[4]) if len(parts) > 4 else None
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    if not inbound_id:
        await callback.answer(t('i18n_inbound_invalid', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    configs_pool['default_inbound_id'] = inbound_id
    save_all()
    
    await callback.answer(
        t('inbound_set_as_default_e729b89224', lang, fa_parts=lambda: (f'{inbound_id}',), en_parts=lambda: (f'{inbound_id}',)),
        show_alert=True
    )
    

    new_callback = callback
    
    await show_inbound_detail(callback.message, inbound_id, lang)
    
async def show_inbound_detail(message: types.Message, inbound_id: int, lang: str = "fa"):
    """نمایش جزئیات یک اینباند با استفاده از Message به جای CallbackQuery"""
    inbounds = await xui_get_inbounds()
    inbound = None
    for i in inbounds:
        if i.get('id') == inbound_id:
            inbound = i
            break
    
    if not inbound:
        await message.answer(t('i18n_inbound_not_found', lang))
        return

@router.callback_query(F.data.startswith("admin_client_detail_"))
@admin_only
async def admin_client_detail(callback: CallbackQuery):
    """نمایش جزئیات یک کلاینت خاص"""
    
    parts = callback.data.split("_")
    
    try:
        email = "_".join(parts[3:-1])  # همه چیز بین detail و inboundid
        inbound_id = int(parts[-1]) if parts[-1].isdigit() else None
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    if not email:
        await callback.answer(t('i18n_invalid_email', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    lang = get_user(callback.from_user.id).get('lang', 'fa')

    await callback.message.edit_text(t('i18n_loading_client_info', lang))
    client = await xui_get_client_info(email)
    
    if not client:
        text = t('client_not_found_it_may_have_985403b186', lang, fa_parts=lambda: (f'{email}',), en_parts=lambda: (f'{email}',))
        
        buttons = [[InlineKeyboardButton(
            text=t('back_14968ad63f', lang),
            callback_data=f"admin_inbound_clients_{inbound_id}"
        )]]
        
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return
    traffic = await xui_get_client_traffic(email)
    total_gb = client.get('totalGB', 0) / (1024**3) if client.get('totalGB') else 0
    enable = client.get('enable', True)
    expiry_time = client.get('expiryTime', 0)
    days_left = t('i18n_unknown', lang)
    if expiry_time > 0:
        try:
            expiry_date = datetime.fromtimestamp(expiry_time / 1000)
            days_left = (expiry_date - datetime.now()).days
            days_left = max(0, days_left)
        except Exception:
            days_left = t('i18n_unknown', lang)
    up = (traffic.get('up', 0) if traffic else 0) / (1024**3)
    down = (traffic.get('down', 0) if traffic else 0) / (1024**3)
    used = up + down
    remaining = max(0, total_gb - used)
    
    text = t('b_client_details_b_email_cod_2fd182a958', lang, fa_parts=lambda: (f'{email}', f'{inbound_id}', t('i18n_status_active', lang) if enable else t('i18n_status_inactive', lang), f'{total_gb:.0f}', f'{used:.2f}', f'{remaining:.2f}', f"{(expiry_date.strftime('%Y-%m-%d') if expiry_time > 0 else t('i18n_unknown', lang))}", f'{days_left}', f'{up:.2f}', f'{down:.2f}'), en_parts=lambda: (f'{email}', f'{inbound_id}', t('i18n_status_active', lang) if enable else t('i18n_status_inactive', lang), f'{total_gb:.0f}', f'{used:.2f}', f'{remaining:.2f}', f"{(expiry_date.strftime('%Y-%m-%d') if expiry_time > 0 else t('i18n_unknown', lang))}", f'{days_left}', f'{up:.2f}', f'{down:.2f}'))
    
    buttons = [
        [InlineKeyboardButton(
            text=t('refresh_cda5094083', lang),
            callback_data=f"admin_client_detail_{email}_{inbound_id}"
        )],
        [InlineKeyboardButton(
            text=t('back_14968ad63f', lang),
            callback_data=f"admin_inbound_clients_{inbound_id}"
        )]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
    await safe_answer(callback)
        
        
        
@router.callback_query(F.data == "admin_inbound_default")
@admin_only
async def admin_inbound_default_setting(callback: CallbackQuery):
    """تنظیم اینباندهای پیش‌فرض (چندین اینباند)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    inbounds = await xui_get_inbounds()
    
    if not inbounds:
        await callback.answer(t('i18n_no_inbounds_found', lang), show_alert=True)
        return

    default_ids = configs_pool.get('default_inbound_ids', [])
    from services.panel_api import get_inbound_display_names
    inbound_map = await get_inbound_display_names(include_disabled=True)
    default_display = (
        ", ".join(
            inbound_map.get(int(ib_id), f"ID:{ib_id}")
            if str(ib_id).lstrip('-').isdigit()
            else str(ib_id)
            for ib_id in default_ids
        )
        if default_ids
        else t('i18n_not_set', lang)
    )

    text = t('b_set_default_inbounds_b_9b1e428a6b', lang)
    text += t('these_inbounds_will_be_used_e58f50a192', lang)
    text += t('current_inbounds_0c8b6c1306', lang, fa_parts=lambda: (f"{default_display}",), en_parts=lambda: (f"{default_display}",))
    text += t('you_can_select_multiple_inbo_2b995eb108', lang)
    text += t('selected_inbounds_are_marked_960d4e6140', lang)
    text += t('please_select_the_inbounds_60485aeaab', lang)
    
    buttons = []
    for inbound in inbounds:
        inbound_id = inbound.get('id')
        remark = inbound.get('remark', f'Inbound {inbound_id}')
        protocol = inbound.get('protocol', 'unknown')
        port = inbound.get('port')
        enable = inbound.get('enable', True)
        
        if not enable:
            continue
        
        is_selected = inbound_id in default_ids
        label = f"{'✅' if is_selected else '  '} {remark} - {protocol.upper()}:{port}"
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"admin_inbound_toggle_default_{inbound_id}",
            style="primary" if is_selected else None
        )])
    buttons.append([InlineKeyboardButton(
        text=t('select_all_9792663d71', lang),
        callback_data="admin_inbound_select_all_defaults",
        style="success"
    )])
    buttons.append([InlineKeyboardButton(
        text=t('save_settings_d9e3bd6fe8', lang),
        callback_data="admin_inbound_save_defaults",
        style="success"
    )])
    buttons.append([InlineKeyboardButton(
        text=t('clear_all_565e888195', lang),
        callback_data="admin_inbound_clear_defaults",
        style="danger"
    )])
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_inbounds"
    )])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_inbound_toggle_default_"))
@admin_only
async def admin_inbound_toggle_default(callback: CallbackQuery):
    """تغییر وضعیت انتخاب یک اینباند"""
    
    try:
        inbound_id = int(callback.data.split("_")[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    default_ids = configs_pool.get('default_inbound_ids', [])
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    if inbound_id in default_ids:
        default_ids.remove(inbound_id)
        await callback.answer(t('i18n_inbound_removed_from_list', lang, fa_parts=lambda: (f'{inbound_id}',), en_parts=lambda: (f'{inbound_id}',)), show_alert=True)
    else:
        default_ids.append(inbound_id)
        await callback.answer(t('i18n_inbound_added_to_list', lang, fa_parts=lambda: (f'{inbound_id}',), en_parts=lambda: (f'{inbound_id}',)), show_alert=True)
    
    configs_pool['default_inbound_ids'] = default_ids
    save_all()
    await admin_inbound_default_setting(callback)


@router.callback_query(F.data == "admin_inbound_save_defaults")
@admin_only
async def admin_inbound_save_defaults(callback: CallbackQuery):
    """ذخیره تنظیمات اینباندهای پیش‌فرض"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    default_ids = configs_pool.get('default_inbound_ids', [])
    
    if not default_ids:
        await callback.answer(
            t('select_at_least_one_inbound_edfdbbe67e', lang),
            show_alert=True
        )
        return
    
    await callback.answer(
        t('inbounds_saved_as_default_67cb15adb4', lang, fa_parts=lambda: (f'{len(default_ids)}',), en_parts=lambda: (f'{len(default_ids)}',)),
        show_alert=True
    )
    try:
        await admin_inbound_default_setting(callback)
    except Exception as e:
        if "message is not modified" in str(e):
            await callback.message.answer(
                t('settings_saved_c0e273f9a9', lang),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t('back_to_list_17f317f77e', lang),
                        callback_data="admin_inbounds"
                    )]
                ])
            )
        else:
            raise


@router.callback_query(F.data == "admin_inbound_clear_defaults")
@admin_only
async def admin_inbound_clear_defaults(callback: CallbackQuery):
    """پاک کردن همه اینباندهای پیش‌فرض"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    configs_pool['default_inbound_ids'] = []
    save_all()
    
    await callback.answer(
        t('all_default_inbounds_cleared_51ed3ca3be', lang),
        show_alert=True
    )
    await admin_inbound_default_setting(callback)
        
@router.callback_query(F.data == "admin_inbound_select_all_defaults")
@admin_only
async def admin_inbound_select_all_defaults(callback: CallbackQuery):
    """انتخاب همه اینباندهای فعال به عنوان پیش‌فرض"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    inbounds = await xui_get_inbounds(force_refresh=True)
    active_inbounds = [i for i in inbounds if i.get('enable', True)]
    all_ids = [int(i.get('id')) for i in active_inbounds if i.get('id') is not None]
    
    if not all_ids:
        await callback.answer(
            t('no_active_inbounds_dbaafeca1e', lang),
            show_alert=True
        )
        return
    
    configs_pool['default_inbound_ids'] = all_ids
    save_all()
    
    logger.info(f"✅ {len(all_ids)} inbound selected as default: {all_ids}")
    
    await callback.answer(
        t('inbounds_selected_e5a04d8363', lang, fa_parts=lambda: (f'{len(all_ids)}',), en_parts=lambda: (f'{len(all_ids)}',)),
        show_alert=True
    )
    await admin_inbound_default_setting(callback)     
        
        



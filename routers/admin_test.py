"""
routers/admin_test.py
---------------------
مدیریت سرویس تست ادمین، اینباندها و تنظیمات اختصاصی کاربران تست
"""

import os
import json
import time
import html
import asyncio
import logging
from datetime import datetime
from io import BytesIO
from typing import Optional, List, Dict, Any, Tuple, Union

from aiogram import Router, F, Bot, types
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BufferedInputFile,
)
from aiogram.filters.callback_data import CallbackData
from aiogram.enums import ParseMode

from config import ADMIN_ID
from db_storage import DATA_DIR
from database import (
    users,
    orders,
    configs_pool,
    save_all,
    now_tehran,
    now_tehran_iso,
    TEST_SERVICE_STATUS,
    USER_TEST_USAGE,
    save_test_usage,
    READY_PACKAGES,
    BLACKLIST,
    update_order,
)
from user_manager import user_states, get_user, get_user_safe, get_admin_id_int
from core.state_stores import (
    TEMP_INBOUND_SELECTION,
    INBOUND_BACK_DATA,
    USER_INBOUND_SELECTION,
    USER_TEST_SETTINGS,
)
from core.save_scheduler import schedule_save
from strings import t
from emoji_sticker_system import premium_emoji
from utils.filters import IsAdmin
from utils.guards import admin_only
from utils.helpers import (
    safe_answer,
    safe_edit_message,
    safe_html,
    notify_blacklisted_user,
    get_back_only_keyboard,
)
from routers.force_join import check_membership
async def send_config_with_qr_option(*args, **kwargs):
    from routers.configs_view import send_config_with_qr_option as _send
    return await _send(*args, **kwargs)
from services.panel_api import xui_create_client_with_inbound, get_user_inbound

async def send_admin_notification(*args, **kwargs):
    import main
    if hasattr(main, "send_admin_notification"):
        return await main.send_admin_notification(*args, **kwargs)

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
        raise AttributeError(f"'NoneType' object has no attribute '{name}'")

log_system = _LogSystemProxy()

def create_order(*args, **kwargs):
    import main
    if hasattr(main, "create_order"):
        return main.create_order(*args, **kwargs)


def format_volume(value: Union[int, float], is_test: bool = False) -> str:
    from routers.admin_packages import format_volume as _fmt
    return _fmt(value, is_test=is_test)

logger = logging.getLogger(__name__)

router = Router(name="admin_test")

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

def create_order(*args, **kwargs):
    import main
    if hasattr(main, "create_order"):
        return main.create_order(*args, **kwargs)



from services.panel_api import xui_get_inbounds


async def get_user_info_from_telegram(user_id: int, force_refresh: bool = False) -> dict:
    import main
    if hasattr(main, "get_user_info_from_telegram"):
        return await main.get_user_info_from_telegram(user_id, force_refresh=force_refresh)
    return {}


async def admin_panel(callback: CallbackQuery):
    import main
    if hasattr(main, "admin_panel"):
        return await main.admin_panel(callback)


async def admin_category_edit(callback: CallbackQuery):
    import main
    if hasattr(main, "admin_category_edit"):
        return await main.admin_category_edit(callback)


def update_test_settings(**changes) -> dict:
    """به‌روزرسانی تنظیمات سرویس تست، درج تاریخ تغییر و ذخیره‌سازی خودکار در دیتابیس"""
    if 'volume_mb' in changes and 'volume' not in changes:
        changes['volume'] = round(changes['volume_mb'] / 1024, 3)
    elif 'volume' in changes and 'volume_mb' not in changes:
        changes['volume_mb'] = int(round(changes['volume'] * 1024))

    TEST_SERVICE_STATUS.update(changes)
    TEST_SERVICE_STATUS['last_updated'] = now_tehran_iso()
    configs_pool['test_service'] = TEST_SERVICE_STATUS
    schedule_save(2.0)
    logger.info(f"⚙️ Test service settings updated: {list(changes.keys())}")
    return TEST_SERVICE_STATUS


def get_admin_test_service_keyboard(settings: dict, lang: str) -> InlineKeyboardMarkup:
    """ساخت کیبورد تنظیمات سرویس تست"""
    buttons = [
        [InlineKeyboardButton(
            text=t('test_f0347c4a3e', lang, fa_parts=lambda: (f"{('غیرفعال کردن' if settings.get('enabled') else 'فعال کردن')}",), en_parts=lambda: (f"{('Disable' if settings.get('enabled') else 'Enable')}",)),
            callback_data="admin_test_toggle"
        )],
        [InlineKeyboardButton(
            text=t('edit_test_volume_mb_3cad56edee', lang),
            callback_data="admin_test_edit_volume"
        )],
        [InlineKeyboardButton(
            text=t('edit_test_duration_5cee1a182d', lang),
            callback_data="admin_test_edit_days"
        )],
        [InlineKeyboardButton(
            text=t('edit_max_tests_815b176da5', lang),
            callback_data="admin_test_edit_max"
        )],
        [InlineKeyboardButton(
            text=t('edit_ip_limit_7d1896e03f', lang),
            callback_data="admin_test_edit_ip_limit"
        )],
        [InlineKeyboardButton(
            text=t('set_test_inbounds_09af2c18bc', lang),
            callback_data="admin_test_inbounds"
        )],
        [InlineKeyboardButton(
            text=t('edit_test_message_5ffc2ccadb', lang),
            callback_data="admin_test_edit_message"
        )],
        [InlineKeyboardButton(
            text=t('test_statistics_da55586f6d', lang),
            callback_data="admin_test_stats"
        )],
        [InlineKeyboardButton(
            text=t('test_users_management_fda9d0c6c6', lang),
            callback_data="admin_test_users",
            style="primary"
        )],
        [InlineKeyboardButton(
            text=t('back_14968ad63f', lang),
            callback_data="admin_panel"
        )]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def build_admin_test_service_content(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    """تولید همزمان متن و کیبورد تنظیمات سرویس تست به صورت یکپارچه"""
    settings = TEST_SERVICE_STATUS
    status_text = t('i18n_status_active', lang) if settings.get('enabled') else t('i18n_status_inactive', lang)

    inbound_ids = settings.get('inbound_ids', [])
    inbound_info = t('i18n_status_default_like_user', lang)
    if inbound_ids:
        inbounds = await xui_get_inbounds()
        inbound_names = []
        for ib_id in inbound_ids:
            for ib in inbounds:
                if ib.get('id') == ib_id:
                    inbound_names.append(f"{ib.get('remark', f'ID:{ib_id}')} - {ib.get('protocol', '').upper()}:{ib.get('port', '')}")
                    break
        if inbound_names:
            inbound_info = t('i18n_test_inbounds_title', lang) + "\n".join([f"  • {name}" for name in inbound_names])
        else:
            inbound_info = t('i18n_selected_inbounds_title', lang, fa_parts=lambda: (f'{inbound_ids}',), en_parts=lambda: (f'{inbound_ids}',))

    ip_limit = settings.get('ip_limit', 0)
    ip_display = t('i18n_status_unlimited', lang) if ip_limit == 0 else t('i18n_devices_count', lang, fa_parts=lambda: (f'{ip_limit}',), en_parts=lambda: (f'{ip_limit}',))

    volume_mb = settings.get('volume_mb', 1024)
    if volume_mb == 0:
        volume_display = t('i18n_status_unlimited', lang)
    else:
        volume_gb = volume_mb / 1024
        volume_display = f"{volume_gb:.1f} GB ({volume_mb:,} MB)"

    text = t('b_test_service_management_b_9634473ed2', lang, fa_parts=lambda: (f'{status_text}', f'{volume_display}', f"{settings.get('days', 3)}", f'{ip_display}', f"{settings.get('max_tests', 1)}", f'{inbound_info}', f"{premium_emoji('note', '📝')}", f"{settings.get('message', '')}", f"{settings.get('last_updated', 'N/A')}"), en_parts=lambda: (f'{status_text}', f'{volume_display}', f"{settings.get('days', 3)}", f'{ip_display}', f"{settings.get('max_tests', 1)}", f'{inbound_info}', f"{premium_emoji('note', '📝')}", f"{settings.get('message', '')}", f"{settings.get('last_updated', 'N/A')}"))

    kb = get_admin_test_service_keyboard(settings, lang)
    return text, kb


@router.callback_query(F.data == "admin_test_service")
@admin_only
async def admin_test_service_settings(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    text, kb = await build_admin_test_service_content(lang)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await safe_answer(callback)


class InboundCB(CallbackData, prefix="inb"):
    """فکتوری کال‌بک دیتای مدیریت اینباندها"""
    action: str   # toggle | selectall | clear | save | back | default
    prefix: str   # test_service | category_1 ...
    inbound_id: int = 0


class OrderInboundCB(CallbackData, prefix="oinb"):
    """فکتوری کال‌بک دیتای مدیریت اینباند سفارشات کاربران"""
    action: str   # toggle | selectall | default | clear | save | cancel
    uid: int
    oid: int
    inbound_id: int = 0


class AdminTestPageCB(CallbackData, prefix="atp"):
    """فکتوری کال‌بک دیتای صفحه‌بندی مدیریت کاربران تست ادمین"""
    kind: str      # "list" | "settings"
    page: int = 0


async def show_inbound_manager(
    message: types.Message,
    title: str,
    current_inbound_ids: list,
    callback_data_prefix: str,
    save_callback: Optional[str] = None,
    back_callback: Optional[str] = None,
    admin_id: Optional[int] = None,
    show_default_button: bool = True,
    show_clear_button: bool = True,
    update_existing: bool = False,
    extra_data: Optional[dict] = None
):
    """صفحه پیشرفته مدیریت اینباندها (با فیلتر نامعتبرها)"""
    if admin_id != ADMIN_ID_INT:
        return
    
    lang = get_user(admin_id).get('lang', 'fa')
    
    inbounds = await xui_get_inbounds()
    active_inbounds = [i for i in inbounds if i.get('enable', True)]
    
    if not active_inbounds:
        await message.answer(t('i18n_no_active_inbounds', lang))
        return
    valid_ids = {ib.get('id') for ib in active_inbounds}
    
    temp_key = f"{callback_data_prefix}_{admin_id}"
    if temp_key in TEMP_INBOUND_SELECTION:
        current_list = TEMP_INBOUND_SELECTION[temp_key]
    else:
        current_list = current_inbound_ids.copy() if current_inbound_ids else []
        TEMP_INBOUND_SELECTION[temp_key] = current_list.copy()
    invalid_ids = [ib for ib in current_list if ib not in valid_ids]
    if invalid_ids:
        logger.warning(f"⚠️ [show_inbound_manager] invalid inbounds removed: {invalid_ids}")
        current_list = [ib for ib in current_list if ib in valid_ids]
        TEMP_INBOUND_SELECTION[temp_key] = current_list
    
    back_key = f"{callback_data_prefix}_{admin_id}_back"
    if back_callback is not None:
        existing_back = INBOUND_BACK_DATA.get(back_key, {})
        INBOUND_BACK_DATA[back_key] = {
            'back_callback': back_callback,
            'extra_data': extra_data if extra_data is not None else existing_back.get('extra_data', {}),
            'title': title or existing_back.get('title')
        }
    elif title and back_key in INBOUND_BACK_DATA:
        INBOUND_BACK_DATA[back_key]['title'] = title
    
    inbound_names = {}
    for ib in active_inbounds:
        inbound_id = ib.get('id')
        remark = ib.get('remark', f'ID:{inbound_id}')
        protocol = ib.get('protocol', '').upper()
        port = ib.get('port', '')
        inbound_names[inbound_id] = f"{remark} - {protocol}:{port}"
    
    text = t('b_b_click_each_inbound_to_se_8ab2435711', lang, fa_parts=lambda: (f'{title}', f'{len(current_list)}'), en_parts=lambda: (f'{title}', f'{len(current_list)}'))
    
    buttons = []
    for inbound in active_inbounds:
        inbound_id = inbound.get('id')
        ib_name = inbound_names.get(inbound_id, f"ID: {inbound_id}")
        
        is_selected = inbound_id in current_list
        
        if is_selected:
            label = f"✅ {ib_name}"
            style = "success"
        else:
            label = f"⬜ {ib_name}"
            style = None
        
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=InboundCB(action="toggle", prefix=callback_data_prefix, inbound_id=inbound_id).pack(),
            style=style
        )])
    
    action_buttons = []
    
    if show_default_button:
        default_ids = configs_pool.get('default_inbound_ids', [])
        if default_ids:
            action_buttons.append(
                InlineKeyboardButton(
                    text=t('select_default_ea628ae037', lang),
                    callback_data=InboundCB(action="default", prefix=callback_data_prefix).pack(),
                    style="primary"
                )
            )
    
    if show_clear_button:
        action_buttons.append(
            InlineKeyboardButton(
                text=t('clear_all_565e888195', lang),
                callback_data=InboundCB(action="clear", prefix=callback_data_prefix).pack(),
                style="danger"
            )
        )
    
    if action_buttons:
        buttons.append(action_buttons)
    buttons.append([InlineKeyboardButton(
        text=t('select_all_9792663d71', lang),
        callback_data=InboundCB(action="selectall", prefix=callback_data_prefix).pack(),
        style="success"
    )])
    
    save_buttons = [
        InlineKeyboardButton(
            text=t('save_3e015bf8c8', lang),
            callback_data=InboundCB(action="save", prefix=callback_data_prefix).pack(),
            style="success"
        )
    ]
    
    if back_callback:
        save_buttons.append(
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data=InboundCB(action="back", prefix=callback_data_prefix).pack(),
                style="danger"
            )
        )
    
    buttons.append(save_buttons)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    try:
        if update_existing:
            try:
                await message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            except Exception as e:
                if "message is not modified" in str(e):
                    try:
                        await message.edit_reply_markup(reply_markup=keyboard)
                    except Exception:
                        pass
                else:
                    raise
        else:
            await message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" not in str(e):
            try:
                await message.delete()
            except Exception:
                pass
            await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)            

@router.callback_query(InboundCB.filter(F.action == "selectall"))
@router.callback_query(F.data.startswith("inbound_selectall_"))
@admin_only
async def inbound_selectall(callback: CallbackQuery, callback_data: Optional[InboundCB] = None):
    """انتخاب همه اینباندها در صفحه مدیریت اینباند (عمومی)"""
    
    prefix = callback_data.prefix if callback_data else callback.data.replace("inbound_selectall_", "")
    temp_key = f"{prefix}_{callback.from_user.id}"
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    inbounds = await xui_get_inbounds()
    active_inbounds = [i for i in inbounds if i.get('enable', True)]
    all_ids = [i.get('id') for i in active_inbounds if i.get('id')]

    if not all_ids:
        await callback.answer(t('i18n_no_active_inbounds_alert', lang), show_alert=True)
        return

    TEMP_INBOUND_SELECTION[temp_key] = all_ids

    await callback.answer(t('i18n_selected_count', lang, fa_parts=lambda: (f'{len(all_ids)}',), en_parts=lambda: (f'{len(all_ids)}',)), show_alert=True)

    back_key = f"{prefix}_{callback.from_user.id}_back"
    back_info = INBOUND_BACK_DATA.get(back_key, {})
    extra_data = back_info.get('extra_data', {})
    saved_title = back_info.get('title') or t('i18n_manage_inbounds_title', lang)

    await show_inbound_manager(
        message=callback.message,
        title=saved_title,
        current_inbound_ids=all_ids,
        callback_data_prefix=prefix,
        back_callback=f"inbound_back_{prefix}",
        admin_id=callback.from_user.id,
        update_existing=True,
        extra_data=extra_data
    )
@router.callback_query(InboundCB.filter(F.action == "toggle"))
@router.callback_query(F.data.startswith("inbound_toggle_"))
@admin_only
async def inbound_toggle(callback: CallbackQuery, callback_data: Optional[InboundCB] = None):
    """تغییر وضعیت یک اینباند (عمومی)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    if callback_data:
        prefix = callback_data.prefix
        inbound_id = callback_data.inbound_id
    else:
        parts = callback.data.split("_")
        try:
            prefix_parts = parts[2:-1]
            prefix = "_".join(prefix_parts)
            inbound_id = int(parts[-1])
        except (ValueError, IndexError):
            await callback.answer(t('i18n_process_error', lang), show_alert=True)
            return

    temp_key = f"{prefix}_{callback.from_user.id}"
    if temp_key not in TEMP_INBOUND_SELECTION:
        await callback.answer(t('i18n_invalid_state', lang), show_alert=True)
        return

    current_list = TEMP_INBOUND_SELECTION[temp_key]

    if inbound_id in current_list:
        current_list.remove(inbound_id)
        await callback.answer(t('i18n_cancelled_one', lang), show_alert=False)
    else:
        current_list.append(inbound_id)
        await callback.answer(t('i18n_selected_one', lang), show_alert=False)
    
    TEMP_INBOUND_SELECTION[temp_key] = current_list
    
    back_key = f"{prefix}_{callback.from_user.id}_back"
    back_info = INBOUND_BACK_DATA.get(back_key, {})
    extra_data = back_info.get('extra_data', {})
    saved_title = back_info.get('title') or t('i18n_manage_inbounds_title', lang)
    
    await show_inbound_manager(
        message=callback.message,
        title=saved_title,
        current_inbound_ids=current_list,
        callback_data_prefix=prefix,
        back_callback=f"inbound_back_{prefix}",
        admin_id=callback.from_user.id,
        update_existing=True,
        extra_data=extra_data
    )


@router.callback_query(InboundCB.filter(F.action == "default"))
@router.callback_query(F.data.startswith("inbound_default_"))
@admin_only
async def inbound_default(callback: CallbackQuery, callback_data: Optional[InboundCB] = None):
    """انتخاب اینباندهای پیش‌فرض (عمومی)"""
    
    prefix = callback_data.prefix if callback_data else callback.data.replace("inbound_default_", "")
    temp_key = f"{prefix}_{callback.from_user.id}"
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    default_ids = configs_pool.get('default_inbound_ids', [])
    if default_ids:
        TEMP_INBOUND_SELECTION[temp_key] = default_ids.copy()
        await callback.answer(t('i18n_default_inbounds_selected', lang, fa_parts=lambda: (f'{len(default_ids)}',), en_parts=lambda: (f'{len(default_ids)}',)), show_alert=True)
    else:
        await callback.answer(t('i18n_no_default_inbounds_set', lang), show_alert=True)
        return
    
    current_list = TEMP_INBOUND_SELECTION[temp_key]
    
    back_key = f"{prefix}_{callback.from_user.id}_back"
    back_info = INBOUND_BACK_DATA.get(back_key, {})
    extra_data = back_info.get('extra_data', {})
    saved_title = back_info.get('title') or t('i18n_manage_inbounds_title', lang)
    
    await show_inbound_manager(
        message=callback.message,
        title=saved_title,
        current_inbound_ids=current_list,
        callback_data_prefix=prefix,
        back_callback=f"inbound_back_{prefix}",
        admin_id=callback.from_user.id,
        update_existing=True,
        extra_data=extra_data
    )



@router.callback_query(InboundCB.filter(F.action == "clear"))
@router.callback_query(F.data.startswith("inbound_clear_"))
@admin_only
async def inbound_clear(callback: CallbackQuery, callback_data: Optional[InboundCB] = None):
    """پاک کردن همه اینباندها (عمومی)"""
    
    prefix = callback_data.prefix if callback_data else callback.data.replace("inbound_clear_", "")
    temp_key = f"{prefix}_{callback.from_user.id}"
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    TEMP_INBOUND_SELECTION[temp_key] = []

    await callback.answer(t('i18n_cleared_all_inbounds', lang), show_alert=True)
    
    back_key = f"{prefix}_{callback.from_user.id}_back"
    back_info = INBOUND_BACK_DATA.get(back_key, {})
    extra_data = back_info.get('extra_data', {})
    saved_title = back_info.get('title') or t('i18n_manage_inbounds_title', lang)
    
    await show_inbound_manager(
        message=callback.message,
        title=saved_title,
        current_inbound_ids=[],
        callback_data_prefix=prefix,
        back_callback=f"inbound_back_{prefix}",
        admin_id=callback.from_user.id,
        update_existing=True,
        extra_data=extra_data
    )


@router.callback_query(InboundCB.filter(F.action == "back"))
@router.callback_query(F.data.startswith("inbound_back_"))
@admin_only
async def inbound_back(callback: CallbackQuery, callback_data: Optional[InboundCB] = None):
    """انصراف و برگشت به صفحه قبل (عمومی)"""
    
    prefix = callback_data.prefix if callback_data else callback.data.replace("inbound_back_", "")
    temp_key = f"{prefix}_{callback.from_user.id}"
    
    if temp_key in TEMP_INBOUND_SELECTION:
        del TEMP_INBOUND_SELECTION[temp_key]
    
    back_key = f"{prefix}_{callback.from_user.id}_back"
    back_info = INBOUND_BACK_DATA.get(back_key, {})
    extra_data = back_info.get('extra_data', {})
    
    if back_key in INBOUND_BACK_DATA:
        del INBOUND_BACK_DATA[back_key]
    
    await safe_answer(callback, t('i18n_cancelled', get_user(callback.from_user.id).get('lang', 'fa')), alert=True)
    
    try:
        if "category" in prefix:
            category_id = extra_data.get('category_id')
            if not category_id and "_" in prefix:
                try:
                    category_id = int(prefix.split("_")[-1])
                except Exception:
                    pass
            if category_id:
                await go_back_to_category_edit(callback, category_id)
            else:
                await go_back_to_admin_panel(callback)
                
        elif "test" in prefix:
            await go_back_to_test_service(callback)
            
        else:
            await go_back_to_admin_panel(callback)
            
    except Exception as e:
        logger.error(f"Error refunding: {e}")
        try:
            await go_back_to_admin_panel(callback)
        except Exception:
            pass


@router.callback_query(InboundCB.filter(F.action == "save"))
@router.callback_query(F.data.startswith("inbound_save_"))
@admin_only
async def inbound_save(callback: CallbackQuery, callback_data: Optional[InboundCB] = None):
    """ذخیره تنظیمات اینباندها (عمومی)"""
    
    prefix = callback_data.prefix if callback_data else callback.data.replace("inbound_save_", "")
    temp_key = f"{prefix}_{callback.from_user.id}"
    
    if temp_key not in TEMP_INBOUND_SELECTION:
        await safe_answer(callback, t('i18n_no_changes_found', get_user(callback.from_user.id).get('lang', 'fa')), alert=True)
        return
    
    current_list = TEMP_INBOUND_SELECTION[temp_key]
    
    back_key = f"{prefix}_{callback.from_user.id}_back"
    back_info = INBOUND_BACK_DATA.get(back_key, {})
    extra_data = back_info.get('extra_data', {})
    
    if temp_key in TEMP_INBOUND_SELECTION:
        del TEMP_INBOUND_SELECTION[temp_key]
    if back_key in INBOUND_BACK_DATA:
        del INBOUND_BACK_DATA[back_key]
    
    await safe_answer(callback, t('i18n_saved_count', get_user(callback.from_user.id).get('lang', 'fa'), fa_parts=lambda: (f'{len(current_list)}',), en_parts=lambda: (f'{len(current_list)}',)), alert=True)
        
    try:
        if "category" in prefix:
            category_id = extra_data.get('category_id')
            if not category_id and "_" in prefix:
                try:
                    category_id = int(prefix.split("_")[-1])
                except Exception:
                    pass
            if category_id:
                for cat in READY_PACKAGES.get('categories', []):
                    if cat.get('id') == category_id:
                        cat['inbound_ids'] = current_list
                        cat['inbound_id'] = None
                        break
                READY_PACKAGES['last_updated'] = now_tehran_iso()
                configs_pool['ready_packages'] = READY_PACKAGES
                schedule_save(2.0)
                
                await go_back_to_category_edit(callback, category_id)
            else:
                await go_back_to_admin_panel(callback)
                
        elif "test" in prefix:
            update_test_settings(inbound_ids=current_list)
            
            await go_back_to_test_service(callback)
            
        else:
            await go_back_to_admin_panel(callback)
            
    except Exception as e:
        logger.error(f"Error saving or refunding: {e}")
        try:
            await go_back_to_admin_panel(callback)
        except Exception:
            pass

@router.callback_query(F.data == "admin_test_inbounds")
@admin_only
async def admin_test_inbounds(callback: CallbackQuery):
    """تنظیم اینباندهای تست"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    current_inbound_ids = TEST_SERVICE_STATUS.get('inbound_ids', [])
    prefix = "test_service"
    
    back_key = f"{prefix}_{callback.from_user.id}_back"
    INBOUND_BACK_DATA[back_key] = {
        'back_callback': "admin_test_service",
        'extra_data': {}
    }
    
    await show_inbound_manager(
        message=callback.message,
        title=t('i18n_test_inbounds_manager_title', lang),
        current_inbound_ids=current_inbound_ids,
        callback_data_prefix=prefix,
        back_callback=f"inbound_back_{prefix}",
        admin_id=callback.from_user.id,
        show_default_button=True,
        show_clear_button=True,
        update_existing=False,
        extra_data={}
    )

async def go_back_to_category_edit(callback: CallbackQuery, category_id: int):
    """برگشت به صفحه ویرایش دسته با حذف پیام و ارسال جدید"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        await callback.message.delete()
    except Exception as e:
        logger.warning(f"Error deleting message: {e}")
        try:
            await callback.message.edit_text(t('i18n_returning', lang))
        except Exception:
            pass

    try:
        await callback.message.answer(
            t('i18n_back_to_category_editing', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_to_category_edit_435f56520d', lang),
                    callback_data=f"admin_category_edit_{category_id}",
                    style="primary"
                )]
            ])
        )
    except Exception as e:
        logger.error(f"Error sending refund message: {e}")
        try:
            await admin_category_edit(callback.model_copy(update={"data": f"admin_category_edit_{category_id}"}))
        except Exception:
            pass


async def go_back_to_test_service(callback: CallbackQuery):
    """برگشت به صفحه تنظیمات تست"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        await callback.message.delete()
    except Exception as e:
        logger.warning(f"Error deleting message: {e}")
        try:
            await callback.message.edit_text(t('i18n_returning', lang))
        except Exception:
            pass

    try:
        await callback.message.answer(
            t('i18n_back_to_test_settings_loading', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_to_test_settings_6faf000080', lang),
                    callback_data="admin_test_service",
                    style="primary"
                )]
            ])
        )
    except Exception as e:
        logger.error(f"Error sending refund message: {e}")
        try:
            await admin_test_service_settings(callback.model_copy(update={"data": "admin_test_service"}))
        except Exception:
            pass


async def go_back_to_admin_panel(callback: CallbackQuery):
    """برگشت به پنل ادمین"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        await callback.message.delete()
    except Exception as e:
        logger.warning(f"Error deleting message: {e}")
        try:
            await callback.message.edit_text(t('i18n_returning', lang))
        except Exception:
            pass

    try:
        await callback.message.answer(
            t('i18n_back_to_admin_panel_loading', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_to_admin_panel_676a1cf43f', lang),
                    callback_data="admin_panel",
                    style="primary"
                )]
            ])
        )
    except Exception as e:
        logger.error(f"Error sending refund message: {e}")
        try:
            await admin_panel(callback.model_copy(update={"data": "admin_panel"}))
        except Exception:
            pass
    
    
@router.callback_query(F.data == "admin_test_toggle")
@admin_only
async def admin_test_toggle(callback: CallbackQuery):
    """فعال/غیرفعال کردن تست سرویس"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    new_status = not TEST_SERVICE_STATUS.get('enabled', False)
    update_test_settings(enabled=new_status)
    
    status = t('i18n_status_active', lang) if new_status else t('i18n_status_inactive', lang)
    await callback.answer(t('test_service_d_8596b6469d', lang, fa_parts=lambda: (f'{status}',), en_parts=lambda: (f'{status}',)), show_alert=True)
    
    await admin_test_service_settings(callback)


@router.callback_query(F.data.startswith("admin_test_edit_"))
@admin_only
async def admin_test_edit_start(callback: CallbackQuery):
    """شروع ویرایش تنظیمات تست"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    setting_type = callback.data.replace("admin_test_edit_", "")
    
    setting_map = {
        'volume': {'key': 'volume', 'label': t('test_volume_mb_9f5acacd02', lang), 'current': TEST_SERVICE_STATUS.get('volume_mb', 1024)},
        'days': {'key': 'days', 'label': t('test_duration_days_ae3ef9b0c5', lang), 'current': TEST_SERVICE_STATUS.get('days', 3)},
        'max': {'key': 'max_tests', 'label': t('max_tests_per_user_d3e96c46f4', lang), 'current': TEST_SERVICE_STATUS.get('max_tests', 1)},
        'message': {'key': 'message', 'label': t('test_message_c27f747183', lang), 'current': TEST_SERVICE_STATUS.get('message', '')},
        'ip_limit': {'key': 'ip_limit', 'label': t('ip_limit_4cbb9d738f', lang), 'current': TEST_SERVICE_STATUS.get('ip_limit', 0)}
    }
    
    if setting_type not in setting_map:
        await callback.answer(t('i18n_invalid_settings_short', lang), show_alert=True)
        return
    
    setting_info = setting_map[setting_type]
    current_display = setting_info['current']
    
    if setting_type == 'ip_limit':
        current_display = "نامحدود" if current_display == 0 else current_display
    if setting_type == 'volume':
        current_display = f"{current_display:,} MB" if current_display > 0 else "نامحدود"
    
    user_states[callback.from_user.id] = {
        'awaiting_test_edit': True,
        'test_setting': setting_type
    }
    
    hint = ""
    if setting_type == 'volume':
        hint = t('10_10_mb_0_unlimited_6832c347c0', lang)
    elif setting_type == 'ip_limit':
        hint = t('0_unlimited_1_only_one_devic_22815bc8f3', lang)
    elif setting_type != 'message':
        hint = t('e_g_10_f1b729efa7', lang)

    await callback.message.answer(
        t('b_edit_b_current_value_code_1c3935cc74', lang, fa_parts=lambda: (f"{setting_info['label']}", f'{current_display}', f'{hint}'), en_parts=lambda: (f"{setting_info['label']}", f'{current_display}', f'{hint}')),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)


def validate_test_volume(mb: int) -> Tuple[bool, Optional[str]]:
    """
    اعتبارسنجی حجم سرویس تست (بر حسب مگابایت).
    mb == 0: نامحدود (مجاز)
    mb < 0 یا 0 < mb < 10: غیرمجاز (حداقل ۱۰ مگابایت)
    mb > 51200: غیرمجاز (حداکثر ۵۰ گیگابایت / ۵۱۲۰۰ مگابایت)
    10 <= mb <= 51200: مجاز
    خروجی: (is_valid, error_translation_key)
    """
    if mb < 0 or (0 < mb < 10):
        return False, 'minimum_test_volume_is_10_mb_18473c4a4c'
    if mb > 51200:
        return False, 'test_volume_cannot_exceed_50_0e55621fcc'
    return True, None


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_test_edit'))
async def admin_test_edit_save(message: Message):
    """ذخیره تنظیمات تست"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_68c51319f6', lang))
        return
    
    state = user_states.get(admin_id, {})
    setting_type = state.get('test_setting')
    
    if not setting_type:
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_invalid_state', lang))
        return
    
    key_map = {
        'volume': 'volume_mb',
        'days': 'days',
        'max': 'max_tests',
        'message': 'message',
        'ip_limit': 'ip_limit'
    }
    
    db_key = key_map.get(setting_type)
    if not db_key:
        await message.reply(t('i18n_invalid_key', lang))
        user_states.pop(admin_id, None)
        return
    
    try:
        if setting_type == 'message':
            new_value = message.text.strip()
            if not new_value:
                await message.reply(t('message_cannot_be_empty_9669d7f21e', lang))
                return
        
        elif setting_type == 'volume':
            new_value_mb = int(message.text.replace(',', '').replace(' ', '').strip())
            is_valid, err_key = validate_test_volume(new_value_mb)
            if not is_valid:
                await message.reply(t(err_key, lang))
                return
            
            if new_value_mb == 0:
                update_test_settings(volume_mb=0, volume=0)
                await message.reply(t('test_volume_set_to_b_unlimit_c2be0621b2', lang))
            else:
                new_value_gb = new_value_mb / 1024
                update_test_settings(volume_mb=new_value_mb, volume=round(new_value_gb, 3))
                await message.reply(t('test_volume_set_to_mb_gb_c8b136a277', lang, fa_parts=lambda: (f'{new_value_mb:,}', f'{round(new_value_gb, 3)}'), en_parts=lambda: (f'{new_value_mb:,}', f'{round(new_value_gb, 3)}')))
            
            user_states.pop(admin_id, None)
            await admin_test_service_settings_message(message)
            return
        
        elif setting_type == 'ip_limit':
            new_value = int(message.text.replace(',', '').replace(' ', '').strip())
            
            if new_value < 0:
                await message.reply(t('ip_limit_cannot_be_negative_bbfec924e0', lang))
                return
            
            if new_value > 999:
                await message.reply(t('ip_limit_cannot_exceed_999_0457e797b9', lang))
                return
            
            update_test_settings(ip_limit=new_value)
            
            if new_value == 0:
                await message.reply(t('ip_limit_set_to_b_unlimited_02a87c414f', lang))
            else:
                await message.reply(t('ip_limit_set_to_devices_bf4890c91d', lang, fa_parts=lambda: (f'{new_value}',), en_parts=lambda: (f'{new_value}',)))
            
            user_states.pop(admin_id, None)
            await admin_test_service_settings_message(message)
            return
        
        else:
            new_value = int(message.text.replace(',', '').replace(' ', '').strip())
            
            if new_value <= 0:
                await message.reply(t('value_must_be_greater_than_z_0770671136', lang))
                return
            
            if setting_type == 'days' and new_value > 30:
                await message.reply(t('test_duration_cannot_exceed_38659b5326', lang))
                return
            elif setting_type == 'max' and new_value > 5:
                await message.reply(t('max_tests_per_user_cannot_ex_e6076362a2', lang))
                return
        
        old_value = TEST_SERVICE_STATUS.get(db_key)
        update_test_settings(**{db_key: new_value})
        
        await message.reply(t('settings_updated_new_value_c_f05f1ab6b8', lang, fa_parts=lambda: (f'{new_value}',), en_parts=lambda: (f'{new_value}',)), parse_mode=ParseMode.HTML)
        
        user_states.pop(admin_id, None)
        await admin_test_service_settings_message(message)
        
    except ValueError:
        await message.reply(t('please_enter_a_valid_number_afbbd0c0b3', lang))
    except Exception as e:
        logger.error(f"Error in save_test_edit: {e}", exc_info=True)
        err_type = html.escape(type(e).__name__)
        await message.reply(t('i18n_error_prefix', lang, fa_parts=lambda: (err_type,), en_parts=lambda: (err_type,)))
        user_states.pop(admin_id, None)

async def admin_test_service_settings_message(message: Message):
    """تنظیمات تست سرویس - نسخه مخصوص Message"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    lang = get_user(message.from_user.id).get('lang', 'fa')
    text, kb = await build_admin_test_service_content(lang)
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
        
_test_users_cache = {
    'time': 0.0,
    'total_tests': 0,
    'users': []
}
_TEST_USERS_CACHE_TTL = 60.0  # 60 ثانیه


def invalidate_test_users_cache() -> None:
    """باطل کردن کش آمار و لیست مرتب‌شده کاربران تست"""
    _test_users_cache['time'] = 0.0
    _test_users_cache['users'] = []
    _test_users_cache['total_tests'] = 0


def get_cached_sorted_test_users(ttl: float = _TEST_USERS_CACHE_TTL) -> tuple[int, list[dict]]:
    """دریافت لیست مرتب‌شده کاربران تست با کش ۶۰ ثانیه‌ای برای بهینه‌سازی پرفورمنس"""
    now = time.monotonic()
    if _test_users_cache['users'] and (now - _test_users_cache['time'] < ttl):
        return _test_users_cache['total_tests'], _test_users_cache['users']

    total_tests = 0
    test_users = []
    unknown_label = "نامشخص"
    for uid, data in USER_TEST_USAGE.items():
        count = data.get('count', 0)
        total_tests += count
        user_info = get_user_safe(uid)
        raw_name = user_info.get('name', f'کاربر_{uid}') if user_info else f'کاربر_{uid}'
        name_escaped = safe_html(raw_name)
        test_users.append({
            'id': uid,
            'name': name_escaped,
            'count': count,
            'last_test': data.get('last_test', unknown_label),
            'last_order_id': data.get('last_order_id', unknown_label)
        })
    test_users.sort(key=lambda x: x['count'], reverse=True)

    _test_users_cache['time'] = now
    _test_users_cache['total_tests'] = total_tests
    _test_users_cache['users'] = test_users
    return total_tests, test_users


@router.callback_query(F.data == "admin_test_users")
@admin_only
async def admin_test_users(callback: CallbackQuery):
    """مدیریت تست کاربران"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    total_test_users = len(USER_TEST_USAGE)
    total_bot_users = len(users)  # تعداد کل کاربران ربات

    total_tests, top_users = get_cached_sorted_test_users()

    text = t('b_test_users_management_b_to_c7db265318', lang, fa_parts=lambda: (f'{total_bot_users}', f'{total_test_users}', f'{total_tests}'), en_parts=lambda: (f'{total_bot_users}', f'{total_test_users}', f'{total_tests}'))
    for i, user in enumerate(top_users[:10], 1):
        text += t('tests_0ac703c94b', lang, fa_parts=lambda: (f'{i}', f"{user['name']}", f"{user['count']}"), en_parts=lambda: (f'{i}', f"{user['name']}", f"{user['count']}"))

    if not top_users:
        text += t('no_users_have_taken_a_test_dd263a9770', lang)

    text += t('b_actions_b_28354ee766', lang)
    buttons = [
        [InlineKeyboardButton(text=t('reset_single_user_test_ac508793b6', lang), callback_data="admin_test_user_reset", style="primary")],
        [InlineKeyboardButton(text=t('test_users_list_e47e35f4d9', lang), callback_data="admin_test_users_list")],
        [InlineKeyboardButton(text=t('set_all_users_test_settings_3fc0ee4006', lang), callback_data="admin_test_all_users_settings", style="primary")],
        [InlineKeyboardButton(text=t('reset_all_users_tests_4fdafcae84', lang), callback_data="admin_test_users_reset_all", style="danger")],
        [InlineKeyboardButton(text=t('back_to_test_service_d7ce21a54e', lang), callback_data="admin_test_service")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)

@router.callback_query(F.data == "admin_test_all_users_settings")
@admin_only
async def admin_test_all_users_settings(callback: CallbackQuery):
    """تنظیم تست برای همه کاربران"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    total_users = len(users)
    users_with_test = len(USER_TEST_USAGE)
    
    text = t('b_set_all_users_test_setting_ecc40cd79e', lang, fa_parts=lambda: (f'{total_users}', f'{users_with_test}', f"{TEST_SERVICE_STATUS.get('volume', 5)}", f"{TEST_SERVICE_STATUS.get('days', 3)}", f"{TEST_SERVICE_STATUS.get('max_tests', 1)}"), en_parts=lambda: (f'{total_users}', f'{users_with_test}', f"{TEST_SERVICE_STATUS.get('volume', 5)}", f"{TEST_SERVICE_STATUS.get('days', 3)}", f"{TEST_SERVICE_STATUS.get('max_tests', 1)}"))
    buttons = [
        [InlineKeyboardButton(text=t('set_test_for_specific_user_1a602964a0', lang), callback_data="admin_test_user_select")],
        [InlineKeyboardButton(text=t('set_test_for_all_new_users_a1e952f4b3', lang), callback_data="admin_test_set_default")],
        [InlineKeyboardButton(text=t('view_users_with_custom_test_7fc7a508ca', lang), callback_data="admin_test_users_with_settings")],
        [InlineKeyboardButton(text=t('clear_all_custom_test_settin_1d7452661b', lang), callback_data="admin_test_clear_all_settings", style="danger")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_test_users")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)
        

@router.callback_query(F.data == "admin_test_user_select")
@admin_only
async def admin_test_user_select(callback: CallbackQuery):
    """انتخاب کاربر برای تنظیم تست"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {'awaiting_test_user_select': True}
    
    text = t('b_select_user_for_test_setti_26dc042017', lang)
    buttons = [
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_test_all_users_settings")]
    ]
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await safe_answer(callback)
        
        
@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_test_user_select'))
async def admin_test_user_select_execute(message: Message):
    """دریافت آیدی کاربر و نمایش تنظیمات"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(
            t('cancelled_8a3eb8aae6', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_test_all_users_settings")]
            ])
        )
        return
    
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.reply(
            t('please_enter_a_valid_numeric_d834b6b50e', lang)
        )
        return
    user_info = await get_user_info_from_telegram(target_id)
    
    if str(target_id) not in users:
        await message.reply(
            t('user_id_not_found_da099be213', lang, fa_parts=lambda: (f"{user_info['full_name']}", f'{target_id}'), en_parts=lambda: (f"{user_info['full_name']}", f'{target_id}')),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('try_again_4d08fd2838', lang), callback_data="admin_test_user_select")],
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_test_all_users_settings")]
            ])
        )
        user_states.pop(admin_id, None)
        return
    
    user_states.pop(admin_id, None)
    text, reply_markup = await build_user_test_settings_content(target_id, lang)
    await message.reply(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    
@router.callback_query(F.data == "admin_test_set_default")
@admin_only
async def admin_test_set_default(callback: CallbackQuery):
    """تنظیم تست پیش‌فرض برای همه کاربران جدید"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {
        'awaiting_default_test_setting': True,
        'setting_type': 'default'
    }
    
    text = t('b_set_default_test_for_new_u_716d27f3c9', lang, fa_format_args=lambda: ((), {'volume': TEST_SERVICE_STATUS.get('volume', 5), 'days': TEST_SERVICE_STATUS.get('days', 3), 'max_tests': TEST_SERVICE_STATUS.get('max_tests', 1)}), en_format_args=lambda: ((), {'volume': TEST_SERVICE_STATUS.get('volume', 5), 'days': TEST_SERVICE_STATUS.get('days', 3), 'max_tests': TEST_SERVICE_STATUS.get('max_tests', 1)}))
    
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)
    await safe_answer(callback)
        
        
@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_default_test_setting'))
async def admin_test_set_default_save(message: Message):
    """ذخیره تنظیمات پیش‌فرض تست"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(
            t('cancelled_8a3eb8aae6', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_test_all_users_settings")]
            ])
        )
        return
    
    try:
        parts = message.text.split('|')
        if len(parts) != 3:
            await message.reply(
                t('invalid_format_please_use_vo_00f5c82638', lang)
            )
            return
        
        volume = int(parts[0].strip())
        days = int(parts[1].strip())
        max_tests = int(parts[2].strip())
        if volume < 1 or volume > 100:
            await message.reply(
                t('volume_must_be_between_1_and_aefa9c9c84', lang)
            )
            return
        if days < 1 or days > 30:
            await message.reply(
                t('duration_must_be_between_1_a_e04edad609', lang)
            )
            return
        if max_tests < 1 or max_tests > 10:
            await message.reply(
                t('max_tests_must_be_between_1_01e41fb0f0', lang)
            )
            return
        update_test_settings(
            volume=volume,
            volume_mb=volume * 1024,
            days=days,
            max_tests=max_tests
        )
        
        user_states.pop(admin_id, None)
        
        await message.reply(
            t('default_test_settings_update_5869dea055', lang, fa_parts=lambda: (f'{volume}', f'{days}', f'{max_tests}'), en_parts=lambda: (f'{volume}', f'{days}', f'{max_tests}')),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_test_all_users_settings")]
            ])
        )
        
    except ValueError:
        await message.reply(
            t('please_enter_valid_numbers_7688d100c1', lang)
        )
    except Exception as e:
        logger.error(f"Error saving default settings: {e}", exc_info=True)
        err_type = html.escape(type(e).__name__)
        await message.reply(t('i18n_error_prefix', lang, fa_parts=lambda: (err_type,), en_parts=lambda: (err_type,)))
        user_states.pop(admin_id, None)
        
        
@router.callback_query(AdminTestPageCB.filter(F.kind == "settings"))
@router.callback_query(F.data == "admin_test_users_with_settings")
@admin_only
async def admin_test_users_with_settings(callback: CallbackQuery, callback_data: AdminTestPageCB = None):
    """نمایش لیست کاربران با تست اختصاصی همراه با صفحه‌بندی"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not USER_TEST_SETTINGS:
        await callback.answer(
            t('no_users_have_custom_test_se_4fe0b041c6', lang),
            show_alert=True
        )
        return

    page = 0
    if callback_data is not None:
        page = callback_data.page
    elif callback.data and callback.data.startswith("admin_test_settings_page_"):
        try:
            page = int(callback.data.split("_")[-1])
        except Exception:
            page = 0
    
    users_list = []
    for uid, settings in USER_TEST_SETTINGS.items():
        user_info = get_user_safe(uid)
        fallback_name = t('i18n_user_fallback_name', lang, fa_parts=lambda: (f'{uid}',), en_parts=lambda: (f'{uid}',))
        raw_name = user_info.get('name', fallback_name) if user_info else fallback_name
        name = safe_html(raw_name)
        users_list.append({
            'id': uid,
            'name': name,
            'settings': settings
        })

    PAGE_SIZE = 15
    total = len(users_list)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total)
    page_items = users_list[start_idx:end_idx]

    text = t('b_users_with_custom_test_set_bf9ea4c4df', lang, fa_parts=lambda: (f'{total}',), en_parts=lambda: (f'{total}',))
    if total_pages > 1:
        text += f"\n📄 <i>(صفحه {page + 1} از {total_pages})</i>\n"

    for idx, user in enumerate(page_items, start=start_idx + 1):
        settings = user['settings']
        text += t('i18n_user_test_settings_line', lang, fa_parts=lambda: (f'{idx}', f"{user['name']}", f"{user['id']}", f"{settings.get('volume', 5)}", f"{settings.get('days', 3)}", f"{settings.get('max_tests', 1)}"), en_parts=lambda: (f'{idx}', f"{user['name']}", f"{user['id']}", f"{settings.get('volume', 5)}", f"{settings.get('days', 3)}", f"{settings.get('max_tests', 1)}"))

    buttons = []
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text=t('prev_ad2dbc546b', lang),
                callback_data=AdminTestPageCB(kind="settings", page=page - 1).pack()
            ))
        nav.append(InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data="noop"
        ))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(
                text=t('next_c99400f27f', lang),
                callback_data=AdminTestPageCB(kind="settings", page=page + 1).pack()
            ))
        if nav:
            buttons.append(nav)

    buttons.append([InlineKeyboardButton(
        text=t('clear_all_custom_settings_d0ccaf008b', lang),
        callback_data="admin_test_clear_all_settings",
        style="danger"
    )])
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_test_all_users_settings"
    )])
    
    if len(text) > 4000:
        file_buffer = BytesIO()
        file_buffer.write(text.encode('utf-8'))
        file_buffer.seek(0)
        
        filename = f"custom_test_users_{now_tehran().strftime('%Y%m%d_%H%M%S')}.txt"
        input_file = BufferedInputFile(file_buffer.read(), filename=filename)
        
        await callback.message.delete()
        await callback.message.answer_document(
            document=input_file,
            caption=t('users_with_custom_test_15f3b95c7e', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    else:
        try:
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except Exception as e:
            logger.debug(f"Failed to edit message in admin_test_users_with_settings, sending new: {e}")
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    
    await safe_answer(callback)
        
        
@router.callback_query(F.data == "admin_test_clear_all_settings")
@admin_only
async def admin_test_clear_all_settings_confirm(callback: CallbackQuery):
    """تأیید پاک کردن همه تنظیمات اختصاصی"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    count = len(USER_TEST_SETTINGS)
    
    if count == 0:
        await callback.answer(
            t('no_custom_settings_exist_653d130992', lang),
            show_alert=True
        )
        return
    
    text = t('b_warning_clear_all_custom_t_4ff8c6f7b7', lang, fa_parts=lambda: (f'{count}',), en_parts=lambda: (f'{count}',))
    buttons = [
        [
            InlineKeyboardButton(text=t('yes_clear_570ddad2aa', lang), callback_data="admin_test_clear_all_settings_execute", style="danger"),
            InlineKeyboardButton(text=t('cancel_4197bafba5', lang), callback_data="admin_test_all_users_settings")
        ]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)
        



@router.callback_query(F.data == "admin_test_clear_all_settings_execute")
@admin_only
async def admin_test_clear_all_settings_execute(callback: CallbackQuery):
    """اجرای پاک کردن همه تنظیمات اختصاصی"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    count = len(USER_TEST_SETTINGS)
    USER_TEST_SETTINGS.clear()
    save_user_test_settings()
    
    await callback.answer(
        t('custom_settings_cleared_aafcc9491e', lang, fa_parts=lambda: (f'{count}',), en_parts=lambda: (f'{count}',)),
        show_alert=True
    )
    await admin_test_all_users_settings(callback)
    
    
    
        
@router.callback_query(F.data == "admin_test_user_reset")
@admin_only
async def admin_test_user_reset_start(callback: CallbackQuery):
    """شروع فرآیند ریست تست یک کاربر"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    user_states[callback.from_user.id] = {'awaiting_test_user_id': True}
    
    text = t('b_reset_single_user_test_b_p_b48bb97ba7', lang)
    buttons = [
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_test_users")]
    ]
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await safe_answer(callback)
        
@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_test_user_id'))
async def admin_test_user_reset_execute(message: Message):
    """اجرای ریست تست یک کاربر"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(
            t('cancelled_8a3eb8aae6', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('test_management_a32a02bd26', lang), callback_data="admin_test_users")]
            ])
        )
        return
    
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.reply(
            t('please_enter_a_valid_numeric_d834b6b50e', lang)
        )
        return
    uid = str(target_id)
    user_info = await get_user_info_from_telegram(target_id)
    user_full_name = user_info.get('full_name', f'کاربر_{target_id}')
    
    if uid not in USER_TEST_USAGE:
        await message.reply(
            t('user_id_has_no_tests_ed425396b7', lang, fa_parts=lambda: (f'{user_full_name}', f'{target_id}'), en_parts=lambda: (f'{user_full_name}', f'{target_id}')),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('try_again_4d08fd2838', lang), callback_data="admin_test_user_reset")],
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_test_users")]
            ])
        )
        user_states.pop(admin_id, None)
        return
    old_data = USER_TEST_USAGE[uid].copy()
    old_count = old_data.get('count', 0)
    del USER_TEST_USAGE[uid]
    save_test_usage()
    invalidate_test_users_cache()
    logger.info(f"🗑 test reset for user {target_id} ({user_info.get('full_name_raw', user_full_name)}) with {old_count} test reset")
    
    if log_system:
        await log_system.log_admin_action(
            admin_id,
            "Reset user test service",
            target_user=target_id,
            details=f"Deleted test services: {old_count}"
        )
    
    if lang == "fa":
        text = t('b_user_test_reset_successful_b32e1334fb', lang, fa_parts=lambda: (f'{target_id}', f'{user_full_name}', f'{old_count}'))
        buttons = [
            [InlineKeyboardButton(text=t('reset_another_user_c172353798', lang), callback_data="admin_test_user_reset")],
            [InlineKeyboardButton(text=t('test_users_list_884e4cd9a1', lang), callback_data="admin_test_users_list")],
            [InlineKeyboardButton(text=t('back_to_management_7403a6db3c', lang), callback_data="admin_test_users")]
        ]
    else:
        text = t('b_user_test_reset_successful_b32e1334fb', lang, en_parts=lambda: (f'{target_id}', f'{user_full_name}', f'{old_count}'))
        buttons = [
            [InlineKeyboardButton(text=t('reset_another_user_c172353798', lang), callback_data="admin_test_user_reset")],
            [InlineKeyboardButton(text=t('test_users_list_884e4cd9a1', lang), callback_data="admin_test_users_list")],
            [InlineKeyboardButton(text=t('back_to_management_7403a6db3c', lang), callback_data="admin_test_users")]
        ]
    
    await message.reply(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
    user_states.pop(admin_id, None)
    
    
    

@router.callback_query(AdminTestPageCB.filter(F.kind == "list"))
@router.callback_query(F.data == "admin_test_users_list")
@admin_only
async def admin_test_users_list(callback: CallbackQuery, callback_data: AdminTestPageCB = None):
    """نمایش لیست کامل کاربران تست‌دهنده با امکان تنظیمات و صفحه‌بندی"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not USER_TEST_USAGE:
        await callback.answer(
            t('no_users_have_taken_a_test_042b886fe7', lang),
            show_alert=True
        )
        return

    page = 0
    if callback_data is not None:
        page = callback_data.page
    elif callback.data and callback.data.startswith("admin_test_list_page_"):
        try:
            page = int(callback.data.split("_")[-1])
        except Exception:
            page = 0

    _, test_users = get_cached_sorted_test_users()

    PAGE_SIZE = 10
    total = len(test_users)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total)
    page_items = test_users[start_idx:end_idx]

    text = t('b_full_list_of_test_users_b_37a0682423', lang, fa_parts=lambda: (f'{total}',), en_parts=lambda: (f'{total}',))
    if total_pages > 1:
        text += f"\n📄 <i>(صفحه {page + 1} از {total_pages})</i>\n"

    for idx, user in enumerate(page_items, start=start_idx + 1):
        text += t('i18n_test_user_list_line', lang, fa_parts=lambda: (f'{idx}', f"{user['name']}", f"{user['id']}", f"{user['count']}"), en_parts=lambda: (f'{idx}', f"{user['name']}", f"{user['id']}", f"{user['count']}"))
        if user['last_test']:
            text += t('i18n_last_test_line', lang, fa_parts=lambda: (f"{user['last_test'][:16]}",), en_parts=lambda: (f"{user['last_test'][:16]}",))
        text += "\n"

    buttons = []
    for user in page_items:
        buttons.append([InlineKeyboardButton(
            text=t('i18n_settings_button', lang, fa_parts=lambda: (f"{user['name']}", f"{user['id']}"), en_parts=lambda: (f"{user['name']}", f"{user['id']}")),
            callback_data=f"admin_test_user_settings_{user['id']}",
            style="primary"
        )])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text=t('prev_ad2dbc546b', lang),
                callback_data=AdminTestPageCB(kind="list", page=page - 1).pack()
            ))
        nav.append(InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data="noop"
        ))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(
                text=t('next_c99400f27f', lang),
                callback_data=AdminTestPageCB(kind="list", page=page + 1).pack()
            ))
        if nav:
            buttons.append(nav)

    buttons.append([InlineKeyboardButton(
        text=t('reset_single_user_d8b4c2bd04', lang),
        callback_data="admin_test_user_reset"
    )])
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_test_users"
    )])
    if len(text) > 4000:
        file_buffer = BytesIO()
        file_buffer.write(text.encode('utf-8'))
        file_buffer.seek(0)
        
        filename = f"test_users_{now_tehran().strftime('%Y%m%d_%H%M%S')}.txt"
        input_file = BufferedInputFile(file_buffer.read(), filename=filename)
        
        await callback.message.delete()
        await callback.message.answer_document(
            document=input_file,
            caption=t('full_test_users_list_f519010f0d', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    else:
        try:
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except Exception as e:
            logger.debug(f"Failed to edit message in admin_test_users_with_settings, sending new: {e}")
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    
    await safe_answer(callback)
        
        
        


def load_user_test_settings():
    """بارگذاری تنظیمات اختصاصی تست کاربران"""
    global USER_TEST_SETTINGS
    try:
        settings_file = os.path.join(DATA_DIR, "user_test_settings.json")
        if os.path.exists(settings_file):
            with open(settings_file, 'r', encoding='utf-8') as f:
                USER_TEST_SETTINGS = json.load(f)
            logger.info(f"✅ Custom test settings for {len(USER_TEST_SETTINGS)} user loaded")
        else:
            USER_TEST_SETTINGS = {}
    except Exception as e:
        logger.error(f"❌ Error loading user test settings: {e}")
        USER_TEST_SETTINGS = {}

def save_user_test_settings():
    """ذخیره تنظیمات اختصاصی تست کاربران"""
    try:
        settings_file = os.path.join(DATA_DIR, "user_test_settings.json")
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(USER_TEST_SETTINGS, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"❌ Error saving user test settings: {e}")
        return False

def get_user_test_settings(user_id: int) -> dict:
    """دریافت تنظیمات اختصاصی تست کاربر — نسخه اصلاح‌شده"""
    uid = str(user_id)

    vol_mb = TEST_SERVICE_STATUS.get('volume_mb')
    if vol_mb is None:
        if 'volume' in TEST_SERVICE_STATUS and TEST_SERVICE_STATUS['volume'] is not None:
            vol_mb = int(round(TEST_SERVICE_STATUS['volume'] * 1024))
        else:
            vol_mb = 1024

    default = {
        'volume_mb': vol_mb,
        'days': TEST_SERVICE_STATUS.get('days', 3),
        'max_tests': TEST_SERVICE_STATUS.get('max_tests', 1),
        'ip_limit': TEST_SERVICE_STATUS.get('ip_limit', 0),
    }

    if uid in USER_TEST_SETTINGS:
        # ✅ کپی بگیر تا دیکشنری اصلی خراب نشه
        settings = dict(USER_TEST_SETTINGS[uid])

        # ✅ تبدیل volume (GB) به volume_mb (MB) اگه لازم بود
        if 'volume_mb' not in settings and 'volume' in settings:
            settings['volume_mb'] = int(round(settings['volume'] * 1024))
        # ✅ یا برعکس (برای نمایش)
        if 'volume' not in settings and 'volume_mb' in settings:
            settings['volume'] = round(settings['volume_mb'] / 1024, 3)

        # پر کردن بقیه‌ی default‌ها
        for key, val in default.items():
            settings.setdefault(key, val)

        return settings

    # کاربر بدون تنظیمات اختصاصی — هم volume و هم volume_mb رو بده
    result = default.copy()
    result['volume'] = round(default['volume_mb'] / 1024, 3)
    return result

def _fmt_test_volume_gb(settings: dict) -> float:
    """
    نمایش حجم تست به گیگابایت
    همیشه از volume_mb می‌خونه (منبع اصلی حقیقت)
    """
    if not settings:
        return 1.0
    
    volume_mb = settings.get('volume_mb')
    if volume_mb is not None:
        try:
            return round(float(volume_mb) / 1024, 2)
        except (TypeError, ValueError):
            pass
    
    # fallback به volume اگه volume_mb نبود
    volume = settings.get('volume')
    if volume is not None:
        try:
            return round(float(volume), 2)
        except (TypeError, ValueError):
            pass
    
    return 1.0

@router.callback_query(F.data.startswith("admin_test_user_volume_"))
@admin_only
async def admin_test_user_volume(callback: CallbackQuery):
    """شروع تنظیم حجم اختصاصی تست برای کاربر"""

    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        target_id = int(callback.data.split("_")[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    user_states[callback.from_user.id] = {
        'awaiting_test_user_setting': True,
        'setting_type': 'volume',
        'target_user': target_id
    }
    
    user_settings = get_user_test_settings(target_id)
    # ✅ نمایش از volume_mb (منبع اصلی حقیقت)
    current_volume_gb = _fmt_test_volume_gb(user_settings)
    
    text = t('b_edit_custom_test_volume_b_869b55412b', lang, fa_parts=lambda: (f'{target_id}', f'{current_volume_gb}'), en_parts=lambda: (f'{target_id}', f'{current_volume_gb}'))
    buttons = [
        [InlineKeyboardButton(text=t('cancel_a82655b92b', lang), callback_data=f"admin_test_user_settings_{target_id}")]
    ]
    
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await callback.message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_test_user_days_"))
@admin_only
async def admin_test_user_days(callback: CallbackQuery):
    """شروع تنظیم مدت اختصاصی تست برای کاربر"""
    
    target_id = int(callback.data.split("_")[4])
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {
        'awaiting_test_user_setting': True,
        'setting_type': 'days',
        'target_user': target_id
    }
    
    await callback.message.answer(
        t('b_set_custom_test_duration_b_e7afcdc701', lang, fa_parts=lambda: (f'{target_id}', f"{get_user_test_settings(target_id)['days']}"), en_parts=lambda: (f'{target_id}', f"{get_user_test_settings(target_id)['days']}")),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_test_user_max_"))
@admin_only
async def admin_test_user_max(callback: CallbackQuery):
    """شروع تنظیم تعداد تست اختصاصی برای کاربر"""
    
    target_id = int(callback.data.split("_")[4])
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {
        'awaiting_test_user_setting': True,
        'setting_type': 'max_tests',
        'target_user': target_id
    }
    
    await callback.message.answer(
        t('b_set_custom_max_tests_b_use_7556ac5ced', lang, fa_parts=lambda: (f'{target_id}', f"{get_user_test_settings(target_id)['max_tests']}"), en_parts=lambda: (f'{target_id}', f"{get_user_test_settings(target_id)['max_tests']}")),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_test_user_setting'))
async def admin_test_user_settings_save(message: Message):
    """ذخیره تنظیم اختصاصی تست کاربر"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(
            t('cancelled_8a3eb8aae6', lang)
        )
        return
    
    state = user_states.get(admin_id, {})
    setting_type = state.get('setting_type')
    target_id = state.get('target_user')
    
    if not setting_type or not target_id:
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_invalid_state', lang))
        return
    
    try:
        new_value = int(message.text.replace(',', '').replace(' ', '').strip())
        
        if new_value <= 0:
            await message.reply(
                t('value_must_be_greater_than_z_0770671136', lang)
            )
            return
        
        if setting_type == 'volume' and new_value > 100:
            await message.reply(
                t('volume_cannot_exceed_100_gb_d227c5380a', lang)
            )
            return
        elif setting_type == 'days' and new_value > 30:
            await message.reply(
                t('duration_cannot_exceed_30_da_1d9486fb07', lang)
            )
            return
        elif setting_type == 'max_tests' and new_value > 10:
            await message.reply(
                t('max_tests_cannot_exceed_10_621b749df5', lang)
            )
            return
        
        uid = str(target_id)
        
        # اطمینان از وجود entry
        if uid not in USER_TEST_SETTINGS:
            USER_TEST_SETTINGS[uid] = {}
        
        # ✅ مقدار رو ذخیره کن
        USER_TEST_SETTINGS[uid][setting_type] = new_value
        
        # ✅✅✅ مهم‌ترین خط: همگام‌سازی volume_mb با volume
        if setting_type == 'volume':
            USER_TEST_SETTINGS[uid]['volume_mb'] = int(round(new_value * 1024))
            logger.info(
                f"✅ [test_settings_save] Test volume for user {target_id} set to: "
                f"{new_value}GB → {USER_TEST_SETTINGS[uid]['volume_mb']}MB"
            )
        
        save_user_test_settings()
        
        user_info = await get_user_info_from_telegram(target_id)
        
        try:
            await message.delete()
        except Exception:
            pass
        
        updated_settings = get_user_test_settings(target_id)
        # ✅ نمایش از volume_mb (مقدار تازه ذخیره شده)
        updated_volume_gb = _fmt_test_volume_gb(updated_settings)
        
        text = t('b_user_test_settings_b_user_a9e1dab676', lang, fa_parts=lambda: (f"{user_info['full_name']}", f'{target_id}', f"{USER_TEST_USAGE.get(str(target_id), {}).get('count', 0)}", f'{updated_volume_gb}', f"{updated_settings.get('days', 3)}", f"{updated_settings.get('max_tests', 1)}"), en_parts=lambda: (f"{user_info['full_name']}", f'{target_id}', f"{USER_TEST_USAGE.get(str(target_id), {}).get('count', 0)}", f'{updated_volume_gb}', f"{updated_settings.get('days', 3)}", f"{updated_settings.get('max_tests', 1)}"))
        buttons = [
            [InlineKeyboardButton(
                text=t('edit_volume_25aa034c83', lang),
                callback_data=f"admin_test_user_volume_{target_id}"
            )],
            [InlineKeyboardButton(
                text=t('edit_duration_10ab7193fb', lang),
                callback_data=f"admin_test_user_days_{target_id}"
            )],
            [InlineKeyboardButton(
                text=t('edit_max_tests_815b176da5', lang),
                callback_data=f"admin_test_user_max_{target_id}"
            )],
            [InlineKeyboardButton(
                text=t('reset_user_test_158529c5e0', lang),
                callback_data=f"admin_test_user_reset_single_{target_id}",
                style="danger"
            )],
            [InlineKeyboardButton(
                text=t('back_to_users_list_3a64be6166', lang),
                callback_data="admin_test_users_list"
            )],
            [InlineKeyboardButton(
                text=t('back_to_test_management_b7c7fe02c9', lang),
                callback_data="admin_test_users"
            )]
        ]
        
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
        user_states.pop(admin_id, None)
        
    except ValueError:
        await message.reply(
            t('please_enter_a_valid_number_afbbd0c0b3', lang)
        )
    except Exception as e:
        logger.error(f"Error saving user test setting: {e}", exc_info=True)
        err_type = html.escape(type(e).__name__)
        await message.reply(t('i18n_error_prefix', lang, fa_parts=lambda: (err_type,), en_parts=lambda: (err_type,)))
        user_states.pop(admin_id, None)

async def build_user_test_settings_content(target_id: int, lang: str = "fa") -> tuple[str, InlineKeyboardMarkup]:
    """تولید محتوا و دکمه‌های صفحه تنظیمات تست کاربر"""
    user_info = await get_user_info_from_telegram(target_id)
    full_name_escaped = safe_html(user_info.get('full_name', f'کاربر_{target_id}'))
    
    user_test_data = USER_TEST_USAGE.get(str(target_id), {})
    current_count = user_test_data.get('count', 0)
    user_settings = get_user_test_settings(target_id)
    
    # ✅ نمایش از volume_mb
    current_volume_gb = _fmt_test_volume_gb(user_settings)
    
    text = t('b_user_test_settings_b_user_d2b94630c8', lang, fa_parts=lambda: (f'{full_name_escaped}', f'{target_id}', f'{current_count}', f'{current_volume_gb}', f"{user_settings.get('days', 3)}", f"{user_settings.get('max_tests', 1)}"), en_parts=lambda: (f'{full_name_escaped}', f'{target_id}', f'{current_count}', f'{current_volume_gb}', f"{user_settings.get('days', 3)}", f"{user_settings.get('max_tests', 1)}"))
    buttons = [
        [InlineKeyboardButton(
            text=t('edit_volume_25aa034c83', lang),
            callback_data=f"admin_test_user_volume_{target_id}"
        )],
        [InlineKeyboardButton(
            text=t('edit_duration_10ab7193fb', lang),
            callback_data=f"admin_test_user_days_{target_id}"
        )],
        [InlineKeyboardButton(
            text=t('edit_max_tests_815b176da5', lang),
            callback_data=f"admin_test_user_max_{target_id}"
        )],
        [InlineKeyboardButton(
            text=t('reset_user_test_158529c5e0', lang),
            callback_data=f"admin_test_user_reset_single_{target_id}",
            style="danger"
        )],
        [InlineKeyboardButton(
            text=t('back_to_users_list_3a64be6166', lang),
            callback_data="admin_test_users_list"
        )],
        [InlineKeyboardButton(
            text=t('back_to_test_management_b7c7fe02c9', lang),
            callback_data="admin_test_users"
        )]
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data.startswith("admin_test_user_settings_"))
@admin_only
async def admin_test_user_settings(callback: CallbackQuery):
    """تنظیمات تست برای یک کاربر خاص"""

    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        target_id = int(callback.data.split("_")[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    text, reply_markup = await build_user_test_settings_content(target_id, lang)
    
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await callback.message.answer(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)
        
@router.callback_query(F.data == "admin_test_users_reset_all")
@admin_only
async def admin_test_users_reset_all_confirm(callback: CallbackQuery):
    """تأیید ریست تست همه کاربران"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    total_users = len(USER_TEST_USAGE)
    total_tests = sum(data.get('count', 0) for data in USER_TEST_USAGE.values())
    
    if total_users == 0:
        await callback.answer(
            t('no_users_have_taken_a_test_800fda8f88', lang),
            show_alert=True
        )
        return
    
    text = t('b_warning_reset_all_users_te_248b37217e', lang, fa_parts=lambda: (f'{total_users}', f'{total_tests}'), en_parts=lambda: (f'{total_users}', f'{total_tests}'))
    buttons = [
        [
            InlineKeyboardButton(text=t('yes_reset_2fbc55f87f', lang), callback_data="admin_test_users_reset_all_execute", style="danger"),
            InlineKeyboardButton(text=t('cancel_4197bafba5', lang), callback_data="admin_test_users")
        ]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@router.callback_query(F.data == "admin_test_users_reset_all_execute")
@admin_only
async def admin_test_users_reset_all_execute(callback: CallbackQuery):
    """اجرای ریست تست همه کاربران"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    total_users = len(USER_TEST_USAGE)
    total_tests = sum(data.get('count', 0) for data in USER_TEST_USAGE.values())
    USER_TEST_USAGE.clear()
    save_test_usage()
    invalidate_test_users_cache()
    logger.info(f"🗑 reset all tests for user {total_users} user with {total_tests} test reset")
    
    if log_system:
        await log_system.log_admin_action(
            callback.from_user.id,
            "Reset test services for all users",
            details=f"Users: {total_users} | Test services: {total_tests}"
        )
    
    text = t('b_all_users_tests_reset_succ_599ea727e9', lang, fa_parts=lambda: (f'{total_users}', f'{total_tests}'), en_parts=lambda: (f'{total_users}', f'{total_tests}'))
    
    buttons = [
        [InlineKeyboardButton(
            text=t('back_to_test_management_b7c7fe02c9', lang),
            callback_data="admin_test_users"
        )]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)
    
@router.callback_query(F.data == "admin_test_stats")
@admin_only
async def admin_test_stats(callback: CallbackQuery):
    """نمایش آمار تست کاربران"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    total_users = len(USER_TEST_USAGE)
    total_tests, test_users = get_cached_sorted_test_users()
    
    text = t('b_test_service_statistics_b_761038eb4f', lang, fa_parts=lambda: (f'{total_users}', f'{total_tests}'), en_parts=lambda: (f'{total_users}', f'{total_tests}'))
    for i, u in enumerate(test_users[:20], 1):
        text += t('tests_0ac703c94b', lang, fa_parts=lambda: (f'{i}', f"{u['name']}", f"{u['count']}"), en_parts=lambda: (f'{i}', f"{u['name']}", f"{u['count']}"))

    if len(test_users) > 20:
        text += t('and_more_users_671fdf93f4', lang, fa_parts=lambda: (f'{len(test_users) - 20}',), en_parts=lambda: (f'{len(test_users) - 20}',))

    if not test_users:
        text += t('no_users_have_taken_a_test_f101764e5b', lang)
    
    buttons = [
        [InlineKeyboardButton(
            text=t('refresh_cda5094083', lang),
            callback_data="admin_test_stats"
        )],
        [InlineKeyboardButton(
            text=t('back_to_settings_8ad1a33ecb', lang),
            callback_data="admin_test_service"
        )]
    ]
    
    await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    
    await safe_answer(callback)
        


def save_user_inbound_selection(user_id: int, inbound: Union[int, List[int]]):
    """ذخیره انتخاب اینباند کاربر (تک یا لیست)"""
    USER_INBOUND_SELECTION[str(user_id)] = inbound
    try:
        inbound_file = os.path.join(DATA_DIR, "user_inbounds.json")
        with open(inbound_file, 'w', encoding='utf-8') as f:
            json.dump(USER_INBOUND_SELECTION, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ selected inbound for user {user_id} saved: {inbound}")
    except Exception as e:
        logger.error(f"❌ Error saving inbound selection: {e}")

def load_user_inbound_selections():
    """بارگذاری انتخاب‌های اینباند کاربران"""
    global USER_INBOUND_SELECTION
    try:
        inbound_file = os.path.join(DATA_DIR, "user_inbounds.json")
        if os.path.exists(inbound_file):
            with open(inbound_file, 'r', encoding='utf-8') as f:
                USER_INBOUND_SELECTION = json.load(f)
            logger.info(f"✅ User inbound selections loaded: {len(USER_INBOUND_SELECTION)} user")
    except Exception as e:
        logger.error(f"Error loading inbound selections: {e}")
        USER_INBOUND_SELECTION = {}



@router.callback_query(F.data == "get_test_service")
async def get_test_service(callback: CallbackQuery):
    """دریافت تست سرویس توسط کاربر - نسخه نهایی"""
    user_id = callback.from_user.id
    
    # ═══════════════════════════════════════════
    # ۱. بررسی‌های امنیتی و دسترسی
    # ═══════════════════════════════════════════
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    if not await check_membership(user_id):
        lang = get_user(user_id).get('lang', 'fa')
        await callback.answer(
            t('please_verify_your_membershi_28b48b1f0b', lang),
            show_alert=True
        )
        return
    
    if not TEST_SERVICE_STATUS.get('enabled', False):
        lang = get_user(user_id).get('lang', 'fa')
        await callback.answer(
            t('test_service_is_currently_di_b20635423d', lang),
            show_alert=True
        )
        return
    
    # ═══════════════════════════════════════════
    # ۲. دریافت تنظیمات تست کاربر
    # ═══════════════════════════════════════════
    lang = get_user(user_id).get('lang', 'fa')
    
    default_volume_mb = TEST_SERVICE_STATUS.get('volume_mb', 1024)
    default_days = TEST_SERVICE_STATUS.get('days', 3)
    default_max_tests = TEST_SERVICE_STATUS.get('max_tests', 1)
    default_ip_limit = TEST_SERVICE_STATUS.get('ip_limit', 0)
    
    user_settings = get_user_test_settings(user_id)
    volume_mb = user_settings.get('volume_mb', default_volume_mb)
    days = user_settings.get('days', default_days)
    max_tests = user_settings.get('max_tests', default_max_tests)
    ip_limit = user_settings.get('ip_limit', default_ip_limit)
    
    # ─── محاسبه حجم ───
    if volume_mb == 0:
        volume_gb = 0
        volume_display = "نامحدود"
    else:
        volume_gb = volume_mb / 1024
        volume_display = format_volume(volume_mb, is_test=True)
    
    logger.info(f"🧪 test for user {user_id}:")
    logger.info(f"  Volume: {volume_mb} MB ({volume_gb} GB) - {volume_display}")
    logger.info(f"  Duration: {days}days")
    logger.info(f"  Maximum tests: {max_tests}")
    logger.info(f"  IP limit: {ip_limit}")
    
    # ═══════════════════════════════════════════
    # ۳. بررسی سقف تست کاربر
    # ═══════════════════════════════════════════
    uid = str(user_id)
    user_test_data = USER_TEST_USAGE.get(uid, {})
    test_count = user_test_data.get('count', 0)
    
    if test_count >= max_tests:
        await callback.answer(
            t('you_have_already_reached_the_fe2d77286d', lang, fa_parts=lambda: (f'{max_tests}',), en_parts=lambda: (f'{max_tests}',)),
            show_alert=True
        )
        return
    
    # ═══════════════════════════════════════════
    # ۴. تعیین اینباندهای تست
    # ═══════════════════════════════════════════
    test_inbound_ids = TEST_SERVICE_STATUS.get('inbound_ids', [])
    
    if not test_inbound_ids:
        user_inbounds = get_user_inbound(user_id)
        if user_inbounds:
            if isinstance(user_inbounds, list):
                test_inbound_ids = user_inbounds
            else:
                test_inbound_ids = [user_inbounds]
            logger.info(f"👤 Using inbounds for user {user_id} for test: {test_inbound_ids}")
        else:
            default_ids = configs_pool.get('default_inbound_ids', [])
            if default_ids:
                test_inbound_ids = default_ids
                logger.info(f"📌 Using default inbounds for test: {test_inbound_ids}")
    
    # ═══════════════════════════════════════════
    # ۵. ارسال پیام لودینگ
    # ═══════════════════════════════════════════
    loading_text = t('creating_test_service_0a1542c383', lang)
    loading_msg = None
    
    try:
        if callback.message.text:
            await callback.message.edit_text(loading_text)
            loading_msg = callback.message
        else:
            loading_msg = await callback.message.answer(loading_text)
    except Exception:
        try:
            loading_msg = await callback.message.answer(loading_text)
        except Exception as e2:
            logger.warning(f"Error sending loading message: {e2}")
    
    # ═══════════════════════════════════════════
    # ۶. ساخت سرویس تست
    # ═══════════════════════════════════════════
    try:
        email = f"test_{user_id}_{int(datetime.now().timestamp())}"
        user_info = get_user(user_id)
        user_name = user_info.get('name', f'کاربر_{user_id}')
        
        sub_link = await xui_create_client_with_inbound(
            email,
            volume_gb,
            days,
            user_name,
            user_id,
            test_inbound_ids,
            ip_limit=ip_limit
        )
        
        # ───────────────────────────────────────
        # ۶.۱. ساخت موفق
        # ───────────────────────────────────────
        if sub_link:
            order_id = create_order(user_id, volume_gb, days, 0, "test", ip_limit=ip_limit)
            update_order(
                order_id,
                status='approved',
                config_link=sub_link,
                sub_link=sub_link,
                email=email,
                payment_method='test',
                inbound_id=test_inbound_ids,
                approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S")
            )
            
            USER_TEST_USAGE[uid] = {
                'count': test_count + 1,
                'last_test': now_tehran_iso(),
                'last_order_id': order_id,
                'inbound_ids': test_inbound_ids,
                'used_settings': {
                    'volume_mb': volume_mb,
                    'days': days,
                    'max_tests': max_tests,
                    'ip_limit': ip_limit
                }
            }
            
            # ─── نوتیفیکیشن ادمین ───
            await send_admin_notification('test', {
                'user_id': user_id,
                'volume': volume_mb,
                'days': days,
                'price': 0,
                'order_id': order_id,
                'remaining_tests': max_tests - (test_count + 1),
                'inbound_ids': test_inbound_ids,
                'ip_limit': ip_limit
            })
            
            # ─── ذخیره test_usage.json ───
            try:
                test_file = os.path.join(DATA_DIR, "test_usage.json")
                with open(test_file, 'w', encoding='utf-8') as f:
                    json.dump(USER_TEST_USAGE, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error saving test user: {e}")
            
            # ─── حذف پیام لودینگ ───
            deleted = False
            if loading_msg:
                try:
                    await loading_msg.delete()
                    deleted = True
                except Exception as e:
                    logger.debug(f"Error deleting loading message: {e}")
            
            if not deleted:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
            
            # ─── ارسال عکس QR با کپشن ───
            await send_config_with_qr_option(user_id, order_id, volume_gb, days, 0, sub_link, lang)
            
            # ─── لاگ ───
            inbound_display = test_inbound_ids if test_inbound_ids else 'پیش‌فرض'
            logger.info(
                f"🧪 User {user_id} received a test service - order #{order_id} - {volume_display}/{days} days - inbounds: {inbound_display} - IP Limit: {ip_limit}"
            )
            
            if log_system:
                await log_system.log_user_action(
                    user_id,
                    "Received service trial",
                    f"Order #{order_id} | {volume_display}/{days} days | "
                    f"Inbounds: {inbound_display} | IP Limit: {ip_limit}"
                )
            
            await callback.answer(
                t('test_service_activated_3b3e937ca9', lang)
            )
        
        # ───────────────────────────────────────
        # ۶.۲. خطا در ساخت
        # ───────────────────────────────────────
        else:
            if loading_msg:
                try:
                    await loading_msg.delete()
                except Exception:
                    pass
            
            error_msg = (
                t('error_creating_test_service_b0e704c6a6', lang)
            )
            try:
                await callback.message.answer(
                    error_msg,
                    reply_markup=get_back_only_keyboard(lang)
                )
            except Exception:
                pass
            
            logger.error(f"❌ Error creating test for user {user_id}")
    
    # ───────────────────────────────────────
    # ۶.۳. خطای غیرمنتظره
    # ───────────────────────────────────────
    except Exception as e:
        logger.error(f"❌ Error retrieving test: {e}", exc_info=True)
        
        if loading_msg:
            try:
                await loading_msg.delete()
            except Exception:
                pass
        
        try:
            await callback.message.answer(
                t('error_processing_request_ple_30e1cc8c79', lang),
                reply_markup=get_back_only_keyboard(lang)
            )
        except Exception:
            pass
    
    # ═══════════════════════════════════════════
    # ۷. پاسخ نهایی callback
    # ═══════════════════════════════════════════
    await safe_answer(callback)


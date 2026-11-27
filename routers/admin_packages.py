"""
routers/admin_packages.py
-------------------------
مدیریت بسته‌های آماده، دسته‌بندی‌ها، کوپن‌های تخفیف و هشدارهای مصرف/انقضا
"""

import os
import re
import json
import time
import html
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple, Union

from aiogram import Router, F, Bot, types
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.filters import Command
from aiogram.enums import ParseMode

from config import ADMIN_ID, SENAI_PANEL_ENABLED, SUPPORT_USERNAME
from db_storage import DATA_DIR, save_json, DB_FILES
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
    update_order,
)
from core.save_scheduler import schedule_save
from user_manager import (
    user_states,
    get_user,
    get_user_safe,
    get_admin_id_int,
    COUPONS,
    save_coupons,
    save_coupon_to_user_db,
    is_coupon_valid_for_user,
    update_user,
)
from core.state_stores import (
    TEMP_INBOUND_SELECTION,
    INBOUND_BACK_DATA,
    USER_INBOUND_SELECTION,
    USER_TEST_SETTINGS,
)
from routers.admin_test import (
    show_inbound_manager,
    save_user_inbound_selection,
)
from services.package_gift_service import (
    get_package_gift_store,
    find_defined_package,
    create_package_gift_code,
    delete_package_gift_code,
)
from routers.force_join import check_membership
from strings import t
from emoji_sticker_system import premium_emoji
from utils.filters import IsAdmin
from utils.guards import admin_only
from utils.helpers import safe_answer, safe_edit_message, safe_html
from utils.rate_limiter import buy_rate_limiter
from utils.payment_guard import payment_guard, PaymentInProgressError
from routers.shop import (
    check_shop_status_and_notify,
    format_package_volume,
    get_user_last_purchased_package,
    show_ready_categories,
    cancel_extend,
    show_category_packages,
    buy_specific_package,
    show_ready_categories_keep_coupon,
    pay_ready_package_balance,
    _process_pay_ready_package_balance,
)

logger = logging.getLogger(__name__)

router = Router(name="admin_packages")

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


class _AlertSystemProxy:
    def __bool__(self):
        try:
            import main
            return bool(getattr(main, "alert_system", None))
        except Exception:
            return False

    def __getattr__(self, name):
        import main
        as_inst = getattr(main, "alert_system", None)
        if as_inst is not None:
            return getattr(as_inst, name)
        raise AttributeError(name)


alert_system = _AlertSystemProxy()


class _AlertSettingsProxy(dict):
    def _target(self):
        import main
        if hasattr(main, "alert_system_settings"):
            return main.alert_system_settings
        return configs_pool.setdefault("alert_settings", {})

    def get(self, *args, **kwargs):
        return self._target().get(*args, **kwargs)

    def __getitem__(self, key):
        return self._target()[key]

    def __setitem__(self, key, value):
        self._target()[key] = value

    def __contains__(self, key):
        return key in self._target()

    def update(self, *args, **kwargs):
        return self._target().update(*args, **kwargs)


alert_system_settings = _AlertSettingsProxy()


def get_main_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_main_keyboard"):
        return main.get_main_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def get_purchase_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_purchase_keyboard"):
        return main.get_purchase_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def get_back_only_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_back_only_keyboard"):
        return main.get_back_only_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


def to_persian_digits(*args, **kwargs):
    import main
    if hasattr(main, "to_persian_digits"):
        return main.to_persian_digits(*args, **kwargs)
    return str(args[0]) if args else ""


async def notify_blacklisted_user(*args, **kwargs):
    import main
    if hasattr(main, "notify_blacklisted_user"):
        return await main.notify_blacklisted_user(*args, **kwargs)


async def check_referral_bonus(*args, **kwargs):
    import main
    if hasattr(main, "check_referral_bonus"):
        return await main.check_referral_bonus(*args, **kwargs)


async def create_order(*args, **kwargs):
    import main
    if hasattr(main, "create_order"):
        return await main.create_order(*args, **kwargs)


def record_purchase(*args, **kwargs):
    import main
    if hasattr(main, "record_purchase"):
        return main.record_purchase(*args, **kwargs)


def get_valid_orders(*args, **kwargs):
    import main
    if hasattr(main, "get_valid_orders"):
        return main.get_valid_orders(*args, **kwargs)
    return []


def get_order_client_email(*args, **kwargs):
    import main
    if hasattr(main, "get_order_client_email"):
        return main.get_order_client_email(*args, **kwargs)
    return ""


def get_feedback_keyboard(*args, **kwargs):
    import main
    if hasattr(main, "get_feedback_keyboard"):
        return main.get_feedback_keyboard(*args, **kwargs)
    return InlineKeyboardMarkup(inline_keyboard=[])


async def send_config_with_qr_option(*args, **kwargs):
    import main
    if hasattr(main, "send_config_with_qr_option"):
        return await main.send_config_with_qr_option(*args, **kwargs)


from services.panel_api import xui_get_inbounds


@router.callback_query(F.data == "admin_coupons")
@admin_only
async def admin_coupons(callback: CallbackQuery):
    """مدیریت کوپن‌ها در پنل ادمین"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    total_coupons = len(COUPONS)
    active_coupons = len([c for c in COUPONS.values() if c.get('status') == 'active'])
    used_coupons = len([c for c in COUPONS.values() if c.get('status') == 'used'])
    expired_coupons = len([c for c in COUPONS.values() if c.get('status') == 'expired'])
    
    text = t('b_coupon_management_b_coupon_13ad71277f', lang, fa_parts=lambda: (f'{total_coupons}', f'{active_coupons}', f'{used_coupons}', f'{expired_coupons}'), en_parts=lambda: (f'{total_coupons}', f'{active_coupons}', f'{used_coupons}', f'{expired_coupons}'))
    buttons = [
        [InlineKeyboardButton(text=t('i18n_admin_coupon_create_button', lang), callback_data="admin_coupon_create")],
        [InlineKeyboardButton(text=t('admin_pgift_menu_btn', lang), callback_data="admin_pgift_menu", style="primary")],
        [InlineKeyboardButton(text=t('coupons_list_2b3f1e787a', lang), callback_data="admin_coupons_list")],
        [InlineKeyboardButton(text=t('delete_coupon_52c714868d', lang), callback_data="admin_coupon_delete")],
        [InlineKeyboardButton(text=t('usage_statistics_671ff0454d', lang), callback_data="admin_coupons_stats")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
    ]
    
    await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))


# ==================== کدهای یک‌بارمصرف بسته ویژه (VIP) ====================

def _pgift_package_label(pkg: dict, lang: str) -> str:
    vol = pkg.get('volume', 0) or 0
    days = pkg.get('days', 30) or 30
    vol_txt = format_package_volume(vol, lang)
    return vol_txt, str(days)


def _format_pgift_result(raw_code: str, record: dict, lang: str) -> Tuple[str, InlineKeyboardMarkup]:
    cat_name = (
        record.get('category_name') if lang == "fa" else record.get('category_name_en') or record.get('category_name')
    ) or ""
    pkg_name = (
        record.get('package_name') if lang == "fa" else record.get('package_name_en') or record.get('package_name')
    ) or cat_name
    vol_txt = format_package_volume(record.get('volume', 0) or 0, lang)
    days = record.get('days', 30) or 30
    uid_lock = record.get('allowed_user_id')
    if uid_lock is not None:
        lock_str = f"🔒 <code>{uid_lock}</code>"
    else:
        lock_str = "🔓 عمومی" if lang == "fa" else "🔓 Open (No user lock)"
    text = t(
        'admin_pgift_created',
        lang,
        fa_parts=lambda: (html.escape(str(pkg_name)), vol_txt, days, lock_str, html.escape(raw_code)),
        en_parts=lambda: (html.escape(str(pkg_name)), vol_txt, days, lock_str, html.escape(raw_code)),
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t('admin_pgift_create_btn', lang), callback_data="admin_pgift_create", style="success")],
        [InlineKeyboardButton(text=t('admin_pgift_list_btn', lang, fa_parts=lambda: (len(get_package_gift_store()),), en_parts=lambda: (len(get_package_gift_store()),)), callback_data="admin_pgift_list")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_pgift_menu")],
    ])
    return text, kb


@router.callback_query(F.data == "admin_pgift_menu")
@admin_only
async def admin_pgift_menu(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    store = get_package_gift_store()
    active_cnt = sum(1 for r in store.values() if isinstance(r, dict) and r.get('status') == 'active')
    used_cnt = sum(1 for r in store.values() if isinstance(r, dict) and r.get('status') != 'active')
    text = t(
        'admin_pgift_menu_title',
        lang,
        fa_parts=lambda: (active_cnt, used_cnt),
        en_parts=lambda: (active_cnt, used_cnt),
    )
    buttons = [
        [InlineKeyboardButton(text=t('admin_pgift_create_btn', lang), callback_data="admin_pgift_create", style="success")],
        [InlineKeyboardButton(text=t('admin_pgift_list_btn', lang, fa_parts=lambda: (len(store),), en_parts=lambda: (len(store),)), callback_data="admin_pgift_list", style="primary")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_coupons")],
    ]
    await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data == "admin_pgift_create")
@admin_only
async def admin_pgift_create_select_cat(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    cats = [c for c in READY_PACKAGES.get('categories', []) if c.get('packages')]
    if not cats:
        await callback.answer(t('admin_pgift_no_packages', lang), show_alert=True)
        return
    buttons = []
    for cat in cats:
        cat_id = cat.get('id')
        icon = cat.get('icon', '📦')
        name = (cat.get('name') if lang == "fa" else cat.get('name_en') or cat.get('name')) or f"#{cat_id}"
        status_dot = "🟢" if cat.get('is_active', True) else "🔴"
        pkg_count = len(cat.get('packages', []))
        buttons.append([InlineKeyboardButton(
            text=f"{status_dot} {icon} {name} ({pkg_count})"[:55],
            callback_data=f"admin_pgift_cat_{cat_id}",
        )])
    buttons.append([InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_pgift_menu")])
    await safe_edit_message(callback, t('admin_pgift_select_cat', lang), InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("admin_pgift_cat_"))
@admin_only
async def admin_pgift_create_select_pkg(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        cat_id = int(callback.data.replace("admin_pgift_cat_", "", 1))
    except ValueError:
        await safe_answer(callback)
        return
    cat = next((c for c in READY_PACKAGES.get('categories', []) if c.get('id') == cat_id), None)
    if not cat or not cat.get('packages'):
        await callback.answer(t('admin_pgift_no_packages', lang), show_alert=True)
        return
    cat_name = (cat.get('name') if lang == "fa" else cat.get('name_en') or cat.get('name')) or f"#{cat_id}"
    buttons = []
    for pkg in cat.get('packages', []):
        pkg_id = pkg.get('id')
        status_dot = "🟢" if pkg.get('is_active', True) else "🔴"
        vol_txt, days_txt = _pgift_package_label(pkg, lang)
        ip_lim = pkg.get('ip_limit', 0) or 0
        ip_str = f" · {ip_lim}👤" if ip_lim > 0 else ""
        buttons.append([InlineKeyboardButton(
            text=f"{status_dot} {vol_txt} · {days_txt}{' روز' if lang == 'fa' else 'd'}{ip_str}"[:55],
            callback_data=f"admin_pgift_pkg_{cat_id}_{pkg_id}",
        )])
    buttons.append([InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_pgift_create")])
    text = t('admin_pgift_select_pkg', lang, fa_parts=lambda: (html.escape(str(cat_name)),), en_parts=lambda: (html.escape(str(cat_name)),))
    await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("admin_pgift_pkg_"))
@admin_only
async def admin_pgift_choose_lock_mode(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        parts = callback.data.replace("admin_pgift_pkg_", "", 1).split("_")
        cat_id, pkg_id = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        await safe_answer(callback)
        return
    cat, pkg = find_defined_package(cat_id, pkg_id)
    if not cat or not pkg:
        await callback.answer(t('admin_pgift_no_packages', lang), show_alert=True)
        return
    pkg_name = (
        pkg.get('name_fa') or pkg.get('name') or cat.get('name')
        if lang == "fa"
        else pkg.get('name_en') or pkg.get('name') or cat.get('name_en') or cat.get('name')
    ) or ""
    vol_txt, days_txt = _pgift_package_label(pkg, lang)
    text = t(
        'admin_pgift_choose_lock',
        lang,
        fa_parts=lambda: (html.escape(str(pkg_name)), vol_txt, days_txt),
        en_parts=lambda: (html.escape(str(pkg_name)), vol_txt, days_txt),
    )
    buttons = [
        [InlineKeyboardButton(text=t('admin_pgift_open_btn', lang), callback_data=f"admin_pgift_open_{cat_id}_{pkg_id}", style="primary")],
        [InlineKeyboardButton(text=t('admin_pgift_lock_btn', lang), callback_data=f"admin_pgift_lock_{cat_id}_{pkg_id}", style="success")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data=f"admin_pgift_cat_{cat_id}")],
    ]
    await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("admin_pgift_open_"))
@admin_only
async def admin_pgift_create_open(callback: CallbackQuery):
    admin_id = callback.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    try:
        parts = callback.data.replace("admin_pgift_open_", "", 1).split("_")
        cat_id, pkg_id = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        await safe_answer(callback)
        return
    try:
        raw_code, record = create_package_gift_code(cat_id, pkg_id, admin_id, allowed_user_id=None)
    except ValueError:
        await callback.answer(t('admin_pgift_no_packages', lang), show_alert=True)
        return
    text, kb = _format_pgift_result(raw_code, record, lang)
    await safe_edit_message(callback, text, kb)


@router.callback_query(F.data.startswith("admin_pgift_lock_"))
@admin_only
async def admin_pgift_lock_prompt(callback: CallbackQuery):
    admin_id = callback.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    try:
        parts = callback.data.replace("admin_pgift_lock_", "", 1).split("_")
        cat_id, pkg_id = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        await safe_answer(callback)
        return
    cat, pkg = find_defined_package(cat_id, pkg_id)
    if not cat or not pkg:
        await callback.answer(t('admin_pgift_no_packages', lang), show_alert=True)
        return
    user_states[admin_id] = {
        'awaiting_pgift_user_id': True,
        'category_id': cat_id,
        'package_id': pkg_id,
    }
    await callback.message.answer(t('admin_pgift_enter_uid', lang), parse_mode=ParseMode.HTML)
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_pgift_user_id'))
async def admin_pgift_lock_save(message: Message):
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    raw = (message.text or "").strip()
    if raw == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_7978307565', lang))
        return
    normalized = raw.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    if not normalized.isdigit() or int(normalized) <= 0:
        await message.reply(t('admin_pgift_invalid_uid', lang))
        return
    target_uid = int(normalized)
    state = user_states.pop(admin_id, {})
    cat_id = state.get('category_id')
    pkg_id = state.get('package_id')
    try:
        raw_code, record = create_package_gift_code(cat_id, pkg_id, admin_id, allowed_user_id=target_uid)
    except ValueError:
        await message.reply(t('admin_pgift_no_packages', lang))
        return
    text, kb = _format_pgift_result(raw_code, record, lang)
    await message.reply(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "admin_pgift_list")
@admin_only
async def admin_pgift_list(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    store = get_package_gift_store()
    if not store:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('admin_pgift_create_btn', lang), callback_data="admin_pgift_create", style="success")],
            [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_pgift_menu")],
        ])
        await safe_edit_message(callback, t('admin_pgift_list_empty', lang), kb)
        return
    items = sorted(
        (r for r in store.values() if isinstance(r, dict) and r.get('id')),
        key=lambda r: str(r.get('created_at', '')),
        reverse=True,
    )
    buttons = []
    for rec in items[:20]:
        st_dot = "🟢" if rec.get('status') == 'active' else "🔴"
        vol_txt = format_package_volume(rec.get('volume', 0) or 0, lang)
        days = rec.get('days', 30) or 30
        lock_icon = "🔒" if rec.get('allowed_user_id') is not None else "🔓"
        preview = rec.get('code_preview', rec.get('id', ''))
        buttons.append([InlineKeyboardButton(
            text=f"{st_dot} {lock_icon} {preview} · {vol_txt}/{days}{'ر' if lang == 'fa' else 'd'}"[:55],
            callback_data=f"admin_pgift_view_{rec['id']}",
        )])
    buttons.append([InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_pgift_menu")])
    await safe_edit_message(callback, t('admin_pgift_list_title', lang), InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("admin_pgift_view_"))
@admin_only
async def admin_pgift_view(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    gift_id = callback.data.replace("admin_pgift_view_", "", 1)
    rec = get_package_gift_store().get(gift_id)
    if not isinstance(rec, dict):
        await callback.answer(t('coupon_not_found_a97baa7923', lang), show_alert=True)
        await admin_pgift_list(callback)
        return
    status_str = ("🟢 فعال" if lang == "fa" else "🟢 Active") if rec.get('status') == 'active' else ("🔴 استفاده‌شده" if lang == "fa" else "🔴 Redeemed")
    pkg_name = (rec.get('package_name') if lang == "fa" else rec.get('package_name_en') or rec.get('package_name')) or rec.get('category_name', '')
    vol_txt = format_package_volume(rec.get('volume', 0) or 0, lang)
    days = rec.get('days', 30) or 30
    uid_lock = rec.get('allowed_user_id')
    lock_str = f"<code>{uid_lock}</code>" if uid_lock is not None else ("بدون محدودیت" if lang == "fa" else "Open")
    created = str(rec.get('created_at', ''))[:16].replace('T', ' ')
    used_extra = ""
    if rec.get('status') != 'active':
        used_at = str(rec.get('used_at', ''))[:16].replace('T', ' ')
        used_extra = (
            f"\n👤 دریافت‌کننده: <code>{rec.get('used_by')}</code> | سفارش: <code>#{rec.get('order_id')}</code>\n⏱ زمان استفاده: <code>{used_at}</code>"
            if lang == "fa"
            else f"\n👤 Redeemed by: <code>{rec.get('used_by')}</code> | Order: <code>#{rec.get('order_id')}</code>\n⏱ Redeemed at: <code>{used_at}</code>"
        )
    text = t(
        'admin_pgift_detail',
        lang,
        fa_parts=lambda: (html.escape(str(rec.get('code_preview', ''))), status_str, html.escape(str(pkg_name)), vol_txt, days, lock_str, created, used_extra),
        en_parts=lambda: (html.escape(str(rec.get('code_preview', ''))), status_str, html.escape(str(pkg_name)), vol_txt, days, lock_str, created, used_extra),
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t('admin_pgift_delete_btn', lang), callback_data=f"admin_pgift_del_{gift_id}", style="danger")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_pgift_list")],
    ])
    await safe_edit_message(callback, text, kb)


@router.callback_query(F.data.startswith("admin_pgift_del_"))
@admin_only
async def admin_pgift_delete(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    gift_id = callback.data.replace("admin_pgift_del_", "", 1)
    removed = delete_package_gift_code(gift_id)
    if not removed:
        await callback.answer(t('coupon_not_found_a97baa7923', lang), show_alert=True)
        return
    await callback.answer(t('admin_pgift_deleted', lang), show_alert=True)
    await admin_pgift_list(callback)

@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_coupon_create'))
async def admin_coupon_create_process(message: Message):
    """پردازش مراحل ایجاد کوپن"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_7978307565', lang))
        return
    
    state = user_states.get(admin_id, {})
    step = state.get('step')
    coupon_data = state.get('coupon_data', {})
    
    if not step:
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_invalid_state', lang))
        return
    
    try:
        # ✅ مرحله 0: انتخاب نوع کوپن
        if step == 'type':
            text_lower = message.text.strip().lower()
            
            if text_lower in ['1', 'معمولی', 'normal', 'n']:
                coupon_data['coupon_type'] = 'normal'
                user_states[admin_id] = {
                    'awaiting_coupon_create': True,
                    'step': 'code',
                    'coupon_data': coupon_data
                }
                await message.reply(
                    t('b_normal_coupon_selected_b_b_947332915f', lang),
                    parse_mode=ParseMode.HTML
                )
            elif text_lower in ['2', 'ادمین', 'admin', 'special', 'a']:
                coupon_data['coupon_type'] = 'admin_special'
                user_states[admin_id] = {
                    'awaiting_coupon_create': True,
                    'step': 'code',
                    'coupon_data': coupon_data
                }
                await message.reply(
                    t('b_admin_private_coupon_selec_f005885cee', lang),
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.reply(
                    t('please_choose_one_of_the_opt_217271b0bc', lang)
                )
            return
        
        # ✅ مرحله code
        if step == 'code':
            code = message.text.strip().replace(' ', '')
            
            if len(code) < 3:
                await message.reply(t('coupon_code_must_be_at_least_b249eb9297', lang))
                return
            
            if not code.isalnum():
                await message.reply(t('coupon_code_must_contain_onl_2701018e34', lang))
                return
            
            if code in COUPONS:
                await message.reply(t('code_already_exists_be3d25e27e', lang, fa_parts=lambda: (f'{code}',), en_parts=lambda: (f'{code}',)))
                return
            
            coupon_data['code'] = code
            user_states[admin_id] = {
                'awaiting_coupon_create': True,
                'step': 'discount',
                'coupon_data': coupon_data
            }
            
            await message.reply(
                t('b_step_2_of_4_discount_perce_43f45e06fd', lang),
                parse_mode=ParseMode.HTML
            )
        
        # ✅ مرحله discount
        elif step == 'discount':
            discount = int(message.text.replace(',', '').replace(' ', '').strip())
            
            if discount < 1 or discount > 100:
                await message.reply(t('discount_must_be_between_1_a_f8aa6938d8', lang))
                return
            
            coupon_data['discount'] = discount
            
            # ✅ برای کوپن ادمین، مرحله usage_limit متفاوت است
            if coupon_data.get('coupon_type') == 'admin_special':
                user_states[admin_id] = {
                    'awaiting_coupon_create': True,
                    'step': 'usage_limit',
                    'coupon_data': coupon_data
                }
                
                await message.reply(
                    t('b_step_3_of_4_usage_limit_fo_9f3e66cb69', lang),
                    parse_mode=ParseMode.HTML
                )
            else:
                user_states[admin_id] = {
                    'awaiting_coupon_create': True,
                    'step': 'usage_limit',
                    'coupon_data': coupon_data
                }
                
                await message.reply(
                    t('b_step_3_of_4_usage_limit_b_270d12f1cd', lang),
                    parse_mode=ParseMode.HTML
                )
        
        # ✅ مرحله usage_limit
        elif step == 'usage_limit':
            usage_limit = int(message.text.replace(',', '').replace(' ', '').strip())
            
            if usage_limit < 0:
                await message.reply(t('usage_limit_cannot_be_negati_3ff4441679', lang))
                return
            
            if usage_limit > 1000:
                await message.reply(t('usage_limit_cannot_exceed_10_0e3280c0ba', lang))
                return
            
            # ✅ برای کوپن ادمین حداقل 1
            if coupon_data.get('coupon_type') == 'admin_special' and usage_limit < 1:
                await message.reply(t('admin_coupon_usage_limit_mus_12531849b3', lang))
                return
            
            coupon_data['usage_limit'] = usage_limit
            user_states[admin_id] = {
                'awaiting_coupon_create': True,
                'step': 'expiry_days',
                'coupon_data': coupon_data
            }
            
            await message.reply(
                t('b_step_4_of_4_expiry_days_b_9d6a2dbba3', lang),
                parse_mode=ParseMode.HTML
            )
        
        # ✅ مرحله expiry_days
        elif step == 'expiry_days':
            expiry_days = int(message.text.replace(',', '').replace(' ', '').strip())
            
            if expiry_days < 0:
                await message.reply(t('expiry_days_cannot_be_negati_29a2127499', lang))
                return
            
            if expiry_days > 365:
                await message.reply(t('expiry_days_cannot_exceed_36_421f6c7d19', lang))
                return
            
            coupon_data['expiry_days'] = expiry_days
            coupon_data['created_at'] = now_tehran_iso()
            coupon_data['status'] = 'active'
            coupon_data['used_count'] = 0
            coupon_data['used_by'] = []
            
            # ✅ فیلدهای مخصوص کوپن ادمین
            if coupon_data.get('coupon_type') == 'admin_special':
                coupon_data['locked_user_id'] = None  # اولین کاربری که استفاده کند
                coupon_data['user_usage'] = {}  # تعداد استفاده هر کاربر
            
            if expiry_days > 0:
                expiry_date = datetime.now() + timedelta(days=expiry_days)
                coupon_data['expiry_date'] = expiry_date.isoformat()
            else:
                coupon_data['expiry_date'] = None
            
            code = coupon_data.get('code', '')
            discount = coupon_data.get('discount', 0)
            usage_limit = coupon_data.get('usage_limit', 0)
            coupon_type = coupon_data.get('coupon_type', 'normal')
            
            COUPONS[code] = coupon_data
            save_coupons(COUPONS)
            
            user_states.pop(admin_id, None)
            expiry_text = f"{expiry_days} روز" if expiry_days > 0 else "نامحدود"
            limit_text = f"{usage_limit} بار" if usage_limit > 0 else "نامحدود"
            
            if coupon_type == 'admin_special':
                type_display = t('admin_private_coupon_a09bbca50a', lang)
                special_note = (
                    t('b_special_note_b_this_coupon_74008f5a12', lang, fa_parts=lambda: (f'{usage_limit}',), en_parts=lambda: (f'{usage_limit}',))
                )
            else:
                type_display = t('normal_coupon_62a30ffda0', lang)
                special_note = ""

            text = t('b_coupon_created_successfull_367bc33acb', lang, fa_parts=lambda: (f'{code}', f'{type_display}', f'{discount}', f'{limit_text}', f'{expiry_text}', f'{special_note}', f'{code}'), en_parts=lambda: (f'{code}', f'{type_display}', f'{discount}', f'{limit_text}', f'{expiry_text}', f'{special_note}', f'{code}'))
            
            buttons = [
                [InlineKeyboardButton(text=t('create_another_ae5262f5e5', lang), callback_data="admin_coupon_create")],
                [InlineKeyboardButton(text=t('coupons_list_2b3f1e787a', lang), callback_data="admin_coupons_list")],
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_coupons")]
            ]
            
            await message.reply(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
            
    except ValueError:
        await message.reply(t('please_enter_a_valid_number_afbbd0c0b3', lang))
    except Exception as e:
        logger.error(f"Error creating coupon: {e}", exc_info=True)
        err_type = html.escape(type(e).__name__)
        await message.reply(t('error_30ed4c9bcc', lang, fa_parts=lambda: (err_type,), en_parts=lambda: (err_type,)))
        user_states.pop(admin_id, None)
        
@router.callback_query(F.data == "admin_coupon_create")
@admin_only
async def admin_coupon_create_start(callback: CallbackQuery):
    """شروع ایجاد کوپن جدید - انتخاب نوع"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {
        'awaiting_coupon_create': True,
        'step': 'type',  # ✅ شروع از مرحله نوع
        'coupon_data': {}
    }
    
    text = t('b_create_new_coupon_choose_t_d54dc8cc69', lang)
    
    await callback.message.answer(text, parse_mode=ParseMode.HTML)
    
    await safe_answer(callback)
    
    
        
@router.callback_query(F.data == "admin_coupon_delete")
@admin_only
async def admin_coupon_delete_select(callback: CallbackQuery):
    """انتخاب کوپن برای حذف"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not COUPONS:
        await callback.answer(
            t('no_coupons_to_delete_9a5bbf6df3', lang),
            show_alert=True
        )
        return
    
    text = t('b_delete_coupon_b_please_sel_aa486d707b', lang)
    
    buttons = []
    
    sorted_coupons = sorted(COUPONS.items(), key=lambda x: x[1].get('created_at', ''), reverse=True)
    
    for code, data in sorted_coupons[:20]:
        status_emoji = "🟢" if data.get('status') == 'active' else "🔴" if data.get('status') == 'used' else "⚫"
        discount = data.get('discount', 0)
        usage_limit = data.get('usage_limit', 0)
        coupon_type = data.get('coupon_type', 'normal')
        
        # ✅✅✅ نمایش متفاوت برای کوپن ادمین
        if coupon_type == 'admin_special':
            user_usage = data.get('user_usage', {})
            total_used = sum(user_usage.values())
            limit_display = usage_limit if usage_limit > 0 else '∞'
            label = f"{status_emoji} 👑 {code} - {discount}% - {total_used}/{limit_display}"
        else:
            used_count = data.get('used_count', 0)
            limit_display = usage_limit if usage_limit > 0 else '∞'
            label = f"{status_emoji} {code} - {discount}% - {used_count}/{limit_display}"
        
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"admin_coupon_delete_confirm_{code}",
            style="danger"
        )])
    
    if len(COUPONS) > 20:
        buttons.append([InlineKeyboardButton(
            text=t('and_more_coupons_57a0f145f7', lang, fa_parts=lambda: (f'{len(COUPONS) - 20}',), en_parts=lambda: (f'{len(COUPONS) - 20}',)),
            callback_data="noop"
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_coupons"
    )])
    
    await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    
    
@router.callback_query(F.data.startswith("admin_coupon_delete_confirm_"))
@admin_only
async def admin_coupon_delete_confirm(callback: CallbackQuery):
    """تأیید حذف کوپن"""
    
    code = callback.data.replace("admin_coupon_delete_confirm_", "")
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if code not in COUPONS:
        await callback.answer(
            t('coupon_not_found_a97baa7923', lang),
            show_alert=True
        )
        return
    
    coupon = COUPONS[code]
    coupon_type = coupon.get('coupon_type', 'normal')
    usage_limit = coupon.get('usage_limit', 0)
    limit_display = usage_limit if usage_limit > 0 else '∞'
    
    # ✅✅✅ محاسبه تعداد استفاده بر اساس نوع کوپن
    if coupon_type == 'admin_special':
        user_usage = coupon.get('user_usage', {})
        total_used = sum(user_usage.values())
        usage_display = f"{total_used}/{limit_display}"
        coupon_type_display = t('admin_coupon_58937466d8', lang)
        
        # جزئیات استفاده
        usage_details = ""
        if user_usage:
            for uid, cnt in user_usage.items():
                usage_details += f"\n   • کاربر {uid}: {cnt} بار"
    else:
        used_count = coupon.get('used_count', 0)
        usage_display = f"{used_count}/{limit_display}"
        coupon_type_display = t('normal_coupon_62a30ffda0', lang)
        usage_details = ""
    
    # وضعیت
    status_map = {
        'active': t('active_bbe0087e37', lang),
        'used': t('used_e84297e841', lang),
        'expired': t('expired_21e5445748', lang)
    }
    status_display = status_map.get(coupon.get('status', 'active'), coupon.get('status', 'نامشخص'))
    
    # تاریخ ایجاد
    created_at = coupon.get('created_at', 'نامشخص')
    if created_at and created_at != 'نامشخص':
        try:
            created_at = created_at[:16].replace('T', ' ')
        except Exception:
            pass
    
    # تاریخ انقضا
    expiry_date = coupon.get('expiry_date')
    expiry_display = t('unlimited_0d936642fc', lang)
    if expiry_date:
        try:
            expiry_dt = datetime.fromisoformat(expiry_date)
            expiry_display = expiry_dt.strftime('%Y-%m-%d %H:%M')
        except Exception:
            pass
    
    text = t('b_confirm_delete_coupon_b_co_4309d1192a', lang, fa_parts=lambda: (f'{code}', f'{coupon_type_display}', f"{coupon.get('discount', 0)}", f'{usage_display}', f'{usage_details}', f'{status_display}', f'{created_at}', f'{expiry_display}'), en_parts=lambda: (f'{code}', f'{coupon_type_display}', f"{coupon.get('discount', 0)}", f'{usage_display}', f'{usage_details}', f'{status_display}', f'{created_at}', f'{expiry_display}'))
    buttons = [
        [
            InlineKeyboardButton(
                text=t('yes_delete_deae44aaf5', lang),
                callback_data=f"admin_coupon_delete_execute_{code}",
                style="danger"
            ),
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data="admin_coupon_delete",
                style="primary"
            )
        ]
    ]
    
    await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    
    
    
@router.callback_query(F.data.startswith("admin_coupon_delete_execute_"))
@admin_only
async def admin_coupon_delete_execute(callback: CallbackQuery):
    """اجرای حذف کوپن"""
    
    code = callback.data.replace("admin_coupon_delete_execute_", "")
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if code not in COUPONS:
        await callback.answer(
            t('coupon_not_found_a97baa7923', lang),
            show_alert=True
        )
        return
    
    coupon_data = COUPONS[code]
    del COUPONS[code]
    save_coupons(COUPONS)
    
    logger.info(f"🗑️ coupon {code} cleared by admin {callback.from_user.id} deleted")
    if log_system:
        await log_system.log_admin_action(
            callback.from_user.id,
            "Coupon deleted",
            details=f"Code: {code} | Discount: {coupon_data.get('discount', 0)}% | Status: {coupon_data.get('status', 'Unspecified')}"
        )
    
    await callback.answer(
        t('coupon_deleted_successfully_76a64de9ca', lang, fa_parts=lambda: (f'{code}',), en_parts=lambda: (f'{code}',)),
        show_alert=True
    )
    
    await admin_coupons(callback)
    
    
    

@router.callback_query(F.data == "admin_coupons_list")
@admin_only
async def admin_coupons_list(callback: CallbackQuery):
    """لیست کوپن‌ها با نمایش دقیق کد"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not COUPONS:
        text = t('no_coupons_available_786e13ad19', lang)
        buttons = [
            [InlineKeyboardButton(text=t('i18n_admin_coupon_create_button', lang), callback_data="admin_coupon_create")],
            [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_coupons")]
        ]
        await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
        return
    
    sorted_coupons = sorted(COUPONS.items(), key=lambda x: x[1].get('created_at', ''), reverse=True)
    
    text = t('b_coupons_list_b_count_coupo_acbd4fa87e', lang, fa_parts=lambda: (f'{len(COUPONS)}',), en_parts=lambda: (f'{len(COUPONS)}',))
    
    for code, data in sorted_coupons[:20]:
        status_emoji = "🟢" if data.get('status') == 'active' else "🔴" if data.get('status') == 'used' else "⚫"
        
        expiry = data.get('expiry_date')
        if expiry:
            try:
                expiry_date = datetime.fromisoformat(expiry)
                ref_now = now_tehran() if expiry_date.tzinfo is not None else now_tehran().replace(tzinfo=None)
                if expiry_date < ref_now:
                    status_emoji = "🔴"
            except Exception:
                pass
        
        coupon_type = data.get('coupon_type', 'normal')
        discount = data.get('discount', 0)
        usage_limit = data.get('usage_limit', 0)
        
        # ✅✅✅ نمایش متفاوت برای کوپن ادمین
        if coupon_type == 'admin_special':
            # برای کوپن ادمین: مجموع استفاده‌ها
            user_usage = data.get('user_usage', {})
            total_used = sum(user_usage.values())
            limit_display = usage_limit if usage_limit > 0 else '∞'
            
            # نمایش 👑 برای کوپن ادمین
            text += f"{status_emoji} 👑 <code>{code}</code> - {discount}% - {total_used}/{limit_display}\n"
        else:
            # برای کوپن معمولی
            used_count = data.get('used_count', 0)
            limit_display = usage_limit if usage_limit > 0 else '∞'
            text += f"{status_emoji} <code>{code}</code> - {discount}% - {used_count}/{limit_display}\n"
    
    if len(COUPONS) > 20:
        text += f"\n... و {len(COUPONS) - 20} کوپن دیگر"
    
    buttons = [
        [InlineKeyboardButton(text=t('i18n_admin_coupon_create_button', lang), callback_data="admin_coupon_create")],
        [InlineKeyboardButton(text=t('delete_coupon_52c714868d', lang), callback_data="admin_coupon_delete")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_coupons")]
    ]
    
    await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    
    
     


def get_admin_configs_keyboard(lang: str = "fa") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t('add_config_7a6d8439b0', lang), callback_data="admin_add_config")],
        [InlineKeyboardButton(text=t('available_configs_050592610f', lang), callback_data="admin_list_configs")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel", style="danger")]
    ])

async def get_ready_packages_text(lang: str = "fa") -> tuple:
    """دریافت متن و دکمه‌های منوی بسته‌های آماده"""
    categories = READY_PACKAGES.get('categories', [])
    enabled = READY_PACKAGES.get('enabled', True)
    
    status_text = t('i18n_status_active', lang) if enabled else t('i18n_status_inactive', lang)
    restrict_extend = READY_PACKAGES.get('restrict_extend_to_same_category', False)
    restrict_status_fa = "🟢 روشن (تمدید فقط در همان دسته)" if restrict_extend else "🔴 خاموش (تمدید به همه دسته‌ها)"
    restrict_status_en = "🟢 ON (Same Category Only)" if restrict_extend else "🔴 OFF (All Categories Open)"
    
    total_packages = sum(len(cat.get('packages', [])) for cat in categories)
    
    if lang == "fa":
        text = t('b_ready_packages_management_8039a76616', lang, fa_parts=lambda: (f'{status_text}', f'{restrict_status_fa}', f'{len(categories)}', f'{total_packages}', f"{READY_PACKAGES.get('last_updated', 'N/A')}"))
        if categories:
            for cat in categories:
                status = t('i18n_ready_category_active', lang) if cat.get('is_active', True) else t('i18n_ready_category_inactive', lang)
                pkg_count = len(cat.get('packages', []))
                text += f"\n{cat.get('icon', '📦')} {safe_html(cat.get('name'))} - {status} ({pkg_count})\n"
                for pkg in cat.get('packages', []):
                    pkg_status = "✅" if pkg.get('is_active', True) else "❌"
                    volume = pkg.get('volume', 0)
                    days = pkg.get('days', 30)
                    price = pkg.get('price', 0)
                    ip_limit = pkg.get('ip_limit', 0)
                    
                    vol_display = "UNL" if volume == 0 else f"{volume}G"
                    
                    if ip_limit == 0:
                        text += f"  {pkg_status} {vol_display} - {days}d - {price:,}T (ID: {pkg.get('id')})\n"
                    else:
                        text += f"  {pkg_status} {vol_display} | {ip_limit}U - {days}d - {price:,}T (ID: {pkg.get('id')})\n"
        else:
            text += t('no_categories_cb4bd993b7', lang)
            text += t('use_add_category_to_start_04513ee9d7', lang)
        
        text += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
        text += t('select_an_option_194bca8aac', lang)
        
        buttons = [
            [InlineKeyboardButton(
                text=t('all_89ea45fab3', lang, fa_parts=lambda: (f"{(t('i18n_package_category_disable', lang) if enabled else t('i18n_package_category_enable', lang))}",)),
                callback_data="admin_packages_toggle"
            )],
            [InlineKeyboardButton(
                text=t('restrict_to_same_cat_bcb76a4f6b', lang, fa_parts=lambda: (f"{(t('i18n_package_restrict_on', lang) if restrict_extend else t('i18n_package_restrict_off', lang))}",)),
                callback_data="admin_toggle_restrict_extend"
            )],
            [InlineKeyboardButton(
                text=t('add_category_4cb08e66cb', lang),
                callback_data="admin_category_add"
            )],
            [InlineKeyboardButton(
                text=t('add_package_cdd7809488', lang),
                callback_data="admin_package_add"
            )],
            [InlineKeyboardButton(
                text=t('edit_category_e54029623f', lang),
                callback_data="admin_category_edit_select"
            )],
            [InlineKeyboardButton(
                text=t('delete_category_400c1164ef', lang),
                callback_data="admin_category_delete_select"
            )],
            [InlineKeyboardButton(
                text=t('back_0321ae0d40', lang),
                callback_data="admin_panel"
            )]
        ]
    else:
        text = t('b_ready_packages_management_8039a76616', lang, en_parts=lambda: (f'{status_text}', f'{restrict_status_en}', f'{len(categories)}', f'{total_packages}', f"{READY_PACKAGES.get('last_updated', 'N/A')}"))
        if categories:
            for cat in categories:
                status = t('i18n_ready_category_active', lang) if cat.get('is_active', True) else t('i18n_ready_category_inactive', lang)
                pkg_count = len(cat.get('packages', []))
                text += f"\n{cat.get('icon', '📦')} {safe_html(cat.get('name_en', cat.get('name')))} - {status} ({pkg_count})\n"
                for pkg in cat.get('packages', []):
                    pkg_status = "✅" if pkg.get('is_active', True) else "❌"
                    volume = pkg.get('volume', 0)
                    days = pkg.get('days', 30)
                    price = pkg.get('price', 0)
                    ip_limit = pkg.get('ip_limit', 0)
                    
                    vol_display = "UNL" if volume == 0 else f"{volume}G"
                    
                    if ip_limit == 0:
                        text += f"  {pkg_status} {vol_display} - {days}d - {price:,}T (ID: {pkg.get('id')})\n"
                    else:
                        text += f"  {pkg_status} {vol_display} | {ip_limit}U - {days}d - {price:,}T (ID: {pkg.get('id')})\n"
        else:
            text += t('no_categories_cb4bd993b7', lang)
            text += t('use_add_category_to_start_04513ee9d7', lang)
        
        text += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
        text += t('select_an_option_194bca8aac', lang)
        
        buttons = [
            [InlineKeyboardButton(
                text=t('all_89ea45fab3', lang, en_parts=lambda: (f"{(t('i18n_package_category_disable', lang) if enabled else t('i18n_package_category_enable', lang))}",)),
                callback_data="admin_packages_toggle"
            )],
            [InlineKeyboardButton(
                text=t('restrict_to_same_cat_bcb76a4f6b', lang, en_parts=lambda: (f"{(t('i18n_package_restrict_on', lang) if restrict_extend else t('i18n_package_restrict_off', lang))}",)),
                callback_data="admin_toggle_restrict_extend"
            )],
            [InlineKeyboardButton(
                text=t('add_category_4cb08e66cb', lang),
                callback_data="admin_category_add"
            )],
            [InlineKeyboardButton(
                text=t('add_package_cdd7809488', lang),
                callback_data="admin_package_add"
            )],
            [InlineKeyboardButton(
                text=t('edit_category_e54029623f', lang),
                callback_data="admin_category_edit_select"
            )],
            [InlineKeyboardButton(
                text=t('delete_category_400c1164ef', lang),
                callback_data="admin_category_delete_select"
            )],
            [InlineKeyboardButton(
                text=t('back_0321ae0d40', lang),
                callback_data="admin_panel"
            )]
        ]
    
    return text, buttons


async def show_ready_packages_menu(target):
    """نمایش منوی مدیریت بسته‌های آماده (هم برای CallbackQuery و هم برای Message)"""
    if isinstance(target, types.CallbackQuery):
        if not getattr(target, "from_user", None) or target.from_user.id != ADMIN_ID_INT:
            return await target.answer("⛔", show_alert=True)
        callback = target
        lang = get_user(callback.from_user.id).get('lang', 'fa')
        text, buttons = await get_ready_packages_text(lang)
        
        try:
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            if "message is not modified" not in str(e):
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer(
                    text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                    parse_mode=ParseMode.HTML
                )
        
        await safe_answer(callback)
            
    elif isinstance(target, types.Message):
        if not getattr(target, "from_user", None) or target.from_user.id != ADMIN_ID_INT:
            return
        message = target
        lang = get_user(message.from_user.id).get('lang', 'fa')
        text, buttons = await get_ready_packages_text(lang)
        
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )

# [Phase 3.1] format_package_volume and get_user_last_purchased_package moved to routers.shop


# [Phase 3.1] show_ready_categories and cancel_extend moved to routers.shop

@router.message(Command("test_keyboard"), IsAdmin())
async def cmd_test_keyboard(message: Message):
    """تست کیبورد خرید با دیباگ (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    lang = get_user(message.from_user.id).get('lang', 'fa')
    text = "🧪 <b>تست کیبورد خرید</b>\n\n"
    
    text += f"🔘 READY_PACKAGES.enabled: {READY_PACKAGES.get('enabled')}\n"
    text += f"📊 تعداد دسته‌ها: {len(READY_PACKAGES.get('categories', []))}\n\n"
    
    for cat in READY_PACKAGES.get('categories', []):
        active_packages = [p for p in cat.get('packages', []) if p.get('is_active', True)]
        text += f"📦 {safe_html(cat.get('name'))}: {len(active_packages)} بسته فعال\n"
        for pkg in active_packages:
            text += f"  • {pkg.get('volume')}GB - {pkg.get('price'):,} تومان\n"
    
    text += "\n🔄 کیبورد ساخته شده:\n"
    keyboard = get_purchase_keyboard(1, 30, lang)
    has_packages_button = False
    for row in keyboard.inline_keyboard:
        for btn in row:
            if btn.callback_data == "show_ready_categories":
                has_packages_button = True
                text += f"✅ دکمه بسته‌های آماده پیدا شد: {btn.text}\n"
    
    if not has_packages_button:
        text += "❌ دکمه بسته‌های آماده پیدا نشد!\n"
    
    await message.reply(text, parse_mode=ParseMode.HTML)
    await message.answer(
        "🛒 <b>کیبورد خرید</b>",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )  
        

# [Phase 3.1] show_category_packages, buy_specific_package, and show_ready_categories_keep_coupon moved to routers.shop

@router.message(Command("check_coupon"), IsAdmin())
async def cmd_check_coupon(message: Message):
    """بررسی وضعیت کوپن کاربر (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    user_id = message.from_user.id
    user_state = user_states.get(user_id, {})
    
    text = f"""
📊 <b>وضعیت کوپن</b>

━━━━━━━━━━━━━━━━━━━━━━
👤 کاربر: {user_id}
🏷️ کوپن فعال: {'✅' if user_state.get('coupon_applied') else '❌'}
📝 کد کوپن: {user_state.get('coupon_code', 'ندارد')}
💳 درصد تخفیف: {user_state.get('coupon_discount', 0)}%
━━━━━━━━━━━━━━━━━━━━━━
"""
    await message.reply(text, parse_mode=ParseMode.HTML)
    
    
    

# [Phase 3.1] pay_ready_package_balance and _process_pay_ready_package_balance moved to routers.shop

def get_admin_users_keyboard(page: int = 0, lang: str = "fa") -> InlineKeyboardMarkup:
    user_list = list(users.values())
    per_page = 10

    start = page * per_page
    end = start + per_page
    total_pages = (len(user_list) + per_page - 1) // per_page
    valid_orders = get_valid_orders()

    buttons = []

    # 🔍 دکمه سرچ (همیشه اول)
    buttons.append([InlineKeyboardButton(
        text=t('advanced_search_3871642329', lang),
        callback_data="admin_search_users",
        style="primary",
    )])

    for u in user_list[start:end]:
        user_id = u.get("id")
        name = u.get("name", "کاربر")[:20]
        balance = u.get("balance", 0)
        orders_count = len([
            o for o in valid_orders.values()
            if o.get("user_id") == user_id and o.get("status") == "approved"
        ])
        buttons.append([InlineKeyboardButton(
            text=f"👤 {name} - {balance:,} T ({orders_count})",
            callback_data=f"admin_user_{user_id}_0",
        )])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text=t('prev_3ae44fe5dd', lang),
                callback_data=f"admin_users_page_{page-1}",
            ))
        nav.append(InlineKeyboardButton(
            text=f"{page+1}/{total_pages}", callback_data="noop",
        ))
        if end < len(user_list):
            nav.append(InlineKeyboardButton(
                text=t('next_7fa7faf32c', lang),
                callback_data=f"admin_users_page_{page+1}",
            ))
        if nav:
            buttons.append(nav)

    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_panel", style="danger",
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_language_keyboard(user_id: int = None) -> InlineKeyboardMarkup:
    """ساخت کیبورد انتخاب زبان با نمایش زبان فعال"""
    
    # ✅ تشخیص زبان فعلی کاربر
    current_lang = 'fa'  # پیش‌فرض فارسی
    lang = get_user(user_id).get('lang', 'fa')
    
    if user_id:
        user = get_user(user_id)
        if user:
            current_lang = user.get('lang', 'fa')
    
    # ✅ تعیین style بر اساس زبان فعال
    fa_style = "primary" if current_lang == 'fa' else None
    en_style = "primary" if current_lang == 'en' else None
    
    # ✅ متن دکمه با علامت ✓ برای زبان فعال
    fa_text = t('message_67f879847b', current_lang)
    en_text = "🇬🇧 English ✓" if current_lang == 'en' else "🇬🇧 English"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=fa_text,
                callback_data="set_lang_fa",
                style=fa_style  # ✅ primary اگر فارسی فعال است
            ),
            InlineKeyboardButton(
                text=en_text,
                callback_data="set_lang_en",
                style=en_style  # ✅ primary اگر انگلیسی فعال است
            )
        ],
        [
            InlineKeyboardButton(
                text=t('main_menu_0cdd07a7cc', lang),
                callback_data="back_to_main",
                style="danger"
            )
        ]
    ])



@router.callback_query(F.data == "admin_ready_packages")
async def admin_ready_packages_menu(callback: CallbackQuery):
    """منوی مدیریت بسته‌های آماده"""
    await show_ready_packages_menu(callback)

@router.callback_query(F.data == "admin_packages_toggle")
@admin_only
async def admin_packages_toggle(callback: CallbackQuery):
    """فعال/غیرفعال کردن کل بسته‌ها"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    READY_PACKAGES['enabled'] = not READY_PACKAGES.get('enabled', True)
    READY_PACKAGES['last_updated'] = now_tehran_iso()
    configs_pool['ready_packages'] = READY_PACKAGES
    schedule_save(2.0)
    
    status = "فعال" if READY_PACKAGES['enabled'] else "غیرفعال"
    await callback.answer(
        t('packages_d_da1e48a48a', lang, fa_parts=lambda: (f'{status}',), en_parts=lambda: (f'{status}',)),
        show_alert=True
    )
    
    await show_ready_packages_menu(callback)

@router.callback_query(F.data == "admin_toggle_restrict_extend")
@admin_only
async def admin_toggle_restrict_extend(callback: CallbackQuery):
    """تغییر وضعیت محدودیت تمدید فقط در همان دسته"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    current = READY_PACKAGES.get('restrict_extend_to_same_category', False)
    new_val = not current
    READY_PACKAGES['restrict_extend_to_same_category'] = new_val
    READY_PACKAGES['last_updated'] = now_tehran_iso()
    configs_pool['ready_packages'] = READY_PACKAGES
    schedule_save(2.0)
    
    if new_val:
        alert_text = t('renewal_restricted_to_the_sa_aa9d215447', lang)
    else:
        alert_text = t('renewal_open_to_all_categori_e2afa9f1f4', lang)
        
    await callback.answer(alert_text, show_alert=True)
    await show_ready_packages_menu(callback)

admin_packages_restrict_toggle = admin_toggle_restrict_extend

@router.callback_query(F.data == "admin_category_add")
@admin_only
async def admin_category_add_start(callback: CallbackQuery):
    """شروع افزودن دسته جدید"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {
        'awaiting_category_add': True,
        'step': 'name',
        'category_data': {}
    }
    
    await callback.message.answer(
        t('b_add_new_category_step_1_of_004970577b', lang),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)



def format_volume(value: Union[int, float], is_test: bool = False) -> str:
    """
    نمایش هوشمند حجم
    
    is_test=False:
        ورودی بر حسب GB است.
        اگر 0 باشد => نامحدود
        اگر کمتر از 1GB باشد با MB نمایش می‌دهد.
    
    is_test=True:
        ورودی بر حسب MB است.
        اگر 0 باشد => نامحدود
        اگر کمتر از 1024MB باشد با MB نمایش می‌دهد.
        اگر بیشتر باشد با GB نمایش می‌دهد.
    """
    if value is None or value <= 0:
        return "نامحدود"
    if is_test:
        mb = value
        
        if mb >= 1024:
            gb = mb / 1024
            if gb >= 10:
                return f"{gb:.0f} GB"
            elif gb >= 1:
                return f"{gb:.1f} GB"
            else:
                return f"{gb:.2f} GB"
        
        if mb >= 100:
            return f"{mb:.0f} MB"
        elif mb >= 10:
            return f"{mb:.1f} MB"
        else:
            return f"{mb:.2f} MB"
    gb = value
    
    if gb < 0.001:  # کمتر از 1 مگابایت
        return "نامحدود"
    
    if gb < 1:
        mb = gb * 1024
        if mb >= 100:
            return f"{mb:.0f} MB"
        elif mb >= 10:
            return f"{mb:.1f} MB"
        else:
            return f"{mb:.2f} MB"
    
    if gb >= 10:
        return f"{gb:.0f} GB"
    elif gb >= 1:
        return f"{gb:.1f} GB"
    else:
        return f"{gb:.2f} GB"
        
@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_category_add'))
async def admin_category_add_process(message: Message):
    """پردازش مراحل افزودن دسته"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_04471c9b42', lang))
        return
    
    state = user_states.get(admin_id, {})
    step = state.get('step')
    category_data = state.get('category_data', {})
    
    if not step:
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_invalid_state', lang))
        return
    
    try:
        if step == 'name':
            category_data['name'] = message.text.strip()
            
            if not category_data['name']:
                await message.reply(t('name_cannot_be_empty_6f2d4a4cdd', lang))
                return
            
            user_states[admin_id] = {
                'awaiting_category_add': True,
                'step': 'name_en',
                'category_data': category_data
            }
            
            await message.reply(
                t('b_step_2_of_5_english_name_b_4aeb1916d4', lang),
                parse_mode=ParseMode.HTML
            )
        elif step == 'name_en':
            category_data['name_en'] = message.text.strip()
            
            if not category_data['name_en']:
                await message.reply(t('english_name_cannot_be_empty_b7c9368c36', lang))
                return
            
            user_states[admin_id] = {
                'awaiting_category_add': True,
                'step': 'icon',
                'category_data': category_data
            }
            
            await message.reply(
                t('b_step_3_of_5_icon_b_please_421f9f26c9', lang),
                parse_mode=ParseMode.HTML
            )
        elif step == 'icon':
            category_data['icon'] = message.text.strip() or '📦'
            
            user_states[admin_id] = {
                'awaiting_category_add': True,
                'step': 'description',
                'category_data': category_data
            }
            
            await message.reply(
                t('b_step_4_of_5_persian_descri_2a1fc9f766', lang),
                parse_mode=ParseMode.HTML
            )
        elif step == 'description':
            category_data['description'] = message.text.strip()
            
            user_states[admin_id] = {
                'awaiting_category_add': True,
                'step': 'description_en',
                'category_data': category_data
            }
            
            await message.reply(
                t('b_step_5_of_5_english_descri_1f24e48059', lang),
                parse_mode=ParseMode.HTML
            )
        elif step == 'description_en':
            category_data['description_en'] = message.text.strip()
            category_data['is_active'] = True
            category_data['inbound_id'] = None
            category_data['packages'] = []
            existing_ids = [c.get('id', 0) for c in READY_PACKAGES.get('categories', [])]
            new_id = max(existing_ids) + 1 if existing_ids else 1
            category_data['id'] = new_id
            category_data['order'] = len(READY_PACKAGES.get('categories', [])) + 1
            READY_PACKAGES['categories'].append(category_data)
            READY_PACKAGES['last_updated'] = now_tehran_iso()
            configs_pool['ready_packages'] = READY_PACKAGES
            schedule_save(2.0)
            await message.reply(
                t('b_category_added_successfull_9e88a71983', lang, fa_parts=lambda: (f"{category_data.get('name')}", f"{category_data.get('id')}", f"{category_data.get('icon', '📦')}", f"{category_data.get('description', 'ندارد')}"), en_parts=lambda: (f"{category_data.get('name')}", f"{category_data.get('id')}", f"{category_data.get('icon', '📦')}", f"{category_data.get('description', 'None')}")),
                parse_mode=ParseMode.HTML
            )
            user_states.pop(admin_id, None)
            await show_ready_packages_menu(message)
    
    except Exception as e:
        logger.error(f"Error adding category: {e}", exc_info=True)
        err_type = html.escape(type(e).__name__)
        await message.reply(t('i18n_error_prefix', lang, fa_parts=lambda: (err_type,), en_parts=lambda: (err_type,)))
        user_states.pop(admin_id, None)


@router.callback_query(F.data == "admin_category_edit_select")
@admin_only
async def admin_category_edit_select(callback: CallbackQuery):
    """انتخاب دسته برای ویرایش"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    categories = READY_PACKAGES.get('categories', [])
    
    if not categories:
        await callback.answer(t('no_categories_12db2a189e', lang), show_alert=True)
        return
    
    buttons = []
    for cat in categories:
        pkg_count = len(cat.get('packages', []))
        status = "🟢" if cat.get('is_active', True) else "🔴"
        buttons.append([InlineKeyboardButton(
            text=t('i18n_category_edit_option', lang, fa_parts=lambda: (status, cat.get('icon', '📦'), cat.get('name'), pkg_count), en_parts=lambda: (status, cat.get('icon', '📦'), cat.get('name_en') or cat.get('name'), pkg_count)),
            callback_data=f"admin_category_edit_{cat.get('id')}"  # ✅ این کالبک به هندلر admin_category_edit می‌رود
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_ready_packages"
    )])
    
    await callback.message.edit_text(
        t('b_select_category_to_edit_b_9296837cae', lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await safe_answer(callback)

@router.callback_query(F.data.startswith("admin_category_edit_field_"))
@admin_only
async def admin_category_edit_field_start(callback: CallbackQuery):
    """شروع ویرایش یک فیلد از دسته"""
    pattern = r"admin_category_edit_field_(\d+)_(.+)"
    match = re.match(pattern, callback.data)
    
    if not match:
        logger.error(f"❌ [start] Regex not matched: {callback.data}")
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    category_id = int(match.group(1))
    field = match.group(2)  # description, name, name_en, icon, description_en
    logger.info(f"🔍 [start] CALLBACK DATA: {callback.data}")
    logger.info(f"🔍 [start] category_id: {category_id}, field: {field}")
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    category = None
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            category = cat
            break
    
    if not category:
        await callback.answer(t('category_not_found_04182ef028', lang), show_alert=True)
        return
    
    field_names = {
        'name': (t('persian_name_eed23c0a5a', lang)),
        'name_en': (t('english_name_def200da34', lang)),
        'icon': (t('icon_3f64c6b19a', lang)),
        'description': (t('persian_description_89b952b8a1', lang)),
        'description_en': (t('english_description_10a0f95218', lang))
    }
    
    current_value = category.get(field, '')
    
    logger.info(f"🔍 [start] field: {field}, current_value: {current_value}")
    
    user_states[callback.from_user.id] = {
        'awaiting_category_edit': True,
        'category_id': category_id,
        'field': field
    }
    
    await callback.message.answer(
        t('b_edit_b_current_value_code_960c9fa333', lang, fa_parts=lambda: (f'{field_names.get(field, field)}', f'{current_value}'), en_parts=lambda: (f'{field_names.get(field, field)}', f'{current_value}')),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)
    
    
@router.callback_query(F.data.startswith("admin_category_edit_"))
@admin_only
async def admin_category_edit(callback: CallbackQuery):
    """ویرایش دسته با نمایش لیست اینباندها"""
    
    logger.info(f"🔍 admin_category_edit CALLED: {callback.data}")
    
    try:
        parts = callback.data.split("_")
        category_id = int(parts[3])
        logger.info(f"✅ category_id: {category_id}")
    except (ValueError, IndexError) as e:
        logger.error(f"❌ Error extracting category_id: {e}")
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    category = None
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            category = cat
            break
    
    if not category:
        await callback.answer(t('category_not_found_04182ef028', lang), show_alert=True)
        return
    
    status_text = "🟢 فعال" if category.get('is_active', True) else "🔴 غیرفعال"
    inbound_ids = category.get('inbound_ids', [])
    if not inbound_ids:
        old_inbound = category.get('inbound_id')
        if old_inbound:
            inbound_ids = [old_inbound]
            category['inbound_ids'] = inbound_ids
            category['inbound_id'] = None  # حذف کلید قدیمی
    inbound_info = "❌ پیش‌فرض (همانند کاربر)"
    if inbound_ids:
        from services.panel_api import get_inbound_display_names
        inbound_map = await get_inbound_display_names(include_disabled=True)
        inbound_names = [
            inbound_map[int(ib_id)]
            for ib_id in inbound_ids
            if str(ib_id).lstrip('-').isdigit() and int(ib_id) in inbound_map
        ]
        if inbound_names:
            inbound_info = "📡 اینباندهای اختصاصی:\n" + "\n".join([f"  • {safe_html(name)}" for name in inbound_names])
        elif not inbound_map:
            inbound_info = f"📡 اینباندهای انتخاب شده: {inbound_ids}"
        else:
            inbound_info = "❌ پیش‌فرض (همانند کاربر)"
    
    text = t('b_edit_category_b_id_persian_c04ea7eccb', lang, fa_parts=lambda: (f"{category.get('name')}", f"{category.get('id')}", f"{category.get('name')}", f"{category.get('name_en')}", f"{category.get('icon', '📦')}", f"{category.get('description', 'ندارد')}", f"{category.get('description_en', 'ندارد')}", f'{status_text}', f"{category.get('order', 0)}", f"{len(category.get('packages', []))}", f'{inbound_info}'), en_parts=lambda: (f"{category.get('name')}", f"{category.get('id')}", f"{category.get('name')}", f"{category.get('name_en')}", f"{category.get('icon', '📦')}", f"{category.get('description', 'None')}", f"{category.get('description_en', 'None')}", f'{status_text}', f"{category.get('order', 0)}", f"{len(category.get('packages', []))}", f'{inbound_info}'))
    
    buttons = [
        [InlineKeyboardButton(
            text=t('edit_persian_name_779315ad82', lang),
            callback_data=f"admin_category_edit_field_{category_id}_name"
        )],
        [InlineKeyboardButton(
            text=t('edit_english_name_bd33577079', lang),
            callback_data=f"admin_category_edit_field_{category_id}_name_en"
        )],
        [InlineKeyboardButton(
            text=t('edit_icon_16401f6c6c', lang),
            callback_data=f"admin_category_edit_field_{category_id}_icon"
        )],
        [InlineKeyboardButton(
            text=t('edit_persian_description_9a0b6d3d51', lang),
            callback_data=f"admin_category_edit_field_{category_id}_description"
        )],
        [InlineKeyboardButton(
            text=t('edit_english_description_3c5f3968b7', lang),
            callback_data=f"admin_category_edit_field_{category_id}_description_en"
        )],
        [InlineKeyboardButton(
            text=f"🔘 {t('disable_26c50d45c1', lang) if category.get('is_active', True) else t('enable_a8db0a64c5', lang)}" if lang == "fa" else f"🔘 {t('disable_26c50d45c1', lang) if category.get('is_active', True) else t('enable_a8db0a64c5', lang)}",
            callback_data=f"admin_category_toggle_{category_id}"
        )],
        [InlineKeyboardButton(
            text=t('set_custom_inbounds_e4a4d437d7', lang),
            callback_data=f"admin_category_inbounds_{category_id}"
        )],
        [InlineKeyboardButton(
            text=t('back_to_list_eca8a9c338', lang),
            callback_data="admin_ready_packages"
        )]
    ]
    buttons.append([
    InlineKeyboardButton(
        text=t('edit_packages_in_this_catego_b793bce4a3', lang),
        callback_data=f"admin_category_packages_{category_id}",
        style="primary"
    )
    ])
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await callback.message.delete()
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
    
    await safe_answer(callback)
@router.callback_query(F.data.startswith("admin_package_edit_"))
@admin_only
async def admin_package_edit(callback: CallbackQuery):
    """ویرایش یک بسته خاص با نمایش تعداد کاربر"""
    
    parts = callback.data.split("_")
    try:
        category_id = int(parts[3])
        package_id = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    category = None
    package = None
    
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            category = cat
            for pkg in cat.get('packages', []):
                if pkg.get('id') == package_id:
                    package = pkg
                    break
            break
    
    if not category or not package:
        await callback.answer(t('i18n_package_or_category_not_found', lang), show_alert=True)
        return
    
    volume_display = "♾️ نامحدود" if package.get('volume', 0) == 0 else f"{package.get('volume', 0)} GB"
    
    ip_limit = package.get('ip_limit', 0)
    if ip_limit == 0:
        ip_display = "♾️ نامحدود"
    elif ip_limit == 1:
        ip_display = "۱ دستگاه"
    else:
        ip_display = f"{ip_limit} دستگاه"
    
    text = t('b_edit_package_b_category_cu_dc8be9802c', lang, fa_parts=lambda: (f'{package_id}', f"{category.get('name')}", f'{volume_display}', f"{package.get('days', 0)}", f"{package.get('price', 0):,}", f'{ip_display}', f"{('🟢 فعال' if package.get('is_active', True) else '🔴 غیرفعال')}"), en_parts=lambda: (f'{package_id}', f"{category.get('name')}", f'{volume_display}', f"{package.get('days', 0)}", f"{package.get('price', 0):,}", f'{ip_display}', f"{('🟢 Active' if package.get('is_active', True) else '🔴 Inactive')}"))
    
    buttons = [
        [InlineKeyboardButton(
            text=t('edit_volume_0_unlimited_5f41393615', lang),
            callback_data=f"package_edit_volume_{category_id}_{package_id}"
        )],
        [InlineKeyboardButton(
            text=t('edit_duration_10ab7193fb', lang),
            callback_data=f"package_edit_days_{category_id}_{package_id}"
        )],
        [InlineKeyboardButton(
            text=t('edit_price_6485ea7434', lang),
            callback_data=f"package_edit_price_{category_id}_{package_id}"
        )],
        [InlineKeyboardButton(
            text=t('edit_users_0_unlimited_fa344d0b0d', lang),
            callback_data=f"package_edit_ip_limit_{category_id}_{package_id}"
        )],
        [InlineKeyboardButton(
            text=f"🔘 {t('disable_26c50d45c1', lang) if package.get('is_active', True) else t('enable_a8db0a64c5', lang)}" if lang == "fa" else f"🔘 {t('disable_26c50d45c1', lang) if package.get('is_active', True) else t('enable_a8db0a64c5', lang)}",
            callback_data=f"package_toggle_{category_id}_{package_id}"
        )],
        [InlineKeyboardButton(
            text=t('delete_package_fa7086d0da', lang),
            callback_data=f"package_delete_{category_id}_{package_id}",
            style="danger"
        )],
        [InlineKeyboardButton(
            text=t('back_to_packages_list_56583592c2', lang),
            callback_data=f"admin_category_packages_{category_id}"
        )]
    ]
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)
@router.callback_query(F.data.startswith("package_edit_volume_"))
@admin_only
async def package_edit_volume(callback: CallbackQuery):
    """شروع ویرایش حجم بسته"""
    
    parts = callback.data.split("_")
    try:
        category_id = int(parts[3])
        package_id = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {
        'awaiting_package_edit': True,
        'category_id': category_id,
        'package_id': package_id,
        'edit_field': 'volume'
    }
    
    await callback.message.answer(
        t('b_edit_package_volume_b_plea_c9502e9a6f', lang),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)

@router.callback_query(F.data.startswith("package_edit_days_"))
@admin_only
async def package_edit_days(callback: CallbackQuery):
    """شروع ویرایش مدت بسته"""
    
    parts = callback.data.split("_")
    try:
        category_id = int(parts[3])
        package_id = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {
        'awaiting_package_edit': True,
        'category_id': category_id,
        'package_id': package_id,
        'edit_field': 'days'
    }
    
    await callback.message.answer(
        t('b_edit_package_duration_b_pl_6bd595fae8', lang),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)


@router.callback_query(F.data.startswith("package_edit_ip_limit_"))
@admin_only
async def package_edit_ip_limit(callback: CallbackQuery):
    """شروع ویرایش محدودیت IP بسته"""
    
    parts = callback.data.split("_")
    try:
        category_id = int(parts[4])
        package_id = int(parts[5])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {
        'awaiting_package_edit': True,
        'category_id': category_id,
        'package_id': package_id,
        'edit_field': 'ip_limit'
    }
    
    await callback.message.answer(
        t('b_edit_package_ip_limit_b_pl_1ae2993c45', lang),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)
    
    
@router.callback_query(F.data.startswith("package_edit_price_"))
@admin_only
async def package_edit_price(callback: CallbackQuery):
    """شروع ویرایش قیمت بسته"""
    
    parts = callback.data.split("_")
    try:
        category_id = int(parts[3])
        package_id = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {
        'awaiting_package_edit': True,
        'category_id': category_id,
        'package_id': package_id,
        'edit_field': 'price'
    }
    
    await callback.message.answer(
        t('b_edit_package_price_b_pleas_6b09678b29', lang),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)
@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_package_edit'))
async def save_package_edit(message: Message):
    """ذخیره ویرایش فیلد بسته با پشتیبانی از IP Limit و حجم نامحدود"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_68c51319f6', lang))
        return
    
    state = user_states.get(admin_id, {})
    category_id = state.get('category_id')
    package_id = state.get('package_id')
    edit_field = state.get('edit_field')
    
    if not category_id or not package_id or not edit_field:
        user_states.pop(admin_id, None)
        await message.reply("❌ خطا: اطلاعات نامعتبر")
        return
    
    try:
        new_value = int(message.text.replace(',', '').replace(' ', '').strip())
        if edit_field == 'volume' and (new_value < 0 or new_value > 1000):
            await message.reply(t('volume_must_be_between_0_and_35c477f9da', lang))
            return
        
        if edit_field == 'days' and (new_value < 1 or new_value > 365):
            await message.reply(t('duration_must_be_between_1_a_9735cb0bea', lang))
            return
        
        if edit_field == 'price' and new_value <= 0:
            await message.reply(t('price_must_be_greater_than_z_058fa0364a', lang))
            return
        
        if edit_field == 'ip_limit' and new_value < 0:
            await message.reply(t('ip_limit_cannot_be_negative_d64a026dd3', lang))
            return
        for cat in READY_PACKAGES.get('categories', []):
            if cat.get('id') == category_id:
                for pkg in cat.get('packages', []):
                    if pkg.get('id') == package_id:
                        old_value = pkg.get(edit_field)
                        pkg[edit_field] = new_value
                        READY_PACKAGES['last_updated'] = now_tehran_iso()
                        configs_pool['ready_packages'] = READY_PACKAGES
                        schedule_save(2.0)
                        
                        field_names = {
                            'volume': t('volume_c445e9f42c', lang),
                            'days': t('duration_dd7080d087', lang),
                            'price': t('price_7442679634', lang),
                            'ip_limit': t('ip_limit_4cbb9d738f', lang)
                        }
                        
                        display_value = "نامحدود" if edit_field == 'volume' and new_value == 0 else new_value
                        if edit_field == 'ip_limit':
                            display_value = "نامحدود" if new_value == 0 else new_value
                        
                        await message.reply(
                            f"✅ <b>{field_names.get(edit_field, edit_field)} با موفقیت بروزرسانی شد!</b>\n\n"
                            f"📊 مقدار قدیم: {old_value}\n"
                            f"📊 مقدار جدید: {display_value}",
                            parse_mode=ParseMode.HTML
                        )
                        
                        user_states.pop(admin_id, None)
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(
                                text=t('back_to_package_edit_269bab40fb', lang),
                                callback_data=f"admin_package_edit_{category_id}_{package_id}"
                            )]
                        ])
                        await message.answer("🔄" if lang == "fa" else "🔄", reply_markup=keyboard)
                        return
        
        await message.reply(t('package_not_found_1847864740', lang))
        user_states.pop(admin_id, None)
        
    except ValueError:
        await message.reply(t('please_enter_a_valid_number_afbbd0c0b3', lang))
    except Exception as e:
        logger.error(f"Error editing package: {e}", exc_info=True)
        await message.reply(f"❌ خطا: {html.escape(type(e).__name__)}")
        user_states.pop(admin_id, None)
        
@router.callback_query(F.data.startswith("package_toggle_"))
@admin_only
async def package_toggle(callback: CallbackQuery):
    """فعال/غیرفعال کردن یک بسته"""
    
    parts = callback.data.split("_")
    try:
        category_id = int(parts[2])
        package_id = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            for pkg in cat.get('packages', []):
                if pkg.get('id') == package_id:
                    pkg['is_active'] = not pkg.get('is_active', True)
                    READY_PACKAGES['last_updated'] = now_tehran_iso()
                    configs_pool['ready_packages'] = READY_PACKAGES
                    schedule_save(2.0)
                    
                    status = "فعال" if pkg['is_active'] else "غیرفعال"
                    await callback.answer(
                        t('package_d_8257a85bcd', lang, fa_parts=lambda: (f'{status}',), en_parts=lambda: (f'{status}',)),
                        show_alert=True
                    )
                    await admin_package_edit(callback)
                    return
    
    await callback.answer("❌ بسته یافت نشد!", show_alert=True)

@router.callback_query(F.data.startswith("package_delete_"))
@admin_only
async def package_delete(callback: CallbackQuery):
    """حذف یک بسته"""
    
    parts = callback.data.split("_")
    try:
        category_id = int(parts[2])
        package_id = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    text = t('b_confirm_delete_package_b_a_54391162c7', lang)
    buttons = [
        [
            InlineKeyboardButton(text=t('yes_delete_78fa0c3a17', lang), callback_data=f"package_confirm_delete_{category_id}_{package_id}", style="danger"),
            InlineKeyboardButton(text=t('cancel_4197bafba5', lang), callback_data=f"admin_package_edit_{category_id}_{package_id}")
        ]
    ]
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)

@router.callback_query(F.data.startswith("package_confirm_delete_"))
@admin_only
async def package_confirm_delete(callback: CallbackQuery):
    """اجرای حذف بسته"""
    
    parts = callback.data.split("_")
    try:
        category_id = int(parts[3])
        package_id = int(parts[4])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            packages = cat.get('packages', [])
            for i, pkg in enumerate(packages):
                if pkg.get('id') == package_id:
                    del packages[i]
                    READY_PACKAGES['last_updated'] = now_tehran_iso()
                    configs_pool['ready_packages'] = READY_PACKAGES
                    schedule_save(2.0)
                    
                    await callback.answer(
                        t('package_deleted_successfully_01df308fd1', lang),
                        show_alert=True
                    )
                    await admin_category_packages(callback)
                    return
    
    await callback.answer("❌ بسته یافت نشد!", show_alert=True)
    
@router.callback_query(F.data.startswith("admin_category_packages_"))
@admin_only
async def admin_category_packages(callback: CallbackQuery):
    """نمایش لیست بسته‌های یک دسته برای ویرایش"""
    
    try:
        category_id = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    category = None
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            category = cat
            break
    
    if not category:
        await callback.answer(t('i18n_category_not_found_bang', lang), show_alert=True)
        return
    
    packages = category.get('packages', [])
    
    text = t('b_manage_packages_in_b_packa_5e4c8e22ef', lang, fa_parts=lambda: (f"{category.get('name')}", f'{len(packages)}'), en_parts=lambda: (f"{category.get('name')}", f'{len(packages)}'))
    
    buttons = []
    
    for pkg in packages:
        pkg_id = pkg.get('id')
        volume = pkg.get('volume', 0)
        days = pkg.get('days', 0)
        price = pkg.get('price', 0)
        is_active = pkg.get('is_active', True)
        
        status_icon = "🟢" if is_active else "🔴"
        label = f"{status_icon} {volume}GB - {days} روز - {price:,} تومان (ID: {pkg_id})"
        
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"admin_package_edit_{category_id}_{pkg_id}"
        )])
    buttons.append([InlineKeyboardButton(
        text=t('add_new_package_to_this_cate_87cfa3060f', lang),
        callback_data=f"admin_package_add_category_{category_id}",
        style="success"
    )])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_to_category_edit_8e04786a54', lang),
        callback_data=f"admin_category_edit_{category_id}"
    )])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)
 
 
 
# ============================================
# هندلرهای تنظیمات هشدار
# ============================================

@router.callback_query(F.data == "admin_alert_settings")
@admin_only
async def admin_alert_settings(callback: CallbackQuery):
    """نمایش تنظیمات سیستم هشدار"""
    
    global alert_system_settings
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    # ✅ بارگذاری تنظیمات از دیتابیس
    if 'alert_settings' in configs_pool and isinstance(configs_pool['alert_settings'], dict):
        alert_system_settings.update(configs_pool['alert_settings'])
    
    # ✅ اگر alert_system وجود دارد، از تنظیمات واقعی آن استفاده کن
    if alert_system:
        enabled = alert_system.enabled
        volume_thresholds = alert_system.volume_thresholds
        expiry_warnings = alert_system.expiry_warnings
    else:
        enabled = alert_system_settings.get('enabled', True)
        volume_thresholds = alert_system_settings.get('volume_thresholds', [10, 5])
        expiry_warnings = alert_system_settings.get('expiry_warnings', [7, 3, 1])
    
    # وضعیت سیستم
    system_status = t('i18n_status_active', lang) if enabled else t('i18n_status_inactive', lang)
    log_status = t('i18n_status_connected', lang) if alert_system and alert_system.log_system else t('i18n_status_disconnected', lang)
    cache_status = t('i18n_status_active', lang) if alert_system else t('i18n_status_inactive', lang)

    text = t('b_alert_settings_b_b_system_982f1a729d', lang, fa_parts=lambda: (f'{system_status}', f'{volume_thresholds}', f'{expiry_warnings}', f'{log_status}', f'{cache_status}'), en_parts=lambda: (f'{system_status}', f'{volume_thresholds}', f'{expiry_warnings}', f'{log_status}', f'{cache_status}'))
    
    buttons = [
        [InlineKeyboardButton(
            text=f"🔘 {(t('disable_26c50d45c1', lang) if enabled else t('enable_a8db0a64c5', lang))}",
            callback_data="admin_alert_toggle"
        )],
        [
            InlineKeyboardButton(
                text=t('volume_8a20bc23c8', lang),
                callback_data="admin_alert_volume"
            ),
            InlineKeyboardButton(
                text=t('expiry_12b4e2e0c4', lang),
                callback_data="admin_alert_expiry"
            )
        ],
        [
            InlineKeyboardButton(
                text=t('check_now_87c2bce5f7', lang),
                callback_data="admin_check_alerts"
            ),
            InlineKeyboardButton(
                text=t('clear_cache_cf44f66e3d', lang),
                callback_data="admin_clear_alert_cache"
            )
        ],
        [InlineKeyboardButton(
            text=t('clear_history_648c7d668a', lang),
            callback_data="admin_clear_alert_history"
        )],
        [InlineKeyboardButton(
            text=t('back_to_admin_65c13ab7ff', lang),
            callback_data="admin_panel"
        )]
    ]
    
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing settings message: {e}")
    
    await callback.answer()


@router.callback_query(F.data == "admin_alert_toggle")
@admin_only
async def admin_alert_toggle(callback: CallbackQuery):
    """فعال/غیرفعال کردن سیستم هشدار"""
    
    global alert_system_settings
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    # تغییر وضعیت
    new_status = not alert_system_settings.get('enabled', True)
    alert_system_settings['enabled'] = new_status
    
    # اعمال به سیستم
    if alert_system:
        alert_system.enabled = new_status
    
    # ذخیره در دیتابیس
    configs_pool['alert_settings'] = alert_system_settings
    from core.task_manager import sync_legacy_task_setting
    sync_legacy_task_setting("alert_worker", enabled=new_status)
    schedule_save(2.0)
    
    # لاگ تغییر
    if alert_system and alert_system.log_system:
        await alert_system.log_system.log_admin_action(
            callback.from_user.id,
            f"{'Enabled' if new_status else 'Disabled'} alert system",
            details=f"New status: {'Enabled' if new_status else 'Disabled'}"
        )
    
    await callback.answer(
        t('alert_system_e77882a617', lang, fa_parts=lambda: (f"{('فعال' if new_status else 'غیرفعال')}",), en_parts=lambda: (f"{('enabled' if new_status else 'disabled')}",)),
        show_alert=True
    )
    
    await admin_alert_settings(callback)


# ============================================
# هندلرهای تغییر آستانه‌ها
# ============================================

@router.callback_query(F.data == "admin_alert_volume")
@admin_only
async def admin_alert_volume_settings(callback: CallbackQuery):
    """تنظیم آستانه‌های حجم - ۲ آستانه + اتمام خودکار"""
    
    global alert_system_settings
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    current = alert_system_settings.get('volume_thresholds', [10, 5])
    
    text = t('b_volume_alert_thresholds_b_8b592078e4', lang, fa_parts=lambda: (f'{current}',), en_parts=lambda: (f'{current}',))
    
    # ✅ فقط ۲ آستانه
    presets = [
        ([10, 5], "استاندارد", "Standard"),
        ([20, 10], "زودهنگام", "Early"),
        ([15, 5], "متوسط", "Medium"),
        ([5, 2], "دیرهنگام", "Late"),
    ]
    
    buttons = []
    for thresholds, fa_label, en_label in presets:
        label = t('i18n_volume_preset_label', lang, fa_parts=lambda: (f'📊 {thresholds[0]}', t('i18n_percent_sign', lang), f'{thresholds[1]}', t('i18n_percent_sign', lang), f'۰{t("i18n_percent_sign", lang)}', t('i18n_expired_word', lang), fa_label if lang == 'fa' else en_label), en_parts=lambda: (f'📊 {thresholds[0]}', t('i18n_percent_sign', lang), f'{thresholds[1]}', t('i18n_percent_sign', lang), f'0{t("i18n_percent_sign", lang)}', t('i18n_expired_word', lang), fa_label if lang == 'fa' else en_label))
        callback_data = f"alert_volume_set_{thresholds[0]}_{thresholds[1]}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=callback_data)])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_to_settings_8ad1a33ecb', lang),
        callback_data="admin_alert_settings"
    )])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("alert_volume_set_"))
@admin_only
async def alert_volume_set(callback: CallbackQuery):
    """اعمال آستانه حجم انتخاب شده"""
    
    global alert_system_settings
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    # استخراج آستانه‌ها (۲ تا)
    parts = callback.data.split("_")[3:]
    thresholds = [int(p) for p in parts]
    
    # ✅ ذخیره فقط ۲ آستانه
    alert_system_settings['volume_thresholds'] = thresholds
    
    # اعمال به سیستم
    if alert_system:
        alert_system.volume_thresholds = thresholds
    
    # ذخیره در دیتابیس
    configs_pool['alert_settings'] = alert_system_settings
    schedule_save(2.0)
    
    # لاگ تغییر
    if alert_system and alert_system.log_system:
        await alert_system.log_system.log_admin_action(
            callback.from_user.id,
            "Changed volume alert thresholds",
            details=f"New thresholds: {thresholds}% + auto exhaust"
        )
    
    await callback.answer(
        t('volume_thresholds_set_to_aut_3b7df8407c', lang, fa_parts=lambda: (f'{thresholds}',), en_parts=lambda: (f'{thresholds}',)),
        show_alert=True
    )
    
    await admin_alert_settings(callback)


@router.callback_query(F.data == "admin_alert_expiry")
@admin_only
async def admin_alert_expiry_settings(callback: CallbackQuery):
    """تنظیم آستانه‌های انقضا - ۲ آستانه + انقضای خودکار"""
    
    global alert_system_settings
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    current = alert_system_settings.get('expiry_warnings', [7, 3, 1])
    
    text = t('b_expiry_alert_thresholds_b_6c911cedb0', lang, fa_parts=lambda: (f'{current}',), en_parts=lambda: (f'{current}',))
    
    presets = [
        ([7, 3, 1], "کامل", "Full"),
        ([3, 1], "استاندارد", "Standard"),
        ([7, 2], "زودهنگام", "Early"),
        ([5, 2], "متوسط", "Medium"),
        ([2, 1], "دیرهنگام", "Late"),
    ]
    
    days_word = t('i18n_days_word', lang)
    exp_word = t('i18n_expired_word', lang)
    buttons = []
    for thresholds, fa_label, en_label in presets:
        lbl = fa_label if lang == 'fa' else en_label
        parts_text = " - ".join(f"{th} {days_word}" for th in thresholds)
        btn_text = f"📅 {parts_text} - {exp_word} ({lbl})"
        cb_data = "alert_expiry_set_" + "_".join(str(th) for th in thresholds)
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_to_settings_8ad1a33ecb', lang),
        callback_data="admin_alert_settings"
    )])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data.startswith("alert_expiry_set_"))
@admin_only
async def alert_expiry_set(callback: CallbackQuery):
    """اعمال آستانه انقضا انتخاب شده"""
    
    global alert_system_settings
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    # استخراج آستانه‌ها (۲ تا)
    parts = callback.data.split("_")[3:]
    thresholds = [int(p) for p in parts]
    
    # ✅ ذخیره فقط ۲ آستانه
    alert_system_settings['expiry_warnings'] = thresholds
    
    # اعمال به سیستم
    if alert_system:
        alert_system.expiry_warnings = thresholds
    
    # ذخیره در دیتابیس
    configs_pool['alert_settings'] = alert_system_settings
    schedule_save(2.0)
    
    # لاگ تغییر
    if alert_system and alert_system.log_system:
        await alert_system.log_system.log_admin_action(
            callback.from_user.id,
            "Changed expiry alert thresholds",
            details=f"New thresholds: {thresholds} days + auto expire"
        )
    
    await callback.answer(
        t('expiry_thresholds_set_to_day_a7fdc95a04', lang, fa_parts=lambda: (f'{thresholds}',), en_parts=lambda: (f'{thresholds}',)),
        show_alert=True
    )
    
    await admin_alert_settings(callback)


# ============================================
# بررسی دستی هشدارها
# ============================================

@router.callback_query(F.data == "admin_check_alerts")
@admin_only
async def admin_check_alerts(callback: CallbackQuery):
    """بررسی دستی هشدارها"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not alert_system:
        await callback.answer(
            t('alert_system_not_initialized_f6e5d08106', lang),
            show_alert=True
        )
        return
    
    await callback.answer(
        t('checking_30bda0641f', lang),
        show_alert=False
    )
    
    try:
        # ارسال پیام موقت
        temp_msg = await callback.message.answer(
            t('checking_services_5f12eaa9ec', lang)
        )
        
        # اجرای بررسی
        await alert_system.check_all_services()
        
        # لاگ بررسی دستی
        if alert_system.log_system:
            await alert_system.log_system.log_admin_action(
                callback.from_user.id,
                "Manual alert check",
                details="Manual execution of service check"
            )
        
        # به‌روزرسانی پیام موقت
        await temp_msg.edit_text(
            t('alert_check_completed_f0dee7721f', lang)
        )
        
        # حذف پیام موقت بعد از 3 ثانیه
        await asyncio.sleep(3)
        try:
            await temp_msg.delete()
        except Exception:
            pass
        
    except Exception as e:
        logger.error(f"Error during manual check: {e}", exc_info=True)
        err_type = html.escape(type(e).__name__)
        try:
            await callback.message.answer(
                t('error_1f472deba8', lang, fa_parts=lambda: (err_type,), en_parts=lambda: (err_type,))
            )
        except Exception:
            pass


# ============================================
# پاک کردن کش هشدارها
# ============================================

@router.callback_query(F.data == "admin_clear_alert_cache")
@admin_only
async def admin_clear_alert_cache(callback: CallbackQuery):
    """پاک کردن کش موقت هشدارها (تاریخچه حفظ می‌شود)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not alert_system:
        await callback.answer(
            t('alert_system_not_initialized_f6e5d08106', lang),
            show_alert=True
        )
        return
    
    try:
        # پاک کردن کش موقت
        alert_system.clear_cache()
        
        # لاگ
        if alert_system.log_system:
            await alert_system.log_system.log_admin_action(
                callback.from_user.id,
                "Cleared alert temp cache",
                details="History preserved"
            )
        
        await callback.answer(
            t('temp_cache_cleared_history_p_3ef5b16125', lang),
            show_alert=True
        )
        
        await admin_alert_settings(callback)
        
    except Exception as e:
        logger.error(f"Error clearing cache: {e}", exc_info=True)
        err_type = html.escape(type(e).__name__)
        await callback.answer(
            t('error_30ed4c9bcc', lang, fa_parts=lambda: (err_type,), en_parts=lambda: (err_type,)),
            show_alert=True
        )


# ============================================
# پاک کردن کامل تاریخچه
# ============================================

@router.callback_query(F.data == "admin_clear_alert_history")
@admin_only
async def admin_clear_alert_history(callback: CallbackQuery):
    """پاک کردن کامل تاریخچه هشدارها (با تایید)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not alert_system:
        await callback.answer(
            t('alert_system_not_initialized_f6e5d08106', lang),
            show_alert=True
        )
        return
    
    # نمایش تایید
    text = t('b_clear_all_alert_history_b_fee899fa92', lang)
    confirm_text = t('yes_clear_it_82c8def9ed', lang)
    cancel_text = t('cancel_4197bafba5', lang)
    
    buttons = [
        [InlineKeyboardButton(
            text=confirm_text,
            callback_data="admin_confirm_clear_history"
        )],
        [InlineKeyboardButton(
            text=cancel_text,
            callback_data="admin_alert_settings"
        )]
    ]
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.callback_query(F.data == "admin_confirm_clear_history")
@admin_only
async def admin_confirm_clear_history(callback: CallbackQuery):
    """تایید پاک کردن کامل تاریخچه"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not alert_system:
        await callback.answer(
            t('alert_system_not_initialized_f6e5d08106', lang),
            show_alert=True
        )
        return
    
    # پاک کردن کامل
    alert_system.clear_all_history()
    
    # لاگ
    if alert_system.log_system:
        await alert_system.log_system.log_admin_action(
            callback.from_user.id,
            "Cleared alert history",
            details="All history and cache cleared"
        )
    
    await callback.answer(
        t('history_cleared_34aa7603eb', lang),
        show_alert=True
    )
    
    await admin_alert_settings(callback)



        
        
@router.callback_query(F.data.startswith("admin_category_inbounds_"))
@admin_only
async def admin_category_inbounds(callback: CallbackQuery):
    """تنظیم اینباندهای اختصاصی برای دسته (با صفحه پیشرفته)"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    try:
        category_id = int(callback.data.split("_")[3])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    category = None
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            category = cat
            break
    
    if not category:
        await callback.answer(t('i18n_category_not_found_bang', lang), show_alert=True)
        return
    
    current_inbound_ids = category.get('inbound_ids', [])
    if not current_inbound_ids:
        old_inbound = category.get('inbound_id')
        if old_inbound:
            current_inbound_ids = [old_inbound]
    
    prefix = f"category_{category_id}"
    back_key = f"{prefix}_{callback.from_user.id}_back"
    INBOUND_BACK_DATA[back_key] = {
        'back_callback': f"admin_category_edit_{category_id}",
        'extra_data': {'category_id': category_id}
    }
    
    await show_inbound_manager(
        message=callback.message,
        title=f"تنظیم اینباندهای {category.get('name')}",
        current_inbound_ids=current_inbound_ids,
        callback_data_prefix=prefix,
        back_callback=f"inbound_back_{prefix}",
        admin_id=callback.from_user.id,
        show_default_button=True,
        show_clear_button=True,
        update_existing=False,
        extra_data={'category_id': category_id}
    )


@router.callback_query(F.data.startswith("inbound_save_category_"))
@admin_only
async def inbound_save_category(callback: CallbackQuery):
    """ذخیره اینباندهای دسته"""
    
    category_id = int(callback.data.replace("inbound_save_category_", ""))
    prefix = f"category_{category_id}"
    temp_key = f"{prefix}_{callback.from_user.id}"
    
    if temp_key not in TEMP_INBOUND_SELECTION:
        await callback.answer("❌ هیچ تغییری یافت نشد", show_alert=True)
        return
    
    current_list = TEMP_INBOUND_SELECTION[temp_key]
    category = None
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            category = cat
            break
    
    if not category:
        await callback.answer("❌ دسته یافت نشد!", show_alert=True)
        return
    category['inbound_ids'] = current_list
    category['inbound_id'] = None
    READY_PACKAGES['last_updated'] = now_tehran_iso()
    configs_pool['ready_packages'] = READY_PACKAGES
    schedule_save(2.0)
    if temp_key in TEMP_INBOUND_SELECTION:
        del TEMP_INBOUND_SELECTION[temp_key]
    
    await callback.answer(f"✅ {len(current_list)} اینباند ذخیره شد", show_alert=True)
    try:
        await admin_category_edit(callback.model_copy(update={"data": f"admin_category_edit_{category_id}"}))
    except Exception as e:
        logger.error(f"Error returning to category editing: {e}")
    

@router.message(Command("check_storage"), IsAdmin())
async def cmd_check_storage(message: Message):
    """بررسی وضعیت ذخیره‌سازی داده‌ها (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    text = "📊 <b>بررسی وضعیت ذخیره‌سازی</b>\n\n"
    text += "📦 <b>داده‌های در حافظه (READY_PACKAGES):</b>\n"
    text += f"  • وضعیت: {'فعال' if READY_PACKAGES.get('enabled') else 'غیرفعال'}\n"
    text += f"  • تعداد دسته‌ها: {len(READY_PACKAGES.get('categories', []))}\n"
    for cat in READY_PACKAGES.get('categories', []):
        inbound_ids = cat.get('inbound_ids', [])
        text += f"  • {safe_html(cat.get('name'))}: اینباندها = {inbound_ids if inbound_ids else 'پیش‌فرض'}\n"
    packages_data = configs_pool.get('ready_packages', {})
    text += "\n📁 <b>داده‌های ذخیره شده در دیتابیس (configs_pool):</b>\n"
    text += f"  • وجود دارد: {'✅' if packages_data else '❌'}\n"
    if packages_data:
        text += f"  • تعداد دسته‌ها: {len(packages_data.get('categories', []))}\n"
        for cat in packages_data.get('categories', []):
            inbound_ids = cat.get('inbound_ids', [])
            text += f"  • {safe_html(cat.get('name'))}: اینباندها = {inbound_ids if inbound_ids else 'پیش‌فرض'}\n"
    test_settings = configs_pool.get('test_service', {})
    text += "\n🧪 <b>تنظیمات تست:</b>\n"
    text += f"  • اینباندها: {test_settings.get('inbound_ids', [])}\n"
    
    text += f"\n🕐 زمان بررسی: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}"
    
    await message.reply(text, parse_mode=ParseMode.HTML)


    
def migrate_category_inbound_data():
    """مهاجرت داده‌های اینباند دسته از تک به چندتایی"""
    for cat in READY_PACKAGES.get('categories', []):
        if 'inbound_id' in cat and cat['inbound_id']:
            if 'inbound_ids' not in cat or not cat['inbound_ids']:
                cat['inbound_ids'] = [cat['inbound_id']]
                logger.info(f"✅ Category inbound migration {cat.get('name')}: {cat['inbound_id']} -> {cat['inbound_ids']}")
            cat['inbound_id'] = None
    
    READY_PACKAGES['last_updated'] = now_tehran_iso()
    configs_pool['ready_packages'] = READY_PACKAGES
    schedule_save(2.0)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_category_edit'))
async def admin_category_edit_field_save(message: Message):
    """ذخیره ویرایش فیلد دسته"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    logger.info(f"🔍 [save] BEFORE READ user_states[{admin_id}] = {user_states.get(admin_id, {})}")
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_68c51319f6', lang))
        return
    
    state = user_states.get(admin_id, {})
    category_id = state.get('category_id')
    field = state.get('field')
    
    logger.info(f"🔍 [save] AFTER READ - category_id: {category_id}, field: {field}")
    
    if not category_id or not field:
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_invalid_info', lang))
        return
    
    new_value = message.text.strip()
    if not new_value:
        await message.reply(t('value_cannot_be_empty_3d66911b6e', lang))
        return
    
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            old_value = cat.get(field)
            cat[field] = new_value
            READY_PACKAGES['last_updated'] = now_tehran_iso()
            
            configs_pool['ready_packages'] = READY_PACKAGES
            schedule_save(2.0)
            
            await message.reply(
                t('b_field_updated_successfully_42cb0a7f3a', lang, fa_parts=lambda: (f'{old_value}', f'{new_value}'), en_parts=lambda: (f'{old_value}', f'{new_value}')),
                parse_mode=ParseMode.HTML
            )
            
            user_states.pop(admin_id, None)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_to_edit_category_733bfd109e', lang),
                    callback_data=f"admin_category_edit_{category_id}"
                )]
            ])
            await message.answer("🔄" if lang == "fa" else "🔄", reply_markup=keyboard)
            return
    
    await message.reply(t('category_not_found_04182ef028', lang))
    user_states.pop(admin_id, None)

@router.callback_query(F.data.startswith("admin_category_toggle_"))
@admin_only
async def admin_category_toggle(callback: CallbackQuery):
    """فعال/غیرفعال کردن یک دسته"""
    
    try:
        category_id = int(callback.data.split("_")[3])
    except Exception:
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    for cat in READY_PACKAGES.get('categories', []):
        if cat.get('id') == category_id:
            cat['is_active'] = not cat.get('is_active', True)
            READY_PACKAGES['last_updated'] = now_tehran_iso()
            
            configs_pool['ready_packages'] = READY_PACKAGES
            schedule_save(2.0)
            
            status = "فعال" if cat.get('is_active') else "غیرفعال"
            await callback.answer(
                t('category_d_034fd72c63', lang, fa_parts=lambda: (f"{cat.get('name')}", f'{status}'), en_parts=lambda: (f"{cat.get('name')}", f'{status}')),
                show_alert=True
            )
            
            await admin_category_edit(callback)
            return
    
    await callback.answer(t('category_not_found_04182ef028', lang), show_alert=True)

@router.callback_query(F.data == "admin_category_delete_select")
@admin_only
async def admin_category_delete_select(callback: CallbackQuery):
    """انتخاب دسته برای حذف"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    categories = READY_PACKAGES.get('categories', [])
    
    if not categories:
        await callback.answer(t('no_categories_12db2a189e', lang), show_alert=True)
        return
    
    buttons = []
    for cat in categories:
        pkg_count = len(cat.get('packages', []))
        buttons.append([InlineKeyboardButton(
            text=t('i18n_category_delete_option', lang, fa_parts=lambda: (cat.get('icon', '📦'), cat.get('name'), pkg_count), en_parts=lambda: (cat.get('icon', '📦'), cat.get('name'), pkg_count)),
            callback_data=f"admin_category_delete_{cat.get('id')}"
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_ready_packages"
    )])
    
    await callback.message.edit_text(
        t('b_select_category_to_delete_39ecbc20ef', lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_category_delete_"))
@admin_only
async def admin_category_delete(callback: CallbackQuery):
    """حذف دسته"""
    
    try:
        category_id = int(callback.data.split("_")[3])
    except Exception:
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    categories = READY_PACKAGES.get('categories', [])
    category_to_delete = None
    
    for cat in categories:
        if cat.get('id') == category_id:
            category_to_delete = cat
            categories.remove(cat)
            break
    
    if category_to_delete:
        READY_PACKAGES['last_updated'] = now_tehran_iso()
        configs_pool['ready_packages'] = READY_PACKAGES
        schedule_save(2.0)
        
        await callback.answer(
            t('category_and_packages_delete_35f9e6d37e', lang, fa_parts=lambda: (f"{category_to_delete.get('name')}", f"{len(category_to_delete.get('packages', []))}"), en_parts=lambda: (f"{category_to_delete.get('name')}", f"{len(category_to_delete.get('packages', []))}")),
            show_alert=True
        )
    else:
        await callback.answer(t('category_not_found_04182ef028', lang), show_alert=True)
    
    await show_ready_packages_menu(callback)



@router.callback_query(F.data == "admin_package_add")
@admin_only
async def admin_package_add_start(callback: CallbackQuery):
    """شروع افزودن بسته به دسته"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    categories = READY_PACKAGES.get('categories', [])
    
    if not categories:
        await callback.answer(t('create_a_category_first_e6ada8c83f', lang), show_alert=True)
        return
    
    buttons = []
    for cat in categories:
        if cat.get('is_active', True):
            buttons.append([InlineKeyboardButton(
                text=f"{cat.get('icon', '📦')} {cat.get('name')}",
                callback_data=f"admin_package_add_category_{cat.get('id')}"
            )])
    
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_ready_packages"
    )])
    
    await callback.message.edit_text(
        t('b_select_category_for_new_pa_1ce4d874af', lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await safe_answer(callback)


@router.callback_query(F.data.startswith("admin_package_add_category_"))
@admin_only
async def admin_package_add_category(callback: CallbackQuery):
    """انتخاب دسته و شروع افزودن بسته"""
    
    try:
        category_id = int(callback.data.split("_")[4])
    except Exception:
        await callback.answer(t('i18n_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_states[callback.from_user.id] = {
        'awaiting_package_add': True,
        'category_id': category_id,
        'step': 'volume',
        'package_data': {}
    }
    
    await callback.message.answer(
        t('b_add_new_package_step_1_of_315fb6aa4f', lang),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_package_add'))
async def admin_package_add_process(message: Message):
    """پردازش مراحل افزودن بسته با پشتیبانی از IP Limit و حجم نامحدود"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('cancelled_4e2b535e69', lang))
        return
    
    state = user_states.get(admin_id, {})
    step = state.get('step')
    category_id = state.get('category_id')
    package_data = state.get('package_data', {})
    
    if not step or not category_id:
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_invalid_state', lang))
        return
    
    try:
        if step == 'volume':
            volume = int(message.text.replace(',', '').replace(' ', '').strip())
            if volume < 0 or volume > 1000:
                await message.reply(t('volume_must_be_between_0_and_35c477f9da', lang))
                return
            
            package_data['volume'] = volume
            user_states[admin_id] = {
                'awaiting_package_add': True,
                'category_id': category_id,
                'step': 'days',
                'package_data': package_data
            }
            
            await message.reply(
                t('b_step_2_of_4_duration_days_77136d3d00', lang),
                parse_mode=ParseMode.HTML
            )
        
        elif step == 'days':
            days = int(message.text.replace(',', '').replace(' ', '').strip())
            if days < 1 or days > 365:
                await message.reply(t('duration_must_be_between_1_a_9735cb0bea', lang))
                return
            
            package_data['days'] = days
            user_states[admin_id] = {
                'awaiting_package_add': True,
                'category_id': category_id,
                'step': 'price',
                'package_data': package_data
            }
            
            await message.reply(
                t('b_step_3_of_4_price_toman_b_89b49fd8f8', lang),
                parse_mode=ParseMode.HTML
            )
        
        elif step == 'price':
            price = int(message.text.replace(',', '').replace(' ', '').strip())
            if price <= 0:
                await message.reply(t('price_must_be_greater_than_z_058fa0364a', lang))
                return
            
            package_data['price'] = price
            user_states[admin_id] = {
                'awaiting_package_add': True,
                'category_id': category_id,
                'step': 'ip_limit',
                'package_data': package_data
            }
            
            await message.reply(
                t('b_step_4_of_4_ip_limit_b_ple_4950679f53', lang),
                parse_mode=ParseMode.HTML
            )
        
        elif step == 'ip_limit':
            ip_limit = int(message.text.replace(',', '').replace(' ', '').strip())
            if ip_limit < 0:
                await message.reply(t('ip_limit_cannot_be_negative_d64a026dd3', lang))
                return
            
            package_data['ip_limit'] = ip_limit
            package_data['is_active'] = True
            
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('id') == category_id:
                    existing_ids = [p.get('id', 0) for p in cat.get('packages', [])]
                    package_data['id'] = max(existing_ids) + 1 if existing_ids else 1
                    
                    cat['packages'].append(package_data)
                    READY_PACKAGES['last_updated'] = now_tehran_iso()
                    
                    configs_pool['ready_packages'] = READY_PACKAGES
                    schedule_save(2.0)
                    
                    volume_display = "نامحدود" if package_data.get('volume', 0) == 0 else f"{package_data.get('volume')} GB"
                    ip_display = "نامحدود" if package_data.get('ip_limit', 0) == 0 else package_data.get('ip_limit')
                    
                    await message.reply(
                        t('b_package_added_successfully_6a38682392', lang, fa_parts=lambda: (f"{cat.get('name')}", f'{volume_display}', f"{package_data.get('days')}", f"{package_data.get('price'):,}", f'{ip_display}', f"{package_data.get('id')}"), en_parts=lambda: (f"{cat.get('name')}", f'{volume_display}', f"{package_data.get('days')}", f"{package_data.get('price'):,}", f'{ip_display}', f"{package_data.get('id')}")),
                        parse_mode=ParseMode.HTML
                    )
                    
                    user_states.pop(admin_id, None)
                    await show_ready_packages_menu(message)
                    return
            
            await message.reply(t('category_not_found_04182ef028', lang))
            user_states.pop(admin_id, None)
    
    except ValueError:
        await message.reply(t('please_enter_a_valid_number_afbbd0c0b3', lang))
    except Exception as e:
        logger.error(f"Error adding package: {e}", exc_info=True)
        err_type = html.escape(type(e).__name__)
        await message.reply(t('i18n_error_prefix', lang, fa_parts=lambda: (err_type,), en_parts=lambda: (err_type,)))
        user_states.pop(admin_id, None)



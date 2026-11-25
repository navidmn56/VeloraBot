import sys
if __name__ == "__main__":
    sys.modules.setdefault("main", sys.modules[__name__])

user_ai_requests = {}
from strings import t
import asyncio
import hashlib
import json
import logging
import os
import shutil
from balance_system import (
    register_balance_handlers,
    approve_balance,
    increase_balance,
    process_balance_amount,
)
import time
import html
import secrets
import base64
import math
import psutil
import re
import traceback
from io import BytesIO
import aiohttp
from datetime import datetime, timedelta
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo
from collections.abc import MutableMapping
from time import monotonic
from typing import Any, Dict, List, Optional, Union, Tuple

from database import TEHRAN_TZ, now_tehran, now_tehran_iso

NOW = now_tehran_iso
from qr_file_system import (
    DOWNLOADED_FILES,
    delete_downloaded_files as _delete_downloaded_files_impl,
    generate_qr_code as _generate_qr_code,
    track_downloaded_file,
)
from ping_utils import smart_ping
from emoji_sticker_system import (
    PREMIUM_EMOJI_IDS,
    STICKER_IDS,
    premium_emoji as _premium_emoji,
    send_sticker as _send_sticker,
)


def premium_emoji(name: str, fallback: str = "📌") -> str:
    return _premium_emoji(name, fallback)


async def send_sticker(
    chat_id: int,
    sticker_key: str,
    fallback_emoji: str = "📌",
    reply_markup: Any = None,
) -> bool:
    return await _send_sticker(
        bot,
        chat_id,
        sticker_key,
        fallback_emoji,
        reply_markup,
        logger,
    )


from yarl import URL
from wireguard_system import build_wireguard_config
from dynamic_phrases import format_start_greeting
from sms_payment_system import sms_payment_manager, register_sms_payment_handlers
from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    CopyTextButton,
    BufferedInputFile,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    ReactionTypeEmoji,
)
import unicodedata
from config import (
    BOT_TOKEN, ADMIN_ID, LOG_BOT_TOKEN, LOG_CHANNEL_ID, SUPPORT_USERNAME,
    BANK_CARD_NUMBER, BANK_CARD_HOLDER, BANK_NAME, BANK_CARD_HOLDER_EN, BANK_NAME_EN,
    SENAI_PANEL_URL, SENAI_PANEL_USERNAME, SENAI_PANEL_PASSWORD, SENAI_SUB_URL,
    SENAI_PANEL_ENABLED, is_senai_panel_enabled,
    GEMINI_API_KEY, GEMINI_ENABLED, GEMINI_MODEL, GEMINI_TEMPERATURE, GEMINI_MAX_TOKENS, GEMINI_DAILY_LIMIT,
    AUTO_AI_RESPONSE,
    START_REACTION_EMOJI,
)
import config as app_config
from daily_usage_system import (
    gregorian_to_jalali,
    handle_daily_usage_request,
    usage_collector,
    usage_store,
)
from text_utils import (
    clean_username,
    extract_numeric_id,
    format_size,
    format_traffic_info as _format_traffic_info,
    normalize_text,
    progress_bar,
    safe_str,
    strip_decorations,
    to_persian_digits,
)
from db_storage import (
    DATA_DIR,
    DB_FILES,
    _db_cache,
    _db_modified,
    _last_save_time,
    clear_db_cache,
    ensure_data_directory,
    get_db_cache_size,
    load_json,
    save_json,
)
from database import (
    users,
    orders,
    referrals,
    configs_pool,
    feedbacks,
    chats,
    BLACKLIST,
    SHOP_STATUS,
    READY_PACKAGES,
    USER_TEST_USAGE,
    TEST_SERVICE_STATUS,
    get_test_service_display,
    reset_database_collections,
    get_valid_orders,
    update_order,
    load_test_usage,
    save_test_usage,
    _init_default_settings,
    _init_default_settings_if_needed,
    _init_empty_databases,
    try_full_restore_from_backup,
    save_all,
    load_all_data,
    register_post_load_hook,
    register_pre_save_hook,
    register_migration_hook,
)
from user_manager import (
    user_states,
    COUPONS_FILE,
    COUPONS,
    load_coupons,
    save_coupons,
    is_coupon_valid_for_user,
    add_coupon_fields_to_user,
    get_user,
    can_user_purchase,
    save_coupon_to_user_db,
    load_coupon_from_user_db,
    clear_coupon_from_user_db,
    fully_remove_coupon_from_user,
    consume_coupon,
    release_coupon_on_cancel,
    debug_coupon_state,
    update_user,
    record_purchase,
    add_balance,
    reduce_balance,
    reset_balance,
    calculate_price,
    get_admin_id_int,
    set_admin_id,
)


def get_user_safe(user_id: Union[int, str, None]) -> Optional[dict]:
    """
    دریافت ایمن اطلاعات کاربر از دیتابیس بدون ایجاد خودکار رکورد جدید در صورت عدم وجود.
    کلید را به صورت رشته در دیکشنری users جستجو می‌کند.
    """
    if user_id is None:
        return None
    return users.get(str(user_id))


from services.background_tasks import (
    get_memory_usage,
    get_database_size,
    cleanup_expired_states,
    optimize_storage,
    send_health_report,
    send_weekly_detailed_report,
    cleanup_expired_states_task,
    sync_deleted_configs_task,
    weekly_cleanup,
    health_monitor,
    disk_space_monitor,
    weekly_detailed_report_task,
    config_pool_monitor,
    log_rotation,
    panel_limits_reset,
    memory_monitor,
    daily_usage_collector_worker,
    start_background_tasks,
    set_bot,
    get_bot,
    set_log_system,
    get_log_system,
)

from utils.guards import admin_only
from utils.helpers import safe_answer, safe_html
from utils.filters import IsAdmin
from utils.rate_limiter import buy_rate_limiter, rate_limit
from utils.payment_guard import payment_guard, PaymentInProgressError
from utils.states import (
    OrderStates,
    BalanceStates,
    SupportStates,
    AIStates,
    AdminStates,
    InState,
)

from services.ai_service import (
    GEMINI_PROMPT_CACHE,
    GEMINI_PROMPT_CACHE_LOCK,
    set_ai_button_enabled,
    get_ai_button_enabled,
)

gemini_client = None
gemini_error_message = None


# [Phase 0/2] Core state stores
from core.state_stores import (
    TempStore,
    TEMP_INBOUND_SELECTION,
    INBOUND_BACK_DATA,
    USER_INBOUND_SELECTION,
    USER_TEST_SETTINGS,
    _tg_user_cache,
)

log_system = None
shared_connector = None


LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
LOG_LEVEL = logging.DEBUG if os.getenv("DEBUG_MODE", "").lower() in ("1", "true", "yes") else logging.INFO

logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler()]
)
root_logger = logging.getLogger()
root_logger.setLevel(LOG_LEVEL)
for handler in root_logger.handlers:
    handler.setLevel(LOG_LEVEL)

console_handler = next(
    (
        handler for handler in root_logger.handlers
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
    ),
    None,
)
if console_handler is None:
    console_handler = logging.StreamHandler()
    root_logger.addHandler(console_handler)
console_handler.setLevel(LOG_LEVEL)
console_formatter = logging.Formatter(LOG_FORMAT)
console_formatter.converter = lambda timestamp: datetime.fromtimestamp(timestamp, TEHRAN_TZ).timetuple()
console_handler.setFormatter(console_formatter)

# امنیت لاگ: جلوگیری از لاگ شدن آپدیت‌های حساس تلگرام و توکن‌ها در کتابخانه‌های ثالث
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)

bot_session = AiohttpSession(timeout=30)
bot = Bot(token=BOT_TOKEN, session=bot_session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
fallback_router = Router(name="fallback")
try:
    ADMIN_ID_INT = int(ADMIN_ID)
except (ValueError, TypeError):
    ADMIN_ID_INT = 0
set_admin_id(ADMIN_ID_INT)

# ==================== ماژول‌های روتر فاز ۱ و ۲ و ۴ ====================
from routers import (
    force_join_router,
    broadcast_router,
    search_router,
    admin_test_router,
    admin_shop_router,
    admin_packages_router,
    admin_tools_router,
    ai_purchase_advisor_router,
    admin_ai_router,
    ai_assistant_router,
    shop_router,
    orders_router,
    payments_router,
    admin_orders_router,
    confirm_approve_package,
    select_inbound_for_order,
    confirm_approve_with_inbound,
    reject_receipt,
    admin_close_msg,
    approve_direct,
    reject_direct,
    handle_wrong_file_type,
    get_order_category_name,
    backfill_order_category,
    admin_orders,
    view_order,
    request_receipt,
    view_receipt,
    cancel_order_admin,
    confirm_cancel_order_admin,
    fulfill_vpn_order,
    approve_order,
    reject_order,
    pay_balance,
    _process_pay_balance,
    send_config_to_user,
    admin_get_config,
    cancel_payment,
    retry_receipt,
    get_user_display_name,
    handle_receipt,
    custom_payment_receipt_amount,
    custom_payment_receipt_confirm,
    custom_payment_receipt_manual,
    custom_payment_receipt,
    custom_payment_receipt_manual_volume,
    custom_payment_receipt_manual_days,
    approve_receipt,
    select_user_inbound,
    set_user_inbound_default,
    cmd_fix_categories,
    set_user_inbound,
    remove_user_inbound,
    select_multiple_inbounds,
    toggle_user_inbound,
    show_inbound_selection,
    toggle_inbound,
    default_inbounds,
    apply_coupon_page,
    cancel_coupon,
    clear_inbounds,
    select_all_inbounds,
    save_inbounds,
    cancel_inbounds,
    clear_user_inbounds,
    save_user_inbounds,
    change_package_inbound,
    set_package_inbound,
    extend_service,
    extend_service_start,
    buy_service,
    vol_down,
    vol_up,
    day_down,
    day_up,
    is_valid_checkout_state,
    reject_expired_checkout,
    pay_card,
    send_receipt_reminder,
    cancel_order_direct,
    create_client_in_panel,
    get_backup_list,
    check_shop_status_and_notify,
    check_membership,
    check_membership_detailed,
    show_verification_page,
    process_verify_membership,
    admin_force_join_settings,
    force_join_toggle,
    admin_broadcast_send,
    _is_admin_broadcasting,
    detect_safe_parse_mode,
    admin_broadcast_start,
    broadcast_type_selected,
    advanced_search_users,
    format_search_results_text,
    get_search_results_keyboard,
    _cache_set,
    _cache_get,
    register_search_handlers,
    set_bot_for_all_routers,
    # Phase 4 AI exports
    GeminiClient,
    conversation_memory,
    check_ai_limit,
    increment_ai_usage,
    reset_ai_limits,
    user_ai_requests,
    get_gemini_client,
    gemini_error_message,
    AI_FEATURE_ENABLED,
    get_ai_button_enabled,
    set_ai_button_enabled,
    get_gemini_prompt_cache,
    init_ai,
    BAD_WORDS_FA,
    BAD_WORDS_EN,
    contains_bad_words,
    get_ai_button_context,
    normalize_ai_user_text,
    strip_repeated_ai_greeting,
    strip_ai_button_directives,
    get_active_ai_packages,
    build_ai_purchase_advisor_question,
    parse_ai_purchase_advisor_response,
    run_ai_purchase_advisor_turn,
    start_ai_purchase_advisor,
    start_ai_purchase_advisor_flow,
    start_new_ai_purchase_advisor,
    retry_ai_purchase_advisor,
    answer_ai_purchase_advisor_option,
    handle_ai_purchase_advisor,
    restore_ai_purchase_advisor_state,
    cmd_memory,
    admin_ai_settings,
    admin_toggle_ai_button,
    admin_ai_test,
    admin_ai_reset_limits,
    cmd_test_full,
    cmd_reset_ai_limit,
    cmd_ai_debug,
    cmd_test_ai,
    cmd_ai_status,
    should_include_ai_user_context,
    build_ai_user_database_context,
    is_ai_question,
    _format_ai_package_button_label,
    build_ai_reply_keyboard,
    handle_ai_menu_action,
    get_ai_response,
    cmd_ai,
    ai_chat_start,
    start_ai_support_chat,
    clear_ai_memory,
    exit_ai_chat,
    process_ai_chat_message,
    auto_ai_response,
    # Phase 5 exports
    user_account_router,
    my_account,
    show_order_status,
    request_order_number,
    handle_order_number_input,
    coupon_status,
    invite_friends,
    change_language,
    set_lang_fa,
    set_lang_en,
    support_router,
    create_chat,
    add_message,
    close_chat,
    _clear_ticket_input_state,
    auto_pause_user_ticket_if_active,
    auto_pause_ticket_on_callback_middleware,
    auto_pause_ticket_on_message_middleware,
    get_user_ticket_keyboard,
    get_active_chats,
    get_user_support_configs,
    format_ticket_user_details,
    open_support_ticket,
    support_create_ticket,
    ticket_no_config,
    ticket_config_selected,
    user_close_ticket,
    user_pause_ticket_input,
    user_continue_ticket,
    support_message_description,
    relay_support_message,
    handle_ticket_button_press,
    handle_chat_message,
    save_feedback,
    handle_feedback,
    handle_feedback_comment,
    configs_view_router,
    _delete_downloaded_files,
    _render_config_page,
    copy_all_links_file,
    back_to_config_page,
    back_to_main_from_file,
    show_config_text,
    show_wireguard_config,
    send_wireguard_config_file,
    show_config_text_page,
    show_config_text_refresh,
    show_single_qr,
    show_subscription_qr,
    my_configs,
    show_all_my_configs,
    view_single_config,
    send_config_with_qr_option,
    get_config_view_keyboard,
    get_config_caption,
    _get_order_telegram_proxy,
    _order_has_wireguard,
    PLATFORM_GUIDES,
    show_platform_guide,
    platform_android,
    platform_ios,
    platform_windows,
    platform_back_to_config,
)

class _MainGeminiProxy:
    def __getattr__(self, name):
        c = get_gemini_client()
        if c is not None:
            return getattr(c, name)
        raise RuntimeError("Gemini client not initialized")
    def __bool__(self):
        return get_gemini_client() is not None

gemini_client = _MainGeminiProxy()

set_bot_for_all_routers(bot)
dp.include_router(force_join_router)
dp.include_router(broadcast_router)
dp.include_router(search_router)
dp.include_router(admin_test_router)
dp.include_router(admin_shop_router)
dp.include_router(admin_packages_router)
dp.include_router(admin_tools_router)
dp.include_router(ai_purchase_advisor_router)
dp.include_router(admin_ai_router)
dp.include_router(ai_assistant_router)
dp.include_router(configs_view_router)
dp.include_router(shop_router)
dp.include_router(orders_router)
dp.include_router(payments_router)
dp.include_router(admin_orders_router)
dp.include_router(user_account_router)
dp.include_router(support_router)
dp.include_router(fallback_router)

class CustomLogger:
    
    @staticmethod
    def log_event(event_type: str, message: str, user_id: int = None):
        user_suffix = f" (user_id={user_id})" if user_id else ""
        full_msg = f"{message}{user_suffix}"
        if event_type == 'ERROR':
            logger.error(full_msg)
        elif event_type == 'WARNING':
            logger.warning(full_msg)
        else:
            logger.info(full_msg)

config_lock = asyncio.Lock()
_order_creation_lock = asyncio.Lock()
# [Phase 0/2] Core debounced save worker
from core.save_scheduler import (
    schedule_save,
    _debounced_save_worker,
    _save_queue,
    set_save_task,
    get_save_task,
)
_save_task = None


def format_traffic_info(client: dict, traffic: dict = None, lang: str = "fa") -> str:
    return _format_traffic_info(client, traffic, lang, premium_emoji)


async def get_config_from_pool_safe(volume: int, days: int):
    async with config_lock:
        return get_config_from_pool(volume, days)


# ==================== ماژول‌های روتر فاز ۲.۱ (سرویس تست و اینباندها) ====================
from routers.admin_test import (
    InboundCB,
    OrderInboundCB,
    AdminTestPageCB,
    update_test_settings,
    get_admin_test_service_keyboard,
    build_admin_test_service_content,
    admin_test_service_settings,
    show_inbound_manager,
    inbound_selectall,
    inbound_toggle,
    inbound_default,
    inbound_clear,
    inbound_back,
    inbound_save,
    admin_test_inbounds,
    go_back_to_category_edit,
    go_back_to_test_service,
    go_back_to_admin_panel,
    admin_test_toggle,
    admin_test_edit_start,
    validate_test_volume,
    admin_test_edit_save,
    admin_test_service_settings_message,
    invalidate_test_users_cache,
    get_cached_sorted_test_users,
    admin_test_users,
    admin_test_all_users_settings,
    admin_test_user_select,
    admin_test_user_select_execute,
    admin_test_set_default,
    admin_test_set_default_save,
    admin_test_users_with_settings,
    admin_test_clear_all_settings_confirm,
    admin_test_clear_all_settings_execute,
    admin_test_user_reset_start,
    admin_test_user_reset_execute,
    admin_test_users_list,
    load_user_test_settings,
    save_user_test_settings,
    get_user_test_settings,
    _fmt_test_volume_gb,
    admin_test_user_volume,
    admin_test_user_days,
    admin_test_user_max,
    admin_test_user_settings_save,
    build_user_test_settings_content,
    admin_test_user_settings,
    admin_test_users_reset_all_confirm,
    admin_test_users_reset_all_execute,
    admin_test_stats,
    save_user_inbound_selection,
    load_user_inbound_selections,
)

def build_receipt_text(order: dict, lang: str = "fa", mode: str = "reminder") -> str:
    """متن یکپارچه درخواست رسید پرداخت"""
    RLM = "\u200F"
    
    order_id = order.get('order_id', '?')
    order_type = order.get('type', 'purchase')
    price = order.get('price', 0) or order.get('amount', 0)
    volume = order.get('volume', 0)
    days = order.get('days', 0)
    parent_order_id = order.get('parent_order_id')
    is_extend = parent_order_id is not None or order.get('is_extend', False)
    if lang == "en":
        category_name = order.get('category_name_en') or order.get('category_name') or ''
    else:
        category_name = order.get('category_name') or order.get('category_name_en') or ''
    category_id = order.get('category_id')
    if not category_name and category_id:
        for cat in READY_PACKAGES.get('categories', []):
            if cat.get('id') == category_id:
                if lang == "en":
                    category_name = cat.get('name_en') or cat.get('name') or ''
                else:
                    category_name = cat.get('name') or ''
                break
    is_balance_charge = (order_type == 'balance_charge')

    if mode == "paid":
        return t('b_payment_successful_b_order_cc6bf433a7', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f"{premium_emoji('id', '🆔')}", f'{order_id}', f'{RLM}'), en_parts=lambda: (f"{premium_emoji('id', '🆔')}", f'{order_id}'))

    icon = "📦"
    if category_id:
        for cat in READY_PACKAGES.get('categories', []):
            if cat.get('id') == category_id:
                icon = cat.get('icon', '📦')
                break
    
    card_emoji = premium_emoji('card', '💳')
    money_emoji = premium_emoji('money', '💰')
    id_emoji = premium_emoji('id', '🆔')
    user_emoji = premium_emoji('user', '👤')
    star_emoji = premium_emoji('star', '🏦')
    config_emoji = premium_emoji('config', icon)
    receipt_emoji = premium_emoji('receipt', '📸')
    info_emoji = premium_emoji('info', 'ℹ️')
    reload_emoji = premium_emoji('reload', '🔄')
    wallet_emoji = premium_emoji('wallet', '💰')
    note_emoji = premium_emoji('note', '📝')
    
    if volume == 0:
        volume_display = t('unlimited_b72dd6e126', lang)
    elif volume < 1:
        volume_display = f"{volume * 1024:.0f} MB"
    else:
        volume_display = f"{volume} GB"
    
    support_display = SUPPORT_USERNAME.strip() if SUPPORT_USERNAME and SUPPORT_USERNAME.strip() else "@my_name_is_navid"
    price_display = t('toman_287614cf02', lang, fa_parts=lambda: (f'{price:,}',), en_parts=lambda: (f'{price:,}',))
    amount_display = t('toman_287614cf02', lang, fa_parts=lambda: (f'{price:,}',), en_parts=lambda: (f'{price:,}',))
    tips_block = (
        t('b_important_notes_b_1_transf_88130d948c', lang, fa_parts=lambda: (f'{RLM}', f'{note_emoji}', f'{RLM}', f'{RLM}', f'{order_id}', f'{RLM}'), en_parts=lambda: (f'{note_emoji}', f'{order_id}'))
    )

    # ⏳ محاسبه مهلت پرداخت و معتبر بودن صفحه (تنظیمات پرداخت خودکار یا پیش‌فرض ربات)
    deadline_minutes = 30
    try:
        sms_cfg = configs_pool.get('sms_payment_settings', {})
        if sms_cfg.get('enabled'):
            deadline_minutes = int(sms_cfg.get('window_minutes', 30))
        else:
            if sms_payment_manager and sms_payment_manager.is_enabled():
                deadline_minutes = int(sms_payment_manager.get_window_minutes())
            elif 'default_payment_timeout' in configs_pool:
                deadline_minutes = int(configs_pool['default_payment_timeout'])
            else:
                deadline_minutes = 30
    except Exception:
        deadline_minutes = 30

    remaining_minutes = deadline_minutes
    created_at_str = order.get('created_at') if isinstance(order, dict) else None
    if created_at_str:
        try:
            created_dt = datetime.fromisoformat(created_at_str)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=TEHRAN_TZ)
            now = datetime.now(TEHRAN_TZ)
            elapsed_min = (now - created_dt).total_seconds() / 60
            if elapsed_min > 0:
                remaining_minutes = max(1, math.ceil(deadline_minutes - elapsed_min))
        except Exception:
            remaining_minutes = deadline_minutes

    if lang == "fa":
        deadline_line = f"مهلت ارسال فیش: {remaining_minutes} دقیقه دیگه"
    else:
        deadline_line = f"Receipt submission deadline: {remaining_minutes} minutes"

    tips_block = f"{tips_block}\n\n{deadline_line}"
    final_line = t('b_after_payment_please_send_3b43eaa1a1', lang, fa_parts=lambda: (f'{RLM}', f'{receipt_emoji}'), en_parts=lambda: (f'{receipt_emoji}',))
    if mode == "waiting":
        return t('b_receipt_received_b_order_c_aa7c9110e7', lang, fa_parts=lambda: (f'{RLM}', f'{receipt_emoji}', f'{RLM}', f'{id_emoji}', f'{order_id}', f'{RLM}', f'{money_emoji}', f'{price_display}', f'{RLM}'), en_parts=lambda: (f'{receipt_emoji}', f'{id_emoji}', f'{order_id}', f'{money_emoji}', f'{price_display}'))
    if mode == "card":
        card_num = ' '.join([BANK_CARD_NUMBER[i:i+4] for i in range(0, 16, 4)])
        category_display = category_name if category_name else (t('ready_package_272798b27e', lang))
        
        if lang == "fa":
            card_block = (
                t('b_card_number_b_code_code_ho_829fbb7b75', lang, fa_parts=lambda: (f'{RLM}', f'{card_emoji}', f'{RLM}', f'{card_num}', f'{RLM}', f'{user_emoji}', f'{BANK_CARD_HOLDER}', f'{RLM}', f'{star_emoji}', f'{BANK_NAME}', f'{RLM}', f'{info_emoji}', f'{support_display}'))
            )
        else:
            holder_name = (BANK_CARD_HOLDER_EN or "").strip() or BANK_CARD_HOLDER
            bank_display = (BANK_NAME_EN or "").strip() or BANK_NAME
            card_block = (
                t('b_card_number_b_code_code_ho_829fbb7b75', lang, en_parts=lambda: (f'{card_emoji}', f'{card_num}', f'{user_emoji}', f'{holder_name}', f'{star_emoji}', f'{bank_display}', f'{info_emoji}', f'{support_display}'))
            )
        if is_extend:
            return t('b_extension_payment_b_order_4a3c2f1d53', lang, fa_parts=lambda: (f'{RLM}', f'{reload_emoji}', f'{RLM}', f'{id_emoji}', f'{order_id}', f'{parent_order_id}', f'{RLM}', f'{config_emoji}', f'{category_display}', f'{RLM}', f'{volume_display}', f'{RLM}', f'{days}', f'{RLM}', f'{money_emoji}', f'{price_display}', f'{card_block}', f'{tips_block}', f'{final_line}'), en_parts=lambda: (f'{reload_emoji}', f'{id_emoji}', f'{order_id}', f'{parent_order_id}', f'{config_emoji}', f'{category_display}', f'{volume_display}', f'{days}', f'{money_emoji}', f'{price_display}', f'{card_block}', f'{tips_block}', f'{final_line}'))
        if is_balance_charge:
            return t('b_balance_top_up_payment_b_o_0259117500', lang, fa_parts=lambda: (f'{RLM}', f'{wallet_emoji}', f'{RLM}', f'{id_emoji}', f'{order_id}', f'{RLM}', f'{money_emoji}', f'{amount_display}', f'{card_block}', f'{tips_block}', f'{final_line}'), en_parts=lambda: (f'{wallet_emoji}', f'{id_emoji}', f'{order_id}', f'{money_emoji}', f'{amount_display}', f'{card_block}', f'{tips_block}', f'{final_line}'))
        return t('b_payment_details_b_order_co_4085f118cb', lang, fa_parts=lambda: (f'{RLM}', f'{config_emoji}', f'{RLM}', f'{id_emoji}', f'{order_id}', f'{RLM}', f'{config_emoji}', f'{category_display}', f'{RLM}', f'{volume_display}', f'{RLM}', f'{days}', f'{RLM}', f'{money_emoji}', f'{price_display}', f'{card_block}', f'{tips_block}', f'{final_line}'), en_parts=lambda: (f'{config_emoji}', f'{id_emoji}', f'{order_id}', f'{config_emoji}', f'{category_display}', f'{volume_display}', f'{days}', f'{money_emoji}', f'{price_display}', f'{card_block}', f'{tips_block}', f'{final_line}'))
    if is_balance_charge:
        return t('b_top_up_receipt_request_b_o_b50eff979a', lang, fa_parts=lambda: (f'{RLM}', f'{receipt_emoji}', f'{RLM}', f'{id_emoji}', f'{order_id}', f'{RLM}', f'{money_emoji}', f'{amount_display}', f'{RLM}', f'{note_emoji}', f'{RLM}', f'{order_id}', f'{RLM}', f'{receipt_emoji}'), en_parts=lambda: (f'{receipt_emoji}', f'{id_emoji}', f'{order_id}', f'{money_emoji}', f'{amount_display}', f'{note_emoji}', f'{order_id}', f'{receipt_emoji}'))
    
    return t('b_receipt_request_b_order_co_7c16b3a99d', lang, fa_parts=lambda: (f'{RLM}', f'{receipt_emoji}', f'{RLM}', f'{id_emoji}', f'{order_id}', f'{RLM}', f'{money_emoji}', f'{price_display}', f'{RLM}', f'{note_emoji}', f'{RLM}', f'{order_id}', f'{RLM}', f'{receipt_emoji}'), en_parts=lambda: (f'{receipt_emoji}', f'{id_emoji}', f'{order_id}', f'{money_emoji}', f'{price_display}', f'{note_emoji}', f'{order_id}', f'{receipt_emoji}'))


def build_receipt_review_status_text(order: dict, status: str, lang: str) -> str:
    order_id = order.get('order_id', '?')
    parent_order_id = order.get('parent_order_id')
    is_balance_charge = order.get('type') == 'balance_charge'

    title = (
        t('b_payment_approved_b_da86ee555a', lang)
        if status == "approved"
        else t('b_receipt_rejected_b_7a4acd988e', lang)
    )
    if is_balance_charge:
        title = (
            t('b_balance_charge_approved_b_3c0186ab36', lang)
            if status == "approved"
            else t('b_balance_charge_receipt_rej_4ce8c231af', lang)
        )
    details = t('order_number_bfd9355a31', lang, fa_parts=lambda: (f'{order_id}',), en_parts=lambda: (f'{order_id}',))
    if parent_order_id is not None:
        details += t('service_renewal_for_order_b59ae135fd', lang, fa_parts=lambda: (f'{parent_order_id}',), en_parts=lambda: (f'{parent_order_id}',))

    return f"{title}\n\n{details}"


def get_receipt_status_metadata(order: dict) -> dict:
    fields = (
        'receipt_status_chat_id',
        'receipt_status_message_id',
        'receipt_status_lang',
    )
    return {field: order.get(field) for field in fields}


def get_extension_success_keyboard(order_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('view_extended_config_04a19a8043', lang),
            callback_data=f"view_config_{order_id}",
            style="primary",
        )],
        [InlineKeyboardButton(
            text=t('main_menu_0cdd07a7cc', lang),
            callback_data="back_to_main",
        )],
    ])


async def update_user_receipt_review_status(order: dict, status: str) -> bool:
    order_id = order.get('order_id')
    latest_order = orders.get(str(order_id))
    if isinstance(latest_order, dict):
        order = latest_order

    message_id = order.get('receipt_status_message_id')
    receipt_chat_id = order.get('receipt_status_chat_id')
    chat_id = receipt_chat_id or order.get('user_id')
    if not message_id or not receipt_chat_id:
        logger.warning(
            'payment receipt response message ID for order #%s not found; sending new status notification',
            order.get('order_id', '?'),
        )

    user_id = order.get('user_id')
    user_data = get_user_safe(user_id) if user_id else None
    lang = order.get('receipt_status_lang') or (user_data.get('lang', 'fa') if user_data else 'fa')
    status_text = build_receipt_review_status_text(order, status, lang)
    if message_id and receipt_chat_id:
        try:
            await bot.edit_message_text(
                status_text,
                chat_id=receipt_chat_id,
                message_id=message_id,
                parse_mode=ParseMode.HTML,
            )
            return True
        except Exception as e:
            logger.warning(
                'Failed to edit receipt status message for order #%s; sending a reply notification: %s',
                order.get('order_id', '?'),
                e,
                exc_info=True,
            )

    try:
        await bot.send_message(
            chat_id,
            status_text,
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message_id if receipt_chat_id and message_id else None,
        )
        return True
    except Exception as e:
        logger.error(
            'Failed to send receipt status notification for order #%s: %s',
            order.get('order_id', '?'),
            e,
            exc_info=True,
        )
        return False
        
        


CONFIG_LINKS_CACHE = {}          # {order_id: {'links': [...], 'email': str, 'timestamp': datetime}}
LINK_ROTATION_CONFIRMATIONS = {}
LINK_ROTATION_LOCKS = {}
CONFIG_LINKS_CACHE_TTL = 300     # 5 دقیقه
CONFIG_PAGE_SIZE = 3             # تعداد لینک در هر صفحه


# ==================== ماژول‌های روتر فاز ۲.۲ (وضعیت فروشگاه و تایید کاربران) ====================
from routers.admin_shop import (
    is_shop_open,
    migrate_inbound_data,
    get_shop_status_message,
    set_shop_status,
    admin_shop_settings,
    admin_toggle_manual_approval,
    admin_pending_users,
    admin_approve_user,
    admin_reject_user,
    admin_toggle_shop,
    admin_shop_message_save,
    confirm_approve_user,
    confirm_reject_user,
    admin_inbounds_list,
    admin_inbound_detail,
    admin_inbound_clients,
    admin_inbound_users,
    admin_inbound_set_default,
    show_inbound_detail,
    admin_client_detail,
    admin_inbound_default_setting,
    admin_inbound_toggle_default,
    admin_inbound_save_defaults,
    admin_inbound_clear_defaults,
    admin_inbound_select_all_defaults,
)

@dp.message(Command("save"), IsAdmin())
async def cmd_save(message: Message):
    """ذخیره‌سازی دستی دیتابیس + گرفتن بکاپ (فقط ادمین)"""
    logger.info("👑 admin requested manual save")
    lang = get_user(message.from_user.id).get('lang', 'fa')
    status_msg = await message.reply(t('i18n_save_in_progress', lang))

    start = time.time()
    success = save_all()

    if not success:
        await status_msg.edit_text(t('i18n_save_failed', lang))
        return
    try:
        backup_database()
        backup_success = True
    except Exception as e:
        logger.error(f"❌ Error creating backup: {e}")
        backup_success = False
    
    elapsed = time.time() - start
    total_size = 0
    file_sizes = {}
    for name, file_path in DB_FILES.items():
        if os.path.exists(file_path):
            size = os.path.getsize(file_path)
            total_size += size
            file_sizes[name] = size
    backup_count = len(get_backup_list())
    if backup_success:
        backup_status = t('i18n_backup_created', lang)
    else:
        backup_status = t('i18n_backup_failed', lang)

    text = t('i18n_manual_save_report', lang, fa_parts=lambda: (f'{elapsed:.2f}', format_size(total_size), f'{backup_count}', f'{backup_status}'), en_parts=lambda: (f'{elapsed:.2f}', format_size(total_size), f'{backup_count}', f'{backup_status}'))

    for name, size in file_sizes.items():
        text += f"• {name}: {format_size(size)}\n"

    text += t('i18n_manual_save_stats', lang, fa_parts=lambda: (f'{len(users)}', f'{len(orders)}', f"{len(configs_pool.get('configs', []))}", f'{len(COUPONS)}'), en_parts=lambda: (f'{len(users)}', f'{len(orders)}', f"{len(configs_pool.get('configs', []))}", f'{len(COUPONS)}'))

    await status_msg.edit_text(text, parse_mode=ParseMode.HTML)


@dp.message(Command("dbstatus"), IsAdmin())
async def cmd_db_status(message: Message):
    """بررسی وضعیت فایل‌های دیتابیس (فقط ادمین)"""
    logger.info("👑 admin requested database status check")
    lang = get_user(message.from_user.id).get('lang', 'fa')

    status_lines = [t('i18n_db_files_status_title', lang)]

    total_size = 0
    for name, path in DB_FILES.items():
        if os.path.exists(path):
            size = os.path.getsize(path)
            total_size += size
            modified = datetime.fromtimestamp(os.path.getmtime(path))
            status_lines.append(f"✅ {name}: {size:,} bytes | {modified.strftime('%H:%M:%S')}")
        else:
            status_lines.append(t('i18n_file_missing', lang, fa_parts=lambda: (f'{name}',), en_parts=lambda: (f'{name}',)))

    status_lines.append("\n" + t('i18n_total_size', lang, fa_parts=lambda: (f'{total_size / 1024:.1f}',), en_parts=lambda: (f'{total_size / 1024:.1f}',)))
    status_lines.append(t('i18n_in_memory_data', lang))
    status_lines.append(t('i18n_users_count_line', lang, fa_parts=lambda: (f'{len(users)}',), en_parts=lambda: (f'{len(users)}',)))
    status_lines.append(t('i18n_orders_count_line', lang, fa_parts=lambda: (f'{len(orders)}',), en_parts=lambda: (f'{len(orders)}',)))
    status_lines.append(t('i18n_configs_count_line', lang, fa_parts=lambda: (f"{len(configs_pool.get('configs', []))}",), en_parts=lambda: (f"{len(configs_pool.get('configs', []))}",)))
    status_lines.append(t('i18n_cache_files_line', lang, fa_parts=lambda: (f'{len(_db_cache)}',), en_parts=lambda: (f'{len(_db_cache)}',)))
    
    await message.reply("\n".join(status_lines), parse_mode=ParseMode.HTML)
    
    

@dp.message(Command("cleanup_backups"), IsAdmin())
async def cmd_cleanup_backups(message: Message):
    """پاکسازی بکاپ‌های قدیمی از پوشه اصلی (فقط ادمین)"""
    logger.info('🧹 starting cleanup of old backups...')
    
    cleanup_report = []
    data_dir = DATA_DIR
    if os.path.exists(data_dir):
        for file in os.listdir(data_dir):
            if file.endswith('.backup') or file.endswith('.tmp'):
                file_path = os.path.join(data_dir, file)
                try:
                    os.remove(file_path)
                    cleanup_report.append(t('i18n_removed_file', get_user(message.from_user.id).get('lang', 'fa'), fa_parts=lambda: (f'{file}',), en_parts=lambda: (f'{file}',)))
                    logger.info(f"Removed extra file: {file}")
                except Exception as e:
                    err_msg = str(e)
                    cleanup_report.append(t('i18n_remove_error', get_user(message.from_user.id).get('lang', 'fa'), fa_parts=lambda: (f'{file}', err_msg), en_parts=lambda: (f'{file}', err_msg)))
    backup_dir = os.path.join(data_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    base_lang = get_user(message.from_user.id).get('lang', 'fa')
    for name in ['users', 'orders', 'referrals', 'configs', 'feedback', 'chats', 'blacklist']:
        main_file = os.path.join(data_dir, f"{name}.json")
        backup_file = os.path.join(data_dir, f"{name}.json.backup")

        if not os.path.exists(main_file) and os.path.exists(backup_file):
            shutil.copy2(backup_file, main_file)
            cleanup_report.append(t('i18n_restored_from_backup', base_lang, fa_parts=lambda: (f'{name}',), en_parts=lambda: (f'{name}',)))
            logger.warning(f"File {name}.json restored from backup")
    if cleanup_report:
        report_text = t('i18n_cleanup_report_title', base_lang) + "\n".join(cleanup_report)
    else:
        report_text = t('i18n_no_extra_files', base_lang)
    
    await message.reply(report_text, parse_mode=ParseMode.HTML)
    


@dp.message(Command("check_packages"), IsAdmin())
async def cmd_check_packages(message: Message):
    """بررسی وضعیت بسته‌های آماده (فقط ادمین)"""
    text = "📦 <b>بررسی بسته‌های آماده</b>\n\n"
    text += f"🔘 وضعیت کلی: {'🟢 فعال' if READY_PACKAGES.get('enabled') else '🔴 غیرفعال'}\n"
    text += f"📊 تعداد دسته‌ها: {len(READY_PACKAGES.get('categories', []))}\n"
    text += f"🕐 آخرین بروزرسانی: {READY_PACKAGES.get('last_updated', 'N/A')}\n\n"
    text += "📋 <b>لیست دسته‌ها و بسته‌ها:</b>\n"
    for cat in READY_PACKAGES.get('categories', []):
        active_packages = [p for p in cat.get('packages', []) if p.get('is_active', True)]
        status = "🟢" if cat.get('is_active') else "🔴"
        text += f"{status} {cat.get('icon', '📦')} <b>{safe_html(cat.get('name'))}</b> (ID: {cat.get('id')})\n"
        text += f"  📦 بسته‌ها: {len(active_packages)} فعال\n"
        for pkg in active_packages:
            text += f"    • {pkg.get('volume')}GB - {pkg.get('days')} روز - {pkg.get('price'):,} تومان\n"
        text += "\n"
    
    await message.reply(text, parse_mode=ParseMode.HTML)
    
    
def load_ready_packages():
    """بارگذاری تنظیمات بسته‌های آماده از configs_pool"""
    global READY_PACKAGES
    
    try:
        packages_data = configs_pool.get('ready_packages', {})
        logger.info(f"📦 data saved in configs_pool: {bool(packages_data)}")
        if packages_data:
            logger.info(f"📦 Number of categories in the database: {len(packages_data.get('categories', []))}")
            for cat in packages_data.get('categories', []):
                inbound_ids = cat.get('inbound_ids', [])
                logger.info(f"  📡 Category {cat.get('name')}: inbounds = {inbound_ids if inbound_ids else 'default'}")
        if packages_data and packages_data.get('categories') and len(packages_data.get('categories', [])) > 0:
            READY_PACKAGES.update(packages_data)
            logger.info(f"📦 Ready-made packages loaded from the database: {len(READY_PACKAGES.get('categories', []))} category")
            total_packages = 0
            for cat in READY_PACKAGES.get('categories', []):
                total_packages += len(cat.get('packages', []))
                inbound_ids = cat.get('inbound_ids', [])
                logger.info(f"  📡 {cat.get('name')}: inbounds = {inbound_ids if inbound_ids else 'default'}")
            
            logger.info(f"📦 Total number of packages: {total_packages}")
            logger.info(f"🕐 Last updated: {READY_PACKAGES.get('last_updated', 'N/A')}")
            
        else:
            logger.warning('⚠️ No ready-made package data found in the database; using default values')
            default_categories = [
                {
                    'id': 1,
                    'name': 'کانفیگ مخصوص جنگ',
                    'name_en': 'War Config',
                    'icon': '⚔️',
                    'description': 'کانفیگ‌های بهینه شده برای دور زدن فیلترینگ',
                    'description_en': 'Optimized configs for bypassing filtering',
                    'inbound_ids': [],  # لیست خالی = استفاده از پیش‌فرض
                    'is_active': True,
                    'order': 1,
                    'packages': [
                        {'id': 1, 'volume': 10, 'days': 30, 'price': 100000, 'is_active': True},
                        {'id': 2, 'volume': 20, 'days': 30, 'price': 200000, 'is_active': True}
                    ]
                },
                {
                    'id': 2,
                    'name': 'کانفیگ مخصوص نت ملی',
                    'name_en': 'National Net Config',
                    'icon': '📡',
                    'description': 'کانفیگ‌های بهینه شده برای اینترنت ملی',
                    'description_en': 'Optimized configs for national internet',
                    'inbound_ids': [],
                    'is_active': True,
                    'order': 2,
                    'packages': [
                        {'id': 3, 'volume': 10, 'days': 30, 'price': 80000, 'is_active': True},
                        {'id': 4, 'volume': 30, 'days': 30, 'price': 200000, 'is_active': True}
                    ]
                }
            ]
            
            READY_PACKAGES.clear()
            READY_PACKAGES.update({
                'enabled': True,
                'restrict_extend_to_same_category': READY_PACKAGES.get('restrict_extend_to_same_category', False),
                'categories': default_categories,
                'last_updated': now_tehran_iso()
            })
            configs_pool['ready_packages'] = READY_PACKAGES
            save_all()
            logger.info('📦 Default ready-made package settings created and saved to the database')
            
    except Exception as e:
        logger.error(f"❌ Error loading ready-made packages: {e}")
        traceback.print_exc()
        READY_PACKAGES.clear()
        READY_PACKAGES.update({
            'enabled': True,
            'categories': [],
            'last_updated': now_tehran_iso()
        })
        
        
def _sync_app_state_after_load():
    ai_settings = configs_pool.get('ai_settings', {})
    enabled = ai_settings.get('button_enabled', True)
    set_ai_button_enabled(enabled)
    logger.info(f"AI button status: {'enabled' if enabled else 'disabled'}")
    if 'shop_status' in configs_pool:
        SHOP_STATUS.clear()
        SHOP_STATUS.update(configs_pool['shop_status'])
        logger.info(f"🛒 Sales status: {'open' if SHOP_STATUS.get('open', True) else 'closed'}")
    load_ready_packages()
    load_user_test_settings()
    for cat in READY_PACKAGES.get('categories', []):
        inbound_ids = cat.get('inbound_ids', [])
        if inbound_ids:
            logger.info(f"📡 Category {cat.get('name')} - inbounds: {inbound_ids}")
    load_user_inbound_selections()

def _sync_configs_before_save():
    configs_pool['ready_packages'] = READY_PACKAGES
    configs_pool['test_service'] = TEST_SERVICE_STATUS

register_post_load_hook(_sync_app_state_after_load)
register_pre_save_hook(_sync_configs_before_save)


@dp.message(Command("checkdata"), IsAdmin())
async def cmd_check_data(message: Message):
    """بررسی محتوای فایل‌های دیتابیس (فقط ادمین)"""
    logger.info("👑 admin requested data check")
    lang = get_user(message.from_user.id).get('lang', 'fa')

    report = []
    report.append(t('i18n_db_files_check_title', lang))

    for name, path in DB_FILES.items():
        if os.path.exists(path):
            size = os.path.getsize(path)
            with open(path, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    if isinstance(data, dict):
                        count = len(data)
                    elif isinstance(data, list):
                        count = len(data)
                    else:
                        count = t('i18n_unknown', lang)
                    report.append(t('i18n_file_items_line', lang, fa_parts=lambda: (f'{name}', f'{size:,}', f'{count}'), en_parts=lambda: (f'{name}', f'{size:,}', f'{count}')))
                except Exception:
                    report.append(t('i18n_file_read_error', lang, fa_parts=lambda: (f'{name}', f'{size:,}'), en_parts=lambda: (f'{name}', f'{size:,}')))
        else:
            report.append(t('i18n_file_missing', lang, fa_parts=lambda: (f'{name}',), en_parts=lambda: (f'{name}',)))
    report.append("\n" + t('i18n_ram_stats_title', lang))
    report.append(t('i18n_users_in_ram', lang, fa_parts=lambda: (f'{len(users)}',), en_parts=lambda: (f'{len(users)}',)))
    report.append(t('i18n_orders_in_ram', lang, fa_parts=lambda: (f'{len(orders)}',), en_parts=lambda: (f'{len(orders)}',)))
    report.append(t('i18n_configs_in_ram', lang, fa_parts=lambda: (f"{len(configs_pool.get('configs', []))}",), en_parts=lambda: (f"{len(configs_pool.get('configs', []))}",)))
    
    await message.reply("\n".join(report), parse_mode=ParseMode.HTML)


@dp.errors()
async def errors_handler(event: types.ErrorEvent):
    """هندلر خطاهای عمومی"""
    exception = event.exception
    update = event.update
    
    error_str = str(exception)
    
    # ✅ نادیده گرفتن خطاهای timeout در callback.answer
    if "query is too old" in error_str or "query ID is invalid" in error_str:
        logger.debug("callback.answer timeout - ignored")
        return True  # نکش ربات رو
    
    # بقیه‌ی خطاها
    update_id = getattr(update, 'update_id', 'N/A')
    event_type = getattr(update, 'event_type', type(update).__name__ if update else 'N/A')
    error_text = f"""
⚠️ <b>خطا در ربات</b>

📅 زمان: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}
❌ خطا: {str(exception)[:300]}
🔍 نوع خطا: {type(exception).__name__}

📝 شناسه آپدیت: {update_id} ({event_type})
"""
    logger.error(f"Error: {exception}", exc_info=True)
    try:
        await bot.send_message(ADMIN_ID_INT, error_text, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    
    return True

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """دستور استارت - نسخه نهایی با مدیریت کامل تایید دستی و عضویت اجباری"""
    user_id = message.from_user.id
    if START_REACTION_EMOJI:
        try:
            await message.react([ReactionTypeEmoji(emoji=START_REACTION_EMOJI)])
        except Exception as e:
            logger.debug(f"Error recording start reaction: {e}")
    await auto_pause_user_ticket_if_active(user_id)
    if await _is_admin_broadcasting(message):
        await admin_broadcast_send(message)
        return
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id, message)
        logger.warning(f"⛔ blocked user {user_id} executed /start command")
        return
    user_name = message.from_user.first_name or message.from_user.username or "کاربر"
    user_name_escaped = html.escape(user_name)
    
    await send_sticker(user_id, 'halloween', '🚀', reply_markup=ReplyKeyboardRemove())
    if message.from_user.last_name:
        user_name += f" {message.from_user.last_name}"
        user_name_escaped = html.escape(user_name)
    
    user_username = message.from_user.username or ""
    args = message.text.split()
    uid = str(user_id)
    is_new_user = uid not in users
    manual_approval = configs_pool.get('manual_approval_settings', {})
    approval_enabled = manual_approval.get('enabled', False)
    
    if is_new_user:
        referred_by = None
        if len(args) > 1 and args[1].isdigit():
            ref_id = int(args[1])
            if ref_id != user_id:
                if str(ref_id) in users:
                    referred_by = ref_id
                    await process_referral(user_id, ref_id)
                else:
                    logger.warning(f"⚠️ Referrer {ref_id}not found in database")
        
        if log_system:
            asyncio.create_task(log_system.log_user_register(user_id, user_name, user_username))
        if not approval_enabled:
            users[uid] = {
                'id': user_id,
                'name': user_name,
                'username': user_username,
                'telegram_username': user_username,
                'balance': 0,
                'volume': 1,
                'days': 30,
                'lang': 'fa',
                'referred_by': referred_by,
                'has_purchased': False,
                'join_date': now_tehran().strftime('%Y/%m/%d'),
                'total_purchases': 0,
                'total_spent': 0,
                'last_purchase_date': None,
                'is_active': True,
                'verified': False,
                'notes': '',
                'created_at': now_tehran_iso(),
                'updated_at': now_tehran_iso(),
                'coupon_code': None,
                'coupon_discount': 0,
                'coupon_applied': False,
                'approved_by_admin': True,
                'approved_date': now_tehran_iso(),
                'requested_approval': False,
                'registration_status': 'approved',
                'admin_notified': False,
                'last_request_time': None
            }
            logger.info(f"👤 New user created: {user_name} (ID: {user_id}) - status: approved (automatic)")
        else:
            users[uid] = {
                'id': user_id,
                'name': user_name,
                'username': user_username,
                'telegram_username': user_username,
                'balance': 0,
                'volume': 1,
                'days': 30,
                'lang': 'fa',
                'referred_by': referred_by,
                'has_purchased': False,
                'join_date': now_tehran().strftime('%Y/%m/%d'),
                'total_purchases': 0,
                'total_spent': 0,
                'last_purchase_date': None,
                'is_active': True,
                'verified': False,
                'notes': '',
                'created_at': now_tehran_iso(),
                'updated_at': now_tehran_iso(),
                'coupon_code': None,
                'coupon_discount': 0,
                'coupon_applied': False,
                'approved_by_admin': False,
                'approved_date': None,
                'requested_approval': False,
                'registration_status': 'pending',
                'admin_notified': False,
                'last_request_time': None
            }
            logger.info(f"👤 New user created: {user_name} (ID: {user_id}) - status: pending (awaiting approval)")
        
        save_json(DB_FILES['users'], users)
        
    else:
        updated = False
        
        if users[uid].get('name') != user_name:
            users[uid]['name'] = user_name
            updated = True
        
        if users[uid].get('username') != user_username:
            users[uid]['username'] = user_username
            users[uid]['telegram_username'] = user_username
            updated = True
        required_fields = {
            'coupon_code': None,
            'coupon_discount': 0,
            'coupon_applied': False,
            'approved_by_admin': False,
            'approved_date': None,
            'requested_approval': False,
            'registration_status': 'pending',
            'admin_notified': False,
            'last_request_time': None
        }
        
        for field, default in required_fields.items():
            if field not in users[uid]:
                users[uid][field] = default
                updated = True
        if not approval_enabled and not users[uid].get('approved_by_admin', False):
            users[uid]['approved_by_admin'] = True
            users[uid]['approved_date'] = now_tehran_iso()
            users[uid]['registration_status'] = 'approved'
            users[uid]['admin_notified'] = False
            updated = True
            logger.info(f"✅ user {user_id} automatically approved because manual approval is disabled")
        if users[uid].get('has_purchased', False) and not users[uid].get('approved_by_admin', False):
            users[uid]['approved_by_admin'] = True
            users[uid]['approved_date'] = now_tehran_iso()
            users[uid]['registration_status'] = 'approved'
            users[uid]['admin_notified'] = False
            updated = True
            logger.info(f"✅ user {user_id}auto-approved due to existing purchase")
        
        if updated:
            users[uid]['updated_at'] = now_tehran_iso()
            save_json(DB_FILES['users'], users)
            logger.info(f"📝 User information for {user_id} updated and saved")
    
    user = users[uid]
    lang = user.get('lang', 'fa')
    is_admin = (user_id == ADMIN_ID_INT)
    if is_admin:
        await message.answer(
            f"{premium_emoji('rocket', '🚀')} {t('welcome_to_admin_panel_4efb80706c', lang)}",
            reply_markup=get_main_keyboard(True, lang, user_id)
        )
        return
    async def check_force_join_and_show():
        """بررسی عضویت اجباری و نمایش صفحه مناسب"""
        settings = configs_pool.get('force_join_settings', {})
        force_join_enabled = settings.get('enabled', False)
        channels = settings.get('channels', [])
        
        if not force_join_enabled or not channels:
            return True  # عضویت اجباری غیرفعال است
        membership_report = await check_membership_detailed(user_id)
        
        if not membership_report['is_all_joined']:
            # کاربر عضو نیست یا لفت داده
            if users[uid].get('verified', False):
                users[uid]['verified'] = False
                users[uid]['updated_at'] = now_tehran_iso()
                save_json(DB_FILES['users'], users)
                logger.warning(f"⚠️ user {user_id} left the channel; membership page displayed")
            
            await show_verification_page(message, user_id, lang)
            return False
        else:
            # کاربر عضو همه کانال‌هاست
            if not users[uid].get('verified', False):
                users[uid]['verified'] = True
                users[uid]['updated_at'] = now_tehran_iso()
                save_json(DB_FILES['users'], users)
                logger.info(f"✅ user {user_id} is a member of all channels; verified changed to True")
            
            return True
    if not approval_enabled:
        if not users[uid].get('approved_by_admin', False):
            users[uid]['approved_by_admin'] = True
            users[uid]['registration_status'] = 'approved'
            users[uid]['approved_date'] = now_tehran_iso()
            users[uid]['updated_at'] = now_tehran_iso()
            save_json(DB_FILES['users'], users)
            logger.info(f"✅ user {user_id} automatically approved (manual approval disabled)")
        can_continue = await check_force_join_and_show()
        if not can_continue:
            return
        
        text = format_start_greeting(user_name_escaped, lang, premium_emoji('rocket', '🚀'))
        
        await message.answer(text, reply_markup=get_main_keyboard(False, lang, user_id))
        return
    if users[uid].get('approved_by_admin', False) or users[uid].get('has_purchased', False):
        coupon_data = load_coupon_from_user_db(user_id)
        coupon_code = coupon_data.get('coupon_code')
        coupon_discount = coupon_data.get('coupon_discount')
        coupon_applied = coupon_data.get('coupon_applied', False)
        
        if coupon_applied and coupon_code:
            is_valid, reason = is_coupon_valid_for_user(coupon_code, user_id)
            if is_valid:
                user_states[user_id] = {
                    'coupon_code': coupon_code,
                    'coupon_discount': coupon_discount if coupon_discount else 0,
                    'coupon_applied': True
                }
                logger.info(f"🏷️ coupon {coupon_code} in user_states for user {user_id} saved")
            else:
                logger.warning(f"⚠️ Coupon {coupon_code} invalid: {reason}")
                clear_coupon_from_user_db(user_id)
        else:
            user_state = user_states.get(user_id, {})
            if user_state.get('coupon_applied', False) and user_state.get('coupon_code'):
                save_coupon_to_user_db(user_id)
        
        # بررسی عضویت اجباری
        can_continue = await check_force_join_and_show()
        if not can_continue:
            return
        
        text = format_start_greeting(user_name_escaped, lang, premium_emoji('rocket', '🚀'))
        
        await message.answer(text, reply_markup=get_main_keyboard(False, lang, user_id))
        return
    
    # ============ مسیر 3: کاربر در انتظار تایید ============
    status = users[uid].get('registration_status', 'pending')
    if status == 'requested':
        text = t('b_your_request_has_been_subm_e34a9c8175', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('hourglass', '⏳')}", f"{premium_emoji('light', '💡')}"), en_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('hourglass', '⏳')}", f"{premium_emoji('light', '💡')}"))
        await message.answer(text, parse_mode=ParseMode.HTML)
        return
    
    if status in ['cancelled', 'rejected']:
        users[uid]['registration_status'] = 'pending'
        users[uid]['requested_approval'] = False
        users[uid]['admin_notified'] = False
        users[uid]['updated_at'] = now_tehran_iso()
        save_json(DB_FILES['users'], users)
        logger.info(f"🔄 user status {user_id} from {status} changed to pending (retry request)")
    text = t('b_welcome_to_our_community_b_38f430476a', lang, fa_parts=lambda: (f"{premium_emoji('loading', '🔹')}", f"{premium_emoji('email', '📨')}", f"{premium_emoji('cancel', '❌')}", f"{premium_emoji('danger', '⚠️')}"), en_parts=lambda: (f"{premium_emoji('loading', '🔹')}", f"{premium_emoji('email', '📨')}", f"{premium_emoji('cancel', '❌')}", f"{premium_emoji('danger', '⚠️')}"))
    
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=t('submit_request_65106cf1cf', lang),
                callback_data="request_approval",
                style="primary"
            ),
            InlineKeyboardButton(
                text=t('exit_4779b8691e', lang),
                callback_data="cancel_registration",
            )
        ]
    ])
    
    await message.answer(text, reply_markup=buttons, parse_mode=ParseMode.HTML)
# check_membership_detailed has been moved to routers/force_join.py

@dp.callback_query(F.data == "request_approval")
async def request_approval(callback: CallbackQuery):
    """کاربر درخواست تایید می‌دهد - با جلوگیری از درخواست تکراری"""
    user_id = callback.from_user.id
    if user_id == ADMIN_ID_INT:
        await callback.answer("👑 شما ادمین هستید!", show_alert=True)
        return
    
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    status = user.get('registration_status', 'pending')
    if status == 'approved':
        await callback.answer(
            t('you_are_already_approved_74b8b21162', lang),
            show_alert=True
        )
        return
    if status == 'requested':
        last_request = user.get('last_request_time')
        if last_request:
            try:
                last_time = datetime.fromisoformat(last_request)
                ref_now = now_tehran() if last_time.tzinfo is not None else now_tehran().replace(tzinfo=None)
                elapsed = (ref_now - last_time).total_seconds()
                
                if elapsed < 60:  # کمتر از 1 دقیقه
                    remaining = 60 - int(elapsed)
                    await callback.answer(
                        t('your_request_has_already_bee_bcd3ef93ff', lang, fa_parts=lambda: (f'{remaining}',), en_parts=lambda: (f'{remaining}',)),
                        show_alert=True
                    )
                    return
            except Exception:
                pass
        await callback.answer(
            t('your_request_is_already_subm_d2b22ad576', lang),
            show_alert=True
        )
        return
    if status == 'cancelled':
        await callback.answer(
            t('you_cancelled_registration_u_5ae065a858', lang),
            show_alert=True
        )
        return
    if status == 'rejected':
        await callback.answer(
            t('your_request_has_been_reject_97c0a791a1', lang),
            show_alert=True
        )
        return
    uid = str(user_id)
    users[uid]['requested_approval'] = True
    users[uid]['registration_status'] = 'requested'
    users[uid]['requested_date'] = now_tehran_iso()
    users[uid]['last_request_time'] = now_tehran_iso()
    users[uid]['admin_notified'] = False  # هنوز به ادمین اطلاع داده نشده
    users[uid]['updated_at'] = now_tehran_iso()
    save_json(DB_FILES['users'], users)
    text = t('b_your_request_has_been_subm_48224cb7f8', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('hourglass', '⏳')}", f"{premium_emoji('light', '💡')}"), en_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('hourglass', '⏳')}", f"{premium_emoji('light', '💡')}"))
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await callback.message.answer(text, parse_mode=ParseMode.HTML)
    user_name = user.get('name', f'کاربر_{user_id}')
    username = user.get('username', '')
    username_display = f"@{username}" if username else 'ندارد'
    
    user_name_escaped = html.escape(user_name)
    
    admin_text = f"""
{premium_emoji('invite', '📨')} <b>درخواست تایید جدید</b>

{premium_emoji('user', '👤')} نام: {user_name_escaped}
{premium_emoji('id', '🆔')} آیدی: <code>{user_id}</code>
{premium_emoji('user1', '📛')} یوزرنیم: {username_display}
{premium_emoji('calendar', '📅')} تاریخ: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}

برای بررسی و تایید از پنل ادمین اقدام کنید.
"""
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=t('approve_user_a373937927', lang),
                callback_data=f"admin_approve_user_{user_id}",
                style="success"
            ),
            InlineKeyboardButton(
                text=t('reject_delete_user_3a19d60bb1', lang),
                callback_data=f"admin_reject_user_{user_id}",
                style="danger"
            )
        ]
    ])
    
    await bot.send_message(ADMIN_ID_INT, admin_text, parse_mode=ParseMode.HTML, reply_markup=admin_kb)
    users[uid]['admin_notified'] = True
    save_json(DB_FILES['users'], users)
    
    logger.info(f"📨 confirmation request for user {user_id} registered and sent to admin")
    
    await safe_answer(callback)


@dp.callback_query(F.data == "cancel_registration")
async def cancel_registration(callback: CallbackQuery):
    """کاربر ثبت‌نام را لغو می‌کند - با ریست کردن وضعیت"""
    user_id = callback.from_user.id
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    
    uid = str(user_id)
    users[uid]['registration_status'] = 'cancelled'
    users[uid]['requested_approval'] = False
    users[uid]['admin_notified'] = False  # ✅ ریست کردن
    users[uid]['cancelled_date'] = now_tehran_iso()
    users[uid]['updated_at'] = now_tehran_iso()
    save_json(DB_FILES['users'], users)
    text = t('b_goodbye_b_use_b_start_b_ag_ce06ba36c7', lang, fa_parts=lambda: (f"{premium_emoji('cancel', '👋')}",), en_parts=lambda: (f"{premium_emoji('cancel', '👋')}",))
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await callback.message.answer(text, parse_mode=ParseMode.HTML)
    
    await safe_answer(callback)
@dp.message(Command("help"))
async def cmd_help(message: Message):
    if not message.from_user:
        return
    if message.from_user.id == ADMIN_ID_INT:
        return await cmd_help_admin(message)
    lang = get_user(message.from_user.id).get('lang', 'fa')
    logger.debug(f"User {message.from_user.id} viewed the guide")
    
    text = t('b_bot_help_b_b_buy_service_b_2c131eb84b', lang, fa_parts=lambda: (f"{premium_emoji('star', '🤖')}", f"{premium_emoji('success', '✅')}", f"{premium_emoji('wallet', '💰')}", f"{premium_emoji('config', '📁')}", f"{premium_emoji('danger', '⚠️')}"), en_parts=lambda: (f"{premium_emoji('star', '🤖')}", f"{premium_emoji('success', '✅')}", f"{premium_emoji('wallet', '💰')}", f"{premium_emoji('config', '📁')}", f"{premium_emoji('danger', '⚠️')}"))
    await message.answer(text)

@dp.message(Command("blacklist"), IsAdmin())
async def cmd_blacklist(message: Message):
    """دستور مشاهده لیست سیاه (فقط ادمین)"""
    if not BLACKLIST:
        await message.reply("✅ لیست سیاه خالی است.")
        return
    
    users_info = []
    for uid in BLACKLIST:
        user_info = await get_user_info_from_telegram(uid)
        users_info.append(f"🆔 {uid} - 👤 {user_info['full_name']} - 📛 @{user_info['username']}" if user_info['username'] else f"🆔 {uid} - 👤 {user_info['full_name']}")
    
    text = "🚫 لیست سیاه:\n\n" + "\n".join(users_info)
    await message.reply(text)

async def block_unauthorized(message: Message, user_id: int) -> bool:
    """بلاک کاربر غیرمجاز - چک لیست سیاه"""
    user_state = user_states.get(user_id, {})
    if user_state.get('awaiting_receipt'):
        return False
    if user_state.get('awaiting_chat'):
        return False
    if user_id == ADMIN_ID_INT:
        return False
    if user_id in BLACKLIST:
        logger.warning(f"⛔ blocked user {user_id} attempted to use bot")
        await notify_blacklisted_user(user_id, message)
        return True
    
    return False

async def notify_blacklisted_user(user_id: int, message: Message = None):
    """ارسال پیام به کاربر مسدود شده"""
    try:
        lang = get_user(user_id).get('lang', 'fa')
        logger.info(f"🔍 SUPPORT_USERNAME from config: '{SUPPORT_USERNAME}'")
        if SUPPORT_USERNAME and SUPPORT_USERNAME.strip():
            support_contact = SUPPORT_USERNAME
        else:
            support_contact = "@my_name_is_navid"
            logger.warning(f"⚠️ SUPPORT_USERNAME is empty; using the default value: {support_contact}")
        emoji_result = premium_emoji('access_denied', '⛔')
        logger.info(f"🔍 premium_emoji('access_denied', '⛔') = '{emoji_result}'")
        
        text = t('b_access_blocked_b_you_are_b_fdd3221c25', lang, fa_parts=lambda: (f'{emoji_result}', f'{support_contact}'), en_parts=lambda: (f'{emoji_result}', f'{support_contact}'))
        logger.info(f"🔍 sent text: {text[:200]}...")
        
        support_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=t('contact_support_7f7c200a77', lang),
                callback_data="support_create_ticket"
            )
        ]])

        if message:
            await message.reply(text, reply_markup=support_keyboard, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(user_id, text, reply_markup=support_keyboard, parse_mode=ParseMode.HTML)
            
        logger.info(f"📨 block message sent to user {user_id} sent")
        return True
    except Exception as e:
        logger.error(f"❌ Error sending message to blocked user {user_id}: {e}")
        return False


@dp.message.outer_middleware()
async def blacklist_middleware_message(handler, event: Message, data: dict):
    user = data.get("event_from_user")
    if user and user.id in BLACKLIST and user.id != ADMIN_ID_INT:
        user_state = user_states.get(user.id, {})
        if not (user_state.get('awaiting_receipt') or user_state.get('awaiting_chat') or user_state.get('awaiting_ticket_reply') or user_state.get('awaiting_ticket_message')):
            await notify_blacklisted_user(user.id, event)
            return
    return await handler(event, data)


@dp.callback_query.outer_middleware()
async def blacklist_middleware_callback(handler, event: CallbackQuery, data: dict):
    user = data.get("event_from_user")
    if user and user.id in BLACKLIST and user.id != ADMIN_ID_INT:
        user_state = user_states.get(user.id, {})
        callback_data = event.data or ""
        if callback_data.startswith("support_") or user_state.get('awaiting_receipt') or user_state.get('awaiting_chat'):
            return await handler(event, data)
        await notify_blacklisted_user(user.id)
        lang = get_user(user.id).get('lang', 'fa')
        await safe_answer(event, t('access_blocked_96a5fa848b', lang), alert=True)
        return
    return await handler(event, data)


dp.callback_query.outer_middleware(auto_pause_ticket_on_callback_middleware)
dp.message.outer_middleware(auto_pause_ticket_on_message_middleware)


# _tg_user_cache is imported from core.state_stores
_TG_USER_CACHE_TTL = 300.0  # 5 دقیقه


async def get_user_info_from_telegram(user_id: int, force_refresh: bool = False) -> dict:
    """دریافت اطلاعات کاربر از تلگرام با کش ۵ دقیقه‌ای و escape برای استفاده در HTML"""
    now = time.monotonic()
    if not force_refresh:
        cached = _tg_user_cache.get(user_id)
        if cached and now < cached[0]:
            return dict(cached[1])

    try:
        chat = await bot.get_chat(user_id)
        first_name_raw = chat.first_name or 'نامشخص'
        last_name_raw = chat.last_name or ''
        full_name_raw = f"{first_name_raw} {last_name_raw}".strip() or 'کاربر ناشناس'
        username_raw = chat.username or ''

        info = {
            'id': user_id,
            'first_name': html.escape(first_name_raw),
            'last_name': html.escape(last_name_raw),
            'username': html.escape(username_raw),
            'full_name': html.escape(full_name_raw)
        }
        _tg_user_cache[user_id] = (now + _TG_USER_CACHE_TTL, info)
        return dict(info)
    except Exception as e:
        logger.error(f"Error retrieving user information {user_id}: {e}")
        fallback = {
            'id': user_id,
            'first_name': 'نامشخص',
            'last_name': '',
            'username': '',
            'full_name': f'کاربر ناشناس ({user_id})'
        }
        _tg_user_cache[user_id] = (now + 60.0, fallback)
        return dict(fallback)



def save_blacklist():
    """ذخیره لیست سیاه در فایل"""
    try:
        blacklist_data = {
            'users': list(BLACKLIST),  # تبدیل set به list برای JSON
            'last_updated': now_tehran_iso(),
            'count': len(BLACKLIST)
        }
        success = save_json(DB_FILES['blacklist'], blacklist_data)
        if success:
            logger.info(f"✅ blacklist saved - {len(BLACKLIST)} user")
        return success
    except Exception as e:
        logger.error(f"❌ Error saving blacklist: {e}")
        return False


def load_blacklist():
    """بارگذاری لیست سیاه از فایل"""
    try:
        blacklist_data = load_json(DB_FILES['blacklist'], use_cache=False)
        if blacklist_data and 'users' in blacklist_data:
            users_list = blacklist_data.get('users', [])
            BLACKLIST.clear()
            BLACKLIST.update(users_list)
            
            logger.info(f"✅ Blacklist loaded - {len(BLACKLIST)} user")
            if BLACKLIST:
                logger.info(f"📋 Blocked users: {BLACKLIST}")
        else:
            BLACKLIST.clear()
            logger.info('📭 Blacklist file does not exist - creating an empty set')
            save_blacklist()
    except Exception as e:
        logger.error(f"❌ Error loading blacklist: {e}")
        BLACKLIST.clear()

def remove_from_blacklist(user_id: int) -> bool:
    """حذف کاربر از لیست سیاه"""
    if user_id in BLACKLIST:
        BLACKLIST.discard(user_id)
        save_json(DB_FILES['blacklist'], {
            'users': list(BLACKLIST),
            'last_updated': now_tehran_iso(),
            'count': len(BLACKLIST)
        })
        logger.info(f"✅ user {user_id}removed from blacklist - count: {len(BLACKLIST)}")
        return True
    return False

@dp.callback_query(F.data == "admin_price_settings")
@admin_only
async def admin_price_settings(callback: CallbackQuery):
    """نمایش تنظیمات قیمت"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    settings = configs_pool.get('price_settings', {})
    
    text = t('b_price_settings_b_base_pric_99401216cf', lang, fa_parts=lambda: (f"{settings.get('base_price', 20000):,}", f"{settings.get('per_gb_price', 20000):,}", f"{premium_emoji('timer', '⏱')}", f"{settings.get('per_15days_price', 5000):,}", f"{settings.get('referral_bonus', 5000):,}", f"{settings.get('min_charge', 10000):,}", f"{settings.get('max_charge', 5000000):,}", f"{settings.get('last_updated', 'N/A')}"), en_parts=lambda: (f"{settings.get('base_price', 20000):,}", f"{settings.get('per_gb_price', 20000):,}", f"{premium_emoji('timer', '⏱')}", f"{settings.get('per_15days_price', 5000):,}", f"{settings.get('referral_bonus', 5000):,}", f"{settings.get('min_charge', 10000):,}", f"{settings.get('max_charge', 5000000):,}", f"{settings.get('last_updated', 'N/A')}"))
    
    buttons = [
        [InlineKeyboardButton(text=t('edit_base_price_eea2092fe7', lang), callback_data="edit_price_base")],
        [InlineKeyboardButton(text=t('edit_gb_price_1986b0697b', lang), callback_data="edit_price_per_gb")],
        [InlineKeyboardButton(text=t('edit_15_days_price_d8a1233bb6', lang), callback_data="edit_price_per_15days")],
        [InlineKeyboardButton(text=t('edit_referral_bonus_669ee07fb7', lang), callback_data="edit_price_referral")],
        [InlineKeyboardButton(text=t('edit_min_charge_48b01b53ac', lang), callback_data="edit_price_min_charge")],
        [InlineKeyboardButton(text=t('edit_max_charge_2253d23bd8', lang), callback_data="edit_price_max_charge")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)
    
    
    
    
@dp.callback_query(F.data.startswith("edit_price_"))
@admin_only
async def edit_price_start(callback: CallbackQuery):
    """شروع ویرایش تنظیمات قیمت"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    callback_data = callback.data
    setting_key = callback_data.replace("edit_price_", "")
    key_mapping = {
        'base': 'base_price',
        'per_gb': 'per_gb_price',
        'per_15days': 'per_15days_price',
        'referral': 'referral_bonus',
        'min_charge': 'min_charge',
        'max_charge': 'max_charge'
    }
    
    db_key = key_mapping.get(setting_key)
    
    if not db_key:
        await callback.answer(f"❌ کلید نامعتبر: {setting_key}", show_alert=True)
        logger.error(f"invalid key in edit_price_start: {setting_key}")
        return
    user_states[callback.from_user.id] = {
        'awaiting_price_edit': True,
        'price_setting': setting_key
    }
    
    setting_names = {
        'base': (t('base_price_1gb_30_days_385d706e2e', lang)),
        'per_gb': (t('extra_gb_price_331df58560', lang)),
        'per_15days': (t('extra_15_days_price_f9d2589adc', lang)),
        'referral': (t('referral_bonus_69dab5a9e9', lang)),
        'min_charge': (t('minimum_charge_0eed965c58', lang)),
        'max_charge': (t('maximum_charge_b3600d87cf', lang))
    }
    
    current_value = configs_pool.get('price_settings', {}).get(db_key, 0)
    
    await callback.message.answer(
        t('b_edit_b_current_value_code_a622cc807e', lang, fa_parts=lambda: (f'{setting_names.get(setting_key, setting_key)}', f'{current_value:,}'), en_parts=lambda: (f'{setting_names.get(setting_key, setting_key)}', f'{current_value:,}')),
        parse_mode=ParseMode.HTML
    )
    await safe_answer(callback)
    
    
    
@dp.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_price_edit'))
async def save_price_edit(message: Message):
    """ذخیره مقدار جدید تنظیمات قیمت"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    setting_names = {
        'base': {'fa': 'قیمت پایه (1GB/30 روز)', 'en': 'Base Price (1GB/30 days)'},
        'per_gb': {'fa': 'قیمت هر گیگ اضافی', 'en': 'Extra GB Price'},
        'per_15days': {'fa': 'قیمت هر 15 روز اضافی', 'en': 'Extra 15 Days Price'},
        'referral': {'fa': 'پاداش دعوت', 'en': 'Referral Bonus'},
        'min_charge': {'fa': 'حداقل شارژ', 'en': 'Minimum Charge'},
        'max_charge': {'fa': 'حداکثر شارژ', 'en': 'Maximum Charge'}
    }
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_edit_cancelled', lang))
        return

    state = user_states.get(admin_id, {})
    setting_key = state.get('price_setting')

    if not setting_key:
        user_states.pop(admin_id, None)
        await message.reply(t('i18n_invalid_state', lang))
        return

    try:
        new_value = int(message.text.replace(',', '').replace(' ', '').strip())

        if new_value <= 0:
            await message.reply(t('i18n_value_must_be_positive', lang))
            return
        key_mapping = {
            'base': 'base_price',
            'per_gb': 'per_gb_price',
            'per_15days': 'per_15days_price',
            'referral': 'referral_bonus',
            'min_charge': 'min_charge',
            'max_charge': 'max_charge'
        }
        
        db_key = key_mapping.get(setting_key)
        
        if not db_key:
            await message.reply(t('i18n_invalid_key_with_name', lang, fa_parts=lambda: (f'{setting_key}',), en_parts=lambda: (f'{setting_key}',)))
            user_states.pop(admin_id, None)
            return
        if db_key == 'min_charge':
            max_charge = configs_pool.get('price_settings', {}).get('max_charge', 5000000)
            if new_value > max_charge:
                await message.reply(t('i18n_min_charge_exceeds_max', lang, fa_parts=lambda: (f'{max_charge:,}',), en_parts=lambda: (f'{max_charge:,}',)))
                return
        elif db_key == 'max_charge':
            min_charge = configs_pool.get('price_settings', {}).get('min_charge', 10000)
            if new_value < min_charge:
                await message.reply(t('i18n_max_charge_below_min', lang, fa_parts=lambda: (f'{min_charge:,}',), en_parts=lambda: (f'{min_charge:,}',)))
                return
        if 'price_settings' not in configs_pool:
            configs_pool['price_settings'] = {}
        
        old_value = configs_pool['price_settings'].get(db_key, 0)
        configs_pool['price_settings'][db_key] = new_value
        configs_pool['price_settings']['last_updated'] = now_tehran_iso()
        save_all()
        
        lang = get_user(admin_id).get('lang', 'fa')
        setting_display_name = setting_names.get(setting_key, {}).get(lang, setting_key)
        CustomLogger.log_event('PRICE_UPDATE', f'Price setting {db_key} changed from {old_value:,} to {new_value:,} Toman', admin_id)
        if log_system:
            await log_system.log_admin_action(
                admin_id,
                f"Updated price setting: {db_key}",
                details=f"Previous value: {old_value:,} | New value: {new_value:,} Toman"
            )
        await message.reply(t('settings_updated_toman_4405deb49f', lang, fa_parts=lambda: (f'{setting_display_name}', f'{old_value:,}', f'{new_value:,}'), en_parts=lambda: (f'{setting_display_name}', f'{old_value:,}', f'{new_value:,}')))
        user_states.pop(admin_id, None)
        settings = configs_pool.get('price_settings', {})
        
        text = t('b_price_settings_updated_b_b_3bc0f3161b', lang, fa_parts=lambda: (f"{settings.get('base_price', 20000):,}", f"{settings.get('per_gb_price', 20000):,}", f"{premium_emoji('timer', '⏱')}", f"{settings.get('per_15days_price', 5000):,}", f"{settings.get('referral_bonus', 5000):,}", f"{settings.get('min_charge', 10000):,}", f"{settings.get('max_charge', 5000000):,}", f"{settings.get('last_updated', 'N/A')}"), en_parts=lambda: (f"{settings.get('base_price', 20000):,}", f"{settings.get('per_gb_price', 20000):,}", f"{premium_emoji('timer', '⏱')}", f"{settings.get('per_15days_price', 5000):,}", f"{settings.get('referral_bonus', 5000):,}", f"{settings.get('min_charge', 10000):,}", f"{settings.get('max_charge', 5000000):,}", f"{settings.get('last_updated', 'N/A')}"))
        
        buttons = [
            [InlineKeyboardButton(text=t('edit_base_price_eea2092fe7', lang), callback_data="edit_price_base")],
            [InlineKeyboardButton(text=t('edit_gb_price_1986b0697b', lang), callback_data="edit_price_per_gb")],
            [InlineKeyboardButton(text=t('edit_15_days_price_d8a1233bb6', lang), callback_data="edit_price_per_15days")],
            [InlineKeyboardButton(text=t('edit_referral_bonus_669ee07fb7', lang), callback_data="edit_price_referral")],
            [InlineKeyboardButton(text=t('edit_min_charge_48b01b53ac', lang), callback_data="edit_price_min_charge")],
            [InlineKeyboardButton(text=t('edit_max_charge_2253d23bd8', lang), callback_data="edit_price_max_charge")],
            [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
        ]
        
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        
    except ValueError:
        await message.reply("❌ لطفاً یک عدد معتبر وارد کنید!")
    except Exception as e:
        logger.error(f"Error in save_price_edit: {e}", exc_info=True)
        await message.reply(f"❌ خطا در ذخیره سازی: {html.escape(type(e).__name__)}")
        user_states.pop(admin_id, None)
        
        
        
@dp.callback_query(F.data == "admin_blacklist")
@admin_only
async def admin_blacklist_menu(callback: CallbackQuery):
    """منوی مدیریت لیست سیاه"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    blacklist_count = len(BLACKLIST)
    
    text = t('b_blacklist_management_b_blo_79c1f84471', lang, fa_parts=lambda: (f'{blacklist_count}',), en_parts=lambda: (f'{blacklist_count}',))
    buttons = [
        [InlineKeyboardButton(text=t('add_to_blacklist_manually_97e5ee4b0d', lang), callback_data="blacklist_add")],
        [InlineKeyboardButton(text=t('show_blacklist_95a812696f', lang), callback_data="blacklist_show")],
        [InlineKeyboardButton(text=t('clear_all_blacklist_438f52a0fd', lang), callback_data="blacklist_clear_all", style="danger")],
        [InlineKeyboardButton(text=t('back_to_admin_panel_985795a510', lang), callback_data="admin_panel")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)

@dp.callback_query(F.data == "blacklist_add")
@admin_only
async def blacklist_add_start(callback: CallbackQuery):
    """شروع فرآیند افزودن دستی به لیست سیاه"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    user_states[callback.from_user.id] = {'awaiting_blacklist_add': True}
    
    text = t('b_add_to_blacklist_manually_b154152273', lang)
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_blacklist")]
        ])
    )
    await safe_answer(callback)


@dp.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get('awaiting_blacklist_add'))
async def blacklist_add_user(message: Message):
    """دریافت آیدی کاربر و افزودن به لیست سیاه"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    if message.text and message.text.strip() == '/cancel':
        user_states.pop(admin_id, None)
        await message.reply(
            t('cancelled_8a3eb8aae6', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('blacklist_080bb5628a', lang), callback_data="admin_blacklist")]
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
    if target_id == ADMIN_ID_INT:
        await message.reply(
            t('cannot_block_admin_c8dc86d7a6', lang)
        )
        user_states.pop(admin_id, None)
        return
    user_info = await get_user_info_from_telegram(target_id)
    full_name_escaped = html.escape(user_info['full_name'])
    username_escaped = html.escape(user_info['username']) if user_info['username'] else 'ندارد'
    username_display = f"@{username_escaped}" if user_info['username'] else 'ندارد'
    if target_id in BLACKLIST:
        await message.reply(
            t('user_id_is_already_blacklist_a67607dcbe', lang, fa_parts=lambda: (f'{full_name_escaped}', f'{target_id}'), en_parts=lambda: (f'{full_name_escaped}', f'{target_id}')),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('view_blacklist_26e797a37e', lang), callback_data="blacklist_show")],
                [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_blacklist")]
            ])
        )
        user_states.pop(admin_id, None)
        return
    BLACKLIST.add(target_id)
    save_blacklist()
    CustomLogger.log_event('BLACKLIST_ADD', f'User {target_id} was added to the blacklist by an admin', target_id)
    if log_system:
        await log_system.log_admin_action(
            admin_id,
            "Manually added to blacklist",
            target_user=target_id,
            details=f"Name: {full_name_escaped} | Username: {username_display}"
        )
    
    logger.info(f"🚫 user {target_id} ({full_name_escaped}) by admin {admin_id} added to blacklist")
    success_text = t('b_user_successfully_added_to_4c0101f15b', lang, fa_parts=lambda: (f'{target_id}', f'{full_name_escaped}', f'{username_display}'), en_parts=lambda: (f'{target_id}', f'{full_name_escaped}', f'{username_display}'))
    
    await message.reply(
        success_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('add_another_e377d7da3c', lang), callback_data="blacklist_add")],
            [InlineKeyboardButton(text=t('view_blacklist_26e797a37e', lang), callback_data="blacklist_show")],
            [InlineKeyboardButton(text=t('back_to_panel_63039f103a', lang), callback_data="admin_panel")]
        ])
    )
    user_states.pop(admin_id, None)
    
@dp.callback_query(F.data == "blacklist_show")
@admin_only
async def blacklist_show(callback: CallbackQuery):
    """نمایش لیست کامل کاربران مسدود با امکان حذف"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not BLACKLIST:
        await callback.answer(
            t('blacklist_is_empty_7c5fc4486d', lang),
            show_alert=True
        )
        return
    await callback.message.edit_text("⏳ در حال دریافت اطلاعات کاربران...")
    
    blacklist_users = []
    for uid in BLACKLIST:
        user_info = await get_user_info_from_telegram(uid)
        user_info['full_name_escaped'] = html.escape(user_info['full_name'])
        user_info['username_escaped'] = html.escape(user_info['username']) if user_info['username'] else ''
        blacklist_users.append(user_info)
    text = t('b_blacklist_b_06fa34c8e0', lang)
    text += t('count_users_07744b8dcb', lang, fa_parts=lambda: (f'{len(blacklist_users)}',), en_parts=lambda: (f'{len(blacklist_users)}',))
    text += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    buttons = []
    for user in blacklist_users:
        display_name = user['full_name_escaped'][:25]
        username_part = f" @{user['username_escaped']}" if user['username_escaped'] else ""
        label = f"🚫 {display_name}{username_part} - ID: {user['id']}"
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"blacklist_user_{user['id']}"
        )])
    
    buttons.append([InlineKeyboardButton(
        text=t('add_user_3f838c4add', lang),
        callback_data="blacklist_add"
    )])
    buttons.append([InlineKeyboardButton(
        text=t('clear_all_bd496050d0', lang),
        callback_data="blacklist_clear_all",
        style="danger"
    )])
    buttons.append([InlineKeyboardButton(
        text=t('back_14968ad63f', lang),
        callback_data="admin_blacklist"
    )])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("blacklist_user_"))
@admin_only
async def blacklist_user_detail(callback: CallbackQuery):
    """نمایش جزئیات کاربر در لیست سیاه"""
    
    user_id = int(callback.data.split("_")[2])
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_info = await get_user_info_from_telegram(user_id)
    full_name_escaped = html.escape(user_info['full_name'])
    username_display = f"@{html.escape(user_info['username'])}" if user_info['username'] else 'ندارد'
    
    text = t('b_user_in_blacklist_b_id_cod_5a9d6c30db', lang, fa_parts=lambda: (f'{user_id}', f'{full_name_escaped}', f'{username_display}'), en_parts=lambda: (f'{user_id}', f'{full_name_escaped}', f'{username_display}'))
    
    buttons = [
        [InlineKeyboardButton(text=t('remove_from_blacklist_067d76b51a', lang), callback_data=f"blacklist_remove_{user_id}", style="success")],
        [InlineKeyboardButton(text=t('back_to_list_eca8a9c338', lang), callback_data="blacklist_show")],
        [InlineKeyboardButton(text=t('admin_panel_bf28b6b107', lang), callback_data="admin_panel")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)
    



@dp.callback_query(F.data.startswith("blacklist_remove_"))
@admin_only
async def blacklist_remove_user(callback: CallbackQuery):
    """خارج کردن کاربر از لیست سیاه"""
    
    user_id = int(callback.data.split("_")[2])
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    user_info = await get_user_info_from_telegram(user_id)
    full_name_escaped = html.escape(user_info['full_name'])
    
    if remove_from_blacklist(user_id):
        CustomLogger.log_event('BLACKLIST_REMOVE', f'User {user_id} was removed from the blacklist', user_id)
        if log_system:
            await log_system.log_admin_action(
                callback.from_user.id,
                f"Removed user {user_id} from the blacklist",
                target_user=user_id,
                details=f"Name: {full_name_escaped}"
            )
        try:
            await bot.send_message(
                user_id,
                f"{premium_emoji('success', '✅')} شما از لیست سیاه خارج شدید!\nاکنون می‌توانید از ربات استفاده کنید.\nلطفاً با /start مجدداً ربات را شروع کنید."
            )
        except Exception:
            pass
        
        text = t('user_id_removed_from_blackli_931429f972', lang, fa_parts=lambda: (f'{full_name_escaped}', f'{user_id}'), en_parts=lambda: (f'{full_name_escaped}', f'{user_id}'))
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('back_to_blacklist_c13aad345d', lang), callback_data="admin_blacklist")],
                [InlineKeyboardButton(text=t('admin_panel_bf28b6b107', lang), callback_data="admin_panel")]
            ])
        )
    else:
        await callback.answer(t('user_not_in_blacklist_dd9d75a789', lang), show_alert=True)
    
    await safe_answer(callback)


@dp.callback_query(F.data == "blacklist_clear_all")
@admin_only
async def blacklist_clear_all_confirm(callback: CallbackQuery):
    """تأیید پاکسازی کامل"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    count = len(BLACKLIST)
    
    text = t('b_warning_clear_all_blacklis_db2f938c67', lang, fa_parts=lambda: (f'{count}',), en_parts=lambda: (f'{count}',))
    buttons = [
        [InlineKeyboardButton(text=t('yes_clear_all_887eeaf3e7', lang), callback_data="blacklist_confirm_clear_all", style="danger")],
        [InlineKeyboardButton(text=t('cancel_4197bafba5', lang), callback_data="admin_blacklist")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data == "blacklist_confirm_clear_all")
@admin_only
async def blacklist_confirm_clear_all(callback: CallbackQuery):
    """اجرای پاکسازی کامل"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    count = len(BLACKLIST)
    removed_users = list(BLACKLIST)
    BLACKLIST.clear()
    save_blacklist()
    CustomLogger.log_event('BLACKLIST_CLEAR_ALL', f'Blacklist cleared - {count} users removed', callback.from_user.id)
    if log_system:
        await log_system.log_admin_action(
            callback.from_user.id,
            "Cleared the entire blacklist",
            details=f"Removed {count} users"
        )
    
    logger.info(f"🗑 blacklist cleared by admin {callback.from_user.id} cleaned - {count} user")
    for uid in removed_users:
        try:
            await bot.send_message(uid, "✅ شما از لیست سیاه خارج شدید!\nاکنون می‌توانید از ربات استفاده کنید.")
        except Exception:
            pass
    
    text = t('blacklist_cleared_users_remo_f6e8a8c8bb', lang, fa_parts=lambda: (f'{count}',), en_parts=lambda: (f'{count}',))
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('back_to_panel_63039f103a', lang), callback_data="admin_panel")]
        ])
    )
    await safe_answer(callback)


def get_next_order_id(exclude_ids: Optional[set] = None) -> int:
    """
    یافتن هوشمند کمترین شناسه یکتا و خالی برای ثبت سفارش (الگوریتم پر کردن فاصله‌ها / Gap Filling)
    اگر شماره‌های کوچک‌تری به دلیل حذف یا پاکسازی سفارشات قبلی آزاد شده باشند،
    آن‌ها را در اولویت قرار داده و یونیک بودن را در کل دیتابیس تضمین می‌کند.
    """
    used_ids = set()
    if exclude_ids:
        used_ids.update(exclude_ids)

    # ۱. جمع‌آوری تمام شناسه‌های عددی موجود در دیتابیس سفارشات (کلیدها و مقادیر)
    for k, v in orders.items():
        try:
            used_ids.add(int(k))
        except (ValueError, TypeError):
            pass
        if isinstance(v, dict):
            oid = v.get('order_id')
            if oid is not None:
                try:
                    used_ids.add(int(oid))
                except (ValueError, TypeError):
                    pass

    # ۲. بررسی مضاعف در استخر کانفیگ‌ها (در صورتی که کانفیگی دارای order_id باشد)
    if isinstance(configs_pool, dict):
        for cfg in configs_pool.get('configs', []):
            if isinstance(cfg, dict):
                cfg_oid = cfg.get('order_id')
                if cfg_oid is not None:
                    try:
                        used_ids.add(int(cfg_oid))
                    except (ValueError, TypeError):
                        pass

    # ۳. شروع از شماره ۱ و انتخاب اولین عدد صحیح مثبت آزاد
    candidate_id = 1
    while candidate_id in used_ids or str(candidate_id) in orders:
        candidate_id += 1

    logger.debug(f"🔢 new order ID assigned: #{candidate_id} (smallest empty & unique ID)")
    return candidate_id

def create_order(user_id: int, volume: int, days: int, price: int, order_type: str = "purchase", ip_limit: int = 0) -> int:
    """ایجاد سفارش جدید با پشتیبانی از حجم 0 (نامحدود) و اولویت‌بندی هوشمند کمترین شناسه آزاد"""
    order_id = get_next_order_id()
    volume_display = "نامحدود" if volume == 0 else f"{volume}GB"
    
    orders[str(order_id)] = {
        'order_id': order_id,
        'user_id': user_id,
        'volume': volume,  # 0 = نامحدود
        'days': days,
        'price': price,
        'type': order_type,
        'status': 'awaiting_payment',
        'date': now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
        'approved_date': None,
        'config_link': None,
        'config_id': None,
        'receipt_photo_id': None,
        'email': None,
        'sub_link': None,
        'panel_client_id': None,
        'payment_method': None,
        'rejected_reason': '',
        'created_at': now_tehran_iso(),
        'updated_at': now_tehran_iso(),
        'ip_limit': ip_limit,
        'inbound_details': []
    }
    save_json(DB_FILES['orders'], orders)
    
    ip_display = "نامحدود" if ip_limit == 0 else ip_limit
    logger.info(f"📝 new order #{order_id} - user:{user_id} - {volume_display}/{days}days - IP Limit: {ip_display}")
    return order_id


def get_global_stats() -> dict:
    """دریافت آمار کلی سیستم با مدیریت خطا"""
    try:
        valid_orders = get_valid_orders()
        approved = [o for o in valid_orders.values() if o.get('status') == 'approved']
        today = now_tehran().strftime('%Y-%m-%d')
        today_orders = 0
        for o in valid_orders.values():
            order_date = o.get('date', '')
            if order_date and isinstance(order_date, str) and order_date.startswith(today):
                today_orders += 1
        today_revenue = 0
        for o in approved:
            approved_date = o.get('approved_date', '')
            if approved_date and isinstance(approved_date, str) and approved_date.startswith(today):
                today_revenue += o.get('price', 0)
        
        return {
            'total_users': len(users),
            'total_orders': len(valid_orders),
            'approved_orders': len(approved),
            'total_revenue': sum(o.get('price', 0) for o in approved),
            'total_balance': sum(u.get('balance', 0) for u in users.values()),
            'available_configs': get_available_configs_count(),
            'blacklisted_count': len(BLACKLIST),
            'today_orders': today_orders,
            'today_revenue': today_revenue
        }
    except Exception as e:
        logger.error(f"❌ Error in get_global_stats: {e}", exc_info=True)
        return {
            'total_users': len(users),
            'total_orders': 0,
            'approved_orders': 0,
            'total_revenue': 0,
            'total_balance': 0,
            'available_configs': 0,
            'blacklisted_count': len(BLACKLIST),
            'today_orders': 0,
            'today_revenue': 0
        }


def migrate_old_data():
    """مهاجرت دیتای قدیمی به ساختار جدید - با پشتیبانی از IP Limit و فیلدهای جدید"""
    global users, orders, referrals, configs_pool
    
    updated = 0
    logger.info('🔄 starting migration of old data...')
    user_defaults = {
        'total_purchases': 0,
        'total_spent': 0,
        'last_purchase_date': None,
        'telegram_username': '',
        'is_active': True,
        'verified': False,
        'notes': '',
        'has_purchased': False,
        'referred_by': None,
        'volume': 1,
        'days': 30,
        'lang': 'fa',
        'created_at': now_tehran_iso(),
        'updated_at': now_tehran_iso(),
        'coupon_code': None,
        'coupon_discount': 0,
        'coupon_applied': False,
        'approved_by_admin': True,
        'approved_date': None,
        'requested_approval': False,
        'registration_status': 'approved'
    }
    
    for uid, user in users.items():
        changed = False
        for field, default in user_defaults.items():
            if field not in user:
                user[field] = default
                changed = True
        
        if not user.get('name'):
            user['name'] = f"کاربر_{uid}"
            changed = True
        
        if changed:
            updated += 1
    order_defaults = {
        'email': None,
        'sub_link': None,
        'panel_client_id': None,
        'payment_method': None,
        'rejected_reason': '',
        'config_id': None,
        'approved_date': None,
        'created_at': now_tehran_iso(),
        'updated_at': now_tehran_iso(),
        'ip_limit': 0,
        'inbound_details': []
    }
    
    for oid, order in orders.items():
        if not isinstance(order, dict):
            continue
        
        changed = False
        for field, default in order_defaults.items():
            if field not in order:
                order[field] = default
                changed = True
                if field == 'ip_limit':
                    logger.info(f"📝 ip_limit field set to 0 for order #{oid} added")
        
        if 'type' not in order:
            order['type'] = 'purchase' if 'volume' in order else 'balance_charge'
            changed = True
        
        if changed:
            updated += 1
    for key, ref in referrals.items():
        if 'reward_given' not in ref:
            ref['reward_given'] = False
            updated += 1
        if 'date' not in ref:
            ref['date'] = now_tehran().strftime("%Y-%m-%d %H:%M:%S")
            updated += 1
    migrate_category_inbound_data()
    migrate_test_inbound_data()
    migrate_inbound_data()
    if 'ip_limit' not in configs_pool:
        configs_pool['ip_limit'] = 0
        logger.info('📝 file ip_limit added to configs_pool')
    
    if updated > 0:
        save_all()
        logger.info(f"✅ {updated} record updated")
    else:
        logger.info('✅ all records are up-to-date')

register_migration_hook(migrate_old_data)

@dp.callback_query(F.data == "delete_old_before_restore")
@admin_only
async def delete_old_before_restore(callback: CallbackQuery):
    """حذف بکاپ‌های before_restore قدیمی (بیشتر از 7 روز)"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    backup_dir = os.path.join(DATA_DIR, 'backups')
    
    if not os.path.exists(backup_dir):
        await callback.answer("❌ پوشه بکاپ وجود ندارد", show_alert=True)
        return
    
    await callback.message.edit_text("⏳ در حال حذف بکاپ‌های قدیمی before_restore...")
    
    cutoff = time.time() - (7 * 24 * 3600)  # 7 روز پیش
    deleted_count = 0
    failed_count = 0
    deleted_files = []
    
    for f in os.listdir(backup_dir):
        if f.startswith('before_restore_') and f.endswith('.json'):
            file_path = os.path.join(backup_dir, f)
            try:
                mtime = os.path.getmtime(file_path)
                if mtime < cutoff:
                    os.remove(file_path)
                    deleted_count += 1
                    deleted_files.append(f)
                    logger.info(f"🗑 Old before_restore backup deleted: {f}")
            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Error deleting {f}: {e}")
    
    text = t('b_old_before_restore_backups_dbcd63ac46', lang, fa_parts=lambda: (f'{deleted_count}', f'{failed_count}', f"{(f'📋 <b>فایل\u200cهای حذف شده:</b>' if deleted_files else '')}"), en_parts=lambda: (f'{deleted_count}', f'{failed_count}', f"{(f'📋 <b>Deleted files:</b>' if deleted_files else '')}"))
    for f in deleted_files[:10]:
        text += f"• {f}\n"
    if len(deleted_files) > 10:
        text += t('and_more_89a633a3b5', lang, fa_parts=lambda: (f'{len(deleted_files) - 10}',), en_parts=lambda: (f'{len(deleted_files) - 10}',))
    
    buttons = [[InlineKeyboardButton(
        text=t('back_to_manager_36a93bc9a4', lang),
        callback_data="admin_manage_backups"
    )]]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)

def backup_database(backup_type: str = 'full_backup'):
    """بکاپ گیری کامل از دیتابیس با تمام تنظیمات، IP Limit، alert_cache و alert_settings"""
    backup_dir = os.path.join(DATA_DIR, 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = now_tehran().strftime('%Y%m%d_%H%M%S')
    
    # ==================== 1. آماده‌سازی configs_pool ====================
    # ✅ افزودن ready_packages و test_service به configs_pool
    configs_pool['ready_packages'] = READY_PACKAGES
    configs_pool['test_service'] = TEST_SERVICE_STATUS
    
    # ✅ اطمینان از وجود alert_settings در configs_pool
    alert_settings = configs_pool.get('alert_settings', {})
    if alert_settings:
        logger.info(f"🔔 alert_settings found in configs_pool: {len(alert_settings.get('volume_thresholds', []))} volume thresholds, {len(alert_settings.get('expiry_warnings', []))} expiry warnings")
    else:
        logger.warning('⚠️ alert_settings not found in configs_pool')
    
    # ==================== 2. لاگ force_join_settings ====================
    force_settings = configs_pool.get('force_join_settings', {})
    logger.info(f"🔍 backing up - force_join_settings: {force_settings}")
    logger.info(f"🔍 number of channels: {len(force_settings.get('channels', []))}")
    
    # ==================== 3. لاگ اینباندهای دسته‌ها ====================
    for cat in READY_PACKAGES.get('categories', []):
        inbound_ids = cat.get('inbound_ids', [])
        logger.info(f"Category {cat.get('name')}: inbounds = {inbound_ids if inbound_ids else 'default'}")
    
    # ==================== 4. آماده‌سازی سفارشات با ip_limit ====================
    orders_with_ip = {}
    for oid, order in orders.items():
        if isinstance(order, dict):
            if 'ip_limit' not in order:
                order['ip_limit'] = 0
                logger.info(f"📝 Added ip_limit field with value 0 to order {oid} added")
            orders_with_ip[oid] = order
        else:
            orders_with_ip[oid] = order
    
    # ==================== 5. بارگذاری alert_cache.json ====================
    alert_cache = {}
    alert_cache_file = os.path.join(DATA_DIR, 'alert_cache.json')
    if os.path.exists(alert_cache_file):
        try:
            with open(alert_cache_file, 'r', encoding='utf-8') as f:
                alert_cache = json.load(f)
            logger.info("🔔 alert_cache.json loaded:")
            logger.info(f"  - volume_alerts: {len(alert_cache.get('volume_alerts', {}))}")
            logger.info(f"  - expiry_alerts: {len(alert_cache.get('expiry_alerts', {}))}")
            logger.info(f"  - history: {len(alert_cache.get('history', {}))}")
            logger.info(f"  - service_info: {len(alert_cache.get('service_info', {}))}")
        except Exception as e:
            logger.error(f"❌ Error reading alert_cache.json: {e}")
            alert_cache = {}
    else:
        logger.warning('⚠️ alert_cache.json file not found - backup will be without alert_cache')
    
    # ==================== 6. دریافت آمار ====================
    try:
        stats = get_global_stats()
    except Exception as e:
        logger.error(f"❌ Error in get_global_stats: {e}")
        stats = {
            'total_users': len(users),
            'total_orders': len(get_valid_orders()),
            'approved_orders': 0,
            'total_revenue': 0,
            'total_balance': sum(u.get('balance', 0) for u in users.values()),
            'available_configs': get_available_configs_count(),
            'blacklisted_count': len(BLACKLIST),
            'today_orders': 0,
            'today_revenue': 0
        }
    
    # ==================== 7. ساخت بکاپ کامل ====================
    daily_usage_backup = {}
    try:
        daily_usage_backup = usage_store.export_backup_data()
        logger.info(f"📊 daily_usage backed up: {len(daily_usage_backup.get('daily_usage', []))} record")
    except Exception as ex_d:
        logger.error(f"❌ Error in export_backup_data daily usage: {ex_d}")

    full_backup = {
        'users': users,
        'orders': orders_with_ip,
        'referrals': referrals,
        'configs': configs_pool,
        'feedback': feedbacks,
        'chats': chats,
        'blacklist': {
            'users': list(BLACKLIST),
            'count': len(BLACKLIST)
        },
        'ready_packages': READY_PACKAGES,
        'test_service': TEST_SERVICE_STATUS,
        'user_inbound_selection': USER_INBOUND_SELECTION,
        'user_test_usage': USER_TEST_USAGE,
        'shop_status': SHOP_STATUS,
        'coupons': dict(COUPONS),
        'daily_usage': daily_usage_backup,
        'sms_payments': sms_payment_manager.db.export_backup_data(),
        'alert_cache': alert_cache,
        'alert_settings': alert_settings,  # ✅ اضافه کردن alert_settings جداگانه
        'backup_info': {
            'timestamp': timestamp,
            'date': now_tehran_iso(),
            'stats': stats,
            'version': '3.3'  # ✅ شامل تمام فایل‌های data
        }
    }
    
    # ==================== 8. ذخیره بکاپ ====================
    backup_file = os.path.join(backup_dir, f'{backup_type}_{timestamp}.json')
    if save_json(backup_file, full_backup):
        logger.info(f"✅ complete backup in {backup_file} saved")
        
        # کپی فایل‌های فیزیکی دیتابیس SQLite در صورت وجود
        for db_filename, bk_prefix in (('daily_usage.db', 'daily_usage'), ('sms_payments.db', 'sms_payments')):
            db_path = os.path.join(DATA_DIR, db_filename)
            if os.path.exists(db_path):
                try:
                    shutil.copy2(db_path, os.path.join(backup_dir, f'{bk_prefix}_{timestamp}.db'))
                    logger.info(f'✅ Physical copy of {db_filename} saved in backup')
                except Exception as e_cp:
                    logger.warning(f"⚠️ Error copying database {db_filename}: {e_cp}")
        
        # ==================== 9. بررسی فایل بکاپ ذخیره شده ====================
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
                
                # بررسی اجزای اصلی
                saved_force = saved_data.get('configs', {}).get('force_join_settings', {})
                saved_ready = saved_data.get('ready_packages', {})
                saved_test = saved_data.get('test_service', {})
                saved_orders = saved_data.get('orders', {})
                saved_alert_cache = saved_data.get('alert_cache', {})
                saved_alert_settings = saved_data.get('alert_settings', {})
                saved_alert_settings_in_configs = saved_data.get('configs', {}).get('alert_settings', {})
                
                # شمارش سفارشات با ip_limit
                orders_with_ip_count = sum(1 for o in saved_orders.values() if isinstance(o, dict) and 'ip_limit' in o)
                
                # لاگ بررسی
                logger.info("🔍 Checking backup file:")
                logger.info(f"  - Users: {len(saved_data.get('users', {}))}")
                logger.info(f"  - Orders: {len(saved_orders)}")
                logger.info(f"  - Orders with ip_limit: {orders_with_ip_count}/{len(saved_orders)}")
                logger.info(f"  - force_join_settings: {saved_force}")
                logger.info(f"  - ready_packages: {len(saved_ready.get('categories', []))} category")
                logger.info(f"  - test_service: {saved_test.get('inbound_ids', [])}")
                logger.info(f"  - alert_settings (separate): {saved_alert_settings}")
                logger.info(f"  - alert_settings (in configs): {saved_alert_settings_in_configs}")
                logger.info("  - alert_cache:")
                logger.info(f"    • volume_alerts: {len(saved_alert_cache.get('volume_alerts', {}))}")
                logger.info(f"    • expiry_alerts: {len(saved_alert_cache.get('expiry_alerts', {}))}")
                logger.info(f"    • history: {len(saved_alert_cache.get('history', {}))}")
                logger.info(f"    • service_info: {len(saved_alert_cache.get('service_info', {}))}")
                logger.info(f"  - blacklist: {saved_data.get('blacklist', {}).get('count', 0)} user")
                logger.info(f"  - user_inbound_selection: {len(saved_data.get('user_inbound_selection', {}))} user")
                logger.info(f"  - user_test_usage: {len(saved_data.get('user_test_usage', {}))} user")
                logger.info(f"  - shop_status: {saved_data.get('shop_status', {}).get('open', 'unknown')}")
                logger.info(f"  - version: {saved_data.get('backup_info', {}).get('version', 'unknown')}")
                
                # بررسی کامل بودن
                required_keys = ['users', 'orders', 'configs', 'alert_cache', 'ready_packages', 'test_service']
                missing_keys = [k for k in required_keys if k not in saved_data]
                if missing_keys:
                    logger.warning(f"⚠️ Missing keys in backup: {missing_keys}")
                else:
                    logger.info(f"✅ Backup is complete - all {len(required_keys)} primary keys are present")
                    
        except Exception as e:
            logger.warning(f"⚠️ Error checking backup file: {e}")
        
        # ==================== 10. پاکسازی بکاپ‌های قدیمی ====================
        _cleanup_old_backups(backup_dir, keep=7)
        
        return True
    else:
        logger.error('❌ error saving backup')
        return False




def create_auto_backup() -> bool:
    """تهیه بکاپ خودکار زمان‌بندی‌شده"""
    return backup_database(backup_type='auto_backup')


def save_alert_cache(alert_cache: dict) -> bool:
    """ذخیره alert_cache در فایل JSON"""
    if not alert_cache:
        logger.warning('⚠️ alert_cache is empty - save not performed')
        return False
    
    alert_cache_file = os.path.join(DATA_DIR, 'alert_cache.json')
    
    try:
        # ایجاد دایرکتوری اگر وجود ندارد
        os.makedirs(os.path.dirname(alert_cache_file), exist_ok=True)
        
        with open(alert_cache_file, 'w', encoding='utf-8') as f:
            json.dump(alert_cache, f, ensure_ascii=False, indent=2)
        
        logger.info("✅ alert_cache.json saved:")
        logger.info(f"  - volume_alerts: {len(alert_cache.get('volume_alerts', {}))}")
        logger.info(f"  - expiry_alerts: {len(alert_cache.get('expiry_alerts', {}))}")
        logger.info(f"  - history: {len(alert_cache.get('history', {}))}")
        logger.info(f"  - service_info: {len(alert_cache.get('service_info', {}))}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Error saving alert_cache.json: {e}")
        return False
def _cleanup_old_backups(backup_dir: str, keep: int = 5, filename: str = 'full_backup_'):
    """نگه داشتن فقط N بکاپ آخر برای هر نوع فایل"""
    try:
        full_backups = []
        before_restore_backups = []
        other_backups = []
        
        for f in os.listdir(backup_dir):
            file_path = os.path.join(backup_dir, f)
            
            if f.startswith('full_backup_') and f.endswith('.json'):
                full_backups.append((os.path.getmtime(file_path), file_path, f))
            elif f.startswith('before_restore_') and f.endswith('.json'):
                before_restore_backups.append((os.path.getmtime(file_path), file_path, f))
            elif f.endswith('.json') or f.endswith('.backup'):
                other_backups.append((os.path.getmtime(file_path), file_path, f))
        full_backups.sort(reverse=True)
        before_restore_backups.sort(reverse=True)
        other_backups.sort(reverse=True)
        for _, path, name in full_backups[keep:]:
            os.remove(path)
            logger.debug(f"🗑 Old full_backup deleted: {name}")
        cutoff_7days = time.time() - (7 * 24 * 3600)
        for mtime, path, name in before_restore_backups:
            if mtime < cutoff_7days:
                os.remove(path)
                logger.debug(f"🗑 Old before_restore backup (>7 days) deleted: {name}")
        cutoff_30days = time.time() - (30 * 24 * 3600)
        for mtime, path, name in other_backups:
            if mtime < cutoff_30days:
                os.remove(path)
                logger.debug(f"🗑 Other old backup deleted: {name}")
        logger.info(f"🧹 backup cleanup: {len(full_backups)} full, {len(before_restore_backups)} before_restore, {len(other_backups)} other")
        logger.info(f"   kept: {min(len(full_backups), keep)} full_backup, before_restores less than 7 days")
            
    except Exception as e:
        logger.warning(f"⚠️ Error cleaning up old backups: {e}")


def find_pending_order(user_id: int) -> Optional[dict]:
    """یافتن جدیدترین سفارش در انتظار پرداخت"""
    valid_orders = get_valid_orders()
    pending_orders = []
    for o in valid_orders.values():
        if o.get('user_id') == user_id and o.get('status') == 'awaiting_payment':
            pending_orders.append(o)
    
    if not pending_orders:
        return None
    pending_orders.sort(key=lambda x: x.get('created_at', x.get('date', '')), reverse=True)
    latest_order = pending_orders[0]
    logger.debug(f"🔍 newest pending order: #{latest_order['order_id']} - type: {latest_order.get('type')}")
    if len(pending_orders) > 1:
        logger.warning(f"⚠️ user {user_id} has {len(pending_orders)} order pending payment!")
    
    return latest_order

# [Phase 5] send_config_with_qr_option moved to routers.configs_view
        
def add_config_to_pool(volume: int, days: int, link: str) -> int:
    """افزودن کانفیگ به مخزن"""
    configs_pool['last_id'] = configs_pool.get('last_id', 0) + 1
    configs_pool['configs'].append({
        'id': configs_pool['last_id'],
        'volume': volume,
        'days': days,
        'link': link,
        'used': False,
        'used_by': None,
        'used_date': None,
        'order_id': None
    })
    save_json(DB_FILES['configs'], configs_pool)
    logger.info(f"📦 config #{configs_pool['last_id']} added to repository - {volume}GB/{days}days")
    return configs_pool['last_id']


def get_config_from_pool(volume: int, days: int) -> Optional[dict]:
    """دریافت کانفیگ از مخزن"""
    configs = configs_pool.get('configs', [])
    for i, c in enumerate(configs):
        if c.get('volume') == volume and c.get('days') == days and not c.get('used'):
            config = c.copy()
            del configs_pool['configs'][i]
            save_json(DB_FILES['configs'], configs_pool)
            logger.info(f"📤 Config #{config['id']} removed from the repository")
            return config
    for i, c in enumerate(configs):
        if c.get('volume') >= volume and c.get('days') >= days and not c.get('used'):
            config = c.copy()
            del configs_pool['configs'][i]
            save_json(DB_FILES['configs'], configs_pool)
            logger.info(f"📤 Replacement config #{config['id']} removed from the repository")
            return config
    
    logger.warning(f"⚠️ config for {volume}GB/{days}days not found")
    return None


def get_available_configs_count() -> int:
    """تعداد کانفیگ‌های موجود"""
    return len([c for c in configs_pool.get('configs', []) if not c.get('used')])


def get_available_configs() -> list:
    """لیست کانفیگ‌های موجود"""
    return [c for c in configs_pool.get('configs', []) if not c.get('used')]


def delete_config(config_id: int) -> bool:
    """حذف کانفیگ"""
    configs = configs_pool.get('configs', [])
    for i, c in enumerate(configs):
        if c.get('id') == config_id:
            del configs[i]
            configs_pool['configs'] = configs
            save_json(DB_FILES['configs'], configs_pool)
            logger.info(f"🗑 Config #{config_id} deleted")
            return True
    return False

# [Phase 5] WireGuard, Telegram proxy, Platform guides, and Config view keyboard moved to routers.configs_view

# [Phase 1.4] Panel API (sessions, login, inbounds, sub settings) moved to services.panel_api
from services.panel_api import (
    LOGIN_TIMEOUT,
    API_TIMEOUT,
    COOKIE_TTL,
    CSRF_TTL,
    INBOUND_CACHE_TTL,
    LOGIN_LOCK,
    INBOUND_LOCK,
    HTTP_SESSION,
    CONNECTOR,
    SENAI_COOKIE,
    COOKIE_TIME,
    SENAI_CSRF,
    CSRF_TIME,
    INBOUND_CACHE,
    PANEL_SUB_PATH,
    PANEL_SUB_URI,
    PANEL_COMPUTED_SUB_BASE_URL,
    panel_semaphore,
    PanelRateLimiter,
    panel_rate_limiter,
    _is_auto_sub_url,
    get_sub_base_url,
    ensure_sub_base_url,
    _get_base_url,
    _ensure_session,
    init_http_session,
    close_http_session,
    _get_cookie_from_session,
    _do_login,
    xui_login,
    xui_get_csrf_token,
    _api_request,
    xui_sync_sub_settings,
    xui_get_inbounds,
    get_user_inbound,
    filter_valid_inbounds,
    reset_panel_rate_limits,
    xui_create_client_with_inbound,
    xui_get_client_info,
    xui_delete_client,
    extract_email_from_sub_link,
    build_sub_link_from_client,
    get_order_client_email,
    find_email_by_sub_id,
    xui_get_client_traffic,
    get_client_inbounds,
    xui_detach_inbounds,
    xui_attach_inbounds,
    xui_reset_client_traffic,
    test_panel_connection,
    get_panel_status,
    xui_get_client_links,
    _panel_success,
    _panel_generate_uuid,
    _panel_generate_wireguard_keypair,
    _subscription_id_from_link,
    _as_allowed_ips,
    _build_panel_client_update_payload,
    _fetch_panel_client,
    _decode_inbound_settings,
    _rotate_panel_client_identity,
)

# [Phase 3.1] check_shop_status_and_notify moved to routers.shop and imported from routers

# [Phase 1.4] xui_create_client_with_inbound, get_user_inbound, filter_valid_inbounds, xui_get_client_info, sub link helpers, and xui_get_client_traffic moved to services.panel_api

def generate_qr_code(data: str, order_id: int):
    return _generate_qr_code(data, order_id, logger)


from wireguard_card_generator import (
    generate_wireguard_qr_code,
    generate_wireguard_qr,
    create_premium_background,
    compose_qr_card,
    export_final_image,
)


# [Phase 3.1] get_config_caption moved to routers.configs_view
async def process_referral(new_id: int, ref_id: int):
    """پردازش رفرال - فقط برای کاربران جدید"""
    uid = str(new_id)
    if uid in users:
        logger.info(f"⚠️ user {new_id}already registered, referral not recorded")
        return
    if str(ref_id) == str(new_id):
        logger.warning(f"⚠️ user {new_id}attempted to invite themselves")
        return
    key = f"{ref_id}_{new_id}"
    if key not in referrals:
        referrals[key] = {
            'referrer': ref_id,
            'referred': new_id,
            'date': now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
            'reward_given': False
        }
        save_all()
        try:
            await bot.send_message(
                ref_id, 
                f"{premium_emoji('invite', '👥')} کاربر جدید با لینک شما وارد شد!\n"
                f"🆔 آیدی: {new_id}\n"
                f"🎁 بعد از اولین خرید، {configs_pool.get('price_settings', {}).get('referral_bonus', 5000):,} تومان پاداش دریافت خواهید کرد."
            )
        except Exception as e:
            logger.error(f"Error sending referral message to {ref_id}: {e}")
        
        logger.info(f"new referral: {ref_id}invited {new_id}")

async def check_referral_bonus(user_id: int):
    """بررسی و اعمال پاداش رفرال - فقط برای کاربرانی که با لینک دعوت ثبت نام کرده‌اند"""
    user = get_user(user_id)
    ref_id = user.get('referred_by')
    if not ref_id:
        logger.info(f"User {user_id}registered without invite link, no reward granted")
        return False
    if user.get('has_purchased'):
        logger.info(f"User {user_id}already purchased, reward already granted")
        return False
    key = f"{ref_id}_{user_id}"
    if key not in referrals:
        logger.warning(f"⚠️ referral {key}not found in database")
        return False
    if referrals[key].get('reward_given'):
        logger.info(f"referral reward {key}already granted")
        return False
    settings = configs_pool.get('price_settings', {})
    bonus = settings.get('referral_bonus', 5000)
    old_balance = get_user(ref_id).get('balance', 0)
    add_balance(ref_id, bonus)
    referrals[key]['reward_given'] = True
    user['has_purchased'] = True
    save_all()
    
    new_balance = old_balance + bonus
    
    logger.info(f"✅ referral reward {bonus} tomans to user {ref_id} given (from {user_id})")
    if log_system:
        await log_system.log_balance_change(
            user_id=ref_id,
            amount=bonus,
            new_balance=new_balance,
            action="add",
            admin_id=None,
            details=f"Referral reward for referring user {user_id}"
        )
        await log_system.log_user_action(
            user_id=ref_id,
            action="Received referral reward",
            details=f"Amount: {bonus:,} Toman | Referred user: {user_id}"
        )
    try:
        await bot.send_message(
            ref_id,
            f"{premium_emoji('gift', '🎉')} کاربر دعوت شده شما ({user_id}) اولین خرید خود را انجام داد!\n"
            f"{premium_emoji('wallet', '💰')} {bonus:,} تومان به حساب شما اضافه شد\n"
            f"💰 موجودی جدید: {new_balance:,} تومان"
        )
    except Exception as e:
        logger.error(f"Failed to send reward notification to referrer {ref_id}: {e}")
    
    return True

# [Phase 2.1] save_feedback moved to routers.support
        
        
def _build_optional_channel_button(lang: str) -> Optional[InlineKeyboardButton]:
    """ساخت دکمه عضویت اختیاری در کانال با پشتیبانی از عنوان دوزبانه."""
    opt_ch = (configs_pool.get('force_join_settings', {}) or {}).get('optional_channel', {}) or {}
    if not (opt_ch.get('enabled') and opt_ch.get('url')):
        return None
    raw_title = (
        opt_ch.get('title_fa' if lang == 'fa' else 'title_en')
        or opt_ch.get('title')
        or ''
    ).strip()
    if not raw_title or raw_title in ("📣 Join Channel", "📣 عضویت در کانال"):
        btn_text = "📣 عضویت در کانال" if lang == "fa" else "📣 Join Channel"
    else:
        btn_text = raw_title
    opt_style = opt_ch.get('style') if opt_ch.get('style') in (None, 'primary', 'success', 'danger') else None
    return InlineKeyboardButton(text=btn_text, url=str(opt_ch['url']), style=opt_style)


def get_main_keyboard(is_admin: bool = False, lang: str = "fa", user_id: int = None) -> InlineKeyboardMarkup:
    """کیبورد اصلی با پشتیبانی از وضعیت تایید کاربر و سقف تست"""
    show_approval_warning = False
    is_approved = True
    
    if user_id and not is_admin:
        user = get_user(user_id)
        if user.get('registration_status') in ['cancelled', 'rejected']:
            show_approval_warning = True
            is_approved = False
        else:
            can_purchase, msg = can_user_purchase(user_id)
            is_approved = can_purchase
            if not is_approved:
                show_approval_warning = True
    
    # ═══════════════════════════════════════════
    # ✅ بررسی سقف تست کاربر
    # ═══════════════════════════════════════════
    can_take_test = True
    
    if user_id and not is_admin:
        try:
            uid = str(user_id)
            user_test_data = USER_TEST_USAGE.get(uid, {})
            test_count = user_test_data.get('count', 0)
            
            user_settings = get_user_test_settings(user_id)
            max_tests = user_settings.get('max_tests', TEST_SERVICE_STATUS.get('max_tests', 1))
            
            can_take_test = test_count < max_tests
        except Exception as e:
            logger.warning(f"Error checking test limit for user {user_id}: {e}")
            can_take_test = True
    
    if lang == "fa":
        buttons = []
        
        # ─── ردیف هشدار تایید ادمین (اگه لازم بود) ───
        if show_approval_warning:
            buttons.append([
                InlineKeyboardButton(
                    text=t('pending_admin_approval_0b9778ef12', lang),
                    callback_data="noop",
                    style="danger"
                )
            ])
        
        # ─── ردیف ۱: خرید سرویس (تنها) ───
        buttons.append([
            InlineKeyboardButton(
                text=t('buy_service_21bce537d0', lang),
                callback_data="buy_service" if is_approved else "noop",
                style="success" if is_approved else "danger"
            )
        ])
        
        # ─── ردیف ۲: حساب کاربری | کانفیگ‌های من ───
        buttons.append([
            InlineKeyboardButton(text=t('my_configs_c510960766', lang), callback_data="my_configs", style="primary"),
            InlineKeyboardButton(text=t('my_account_ded04b7927', lang), callback_data="my_account" if is_approved else "noop", style="primary")
            
        ])
        
        # ─── ردیف ۳: اعمال کوپن | افزایش موجودی ───
        buttons.append([
            InlineKeyboardButton(text=t('apply_coupon_4e5f8d4d2b', lang), callback_data="apply_coupon", style="primary"),
            InlineKeyboardButton(text=t('increase_balance_81c62efc81', lang), callback_data="increase_balance" if is_approved else "noop", style="primary")
        ])
        
        # ─── ردیف ۴: دعوت از دوستان | پشتیبانی هوشمند ───
        row_4 = [
            InlineKeyboardButton(text=t('invite_friends_f6c5d030ec', lang), callback_data="invite_friends", style="primary"),
            InlineKeyboardButton(text=t('smart_support_d861be9ab3', lang), callback_data="ai_chat", style="primary"),
        ]
        buttons.append(row_4)
        
        test_emoji, test_name = get_test_service_display(lang)
        # ─── ردیف ۵: سرویس تست / خوش‌آمد (فقط اگه تست باقی مونده) ───
        if TEST_SERVICE_STATUS.get('enabled', False) and can_take_test:
            buttons.append([
                InlineKeyboardButton(text=f"{test_emoji} {test_name}", callback_data="get_test_service", style="primary")
            ])

        opt_btn = _build_optional_channel_button(lang)
        if opt_btn is not None:
            buttons.append([opt_btn])

        # ─── ردیف ۶: تغییر زبان ───
        buttons.append([
            InlineKeyboardButton(text=t('change_language_d5c2ea5f9d', lang), callback_data="change_language")
        ])
    
    else:
        buttons = []
        
        # ─── ردیف هشدار تایید ادمین (اگه لازم بود) ───
        if show_approval_warning:
            buttons.append([
                InlineKeyboardButton(
                    text=t('pending_admin_approval_0b9778ef12', lang),
                    callback_data="noop",
                    style="danger"
                )
            ])
        
        # ─── ردیف ۱: خرید سرویس (تنها) ───
        buttons.append([
            InlineKeyboardButton(
                text=t('buy_service_21bce537d0', lang),
                callback_data="buy_service" if is_approved else "noop",
                style="success" if is_approved else "danger"
            )
        ])
        
        # ─── ردیف ۲: حساب کاربری | کانفیگ‌های من ───
        buttons.append([
            InlineKeyboardButton(text=t('my_configs_c510960766', lang), callback_data="my_configs", style="primary"),
            InlineKeyboardButton(text=t('my_account_ded04b7927', lang), callback_data="my_account" if is_approved else "noop", style="primary")
            
        ])
        
        # ─── ردیف ۳: اعمال کوپن | افزایش موجودی ───
        buttons.append([
            InlineKeyboardButton(text=t('apply_coupon_4e5f8d4d2b', lang), callback_data="apply_coupon", style="primary"),
            InlineKeyboardButton(text=t('increase_balance_81c62efc81', lang), callback_data="increase_balance" if is_approved else "noop", style="primary")
        ])
        
        # ─── ردیف ۴: دعوت از دوستان | پشتیبانی هوشمند ───
        row_4 = [
            InlineKeyboardButton(text=t('invite_friends_f6c5d030ec', lang), callback_data="invite_friends", style="primary"),
            InlineKeyboardButton(text=t('smart_support_d861be9ab3', lang), callback_data="ai_chat", style="primary"),
        ]
        buttons.append(row_4)
        
        test_emoji, test_name = get_test_service_display(lang)
        # ─── ردیف ۵: سرویس تست / خوش‌آمد (فقط اگه تست باقی مونده) ───
        if TEST_SERVICE_STATUS.get('enabled', False) and can_take_test:
            buttons.append([
                InlineKeyboardButton(text=f"{test_emoji} {test_name}", callback_data="get_test_service", style="primary")
            ])

        opt_btn = _build_optional_channel_button(lang)
        if opt_btn is not None:
            buttons.append([opt_btn])

        # ─── ردیف ۶: تغییر زبان ───
        buttons.append([
            InlineKeyboardButton(text=t('change_language_d5c2ea5f9d', lang), callback_data="change_language")
        ])
    
    # ─── ردیف آخر: پنل ادمین (فقط ادمین) ───
    if is_admin:
        buttons.append([
            InlineKeyboardButton(text=f"👑 {t('admin_panel_44cb2a095d', lang)}", callback_data="admin_panel")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# [Phase 2.1] get_test_service moved to routers/admin_test.py
from routers.admin_test import get_test_service

        



# [Phase 1.4] get_client_inbounds, xui_detach_inbounds, xui_attach_inbounds, xui_reset_client_traffic moved to services.panel_api

# [Phase 3.2] extend_service and extend_service_start moved to routers/orders.py

async def emergency_backup_from_panel():
    """
    بکاپ اضطراری - بازنویسی کامل اوردرها از پنل با پشتیبانی از IP Limit
    ✅ بهبود: تشخیص دقیق تست vs خرید از ایمیل
    ✅ بهبود: استخراج نام کاربر از کامنت پنل با اولویت بالا
    ✅ بهبود: به‌روزرسانی order_type برای کلاینت‌های تکراری
    """
    global users, orders, referrals, configs_pool, feedbacks, chats, BLACKLIST
    
    logger.info('🚨 emergency panel backup started (keeping existing users)...')
    
    if not is_senai_panel_enabled():
        logger.error('❌ Panel is disabled')
        return {"success": False, "error": "پنل غیرفعال است"}
    
    try:
        
        timestamp = now_tehran().strftime('%Y%m%d_%H%M%S')
        old_backup_dir = os.path.join(DATA_DIR, 'backups')
        os.makedirs(old_backup_dir, exist_ok=True)
        old_backup_file = os.path.join(old_backup_dir, f'before_emergency_restore_{timestamp}.json')
        
        old_data = {
            'users': users.copy(),
            'orders': orders.copy(),
            'referrals': referrals.copy(),
            'configs': configs_pool.copy(),
            'feedback': feedbacks.copy(),
            'chats': chats.copy(),
            'blacklist': {'users': list(BLACKLIST)}
        }
        
        with open(old_backup_file, 'w', encoding='utf-8') as f:
            json.dump(old_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Backup of the previous state at {old_backup_file} saved")
        
        
        logger.info('📡 Fetching information from the panel...')
        
        inbounds = await xui_get_inbounds()
        if not inbounds:
            logger.error('❌ No inbounds found')
            return {"success": False, "error": "هیچ اینباندی یافت نشد"}
        
        clients_dict = {}
        skipped_clients = 0
        bot_clients = 0
        all_inbounds_info = []
        users_with_configs = set()
        
        
        user_names_from_panel = {}
        def extract_user_info(email: str, comment: str) -> tuple:
            """استخراج user_id, user_name و order_type از ایمیل و کامنت"""
            user_id = None
            user_name = None
            order_type = None
            if email.startswith('test_'):
                order_type = 'test'
                parts = email.split('_')
                if len(parts) >= 2 and parts[1].isdigit():
                    user_id = int(parts[1])
            elif email.startswith('t') and '_' in email:
                order_type = 'test'
                match = re.search(r't(\d+)_\d+', email)
                if match:
                    user_id = int(match.group(1))
            elif email.startswith('user'):
                order_type = 'purchase'
                match = re.search(r'user(\d+)', email)
                if match:
                    user_id = int(match.group(1))
            elif email.startswith('u') and '_' in email:
                order_type = 'purchase'
                match = re.search(r'u(\d+)_\d+', email)
                if match:
                    user_id = int(match.group(1))
            
            
            if comment:
                match = re.search(r'^(.*?)\s*\(ID[:=](\d+)\)', comment)
                if match:
                    user_name = match.group(1).strip()
                    user_name = re.sub(r'[<>/\\|]+$', '', user_name).strip()
                    if not user_id:
                        user_id = int(match.group(2))
                    logger.info(f"✅ [comment] user_id: {user_id}, name: {user_name}")
                else:
                    match_id = re.search(r'ID[:=](\d+)', comment)
                    if match_id:
                        if not user_id:
                            user_id = int(match_id.group(1))
                        name_part = comment.replace(match_id.group(0), '').strip()
                        name_part = re.sub(r'[\(\)\[\]\{\}<>/]+', '', name_part).strip()
                        if name_part:
                            user_name = name_part
                            logger.info(f"✅ [comment-ID] user_id: {user_id}, name: {user_name}")
            
            if user_id and not order_type:
                order_type = 'purchase'
            
            return user_id, user_name, order_type
        
        for inbound in inbounds:
            inbound_id = inbound.get('id')
            remark = inbound.get('remark', f'Inbound_{inbound_id}')
            protocol = inbound.get('protocol', 'unknown')
            port = inbound.get('port', '')
            settings = inbound.get('settings', {})
            inbound_clients = settings.get('clients', [])
            
            all_inbounds_info.append({
                'id': inbound_id,
                'remark': remark,
                'protocol': protocol,
                'port': port
            })
            
            for client in inbound_clients:
                if not client.get('enable', True):
                    continue
                    
                email = client.get('email', '')
                if not email:
                    continue
                
                comment = client.get('comment', '')
                
                
                user_id, user_name, order_type = extract_user_info(email, comment)
                
                if user_id:
                    bot_clients += 1
                    users_with_configs.add(user_id)
                    
                    
                    if user_name:
                        user_names_from_panel[str(user_id)] = user_name
                    
                    
                    if email not in clients_dict:
                        clients_dict[email] = {
                            'email': email,
                            'totalGB': client.get('totalGB', 0),
                            'expiryTime': client.get('expiryTime', 0),
                            'enable': client.get('enable', True),
                            'user_id': user_id,
                            'comment': comment,
                            'order_type': order_type or 'purchase',
                            'inbound_ids': [],
                            'inbound_details': [],
                            'ip_limit': client.get('limitIp', 0),
                            'subId': client.get('subId', '') or email,
                            'user_name': user_name
                        }
                    else:
                        
                        existing = clients_dict[email]
                        
                        
                        if order_type == 'test' and existing['order_type'] != 'test':
                            existing['order_type'] = 'test'
                            logger.info(f"🔄 Updating type: {email} → test")
                        
                        
                        if not existing.get('user_name') and user_name:
                            existing['user_name'] = user_name
                            logger.info(f"🔄 Updating name: {email} → {user_name}")
                        
                        
                        if comment and len(comment) > len(existing.get('comment', '')):
                            existing['comment'] = comment
                    
                    
                    clients_dict[email]['inbound_ids'].append(inbound_id)
                    clients_dict[email]['inbound_details'].append({
                        'inbound_id': inbound_id,
                        'remark': remark,
                        'protocol': protocol,
                        'port': port
                    })
                    
                    logger.info(f"✅ Client: {email} (User: {user_id}) - Type: {clients_dict[email]['order_type']} - name: {user_name or 'unknown'}")
                else:
                    skipped_clients += 1
                    logger.info(f"⏭️ Manual client skipped: {email}")
        
        clients = list(clients_dict.values())
        
        
        test_count = len([c for c in clients if c.get('order_type') == 'test'])
        purchase_count = len([c for c in clients if c.get('order_type') == 'purchase'])
        names_found = len(user_names_from_panel)
        
        logger.info(f"✅ {len(clients)} unique client found")
        logger.info(f"⏭️ {skipped_clients} manual client skipped")
        logger.info(f"👥 {len(users_with_configs)} user with an active config")
        logger.info(f"📊 Tests: {test_count} | Purchases: {purchase_count}")
        logger.info(f"📝 {names_found} username extracted from comments")
        
        if not clients:
            return {"success": False, "error": "هیچ کلاینتی که توسط ربات ساخته شده باشد، در پنل یافت نشد!"}
        
        
        logger.info('🗑 Deleting previous orders...')
        orders.clear()
        logger.info('✅ Previous orders deleted')
        
        
        updated_users = 0
        new_users = 0
        
        for user_id in users_with_configs:
            uid = str(user_id)
            
            
            panel_name = user_names_from_panel.get(uid)
            
            if uid in users:
                
                old_name = users[uid].get('name', '')
                
                if panel_name and (old_name.startswith('کاربر_') or old_name == 'کاربر ناشناس' or 'ناشناس' in old_name):
                    users[uid]['name'] = panel_name
                    logger.info(f"✅ User name {user_id} changed from \'{old_name}\' to \'{panel_name}\'")
                elif panel_name and old_name != panel_name:
                    logger.info(f"ℹ️ User {user_id}: previous name \'{old_name}\' was retained (comment: \'{panel_name}')")
                
                users[uid]['has_purchased'] = True
                users[uid]['updated_at'] = now_tehran_iso()
                updated_users += 1
                logger.info(f"👤 User {user_id} updated")
            else:
                
                final_name = panel_name if panel_name else f'کاربر_{user_id}'
                
                users[uid] = {
                    'id': user_id,
                    'name': final_name,
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
                    'notes': f'ایجاد شده از بکاپ اضطراری - {now_tehran().strftime("%Y-%m-%d %H:%M:%S")}',
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
                new_users += 1
                logger.info(f"👤 New user {user_id} created with name \'{final_name}'")
        
        logger.info(f"✅ {updated_users} users updated")
        logger.info(f"✅ {new_users} new users created")
        
       
        new_orders = {}
        order_counter = 0
        
        for client in clients:
            order_counter += 1
            order_id = order_counter
            
            user_id = client.get('user_id')
            email = client.get('email', '')
            order_type = client.get('order_type', 'purchase')
            comment = client.get('comment', '')
            ip_limit = client.get('ip_limit', 0)
            
            total_gb = client.get('totalGB', 0) / (1024**3)
            total_gb = round(total_gb, 1)
            
            expiry_time = client.get('expiryTime', 0)
            days = 30
            if expiry_time > 0:
                try:
                    expiry_date = datetime.fromtimestamp(expiry_time / 1000)
                    days = (expiry_date - datetime.now()).days
                    days = max(1, days)
                except Exception:
                    days = 30
            

            sub_link = build_sub_link_from_client(email, client)
            sub_id_value = client.get('subId', '') or email
            inbound_ids = client.get('inbound_ids', [])
            
            price = 0
            if order_type == 'purchase':
                price_match = re.search(r'price[:=](\d+)', comment, re.IGNORECASE)
                if price_match:
                    price = int(price_match.group(1))
            
            new_orders[str(order_id)] = {
                'order_id': order_id,
                'user_id': user_id,
                'volume': int(total_gb),
                'days': days,
                'price': price,
                'type': order_type,
                'status': 'approved',
                'date': now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
                'approved_date': now_tehran().strftime("%Y-%m-%d %H:%M:%S"),
                'config_link': sub_link,
                'config_id': None,
                'receipt_photo_id': None,
                'email': email,
                'sub_id': sub_id_value,
                'sub_link': sub_link,
                'panel_client_id': None,
                'payment_method': 'emergency_restore',
                'rejected_reason': '',
                'inbound_id': inbound_ids,
                'inbound_details': client.get('inbound_details', []),
                'created_at': now_tehran_iso(),
                'updated_at': now_tehran_iso(),
                'notes': f'بازنویسی از پنل - {now_tehran().strftime("%Y-%m-%d %H:%M:%S")}',
                'ip_limit': ip_limit
            }
            
            logger.info(f"📝 Order #{order_id} for user {user_id} created")
            logger.info(f"   📦 {total_gb}GB/{days} days - type: {order_type} - price: {price:,}tomans")
        
        
        orders.clear()
        orders.update(new_orders)
        
        logger.info(f"✅ {len(new_orders)} new order created")
        logger.info(f"   🧪 Tests: {len([o for o in new_orders.values() if o.get('type') == 'test'])}")
        logger.info(f"   🛒 Purchases: {len([o for o in new_orders.values() if o.get('type') == 'purchase'])}")
        
        
        save_all()
        logger.info('✅ Database saved successfully')
        
       
        backup_dir = os.path.join(DATA_DIR, 'emergency_backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(backup_dir, f'emergency_backup_{timestamp}.json')
        
        backup_data = {
            'users_count': len(users),
            'orders_count': len(new_orders),
            'users_with_configs': len(users_with_configs),
            'total_users': len(users),
            'backup_info': {
                'timestamp': timestamp,
                'date': now_tehran_iso(),
                'type': 'emergency_from_panel_keep_users',
                'users_count': len(users),
                'orders_count': len(new_orders),
                'skipped_clients': skipped_clients,
                'total_clients': bot_clients,
                'test_count': test_count,
                'purchase_count': purchase_count,
                'users_with_configs': len(users_with_configs),
                'users_without_configs': len(users) - len(users_with_configs),
                'new_users': new_users,
                'updated_users': updated_users,
                'names_from_panel': names_found,
                'version': '3.4'
            }
        }
        
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Emergency backup at {backup_file} saved")
        
        return {
            "success": True,
            "users_count": len(users),
            "orders_count": len(new_orders),
            "test_count": test_count,
            "purchase_count": purchase_count,
            "skipped_clients": skipped_clients,
            "total_clients": bot_clients,
            "clients_count": bot_clients,
            "users_with_configs": len(users_with_configs),
            "users_without_configs": len(users) - len(users_with_configs),
            "new_users": new_users,
            "updated_users": updated_users,
            "names_from_panel": names_found,
            "backup_file": backup_file,
            "message": f"✅ {len(users)} کاربر و {len(new_orders)} اوردر بازنویسی شد.\n"
                       f"   🧪 تست‌ها: {test_count}\n"
                       f"   🛒 خریدها: {purchase_count}\n"
                       f"   📝 {names_found} نام از کامنت پنل استخراج شد."
        }
        
    except Exception as e:
        logger.error(f"❌ Error creating emergency backup: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    
    
@dp.message(Command("emergency_backup"), IsAdmin())
async def cmd_emergency_backup(message: Message):
    """بکاپ اضطراری از پنل - نسخه Message (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    lang = get_user(message.from_user.id).get('lang', 'fa')
    
    text = t('b_emergency_backup_from_pane_dd28100782', lang)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=t('yes_execute_6ae7782e30', lang),
                callback_data="confirm_emergency_backup",
                style="danger"
            ),
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data="admin_panel"
            )
        ]
    ])
    
    await message.reply(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
@dp.callback_query(F.data == "confirm_emergency_backup")
@admin_only
async def confirm_emergency_backup(callback: CallbackQuery):
    """تایید و اجرای بکاپ اضطراری"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    
    await callback.message.edit_text(
        t('executing_emergency_backup_525b0746e8', lang)
    )
    
    try:
        
        result = await emergency_backup_from_panel()
        
        if result.get("success"):
            text = t('b_emergency_backup_completed_6177d6f126', lang, fa_parts=lambda: (f"{result.get('users_count', 0)}", f"{result.get('orders_count', 0)}", f"{result.get('clients_count', 0)}", f"{result.get('backup_file', 'نامشخص')}"), en_parts=lambda: (f"{result.get('users_count', 0)}", f"{result.get('orders_count', 0)}", f"{result.get('clients_count', 0)}", f"{result.get('backup_file', 'Unknown')}"))
            
            buttons = [
                [InlineKeyboardButton(
                    text=t('view_users_08d9e7a637', lang),
                    callback_data="admin_users"
                )],
                [InlineKeyboardButton(
                    text=t('view_orders_bdec673bda', lang),
                    callback_data="admin_orders"
                )],
                [InlineKeyboardButton(
                    text=t('admin_panel_bf28b6b107', lang),
                    callback_data="admin_panel"
                )]
            ]
            
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode=ParseMode.HTML
            )
            
        else:
            error = result.get('error', 'Unknown error')
            await callback.message.edit_text(
                f"❌ خطا در بکاپ اضطراری:\n{error}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=t('back_14968ad63f', lang),
                        callback_data="admin_panel"
                    )]
                ])
            )
            
    except Exception as e:
        logger.error(f"Error creating emergency backup: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ خطا: {html.escape(type(e).__name__)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_14968ad63f', lang),
                    callback_data="admin_panel"
                )]
            ])
        )
    
    await safe_answer(callback)

@dp.callback_query(F.data.startswith("admin_test_user_reset_single_"))
@admin_only
async def admin_test_user_reset_single(callback: CallbackQuery):
    """ریست تست یک کاربر خاص"""

    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        target_id = int(callback.data.split("_")[-1])  # ✅ گرفتن آخرین قسمت
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return

    uid = str(target_id)
    if uid not in USER_TEST_USAGE:
        await callback.answer(
            t('this_user_has_no_tests_3ef271c8cb', lang),
            show_alert=True
        )
        return
    
    old_data = USER_TEST_USAGE[uid].copy()
    old_count = old_data.get('count', 0)
    
    
    del USER_TEST_USAGE[uid]
    save_test_usage()
    invalidate_test_users_cache()
    
    user_info = await get_user_info_from_telegram(target_id)
    
    await callback.answer(
        t('user_test_reset_with_tests_905746003a', lang, fa_parts=lambda: (f"{user_info['full_name']}", f'{old_count}'), en_parts=lambda: (f"{user_info['full_name']}", f'{old_count}')),
        show_alert=True
    )
    await admin_test_user_settings(callback)
    
    
    
    
def migrate_test_inbound_data():
    """مهاجرت داده‌های اینباند تست از تک به چندتایی"""
    if 'inbound_id' in TEST_SERVICE_STATUS:
        old_inbound = TEST_SERVICE_STATUS.get('inbound_id')
        if old_inbound and 'inbound_ids' not in TEST_SERVICE_STATUS:
            TEST_SERVICE_STATUS['inbound_ids'] = [old_inbound]
            logger.info(f"✅ Test inbound migration: {old_inbound} -> {TEST_SERVICE_STATUS['inbound_ids']}")
        del TEST_SERVICE_STATUS['inbound_id']
        configs_pool['test_service'] = TEST_SERVICE_STATUS
        save_all()
        
# [Phase 4] AI Chat callback handlers moved to routers.ai_assistant

async def safe_edit_message(callback: CallbackQuery, text: str = None, reply_markup: InlineKeyboardMarkup = None, parse_mode: str = ParseMode.HTML):
    """ویرایش امن پیام با پشتیبانی از انواع پیام و HTML"""
    try:
        message = callback.message
        
        # بررسی نوع پیام
        has_caption = any([
            message.photo,
            message.document,
            message.video,
            message.audio,
            message.animation,
        ])
        
        if has_caption:
            # پیام با caption (عکس/فایل/ویدیو)
            if text:
                await message.edit_caption(
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
            elif reply_markup:
                await message.edit_reply_markup(reply_markup=reply_markup)
                
        elif message.text:
            # پیام متنی
            if text and reply_markup:
                await message.edit_text(
                    text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
            elif reply_markup:
                await message.edit_reply_markup(reply_markup=reply_markup)
            elif text:
                await message.edit_text(
                    text,
                    parse_mode=parse_mode
                )
        else:
            # نوع نامشخص - حذف و ارسال جدید
            try:
                await message.delete()
            except Exception:
                pass
            
            if text:
                await message.answer(
                    text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                
    except Exception as e:
        error_str = str(e)
        
        if "message is not modified" in error_str:
            logger.debug(f"Message not modified for user {callback.from_user.id}")
            return
        
        elif "there is no text in the message to edit" in error_str:
            logger.warning("⚠️ Message cannot be edited; deleting and sending a new one...")
            try:
                await callback.message.delete()
            except Exception:
                pass
            
            if text:
                try:
                    await callback.message.answer(
                        text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup
                    )
                except Exception as e2:
                    logger.error(f"Error sending new message: {e2}")
            return
        
        elif "message to edit not found" in error_str:
            logger.warning("⚠️ Message not found; sending a new message...")
            if text:
                try:
                    await callback.message.answer(
                        text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup
                    )
                except Exception as e2:
                    logger.error(f"Error sending new message: {e2}")
            return
        
        elif "message can't be edited" in error_str:
            logger.warning("⚠️ Message cannot be edited (it may be outdated)")
            try:
                await callback.message.delete()
            except Exception:
                pass
            
            if text:
                try:
                    await callback.message.answer(
                        text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup
                    )
                except Exception as e2:
                    logger.error(f"Error sending new message: {e2}")
            return
        
        else:
            logger.error(f"Error in safe_edit_message: {e}")
        
        
def get_purchase_keyboard(volume: int, days: int, lang: str = "fa") -> InlineKeyboardMarkup:
    buttons = []
    try:
        ready_enabled = READY_PACKAGES.get('enabled', True)
        categories = READY_PACKAGES.get('categories', [])
        has_packages = False
        if ready_enabled and categories:
            for cat in categories:
                if cat.get('is_active', True):
                    active_packages = [p for p in cat.get('packages', []) if p.get('is_active', True)]
                    if active_packages:
                        has_packages = True
                        break
        if ready_enabled and has_packages:
            buttons.append([
                InlineKeyboardButton(
                    text=t('buy_ready_packages_e0b46bba03', lang),
                    callback_data="show_ready_categories",
                    style="primary"
                )
            ])
            logger.info('✅ Ready packages button added to the keyboard')
        else:
            logger.warning(f"⚠️ Ready packages are not displayed - enabled: {ready_enabled}, has_packages: {has_packages}")
            
    except Exception as e:
        logger.error(f"❌ Error checking ready packages: {e}", exc_info=True)
    buttons.extend([
        [
            InlineKeyboardButton(text="➖", callback_data="vol_down"),
            InlineKeyboardButton(text=f"{volume}GB", callback_data="noop", style="primary"),
            InlineKeyboardButton(text="➕", callback_data="vol_up")
        ],
        [
            InlineKeyboardButton(text="➖", callback_data="day_down"),
            InlineKeyboardButton(text=f"{days} {t('days_7609a53ae9', lang)}", callback_data="noop", style="primary"),
            InlineKeyboardButton(text="➕", callback_data="day_up")
        ],
        [
            InlineKeyboardButton(text=f"💳 {t('pay_by_card_8ef3792b24', lang)}", callback_data="pay_card", style="success"),
            InlineKeyboardButton(text=f"💰{t('pay_by_balance_782475a04b', lang)}", callback_data="pay_balance", style="success")
        ],
        [
            InlineKeyboardButton(text=f"🏠 {t('main_menu_9ae3456442', lang)}", callback_data="back_to_main", style="danger")
        ]
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_only_keyboard(lang: str = "fa") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🏠 {t('main_menu_9ae3456442', lang)}", callback_data="back_to_main", style= "danger")]
    ])

def get_cancel_inline_keyboard(lang: str = "fa") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌{t('cancel_payment_77ac7fd08e', lang)}", callback_data="cancel_payment", style="danger")]
    ])



def get_feedback_keyboard(order_id: int, lang: str = "fa") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t('excellent_7403b884c9', lang), callback_data=f"feedback_good_{order_id}"),
            InlineKeyboardButton(text=t('average_63076dca8d', lang), callback_data=f"feedback_medium_{order_id}"),
            InlineKeyboardButton(text=t('bad_1afddf6889', lang), callback_data=f"feedback_bad_{order_id}")
        ],
        [InlineKeyboardButton(text=t('main_menu_0cdd07a7cc', lang), callback_data="back_to_main", style="danger")]
    ])



def get_admin_keyboard(lang: str = "fa") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t('orders_ecbbcfef7a', lang), callback_data="admin_orders"),
            InlineKeyboardButton(text=t('users_6c0a59394d', lang), callback_data="admin_users"),
            InlineKeyboardButton(text=t('ready_package_82fdb1605c', lang), callback_data="admin_ready_packages")
        ],
        [
            InlineKeyboardButton(text=t('health_report_test_79ea763943', lang), callback_data="test_health_report"),
            InlineKeyboardButton(text=t('disk_warning_test_8c3dbfc2a9', lang), callback_data="test_disk_warning"),
            InlineKeyboardButton(text=t('weekly_report_test_5ad08164be', lang), callback_data="test_weekly_report"),
        ],
        [
            InlineKeyboardButton(text=t('chats_02caa6561e', lang), callback_data="admin_chats"),
            InlineKeyboardButton(text=t('configs_fc1a5d9c0e', lang), callback_data="admin_configs"),
            InlineKeyboardButton(text=t('alert_check_e6d7855be2', lang), callback_data="admin_check_alerts")
        ],
        [
            InlineKeyboardButton(text=t('coupon_management_3cfb4152e7', lang), callback_data="admin_coupons"),
            InlineKeyboardButton(text=t('alert_settings_d80975e965', lang), callback_data="admin_alert_settings")
        ],
        [
            InlineKeyboardButton(text=t('stats_f28df125ad', lang), callback_data="admin_stats"),
            InlineKeyboardButton(text=t('server_3960831b5b', lang), callback_data="admin_panel_status"),
            InlineKeyboardButton(text=t('price_settings_36cefcfb5d', lang), callback_data="admin_price_settings")
        ],
        [
            InlineKeyboardButton(text=t('sms_auto_pay_82c3524eb8', lang), callback_data="admin_sms_payment"),
            InlineKeyboardButton(text=t('test_panel_91d16fd13f', lang), callback_data="panel_test"),
            InlineKeyboardButton(text=t('blacklist_b56a9f18a4', lang), callback_data="admin_blacklist")
        ],
        [
            InlineKeyboardButton(text="🤖 AI", callback_data="admin_ai_settings"),
            InlineKeyboardButton(text=t('broadcast_fec8ff7112', lang), callback_data="admin_broadcast"),
            InlineKeyboardButton(text=t('sync_85826adfde', lang), callback_data="admin_sync_configs")
        ],
        [
            InlineKeyboardButton(text=t('shop_management_5571340840', lang), callback_data="admin_shop_settings"),
            InlineKeyboardButton(text=t('test_service_0ac582d9a8', lang), callback_data="admin_test_service"),
            InlineKeyboardButton(text=t('inbounds_418bed4d9d', lang), callback_data="admin_inbounds")
        ],
        [
            InlineKeyboardButton(text=t('backup_9feb2f5c96', lang), callback_data="backup_db"),
            InlineKeyboardButton(text=t('restore_backup_e1fc1d38f5', lang), callback_data="admin_restore_backup"),
            InlineKeyboardButton(text=t('reset_db_b47c0e1750', lang), callback_data="admin_reset_db")
        ],
        [
            InlineKeyboardButton(text=t('backup_manager_auto_btn', lang), callback_data="admin_manage_backups", style="primary"),
            InlineKeyboardButton(text=t('emergency_backup_7cf7965fe8', lang), callback_data="admin_emergency_backup", style="danger")
        ],


        [
            InlineKeyboardButton(text=t('clear_logs_a318ab7b3a', lang), callback_data="admin_clear_logs"),
            InlineKeyboardButton(text=t('force_join_8fb16d5dbf', lang), callback_data="admin_force_join"),
            InlineKeyboardButton(text=t('main_menu_0cdd07a7cc', lang), callback_data="back_to_main", style="danger")
        ]
    ])
        
        
        
@dp.callback_query(F.data == "admin_emergency_backup")
@admin_only
async def admin_emergency_backup(callback: CallbackQuery):
    """دکمه بکاپ اضطراری در پنل ادمین"""
    
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    text = t('b_emergency_backup_from_pane_dd28100782', lang)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=t('yes_execute_6ae7782e30', lang),
                callback_data="confirm_emergency_backup",
                style="danger"
            ),
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data="admin_panel"
            )
        ]
    ])
    
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
    await safe_answer(callback)
            
        
@dp.callback_query(F.data == "test_health_report")
@admin_only
async def test_health_report(callback: CallbackQuery):
    """تست دستی گزارش سلامت"""
    
    await callback.answer("⏳ در حال تولید گزارش...")
    await send_health_report(callback.message.chat.id)
    
    await callback.message.answer("✅ گزارش سلامت ارسال شد!")
@dp.callback_query(F.data == "test_disk_warning")
@admin_only
async def test_disk_warning(callback: CallbackQuery):
    """تست دستی هشدار فضای دیسک"""
    
    await callback.answer("⏳ در حال بررسی...")
    total, used, free = shutil.disk_usage(".")
    free_gb = free / (1024**3)
    warning_msg = f"""
🧪 <b>تست هشدار فضای دیسک</b>

⚠️ <b>هشدار: فضای خالی دیسک کم است!</b>

💾 فضای خالی: {free_gb:.1f} GB
📊 فضای استفاده شده: {used / (1024**3):.1f} GB
📊 کل فضا: {total / (1024**3):.1f} GB

📁 <b>فایل‌های بزرگ:</b>
"""
    large_files = []
    for file in ['bot_debug.log', 'events.log', 'bot_error.log']:
        if os.path.exists(file):
            size_mb = os.path.getsize(file) / (1024 * 1024)
            if size_mb > 1:
                large_files.append(f"• {file}: {size_mb:.1f} MB")
    
    if large_files:
        warning_msg += "\n".join(large_files)
    else:
        warning_msg += "• هیچ فایل بزرگی یافت نشد"
    
    warning_msg += f"""

💡 راهکارها:
• بکاپ‌های قدیمی را حذف کنید
• دیتابیس را بهینه‌سازی کنید

🕐 زمان: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    await callback.message.answer(warning_msg, parse_mode=ParseMode.HTML)
    await callback.answer("✅ هشدار دیسک ارسال شد!")





# ==================== ماژول‌های روتر فاز ۲.۳ (کوپن‌های تخفیف ادمین) ====================
from routers.admin_packages import (
    admin_coupons,
    admin_coupon_create_process,
    admin_coupon_create_start,
    admin_coupon_delete_select,
    admin_coupon_delete_confirm,
    admin_coupon_delete_execute,
    admin_coupons_list,
)

# [Phase 1.1] safe_html imported from utils.helpers


@dp.message(F.text.regexp(r'^/use_coupon(?:_|\s+|@\w+)'))
async def use_coupon(message: Message):
    """اعتبارسنجی و اعمال کوپن - پشتیبانی از /use_coupon_CODE و /use_coupon CODE"""
    user_id = message.from_user.id

    # ✅ اگر ادمین در حالت پیام همگانی هست، به broadcast هدایت کن
    if user_id == ADMIN_ID_INT and user_states.get(user_id, {}).get('awaiting_broadcast'):
        await admin_broadcast_send(message)
        return

    lang = get_user(user_id).get('lang', 'fa')

    # ✅ استخراج کد کوپن از پیام
    code = None
    text = (message.text or "").strip()

    # فرمت 1: /use_coupon_CODE یا /use_coupon_CODE@botname
    match = re.match(r'^/use_coupon_([A-Za-z0-9_]+?)(?:@\w+)?$', text)
    if match:
        code = match.group(1)

    # فرمت 2: /use_coupon CODE یا /use_coupon@botname CODE
    if not code:
        match = re.match(r'^/use_coupon(?:@\w+)?\s+(.+)$', text)
        if match:
            code = match.group(1).strip()

    # ✅ اگر کد پیدا نشد، راهنما نشون بده
    if not code:
        await message.reply(
            t('b_use_discount_coupon_b_to_u_a9b403b479', lang),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('main_menu_0cdd07a7cc', lang),
                    callback_data="back_to_main"
                )]
            ])
        )
        return

    # ==================== بقیه کد اصلی بدون تغییر ====================

    # ✅ دکمه بازگشت
    back_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('main_menu_0cdd07a7cc', lang),
            callback_data="back_to_main"
        )]
    ])

    if code not in COUPONS:
        code_upper = code.upper()
        code_lower = code.lower()
        code_title = code.title()

        suggestion = None
        if code_upper in COUPONS:
            suggestion = code_upper
        elif code_lower in COUPONS:
            suggestion = code_lower
        elif code_title in COUPONS:
            suggestion = code_title

        # ✅ امن‌سازی ورودی کاربر
        code_safe = safe_html(code, max_length=50)
        suggestion_safe = safe_html(suggestion, max_length=50) if suggestion else ""
        
        if suggestion:
            await message.reply(
                t('coupon_code_code_code_not_fo_1c5953d14a', lang, fa_parts=lambda: (f'{code_safe}', f'{suggestion_safe}'), en_parts=lambda: (f'{code_safe}', f'{suggestion_safe}')),
                parse_mode=ParseMode.HTML,
                reply_markup=back_button
            )
            return

        await message.reply(
            t('coupon_code_code_not_found_c_f8ad63bbde', lang, fa_parts=lambda: (f'{code_safe}',), en_parts=lambda: (f'{code_safe}',)),
            parse_mode=ParseMode.HTML,
            reply_markup=back_button
        )
        return

    coupon = COUPONS[code]
    coupon_type = coupon.get('coupon_type', 'normal')

    # ==================== بررسی کوپن ادمین ====================
    if coupon_type == 'admin_special':
        locked_user_id = coupon.get('locked_user_id')

        if locked_user_id is None:
            coupon['locked_user_id'] = user_id
            save_coupons(COUPONS)
            logger.info(f"🔒 Admin coupon {code} for user {user_id} locked (first user)")
        elif locked_user_id != user_id:
            logger.warning(f"⛔ User {user_id} tried to use admin coupon {code} tried to use it (lock: {locked_user_id})")
            await message.reply(
                t('b_this_coupon_is_private_b_t_afed462368', lang),
                parse_mode=ParseMode.HTML,
                reply_markup=back_button
            )
            return

        user_usage = coupon.get('user_usage', {})
        user_used_count = user_usage.get(str(user_id), 0)
        max_usage = coupon.get('usage_limit', 1)

        if user_used_count >= max_usage:
            logger.warning(f"⚠️ user {user_id} reached the maximum uses for admin coupon {code} reached ({user_used_count}/{max_usage})")
            await message.reply(
                t('b_you_have_reached_the_maxim_97e4696029', lang, fa_parts=lambda: (f'{user_used_count}', f'{max_usage}'), en_parts=lambda: (f'{user_used_count}', f'{max_usage}')),
                parse_mode=ParseMode.HTML,
                reply_markup=back_button
            )
            return

        remaining = max_usage - user_used_count
        remaining_text = f"{remaining} بار"
        discount = coupon.get('discount', 0)

        user_states[user_id] = {
            'coupon_code': code,
            'coupon_discount': discount,
            'coupon_applied': True
        }

        logger.info(f"✅ [use_coupon] Admin coupon {code} with discount {discount}% for user {user_id} applied (used {user_used_count + 1}/{max_usage})")
        save_coupon_to_user_db(user_id)

        success_buttons = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('buy_service_21bce537d0', lang),
                callback_data="buy_service",
                style="success"
            )],
            [InlineKeyboardButton(
                text=t('main_menu_0cdd07a7cc', lang),
                callback_data="back_to_main",
                style="primary"
            )]
        ])

        await message.reply(
            t('b_admin_coupon_applied_succe_9bbdb687fa', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('label', '🏷️')}", f'{code}', f"{premium_emoji('discount', '💳')}", f'{discount}', f"{premium_emoji('count', '🔢')}", f'{remaining_text}', f"{premium_emoji('shopping_cart', '🛒')}"), en_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('label', '🏷️')}", f'{code}', f"{premium_emoji('discount', '💳')}", f'{discount}', f"{premium_emoji('count', '🔢')}", f'{remaining_text}', f"{premium_emoji('shopping_cart', '🛒')}")),
            parse_mode=ParseMode.HTML,
            reply_markup=success_buttons
        )
        return

    # ==================== کوپن معمولی ====================
    logger.info(f"🔍 [use_coupon] regular coupon {code} found - status: {coupon.get('status')}, used_by: {coupon.get('used_by', [])}")

    if user_id in coupon.get('used_by', []):
        clear_coupon_from_user_db(user_id)
        await message.reply(
            t('you_have_already_used_this_c_7239e94374', lang),
            parse_mode=ParseMode.HTML,
            reply_markup=back_button
        )
        fully_remove_coupon_from_user(user_id)
        return

    if coupon.get('status') != 'active':
        status_text = {
            'used': '❌ این کوپن به پایان رسیده است!',
            'expired': '❌ این کوپن منقضی شده است!'
        }.get(coupon.get('status'), '❌ این کوپن فعال نیست!')

        await message.reply(
            status_text if lang == "fa" else t('i18n_coupon_inactive', lang),
            parse_mode=ParseMode.HTML,
            reply_markup=back_button
        )
        return

    expiry_date = coupon.get('expiry_date')
    if expiry_date:
        try:
            expiry = datetime.fromisoformat(expiry_date)
            ref_now = now_tehran() if expiry.tzinfo is not None else now_tehran().replace(tzinfo=None)
            if expiry < ref_now:
                coupon['status'] = 'expired'
                save_coupons(COUPONS)
                await message.reply(
                    t('this_coupon_has_expired_8bf708462f', lang),
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_button
                )
                return
        except Exception:
            pass

    usage_limit = coupon.get('usage_limit', 0)
    used_count = coupon.get('used_count', 0)

    if usage_limit > 0 and used_count >= usage_limit:
        coupon['status'] = 'used'
        save_coupons(COUPONS)
        await message.reply(
            t('this_coupon_has_reached_its_ed588c0700', lang),
            parse_mode=ParseMode.HTML,
            reply_markup=back_button
        )
        return

    discount = coupon.get('discount', 0)
    remaining = usage_limit - used_count if usage_limit > 0 else 'نامحدود'

    user_states[user_id] = {
        'coupon_code': code,
        'coupon_discount': discount,
        'coupon_applied': True
    }

    logger.info(f"✅ [use_coupon] coupon {code} with discount {discount}% for user {user_id} applied")
    save_coupon_to_user_db(user_id)

    success_buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('buy_service_21bce537d0', lang),
            callback_data="buy_service",
            style="success"
        )],
        [InlineKeyboardButton(
            text=t('main_menu_0cdd07a7cc', lang),
            callback_data="back_to_main",
            style="primary"
        )]
    ])

    await message.reply(
        t('b_coupon_applied_successfull_e9d9c125d7', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('label', '🏷️')}", f'{code}', f"{premium_emoji('discount', '💳')}", f'{discount}', f"{premium_emoji('count', '🔢')}", f'{remaining}', f"{premium_emoji('shopping_cart', '🛒')}", f"{premium_emoji('light', '💡')}"), en_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('label', '🏷️')}", f'{code}', f"{premium_emoji('discount', '💳')}", f'{discount}', f"{premium_emoji('count', '🔢')}", f'{remaining}', f"{premium_emoji('shopping_cart', '🛒')}", f"{premium_emoji('light', '💡')}")),
        parse_mode=ParseMode.HTML,
        reply_markup=success_buttons
    )
        
@dp.message(lambda m: (
    bool(m.from_user and m.from_user.id != ADMIN_ID_INT)
    and user_states.get(m.from_user.id, {}).get('awaiting_coupon_code')
    and m.text
    and not m.text.startswith('/')
))
async def handle_coupon_code_input(message: Message):
    """پردازش کد کوپن وارد شده در حالت awaiting_coupon_code"""
    user_id = message.from_user.id
    lang = get_user(user_id).get('lang', 'fa')

    # ✅ چک لیست سیاه
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        user_states[user_id].pop('awaiting_coupon_code', None)
        return

    # ✅ استخراج کد
    code = message.text.strip()

    if not code:
        await message.reply(
            t('please_enter_a_valid_code_d372db3254', lang)
        )
        return

    # ✅ حذف state (تا از این به بعد پیام‌های عادی پردازش بشن)
    user_states[user_id].pop('awaiting_coupon_code', None)

    # ══════════════════════════════════════════════
    # اعتبارسنجی کوپن (همون منطق use_coupon)
    # ══════════════════════════════════════════════
    back_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('main_menu_0cdd07a7cc', lang),
            callback_data="back_to_main",
            style="primary"
        )]
    ])

    # ─── کوپن در دیتابیس هست؟ ───
    if code not in COUPONS:
        code_upper = code.upper()
        code_lower = code.lower()
        code_title = code.title()

        suggestion = None
        if code_upper in COUPONS:
            suggestion = code_upper
        elif code_lower in COUPONS:
            suggestion = code_lower
        elif code_title in COUPONS:
            suggestion = code_title

        # ✅ امن‌سازی
        code_safe = safe_html(code, max_length=50)
        suggestion_safe = safe_html(suggestion, max_length=50) if suggestion else ""
        
        if suggestion:
            await message.reply(
                t('coupon_code_code_code_not_fo_1c5953d14a', lang, fa_parts=lambda: (f'{code_safe}', f'{suggestion_safe}'), en_parts=lambda: (f'{code_safe}', f'{suggestion_safe}')),
                parse_mode=ParseMode.HTML,
                reply_markup=back_button
            )
            return

        await message.reply(
            t('coupon_code_code_not_found_c_f8ad63bbde', lang, fa_parts=lambda: (f'{code_safe}',), en_parts=lambda: (f'{code_safe}',)),
            parse_mode=ParseMode.HTML,
            reply_markup=back_button
        )
        return

    coupon = COUPONS[code]
    coupon_type = coupon.get('coupon_type', 'normal')

    # ══════════════════════════════════════════════
    # کوپن ادمین (admin_special)
    # ══════════════════════════════════════════════
    if coupon_type == 'admin_special':
        locked_user_id = coupon.get('locked_user_id')

        # اولین بار → قفل روی این کاربر
        if locked_user_id is None:
            coupon['locked_user_id'] = user_id
            save_coupons(COUPONS)
            logger.info(f"🔒 Admin coupon {code} for user {user_id} locked")

        elif locked_user_id != user_id:
            logger.warning(f"⛔ User {user_id} tried to use admin coupon {code} tried to use it (lock: {locked_user_id})")
            await message.reply(
                t('b_this_coupon_is_private_b_t_5656bf1c5d', lang),
                parse_mode=ParseMode.HTML,
                reply_markup=back_button
            )
            return

        # بررسی تعداد استفاده
        user_usage = coupon.get('user_usage', {})
        user_used_count = user_usage.get(str(user_id), 0)
        max_usage = coupon.get('usage_limit', 1)

        if user_used_count >= max_usage:
            logger.warning(f"⚠️ user {user_id} reached the maximum uses for coupon {code} reached ({user_used_count}/{max_usage})")
            await message.reply(
                t('b_you_have_reached_the_maxim_f6c56d6309', lang, fa_parts=lambda: (f'{user_used_count}', f'{max_usage}'), en_parts=lambda: (f'{user_used_count}', f'{max_usage}')),
                parse_mode=ParseMode.HTML,
                reply_markup=back_button
            )
            return

        # ✅ اعمال کوپن
        remaining = max_usage - user_used_count
        discount = coupon.get('discount', 0)

        if user_id not in user_states:
            user_states[user_id] = {}

        user_states[user_id]['coupon_code'] = code
        user_states[user_id]['coupon_discount'] = discount
        user_states[user_id]['coupon_applied'] = True

        save_coupon_to_user_db(user_id)

        success_buttons = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('buy_service_21bce537d0', lang),
                callback_data="buy_service",
                style="success"
            )],
            [InlineKeyboardButton(
                text=t('main_menu_0cdd07a7cc', lang),
                callback_data="back_to_main",
                style="primary"
            )]
        ])

        await message.reply(
            t('b_admin_coupon_applied_b_cod_db47ed9e6e', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('label', '🏷️')}", f'{code}', f"{premium_emoji('discount', '💳')}", f'{discount}', f"{premium_emoji('count', '🔢')}", f'{remaining}', f"{premium_emoji('shopping_cart', '🛒')}"), en_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('label', '🏷️')}", f'{code}', f"{premium_emoji('discount', '💳')}", f'{discount}', f"{premium_emoji('count', '🔢')}", f'{remaining}')),
            parse_mode=ParseMode.HTML,
            reply_markup=success_buttons
        )
        return

    # ══════════════════════════════════════════════
    # کوپن معمولی
    # ══════════════════════════════════════════════
    logger.info(f"🔍 [coupon_input] regular coupon {code} - status: {coupon.get('status')}, used_by: {coupon.get('used_by', [])}")

    # قبلاً استفاده کرده؟
    if user_id in coupon.get('used_by', []):
        clear_coupon_from_user_db(user_id)
        fully_remove_coupon_from_user(user_id)
        await message.reply(
            t('you_have_already_used_this_c_7239e94374', lang),
            parse_mode=ParseMode.HTML,
            reply_markup=back_button
        )
        return

    # وضعیت کوپن
    if coupon.get('status') != 'active':
        status_text = {
            'used': '❌ این کوپن به پایان رسیده است!',
            'expired': '❌ این کوپن منقضی شده است!'
        }.get(coupon.get('status'), '❌ این کوپن فعال نیست!')

        await message.reply(
            status_text if lang == "fa" else t('i18n_coupon_inactive', lang),
            parse_mode=ParseMode.HTML,
            reply_markup=back_button
        )
        return

    # تاریخ انقضا
    expiry_date = coupon.get('expiry_date')
    if expiry_date:
        try:
            expiry = datetime.fromisoformat(expiry_date)
            ref_now = now_tehran() if expiry.tzinfo is not None else now_tehran().replace(tzinfo=None)
            if expiry < ref_now:
                coupon['status'] = 'expired'
                save_coupons(COUPONS)
                await message.reply(
                    t('this_coupon_has_expired_8bf708462f', lang),
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_button
                )
                return
        except Exception:
            pass

    # ظرفیت
    usage_limit = coupon.get('usage_limit', 0)
    used_count = coupon.get('used_count', 0)

    if usage_limit > 0 and used_count >= usage_limit:
        coupon['status'] = 'used'
        save_coupons(COUPONS)
        await message.reply(
            t('this_coupon_has_reached_its_ed588c0700', lang),
            parse_mode=ParseMode.HTML,
            reply_markup=back_button
        )
        return

    # ✅ اعمال
    discount = coupon.get('discount', 0)
    remaining = usage_limit - used_count if usage_limit > 0 else 'نامحدود'

    if user_id not in user_states:
        user_states[user_id] = {}

    user_states[user_id]['coupon_code'] = code
    user_states[user_id]['coupon_discount'] = discount
    user_states[user_id]['coupon_applied'] = True

    save_coupon_to_user_db(user_id)
    logger.info(f"✅ [coupon_input] coupon {code} with discount {discount}% for user {user_id} applied")

    success_buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('buy_service_21bce537d0', lang),
            callback_data="buy_service",
            style="success"
        )],
        [InlineKeyboardButton(
            text=t('main_menu_0cdd07a7cc', lang),
            callback_data="back_to_main",
            style="primary"
        )]
    ])

    await message.reply(
        t('b_coupon_applied_b_code_code_6370aec08f', lang, fa_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('label', '🏷️')}", f'{code}', f"{premium_emoji('discount', '💳')}", f'{discount}', f"{premium_emoji('count', '🔢')}", f'{remaining}', f"{premium_emoji('shopping_cart', '🛒')}"), en_parts=lambda: (f"{premium_emoji('success', '✅')}", f"{premium_emoji('label', '🏷️')}", f'{code}', f"{premium_emoji('discount', '💳')}", f'{discount}', f"{premium_emoji('count', '🔢')}", f'{remaining}', f"{premium_emoji('shopping_cart', '🛒')}")),
        parse_mode=ParseMode.HTML,
        reply_markup=success_buttons
    )
        

@dp.callback_query(F.data == "test_weekly_report")
@admin_only
async def test_weekly_report(callback: CallbackQuery):
    """تست دستی گزارش هفتگی با جزئیات کامل"""
    
    await callback.answer("⏳ در حال تولید گزارش کامل...")
    await send_weekly_detailed_report(callback.message.chat.id)
    
    await callback.message.answer("✅ گزارش هفتگی ارسال شد!")

# ==================== ماژول‌های روتر فاز ۲.۳ (بسته‌های آماده و هشدارها) ====================
from routers.admin_packages import (
    format_package_volume,
    format_volume,
    buy_specific_package,
    get_admin_users_keyboard,
    get_language_keyboard,
    cmd_test_keyboard,
    cmd_check_coupon,
    cmd_check_storage,
    get_admin_configs_keyboard,
    get_ready_packages_text,
    show_ready_packages_menu,
    get_user_last_purchased_package,
    show_ready_categories,
    show_category_packages,
    admin_ready_packages_menu,
    admin_packages_toggle,
    admin_packages_restrict_toggle,
    admin_category_add_start,
    admin_category_add_process,
    admin_category_edit,
    admin_package_edit,
    package_toggle,
    package_delete,
    admin_alert_settings,
    admin_alert_toggle,
    admin_alert_volume_settings,
    alert_volume_set,
    admin_alert_expiry_settings,
    alert_expiry_set,
    admin_check_alerts,
    admin_clear_alert_cache,
    admin_clear_alert_history,
    admin_confirm_clear_history,
    admin_category_inbounds,
    inbound_save_category,
    migrate_category_inbound_data,
    admin_category_edit_field_save,
    admin_category_toggle,
    admin_category_delete_select,
    admin_category_delete,
    admin_package_add_start,
    admin_package_add_category,
    admin_package_add_process,
)

# Force Join handlers and membership checks have been moved to routers/force_join.py

@dp.message(IsAdmin(), lambda message: user_states.get(message.from_user.id, {}).get('awaiting_config', False))
async def catch_admin_messages(message: Message):
    """هندلر مخصوص ادمین - تایید خودکار از طریق پنل"""
    admin_id = message.from_user.id
    if (message.text or "").strip() == "/cancel":
        user_states.pop(admin_id, None)
        admin_lang = get_user(admin_id).get('lang', 'fa')
        await message.reply(t('i18n_cancel_config_send', admin_lang))
        return
    state = user_states.get(admin_id, {})
    
    order_id = state.get('order_id')
    user_id = state.get('user_id')
    volume = state.get('volume')
    days = state.get('days')
    price = state.get('price')
    user_info = get_user(user_id)
    user_name = user_info.get('name', f'کاربر_{user_id}')
    lang = user_info.get('lang', 'fa')
    
    logger.info(f"🔴 auto-approval of order #{order_id} - client creation in panel...")
    update_order(order_id, status='approved', approved_date=now_tehran().strftime("%Y-%m-%d %H:%M:%S"))
    await check_referral_bonus(user_id)
    if is_senai_panel_enabled():
        await message.reply(t('i18n_client_creation_started', lang, fa_parts=lambda: (order_id,), en_parts=lambda: (order_id,)))
        
        timestamp = int(datetime.now().timestamp())
        email = f"user{user_id}_{timestamp}"
        ip_limit = state.get('ip_limit', 0)
        sub_link = await create_client_in_panel(user_id, email, volume, days, user_name, ip_limit=ip_limit)
        
        if sub_link:
            update_order(order_id, config_link=sub_link, email=email)
            await send_config_with_qr_option(user_id, order_id, volume, days, price, sub_link, lang)
            try:
                await bot.send_message(user_id, 
                    f"{premium_emoji('star', '⭐')} {t('please_rate_our_service_e52df3f954', lang)}",
                    reply_markup=get_feedback_keyboard(order_id, lang)
                )
            except Exception as e:
                logger.error(f"Error sending feedback request: {e}")
            
            await message.reply(
                t('i18n_order_approved_notice', lang, fa_parts=lambda: (order_id, user_name, user_id, volume, days, sub_link[:50]), en_parts=lambda: (order_id, user_name, user_id, volume, days, sub_link[:50]))
            )
        else:
            await message.reply(t('i18n_client_creation_failed_order', lang, fa_parts=lambda: (order_id,), en_parts=lambda: (order_id,)))
            user = get_user(user_id)
            update_user(user_id, 'balance', user['balance'] + price)
            
            try:
                await bot.send_message(user_id,
                    f"{premium_emoji('danger', '❌')} {t('an_error_occurred_your_balan_daec318a5d', lang)}"
                )
            except Exception:
                pass
    else:
        config_link = message.text.strip()
        
        update_order(order_id, config_link=config_link)
        await send_config_with_qr_option(user_id, order_id, volume, days, price, config_link, lang)
        
        try:
            await bot.send_message(user_id, 
                f"{premium_emoji('star', '⭐')} {t('please_rate_our_service_e52df3f954', lang)}",
                reply_markup=get_feedback_keyboard(order_id, lang)
            )
        except Exception as e:
            logger.error(f"Error sending feedback request: {e}")
        
        await message.reply(t('i18n_config_sent_for_order', lang, fa_parts=lambda: (f'{order_id}',), en_parts=lambda: (f'{order_id}',)))
    user_states.pop(admin_id, None)
    logger.info("admin status cleared")
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    coupon_state = user_states.get(user_id, {})
    if coupon_state.get("coupon_applied") and coupon_state.get("coupon_code"):
        save_coupon_to_user_db(user_id)
    debug_coupon_state(user_id, "back_to_main_start")
    user = get_user(user_id)
    lang = user.get('lang', 'fa')
    is_admin = (user_id == ADMIN_ID_INT)
    before_state = user_states.get(user_id, {})
    was_ticket_input = before_state.get('awaiting_chat', False)
    logger.debug(f"User {user_id}returned to main menu - previous status: {before_state}")
    coupon_code = before_state.get('coupon_code')
    coupon_discount = before_state.get('coupon_discount')
    coupon_applied = before_state.get('coupon_applied')
    if before_state.get('awaiting_chat'):
        chat_id = before_state.get('chat_id')
        chat = chats.get(str(chat_id)) if chat_id is not None else None
        if (
            chat
            and chat.get('user_id') == user_id
            and chat.get('kind') == 'ticket'
            and chat.get('status') == 'open'
        ):
            chat['user_input_enabled'] = False
            chat['updated_at'] = now_tehran_iso()
            save_all()
        logger.info(
            'User %s left ticket #%s message-receiving mode by selecting the main menu',
            user_id,
            chat_id,
        )
    
    logger.info(f"🔍 coupon in back_to_main - code: {coupon_code}, applied: {coupon_applied}, discount: {coupon_discount}")
    if user_id in user_states:
        user_states.pop(user_id, None)
    if coupon_applied and coupon_code:
        user_states[user_id] = {
            'coupon_code': coupon_code,
            'coupon_discount': coupon_discount,
            'coupon_applied': True
        }
        logger.info(f"🏷️ coupon {coupon_code} for user {user_id} preserved in back_to_main")
    else:
        logger.debug("No active coupon to preserve for user %s in back_to_main.", user_id)
    save_all()
    after_state = user_states.get(user_id, {})
    logger.info(f"🔍 final user_states status in back_to_main: {after_state}")
    
    text = t('main_menu_c928863059', lang, fa_parts=lambda: (f"{premium_emoji('rocket', '🚀')}",), en_parts=lambda: (f"{premium_emoji('rocket', '🚀')}",))
    if callback.message.content_type == 'text':
        await callback.message.edit_text(text, reply_markup=get_main_keyboard(is_admin, lang, user_id))
    else:
        try:
            await callback.message.delete()
        except Exception as e:
            logger.warning(f"Failed to delete message: {e}")
        
        await bot.send_message(
            callback.message.chat.id,
            text,
            reply_markup=get_main_keyboard(is_admin, lang, user_id)
        )
    has_active_ticket_input = any(
        chat.get('user_id') == user_id and chat.get('kind') == 'ticket' and chat.get('user_input_enabled')
        for chat in get_active_chats()
    )
    if was_ticket_input or has_active_ticket_input:
        await auto_pause_user_ticket_if_active(user_id)
    
    await safe_answer(callback)
        
# [Phase 1.4] test_panel_connection moved to services.panel_api

# Admin Broadcast system and handlers have been moved to routers/admin_broadcast.py


# [Phase 3.2] buy_service and vol_down moved to routers/orders.py

# [Phase 5] show_subscription_qr moved to routers.configs_view

# [Phase 1.4] xui_get_client_links, _panel_* and _rotate_panel_client_identity moved to services.panel_api

async def _show_rotated_subscription(
    chat_id: int, order_id: int, subscription_link: str, lang: str
):
    wireguard_available = await _order_has_wireguard(order_id)
    caption = (
        t('b_subscription_link_changed_3059c55c74', lang, fa_parts=lambda: (f'{html.escape(subscription_link)}',), en_parts=lambda: (f'{html.escape(subscription_link)}',))
    )
    await bot.send_photo(
        chat_id,
        generate_qr_code(subscription_link, order_id),
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=get_config_view_keyboard(
            order_id, show_qr=True, lang=lang,
            wireguard_available=wireguard_available,
        ),
    )


@dp.callback_query(F.data.regexp(r"^change_link_\d+_[012]$"))
async def change_subscription_link_start(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get("lang", "fa")
    try:
        _, _, order_id_raw, mode_raw = callback.data.split("_")
        order_id = int(order_id_raw)
        mode = int(mode_raw)
    except (ValueError, AttributeError):
        await callback.answer(t('invalid_request_f6d37c4966', lang), show_alert=True)
        return

    order = orders.get(str(order_id))
    if (
        mode not in (0, 1, 2)
        or not order
        or order.get("user_id") != user_id
        or order.get("status") not in ("approved", "inactive")
        or not order.get("email")
        or not order.get("config_link")
    ):
        await callback.answer(t('this_config_cannot_be_change_259aec4351', lang), show_alert=True)
        return

    prompt = (
        t('b_change_subscription_link_b_e8a6a18ddc', lang)
    )
    confirmation = await callback.message.answer(
        prompt,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=t('no_4a678298f8', lang),
                callback_data="change_link_no",
                style="primary",
            ),
            InlineKeyboardButton(
                text=t('yes_change_it_0ce2e9bfc4', lang),
                callback_data="change_link_yes",
                style="danger",
            ),
        ]]),
    )
    LINK_ROTATION_CONFIRMATIONS[(user_id, confirmation.message_id)] = {
        "order_id": order_id,
        "email": order["email"],
        "origin_message_id": callback.message.message_id,
        "processing": False,
    }
    await callback.answer()


@dp.callback_query(F.data == "change_link_no")
async def change_subscription_link_cancel(callback: CallbackQuery):
    key = (callback.from_user.id, callback.message.message_id)
    LINK_ROTATION_CONFIRMATIONS.pop(key, None)
    try:
        await callback.message.delete()
    except Exception as e:
        logger.warning(f"Error deleting the link-change cancellation message: {e}")
    await callback.answer(t('cancelled_b818100927', get_user(callback.from_user.id).get("lang", "fa")))


@dp.callback_query(F.data == "change_link_yes")
async def change_subscription_link_confirm(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get("lang", "fa")
    key = (user_id, callback.message.message_id)
    confirmation = LINK_ROTATION_CONFIRMATIONS.get(key)
    if not confirmation or confirmation["processing"]:
        await callback.answer(
            t('this_request_expired_or_is_a_94d45cc288', lang),
            show_alert=True,
        )
        return

    confirmation["processing"] = True
    order_id = confirmation["order_id"]
    email = confirmation["email"]
    lock = LINK_ROTATION_LOCKS.setdefault(email, asyncio.Lock())
    await callback.answer(t('checking_the_panel_9b33556a27', lang))
    try:
        await callback.message.edit_text(
            t('rotating_the_link_and_verify_9c82aff3ed', lang),
        )
        async with lock:
            subscription_link, _ = await _rotate_panel_client_identity(email, user_id, order_id)
    except Exception as e:
        confirmation["processing"] = False
        logger.error(
            'Error changing the subscription link for order #%s for user %s: %s',
            order_id,
            user_id,
            e,
            exc_info=True,
        )
        LINK_ROTATION_CONFIRMATIONS.pop(key, None)
        rollback_failed = "بازگردانی پنل برای اینباندهای" in str(e)
        error_intro = (
            t('link_rotation_failed_the_pre_dabaaf163b', lang) if lang == 'fa' and (not rollback_failed) else t('link_rotation_failed_and_ful_01637925ae', lang) if lang == 'fa' else t('link_rotation_failed_the_pre_dabaaf163b', lang) if not rollback_failed else t('link_rotation_failed_and_ful_01637925ae', lang)
        )
        try:
            await callback.message.edit_text(
                f"{error_intro}\n\n<code>{html.escape(str(e)[:400])}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as delete_error:
            logger.warning(f"Error displaying link-change error: {delete_error}")
        return

    LINK_ROTATION_CONFIRMATIONS.pop(key, None)
    try:
        await bot.delete_message(callback.message.chat.id, confirmation["origin_message_id"])
    except Exception as e:
        logger.warning(f"Error deleting the page containing the old link: {e}")
    try:
        await callback.message.delete()
    except Exception as e:
        logger.warning(f"Error deleting the link-change confirmation message: {e}")
    try:
        await _show_rotated_subscription(
            callback.message.chat.id,
            order_id,
            subscription_link,
            lang,
        )
    except Exception as e:
        logger.error(f"Error displaying the QR code for the new link of order #{order_id}: {e}", exc_info=True)
        wireguard_available = await _order_has_wireguard(order_id)
        await bot.send_message(
            callback.message.chat.id,
            (
                t('link_changed_the_qr_could_no_aa54dc2a1e', lang, fa_parts=lambda: (f'{html.escape(subscription_link)}',), en_parts=lambda: (f'{html.escape(subscription_link)}',))
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=get_config_view_keyboard(
                order_id, show_qr=False, lang=lang,
                wireguard_available=wireguard_available,
            ),
        )
    logger.info('User %s changed subscription link for order #%s', user_id, order_id)


@dp.callback_query(F.data.regexp(r"^daily_usage_\d+(_\d+)?$"))
async def handle_daily_usage_button(callback: CallbackQuery):
    """هندلر دکمه آمار مصرف روزانه اینترنت"""
    parts = callback.data.split("_")
    order_id = int(parts[2])
    from_view = int(parts[3]) if len(parts) > 3 else 0
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    await handle_daily_usage_request(
        callback=callback,
        order_id=order_id,
        from_view=from_view,
        get_order_func=lambda oid: orders.get(str(oid)),
        get_inbounds_func=xui_get_inbounds,
        get_client_traffic_func=xui_get_client_traffic,
        lang=lang
    )


# [Phase 5] _get_cached_config_links, _render_config_page, copy_all_links_file, show_config_text, wireguard, show_single_qr moved to routers.configs_view

# [Phase 3.2] vol_up, day_down, day_up, is_valid_checkout_state, reject_expired_checkout, pay_card, send_receipt_reminder, cancel_order_direct, create_client_in_panel moved to routers/orders.py

@dp.callback_query(F.data == "admin_coupons_stats")
@admin_only
async def admin_coupons_stats(callback: CallbackQuery):
    """آمار کوپن‌ها با نمایش دقیق مصرف"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    total = len(COUPONS)
    active = 0
    used = 0
    expired = 0
    partially_used = 0  # کوپن‌هایی که تا حدی مصرف شده‌اند ولی هنوز فعال هستند
    
    for coupon in COUPONS.values():
        status = coupon.get('status', 'unknown')
        if status == 'active':
            usage_limit = coupon.get('usage_limit', 0)
            used_count = coupon.get('used_count', 0)
            if usage_limit > 0 and 0 < used_count < usage_limit:
                partially_used += 1
            active += 1
        elif status == 'used':
            used += 1
        elif status == 'expired':
            expired += 1
    
    total_usage = sum(c.get('used_count', 0) for c in COUPONS.values())
    most_used = None
    max_usage = 0
    for code, data in COUPONS.items():
        if data.get('used_count', 0) > max_usage:
            max_usage = data.get('used_count', 0)
            most_used = code
    
    text = t('b_coupon_statistics_b_total_34c418f4cd', lang, fa_parts=lambda: (f'{total}', f'{active}', f'{partially_used}', f'{used}', f'{expired}', f'{total_usage}', f"{(most_used if most_used else 'ندارد')}"), en_parts=lambda: (f'{total}', f'{active}', f'{partially_used}', f'{used}', f'{expired}', f'{total_usage}', f"{(most_used if most_used else 'None')}"))
    
    buttons = [
        [InlineKeyboardButton(text=t('refresh_cda5094083', lang), callback_data="admin_coupons_stats")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_coupons")]
    ]
    
    await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    


async def send_admin_notification(purchase_type: str, data: dict):
    """ارسال نوتیفیکیشن ساده و مینیمال به ادمین با حجم هوشمند"""
    
    user_id = data.get('user_id')
    
    # ✅ دریافت اطلاعات کاربر از تلگرام
    try:
        user_info = await get_user_info_from_telegram(user_id)
        user_name_raw = user_info.get('full_name', f'کاربر {user_id}')
        user_username = user_info.get('username', '')
    except Exception as e:
        logger.error(f"Error retrieving user information {user_id}: {e}")
        user_name_raw = f'کاربر {user_id}'
        user_username = ''
    
    # ✅ دریافت نام از دیتابیس (اگه موجود باشه)
    db_name = ''
    try:
        user_db = get_user(user_id)
        if user_db:
            db_name = user_db.get('name', '') or ''
    except Exception:
        pass
    
    # ✅ انتخاب بهترین نام
    if db_name and db_name.strip() and not db_name.startswith('کاربر_'):
        display_name = db_name.strip()
    elif user_name_raw and user_name_raw.strip():
        display_name = user_name_raw.strip()
    else:
        display_name = f'کاربر_{user_id}'
    
    # ✅ نرمال‌سازی یونیکد (تبدیل کاراکترهای فانتزی به ASCII)
    try:
        display_name_normalized = unicodedata.normalize('NFKD', display_name)
        display_name_clean = display_name_normalized.encode('ascii', 'ignore').decode('ascii')
        
        # اگه بعد از نرمال‌سازی خالی شد، از نام اصلی استفاده کن
        if not display_name_clean or display_name_clean.strip() == '':
            display_name_clean = display_name
    except Exception:
        display_name_clean = display_name
    
    # ✅ ساخت نمایش امن HTML
    def safe_html_escape(text: str) -> str:
        """Escape امن برای HTML - نمایش درست < >"""
        if not text:
            return ''
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&#60;')
        text = text.replace('>', '&#62;')
        text = text.replace('"', '&quot;')
        text = text.replace("'", '&#39;')
        return text
    
    user_name_escaped = safe_html_escape(display_name_clean)
    user_username_escaped = safe_html_escape(user_username) if user_username else ''
    
    # ✅ ساخت نمایش کاربر - نام + یوزرنیم باهم
    if user_username_escaped:
        user_display = f"{user_name_escaped} (@{user_username_escaped})"
    else:
        user_display = f"{user_name_escaped}"
    
    # ✅ اطلاعات اصلی
    is_test = (purchase_type == 'test')
    is_extend = (purchase_type == 'extend') or bool(data.get('is_extend', False))
    payment_type = data.get('payment_type', '') or ''
    price = data.get('price', 0) or 0
    
    # ✅ عنوان
    if is_test:
        title = "🧪 تست رایگان"
    elif is_extend:
        if 'balance' in payment_type or 'balance' in str(data.get('payment_label', '')):
            title = "🔄 تمدید با موجودی"
        elif 'card' in payment_type or 'card' in str(data.get('payment_label', '')):
            title = "🔄 تمدید با کارت"
        elif 'free' in payment_type:
            title = "🔄 تمدید رایگان"
        else:
            title = "🔄 تمدید سرویس"
    else:
        if 'balance' in payment_type:
            title = "💰 خرید با موجودی"
        elif 'card' in payment_type:
            title = "💳 خرید با کارت"
        elif 'free' in payment_type:
            title = "🎁 خرید رایگان"
        else:
            title = "🛒 خرید جدید"
    
    # ✅ حجم
    volume = data.get('volume', 'نامشخص')
    
    if isinstance(volume, (int, float)):
        if volume == 0:
            volume_display = "♾️ نامحدود"
        elif is_test:
            volume_display = format_volume(volume, is_test=True)
        else:
            volume_display = format_volume(volume, is_test=False)
    else:
        volume_display = volume
    
    # ✅ محدودیت IP
    ip_limit = data.get('ip_limit', 0) or 0
    ip_display = "نامحدود" if ip_limit == 0 else str(ip_limit)
    
    # ✅ ساخت متن
    text = f"{title}\n\n"
    text += f"👤 {user_display}\n"
    text += f"🆔 <code>{user_id}</code>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📦 {volume_display}\n"
    text += f"⏱️ {data.get('days', 0) or 0} روز\n"
    text += f"💰 {price:,} تومان\n"
    
    # ✅ اطلاعات تمدید
    if is_extend:
        old_volume = data.get('old_volume', 0) or 0
        old_days = data.get('old_days', 0) or 0
        new_volume = data.get('new_volume', 0) or 0
        new_days = data.get('new_days', 0) or 0
        parent_order_id = data.get('parent_order_id', 'نامشخص')
        
        old_volume_display = "♾️ نامحدود" if old_volume == 0 else f"{old_volume:.1f}GB"
        new_volume_display = "♾️ نامحدود" if new_volume == 0 else f"{new_volume:.1f}GB"
        
        text += "━━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"🔄 سفارش اصلی: <code>#{parent_order_id}</code>\n"
        text += f"📦 {old_volume_display} → {new_volume_display}\n"
        text += f"⏱️ {old_days} → {new_days} روز\n"
    
    # ✅ اطلاعات تست
    if is_test:
        remaining_tests = data.get('remaining_tests', 'نامشخص')
        text += f"🧪 تست‌های باقیمانده: {remaining_tests}\n"
        text += f"👤 محدودیت IP: {ip_display}\n"
    
    # ✅ نام بسته
    if data.get('category_name'):
        category_name = safe_html_escape(str(data.get('category_name', '')))
        text += f"📦 بسته: {category_name}\n"
    
    # ✅ شماره سفارش
    if data.get('order_id'):
        text += f"🆔 سفارش: <code>#{data.get('order_id')}</code>\n"
    
    # ✅ موجودی
    if data.get('balance_before') is not None:
        text += f"💰 موجودی قبلی: {data.get('balance_before'):,} تومان\n"
    if data.get('balance_after') is not None:
        text += f"💰 موجودی جدید: {data.get('balance_after'):,} تومان\n"
    
    # ✅ اینباندها
    inbound_ids = data.get('inbound_ids')
    if inbound_ids:
        if isinstance(inbound_ids, list):
            inbound_display = ', '.join(str(ib) for ib in inbound_ids if ib)
            if inbound_display:
                text += f"📡 اینباندها: <code>{inbound_display}</code>\n"
        else:
            text += f"📡 اینباند: <code>{inbound_ids}</code>\n"
    
    # ✅ اطلاعات کوپن
    coupon_code = data.get('coupon_code')
    coupon_discount = data.get('coupon_discount', 0) or 0
    original_price = data.get('original_price', 0) or 0
    
    if coupon_discount > 0:
        text += "━━━━━━━━━━━━━━━━━━━━━━\n"
        text += f"🏷️ کوپن: <code>{safe_html_escape(str(coupon_code))}</code>\n"
        text += f"📊 تخفیف: {coupon_discount}%\n"
        
        if original_price > 0 and original_price != price:
            text += f"💰 قیمت اصلی: {original_price:,} تومان\n"
            text += f"💎 قیمت نهایی: {price:,} تومان\n"
    
    text += f"📅 {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}"
    
    # ✅ ارسال نوتیفیکیشن
    try:
        await bot.send_message(ADMIN_ID_INT, text, parse_mode=ParseMode.HTML)
        logger.info(f"📨 Notification {purchase_type} sent to admin - user {user_id}")
    except Exception as e:
        logger.error(f"❌ Error sending notification to admin: {e}")
        try:
            # ارسال ساده بدون HTML
            simple_text = (
                f"{title}\n"
                f"کاربر: {display_name_clean}\n"
                f"یوزرنیم: @{user_username if user_username else 'ندارد'}\n"
                f"آیدی: {user_id}\n"
                f"مبلغ: {price:,} تومان\n"
                f"نوع: {purchase_type}"
            )
            await bot.send_message(ADMIN_ID_INT, simple_text, parse_mode=None)
            logger.info(f"📨 Notification {purchase_type} sent as plain text")
        except Exception as e2:
            logger.error(f"❌ Error sending simple notification: {e2}")


# [Phase 3.3] Payment & receipt handlers moved to routers/payments.py

async def cleanup_orders_database(days: int = 30, dry_run: bool = False) -> dict:
    
    global orders
    
    logger.info("=" * 60)
    logger.info(f"🧹 starting database cleanup for orders (days={days}, dry_run={dry_run})")
    
    start_time = time.time()
    cutoff_date = now_tehran().replace(tzinfo=None) - timedelta(days=days)
    stats = {
        'total_before': len(orders),
        'deleted_removed': 0,           # status=deleted
        'cancelled_removed': 0,         # status=cancelled (قدیمی)
        'rejected_removed': 0,          # status=rejected (قدیمی)
        'awaiting_payment_removed': 0,  # awaiting_payment بدون receipt (قدیمی)
        'empty_removed': 0,             # سفارش‌های خالی/خراب
        'total_removed': 0,
        'total_after': 0,
        'kept_approved': 0,
        'kept_inactive': 0,
        'kept_pending': 0,
        'kept_rejected': 0, 
        'kept_other': 0,
        'removed_order_ids': [],
        'errors': []
    }
    
    to_delete = []
    
    for oid, order in list(orders.items()):
        try:
            # بررسی معتبر بودن
            if not isinstance(order, dict):
                to_delete.append((oid, 'empty', order))
                stats['empty_removed'] += 1
                continue
            
            # اگه order_id نداره، خرابه
            if 'order_id' not in order:
                to_delete.append((oid, 'empty', order))
                stats['empty_removed'] += 1
                continue
            
            status = order.get('status', '')
            
            # ─────────────────────────────────────────
            # 1. سفارش‌های deleted → همیشه حذف
            # ─────────────────────────────────────────
            if status == 'deleted':
                to_delete.append((oid, 'deleted', order))
                stats['deleted_removed'] += 1
                continue
            
            # ─────────────────────────────────────────
            # 2. سفارش‌های cancelled قدیمی
            # ─────────────────────────────────────────
            if status == 'cancelled':
                updated = order.get('updated_at') or order.get('created_at') or order.get('date', '')
                if _is_older_than(updated, cutoff_date, days):
                    to_delete.append((oid, 'cancelled', order))
                    stats['cancelled_removed'] += 1
                else:
                    stats['kept_other'] += 1
                continue
            
            
            # ─────────────────────────────────────────
            # 3. سفارش‌های rejected → همیشه حفظ
            # ─────────────────────────────────────────
            if status == 'rejected':
                stats['kept_rejected'] += 1
                continue
            
            # ─────────────────────────────────────────
            # 4. awaiting_payment قدیمی و بدون فیش
            # ─────────────────────────────────────────
            if status == 'awaiting_payment':
                has_receipt = bool(order.get('receipt_photo_id'))
                updated = order.get('updated_at') or order.get('created_at') or order.get('date', '')
                
                if not has_receipt and _is_older_than(updated, cutoff_date, days):
                    to_delete.append((oid, 'awaiting_payment', order))
                    stats['awaiting_payment_removed'] += 1
                else:
                    stats['kept_other'] += 1
                continue
            
            # ─────────────────────────────────────────
            # 5. سفارش‌های approved → همیشه حفظ
            # ─────────────────────────────────────────
            if status == 'approved':
                stats['kept_approved'] += 1
                continue
            
            # ─────────────────────────────────────────
            # 6. سفارش‌های inactive → همیشه حفظ
            # ─────────────────────────────────────────
            if status == 'inactive':
                stats['kept_inactive'] += 1
                continue
            
            # ─────────────────────────────────────────
            # 7. pending / pending_balance_charge → همیشه حفظ
            # ─────────────────────────────────────────
            if status in ['pending', 'pending_balance_charge']:
                stats['kept_pending'] += 1
                continue
            
            # ─────────────────────────────────────────
            # 8. بقیه وضعیت‌ها
            # ─────────────────────────────────────────
            stats['kept_other'] += 1
            
        except Exception as e:
            logger.error(f"❌ Error checking order {oid}: {e}")
            stats['errors'].append(f"#{oid}: {str(e)[:50]}")
    
    # ─────────────────────────────────────────
    # اجرای حذف
    # ─────────────────────────────────────────
    stats['total_removed'] = len(to_delete)
    
    if not dry_run:
        # بکاپ قبل از حذف
        if stats['total_removed'] > 0:
            try:
                backup_file = os.path.join(
                    DATA_DIR, 
                    'backups', 
                    f'orders_before_cleanup_{now_tehran().strftime("%Y%m%d_%H%M%S")}.json'
                )
                os.makedirs(os.path.dirname(backup_file), exist_ok=True)
                
                backup_data = {
                    'orders': {oid: order for oid, _, order in to_delete},
                    'backup_info': {
                        'timestamp': now_tehran_iso(),
                        'reason': f'پاکسازی {stats["total_removed"]} سفارش',
                        'days_threshold': days,
                        'stats': stats
                    }
                }
                
                with open(backup_file, 'w', encoding='utf-8') as f:
                    json.dump(backup_data, f, ensure_ascii=False, indent=2)
                
                logger.info(f"💾 Backup of deleted orders at: {backup_file}")
                stats['backup_file'] = backup_file
            except Exception as e:
                logger.error(f"❌ Error creating backup: {e}")
                stats['errors'].append(f"Backup error: {str(e)[:50]}")
        
        # حذف واقعی
        for oid, reason, order in to_delete:
            try:
                del orders[oid]
                stats['removed_order_ids'].append({
                    'order_id': oid,
                    'reason': reason,
                    'user_id': order.get('user_id'),
                    'status': order.get('status'),
                    'type': order.get('type'),
                    'date': order.get('date', ''),
                })
            except Exception as e:
                logger.error(f"❌ Error deleting order {oid}: {e}")
                stats['errors'].append(f"Delete #{oid}: {str(e)[:50]}")
        
        # ذخیره دیتابیس
        try:
            save_json(DB_FILES['orders'], orders)
            logger.info("💾 Orders database saved")
        except Exception as e:
            logger.error(f"❌ Error saving database: {e}")
            stats['errors'].append(f"Save error: {str(e)[:50]}")
    
    stats['total_after'] = len(orders)
    elapsed = time.time() - start_time
    
    # ─────────────────────────────────────────
    # گزارش
    # ─────────────────────────────────────────
    logger.info("-" * 60)
    logger.info("🧹 order cleanup result:")
    logger.info(f"   Before: {stats['total_before']} | After: {stats['total_after']}")
    logger.info(f"   Deleted: {stats['total_removed']}")
    logger.info(f"     ├─ deleted: {stats['deleted_removed']}")
    logger.info(f"     ├─ cancelled: {stats['cancelled_removed']}")
    logger.info(f"     ├─ rejected: {stats['rejected_removed']}")
    logger.info(f"     ├─ awaiting_payment: {stats['awaiting_payment_removed']}")
    logger.info(f"     └─ empty: {stats['empty_removed']}")
    logger.info("   Preserved:")
    logger.info(f"     ├─ approved: {stats['kept_approved']}")
    logger.info(f"     ├─ inactive: {stats['kept_inactive']}")
    logger.info(f"     ├─ pending: {stats['kept_pending']}")
    logger.info(f"     └─ other: {stats['kept_other']}")
    logger.info(f"   Time: {elapsed:.2f} seconds")
    logger.info("=" * 60)
    
    return stats


def _is_older_than(date_str: str, cutoff: datetime, days: int) -> bool:
    """بررسی اینکه تاریخ قدیمی‌تر از cutoff هست یا نه"""
    if not date_str:
        # اگه تاریخ نداره، فرض می‌کنیم قدیمیه
        return True
    
    try:
        # تلاش برای parse کردن تاریخ‌های مختلف
        date_clean = str(date_str).replace(' ', 'T').split('.')[0]
        
        # اگه فقط تاریخ داره (2026-07-28)
        if 'T' not in date_clean:
            date_clean += 'T00:00:00'
        
        updated_dt = datetime.fromisoformat(date_clean)
        
        # اگه timezone داره، حذفش کن
        if updated_dt.tzinfo:
            updated_dt = updated_dt.replace(tzinfo=None)
        
        return updated_dt < cutoff
        
    except Exception as e:
        logger.debug(f"⚠️ Error parsing date \'{date_str}': {e}")
        # اگه نتونستیم parse کنیم، فرض می‌کنیم قدیمیه
        return True
    
    
@dp.message(Command("cleanup_orders"), IsAdmin())
async def cmd_cleanup_orders(message: Message):
    """پاکسازی دیتابیس سفارشات (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    parts = message.text.split()
    dry_run = '--dry' in parts or 'dry' in parts
    days = 15  # ✅ پیش‌فرض 15 روز
    
    # استخراج days اگه داده شده
    for part in parts:
        if part.isdigit():
            days = int(part)
            break
    
    status_msg = await message.reply(
        f"⏳ در حال پاکسازی (days={days}, dry_run={dry_run})..."
    )
    
    try:
        result = await cleanup_orders_database(days=days, dry_run=dry_run)
        
        # ساخت گزارش
        text = f"""
🧹 <b>پاکسازی دیتابیس سفارشات</b>
{'⚠️ (حالت تست - چیزی حذف نشد)' if dry_run else ''}

━━━━━━━━━━━━━━━━━━━━━━
📊 <b>قبل:</b> {result['total_before']} سفارش
📊 <b>بعد:</b> {result['total_after']} سفارش
🗑 <b>حذف شده:</b> {result['total_removed']}
━━━━━━━━━━━━━━━━━━━━━━

<b>🗑 حذف شده:</b>
• 🔴 deleted: {result['deleted_removed']}
• 🟠 cancelled: {result['cancelled_removed']}
• 🟣 awaiting_payment: {result['awaiting_payment_removed']}
• ⚫ empty: {result['empty_removed']}
━━━━━━━━━━━━━━━━━━━━━━

<b>✅ حفظ شده:</b>
• ✅ approved: {result['kept_approved']}
• 🔵 inactive: {result['kept_inactive']}
• ⏳ pending: {result['kept_pending']}
• 🟡 rejected: {result['kept_rejected']}
• 📦 other: {result['kept_other']}
━━━━━━━━━━━━━━━━━━━━━━

{f"⚠️ <b>خطاها:</b> {len(result['errors'])}" if result['errors'] else "✅ بدون خطا"}
{f"💾 <b>بکاپ:</b> <code>{os.path.basename(result.get('backup_file', ''))}</code>" if result.get('backup_file') else ""}
"""
        
        buttons = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔙 برگشت به پنل",
                callback_data="admin_panel"
            )]
        ])
        
        await status_msg.edit_text(text, reply_markup=buttons, parse_mode=ParseMode.HTML)
        
        # ارسال لیست سفارش‌های حذف‌شده
        # ✅ ارسال لیست سفارش‌های حذف‌شده - همیشه به صورت فایل
        if result['removed_order_ids'] and not dry_run:
            try:
                # ساخت محتوای فایل
                lines = [
                    "=" * 70,
                    "📋 گزارش سفارش‌های حذف شده",
                    "=" * 70,
                    f"🕐 تاریخ: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"📊 تعداد کل: {len(result['removed_order_ids'])}",
                    f"⏱ آستانه: {days} روز",
                    "",
                    "📊 تقسیم بر اساس دلیل حذف:",
                    f"  • deleted: {result['deleted_removed']}",
                    f"  • cancelled: {result['cancelled_removed']}",
                    f"  • rejected: {result['rejected_removed']}",
                    f"  • awaiting_payment: {result['awaiting_payment_removed']}",
                    f"  • empty: {result['empty_removed']}",
                    "",
                    "=" * 70,
                    "📋 لیست تفصیلی سفارش‌ها:",
                    "=" * 70,
                    "",
                ]
                
                for i, item in enumerate(result['removed_order_ids'], 1):
                    lines.append(
                        f"{i}. سفارش #{item['order_id']}\n"
                        f"   👤 کاربر: {item['user_id']}\n"
                        f"   📊 وضعیت: {item['status']}\n"
                        f"   📦 نوع: {item['type']}\n"
                        f"   🗑 دلیل حذف: {item['reason']}\n"
                        f"   📅 تاریخ: {item['date']}\n"
                        f"   {'─' * 60}\n"
                    )
                
                # اضافه کردن آمار نهایی
                lines.append("")
                lines.append("=" * 70)
                lines.append("📊 آمار کلی:")
                lines.append("=" * 70)
                lines.append(f"📊 کل قبل: {result['total_before']}")
                lines.append(f"📊 کل بعد: {result['total_after']}")
                lines.append(f"🗑 حذف شده: {result['total_removed']}")
                lines.append("")
                lines.append("✅ حفظ شده:")
                lines.append(f"  • approved: {result['kept_approved']}")
                lines.append(f"  • inactive: {result['kept_inactive']}")
                lines.append(f"  • pending: {result['kept_pending']}")
                lines.append(f"  • rejected: {result.get('kept_rejected', 0)}")
                lines.append(f"  • other: {result['kept_other']}")
                lines.append("")
                lines.append(f"🕐 پایان: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}")
                lines.append("=" * 70)
                
                # تبدیل به bytes
                file_content = "\n".join(lines)
                file_buffer = BytesIO()
                file_buffer.write(file_content.encode('utf-8'))
                file_buffer.seek(0)
                
                # نام فایل با تاریخ
                filename = f"removed_orders_{now_tehran().strftime('%Y%m%d_%H%M%S')}.txt"
                input_file = BufferedInputFile(
                    file_buffer.read(),
                    filename=filename
                )
                
                # کپشن
                caption = (
                    f"📋 <b>گزارش حذف سفارش‌ها</b>\n\n"
                    f"🗑 حذف شده: <b>{result['total_removed']}</b>\n"
                    f"📊 قبل: {result['total_before']} → بعد: {result['total_after']}\n"
                    f"📁 فایل: <code>{filename}</code>"
                )
                
                # ارسال فایل
                await message.answer_document(
                    document=input_file,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
                
                logger.info(f"📨 Report file ({len(result['removed_order_ids'])} order) sent")
                
            except Exception as e:
                logger.error(f"❌ Error sending report file: {e}", exc_info=True)
                # fallback: ارسال به صورت متن اگه فایل کار نکرد
                try:
                    fallback_text = f"❌ خطا در ارسال فایل. تعداد حذف شده: {result['total_removed']}"
                    await message.answer(fallback_text)
                except Exception:
                    pass
        
        # لاگ
        if log_system:
            await log_system.log_admin_action(
                message.from_user.id,
                "Cleaned orders database",
                details=(
                    f"days={days} | dry_run={dry_run} | "
                    f"Deleted: {result['total_removed']} | "
                    f"Remaining: {result['total_after']}"
                )
            )
        
    except Exception as e:
        logger.error(f"❌ Error cleaning up orders: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ خطا در پاکسازی:\n<code>{str(e)[:200]}</code>",
            parse_mode=ParseMode.HTML
        )
        

# [Phase 3.4] Admin order approval, inbound selection & receipt review moved to routers/admin_orders.py

# [Phase 5] my_configs, show_all_my_configs, view_single_config, my_account, order_status, coupon_status, invite_friends, change_language, and support/ticket handlers moved to routers (configs_view, user_account, support)

# ==================== ماژول‌های روتر فاز ۲.۴ (ابزارهای مدیریت، همگام‌سازی و بازسازی) ====================
from routers.admin_tools import (
    admin_chat_reply,
    cmd_check_backup,
    cmd_check_user_coupon,
    add_balance_manual,
    add_new_config,
    auto_log_cleanup,
    admin_reduce_balance_cmd,
    admin_reset_balance_cmd,
    confirm_reset_balance,
    admin_chats_list,
    admin_chat_view,
    admin_close_chat,
    admin_sync_configs,
    admin_clear_logs_confirm,
    admin_clear_logs_execute,
    admin_test_panel,
    sync_deleted_configs,
    sync_user_configs,
)

async def _handle_admin_search_message(message: Message, query: str, lang: str) -> bool:
    """
    پردازش پیام سرچ ادمین
    Returns:
        True اگر پیام پردازش شد، False اگر باید به handler بعدی بره
    """
    user_id = message.from_user.id
    
    # ✅ اگه /cancel
    if query == "/cancel":
        user_states.pop(user_id, None)
        await message.reply(
            t('search_cancelled_fb59f13abc', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=t('panel_617cd9c332', lang),
                    callback_data="admin_panel",
                )
            ]]),
        )
        return True
    
    # ✅ بررسی خالی
    if not query:
        await message.reply(
            t('please_send_a_query_b717532e7d', lang)
        )
        return True
    
    # ✅ بررسی حداقل کاراکتر
    if len(query) < 2:
        await message.reply(
            t('minimum_2_characters_1bf8d91efa', lang)
        )
        return True
    
    # ✅ پاک کردن state
    user_states.pop(user_id, None)
    
    # ✅ سرچ
    results = advanced_search_users(query, search_in="all", limit=200)
    _cache_set(user_id, results, query)
    
    if not results:
        text = t('b_no_results_b_query_code_co_cc01e6084b', lang, fa_parts=lambda: (f'{html.escape(query)}',), en_parts=lambda: (f'{html.escape(query)}',))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('new_search_ff6b25d9d6', lang),
                callback_data="admin_search_users",
            )],
            [InlineKeyboardButton(
                text=t('back_460da353ef', lang),
                callback_data="admin_users",
            )],
        ])
        await message.reply(text, reply_markup=kb, parse_mode="HTML")
        return True
    
    text = format_search_results_text(results, page=0, query=query, lang=lang)
    kb = get_search_results_keyboard(results, page=0, lang=lang)
    await message.reply(text, reply_markup=kb, parse_mode="HTML")
    return True

# [Phase 4] is_ai_question moved to routers.ai_assistant
@fallback_router.message(F.text)
async def handle_text_messages(message: Message):
    """هندلر یکپارچه برای تمام پیام‌های متنی"""
    
    user_id = message.from_user.id
    user_state = user_states.get(user_id, {})
    lang = get_user(user_id).get('lang', 'fa')
    if user_id == ADMIN_ID_INT and user_state.get("awaiting_user_search"):
        handled = await _handle_admin_search_message(
            message, 
            (message.text or "").strip(), 
            lang
        )
        if handled:
            return
    CustomLogger.log_event('MESSAGE', f'Message: {message.text[:50]}', user_id)
    if user_state.get('ai_chat_mode'):
        await process_ai_chat_message(message)
        return
        # ✅ لغو ورودی کوپن
    if user_state.get('awaiting_coupon_code'):
        text = (message.text or "").strip()
        
        if text == '/cancel':
            user_states[user_id].pop('awaiting_coupon_code', None)
            await message.reply(
                t('coupon_input_cancelled_fa93687800', lang),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text=t('main_menu_0cdd07a7cc', lang),
                        callback_data="back_to_main",
                        style="primary"
                    )
                ]])
            )
            return
        
        # اگه دستور دیگه‌ای زد
        if text.startswith('/'):
            user_states[user_id].pop('awaiting_coupon_code', None)
            # اجازه بده به هندلر بعدی بره
        else:
            # پردازش کد کوپن
            await handle_coupon_code_input(message)
            return
    if user_state.get('awaiting_receipt'):
        await message.reply(
            t('i18n_send_receipt_photo_not_text', lang),
            reply_markup=get_cancel_inline_keyboard(lang),
            parse_mode=ParseMode.HTML
        )
        return
    if user_state.get('awaiting_amount'):
        await process_balance_amount(message)
        return
    if user_state.get('awaiting_chat'):
        await handle_chat_message(message)
        return
    if user_state.get('awaiting_feedback_comment'):
        await handle_feedback_comment(message)
        return
    if await block_unauthorized(message, user_id):
        return
    if user_id == ADMIN_ID_INT:
        await handle_admin_special_states(message, user_state)
        return
    if AUTO_AI_RESPONSE and gemini_client:
        if is_ai_question(message.text) and len(message.text.strip()) >= 5:
            can_use, remaining, limit_msg = check_ai_limit(user_id)
            if can_use:
                logger.info(f"🤖 AI automatic response to user question {user_id}")
                await auto_ai_response(message)
                return
    logger.debug(f"status-less message from user {user_id}: {message.text[:50]}")
    

# [Phase 4] AI Purchase Advisor, AI Assistant, and Admin AI commands moved to routers.ai_purchase_advisor, routers.ai_assistant, and routers.admin_ai

@dp.message(Command("help"), IsAdmin())
async def cmd_help_admin(message: Message):
    """نمایش راهنمای کامل دستورات ادمین"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    lang = get_user(message.from_user.id).get('lang', 'fa')
    
    await message.reply(
        t('i18n_admin_command_help', lang),
        parse_mode=ParseMode.HTML
    )
    
    
async def handle_admin_special_states(message: Message, user_state: dict):
    """پردازش وضعیت‌های خاص ادمین - نسخه کامل"""
    admin_id = message.from_user.id
    lang = get_user(admin_id).get('lang', 'fa')
    text = message.text.strip() if message.text else ""
    if text.startswith('/test_full'):
        await cmd_test_full(message)
        return
    
    if text.startswith('/reset_ai_limit'):
        await cmd_reset_ai_limit(message)
        return
    
    if text.startswith('/aistatus'):
        await cmd_ai_status(message)
        return
    
    if text.startswith('/ai_debug'):
        await cmd_ai_debug(message)
        return
    if text.startswith('/emergency_backup'):
        await cmd_emergency_backup(message)
        return
    if text.startswith('/cleanup_orders'):
        await cmd_cleanup_orders(message)
        return
    if text.startswith('/testai'):
        await cmd_test_ai(message)
        return
    
    if text.startswith('/check_storage'):
        await cmd_check_storage(message)
        return
    
    if text.startswith('/checkdata'):
        await cmd_check_data(message)
        return
    
    if text.startswith('/memory'):
        await cmd_memory(message)
        return
    
    if text.startswith('/save'):
        await cmd_save(message)
        return
    
    if text.startswith('/dbstatus'):
        await cmd_db_status(message)
        return
    
    if text.startswith('/check_packages'):
        await cmd_check_packages(message)
        return
    
    if text.startswith('/check_backup'):
        await cmd_check_backup(message)
        return
    
    if text.startswith('/check_coupon'):
        await cmd_check_coupon(message)
        return
    if text.startswith('/check_user_coupon'):
        await cmd_check_user_coupon(message)
        return
    if text.startswith('/use_coupon'):
        await use_coupon(message)
        return
    
    if text.startswith('/blacklist'):
        await cmd_blacklist(message)
        return
    if text.startswith('/stats'):
        await cmd_stats(message)
        return
    if text.startswith('/help'):
        await cmd_help_admin(message)
        return
    if text.startswith('/cleanup_backups'):
        await cmd_cleanup_backups(message)
        return
    
    if text.startswith('/test_keyboard'):
        await cmd_test_keyboard(message)
        return
    if text == '/cancel':
        if user_state.get('awaiting_config'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_config_send', lang))
            return
        elif user_state.get('awaiting_broadcast'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_broadcast', lang))
            return
        elif user_state.get('awaiting_chat_reply'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_chat_reply', lang))
            return
        elif user_state.get('awaiting_manual_balance'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_balance_change', lang))
            return
        elif user_state.get('awaiting_new_config'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_add_config', lang))
            return
        elif user_state.get('awaiting_price_edit'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_price_edit', lang))
            return
        elif user_state.get('awaiting_blacklist_add'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_add_blacklist', lang))
            return
        elif user_state.get('awaiting_category_add'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_add_category', lang))
            return
        elif user_state.get('awaiting_package_add'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_add_package', lang))
            return
        elif user_state.get('awaiting_category_edit'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_edit_category', lang))
            return
        elif user_state.get('awaiting_coupon_create'):
            user_states.pop(admin_id, None)
            await message.reply(t('i18n_cancel_create_coupon', lang))
            return
        else:
            await message.reply(
                t('i18n_admin_cancel_help', lang)
            )
            return
    if user_state.get('awaiting_custom_payment_receipt_amount'):
            await custom_payment_receipt_amount(message)
            return
    elif user_state.get('awaiting_config'):
        await admin_get_config(message)
    
    elif user_state.get('awaiting_broadcast'):
        await admin_broadcast_send(message)
    elif user_state.get('awaiting_chat_reply'):
        await admin_chat_reply(message)
    elif user_state.get('awaiting_manual_balance'):
        await add_balance_manual(message)
    elif user_state.get('awaiting_new_config'):
        await add_new_config(message)
    elif user_state.get('awaiting_price_edit'):
        await save_price_edit(message)
    elif user_state.get('awaiting_blacklist_add'):
        await blacklist_add_user(message)
    elif user_state.get('awaiting_category_add'):
        await admin_category_add_process(message)
    elif user_state.get('awaiting_package_add'):
        await admin_package_add_process(message)
    elif user_state.get('awaiting_category_edit'):
        await admin_category_edit_field_save(message)
    elif user_state.get('awaiting_coupon_create'):
        await admin_coupon_create_process(message)
    else:
        logger.debug(f"Admin - message ignored: {message.text}")


# [Phase 4] auto_ai_response moved to routers.ai_assistant

@dp.callback_query(F.data == "admin_panel")
@admin_only(message='⛔ دسترسی محدود!', return_answer=False, on_denied=lambda callback: logger.warning(f"Unauthorized access to the admin panel by user {callback.from_user.id}"))
async def admin_panel(callback: CallbackQuery):
    version = "v1.8.0"
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    logger.info('admin entered panel management')
    
    
    panel_text = f"{premium_emoji('admin', '👑')} {t('admin_panel_44cb2a095d', lang)} {version}"
    
    try:
        if callback.message.content_type in ['photo', 'document', 'video', 'audio', 'voice', 'animation', 'sticker']:
            await callback.message.delete()
            await callback.message.answer(
                panel_text,
                reply_markup=get_admin_keyboard(lang)
            )
        else:
            await callback.message.edit_text(
                panel_text,
                reply_markup=get_admin_keyboard(lang)
            )
    except Exception as e:
        error_str = str(e)
        if "there is no text in the message to edit" in error_str:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                panel_text,
                reply_markup=get_admin_keyboard(lang)
            )
        else:
            logger.error(f"Error in admin_panel: {e}")
            await callback.answer(t('i18n_panel_display_error', lang), show_alert=True)
            raise
    
    await safe_answer(callback)
        
        

# [Phase 3.4] Admin orders list, view, cancellation & fulfillment moved to routers/admin_orders.py

@dp.callback_query(F.data == "admin_configs")
@admin_only(answer_on_denied=False)
async def admin_configs(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    await callback.message.edit_text(f"{premium_emoji('config', '📦')} {t('config_manager_2e8fcd1c94', lang)}", reply_markup=get_admin_configs_keyboard(lang))
    await safe_answer(callback)

@dp.callback_query(F.data == "admin_add_config")
@admin_only(answer_on_denied=False)
async def admin_add_config(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    await callback.message.answer(t('please_send_the_config_forma_3b9751ba53', lang), parse_mode=ParseMode.MARKDOWN)
    user_states[callback.from_user.id] = {'awaiting_new_config': True}
    await safe_answer(callback)



@dp.callback_query(F.data == "admin_list_configs")
@admin_only(answer_on_denied=False)
async def admin_list_configs(callback: CallbackQuery):
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    configs = get_available_configs()
    
    if not configs:
        text = t('no_configs_available_a81befe7f5', lang)
        try:
            await callback.message.edit_text(text, reply_markup=get_admin_configs_keyboard(lang))
        except Exception as e:
            if "message is not modified" in str(e):
                try:
                    await callback.message.edit_reply_markup(reply_markup=get_admin_configs_keyboard(lang))
                except Exception:
                    pass
            else:
                raise
        
        await safe_answer(callback)
        return
    
    buttons = []
    for c in configs:
        buttons.append([InlineKeyboardButton(
            text=t('i18n_config_list_item', lang, fa_parts=lambda: (c['id'], c['volume'], c['days']), en_parts=lambda: (c['id'], c['volume'], c['days'])),
            callback_data=f"config_detail_{c['id']}"
        )])
    
    buttons.append([InlineKeyboardButton(
        text=f"🔙 {t('back_d35a19b459', lang)}",
        callback_data="admin_configs"
    )])
    
    text = t('available_configs_items_a2be97e8a6', lang, fa_parts=lambda: (f'{len(configs)}',), en_parts=lambda: (f'{len(configs)}',))
    
    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception as e:
        if "message is not modified" in str(e):
            try:
                await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
            except Exception:
                pass
        else:
            raise
    
    await safe_answer(callback)

@dp.callback_query(F.data.startswith("config_detail_"))
@admin_only(answer_on_denied=False)
async def config_detail(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    config_id = int(callback.data.split("_")[2])
    config = None
    for c in configs_pool.get('configs', []):
        if c.get('id') == config_id:
            config = c
            break
    if not config:
        return
    
    text = t('config_volume_gb_duration_da_8631cb4b65', lang, fa_parts=lambda: (f"{premium_emoji('config', '📁')}", f'{config_id}', f"{premium_emoji('box', '📦')}", f"{config['volume']}", f"{premium_emoji('timer', '⏱')}", f"{config['days']}", f"{premium_emoji('link', '🔗')}", f"{config['link']}", f"{('✅ موجود' if not config.get('used') else '❌ استفاده شده')}"), en_parts=lambda: (f"{premium_emoji('config', '📁')}", f'{config_id}', f"{premium_emoji('box', '📦')}", f"{config['volume']}", f"{premium_emoji('timer', '⏱')}", f"{config['days']}", f"{premium_emoji('link', '🔗')}", f"{config['link']}", f"{('✅ Available' if not config.get('used') else '❌ Used')}"))
    buttons = [
        [InlineKeyboardButton(text=t('delete_2bd72b91a8', lang), callback_data=f"delete_config_{config_id}")],
        [InlineKeyboardButton(text=f"🔙 {t('back_d35a19b459', lang)}", callback_data="admin_list_configs")]
    ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)

@dp.callback_query(F.data.startswith("delete_config_"))
@admin_only(answer_on_denied=False)
async def delete_config_handler(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    config_id = int(callback.data.split("_")[2])
    if delete_config(config_id):
        await callback.answer(t('config_deleted_9287da8ac1', lang), show_alert=True)
        logger.info(f"Config #{config_id} deleted by admin")
    else:
        await callback.answer(t('error_deleting_98cfde69f0', lang), show_alert=True)
    await admin_list_configs(callback)

@dp.callback_query(F.data == "admin_users")
@admin_only(answer_on_denied=False)
async def admin_users(callback: CallbackQuery):
    """لیست کاربران با Pagination"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    await callback.message.edit_text(
        t('users_list_22d7a91e6c', lang),
        reply_markup=get_admin_users_keyboard(0, lang)
    )
    await safe_answer(callback)

@dp.callback_query(F.data.startswith("admin_users_page_"))
@admin_only(answer_on_denied=False)
async def admin_users_page(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    page = int(callback.data.split("_")[3])
    await callback.message.edit_text(t('users_list_22d7a91e6c', lang), reply_markup=get_admin_users_keyboard(page, lang))
    await safe_answer(callback)
    
  
@dp.callback_query(F.data.startswith("admin_view_config_"))
@admin_only(answer_on_denied=False)
async def admin_view_config_detail(callback: CallbackQuery):
    """نمایش جزئیات کامل یک کانفیگ برای ادمین با نمایش تعداد کاربر"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    order_id = int(callback.data.split("_")[3])
    
    order = orders.get(str(order_id))
    if not order:
        await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return
    ip_limit = order.get('ip_limit', 0)
    if ip_limit == 0:
        ip_display = "تعداد کاربر: ♾️ نامحدود"
    elif ip_limit == 1:
        ip_display = "تعداد کاربر: ۱ دستگاه"
    else:
        ip_display = f"تعداد کاربر: {ip_limit} دستگاه"
    
    email = get_order_client_email(order)
    if not email:
        await callback.answer(t('i18n_info_unavailable', lang), show_alert=True)
        return
    
    await callback.answer(t('i18n_fetching', lang))
    
    text = f"📧 <b>{email}</b>\n"
    text += f"🆔 سفارش: #{order_id}\n"
    text += f"👤 کاربر: {order.get('user_id')}\n"
    text += f"📦 حجم خرید: {order.get('volume')}GB | ⏳ {order.get('days')} روز\n"
    text += f"💰 قیمت: {order.get('price', 0):,} تومان\n"
    text += f"👤 {ip_display}\n"
    
    if is_senai_panel_enabled():
        client = await xui_get_client_info(email)
        if client:
            traffic = await xui_get_client_traffic(email)
            total = client.get('totalGB', 0) / (1024**3)
            up = (traffic.get('up', 0) if traffic else 0) / (1024**3)
            down = (traffic.get('down', 0) if traffic else 0) / (1024**3)
            used = up + down
            remaining = max(0, total - used)
            enable = client.get('enable', False)
            exp = client.get('expiryTime', 0)
            days_left = max(0, (datetime.fromtimestamp(exp/1000) - datetime.now()).days) if exp > 0 else "∞"
            ip_limit_panel = client.get('limitIp', 0)
            
            if ip_limit_panel == 0:
                ip_panel_display = "نامحدود"
            elif ip_limit_panel == 1:
                ip_panel_display = "۱ دستگاه"
            else:
                ip_panel_display = f"{ip_limit_panel} دستگاه"
            
            text += f"\n📊 <b>وضعیت:</b> {'🟢 فعال' if enable else '🔴 غیرفعال'}\n"
            text += f"📦 حجم کل: {total:.0f} GB\n"
            text += f"📤 آپلود: {up:.2f} GB\n"
            text += f"📥 دانلود: {down:.2f} GB\n"
            text += f"📊 مصرف: {used:.2f} GB\n"
            text += f"⬇️ باقی‌مانده: {remaining:.2f} GB\n"
            text += f"⏳ روزهای باقی‌مانده: {days_left}\n"
            text += f"👤 تعداد کاربر در پنل: {ip_panel_display}\n"
            text += f"\n🔗 <code>{order['config_link']}</code>"
    
    text += f"\n<code>🕐 {now_tehran().strftime('%H:%M:%S')}</code>"
    
    keyboard_buttons = []
    has_cat = bool(order.get('category_id') or order.get('category_name'))
    cat_btn_label = t('i18n_change_order_category', lang) if has_cat else t('i18n_set_order_category', lang)
    keyboard_buttons.append([
        InlineKeyboardButton(text=cat_btn_label, callback_data=f"admin_set_order_cat_{order_id}")
    ])
    keyboard_buttons.append([
        InlineKeyboardButton(text=t('back_to_order_756d7fac90', lang), callback_data=f"view_order_{order_id}"),
        InlineKeyboardButton(text=t('user_e7c760b3e4', lang), callback_data=f"admin_user_{order.get('user_id')}")
    ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("admin_set_order_cat_"))
@admin_only
async def admin_set_order_category_prompt(callback: CallbackQuery):
    """نمایش لیست دسته‌بندی‌ها برای تعیین/تغییر دسته‌بندی سفارش توسط ادمین"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    raw_id = callback.data.replace("admin_set_order_cat_", "")
    try:
        order_id = int(raw_id)
    except (IndexError, ValueError):
        return await callback.answer(t('i18n_invalid_order_id_alert', lang), show_alert=True)
    
    order = orders.get(str(order_id))
    if not order:
        return await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
    
    categories = READY_PACKAGES.get('categories', [])
    if not categories:
        return await callback.answer(t('i18n_no_categories_defined', lang), show_alert=True)
    
    current_cat_name = order.get('category_name') or get_order_category_name(order, lang) or (t('unknown_e68c579791', lang))
    
    text = t('b_set_category_for_order_b_c_2c1a4adb68', lang, fa_parts=lambda: (f'{order_id}', f'{current_cat_name}'), en_parts=lambda: (f'{order_id}', f'{current_cat_name}'))
    
    cat_buttons = []
    for cat in categories:
        icon = cat.get('icon', '📦')
        name = cat.get('name') if lang == "fa" else cat.get('name_en', cat.get('name'))
        is_current = (order.get('category_id') == cat.get('id'))
        mark = t('i18n_current_category_marker', lang) if is_current else ''
        cat_buttons.append([InlineKeyboardButton(
            text=f"{icon} {name}{mark}",
            callback_data=f"admin_apply_order_cat_{order_id}_{cat.get('id')}"
        )])
    
    back_text = t('back_to_order_6608ba1910', lang)
    cat_buttons.append([InlineKeyboardButton(
        text=back_text,
        callback_data=f"view_order_{order_id}"
    )])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=cat_buttons),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_apply_order_cat_"))
@admin_only
async def admin_apply_order_category(callback: CallbackQuery):
    """اعمال دسته‌بندی انتخابی روی سفارش توسط ادمین"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    prefix = "admin_apply_order_cat_"
    data_body = callback.data[len(prefix):]
    try:
        order_id_str, cat_id_str = data_body.split("_", 1)
        order_id = int(order_id_str)
        cat_id = int(cat_id_str)
    except (IndexError, ValueError):
        return await callback.answer(t('i18n_id_processing_error', lang), show_alert=True)
    
    order = orders.get(str(order_id))
    if not order:
        return await callback.answer(t('i18n_order_not_found', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
    
    category = next((c for c in READY_PACKAGES.get('categories', []) if c.get('id') == cat_id), None)
    if not category:
        return await callback.answer(t('i18n_category_not_found', lang), show_alert=True)
    
    cat_name = category.get('name', '')
    cat_name_en = category.get('name_en', cat_name)
    
    update_data = {
        'category_id': cat_id,
        'category_name': cat_name,
        'category_name_en': cat_name_en,
        'updated_at': now_tehran_iso()
    }
    if order.get('type') in ['purchase', 'custom', None, '']:
        update_data['type'] = 'ready_package'
    
    update_order(order_id, **update_data)
    
    alert_msg = t('category_set_to_successfully_84a7c154b7', lang, fa_parts=lambda: (f'{cat_name}',), en_parts=lambda: (f'{cat_name_en}',))
    await callback.answer(alert_msg, show_alert=True)
    
    try:
        updated_callback = callback.model_copy(update={"data": f"view_order_{order_id}"})
        await view_order(updated_callback)
    except Exception as e:
        logger.error(f"Error re-rendering order #{order_id}: {e}")
    
@dp.callback_query(F.data.startswith("admin_add_blacklist_"))
@admin_only
async def admin_add_user_to_blacklist(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    try:
        _, target_value, page_value = callback.data.rsplit("_", 2)
        target_id = int(target_value)
        page = int(page_value)
    except (TypeError, ValueError):
        return await callback.answer(t('i18n_user_info_invalid', lang), show_alert=True)

    if target_id == ADMIN_ID_INT:
        return await callback.answer(
            t('the_admin_account_cannot_be_b4dc441a67', lang),
            show_alert=True,
        )
    if str(target_id) not in users:
        return await callback.answer(
            t('user_not_found_5345dc2f92', lang),
            show_alert=True,
        )
    if target_id in BLACKLIST:
        return await callback.answer(
            t('this_user_is_already_blackli_4673c9731e', lang),
            show_alert=True,
        )

    BLACKLIST.add(target_id)
    if not save_blacklist():
        BLACKLIST.discard(target_id)
        return await callback.answer(
            t('could_not_save_the_blacklist_175b5b1202', lang),
            show_alert=True,
        )

    target_name = html.escape(get_user(target_id).get('name', f'کاربر_{target_id}'))
    CustomLogger.log_event('BLACKLIST_ADD', f'User {target_id} was added to the blacklist from the detail page', target_id)
    if log_system:
        await log_system.log_admin_action(
            callback.from_user.id,
            "Added user to blacklist",
            target_user=target_id,
            details=f"Name: {target_name}",
        )

    await callback.message.edit_text(
        (
            t('user_b_b_id_code_code_was_ad_23edd68275', lang, fa_parts=lambda: (f'{target_name}', f'{target_id}'), en_parts=lambda: (f'{target_name}', f'{target_id}'))
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('remove_from_blacklist_ce91598f51', lang),
                callback_data=f"blacklist_remove_{target_id}",
            )],
            [InlineKeyboardButton(
                text=t('back_to_user_details_6baa038200', lang),
                callback_data=f"admin_user_{target_id}_{page}",
            )],
        ]),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_user_refresh_sync_"))
@admin_only
async def admin_user_refresh_sync(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')

    try:
        _, _, _, _, target_value, page_value = callback.data.split("_")
        target_id = int(target_value)
        page = int(page_value)
    except (TypeError, ValueError):
        return await callback.answer(t('i18n_user_info_invalid', lang), show_alert=True)

    if str(target_id) not in users:
        return await callback.answer(
            t('user_not_found_5345dc2f92', lang),
            show_alert=True,
        )

    await callback.answer(
        t('syncing_user_configs_9821cf9e1c', lang)
    )
    try:
        stats = await sync_user_configs(target_id)
    except Exception as e:
        logger.error('Failed to synchronize user %s: %s', target_id, e, exc_info=True)
        error_text = t('config_sync_failed_4a5249b708', lang)
        await callback.message.edit_text(
            error_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=t('user_details_f8fea105d3', lang),
                    callback_data=f"admin_user_{target_id}_{page}",
                )
            ]]),
        )
        return

    stats_text = (
        t('config_sync_finished_for_use_99042d97ea', lang, fa_parts=lambda: (f'{target_id}', f"{stats.get('total_checked', 0)}", f"{stats.get('new', 0)}", f"{stats.get('approved', 0)}", f"{stats.get('inactive', 0)}", f"{stats.get('deleted', 0)}"), en_parts=lambda: (f'{target_id}', f"{stats.get('total_checked', 0)}", f"{stats.get('new', 0)}", f"{stats.get('approved', 0)}", f"{stats.get('inactive', 0)}", f"{stats.get('deleted', 0)}"))
    )
    if not stats.get('total_checked') and not stats.get('new'):
        stats_text += (
            t('nothing_was_synchronized_che_d874fc3091', lang)
        )
    await callback.message.edit_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t('sync_again_816d337f87', lang),
                callback_data=f"admin_user_refresh_sync_{target_id}_{page}",
            )],
            [InlineKeyboardButton(
                text=t('user_details_f8fea105d3', lang),
                callback_data=f"admin_user_{target_id}_{page}",
            )],
        ]),
    )


@dp.callback_query(F.data.startswith("admin_user_"))
@admin_only(answer_on_denied=False)
async def admin_user_detail(callback: CallbackQuery):
    """مشاهده جزئیات کاربر - با نمایش تاریخچه سفارشات"""
    parts = callback.data.split("_")
    target_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    per_page = 5  # تعداد سفارشات در هر صفحه
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    target = get_user(target_id)
    user_name_raw = target.get('name', f'کاربر_{target_id}')
    user_name_escaped = html.escape(user_name_raw)  # ✅ این خط مهم است
    
    # دریافت یوزرنیم از دیتابیس یا سفارشات
    username = target.get('username') or target.get('telegram_username') or ''
    user_state = user_states.get(target_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_applied = user_state.get('coupon_applied', False)
    
    if not coupon_applied or not coupon_code:
        coupon_data = load_coupon_from_user_db(target_id)
        if coupon_data.get('coupon_applied'):
            coupon_code = coupon_data.get('coupon_code')
            coupon_applied = True
    ref_count = len([r for r in referrals.values() if r.get('referrer') == target_id])
    valid_orders = get_valid_orders()
    user_orders = [o for o in valid_orders.values() if o.get('user_id') == target_id]
    
    if not username:
        for o in user_orders:
            if o.get('username'):
                username = o.get('username')
                break

    # استعلام زنده از تلگرام در صورت خالی بودن یوزرنیم
    if not username:
        try:
            tg_info = await get_user_info_from_telegram(target_id)
            if tg_info and tg_info.get('username'):
                username = tg_info.get('username')
                target['username'] = username
                target['telegram_username'] = username
                if str(target_id) in users:
                    users[str(target_id)]['username'] = username
                    users[str(target_id)]['telegram_username'] = username
            if tg_info and tg_info.get('first_name') and tg_info.get('first_name') != 'نامشخص' and user_name_raw.startswith('کاربر_'):
                user_name_escaped = tg_info.get('first_name')
                target['name'] = user_name_escaped
                if str(target_id) in users:
                    users[str(target_id)]['name'] = user_name_escaped
        except Exception:
            pass

    username_clean = str(username).lstrip('@').strip() if username else ""
    username_line = f"\n🔹 <b>یوزرنیم:</b> @{username_clean}" if username_clean else ""

    approved = [o for o in user_orders if o.get('status') == 'approved']
    pending = [o for o in user_orders if o.get('status') in ['pending', 'pending_balance_charge']]
    awaiting_payment = [o for o in user_orders if o.get('status') == 'awaiting_payment']
    rejected = [o for o in user_orders if o.get('status') == 'rejected']
    cancelled = [o for o in user_orders if o.get('status') == 'cancelled']
    all_orders = sorted(
        user_orders,
        key=lambda x: x.get('date', ''),
        reverse=True
    )
    
    total_orders = len(all_orders)
    total_pages = (total_orders + per_page - 1) // per_page if total_orders > 0 else 1
    
    if page >= total_pages:
        page = total_pages - 1
    if page < 0:
        page = 0
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, total_orders)
    page_orders = all_orders[start_idx:end_idx]
    join_date_escaped = html.escape(target.get('join_date', 'نامشخص'))
    
    text = t('b_b_code_code_t_d80f500220', lang, fa_parts=lambda: (f'{user_name_escaped}', f'{username_line}', f'{target_id}', f"{target.get('balance', 0):,}", f'{ref_count}', f'{len(user_orders)}', f'{len(approved)}', f'{join_date_escaped}'), en_parts=lambda: (f'{user_name_escaped}', f'{username_line}', f'{target_id}', f"{target.get('balance', 0):,}", f'{ref_count}', f'{len(user_orders)}', f'{len(approved)}', f'{join_date_escaped}'))
    buttons = []
    
    if username_clean:
        buttons.append([
            InlineKeyboardButton(
                text=t('message_user_pv_4b2e3dc668', lang),
                url=f"https://t.me/{username_clean}"
            )
        ])
    
    if all_orders:
        text += t('b_orders_b_of_2ba7ac623e', lang, fa_parts=lambda: (f'{start_idx + 1}', f'{end_idx}', f'{total_orders}'), en_parts=lambda: (f'{start_idx + 1}', f'{end_idx}', f'{total_orders}'))
        for o in page_orders:
            order_id = o.get('order_id', '?')
            order_type = o.get('type', 'purchase')
            order_status = o.get('status', 'unknown')
            price = o.get('price', 0)
            volume = o.get('volume', 0)
            days = o.get('days', 0)
            amount = o.get('amount', 0)
            date = html.escape(o.get('date', 'نامشخص')[:10])
            if order_type == 'balance_charge':
                type_icon = "💰"
                type_name = "شارژ"
                detail = f"{amount:,} تومان"
            elif order_type in ['ready_package', 'category_purchase']:
                type_icon = "📦"
                type_name = "بسته"
                detail = f"{volume}GB/{days}روز"
            elif order_type == 'test':
                type_icon = "🧪"
                type_name = "تست"
                detail = f"{volume}GB/{days}روز"
            else:
                type_icon = "🛒"
                type_name = "خرید"
                detail = f"{volume}GB/{days}روز"
            status_icons = {
                'approved': '✅',
                'pending': '📸',
                'pending_balance_charge': '📸',
                'awaiting_payment': '⏳',
                'rejected': '❌',
                'cancelled': '🚫'
            }
            status_icon = status_icons.get(order_status, '❓')
            label = f"{status_icon} #{order_id} {type_icon}{type_name} - {detail} - {price:,}T"
            
            buttons.append([InlineKeyboardButton(
                text=label[:55],
                callback_data=f"view_order_{order_id}"
            )])
        if total_pages > 1:
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton(
                    text=t('prev_ad2dbc546b', lang),
                    callback_data=f"admin_user_{target_id}_{page-1}"
                ))
            
            nav.append(InlineKeyboardButton(
                text=f"{page+1}/{total_pages}",
                callback_data="noop"
            ))
            
            if page < total_pages - 1:
                nav.append(InlineKeyboardButton(
                    text=t('next_c99400f27f', lang),
                    callback_data=f"admin_user_{target_id}_{page+1}"
                ))
            
            if nav:
                buttons.append(nav)
    buttons.append([
        InlineKeyboardButton(text=f"➕ {t('add_14d78fb774', lang)}", callback_data=f"admin_add_balance_{target_id}"),
        InlineKeyboardButton(text=f"➖ {t('reduce_7a5a7676e3', lang)}", callback_data=f"admin_reduce_balance_{target_id}")
    ])
    buttons.append([
        InlineKeyboardButton(text=f"❌ {t('reset_464f250c8b', lang)}", callback_data=f"admin_reset_balance_{target_id}")
    ])
    blacklist_button = InlineKeyboardButton(
        text=(
            t('remove_from_blacklist_a726f98c84', lang)
        ) if target_id in BLACKLIST else (
            t('add_to_blacklist_0cc0469f22', lang)
        ),
        callback_data=(
            f"blacklist_remove_{target_id}"
            if target_id in BLACKLIST
            else f"admin_add_blacklist_{target_id}_{page}"
        ),
    )
    buttons.append([
        InlineKeyboardButton(
            text=f"🧪 {t('edit_user_test_6e1748481c', lang)}",
            callback_data=f"admin_test_user_settings_{target_id}",
        ),
        blacklist_button,
    ])
    buttons.append([
        InlineKeyboardButton(
            text=f"🔄 {t('refresh_sync_configs_cd18bef3ba', lang)}",
            callback_data=f"admin_user_refresh_sync_{target_id}_{page}",
        ),
        InlineKeyboardButton(text=f"🗑 {t('delete_user_0bf6445864', lang)}", callback_data=f"admin_delete_user_{target_id}")
    ])
    cancelled_orders_count = len(cancelled) + len(rejected)
    if cancelled_orders_count > 0:
        buttons.append([
            InlineKeyboardButton(
                text=f"🗑 {t('delete_cancelled_rejected_or_4c28042ab0', lang, fa_format_args=lambda: ((cancelled_orders_count,), {}), en_parts=lambda: (f'{cancelled_orders_count}',))}",
                callback_data=f"delete_cancelled_orders_{target_id}",
                style="danger"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(text=f"🔙 {t('back_d35a19b459', lang)}", callback_data="admin_users")
    ])
    
    text += f"\n\n<code>🕐 {now_tehran().strftime('%H:%M:%S')}</code>"
    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing message: {e}")
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
    if coupon_applied and coupon_code:
        save_coupon_to_user_db(target_id)
    
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("delete_cancelled_orders_"))
@admin_only
async def delete_cancelled_orders(callback: CallbackQuery):
    """حذف تمام سفارشات لغو شده و رد شده یک کاربر"""
    
    target_id = int(callback.data.split("_")[3])
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    valid_orders = get_valid_orders()
    user_orders = [o for o in valid_orders.values() if o.get('user_id') == target_id]
    cancelled_orders = [o for o in user_orders if o.get('status') in ['cancelled', 'rejected']]
    
    if not cancelled_orders:
        await callback.answer(
            t('no_cancelled_or_rejected_ord_6a979fdb14', lang),
            show_alert=True
        )
        return
    text = t('b_delete_cancelled_rejected_e16e53bbf0', lang, fa_parts=lambda: (f"{html.escape(get_user(target_id).get('name', 'کاربر'))}", f'{target_id}', f'{len(cancelled_orders)}'), en_parts=lambda: (f"{html.escape(get_user(target_id).get('name', 'User'))}", f'{target_id}', f'{len(cancelled_orders)}'))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=t('yes_delete_78fa0c3a17', lang),
                callback_data=f"confirm_delete_cancelled_{target_id}",
                style="danger"
            ),
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data=f"admin_user_{target_id}"
            )
        ]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.debug(f"Failed to edit message in delete_cancelled_orders, sending new: {e}")
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("confirm_delete_cancelled_"))
@admin_only
async def confirm_delete_cancelled_orders(callback: CallbackQuery):
    """اجرای حذف سفارشات لغو/رد شده"""
    
    target_id = int(callback.data.split("_")[3])
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    valid_orders = get_valid_orders()
    user_orders = [o for o in valid_orders.values() if o.get('user_id') == target_id]
    cancelled_orders = [o for o in user_orders if o.get('status') in ['cancelled', 'rejected']]
    
    deleted_count = 0
    deleted_ids = []
    
    for o in cancelled_orders:
        oid = str(o.get('order_id'))
        if oid in orders:
            deleted_ids.append(o.get('order_id'))
            del orders[oid]
            deleted_count += 1
            logger.info(f"🗑 order #{o.get('order_id')} (canceled/rejected) deleted")
    save_json(DB_FILES['orders'], orders)
    text = t('b_cancelled_rejected_orders_0d5b967952', lang, fa_parts=lambda: (f"{html.escape(get_user(target_id).get('name', 'کاربر'))}", f'{target_id}', f'{deleted_count}', f"{', '.join(map(str, deleted_ids[:5]))}", f"{('...' if len(deleted_ids) > 5 else '')}"), en_parts=lambda: (f"{html.escape(get_user(target_id).get('name', 'User'))}", f'{target_id}', f'{deleted_count}', f"{', '.join(map(str, deleted_ids[:5]))}", f"{('...' if len(deleted_ids) > 5 else '')}"))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('back_to_user_08846d05c5', lang),
            callback_data=f"admin_user_{target_id}"
        )]
    ])
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.debug(f"Failed to edit message in delete_cancelled_orders, sending new: {e}")
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
    await callback.answer(t('orders_deleted_6ac771ed6a', lang), show_alert=True)



@dp.callback_query(F.data.startswith("admin_add_balance_"))
@admin_only(answer_on_denied=False)
async def admin_add_balance_cmd(callback: CallbackQuery):
    """شروع افزایش موجودی - با ذخیره کوپن کاربر"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    target_id = int(callback.data.split("_")[3])
    target = get_user(target_id)
    target_name_raw = target.get('name', f'کاربر_{target_id}')
    target_name_escaped = html.escape(target_name_raw)
    user_state = user_states.get(target_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount')
    coupon_applied = user_state.get('coupon_applied', False)
    
    logger.info(f"🔍 [admin_add_balance_cmd] user coupon {target_id}: code={coupon_code}, applied={coupon_applied}")
    user_states[callback.from_user.id] = {
        'awaiting_manual_balance': True, 
        'manual_balance_target': target_id,
        'balance_action': 'add',
        'target_coupon_code': coupon_code,
        'target_coupon_discount': coupon_discount,
        'target_coupon_applied': coupon_applied
    }
    
    logger.info(f"🔍 [admin_add_balance_cmd] admin state saved: {user_states[callback.from_user.id]}")
    
    await callback.message.answer(t('please_enter_the_amount_for_dbc573d359', lang, fa_parts=lambda: (f'{target_name_escaped}',), en_parts=lambda: (f'{target_name_escaped}',)))
    
    await safe_answer(callback)



@dp.callback_query(F.data == "admin_stats")
@admin_only(answer_on_denied=False)
async def admin_stats(callback: CallbackQuery):
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    total_users = len(users)
    valid_orders = get_valid_orders()
    approved = [o for o in valid_orders.values() if o.get('status') == 'approved']
    pending = [o for o in valid_orders.values() if o.get('status') == 'pending']
    
    total_revenue = sum(o.get('price', 0) for o in approved)
    total_balance = sum(u.get('balance', 0) for u in users.values())
    available_configs = get_available_configs_count()
    total_used_gb = 0
    total_capacity_gb = 0
    unlimited_configs_count = 0
    panel_stats_available = False

    def is_sold_config(order: dict) -> bool:
        order_type = str(order.get('type', '')).lower()
        return not (
            order.get('is_test')
            or order.get('is_extend')
            or order_type in {'test', 'extend', 'balance_charge'}
        )

    sold_approved_orders = [
        order for order in approved
        if is_sold_config(order)
    ]
    approved_emails = set()
    for order in sold_approved_orders:
        email = order.get('email')
        if not email:
            email = extract_email_from_sub_link(
                order.get('sub_link') or order.get('config_link') or ''
            )
        if email:
            approved_emails.add(str(email))

    category_names = {}
    category_counts = {}
    for category in READY_PACKAGES.get('categories', []):
        category_id = category.get('id')
        if category_id is None:
            continue
        category_names[str(category_id)] = (
            category.get('name') if lang == 'fa'
            else category.get('name_en') or category.get('name')
        ) or (t('category_e867555720', lang, fa_parts=lambda: (f'{category_id}',), en_parts=lambda: (f'{category_id}',)))
        category_counts[str(category_id)] = 0

    custom_order_count = 0
    for order in sold_approved_orders:
        category_id = order.get('category_id')
        category_key = str(category_id) if category_id is not None else None
        category_name = (
            order.get('category_name') if lang == 'fa'
            else order.get('category_name_en') or order.get('category_name')
        )
        if category_key:
            if category_key not in category_names:
                category_names[category_key] = category_name or (
                    t('category_e867555720', lang, fa_parts=lambda: (f'{category_id}',), en_parts=lambda: (f'{category_id}',))
                )
                category_counts[category_key] = 0
            category_counts[category_key] += 1
        elif category_name:
            category_key = f"name:{category_name}"
            category_names[category_key] = category_name
            category_counts[category_key] = category_counts.get(category_key, 0) + 1
        else:
            custom_order_count += 1

    panel_clients = {}
    traffic_by_email = {}
    if is_senai_panel_enabled():
        try:
            inbounds = await xui_get_inbounds(include_disabled=True)
            for inbound in inbounds:
                settings = inbound.get('settings', {})
                if isinstance(settings, str):
                    settings = json.loads(settings)
                if not isinstance(settings, dict):
                    continue
                for client in settings.get('clients', []):
                    email = client.get('email')
                    if not email or str(email) not in approved_emails:
                        continue
                    panel_clients.setdefault(str(email), client)

                client_stats = inbound.get('clientStats', [])
                if isinstance(client_stats, str):
                    client_stats = json.loads(client_stats)
                if isinstance(client_stats, list):
                    for client_stat in client_stats:
                        email = client_stat.get('email')
                        if email and str(email) in approved_emails:
                            try:
                                up = int(client_stat.get('up', 0) or 0)
                                down = int(client_stat.get('down', 0) or 0)
                            except (TypeError, ValueError):
                                logger.warning('Invalid client traffic statistics in the panel were ignored')
                                continue
                            traffic_by_email[str(email)] = (
                                traffic_by_email.get(str(email), 0) + up + down
                            )

            actual_clients = {
                email: client
                for email, client in panel_clients.items()
            }
            panel_stats_available = bool(inbounds)
            active_configs_count = len(actual_clients)
            for client in actual_clients.values():
                if client.get('totalGB') is None:
                    logger.warning('Client volume limit is not available in the panel')
                    continue
                try:
                    total_bytes = int(client.get('totalGB') or 0)
                except (TypeError, ValueError):
                    logger.warning('Invalid client volume ignored in panel statistics')
                    continue
                if total_bytes == 0:
                    unlimited_configs_count += 1
                else:
                    total_capacity_gb += total_bytes / (1024 ** 3)

            total_used_gb = sum(
                traffic_by_email.get(email, 0)
                for email, client in actual_clients.items()
                if client.get('totalGB')
            ) / (1024 ** 3)
        except Exception as e:
            logger.error(f"Error retrieving panel statistics: {e}", exc_info=True)
            panel_stats_available = False

    category_lines_fa = [
        f"• {category_names[key]}: {count}"
        for key, count in category_counts.items()
    ]
    category_lines_en = [
        f"• {category_names[key]}: {count}"
        for key, count in category_counts.items()
    ]
    category_text_fa = "\n".join(category_lines_fa) or "• دسته‌ای تعریف نشده است"
    category_text_en = "\n".join(category_lines_en) or "• No categories defined"
    now = now_tehran().strftime("%H:%M:%S")
    
    panel_text = (
        t('approved_configs_in_panel_un_1052dbdec1', lang, fa_parts=lambda: (f'{active_configs_count}', f'{unlimited_configs_count}', f'{total_capacity_gb:.2f}', f'{total_used_gb:.2f}', f'{max(total_capacity_gb - total_used_gb, 0):.2f}'), en_parts=lambda: (f'{active_configs_count}', f'{unlimited_configs_count}', f'{total_capacity_gb:.2f}', f'{total_used_gb:.2f}', f'{max(total_capacity_gb - total_used_gb, 0):.2f}'))
        if panel_stats_available else t('failed_to_retrieve_panel_inf_ced5427e01', lang)
    )
    text = t('b_system_statistics_b_code_c_196cc9120a', lang, fa_parts=lambda: (f'{now}', f'{total_users}', f'{len(valid_orders)}', f'{len(approved)}', f'{len(pending)}', f'{total_revenue:,}', f'{total_balance:,}', f'{category_text_fa}', f'{custom_order_count}', f'{panel_text}', f'{available_configs}'), en_parts=lambda: (f'{now}', f'{total_users}', f'{len(valid_orders)}', f'{len(approved)}', f'{len(pending)}', f'{total_revenue:,}', f'{total_balance:,}', f'{category_text_en}', f'{custom_order_count}', f'{panel_text}', f'{available_configs}'))
    
    buttons = [
        [InlineKeyboardButton(text=t('refresh_cda5094083', lang), callback_data="admin_stats")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
    ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data == "admin_reset_db")
@admin_only(answer_on_denied=False)
async def admin_reset_db_confirm(callback: CallbackQuery):
    """تایید ریستارت دیتابیس - با دو گزینه"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    active_configs_count = 0
    if is_senai_panel_enabled():
        valid_orders = get_valid_orders()
        approved_orders = [o for o in valid_orders.values() 
                          if o.get('status') == 'approved' and o.get('config_link')]
        active_configs_count = len(approved_orders)
    
    if lang == "fa":
        text = t('b_reset_database_select_rese_94e47c3880', lang, fa_parts=lambda: (f'{active_configs_count}',))
        buttons = [
            [InlineKeyboardButton(text=t('reset_database_bot_only_92c1beed54', lang), callback_data="reset_db_only", style="primary")],  # تغییر نام
            [InlineKeyboardButton(text=t('full_reset_db_panel_137b92dc9c', lang), callback_data="reset_db_full", style="danger")],
            [InlineKeyboardButton(text=t('cancel_4197bafba5', lang), callback_data="admin_panel")]
        ]
    else:
        text = t('b_reset_database_select_rese_94e47c3880', lang, en_parts=lambda: (f'{active_configs_count}',))
        buttons = [
            [InlineKeyboardButton(text=t('reset_database_bot_only_92c1beed54', lang), callback_data="reset_db_only", style="primary")],
            [InlineKeyboardButton(text=t('full_reset_db_panel_137b92dc9c', lang), callback_data="reset_db_full", style="danger")],
            [InlineKeyboardButton(text=t('cancel_4197bafba5', lang), callback_data="admin_panel")]
        ]
    
    await callback.message.edit_text(
        text, 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    await safe_answer(callback)
        
        

        
@dp.callback_query(F.data == "reset_db_only")
@admin_only(answer_on_denied=False)
async def reset_db_only(callback: CallbackQuery):
    """ریست فقط دیتابیس (کانفیگ‌های پنل حفظ می‌شوند)"""
    global users, orders, referrals, configs_pool, feedbacks, chats, BLACKLIST  # ✅ اینجا باید اول باشد
    
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    text = t('b_confirm_database_reset_b_t_715493cd7a', lang)
    
    buttons = [
        [
            InlineKeyboardButton(
                text=t('yes_reset_2fbc55f87f', lang),
                callback_data="confirm_reset_db_only",
                style="danger"
            ),
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data="admin_panel"
            )
        ]
    ]
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)


@dp.callback_query(F.data == "confirm_reset_db_only")
@admin_only(answer_on_denied=False)
async def confirm_reset_db_only(callback: CallbackQuery):
    """اجرای ریست دیتابیس"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    await callback.message.edit_text(
        t('i18n_reset_database_working', lang),
        reply_markup=None
    )
    
    try:
        logger.info('💾 Backing up before database reset...')
        await callback.message.edit_text(t('i18n_taking_backup_ellipsis', lang))
        backup_database()
        active_configs_before = []
        if is_senai_panel_enabled():
            valid_orders = get_valid_orders()
            approved_orders = [o for o in valid_orders.values() 
                              if o.get('status') == 'approved' and o.get('config_link')]
            for o in approved_orders:
                email = extract_email_from_sub_link(o.get('config_link', ''))
                if email:
                    active_configs_before.append({
                        'email': email,
                        'user_id': o.get('user_id'),
                        'order_id': o.get('order_id')
                    })
            logger.info(f"📊 Number of active configurations before reset: {len(active_configs_before)}")
        saved_user_inbound_selection = USER_INBOUND_SELECTION.copy()
        saved_user_test_usage = USER_TEST_USAGE.copy()
        await callback.message.edit_text(t('i18n_cleaning_database', lang))
        reset_database_collections()
        COUPONS.clear()
        save_coupons(COUPONS)
        user_states.clear()
        save_json(DB_FILES['user_states'], {})
        try:
            usage_store.clear_all_data()
        except Exception as e_du:
            logger.warning(f"⚠️ Error clearing daily_usage during reset: {e_du}")
        try:
            sms_payment_manager.db.clear_all_data()
        except Exception as e_sms:
            logger.warning(f"⚠️ Error clearing sms_payments during reset: {e_sms}")
        try:
            if 'alert_system' in globals() and alert_system:
                alert_system.clear_all_history()
            else:
                save_json(os.path.join(DATA_DIR, 'alert_cache.json'), {})
        except Exception as e_ac:
            logger.warning(f"⚠️ Error clearing alert_cache during reset: {e_ac}")
        USER_INBOUND_SELECTION.clear()
        USER_INBOUND_SELECTION.update(saved_user_inbound_selection)
        
        USER_TEST_USAGE.clear()
        USER_TEST_USAGE.update(saved_user_test_usage)
        await callback.message.edit_text(t('i18n_saving_database', lang))
        save_all()
        
        logger.info("✅ Database reset - panel configs were left untouched")
        logger.info(f"📊 Active configs in the panel: {len(active_configs_before)} number")
        text = t('b_database_reset_successfull_d83c3b8c7b', lang, fa_parts=lambda: (f'{len(active_configs_before)}',), en_parts=lambda: (f'{len(active_configs_before)}',))
        
        buttons = [
            [InlineKeyboardButton(
                text=t('sync_with_panel_3d8cee5b4a', lang),
                callback_data="admin_sync_configs"
            )],
            [InlineKeyboardButton(
                text=t('emergency_backup_from_panel_f37a897b08', lang),
                callback_data="admin_emergency_backup",
                style="primary"
            )],
            [InlineKeyboardButton(
                text=t('view_orders_bdec673bda', lang),
                callback_data="admin_orders"
            )],
            [InlineKeyboardButton(
                text=t('back_to_panel_63039f103a', lang),
                callback_data="admin_panel"
            )]
        ]
        
        await callback.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        
        logger.info(f"✅ Database by admin {callback.from_user.id} reset")
        
    except Exception as e:
        logger.error(f"❌ Error resetting database: {e}", exc_info=True)
        err_str = str(e)
        text = t('error_resetting_database_18e3f39706', lang, fa_parts=lambda: (err_str,), en_parts=lambda: (err_str,))
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_14968ad63f', lang),
                    callback_data="admin_panel"
                )]
            ])
        )
    
    await safe_answer(callback)


@dp.callback_query(F.data == "reset_db_full")
@admin_only(answer_on_denied=False)
async def reset_db_full(callback: CallbackQuery):
    """ریست کامل دیتابیس + حذف کانفیگ‌های ربات (حفظ کانفیگ‌های شخصی)"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    text = t('b_warning_full_reset_databas_794aeef35e', lang)
    
    buttons = [
        [
            InlineKeyboardButton(
                text=t('yes_full_reset_6565be24a3', lang),
                callback_data="confirm_full_reset_keep_personal",
                style="danger"
            ),
            InlineKeyboardButton(
                text=t('cancel_4197bafba5', lang),
                callback_data="admin_panel"
            )
        ]
    ]
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)


@dp.callback_query(F.data == "confirm_full_reset_keep_personal")
@admin_only(answer_on_denied=False)
async def confirm_full_reset_keep_personal(callback: CallbackQuery):
    """اجرای ریست کامل با حفظ کانفیگ‌های شخصی"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    await callback.message.edit_text(
        t('i18n_full_reset_running', lang),
        reply_markup=None
    )

    try:
        await callback.message.edit_text(t('i18n_taking_backup', lang))
        backup_database()
        await callback.message.edit_text(t('i18n_fetching_bot_configs', lang))
        
        deleted_clients = 0
        failed_clients = 0
        skipped_personal = 0
        client_list = []
        unique_emails = set()  # ✅ برای جلوگیری از تکراری
        
        if is_senai_panel_enabled():
            inbounds = await xui_get_inbounds()
            if inbounds:
                total_bot_clients = 0
                total_personal_clients = 0
                all_clients = []
                for inbound in inbounds:
                    settings = inbound.get('settings', {})
                    clients = settings.get('clients', [])
                    
                    for client in clients:
                        email = client.get('email', '')
                        if not email:
                            continue
                        all_clients.append({
                            'email': email,
                            'inbound_id': inbound.get('id'),
                            'inbound_remark': inbound.get('remark', ''),
                            'enable': client.get('enable', True)
                        })
                clients_by_email = {}
                for client in all_clients:
                    email = client['email']
                    if email not in clients_by_email:
                        clients_by_email[email] = {
                            'email': email,
                            'inbounds': [],
                            'enable': client['enable']
                        }
                    clients_by_email[email]['inbounds'].append({
                        'inbound_id': client['inbound_id'],
                        'inbound_remark': client['inbound_remark']
                    })
                
                logger.info(f"📊 Total number of unique clients: {len(clients_by_email)}")
                for email, data in clients_by_email.items():
                    is_bot_client = False
                    if email.startswith('test_') or re.match(r'^t\d+_\d+', email):
                        is_bot_client = True
                    elif (email.startswith('user') and re.search(r'user(\d+)', email)) or re.match(r'^u\d+_\d+', email):
                        is_bot_client = True
                    
                    if is_bot_client:
                        total_bot_clients += 1
                        client_list.append(email)
                        unique_emails.add(email)
                        logger.info(f"🤖 Bot client: {email} - {len(data['inbounds'])} inbound")
                    else:
                        total_personal_clients += 1
                        skipped_personal += 1
                        logger.info(f"⏭️ Personal client preserved: {email} - {len(data['inbounds'])} inbound")
                
                await callback.message.edit_text(
                    t('i18n_reset_panel_clients_progress', lang, fa_parts=lambda: (total_bot_clients, total_personal_clients, len(clients_by_email)), en_parts=lambda: (total_bot_clients, total_personal_clients, len(clients_by_email)))
                )
                for i, email in enumerate(client_list):
                    try:
                        success = await xui_delete_client(email)
                        if success:
                            deleted_clients += 1
                            logger.info(f"🗑 Bot client deleted: {email}")
                        else:
                            failed_clients += 1
                            logger.error(f"❌ Error deleting client: {email}")
                    except Exception as e:
                        failed_clients += 1
                        logger.error(f"❌ Error deleting client {email}: {e}")
                    
                    if (i + 1) % 5 == 0:
                        await callback.message.edit_text(
                            t('i18n_reset_config_progress', lang, fa_parts=lambda: (i+1, len(client_list)), en_parts=lambda: (i+1, len(client_list)))
                        )
                    
                    await asyncio.sleep(0.3)
                
                logger.info(f"✅ {deleted_clients} bot client deleted from panel")
                logger.info(f"⏭️ {skipped_personal} personal client preserved")
                logger.info(f"❌ {failed_clients} bot client was not deleted")
                logger.info(f"📊 Total unique clients: {len(clients_by_email)}")
            else:
                logger.info('📭 No inbounds found in the panel')
        else:
            logger.info('📴 Panel is inactive - configurations were not deleted')
        await callback.message.edit_text(t('i18n_clearing_database', lang))
        reset_database_collections()
        COUPONS.clear()
        save_coupons(COUPONS)
        USER_INBOUND_SELECTION.clear()
        USER_TEST_USAGE.clear()
        user_states.clear()
        save_json(DB_FILES['user_states'], {})
        try:
            usage_store.clear_all_data()
        except Exception as e_du:
            logger.warning(f"⚠️ Error clearing daily_usage during full reset: {e_du}")
        try:
            sms_payment_manager.db.clear_all_data()
        except Exception as e_sms:
            logger.warning(f"⚠️ Error clearing sms_payments during full reset: {e_sms}")
        try:
            if 'alert_system' in globals() and alert_system:
                alert_system.clear_all_history()
            else:
                save_json(os.path.join(DATA_DIR, 'alert_cache.json'), {})
        except Exception as e_ac:
            logger.warning(f"⚠️ Error clearing alert_cache during full reset: {e_ac}")
        _db_cache.clear()
        _db_modified.clear()
        await callback.message.edit_text(t('i18n_saving_database', lang))
        save_all()
        
        logger.info("✅ Database reset")
        logger.info(f"   - {deleted_clients} bot config deleted from the panel")
        logger.info(f"   - {skipped_personal} personal config preserved")
        logger.info(f"   - {failed_clients} bot config was not deleted")
        text = t('b_full_reset_completed_b_b_r_98e8371ead', lang, fa_parts=lambda: (f'{deleted_clients}', f'{skipped_personal}', f'{failed_clients}'), en_parts=lambda: (f'{deleted_clients}', f'{skipped_personal}', f'{failed_clients}'))
        
        buttons = [
            [InlineKeyboardButton(
                text=t('view_backups_80e0984146', lang),
                callback_data="admin_restore_backup"
            )],
            [InlineKeyboardButton(
                text=t('emergency_backup_from_panel_f37a897b08', lang),
                callback_data="admin_emergency_backup",
                style="primary"
            )],
            [InlineKeyboardButton(
                text=t('back_to_panel_e933ddbad1', lang),
                callback_data="admin_panel"
            )]
        ]
        
        await callback.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        
        logger.warning(f"🚨 Full reset (personal configs preserved) by admin {callback.from_user.id} completed")
        
    except Exception as e:
        logger.error(f"❌ Error during full reset: {e}", exc_info=True)
        err_str = str(e)
        text = t('error_in_full_reset_d20b8a4f30', lang, fa_parts=lambda: (err_str,), en_parts=lambda: (err_str,))
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_14968ad63f', lang),
                    callback_data="admin_panel"
                )]
            ])
        )
    
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("admin_delete_user_"))
@admin_only
async def admin_delete_user_confirm(callback: CallbackQuery):
    """تایید حذف کاربر"""
    
    target_id = int(callback.data.split("_")[3])
    target = get_user(target_id)
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    target_name_raw = target.get('name', f'کاربر_{target_id}')
    target_name_escaped = html.escape(target_name_raw)
    
    if log_system:
        await log_system.log_user_deleted(callback.from_user.id, target_id, target_name_escaped)
    
    text = t('b_delete_user_b_id_balance_t_e23b6c127a', lang, fa_parts=lambda: (f'{target_name_escaped}', f'{target_id}', f"{target.get('balance', 0):,}"), en_parts=lambda: (f'{target_name_escaped}', f'{target_id}', f"{target.get('balance', 0):,}"))
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t('delete_all_configs_b70f4566ab', lang),
                    callback_data=f"confirm_delete_user_{target_id}",
                    style="danger"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t('delete_user_only_27ab660a39', lang),
                    callback_data=f"confirm_delete_user_keep_config_{target_id}",
                    style="primary"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t('cancel_4197bafba5', lang),
                    callback_data=f"admin_user_{target_id}"
                )
            ]
        ]),
        parse_mode=ParseMode.HTML
    )
    await safe_answer(callback)
    
@dp.callback_query(F.data.startswith("confirm_delete_user_keep_config_"))
@admin_only
async def confirm_delete_user_keep_config(callback: CallbackQuery):
    """اجرای حذف کاربر بدون حذف کانفیگ از پنل"""
    
    # روش صحیح: جدا کردن از آخر
    target_id = int(callback.data.rsplit("_", 1)[1])
    target = get_user(target_id)
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    target_name_raw = target.get('name', f'کاربر_{target_id}')
    target_name_escaped = html.escape(target_name_raw)
    
    await callback.message.edit_text("⏳ در حال حذف کاربر...")
    
    # حذف فقط از دیتابیس بدون حذف کانفیگ
    uid = str(target_id)
    if uid in users:
        del users[uid]
    for oid in list(orders.keys()):
        if isinstance(orders[oid], dict) and orders[oid].get('user_id') == target_id:
            del orders[oid]
    for key in list(referrals.keys()):
        if referrals[key].get('referrer') == target_id or referrals[key].get('referred') == target_id:
            del referrals[key]
    for cid in list(chats.keys()):
        if chats[cid].get('user_id') == target_id:
            del chats[cid]
    
    save_all()
    
    text = t('user_id_deleted_a53d0b8375', lang, fa_parts=lambda: (f'{target_name_escaped}', f'{target_id}'), en_parts=lambda: (f'{target_name_escaped}', f'{target_id}'))
    text += t('user_configs_kept_in_panel_a498a215ee', lang)
    text += t('database_updated_277446c8c5', lang)
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('back_to_list_ad4c935aca', lang), callback_data="admin_users")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer(t('deleted_e95d4ae5cb', lang), show_alert=True)
    
  
@dp.callback_query(F.data.startswith("confirm_delete_user_"))
@admin_only
async def confirm_delete_user(callback: CallbackQuery):
    """اجرای حذف کاربر"""
    
    target_id = int(callback.data.split("_")[3])
    target = get_user(target_id)
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    target_name_raw = target.get('name', f'کاربر_{target_id}')
    target_name_escaped = html.escape(target_name_raw)
    
    await callback.message.edit_text("⏳ در حال حذف کاربر...")
    
    deleted_configs = 0
    if is_senai_panel_enabled():
        valid_orders = get_valid_orders()
        user_orders = [o for o in valid_orders.values() 
                      if o.get('user_id') == target_id 
                      and o.get('status') == 'approved' 
                      and o.get('config_link')]
        
        for o in user_orders:
            email = extract_email_from_sub_link(o.get('config_link', ''))
            if email:
                success = await xui_delete_client(email)
                if success:
                    deleted_configs += 1
                    logger.info(f"🗑 Config {email} deleted from the panel")
    uid = str(target_id)
    if uid in users:
        del users[uid]
    for oid in list(orders.keys()):
        if isinstance(orders[oid], dict) and orders[oid].get('user_id') == target_id:
            del orders[oid]
    for key in list(referrals.keys()):
        if referrals[key].get('referrer') == target_id or referrals[key].get('referred') == target_id:
            del referrals[key]
    for cid in list(chats.keys()):
        if chats[cid].get('user_id') == target_id:
            del chats[cid]
    
    save_all()
    
    text = t('user_id_deleted_a53d0b8375', lang, fa_parts=lambda: (f'{target_name_escaped}', f'{target_id}'), en_parts=lambda: (f'{target_name_escaped}', f'{target_id}'))
    if deleted_configs > 0:
        text += t('configs_deleted_from_panel_e8a3ce1a6b', lang, fa_parts=lambda: (f'{deleted_configs}',), en_parts=lambda: (f'{deleted_configs}',))
    text += t('database_updated_277446c8c5', lang)
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('back_to_list_ad4c935aca', lang), callback_data="admin_users")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer(t('deleted_e95d4ae5cb', lang), show_alert=True)
   
@dp.callback_query(F.data == "backup_db")
@admin_only(answer_on_denied=False)
async def backup_db_cmd(callback: CallbackQuery):
    """بکاپ دستی"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    backup_database()
    
    await callback.answer(t('backup_saved_successfully_dce5990ab9', lang), show_alert=True)
        
# [Phase 1.4] get_panel_status moved to services.panel_api

@dp.callback_query(F.data == "admin_panel_status")
@admin_only(answer_on_denied=False)
async def admin_panel_status(callback: CallbackQuery):
    """نمایش وضعیت سرور"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    if not is_senai_panel_enabled():
        await callback.answer(t('i18n_admin_panel_disconnected', lang), show_alert=True)
        return
    
    await callback.answer(t('i18n_fetching', lang))
    
    status = await get_panel_status()
    
    if status:
        cpu = status.get('cpu', 0)
        mem = status.get('mem', {})
        disk = status.get('disk', {})
        net = status.get('net', {})
        uptime = status.get('uptime', 0)
        
        net_up = status.get('net_up', 0)
        net_down = status.get('net_down', 0)
        mem_total_gb = mem.get('total', 0) / (1024**3)
        mem_current_gb = mem.get('current', 0) / (1024**3)
        mem_percent = mem.get('percent', 0)
        if mem_percent == 0 and mem_total_gb > 0 and mem_current_gb > 0:
            mem_percent = (mem_current_gb / mem_total_gb) * 100
        disk_total_gb = disk.get('total', 0) / (1024**3)
        disk_current_gb = disk.get('current', 0) / (1024**3)
        disk_percent = disk.get('percent', 0)
        
        if disk_percent == 0 and disk_total_gb > 0 and disk_current_gb > 0:
            disk_percent = (disk_current_gb / disk_total_gb) * 100
        
        text = t('b_server_status_b_cpu_ram_gb_ea645f5326', lang, fa_parts=lambda: (f"{premium_emoji('cpu', '💻')}", f'{cpu:.1f}', f"{premium_emoji('ram', '🧠')}", f'{mem_current_gb:.2f}', f'{mem_total_gb:.2f}', f'{mem_percent:.1f}', f"{premium_emoji('disk', '💾')}", f'{disk_current_gb:.2f}', f'{disk_total_gb:.2f}', f'{disk_percent:.1f}', f"{premium_emoji('globe', '🌐')}", f"{premium_emoji('net_up', '⬆️')}", f'{net_up / 1024:.1f}', f"{premium_emoji('net_down', '⬇️')}", f'{net_down / 1024:.1f}', f"{premium_emoji('timer', '⏱')}", f'{uptime // 3600}', f'{uptime % 3600 // 60}'), en_parts=lambda: (f"{premium_emoji('cpu', '💻')}", f'{cpu:.1f}', f"{premium_emoji('ram', '🧠')}", f'{mem_current_gb:.2f}', f'{mem_total_gb:.2f}', f'{mem_percent:.1f}', f"{premium_emoji('disk', '💾')}", f'{disk_current_gb:.2f}', f'{disk_total_gb:.2f}', f'{disk_percent:.1f}', f"{premium_emoji('globe', '🌐')}", f"{premium_emoji('net_up', '⬆️')}", f'{net_up / 1024:.1f}', f"{premium_emoji('net_down', '⬇️')}", f'{net_down / 1024:.1f}', f"{premium_emoji('timer', '⏱')}", f'{uptime // 3600}', f'{uptime % 3600 // 60}'))
    else:
        text = t('i18n_admin_server_status_error', lang)
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t('refresh_cda5094083', lang), callback_data="admin_panel_status")],
        [InlineKeyboardButton(text=f"🔙 {t('back_d35a19b459', lang)}", callback_data="admin_panel")]
    ]))
    await safe_answer(callback)
       
@dp.callback_query(F.data == "admin_ping_test")
@admin_only(answer_on_denied=False)
async def admin_ping_test(callback: CallbackQuery):
    """تست پینگ - HTTP version"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    await callback.message.edit_text(t('i18n_admin_ping_testing', lang))
    
    results = {}
    if is_senai_panel_enabled():
        try:
            import time
            start = time.time()
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(SENAI_PANEL_URL, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    elapsed = (time.time() - start) * 1000
                    logger.info(f"🔍 Panel HTTP: {resp.status} in {elapsed:.0f}ms")
                    results['🟢 پنل'] = f'{elapsed:.0f}ms'
        except Exception:
            results['🔴 پنل'] = 'Timeout'
    http_targets = [
        ('Google', 'https://www.google.com'),
        ('Cloudflare', 'https://www.cloudflare.com'),
        ('Telegram', 'https://telegram.org'),
    ]
    
    for name, url in http_targets:
        try:
            start = time.time()
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=True) as resp:
                    elapsed = (time.time() - start) * 1000
                    logger.info(f"🔍 HTTP {name}: {resp.status} in {elapsed:.0f}ms")
                    results[f'🟢 {name}'] = f'{elapsed:.0f}ms'
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ {name} HTTP timeout")
            results[f'🔴 {name}'] = 'Timeout'
        except Exception as e:
            logger.error(f"❌ {name} HTTP error: {e}")
            try:
                ip = {'Google': '8.8.8.8', 'Cloudflare': '1.1.1.1', 'Telegram': '149.154.167.99'}.get(name, '8.8.8.8')
                start = time.time()
                reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, 443), timeout=3)
                elapsed = (time.time() - start) * 1000
                writer.close()
                await writer.wait_closed()
                results[f'🟡 {name} (TCP)'] = f'{elapsed:.0f}ms'
            except Exception:
                results[f'🔴 {name}'] = 'Failed'
    text = t('b_ping_test_http_b_code_code_681ce59f51', lang, fa_parts=lambda: (f"{now_tehran().strftime('%H:%M:%S')}",), en_parts=lambda: (f"{now_tehran().strftime('%H:%M:%S')}",))
    
    for name, result in results.items():
        text += f"{name}: <code>{result}</code>\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t('retry_ccc33a5d76', lang), callback_data="admin_ping_test")],
        [InlineKeyboardButton(text=t('back_14968ad63f', lang), callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await safe_answer(callback)
@dp.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await safe_answer(callback)

    
# [Phase 4] cmd_ai_status and init_ai moved to routers.admin_ai and services.ai_service

# [Phase 6] Background tasks & monitoring imported from services.background_tasks

from transaction_system import register_transaction_handlers
async def main():
    global log_system, panel_semaphore, panel_rate_limiter, shared_connector

    ensure_data_directory()
    await init_http_session()
    # بعد از بخش tasks و قبل از start polling
    
    load_all_data()
    register_search_handlers(
        dp=dp,
        admin_id_int=ADMIN_ID_INT,
        get_user_func=get_user,
        get_lang_func=lambda uid: get_user(uid).get("lang", "fa"),
    )
    logger.info("✅ Search handlers registered successfully")
    
    register_balance_handlers(dp, __import__('sys').modules[__name__])
    logger.info("✅ Balance handlers registered successfully")
    register_transaction_handlers(dp, __import__('sys').modules[__name__])
    logger.info("✅ Transaction handlers registered successfully")
    register_sms_payment_handlers(dp, __import__('sys').modules[__name__])
    logger.info("✅ SMS Payment handlers registered successfully")
    await init_ai()
    logger.info("=" * 60)
    logger.info('initializing bot...')
    logger.info('database loaded successfully')
    logger.info("=" * 60)
    logger.info('🔍 checking database files after loading:')
    for name, path in DB_FILES.items():
        if os.path.exists(path):
            size = os.path.getsize(path)
            logger.info(f"  ✅ {name}: {size:,} bytes - {os.path.abspath(path)}")
        else:
            logger.info(f"  ❌ {name}: does not exist!")
        logger.info("=" * 60)
    
    try:
        import sys
        sys.setrecursionlimit(10000)
        logger.info('Recursion limit increased to 10000')
        
        blacklist_count = load_blacklist()
        logger.info(f"Blacklist loaded: {blacklist_count} user")
        
        logger.info('Starting external logging system...')
        try:
            if LOG_BOT_TOKEN and LOG_CHANNEL_ID:
                from logger_system import init_logger
                log_system = await init_logger()
                if log_system:
                    set_log_system(log_system)
                    logger.info('✅ External logging system started')
                else:
                    logger.warning('⚠️ External logging system did not start - return value was None')
                    log_system = None
            else:
                logger.warning(f"⚠️ External logging system is not configured (LOG_BOT_TOKEN: {bool(LOG_BOT_TOKEN)}, LOG_CHANNEL_ID: {bool(LOG_CHANNEL_ID)})")
                log_system = None
        except ImportError as e:
            logger.warning(f"⚠️ logger_system module not found: {e}")
            log_system = None
        except Exception as e:
            logger.error(f"❌ Error starting logging system: {e}", exc_info=True)
            log_system = None
        
        logger.info('Fetching bot information from Telegram API...')
        bot_info = await bot.get_me()
        logger.info(f"Bot information received: {bot_info.first_name} (@{bot_info.username})")
        logger.info('🧪 Starting alert system...')
        await init_alert_system()
        if alert_system and log_system:
            alert_system.log_system = log_system
            logger.info('✅ Logging system connected to alert system')
        elif alert_system and not log_system:
            logger.warning('⚠️ Logging system is unavailable; warnings will not be logged')
        if log_system:
            try:
                await log_system.log_bot_start(bot_info, ADMIN_ID_INT)
                logger.info('Startup log recorded in external system')
            except Exception as e:
                logger.error(f"Error sending startup log to external system: {e}", exc_info=True)
        
        total_users = len(users)
        active_configs = get_available_configs_count()
        total_orders = len(get_valid_orders())
        states_count = len(user_states)
        db_size = get_database_size()
        db_total_mb = db_size.get('total', 0) / (1024 * 1024)
        
        logger.info(f"✅ Bot {bot_info.first_name} (@{bot_info.username}) started!")
        logger.info(f"👑 Admin: {ADMIN_ID_INT}")
        logger.info(f"📦 Configs available in the repository: {active_configs}")
        logger.info(f"👥 Number of users: {total_users}")
        logger.info(f"📋 Total orders: {total_orders}")
        logger.info(f"🧠 Active states: {states_count}")
        logger.info(f"💾 Database size: {db_total_mb:.1f} MB")
        logger.info("🔒 Security system is active")
        logger.info("=" * 60)
        logger.info('🚀 Bot is ready!')
        
        startup_message = f"""
🚀 <b>ربات راه‌اندازی شد!</b>

📊 <b>آمار اولیه:</b>
👥 کاربران: {total_users}
📦 کانفیگ موجود: {active_configs}
📋 سفارشات: {total_orders}
🧠 وضعیت‌های فعال: {states_count}
💾 حجم دیتابیس: {db_total_mb:.1f} MB
🕐 زمان: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}

⚙️ <b>تنظیمات پنل:</b>
🔄 درخواست‌های همزمان: 3
⏱ محدودیت نرخ: 30 درخواست در دقیقه

✅ ربات با موفقیت شروع به کار کرد.
"""
        try:
            await bot.send_message(ADMIN_ID_INT, startup_message, parse_mode=ParseMode.HTML)
            logger.info('Startup message sent to admin')
        except Exception as e:
            logger.warning(f"Failed to send startup message to admin: {e}")
        
        logger.info('Starting background tasks...')
        global _save_task
        _save_task = asyncio.create_task(_debounced_save_worker(), name="debounced_save_worker")

        tasks = [_save_task] + start_background_tasks(bot)
        
        logger.info('Starting migration of old data...')
        migrate_old_data()
        logger.info('Migration of old data completed')
        
        shared_connector = aiohttp.TCPConnector(
            ssl=False,
            limit=20,
            limit_per_host=10,
            ttl_dns_cache=300
        )
        logger.info('✅ shared connector created for aiohttp (limit=20, limit_per_host=10, ttl_dns_cache=300)')
        
        if sms_payment_manager.is_enabled():
            try:
                await sms_payment_manager.server.start(
                    host=sms_payment_manager.get_webhook_host(),
                    port=sms_payment_manager.get_webhook_port()
                )
            except Exception as e:
                logger.error(f"❌ Error starting SMS webhook server: {e}")

        logger.info('🚀 Starting polling...')
        logger.info("=" * 60)
        await dp.start_polling(bot, close_bot_session=False)
        
    except asyncio.CancelledError:
        logger.info('Main bot task was canceled')
        raise
    except Exception as e:
        error_msg = f"خطای بحرانی در راه‌اندازی: {e}"
        logger.critical(error_msg, exc_info=True)
        
        try:
            await bot.send_message(
                ADMIN_ID_INT,
                f"❌ <b>خطا در راه‌اندازی ربات!</b>\n\n{error_msg}\n\n"
                f"📝 <b>تریس کامل:</b>\n<code>{traceback.format_exc()[:1000]}</code>",
                parse_mode=ParseMode.HTML
            )
            logger.info('Critical error message sent to admin')
        except Exception as send_err:
            logger.error(f"Failed to send error message to admin: {send_err}")
        
        if log_system:
            try:
                await log_system.log_error(e, "main")
                logger.info('Critical error recorded in external logging system')
            except Exception as log_err:
                logger.error(f"Error recording error in external logging system: {log_err}")
        
        raise

# [Phase 6] cleanup_expired_states moved to services.background_tasks


async def shutdown(dispatcher: Dispatcher, bot: Bot):
    """خاموش کردن graceful ربات با بستن کامل اتصالات"""
    logger.info('🛑 stopping bot process...')
    
    shutdown_start = datetime.now()
    
    try:
        if _save_task and not _save_task.done():
            _save_task.cancel()
        logger.info('💾 Final database save...')
        save_all()
        logger.info('✅ Database saved successfully')
        
        logger.info('🧹 Cleaning up remaining states...')
        cleaned = cleanup_expired_states()
        if cleaned > 0:
            logger.info(f"🧹 {cleaned} expired status cleared")

        try:
            await sms_payment_manager.server.stop()
        except Exception as e:
            logger.warning(f"⚠️ Error stopping SMS web server: {e}")

        if log_system:
            try:
                await log_system.log_bot_stop(ADMIN_ID_INT)
                logger.info('✅ Shutdown log recorded in external system')
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"⚠️ Error closing logging system: {e}")
        
        try:
            uptime = datetime.now() - shutdown_start
            shutdown_msg = f"""
🛑 <b>ربات متوقف شد</b>

🕐 زمان توقف: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}
⏱ زمان اجرای فرآیند توقف: {uptime.total_seconds():.1f} ثانیه
📊 وضعیت نهایی: {len(users)} کاربر، {len(get_valid_orders())} سفارش
💾 بکاپ نهایی ذخیره شد
🔌 اتصالات در حال بسته‌شدن هستند
"""
            await bot.send_message(ADMIN_ID_INT, shutdown_msg, parse_mode=ParseMode.HTML)
            logger.info('✅ Shutdown message sent to admin')
        except Exception as e:
            logger.warning(f"⚠️ Failed to send shutdown message to admin: {e}")
        
        await asyncio.sleep(0.5)
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                current_task = asyncio.current_task(loop)
                pending = [
                    task for task in asyncio.all_tasks(loop)
                    if not task.done() and task is not current_task
                ]
                if pending:
                    for task in pending:
                        task.cancel()
                    logger.info(f"⏳ Waiting to cancel {len(pending)} remaining tasks...")
                    await asyncio.wait(pending, timeout=2.0)
        except Exception as e:
            logger.warning(f"⚠️ Error closing event loop: {e}")
        
    except Exception as e:
        logger.error(f"❌ Error during bot shutdown: {e}", exc_info=True)
        raise
    finally:
        logger.info('🔌 Closing remaining connections...')
        cleanup_errors = []

        async def close_resource(name, close):
            try:
                await close()
                logger.info(f"✅ {name} closed")
            except Exception as e:
                cleanup_errors.append(name)
                logger.warning(f"⚠️ Error closing {name}: {e}")

        await close_resource("HTTP session", close_http_session)

        if shared_connector:
            await close_resource("shared connector", shared_connector.close)
        if CONNECTOR:
            await close_resource("CONNECTOR", CONNECTOR.close)
        await close_resource("Bot session", bot.session.close)
        await close_resource("FSM storage", dispatcher.fsm.storage.close)
        if log_system:
            await close_resource("سیستم لاگ خارجی", log_system.close)
        if cleanup_errors:
            logger.error(f"Bot shutdown completed with errors while closing these resources: {', '.join(cleanup_errors)}")
        else:
            logger.info('✅ Bot stopped successfully')
        logger.info(f"⏱ Total shutdown time: {(datetime.now() - shutdown_start).total_seconds():.1f} seconds")

# [Phase 6] get_memory_usage moved to services.background_tasks

@dp.message(Command("stats"), IsAdmin())
async def cmd_stats(message: Message):
    """دستور نمایش آمار (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    logger.info(f"admin ({ADMIN_ID_INT}) requested statistics")
    
    total_users = len(users)
    total_orders = len(get_valid_orders())
    total_referrals = len(referrals)
    active_chats = len(get_active_chats())
    blacklist_count = len(BLACKLIST)
    available_configs = get_available_configs_count()
    db_size = get_database_size()
    db_total_mb = db_size.get('total', 0) / (1024 * 1024)
    states_count = len(user_states)
    cache_size = len(_db_cache)
    
    logger.debug(f"statistics collected: users={total_users}, orders={total_orders}, configs={available_configs}")
    
    stats_text = f"""
📊 <b>آمار ربات</b>

👥 کاربران: {total_users}
📝 سفارشات: {total_orders}
🎁 رفرال‌ها: {total_referrals}
💬 چت‌های فعال: {active_chats}
🚫 لیست سیاه: {blacklist_count}
📦 کانفیگ موجود: {available_configs}

💾 حجم دیتابیس: {db_total_mb:.1f} MB
🧠 وضعیت‌های کاربران: {states_count}
🗄 کش دیتابیس: {cache_size} آیتم

🕐 زمان: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    try:
        await message.reply(stats_text, parse_mode=ParseMode.HTML)
        logger.info('Stats response sent to admin')
    except Exception as e:
        logger.error(f"Error sending statistics to admin: {e}", exc_info=True)

from alert_system import AlertSystem

alert_system = None

alert_system_settings = {
    'enabled': True,
    'volume_thresholds': [10, 5],      
    'expiry_warnings': [7, 3, 1],  
    'test_volume_thresholds': [30],
    'test_expiry_warnings': [0.25],
    'cooldown_minutes': 120,
}


async def init_alert_system():
    """راه‌اندازی سیستم هشدار با بارگذاری تنظیمات"""
    global alert_system, alert_system_settings, log_system
    
    try:
        logger.info('🧪 Starting service alert system...')
        
        if 'alert_settings' in configs_pool and isinstance(configs_pool['alert_settings'], dict):
            saved_settings = configs_pool['alert_settings']
            alert_system_settings.update(saved_settings)
            logger.info(f"⚙️ Alert settings loaded from the database: {alert_system_settings}")
        else:
            logger.info('⚙️ Using default alert settings')
        
        cache_file = os.path.join(DATA_DIR, 'alert_cache.json')
        alert_system = AlertSystem(
            bot=bot,
            orders_getter=get_valid_orders,
            user_getter=get_user,
            extract_email_func=None,                          # دیگه استفاده نمی‌شه (نگه‌داری برای سازگاری)
            cache_file=cache_file,
            log_system=log_system,
            find_email_by_sub_id_func=find_email_by_sub_id,   # ✅ تابع جدید برای resolve subId → email
            update_order_func=update_order                     # ✅ تابع جدید برای ذخیره email در سفارش
        )
        alert_system.update_settings(alert_system_settings)
        asyncio.create_task(alert_system.run_alert_worker())
        
        logger.info('✅ Alert system started successfully')
        logger.info(f"📊 Volume thresholds: {alert_system.volume_thresholds}% + automatic expiration")
        logger.info(f"📅 Expiration thresholds: {alert_system.expiry_warnings} days + automatic expiration")
        logger.info(f"🔍 Resolve email: {'✅ enabled' if alert_system.find_email_by_sub_id else '❌ disabled'}")
        
        return alert_system
        
    except Exception as e:
        logger.error(f"❌ Error starting the alert system: {e}", exc_info=True)
        return None

@dp.message(Command("check_alerts"), IsAdmin())
async def cmd_check_alerts(message: Message):
    """بررسی دستی هشدارها (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    if not alert_system:
        await message.reply("❌ سیستم هشدار راه‌اندازی نشده است!")
        return
    
    await message.reply("⏳ در حال بررسی سرویس‌ها...")
    await alert_system.check_all_services()
    await message.reply("✅ بررسی هشدارها انجام شد!")

@dp.message(Command("clear_alert_cache"), IsAdmin())
async def cmd_clear_alert_cache(message: Message):
    """پاک کردن کش هشدارها (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    if not alert_system:
        await message.reply("❌ سیستم هشدار راه‌اندازی نشده است!")
        return
    
    parts = message.text.split()
    order_id = None
    if len(parts) > 1:
        try:
            order_id = int(parts[1])
        except Exception:
            pass
    
    alert_system.clear_cache(order_id)
    
    if order_id:
        await message.reply(f"✅ کش هشدارهای سفارش #{order_id} پاک شد!")
    else:
        await message.reply("✅ همه کش هشدارها پاک شد!")
        
        
if __name__ == "__main__":
    async def run():
        """تابع اجرای اصلی با مدیریت خطا"""
        logger.info("=" * 60)
        logger.info('Starting bot...')
        logger.info(f"Start time: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            await main()
        except KeyboardInterrupt:
            logger.info('🛑 Received shutdown signal from user (KeyboardInterrupt)')
        except asyncio.CancelledError:
            logger.info('Bot execution canceled (CancelledError)')
        except Exception as e:
            logger.critical(f"❌ Critical error in main execution: {e}", exc_info=True)
            raise
        finally:
            await shutdown(dp, bot)
    
    try:
        asyncio.run(run())
        logger.info('Bot shut down successfully')
    except KeyboardInterrupt:
        logger.info('Bot stopped by user (KeyboardInterrupt)')
    except Exception as e:
        logger.critical(f"Unexpected error at asyncio.run level: {e}", exc_info=True)
    finally:
        logger.info(f"Execution ended - {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}")

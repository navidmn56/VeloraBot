"""
routers/admin_ai.py
-------------------
مدیریت پنل هوش مصنوعی، تنظیمات دکمه AI، تست مدل‌ها، بررسی حافظه و لاگ‌های دیباگ
"""

import os
import json
import time
import asyncio
import logging
import html
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Union

import aiohttp
from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.filters import Command
from aiogram.enums import ParseMode

import config as app_config
from config import (
    ADMIN_ID,
    GEMINI_API_KEY,
    GEMINI_ENABLED,
    GEMINI_MODEL,
    GEMINI_MAX_TOKENS,
    GEMINI_DAILY_LIMIT,
    GEMINI_TEMPERATURE,
)
from database import users, configs_pool, save_all, now_tehran, now_tehran_iso
from user_manager import user_states, get_user, get_admin_id_int
from services.ai_service import (
    GeminiClient,
    conversation_memory,
    check_ai_limit,
    increment_ai_usage,
    reset_ai_limits,
    user_ai_requests,
    get_gemini_client,
    AI_FEATURE_ENABLED,
    get_ai_button_enabled,
    set_ai_button_enabled,
    gemini_error_message,
)
from strings import t
from utils.filters import IsAdmin
from utils.guards import admin_only
from utils.helpers import safe_answer

logger = logging.getLogger(__name__)

router = Router(name="admin_ai")

ADMIN_ID_INT = get_admin_id_int()

_bot: Optional[Bot] = None

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
        raise AttributeError(f"log_system has no attribute {name}")

log_system = _LogSystemProxy()


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


class _GeminiClientProxy:
    def __getattr__(self, name):
        c = get_gemini_client()
        if c is not None:
            return getattr(c, name)
        raise RuntimeError("Gemini client not initialized")

    def __bool__(self):
        return get_gemini_client() is not None


gemini_client = _GeminiClientProxy()


async def get_ai_response(*args, **kwargs):
    from routers.ai_assistant import get_ai_response as gar
    return await gar(*args, **kwargs)


@router.message(Command("memory"), IsAdmin())
async def cmd_memory(message: Message):
    """مشاهده و مدیریت حافظه مکالمه (فقط ادمین)"""
    
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    parts = message.text.split()
    
    if len(parts) == 1:
        stats = conversation_memory.get_stats()
        if conversation_memory.has_history(ADMIN_ID_INT):
            history = conversation_memory.get_history(ADMIN_ID_INT)
            history_text = "\n".join([
                f"{'👤' if msg['role']=='user' else '🤖'} {msg['content'][:50]}..."
                for msg in history[-5:]
            ])
        else:
            history_text = "هیچ تاریخی وجود ندارد"
        
        text = f"""
🧠 <b>وضعیت حافظه مکالمه</b>

📊 <b>آمار:</b>
• کاربران فعال: {stats['total_users']}
• کل پیام‌ها: {stats['total_messages']}
• کاربران آنلاین: {stats['active_users']}

📝 <b>تاریخچه شما (۵ پیام آخر):</b>
{history_text}

💡 <b>دستورات:</b>
• <code>/memory clear</code> - پاک کردن حافظه شما
• <code>/memory clear_all</code> - پاک کردن همه حافظه‌ها (فقط ادمین)
• <code>/memory user [ID]</code> - مشاهده تاریخچه یک کاربر
"""
        await message.reply(text, parse_mode=ParseMode.HTML)
    
    elif len(parts) >= 2 and parts[1] == "clear":
        conversation_memory.clear(message.from_user.id)
        await message.reply("🧹 حافظه مکالمه شما پاک شد!")
    
    elif len(parts) >= 2 and parts[1] == "clear_all":
        if message.from_user.id == ADMIN_ID_INT:
            conversation_memory.clear_all()
            await message.reply("🧹 همه حافظه‌ها پاک شدند!")
    
    elif len(parts) >= 2 and parts[1] == "user" and len(parts) >= 3:
        if message.from_user.id == ADMIN_ID_INT:
            try:
                target_id = int(parts[2])
                if conversation_memory.has_history(target_id):
                    history = conversation_memory.get_history(target_id)
                    text = f"🧠 <b>تاریخچه کاربر {target_id}</b>\n\n"
                    for msg in history[-10:]:
                        role = "👤 کاربر" if msg['role'] == 'user' else "🤖 دستیار"
                        text += f"{role}: {msg['content'][:100]}\n"
                    await message.reply(text, parse_mode=ParseMode.HTML)
                else:
                    await message.reply(f"❌ کاربر {target_id} هیچ تاریخی ندارد")
            except Exception:
                await message.reply("❌ آیدی نامعتبر")
                
@router.callback_query(F.data == "admin_ai_settings")
@admin_only
async def admin_ai_settings(callback: CallbackQuery):
    """تنظیمات هوش مصنوعی برای ادمین با نمایش خطاهای دقیق از configs_pool"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    ai_settings = configs_pool.get('ai_settings', {})
    ai_button_status = ai_settings.get('button_enabled', True)
    
    # ============================================
    # دریافت خطاهای ذخیره شده از configs_pool
    # ============================================
    ai_errors = configs_pool.get('ai_errors', {})
    gemini_error_message = ai_errors.get('gemini_error', '')
    last_check = ai_errors.get('last_check', '')
    
    # ============================================
    # بررسی وضعیت واقعی سرویس‌ها
    # ============================================
    gemini_status = t('i18n_status_inactive', lang)
    gemini_display_error = ""
    model_name = t('i18n_no_service_active', lang)
    daily_limit = 0

    # --- بررسی Gemini ---
    if GEMINI_ENABLED:
        if gemini_client:
            gemini_status = t('i18n_status_active', lang)
            model_name = GEMINI_MODEL
            daily_limit = GEMINI_DAILY_LIMIT
            gemini_display_error = ""
        else:
            gemini_status = t('i18n_status_error', lang)
            # استفاده از خطای ذخیره شده
            if gemini_error_message:
                gemini_display_error = gemini_error_message
            else:
                # خطاهای احتمالی (fallback)
                if GEMINI_API_KEY == "AIzaSyDxxxxxxxxxxxxxxxxxx" or not GEMINI_API_KEY:
                    gemini_display_error = t('i18n_error_api_key_not_set', lang)
                elif len(GEMINI_API_KEY) < 30:
                    gemini_display_error = t('i18n_error_api_key_invalid', lang)
                else:
                    gemini_display_error = t('i18n_error_google_api_unreachable', lang)

    # --- تعیین وضعیت کلی ---
    if gemini_client:
        overall_status = t('i18n_status_active', lang)
        service_name = "Google Gemini"
    else:
        overall_status = t('i18n_status_inactive', lang)
        service_name = t('i18n_no_service_active', lang)
        if gemini_error_message:
            overall_status = t('i18n_status_needs_review', lang)

    # --- آمار استفاده روزانه ---
    today = now_tehran().date().isoformat()
    daily_usage = sum(u['count'] for u in user_ai_requests.values() if u.get('date') == today)
    button_status = t('i18n_status_active', lang) if ai_button_status else t('i18n_status_inactive', lang)

    # ============================================
    # ساخت متن با خطاهای دقیق
    # ============================================
    gemini_error_display = f"\n  <code>{gemini_display_error}</code>" if gemini_display_error else ""

    # راه‌حل پیشنهادی بر اساس خطاها
    solution_text = ""
    if gemini_error_message and "Location" in gemini_error_message:
        solution_text = t('to_fix_location_error_setup_bfa24fc2a7', lang)
    elif gemini_error_message and t('api_key_bd36d76e96', lang) in gemini_error_message.lower():
        solution_text = t('get_api_key_from_https_aistu_f85fa65b77', lang)
    elif gemini_error_message:
        solution_text = t('check_your_api_key_at_https_18120e4a72', lang)

    text = t('b_ai_settings_b_service_stat_0901d54e00', lang, fa_parts=lambda: (f'{overall_status}', f'{service_name}', f'{daily_limit}', f'{button_status}', f'{gemini_status}', f'{gemini_error_display}', f'{daily_usage}', f"{(t('last_check_26ae94e71d', lang, fa_parts=lambda: (f'{last_check[:16]}',)) if last_check else '')}", f'{solution_text}'), en_parts=lambda: (f'{overall_status}', f'{service_name}', f'{daily_limit}', f'{button_status}', f'{gemini_status}', f'{gemini_error_display}', f'{daily_usage}', f"{(t('last_check_26ae94e71d', lang, en_parts=lambda: (f'{last_check[:16]}',)) if last_check else '')}", f'{solution_text}'))
    
    # ============================================
    # دکمه‌ها
    # ============================================
    buttons = [
        [InlineKeyboardButton(
            text=t('i18n_ai_toggle_button', lang, fa_parts=lambda: ('غیرفعال کردن' if ai_button_status else 'فعال کردن',), en_parts=lambda: (t('i18n_ai_disable_action' if ai_button_status else 'i18n_ai_enable_action', lang),)),
            callback_data="admin_toggle_ai_button"
        )],
        [InlineKeyboardButton(
            text=t('i18n_ai_retest_connection', lang),
            callback_data="admin_ai_test"
        )],
        [InlineKeyboardButton(
            text=t('i18n_ai_reset_user_limits', lang),
            callback_data="admin_ai_reset_limits"
        )],
        [InlineKeyboardButton(
            text=t('back_14968ad63f', lang),
            callback_data="admin_panel"
        )]
    ]
    
    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" not in str(e):
            await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)
    
    await safe_answer(callback)
        
@router.callback_query(F.data == "admin_toggle_ai_button")
@admin_only
async def admin_toggle_ai_button(callback: CallbackQuery):
    """فعال/غیرفعال کردن دکمه AI برای کاربران"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    new_state = not get_ai_button_enabled()
    set_ai_button_enabled(new_state)
    if 'ai_settings' not in configs_pool:
        configs_pool['ai_settings'] = {}
    configs_pool['ai_settings']['button_enabled'] = new_state
    configs_pool['ai_settings']['last_updated'] = now_tehran_iso()
    save_all()  # ذخیره در دیتابیس
    
    status_text = "فعال" if new_state else "غیرفعال"
    if log_system:
        await log_system.log_admin_action(
            callback.from_user.id,
            "Updated AI button status",
            details=f"AI button is now {status_text}"
        )
    
    await callback.answer(t('i18n_ai_toggle_status_changed', lang, fa_parts=lambda: (status_text,), en_parts=lambda: (t('i18n_ai_enabled_status' if new_state else 'i18n_ai_disabled_status', lang),)), show_alert=True)
    await admin_ai_settings(callback)

@router.callback_query(F.data == "admin_ai_test")
@admin_only
async def admin_ai_test(callback: CallbackQuery):
    """تست کامل اتصال به همه سرویس‌های هوش مصنوعی با نمایش خطاهای دقیق"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    
    await callback.answer(t('i18n_testing_now', lang))
    await callback.message.edit_text(t('i18n_testing_ai_services', lang))
    
    # ============================================
    # تست Gemini
    # ============================================
    gemini_test_result = "❌ غیرفعال"
    gemini_test_detail = ""
    
    if GEMINI_ENABLED:
        if gemini_client:
            try:
                # ✅ تست مناسب برای دستیار فروش
                test_response = await gemini_client.chat(
                    "سلام! لطفاً در یک جمله کوتاه خودت را معرفی کن.", 
                    retry=1
                )
                
                # ✅ بررسی: خالی نباشه، خطا نداشته باشه، حداقل ۵ کاراکتر داشته باشه
                is_error = bool(test_response) and any(
                    marker in test_response 
                    for marker in ["❌", "⏰", "خطای", "Error:", "خطا در"]
                )
                
                if test_response and len(test_response.strip()) >= 5 and not is_error:
                    gemini_test_result = t('i18n_status_active', lang)
                    gemini_test_detail = t('i18n_response_received', lang, fa_parts=lambda: (f'{len(test_response)}', f'{test_response[:80]}'), en_parts=lambda: (f'{len(test_response)}', f'{test_response[:80]}'))
                else:
                    gemini_test_result = t('i18n_status_partial', lang)
                    gemini_test_detail = t('i18n_response_partial', lang, fa_parts=lambda: ((f'{test_response[:80]}' if test_response else t('i18n_no_response_received', lang)),), en_parts=lambda: ((f'{test_response[:80]}' if test_response else t('i18n_no_response_received', lang)),))
            except Exception as e:
                err_str = str(e)[:80]
                gemini_test_result = t('i18n_status_error', lang)
                gemini_test_detail = t('i18n_error_detail', lang, fa_parts=lambda: (err_str,), en_parts=lambda: (err_str,))
        else:
            gemini_test_result = t('i18n_status_error', lang)
            ai_errors = configs_pool.get('ai_errors', {})
            gemini_error_msg = ai_errors.get('gemini_error', '')
            if gemini_error_msg:
                gemini_test_detail = gemini_error_msg
            elif GEMINI_API_KEY == "AIzaSyDxxxxxxxxxxxxxxxxxx" or not GEMINI_API_KEY:
                gemini_test_detail = t('i18n_error_api_key_not_set', lang)
            elif len(GEMINI_API_KEY) < 30:
                gemini_test_detail = t('i18n_error_api_key_invalid', lang)
            else:
                gemini_test_detail = t('i18n_error_google_api_unreachable', lang)
    else:
        gemini_test_detail = t('i18n_ai_disabled_in_config', lang)
    
    
    # ============================================
    # تست واقعی ارسال پیام (در صورت فعال بودن)
    # ============================================
    # تست واقعی ارسال پیام (در صورت فعال بودن)
    real_test_result = ""
    if gemini_client:
        try:
            test_msg = await gemini_client.chat("سلام! چطوری؟ یک جواب کوتاه بده.", retry=1)
            if test_msg and len(test_msg.strip()) >= 5:
                real_test_result = "\n\n" + t('i18n_send_test_success', lang, fa_parts=lambda: (f'{len(test_msg)}',), en_parts=lambda: (f'{len(test_msg)}',))
            else:
                real_test_result = "\n\n" + t('i18n_send_test_short', lang)
        except Exception as e:
            err_str = str(e)[:80]
            real_test_result = "\n\n" + t('i18n_send_test_error', lang, fa_parts=lambda: (err_str,), en_parts=lambda: (err_str,))
    else:
        real_test_result = "\n\n" + t('i18n_send_test_no_service', lang)
    # ============================================
    # جمع‌بندی نهایی
    # ============================================
    text = t('b_ai_test_results_b_time_b_g_a2f55011c6', lang, fa_parts=lambda: (f"{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}", f'{gemini_test_result}', f"{(f'📝 {gemini_test_detail}' if gemini_test_detail else '')}", f'{real_test_result}', f"{(f'💡 <b>راه\u200cحل پیشنهادی:</b> کلید API Gemini را بررسی کنید.' if '❌' in gemini_test_result else '⚠️ <b>هشدار:</b> پاسخ کامل نیست — GEMINI_MAX_TOKENS را افزایش دهید.' if '⚠️' in gemini_test_result else '✅ سرویس Gemini به درستی کار می\u200cکند.')}"), en_parts=lambda: (f"{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}", f'{gemini_test_result}', f"{(f'📝 {gemini_test_detail}' if gemini_test_detail else '')}", f'{real_test_result}', f"{(f'💡 <b>Solution:</b> Check your Gemini API key.' if '❌' in gemini_test_result else '⚠️ <b>Warning:</b> Response is incomplete — increase GEMINI_MAX_TOKENS.' if '⚠️' in gemini_test_result else '✅ All services are working properly.')}"))
    
    buttons = [
        [InlineKeyboardButton(
            text=t('retest_d4ef8a8e93', lang),
            callback_data="admin_ai_test"
        )],
        [InlineKeyboardButton(
            text=t('back_to_ai_settings_a81d62e57d', lang),
            callback_data="admin_ai_settings"
        )]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    
    await safe_answer(callback)


@router.callback_query(F.data == "admin_ai_reset_limits")
@admin_only
async def admin_ai_reset_limits(callback: CallbackQuery):
    """ریست محدودیت تمام کاربران"""
    
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    today = now_tehran().date().isoformat()
    before_count = sum(u['count'] for u in user_ai_requests.values() if u.get('date') == today)
    before_users = len([u for u in user_ai_requests.values() if u.get('date') == today])
    reset_ai_limits()
    configs_pool['user_ai_requests'] = user_ai_requests
    save_all()
    logger.info(f"🔄 AI limits reset by admin {callback.from_user.id} reset")
    logger.info(f"   user count before: {before_users} | question count: {before_count}")
    
    if log_system:
        await log_system.log_admin_action(
            callback.from_user.id,
            "Reset AI limits",
            details=f"Users: {before_users} | Questions: {before_count}"
        )
    text = t('b_ai_limits_reset_successful_b7fd070893', lang, fa_parts=lambda: (f'{before_users}', f'{before_count}'), en_parts=lambda: (f'{before_users}', f'{before_count}'))
    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_to_ai_settings_a81d62e57d', lang),
                    callback_data="admin_ai_settings"
                )]
            ]),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.debug(f"Failed to edit AI test message, sending new: {e}")
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=t('back_to_ai_settings_a81d62e57d', lang),
                    callback_data="admin_ai_settings"
                )]
            ]),
            parse_mode=ParseMode.HTML
        )
    
    await safe_answer(callback)
    
    
    


@router.message(Command("test_full"), IsAdmin())
async def cmd_test_full(message: Message):
    """تست پاسخ کامل (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    await message.reply("⏳ در حال تست پاسخ کامل...")
    
    test_question = "لطفاً یک توضیح کامل درباره کانفیگ‌ها بده. شامل: قیمت‌ها، انواع، مزایا، معایب و نحوه خرید. حداقل ۵ پاراگراف."
    
    answer = await get_ai_response(test_question, message.from_user.id)
    words = len(answer.split())
    paragraphs = len([p for p in answer.split('\n') if p.strip()])
    
    response = f"""
🧪 <b>تست پاسخ کامل</b>

📊 <b>آمار:</b>
• تعداد کلمات: {words}
• تعداد پاراگراف: {paragraphs}
• طول کل: {len(answer)} کاراکتر

━━━━━━━━━━━━━━━━━━━━━━
🤖 <b>پاسخ:</b>

{answer}
"""
    await message.reply(response, parse_mode=ParseMode.HTML)

@router.message(Command("reset_ai_limit"), IsAdmin())
async def cmd_reset_ai_limit(message: Message):
    """ریست محدودیت AI یک کاربر خاص (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply(
            "📊 <b>ریست محدودیت AI</b>\n\n"
            "استفاده:\n"
            "<code>/reset_ai_limit 123456789</code>\n\n"
            "برای ریست محدودیت خودت:\n"
            "<code>/reset_ai_limit me</code>",
            parse_mode=ParseMode.HTML
        )
        return
    
    target = parts[1]
    if target == "me":
        target_id = message.from_user.id
    else:
        try:
            target_id = int(target)
        except Exception:
            await message.reply("❌ آیدی نامعتبر")
            return
    
    if target_id in user_ai_requests:
        del user_ai_requests[target_id]
        await message.reply(f"✅ محدودیت AI کاربر {target_id} ریست شد!")
    else:
        await message.reply(f"ℹ️ کاربر {target_id} هیچ سوالی نپرسیده بود.")
        
        


@router.message(Command("ai_debug"), IsAdmin())
async def cmd_ai_debug(message: Message):
    """بررسی تنظیمات AI (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    text = f"""
🤖 <b>دیباگ AI</b>

━━━━━━━━━━━━━━━━━━━━━━
📡 <b>Gemini:</b>
  • فعال: {GEMINI_ENABLED}
  • مدل: {GEMINI_MODEL}
  • Max Tokens: {GEMINI_MAX_TOKENS}
  • Temperature: {GEMINI_TEMPERATURE}
  • Daily Limit: {GEMINI_DAILY_LIMIT}
  • System Prompt: {len(app_config.GEMINI_SYSTEM_PROMPT)} کاراکتر

📊 <b>وضعیت اتصال:</b>
  • Client: {'🟢 متصل' if gemini_client else '🔴 غیرفعال'}
  • خطا: {gemini_error_message if gemini_error_message else '✅ ندارد'}

💡 <b>توصیه:</b>
  • اگر پاسخ‌ها ناقص است، GEMINI_MAX_TOKENS را افزایش دهید
  • مقدار پیشنهادی: 800 تا 1500
  • مقدار فعلی: {GEMINI_MAX_TOKENS}
"""
    await message.reply(text, parse_mode=ParseMode.HTML)
       
@router.message(Command("testai"), IsAdmin())
async def cmd_test_ai(message: Message):
    """تست مستقیم هوش مصنوعی (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    await message.reply("⏳ در حال تست هوش مصنوعی...")
    test_message = "سلام، یک تست ساده است. لطفاً پاسخ بده."
    
    try:
        answer = await get_ai_response(test_message, message.from_user.id, message.from_user.username)
        await message.reply(f"✅ پاسخ تست:\n\n{answer}")
    except Exception as e:
        logger.error(f"Error in test AI: {e}", exc_info=True)
        await message.reply(f"❌ خطا در تست: {html.escape(type(e).__name__)}")





@router.message(Command("aistatus"), IsAdmin())
async def cmd_ai_status(message: Message):
    """چک کردن وضعیت AI (فقط ادمین)"""
    if not getattr(message, "from_user", None) or message.from_user.id != ADMIN_ID_INT:
        return
    
    status_text = f"""
🤖 <b>وضعیت هوش مصنوعی</b>

━━━━━━━━━━━━━━━━━━━━━━
📡 Gemini Client: {'✅ فعال' if gemini_client else '❌ غیرفعال'}
🔘 دکمه AI در منو: {'🟢 نمایش داده می‌شود' if get_ai_button_enabled() else '🔴 نمایش داده نمی‌شود'}
━━━━━━━━━━━━━━━━━━━━━━

💡 برای فعال/غیرفعال کردن دکمه:
   از پنل ادمین → AI Settings → دکمه Toggle استفاده کنید
"""
    await message.reply(status_text, parse_mode=ParseMode.HTML)
    

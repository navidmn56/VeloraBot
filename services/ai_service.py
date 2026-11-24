"""
services/ai_service.py
----------------------
سرویس هوش مصنوعی گوگل جیمینای (Gemini)، حافظه مکالمه کاربران و مدیریت محدودیت‌های استفاده
"""

import os
import json
import time
import hashlib
import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Union

import aiohttp

from config import (
    GEMINI_API_KEY,
    GEMINI_ENABLED,
    GEMINI_MODEL,
    GEMINI_TEMPERATURE,
    GEMINI_MAX_TOKENS,
    GEMINI_DAILY_LIMIT,
)
from db_storage import DATA_DIR, DB_FILES, save_json
from database import users, configs_pool, save_all, now_tehran, now_tehran_iso
from user_manager import get_user

logger = logging.getLogger(__name__)

gemini_client = None
gemini_error_message = None
AI_FEATURE_ENABLED = True
user_ai_requests: Dict[Any, Any] = {}

GEMINI_PROMPT_CACHE = {
    "fingerprint": None,
    "name": None,
    "expires_at": 0.0,
    "retry_after": 0.0,
    "disabled": False,
}
GEMINI_PROMPT_CACHE_LOCK = asyncio.Lock()


def get_gemini_client():
    global gemini_client
    return gemini_client


def set_gemini_client(client):
    global gemini_client
    gemini_client = client


def get_ai_button_enabled() -> bool:
    global AI_FEATURE_ENABLED
    return AI_FEATURE_ENABLED


def set_ai_button_enabled(enabled: bool):
    global AI_FEATURE_ENABLED
    AI_FEATURE_ENABLED = bool(enabled)
    import sys
    for mod_name in ("main", "routers.admin_ai", "routers.ai_assistant", "routers.ai_purchase_advisor"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "AI_FEATURE_ENABLED"):
            setattr(mod, "AI_FEATURE_ENABLED", AI_FEATURE_ENABLED)


async def get_gemini_prompt_cache(session: aiohttp.ClientSession, system_prompt: str) -> Optional[str]:
    """Create and reuse Gemini's server-side cache for the stable system prompt."""
    fingerprint = hashlib.sha256(
        f"{GEMINI_MODEL}\0{system_prompt}".encode("utf-8")
    ).hexdigest()
    now = time.monotonic()
    if GEMINI_PROMPT_CACHE["fingerprint"] == fingerprint:
        if GEMINI_PROMPT_CACHE["name"] and GEMINI_PROMPT_CACHE["expires_at"] > now:
            return GEMINI_PROMPT_CACHE["name"]
        if GEMINI_PROMPT_CACHE["disabled"] or GEMINI_PROMPT_CACHE["retry_after"] > now:
            return None

    async with GEMINI_PROMPT_CACHE_LOCK:
        now = time.monotonic()
        if GEMINI_PROMPT_CACHE["fingerprint"] == fingerprint:
            if GEMINI_PROMPT_CACHE["name"] and GEMINI_PROMPT_CACHE["expires_at"] > now:
                return GEMINI_PROMPT_CACHE["name"]
            if GEMINI_PROMPT_CACHE["disabled"] or GEMINI_PROMPT_CACHE["retry_after"] > now:
                return None

        cache_url = (
            "https://generativelanguage.googleapis.com/v1beta/cachedContents"
            f"?key={GEMINI_API_KEY}"
        )
        try:
            async with session.post(
                cache_url,
                json={
                    "model": f"models/{GEMINI_MODEL}",
                    "displayName": "velorabot-system-prompt",
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "ttl": "3600s",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if 200 <= response.status < 300:
                    cache_data = await response.json()
                    cache_name = cache_data.get("name") if isinstance(cache_data, dict) else None
                    if cache_name:
                        GEMINI_PROMPT_CACHE.update({
                            "fingerprint": fingerprint,
                            "name": cache_name,
                            "expires_at": time.monotonic() + 3500,
                            "retry_after": 0.0,
                            "disabled": False,
                        })
                        logger.info('✅ Server-side caching for the main Gemini prompt enabled')
                        return cache_name
                    logger.warning('⚠️ Gemini cache was created, but the response contained no cache ID')
                    GEMINI_PROMPT_CACHE.update({
                        "fingerprint": fingerprint,
                        "name": None,
                        "expires_at": 0.0,
                        "retry_after": time.monotonic() + 300,
                        "disabled": False,
                    })
                else:
                    logger.warning(
                        '⚠️ Failed to create Gemini prompt cache (HTTP %s); continuing this request with a regular prompt',
                        response.status,
                    )
                    GEMINI_PROMPT_CACHE.update({
                        "fingerprint": fingerprint,
                        "name": None,
                        "expires_at": 0.0,
                        "retry_after": time.monotonic() + 300,
                        "disabled": response.status in (400, 401, 403, 404, 422),
                    })
        except (asyncio.TimeoutError, aiohttp.ClientError, json.JSONDecodeError) as error:
            logger.warning('⚠️ Failed to create prompt cache: %s', error)
            GEMINI_PROMPT_CACHE.update({
                "fingerprint": fingerprint,
                "name": None,
                "expires_at": 0.0,
                "retry_after": time.monotonic() + 60,
                "disabled": False,
            })
    return None


class GeminiClient:
    
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
    
    async def test_connection(self) -> Dict:
        """تست اتصال به Gemini API"""
        try:
            url = f"{self.base_url}/models?key={self.api_key}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        models = data.get('models', [])
                        gemini_models = [m['name'].split('/')[-1] for m in models if 'gemini' in m['name']]
                        
                        if self.model in gemini_models:
                            return {'success': True, 'message': 'مدل موجود است'}
                        else:
                            return {'success': False, 'error': f'مدل {self.model} یافت نشد', 'available': gemini_models[:5]}
                    else:
                        text = await response.text()
                        return {'success': False, 'error': f"HTTP {response.status}: {text[:100]}"}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def chat(self, user_message: str, user_id: int = None, username: str = None, retry: int = 2) -> str:
        """ارسال درخواست از مسیر مشترک AI با cache و ردکردن پاسخ ناقص."""
        from routers.ai_assistant import get_ai_response, build_ai_user_database_context
        user_context = ""
        if user_id:
            user_context = build_ai_user_database_context(user_id, user_message)
        return await get_ai_response(
            user_message,
            user_id,
            username,
            user_context=user_context,
        )


class ConversationMemory:
    """مدیریت حافظه مکالمه برای هر کاربر"""
    
    STORAGE_KEY = "ai_conversation_memory"

    def __init__(self):
        self.memories = {}
        self.last_activity = {}

    def _load_history(self, user_id: int) -> list:
        if user_id not in self.memories:
            user = users.get(str(user_id), {})
            history = user.get(self.STORAGE_KEY, []) if isinstance(user, dict) else []
            self.memories[user_id] = history if isinstance(history, list) else []
        return self.memories[user_id]

    def _persist_history(self, user_id: int) -> bool:
        user = users.get(str(user_id))
        if not isinstance(user, dict):
            user = get_user(user_id)
        history = self.memories.get(user_id, [])
        if history:
            user[self.STORAGE_KEY] = history
        else:
            user.pop(self.STORAGE_KEY, None)
        if not save_json(DB_FILES['users'], users):
            logger.error("Could not persist AI conversation memory for user %s", user_id)
            return False
        return True
    
    def add_message(self, user_id: int, role: str, content: str):
        """اضافه کردن و ذخیره دائمی پیام مکالمه کاربر"""
        history = self._load_history(user_id)
        history.append({
            'role': role,  # 'user' یا 'assistant'
            'content': content,
            'timestamp': now_tehran_iso()
        })
        self.last_activity[user_id] = datetime.now()
        self._persist_history(user_id)
    
    def get_history(self, user_id: int) -> list:
        """دریافت تاریخچه کامل و ماندگار مکالمه کاربر"""
        history = self._load_history(user_id)
        if history and user_id not in self.last_activity:
            try:
                self.last_activity[user_id] = datetime.fromisoformat(
                    str(history[-1].get('timestamp'))
                )
            except (TypeError, ValueError):
                self.last_activity[user_id] = datetime.now()
        return history
    
    def get_context(self, user_id: int, max_messages: Optional[int] = None) -> str:
        """دریافت متن مکالمه برای ارسال به AI"""
        history = self.get_history(user_id)
        if not history:
            return ""
        recent = history[-max_messages:] if max_messages else history
        
        context = "تاریخچه مکالمه:\n"
        for msg in recent:
            role = "کاربر" if msg['role'] == 'user' else "دستیار"
            context += f"{role}: {msg['content']}\n"
        
        return context
    
    def has_history(self, user_id: int) -> bool:
        """آیا کاربر تاریخچه دارد؟"""
        return bool(self.get_history(user_id))
    
    def clear(self, user_id: int):
        """پاک کردن حافظه کاربر"""
        self.memories.pop(user_id, None)
        self.last_activity.pop(user_id, None)
        user = users.get(str(user_id))
        if isinstance(user, dict):
            user.pop(self.STORAGE_KEY, None)
            if not save_json(DB_FILES['users'], users):
                logger.error(
                    "Could not clear persisted AI conversation memory for user %s",
                    user_id,
                )

    def clear_all(self):
        """پاک کردن حافظه مکالمه همه کاربران"""
        self.memories.clear()
        self.last_activity.clear()
        for user in users.values():
            if isinstance(user, dict):
                user.pop(self.STORAGE_KEY, None)
        if not save_json(DB_FILES['users'], users):
            logger.error("Could not clear persisted AI conversation memory for all users")
    
    def get_stats(self) -> dict:
        """دریافت آمار حافظه"""
        histories = [
            (int(user_id), user.get(self.STORAGE_KEY, []))
            for user_id, user in users.items()
            if str(user_id).isdigit()
            and isinstance(user, dict)
            and isinstance(user.get(self.STORAGE_KEY), list)
            and user.get(self.STORAGE_KEY)
        ]
        now = datetime.now()
        active_users = 0
        for user_id, history in histories:
            try:
                last_activity = datetime.fromisoformat(
                    str(history[-1].get('timestamp'))
                )
            except (AttributeError, TypeError, ValueError):
                last_activity = self.last_activity.get(user_id, now)
            if (now - last_activity).total_seconds() < 600:
                active_users += 1
        return {
            'total_users': len(histories),
            'total_messages': sum(len(messages) for _, messages in histories),
            'active_users': active_users,
        }
conversation_memory = ConversationMemory()

def check_ai_limit(user_id: int) -> tuple:
    """بررسی محدودیت روزانه کاربر برای استفاده از AI
    
    Returns:
        (can_use: bool, remaining: int, message: str)
    """
    today = now_tehran().date().isoformat()
    daily_limit = GEMINI_DAILY_LIMIT
    
    if user_id not in user_ai_requests:
        user_ai_requests[user_id] = {'date': today, 'count': 0}
    
    if user_ai_requests[user_id]['date'] != today:
        user_ai_requests[user_id] = {'date': today, 'count': 0}
    
    used = user_ai_requests[user_id]['count']
    remaining = daily_limit - used
    
    if remaining <= 0:
        return False, 0, f"⚠️ شما به سقف {daily_limit} سوال در روز رسیده‌اید. فردا دوباره امتحان کنید."
    
    return True, remaining, None


def increment_ai_usage(user_id: int):
    """افزایش شمارش استفاده کاربر از AI"""
    today = now_tehran().date().isoformat()
    
    if user_id not in user_ai_requests or user_ai_requests[user_id]['date'] != today:
        user_ai_requests[user_id] = {'date': today, 'count': 0}
    
    user_ai_requests[user_id]['count'] += 1


def reset_ai_limits():
    """ریست محدودیت‌های روزانه (برای استفاده در تسک روزانه)"""
    global user_ai_requests
    
    today = now_tehran().date().isoformat()
    before_count = sum(u['count'] for u in user_ai_requests.values() if u.get('date') == today)
    before_users = len([u for u in user_ai_requests.values() if u.get('date') == today])
    user_ai_requests = {uid: data for uid, data in user_ai_requests.items() if data['date'] == today}
    for uid in list(user_ai_requests.keys()):
        if user_ai_requests[uid]['date'] == today:
            user_ai_requests[uid]['count'] = 0
    configs_pool['user_ai_requests'] = user_ai_requests
    save_all()
    
    logger.info(f"🔄 AI limits reset - {before_users} user with {before_count} question reset")
    
    return before_users, before_count




async def init_ai():
    """راه‌اندازی کلاینت هوش مصنوعی - فقط Google Gemini"""
    global gemini_client, gemini_error_message

    gemini_error_message = None
    gemini_client = None

    logger.info("=" * 70)
    logger.info('🤖 initializing AI...')
    logger.info("-" * 70)

    logger.info('📡 checking Google Gemini service:')
    logger.info(f"   ├─ GEMINI_ENABLED: {GEMINI_ENABLED}")
    logger.info(f"   ├─ GEMINI_API_KEY: {GEMINI_API_KEY[:15] if GEMINI_API_KEY and len(GEMINI_API_KEY) > 10 else 'NOT SET'}...")
    logger.info(f"   ├─ GEMINI_MODEL: {GEMINI_MODEL}")
    logger.info(f"   ├─ GEMINI_MAX_TOKENS: {GEMINI_MAX_TOKENS}")
    logger.info(f"   └─ GEMINI_DAILY_LIMIT: {GEMINI_DAILY_LIMIT}")

    if GEMINI_ENABLED:
        # بررسی کلید API
        if not GEMINI_API_KEY or GEMINI_API_KEY == "AIzaSyDxxxxxxxxxxxxxxxxxx" or len(GEMINI_API_KEY) < 30:
            gemini_error_message = "❌ کلید API در config.py تنظیم نشده یا نامعتبر است"
            logger.error(f"   ❌ {gemini_error_message}")
            logger.info('   💡 Solution: get a new key from https://aistudio.google.com/apikey')
        else:
            logger.info('   ✅ API key exists (testing connection...)')

            try:
                test_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
                logger.info(f"   🌐 Sending test request to: {test_url[:60]}...")

                async with aiohttp.ClientSession() as session:
                    async with session.get(test_url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                        response_text = await response.text()
                        logger.info(f"   📥 Response received - Status: {response.status}")

                        if response.status == 200:
                            try:
                                data = json.loads(response_text)
                                models = data.get('models', [])
                                gemini_models = [m['name'].split('/')[-1] for m in models if 'gemini' in m['name']]

                                logger.info("   ✅ Connected to Gemini!")
                                logger.info(f"   📋 Available models: {gemini_models}")

                                if GEMINI_MODEL in gemini_models:
                                    logger.info(f"   ✅ Model \'{GEMINI_MODEL}\' is available")
                                    gemini_client = GeminiClient(GEMINI_API_KEY, GEMINI_MODEL)
                                    gemini_error_message = None
                                    logger.info('   🎉 Gemini started successfully!')
                                else:
                                    suggested_models = [m for m in gemini_models if 'flash' in m or 'pro' in m]
                                    if not suggested_models:
                                        suggested_models = gemini_models[:3]

                                    gemini_error_message = f"❌ مدل '{GEMINI_MODEL}' موجود نیست. مدل‌های پیشنهادی: {', '.join(suggested_models)}"
                                    logger.error(f"   ❌ {gemini_error_message}")
                                    gemini_client = None

                            except json.JSONDecodeError as e:
                                gemini_error_message = f"❌ پاسخ JSON نامعتبر: {str(e)[:50]}"
                                logger.error(f"   ❌ {gemini_error_message}")
                                logger.error(f"   📄 Response: {response_text[:200]}")
                                gemini_client = None

                        elif response.status == 400:
                            try:
                                error_data = json.loads(response_text)
                                error_msg = error_data.get('error', {}).get('message', response_text[:100])

                                if "User location is not supported" in error_msg:
                                    gemini_error_message = "🌍 موقعیت جغرافیایی پشتیبانی نمی‌شود - از VPN روی سرور استفاده کنید"
                                elif "API key not valid" in error_msg or "invalid" in error_msg.lower():
                                    gemini_error_message = "❌ کلید API نامعتبر است - یک کلید جدید بگیرید"
                                elif "quota" in error_msg.lower():
                                    gemini_error_message = "⚠️ سهمیه روزانه تمام شده - فردا امتحان کنید"
                                else:
                                    gemini_error_message = f"❌ خطای 400: {error_msg[:100]}"

                                logger.error(f"   ❌ {gemini_error_message}")
                                logger.error(f"   📄 Full response: {response_text[:300]}")

                            except Exception:
                                gemini_error_message = f"❌ خطای 400: {response_text[:100]}"
                                logger.error(f"   ❌ {gemini_error_message}")
                            gemini_client = None

                        elif response.status == 403:
                            gemini_error_message = "❌ دسترسی ممنوع (403) - کلید API نامعتبر یا پروژه فعال نیست"
                            logger.error(f"   ❌ {gemini_error_message}")
                            logger.info('   💡 Solution: Enable the API in Google Cloud Console')
                            gemini_client = None

                        elif response.status == 404:
                            gemini_error_message = f"❌ مدل '{GEMINI_MODEL}' یافت نشد (404)"
                            logger.error(f"   ❌ {gemini_error_message}")
                            logger.info('   💡 Solution: Try a valid model such as gemini-1.5-flash')
                            gemini_client = None

                        elif response.status == 429:
                            gemini_error_message = "⚠️ محدودیت درخواست (429) - چند لحظه صبر کنید"
                            logger.warning(f"   ⚠️ {gemini_error_message}")
                            gemini_client = None

                        else:
                            gemini_error_message = f"❌ خطای ناشناخته: {response.status} - {response_text[:100]}"
                            logger.error(f"   ❌ {gemini_error_message}")
                            gemini_client = None

            except asyncio.TimeoutError:
                gemini_error_message = "⏰ زمان اتصال به Google API به پایان رسید (Timeout)"
                logger.error(f"   ❌ {gemini_error_message}")
                logger.info("   💡 Solution: Check the server's internet connection")
                gemini_client = None

            except aiohttp.ClientConnectorError as e:
                gemini_error_message = f"🌐 خطای اتصال شبکه: {str(e)[:80]}"
                logger.error(f"   ❌ {gemini_error_message}")
                logger.info("   💡 Solution: Check DNS or the server's internet connection")
                gemini_client = None

            except aiohttp.ClientError as e:
                gemini_error_message = f"🌐 خطای شبکه: {str(e)[:80]}"
                logger.error(f"   ❌ {gemini_error_message}")
                gemini_client = None

            except Exception as e:
                gemini_error_message = f"⚠️ خطای غیرمنتظره: {str(e)[:100]}"
                logger.error(f"   ❌ {gemini_error_message}")
                import traceback
                logger.error(f"   📄 {traceback.format_exc()[:200]}")
                gemini_client = None
    else:
        gemini_error_message = "ℹ️ Gemini در config.py غیرفعال شده است (GEMINI_ENABLED = False)"
        logger.info(f"   ℹ️ {gemini_error_message}")

    logger.info("-" * 70)
    logger.info('📊 final summary:')

    if gemini_client:
        logger.info('   ✅ Google Gemini: Enabled')
        logger.info(f"      └─ Model: {GEMINI_MODEL}")
        logger.info('   🎉 AI service started successfully!')
        logger.info('   📌 Active service: Google Gemini')
    else:
        logger.info('   ❌ Google Gemini: Disabled')

"""
services/panel_api.py
---------------------
ماژول ارتباط با وب‌سرویس و پنل 3X-UI (سنایی / علیرضا / MHSanaei)
شامل توابع لاگین، دریافت توکن CSRF، استخراج و همگام‌سازی سابسکریپشن،
مدیریت کلاینت‌ها (ساخت، حذف، اطلاعات، لینک‌ها، تغییر و روتیشن هویت)،
مدیریت اینباندها (دریافت، فیلتر، اتصال و انفصال)، محاسبه ترافیک و تست وضعیت سرور پنل.
"""

import asyncio
import base64
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote, urlparse

import aiohttp
from aiohttp import ClientTimeout, CookieJar
from yarl import URL

from config import (
    SENAI_PANEL_ENABLED,
    SENAI_PANEL_PASSWORD,
    SENAI_PANEL_URL,
    SENAI_PANEL_USERNAME,
    SENAI_SUB_URL,
)
from core.state_stores import (
    CONFIG_LINKS_CACHE,
    USER_INBOUND_SELECTION,
)
from database import (
    DB_FILES,
    configs_pool,
    now_tehran_iso,
    orders,
    save_json,
    update_order,
)
from ping_utils import smart_ping

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# تنظیمات، محدودیت‌ها و متغیرهای وضعیت (State)
# ═══════════════════════════════════════════════════════════════════════════

LOGIN_TIMEOUT = ClientTimeout(total=5, connect=3)
API_TIMEOUT = ClientTimeout(total=5, connect=3)

COOKIE_TTL = 3600  # 1 hour
CSRF_TTL = 3600    # 1 hour
INBOUND_CACHE_TTL = 300  # 5 minutes

LOGIN_LOCK = asyncio.Lock()
INBOUND_LOCK = asyncio.Lock()

HTTP_SESSION: Optional[aiohttp.ClientSession] = None
CONNECTOR: Optional[aiohttp.TCPConnector] = None

SENAI_COOKIE: Optional[str] = None
COOKIE_TIME: float = 0.0

SENAI_CSRF: Optional[str] = None
CSRF_TIME: float = 0.0

INBOUND_CACHE: Dict[str, Any] = {
    "data": [],
    "time": 0.0,
    "loaded": False,
}

PANEL_SUB_PATH: Optional[str] = None
PANEL_SUB_URI: Optional[str] = None
PANEL_COMPUTED_SUB_BASE_URL: Optional[str] = None

panel_semaphore = asyncio.Semaphore(3)  # حداکثر ۳ درخواست همزمان


class PanelRateLimiter:
    """محدود کننده نرخ درخواست به پنل"""

    def __init__(self, requests_per_minute: int = 30):
        self.requests_per_minute = requests_per_minute
        self.interval = 60.0 / requests_per_minute
        self.last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def wait_if_needed(self):
        """اگر لازم باشد، صبر کن تا نرخ درخواست محدود نشود"""
        async with self._lock:
            now = time.time()
            time_since_last = now - self.last_request_time

            if time_since_last < self.interval:
                wait_time = self.interval - time_since_last
                logger.debug(f"⏳ Rate limit: waiting {wait_time:.2f}s before next request")
                await asyncio.sleep(wait_time)

            self.last_request_time = time.time()


panel_rate_limiter = PanelRateLimiter(requests_per_minute=30)

# کش شناسه ساب به ایمیل
_subid_to_email_cache: Dict[str, Tuple[datetime, Optional[str]]] = {}
_subid_cache_ttl = 300            # ۵ دقیقه برای کش مثبت
_subid_cache_negative_ttl = 60    # ۶۰ ثانیه برای کش منفی


# ═══════════════════════════════════════════════════════════════════════════
# توابع آدرس و سابسکریپشن
# ═══════════════════════════════════════════════════════════════════════════

def _is_auto_sub_url(url: Optional[str]) -> bool:
    """بررسی اینکه آیا آدرس ساب روی حالت خودکار یا خالی است"""
    if not url:
        return True
    cleaned = str(url).strip().lower()
    return cleaned in ("auto", "none", "") or "sub.domain.com" in cleaned


def get_sub_base_url() -> str:
    """
    محاسبه آدرس پایه سابسکریپشن همراه با وب‌پث
    - در صورت تنظیم دستی SENAI_SUB_URL (غیر از auto یا خالی)، همان استفاده می‌شود
    - در صورت تنظیم روی auto یا خالی، مقدار به صورت خودکار و دقیق از تنظیمات پنل سنایی (subURI، subPort، subPath، SSL) استخراج می‌شود
    """
    raw_sub = (SENAI_SUB_URL or "").strip()
    if not _is_auto_sub_url(raw_sub):
        try:
            parsed = urlparse(raw_sub)
            path = (parsed.path or "").strip('/')
            if path:
                return raw_sub.rstrip('/')

            sub_path = (PANEL_SUB_PATH or "sub").strip('/')
            return f"{raw_sub.rstrip('/')}/{sub_path}"
        except Exception:
            return raw_sub.rstrip('/')

    # حالت خودکار (auto) با آدرس استخراج شده از پنل سنایی
    if PANEL_COMPUTED_SUB_BASE_URL:
        return PANEL_COMPUTED_SUB_BASE_URL.rstrip('/')

    # در صورت عدم اجرای همگام‌سازی، بازگشت به فال‌بک پنل با /sub
    try:
        panel_parsed = urlparse(SENAI_PANEL_URL)
        scheme = panel_parsed.scheme or "https"
        host = panel_parsed.hostname or "localhost"
        port_str = f":{panel_parsed.port}" if panel_parsed.port else ""
        sub_path = (PANEL_SUB_PATH or "sub").strip('/')
        return f"{scheme}://{host}{port_str}/{sub_path}"
    except Exception:
        return ""


async def ensure_sub_base_url() -> str:
    """اطمینان از دریافت و همگام‌سازی آدرس سابسکریپشن از پنل در صورت قرار داشتن روی حالت auto"""
    global PANEL_COMPUTED_SUB_BASE_URL
    if _is_auto_sub_url(SENAI_SUB_URL) and not PANEL_COMPUTED_SUB_BASE_URL:
        await xui_sync_sub_settings()
    return get_sub_base_url()


def _get_base_url() -> URL:
    """دریافت Base URL بدون path"""
    panel_url = URL(SENAI_PANEL_URL)
    return URL(f"{panel_url.scheme}://{panel_url.host}:{panel_url.port}")


# ═══════════════════════════════════════════════════════════════════════════
# مدیریت Session و لاگین
# ═══════════════════════════════════════════════════════════════════════════

async def _ensure_session():
    """اطمینان از وجود Session فعال"""
    global HTTP_SESSION, CONNECTOR

    needs_new = HTTP_SESSION is None or HTTP_SESSION.closed
    if not needs_new:
        try:
            running_loop = asyncio.get_running_loop()
            session_loop = getattr(HTTP_SESSION, "_loop", None)
            if session_loop is not None and (session_loop is not running_loop or session_loop.is_closed()):
                needs_new = True
        except RuntimeError:
            pass

    if needs_new:
        if HTTP_SESSION is not None and not HTTP_SESSION.closed:
            try:
                old_loop = getattr(HTTP_SESSION, "_loop", None)
                if old_loop is None or not old_loop.is_closed():
                    await HTTP_SESSION.close()
            except Exception:
                pass
        CONNECTOR = aiohttp.TCPConnector(
            ssl=False,
            limit=50,
            limit_per_host=20,
            ttl_dns_cache=300,
            keepalive_timeout=300,
            force_close=False,
        )
        HTTP_SESSION = aiohttp.ClientSession(
            connector=CONNECTOR,
            cookie_jar=CookieJar(unsafe=True),
        )

    return HTTP_SESSION


async def init_http_session():
    """فقط یک بار در startup ربات صدا زده شود"""
    await _ensure_session()
    try:
        await xui_sync_sub_settings()
    except Exception as e:
        logger.warning(f"Error syncing subscription settings: {e}")


async def close_http_session():
    """بستن سشن هنگام خاموش شدن بات"""
    global HTTP_SESSION, CONNECTOR
    global SENAI_COOKIE, COOKIE_TIME
    global SENAI_CSRF, CSRF_TIME
    global INBOUND_CACHE
    global PANEL_SUB_PATH, PANEL_SUB_URI, PANEL_COMPUTED_SUB_BASE_URL

    if HTTP_SESSION and not HTTP_SESSION.closed:
        await HTTP_SESSION.close()

    HTTP_SESSION = None
    CONNECTOR = None

    SENAI_COOKIE = None
    COOKIE_TIME = 0.0

    SENAI_CSRF = None
    CSRF_TIME = 0.0

    PANEL_SUB_PATH = None
    PANEL_SUB_URI = None
    PANEL_COMPUTED_SUB_BASE_URL = None

    INBOUND_CACHE = {
        "data": [],
        "time": 0.0,
        "loaded": False,
    }


def _get_cookie_from_session() -> Optional[str]:
    """استخراج کوکی از CookieJar خود Session - منبع اصلی"""
    if HTTP_SESSION is None or HTTP_SESSION.closed:
        return None

    base_url = _get_base_url()
    jar = HTTP_SESSION.cookie_jar.filter_cookies(base_url)

    for name in ("3x-ui", "session"):
        cookie = jar.get(name)
        if cookie and cookie.value:
            return cookie.value

    return None


async def _do_login() -> Optional[str]:
    """عملیات واقعی لاگین (داخل Lock صدا زده شود)"""
    global SENAI_COOKIE, COOKIE_TIME, SENAI_CSRF, CSRF_TIME

    try:
        await _ensure_session()
        async with HTTP_SESSION.get(
            f"{SENAI_PANEL_URL}/csrf-token",
            timeout=LOGIN_TIMEOUT,
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            if not data.get("success"):
                return None
            SENAI_CSRF = data.get("obj")
            CSRF_TIME = time.time()
            logger.debug('CSRF token received')

        async with HTTP_SESSION.post(
            f"{SENAI_PANEL_URL}/login",
            data={
                "username": SENAI_PANEL_USERNAME,
                "password": SENAI_PANEL_PASSWORD,
            },
            headers={"X-CSRF-Token": SENAI_CSRF},
            allow_redirects=False,
            timeout=LOGIN_TIMEOUT,
        ) as resp:
            if resp.status in (200, 302):
                jar_cookie = _get_cookie_from_session()
                if jar_cookie:
                    SENAI_COOKIE = jar_cookie
                    COOKIE_TIME = time.time()
                    logger.debug('Login successful (from CookieJar)')
                    return SENAI_COOKIE
                for name in ("3x-ui", "session"):
                    cookie = resp.cookies.get(name)
                    if cookie and cookie.value:
                        SENAI_COOKIE = cookie.value
                        COOKIE_TIME = time.time()
                        logger.debug('Login successful (from response.cookies)')
                        return SENAI_COOKIE

                logger.error('Cookie not found in response or CookieJar')

            return None

    except Exception as e:
        logger.error(f"Error logging in: {e}")
        return None


async def xui_login() -> Optional[str]:
    """ورود به پنل 3X-UI"""
    global SENAI_COOKIE, COOKIE_TIME

    if not SENAI_PANEL_ENABLED:
        return None

    current_time = time.time()
    cookie = _get_cookie_from_session()
    if cookie:
        SENAI_COOKIE = cookie
        COOKIE_TIME = current_time
        return cookie
    if SENAI_COOKIE and (current_time - COOKIE_TIME) < COOKIE_TTL:
        return SENAI_COOKIE

    async with LOGIN_LOCK:
        current_time = time.time()
        if SENAI_COOKIE and (current_time - COOKIE_TIME) < COOKIE_TTL:
            return SENAI_COOKIE

        cookie = _get_cookie_from_session()
        if cookie:
            SENAI_COOKIE = cookie
            COOKIE_TIME = current_time
            return cookie

        return await _do_login()


async def xui_get_csrf_token(session=None) -> Optional[str]:
    """دریافت CSRF token با TTL"""
    global SENAI_CSRF, CSRF_TIME

    current_time = time.time()

    if SENAI_CSRF and (current_time - CSRF_TIME) < CSRF_TTL:
        return SENAI_CSRF

    await _ensure_session()

    async with HTTP_SESSION.get(
        f"{SENAI_PANEL_URL}/csrf-token",
        timeout=API_TIMEOUT,
    ) as resp:
        if resp.status == 200:
            data = await resp.json(content_type=None)
            if data.get("success"):
                SENAI_CSRF = data.get("obj")
                CSRF_TIME = current_time
                logger.debug(f"CSRF token: {SENAI_CSRF[:20]}...")

    return SENAI_CSRF


async def _api_request(method: str, path: str, **kwargs) -> Optional[dict]:
    """درخواست به API با retry خودکار در صورت 401"""
    global SENAI_COOKIE, COOKIE_TIME, SENAI_CSRF, CSRF_TIME

    await _ensure_session()
    await xui_login()
    if not SENAI_COOKIE:
        return None

    headers = kwargs.pop("headers", {})
    if method.upper() != "GET":
        if not SENAI_CSRF or (time.time() - CSRF_TIME) >= CSRF_TTL:
            await xui_get_csrf_token()
        if SENAI_CSRF:
            headers["X-CSRF-Token"] = SENAI_CSRF

    url = f"{SENAI_PANEL_URL}{path}"

    try:
        async with HTTP_SESSION.request(
            method, url,
            headers=headers,
            timeout=API_TIMEOUT,
            **kwargs,
        ) as resp:
            if resp.status == 401:
                logger.warning('401 - logging in again...')

                async with LOGIN_LOCK:
                    cookie_check = _get_cookie_from_session()
                    if cookie_check and cookie_check != SENAI_COOKIE:
                        SENAI_COOKIE = cookie_check
                        COOKIE_TIME = time.time()
                        SENAI_CSRF = None
                        CSRF_TIME = 0.0
                        logger.debug('Concurrent login detected')
                    else:
                        SENAI_COOKIE = None
                        COOKIE_TIME = 0.0
                        SENAI_CSRF = None
                        CSRF_TIME = 0.0
                        HTTP_SESSION.cookie_jar.clear()
                        await _do_login()

                if not SENAI_COOKIE:
                    return None
                headers_retry = {}
                if method.upper() != "GET":
                    if not SENAI_CSRF:
                        await xui_get_csrf_token()
                    if SENAI_CSRF:
                        headers_retry["X-CSRF-Token"] = SENAI_CSRF

                async with HTTP_SESSION.request(
                    method, url,
                    headers=headers_retry,
                    timeout=API_TIMEOUT,
                    **kwargs,
                ) as retry_resp:
                    if retry_resp.status == 200:
                        return await retry_resp.json(content_type=None)
                    return None
            if resp.status == 200:
                return await resp.json(content_type=None)

            return None

    except Exception as e:
        logger.error(f"API request error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# همگام‌سازی تنظیمات سابسکریپشن از پنل سنایی
# ═══════════════════════════════════════════════════════════════════════════

async def xui_sync_sub_settings() -> bool:
    """دریافت و استخراج دقیق تنظیمات سابسکریپشن از پنل سنایی (پشتیبانی از http، https، پورت، دامنه‌های مختلف و پث‌های سفارشی)"""
    global PANEL_SUB_PATH, PANEL_SUB_URI, PANEL_COMPUTED_SUB_BASE_URL
    if not SENAI_PANEL_ENABLED:
        return False
    try:
        await xui_get_csrf_token()

        result = await _api_request("POST", "/panel/setting/all")
        if not result or not result.get("success"):
            result = await _api_request("POST", "/panel/api/setting/all")
        if not result or not result.get("success"):
            result = await _api_request("GET", "/panel/setting/all")
        if not result or not result.get("success"):
            result = await _api_request("GET", "/panel/api/setting/all")

        logger.info(f"📡 request settings result from Sanaei panel: success={bool(result and result.get('success'))}")

        if result and result.get("success"):
            raw_obj = result.get("obj")
            if isinstance(raw_obj, list):
                settings_map = {item.get("key"): item.get("value") for item in raw_obj if isinstance(item, dict)}
            elif isinstance(raw_obj, dict):
                settings_map = raw_obj
            else:
                settings_map = {}

            logger.info(f"📋 Keys received from Sanaei panel settings: {list(settings_map.keys())}")

            # 1. استخراج دامنه سابسکریپشن (بررسی همه کلیدهای ممکن در نسخه‌های مختلف 3X-UI)
            sub_domain = (
                settings_map.get("subDomain") or
                settings_map.get("subURI") or
                settings_map.get("subUrl") or
                settings_map.get("subURL") or
                settings_map.get("sub_domain") or
                settings_map.get("sub_uri") or
                settings_map.get("subscriptionUrl") or
                settings_map.get("domain") or
                ""
            ).strip()

            # 2. استخراج پورت سابسکریپشن
            sub_port_raw = (
                settings_map.get("subPort") or
                settings_map.get("sub_port") or
                settings_map.get("subscriptionPort") or
                ""
            )
            try:
                sub_port = int(str(sub_port_raw).strip()) if str(sub_port_raw).strip() else 0
            except (ValueError, TypeError):
                sub_port = 0

            # 3. استخراج وب‌پث سابسکریپشن
            sub_path = (
                settings_map.get("subPath") or
                settings_map.get("sub_path") or
                settings_map.get("subscriptionPath") or
                "sub"
            ).strip().strip('/')
            if not sub_path:
                sub_path = "sub"

            # 4. استخراج گواهی SSL ساب
            sub_cert = (
                settings_map.get("subCertFile") or
                settings_map.get("sub_cert_file") or
                ""
            ).strip()

            PANEL_SUB_PATH = sub_path
            PANEL_SUB_URI = sub_domain

            panel_parsed = urlparse(SENAI_PANEL_URL)
            panel_host = panel_parsed.hostname or "localhost"

            # اگر sub_domain خالی بود و آدرس پنل 127.0.0.1 یا localhost بود، تلاش برای استخراج دامنه از اینباندها
            if not sub_domain and panel_host in ("127.0.0.1", "localhost", "::1"):
                try:
                    inbounds = await xui_get_inbounds()
                    for ib in inbounds:
                        stream = ib.get("streamSettings") or {}
                        if isinstance(stream, str):
                            try:
                                stream = json.loads(stream)
                            except Exception:
                                stream = {}
                        reality_names = stream.get("realitySettings", {}).get("serverNames") or []
                        for name in reality_names:
                            if name and "." in name and not name.startswith("127."):
                                sub_domain = name.strip()
                                logger.info(f"🔍 Fallback domain extracted from Reality inbound: {sub_domain}")
                                break
                        if sub_domain:
                            break
                        tls_name = stream.get("tlsSettings", {}).get("serverName") or ""
                        if tls_name and "." in tls_name and not tls_name.startswith("127."):
                            sub_domain = tls_name.strip()
                            logger.info(f"🔍 Fallback domain extracted from TLS inbound: {sub_domain}")
                            break
                        ws_host = stream.get("wsSettings", {}).get("headers", {}).get("Host") or ""
                        if ws_host and "." in ws_host and not ws_host.startswith("127."):
                            sub_domain = ws_host.strip()
                            logger.info(f"🔍 Fallback domain extracted from WebSocket inbound: {sub_domain}")
                            break
                except Exception as e:
                    logger.debug(f"Unable to extract domain from inbounds: {e}")

            # تعیین پروتکل (http یا https)
            scheme = "https"
            if sub_domain.startswith("http://"):
                scheme = "http"
            elif sub_domain.startswith("https://"):
                scheme = "https"
            elif sub_cert:
                scheme = "https"
            elif sub_port in (443, 8443, 2053, 2083, 2087, 2096):
                scheme = "https"
            elif sub_port in (80, 8080, 8880, 2052, 2082, 2086, 2095):
                scheme = "http"
            elif panel_parsed.scheme:
                scheme = panel_parsed.scheme

            # ساخت آدرس نهایی با پورت و وب‌پث
            if sub_domain:
                clean_domain = re.sub(r"^https?://", "", sub_domain).strip().strip('/')
                if '/' in clean_domain:
                    parts = clean_domain.split('/', 1)
                    host_part = parts[0]
                    path_part = parts[1].strip('/')
                    if path_part:
                        sub_path = path_part
                else:
                    host_part = clean_domain

                if ':' in host_part:
                    netloc = host_part
                else:
                    if sub_port and sub_port not in (80, 443):
                        netloc = f"{host_part}:{sub_port}"
                    else:
                        netloc = host_part

                PANEL_COMPUTED_SUB_BASE_URL = f"{scheme}://{netloc}/{sub_path}".rstrip('/')
            else:
                host_part = panel_host
                if sub_port and sub_port not in (80, 443):
                    netloc = f"{host_part}:{sub_port}"
                elif not sub_port and panel_parsed.port and panel_parsed.port not in (80, 443):
                    netloc = f"{host_part}:{panel_parsed.port}"
                else:
                    netloc = host_part

                PANEL_COMPUTED_SUB_BASE_URL = f"{scheme}://{netloc}/{sub_path}".rstrip('/')

            logger.info(f"🌐 Final subscription URL extracted from the Sanaei panel: {PANEL_COMPUTED_SUB_BASE_URL}")
            return True
        else:
            logger.warning(f"⚠️ Unsuccessful or empty response from Sanaei panel settings: {result}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to retrieve subscription settings from panel: {e}", exc_info=True)
    return False


# ═══════════════════════════════════════════════════════════════════════════
# مدیریت اینباندها
# ═══════════════════════════════════════════════════════════════════════════

async def xui_get_inbounds(
    force_refresh: bool = False,
    include_disabled: bool = False,
) -> list:
    """دریافت لیست اینباندها با کش و Lock"""
    global INBOUND_CACHE

    if include_disabled:
        async with INBOUND_LOCK:
            result = await _api_request("GET", "/panel/api/inbounds/list")
        if result and result.get("success") and isinstance(result.get("obj"), list):
            return result["obj"]
        logger.error('failed to receive all inbounds from panel')
        return []

    # اگه force_refresh، کش رو باطل کن
    if force_refresh:
        INBOUND_CACHE["loaded"] = False
        INBOUND_CACHE["time"] = 0.0

    current_time = time.time()
    if INBOUND_CACHE["loaded"] and (current_time - INBOUND_CACHE["time"]) < INBOUND_CACHE_TTL:
        logger.debug(f"inbound cache: {len(INBOUND_CACHE['data'])} number")
        return INBOUND_CACHE["data"]

    async with INBOUND_LOCK:
        current_time = time.time()
        if INBOUND_CACHE["loaded"] and (current_time - INBOUND_CACHE["time"]) < INBOUND_CACHE_TTL:
            return INBOUND_CACHE["data"]

        result = await _api_request("GET", "/panel/api/inbounds/list")
        if result and result.get("success"):
            inbounds = [i for i in result.get("obj", []) if i.get("enable", True)]
            INBOUND_CACHE["data"] = inbounds
            INBOUND_CACHE["time"] = current_time
            INBOUND_CACHE["loaded"] = True
            logger.debug(f"{len(inbounds)} active inbound retrieved")
            return inbounds
        if INBOUND_CACHE["loaded"]:
            logger.warning('Error retrieving inbounds; using previous cache')
            return INBOUND_CACHE["data"]

        return []


def get_user_inbound(user_id: int) -> Optional[Union[int, List[int]]]:
    """دریافت اینباند انتخاب شده برای کاربر (تک یا لیست)"""
    user_inbound = USER_INBOUND_SELECTION.get(str(user_id))
    if user_inbound:
        return user_inbound
    default_ids = configs_pool.get('default_inbound_ids', [])
    if default_ids:
        return default_ids
    return None


async def filter_valid_inbounds(inbound_ids) -> list:
    """
    فیلتر کردن اینباندهای نامعتبر
    فقط اینباندهایی که توی پنل وجود دارند و فعال هستند را برمی‌گرداند.
    """
    if not inbound_ids:
        return []

    if not isinstance(inbound_ids, list):
        inbound_ids = [inbound_ids]

    inbound_ids = [ib for ib in inbound_ids if ib]
    if not inbound_ids:
        return []

    try:
        inbounds = await xui_get_inbounds()
        active_inbound_ids = {i.get('id') for i in inbounds if i.get('enable', True)}
    except Exception as e:
        logger.error(f"❌ [filter_valid_inbounds] Error retrieving inbounds: {e}")
        return inbound_ids

    valid = [ib for ib in inbound_ids if ib in active_inbound_ids]
    invalid = [ib for ib in inbound_ids if ib not in active_inbound_ids]

    if invalid:
        logger.warning(f"⚠️ [filter_valid_inbounds] invalid inbounds removed: {invalid}")

    return valid


async def get_inbound_display_names(
    include_disabled: bool = True,
    force_refresh: bool = False,
) -> Dict[int, str]:
    """Build a mapping of inbound_id -> human-readable 'remark - PROTOCOL:port' label."""
    inbounds = await xui_get_inbounds(
        force_refresh=force_refresh,
        include_disabled=include_disabled,
    )
    if not inbounds and include_disabled:
        inbounds = await xui_get_inbounds(force_refresh=force_refresh, include_disabled=False)

    names: Dict[int, str] = {}
    for ib in inbounds or []:
        if not isinstance(ib, dict):
            continue
        raw_id = ib.get("id")
        if raw_id is None:
            continue
        try:
            ib_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        remark = str(ib.get("remark") or f"ID:{ib_id}")
        protocol = str(ib.get("protocol") or "").upper()
        port = ib.get("port", "")
        disabled_tag = "" if ib.get("enable", True) else " (غیرفعال)"
        names[ib_id] = f"{remark} - {protocol}:{port}{disabled_tag}"
    return names


async def reset_panel_rate_limits() -> bool:
    """ریست کردن محدودیت‌های پنل"""
    global panel_semaphore, panel_rate_limiter
    panel_semaphore = asyncio.Semaphore(3)
    panel_rate_limiter = PanelRateLimiter(requests_per_minute=30)
    logger.info('🔄 panel limits reset')
    return True


# ═══════════════════════════════════════════════════════════════════════════
# ساخت کلاینت در پنل
# ═══════════════════════════════════════════════════════════════════════════

async def xui_create_client_with_inbound(
    email: str,
    volume_gb: int,
    days: int,
    user_name: str = None,
    user_id: int = None,
    inbound_id: int = None,
    ip_limit: int = 0,
) -> Optional[str]:
    """ساخت کلاینت با اینباند مشخص (یا پیش‌فرض) - پشتیبانی از چندین اینباند و IP Limit"""
    global SENAI_COOKIE, SENAI_CSRF

    inbound_ids = []
    if inbound_id is not None:
        if isinstance(inbound_id, list):
            inbound_ids = inbound_id
            logger.info(f"📡 Using the specified inbound list: {inbound_ids}")
        else:
            inbound_ids = [inbound_id]
            logger.info(f"📡 Using the specified inbound: {inbound_id}")
    elif user_id:
        user_inbound = get_user_inbound(user_id)
        if user_inbound:
            if isinstance(user_inbound, list):
                inbound_ids = user_inbound
                logger.info(f"👤 Using inbounds for user {user_id}: {inbound_ids}")
            else:
                inbound_ids = [user_inbound]
                logger.info(f"👤 Using inbound selected by user {user_id}: {user_inbound}")
    if not inbound_ids:
        default_ids = configs_pool.get('default_inbound_ids', [])
        if default_ids:
            inbound_ids = default_ids
            logger.info(f"📌 Using default inbounds: {default_ids}")

    for attempt in range(3):  # 3 تلاش برای دریافت اینباندها
        if attempt > 0:
            logger.info(f"🔄 Retrying {attempt+1}/3 to retrieve inbounds")
            await asyncio.sleep(2 * attempt)

        try:
            async with panel_semaphore:
                await panel_rate_limiter.wait_if_needed()

                cookie = await xui_login()
                if not cookie:
                    logger.error('❌ Failed to log in to panel')
                    continue

                inbounds = await xui_get_inbounds()
                if not inbounds:
                    logger.error('❌ No active inbounds found')
                    continue
                if not inbound_ids:
                    inbound_ids = [i.get('id') for i in inbounds if i.get('enable', True)]
                    logger.info(f"📡 Using all active inbounds: {inbound_ids}")
                valid_inbound_ids = []
                invalid_inbounds = []

                for ib_id in inbound_ids:
                    found = False
                    for i in inbounds:
                        if i.get('id') == ib_id and i.get('enable', True):
                            valid_inbound_ids.append(ib_id)
                            found = True
                            break
                    if not found:
                        invalid_inbounds.append(ib_id)

                if invalid_inbounds:
                    logger.warning(f"⚠️ Invalid inbounds: {invalid_inbounds}")

                if not valid_inbound_ids:
                    valid_inbound_ids = [i.get('id') for i in inbounds if i.get('enable', True)]
                    logger.info(f"📡 Using all active inbounds (because the previous inbounds were invalid): {valid_inbound_ids}")

                if not valid_inbound_ids:
                    logger.error('❌ No valid inbounds found')
                    continue

                expiry_time = int(datetime.now().timestamp() * 1000) + (days * 24 * 60 * 60 * 1000)
                if volume_gb == 0:
                    total_bytes = 0  # 0 در پنل به معنی نامحدود است
                    logger.info("📦 Volume: unlimited (0 bytes)")
                else:
                    total_bytes = int(volume_gb * 1024 * 1024 * 1024)
                    logger.info(f"📦 Data: {volume_gb} GB = {total_bytes:,} bytes")

                logger.info(f"⏱ Expiration: {days} days = {expiry_time}")
                comment_parts = []
                if user_name:
                    comment_parts.append(user_name)
                if user_id:
                    comment_parts.append(f"(ID:{user_id})")
                comment_text = " ".join(comment_parts) if comment_parts else email

                if len(comment_text) > 100:
                    comment_text = comment_text[:97] + "..."

                logger.info(f"📝 Comment: {comment_text}")
                sub_id = secrets.token_urlsafe(16)
                bulk_data = [
                    {
                        "client": {
                            "email": email,
                            "enable": True,
                            "expiryTime": expiry_time,
                            "totalGB": total_bytes,
                            "limitIp": ip_limit,
                            "subId": sub_id,
                            "resetStrategy": "no_reset",
                            "comment": comment_text,
                        },
                        "inboundIds": valid_inbound_ids,
                    }
                ]
                logger.info('📤 Client creation request sent to the panel (%s inbounds)', len(valid_inbound_ids))
                logger.info(f"👤 IP limit: {ip_limit if ip_limit > 0 else 'unlimited'}")
                logger.info(f"📦 Data: {'unlimited' if volume_gb == 0 else f'{volume_gb} GB'}")
                await _ensure_session()
                csrf = await xui_get_csrf_token(HTTP_SESSION)
                headers = {"X-CSRF-Token": csrf} if csrf else {}

                async with HTTP_SESSION.post(
                    f"{SENAI_PANEL_URL}/panel/api/clients/bulkCreate",
                    cookies={"3x-ui": cookie},
                    headers=headers,
                    json=bulk_data,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    response_text = await response.text()
                    logger.info(f"📥 Panel response: Status {response.status}")
                    if response.status == 200:
                        try:
                            data = json.loads(response_text)
                            if data.get("success"):
                                logger.info(f"✅ Client {email} with inbounds {valid_inbound_ids} created!")
                                logger.info(f"   📦 Volume: {'unlimited' if volume_gb == 0 else f'{volume_gb} GB'}")
                                logger.info(f"   👤 IP limit: {ip_limit if ip_limit > 0 else 'unlimited'}")
                                logger.info(f"   📡 Inbounds: {valid_inbound_ids}")
                                logger.info(f"   📝 Comment: {comment_text}")
                                try:
                                    actual_client = await xui_get_client_info(email)
                                    if actual_client:
                                        actual_sub_id = actual_client.get('subId', '') or email
                                        logger.info(f"   🔗 Actual subId from panel: {actual_sub_id}")
                                        base_sub = await ensure_sub_base_url()
                                        return f"{base_sub}/{actual_sub_id}"
                                except Exception as e:
                                    logger.warning(f"⚠️ Error retrieving actual subId: {e}")

                                base_sub = await ensure_sub_base_url()
                                return f"{base_sub}/{email}"
                            else:
                                error_msg = data.get('msg', 'Unknown error')
                                logger.error(f"❌ Error creating client: {error_msg}")
                                logger.info(f"📝 Full response: {response_text[:500]}")
                        except json.JSONDecodeError:
                            logger.error(f"❌ Invalid JSON response: {response_text[:200]}")
                    elif response.status == 403:
                        logger.error('❌ Error 403 - Unauthorized access')
                        SENAI_COOKIE = None
                        SENAI_CSRF = None
                        await asyncio.sleep(3)
                    elif response.status == 429:
                        logger.warning('⚠️ Request rate limit (429)')
                        await asyncio.sleep(5 * (attempt + 1))
                    else:
                        logger.error(f"❌ Error creating client: Status {response.status}")
                        logger.info(f"📝 Response: {response_text[:200]}")

        except asyncio.TimeoutError:
            logger.error(f"⏰ Timeout creating client {email} (attempt {attempt+1}/3)")
            await asyncio.sleep(5 * (attempt + 1))
        except aiohttp.ClientError as e:
            logger.error(f"🌐 Network error creating client {email} (attempt {attempt+1}/3): {e}")
            await asyncio.sleep(3 * (attempt + 1))
        except Exception as e:
            logger.error(f"❌ Unexpected error creating client (attempt {attempt+1}/3): {e}")
            SENAI_COOKIE = None
            SENAI_CSRF = None
            await asyncio.sleep(3 * (attempt + 1))

    logger.error(f"❌ client creation {email} after 3 failed attempts failed")
    return None


# ═══════════════════════════════════════════════════════════════════════════
# اطلاعات، ترافیک، لینک‌ها و حذف کلاینت
# ═══════════════════════════════════════════════════════════════════════════

async def xui_get_client_info(email: str) -> Optional[dict]:
    """دریافت اطلاعات کلاینت از پنل 3X-UI با مدیریت خطا"""
    cookie = await xui_login()
    if not cookie:
        return None

    try:
        await _ensure_session()
        csrf = await xui_get_csrf_token(HTTP_SESSION)
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        async with HTTP_SESSION.get(
            f"{SENAI_PANEL_URL}/panel/api/clients/get/{email}",
            cookies={"3x-ui": cookie},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("success"):
                    obj = data.get("obj", {})
                    client = obj.get("client", obj)

                    logger.debug('Client retrieved from panel (%s)', type(client).__name__)

                    if not isinstance(client, dict):
                        logger.warning(f"⚠️ Client for {email} is not a dictionary: {type(client)}")
                        return None

                    expiry = client.get('expiryTime', 0)
                    if expiry > 0:
                        try:
                            expiry_date = datetime.fromtimestamp(expiry / 1000)
                            logger.debug(f"📅 Expiration date: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}")
                        except Exception:
                            pass

                    return client
                else:
                    logger.info(f"ℹ️ Client {email} not found in panel (success: false)")
                    return None
            elif response.status == 404:
                logger.info(f"ℹ️ Client {email} not found in panel (404)")
                return None
            else:
                logger.warning(f"⚠️ Error retrieving client {email}: Status {response.status}")
                if response.status >= 500:
                    logger.warning(f"⚠️ Server error {response.status} - client {email} may exist")
                    return {}
                return None
    except asyncio.TimeoutError:
        logger.warning(f"⏰ Timeout retrieving client {email}")
        return {}
    except aiohttp.ClientError as e:
        logger.warning(f"🌐 Network error retrieving client {email}: {e}")
        return {}
    except Exception as e:
        logger.error(f"❌ Error retrieving client information {email}: {e}")
        return None


async def xui_delete_client(email: str) -> bool:
    """حذف کلاینت از پنل 3X-UI"""
    cookie = await xui_login()
    if not cookie:
        return False

    try:
        await _ensure_session()
        csrf = await xui_get_csrf_token(HTTP_SESSION)
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        async with HTTP_SESSION.post(
            f"{SENAI_PANEL_URL}/panel/api/clients/del/{email}",
            cookies={"3x-ui": cookie},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("success"):
                    logger.info(f"✅ Client {email} deleted from the panel")
                    return True
            logger.error(f"❌ Error deleting client {email}: {response.status}")
            return False
    except Exception as e:
        logger.error(f"❌ Error deleting client {email}: {e}")
        return False


def extract_email_from_sub_link(sub_link: str) -> Optional[str]:
    """استخراج email از لینک ساب"""
    if not sub_link:
        return None
    parts = sub_link.rstrip('/').split('/')
    if parts:
        return parts[-1]
    return None


def build_sub_link_from_client(email: str, client_data: dict = None) -> str:
    """ساخت لینک ساب با اولویت subId (نه email) و وب‌پث هوشمند"""
    base_sub = get_sub_base_url()
    if not base_sub:
        base_sub = f"{(SENAI_SUB_URL or '').rstrip('/')}/sub"

    if client_data and isinstance(client_data, dict):
        sub_id = client_data.get('subId', '') or ''
        if sub_id.strip():
            return f"{base_sub}/{sub_id.strip()}"

    if email:
        return f"{base_sub}/{email.strip()}"

    return ""


def get_order_client_email(order: dict) -> Optional[str]:
    """دریافت email کلاینت از سفارش"""
    email = order.get('email', '')
    if email and str(email).strip():
        return str(email).strip()

    logger.debug(
        f"⚠️ [get_order_client_email] order #{order.get('order_id')} no direct email"
    )
    return None


def _prune_subid_cache() -> None:
    """Keep _subid_to_email_cache bounded to prevent unbounded memory growth."""
    if len(_subid_to_email_cache) <= 2000:
        return
    now_dt = datetime.now()
    expired_keys = [
        k for k, (ts, val) in list(_subid_to_email_cache.items())
        if (now_dt - ts).total_seconds() >= (_subid_cache_ttl if val else _subid_cache_negative_ttl)
    ]
    for k in expired_keys:
        _subid_to_email_cache.pop(k, None)
    if len(_subid_to_email_cache) > 2000:
        excess = len(_subid_to_email_cache) - 1500
        for k in list(_subid_to_email_cache.keys())[:excess]:
            _subid_to_email_cache.pop(k, None)


async def find_email_by_sub_id(sub_id: str, use_cache: bool = True) -> Optional[str]:
    """پیدا کردن email کلاینت با subId (با کش)"""
    if not sub_id:
        return None

    if use_cache and sub_id in _subid_to_email_cache:
        cache_time, cached_email = _subid_to_email_cache[sub_id]
        age = (datetime.now() - cache_time).total_seconds()

        if cached_email:
            if age < _subid_cache_ttl:
                logger.debug(f"📦 [find_email_by_sub_id] cache hit: {sub_id[:15]}... → {cached_email}")
                return cached_email
        else:
            if age < _subid_cache_negative_ttl:
                logger.debug(f"📦 [find_email_by_sub_id] negative cache: {sub_id[:15]}...")
                return None

    try:
        inbounds = await xui_get_inbounds()
        for inbound in inbounds:
            settings = inbound.get('settings', {})
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except Exception:
                    settings = {}
            clients = settings.get('clients', [])
            for client in clients:
                if client.get('subId', '') == sub_id:
                    email = client.get('email', '')
                    if email:
                        _prune_subid_cache()
                        _subid_to_email_cache[sub_id] = (datetime.now(), email)
                        logger.info(f"✅ [find_email_by_sub_id] {sub_id[:15]}... → {email}")
                        return email
    except Exception as e:
        logger.error(f"❌ [find_email_by_sub_id] Error: {e}")
        if sub_id in _subid_to_email_cache:
            _, cached_email = _subid_to_email_cache[sub_id]
            if cached_email:
                return cached_email
        return None

    _prune_subid_cache()
    _subid_to_email_cache[sub_id] = (datetime.now(), None)
    logger.debug(f"⏭️ [find_email_by_sub_id] not found: {sub_id[:15]}...")
    return None


async def xui_get_client_traffic(email: str) -> Optional[dict]:
    """دریافت آمار مصرف ترافیک کلاینت از پنل"""
    cookie = await xui_login()
    if not cookie:
        logger.warning("Traffic API skipped for client %s: panel login failed.", email)
        return None

    try:
        await _ensure_session()
        csrf = await xui_get_csrf_token(HTTP_SESSION)
        headers = {"X-CSRF-Token": csrf} if csrf else {}
        async with HTTP_SESSION.get(
            f"{SENAI_PANEL_URL}/panel/api/clients/traffic/{email}",
            cookies={"3x-ui": cookie},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            body = await response.text()
            content_type = response.headers.get("Content-Type", "unknown")
            if response.status != 200:
                logger.warning(
                    "Traffic API returned HTTP %s for client %s (content-type=%s, body=%r).",
                    response.status, email, content_type, body[:500],
                )
                return None
            try:
                data = json.loads(body)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Traffic API returned invalid JSON for client %s (content-type=%s): %s; body=%r",
                    email, content_type, exc, body[:500],
                )
                return None
            if not isinstance(data, dict):
                logger.warning("Traffic API returned %s instead of an object for client %s.", type(data).__name__, email)
                return None
            if not data.get("success"):
                logger.warning(
                    "Traffic API reported failure for client %s (msg=%r, body=%r).",
                    email, data.get("msg") or data.get("message"), body[:500],
                )
                return None
            traffic = data.get("obj")
            if not isinstance(traffic, dict):
                logger.warning("Traffic API response has no usable obj for client %s (obj_type=%s).", email, type(traffic).__name__)
                return None
            return traffic
    except Exception as exc:
        logger.warning("Error retrieving traffic for client %s: %s", email, exc, exc_info=True)
        return None


async def get_client_inbounds(email: str) -> list:
    """دریافت لیست اینباندهایی که کلاینت به آنها متصل است"""
    try:
        client_info = await xui_get_client_info(email)
        if client_info:
            inbound_ids = client_info.get('inboundIds', [])
            if inbound_ids:
                return inbound_ids if isinstance(inbound_ids, list) else [inbound_ids]

            inbound_id = client_info.get('inboundId')
            if inbound_id:
                return [inbound_id]

        inbounds = await xui_get_inbounds()
        found_inbounds = []
        for inbound in inbounds:
            settings = inbound.get('settings', {})
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except Exception:
                    settings = {}
            clients = settings.get('clients', [])
            for client in clients:
                if client.get('email') == email:
                    found_inbounds.append(inbound.get('id'))
                    break
        return found_inbounds

    except Exception as e:
        logger.error(f"❌ Error retrieving client inbounds {email}: {e}")
        return []


async def xui_detach_inbounds(email: str, inbound_ids: list) -> bool:
    """حذف یک یا چند اینباند از کلاینت"""
    if not inbound_ids:
        logger.info('ℹ️ no inbounds to detach')
        return True

    try:
        cookie = await xui_login()
        if not cookie:
            logger.error('❌ Error logging in to the panel')
            return False

        await _ensure_session()
        csrf = await xui_get_csrf_token(HTTP_SESSION)
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        detach_url = f"{SENAI_PANEL_URL}/panel/api/clients/{email}/detach"
        detach_data = {"inboundIds": inbound_ids}

        logger.info('📤 Detach request sent for %s inbounds', len(inbound_ids))

        async with HTTP_SESSION.post(
            detach_url,
            cookies={"3x-ui": cookie},
            headers=headers,
            json=detach_data,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            response_text = await response.text()
            logger.info(f"📥 Detach response: Status {response.status}")

            if response.status == 200:
                try:
                    data = json.loads(response_text)
                    if data.get("success"):
                        logger.info(f"✅ Inbounds {inbound_ids} successfully detached from client {email} removed")
                        return True
                    else:
                        logger.error(f"❌ detach failed: {data.get('msg', 'Unknown error')}")
                        return False
                except json.JSONDecodeError:
                    logger.error(f"❌ Error decoding JSON: {response_text[:200]}")
                    return False
            else:
                logger.error(f"❌ detach failed: Status {response.status}")
                return False

    except Exception as e:
        logger.error(f"❌ Error detaching inbounds from client {email}: {e}")
        return False


async def xui_attach_inbounds(email: str, inbound_ids: list) -> bool:
    """اضافه کردن یک یا چند اینباند به کلاینت موجود"""
    if not inbound_ids:
        logger.info('ℹ️ no inbounds to attach')
        return True

    try:
        cookie = await xui_login()
        if not cookie:
            logger.error('❌ Error logging in to the panel')
            return False

        await _ensure_session()
        csrf = await xui_get_csrf_token(HTTP_SESSION)
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        attach_url = f"{SENAI_PANEL_URL}/panel/api/clients/{email}/attach"
        attach_data = {"inboundIds": inbound_ids}

        logger.info('📤 Attach request sent for %s inbounds', len(inbound_ids))

        async with HTTP_SESSION.post(
            attach_url,
            cookies={"3x-ui": cookie},
            headers=headers,
            json=attach_data,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            response_text = await response.text()
            logger.info(f"📥 Attach response: Status {response.status}")

            if response.status == 200:
                try:
                    data = json.loads(response_text)
                    if data.get("success"):
                        logger.info(f"✅ Inbounds {inbound_ids} successfully attached to client {email} added")
                        return True
                    else:
                        error_msg = data.get('msg', 'Unknown error')
                        logger.error(f"❌ attach failed: {error_msg}")
                        return False
                except json.JSONDecodeError:
                    logger.error(f"❌ Error decoding JSON: {response_text[:200]}")
                    return False
            else:
                logger.error(f"❌ attach failed: Status {response.status}")
                return False

    except Exception as e:
        logger.error(f"❌ Error attaching inbounds to client {email}: {e}")
        return False


async def xui_reset_client_traffic(email: str, inbounds: list = None) -> bool:
    """ریست کردن ترافیک مصرفی کلاینت در پنل 3X-UI"""
    if not SENAI_PANEL_ENABLED or not email:
        return False

    success = False
    try:
        cookie = await xui_login()
        if not cookie:
            logger.error(f"❌ Error logging in to the panel to reset traffic {email}")
            return False

        await _ensure_session()
        csrf = await xui_get_csrf_token(HTTP_SESSION)
        headers = {"X-CSRF-Token": csrf} if csrf else {}
        encoded_email = quote(str(email), safe='')

        # 1. تلاش از طریق API مستقیم کلاینت
        try:
            url = f"{SENAI_PANEL_URL}/panel/api/clients/resetTraffic/{encoded_email}"
            async with HTTP_SESSION.post(
                url,
                cookies={"3x-ui": cookie},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp_text = await resp.text()
                if resp.status == 200:
                    try:
                        data = json.loads(resp_text)
                        if data.get("success"):
                            logger.info(f"✅ Client traffic {email} reset via the clients/resetTraffic endpoint")
                            success = True
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"ℹ️ clients/resetTraffic: {e}")

        # 2. ریست روی تک تک اینباندها
        target_inbounds = list(inbounds) if inbounds else []
        if not target_inbounds:
            try:
                target_inbounds = await get_client_inbounds(email)
            except Exception:
                target_inbounds = []

        if target_inbounds:
            for inb_id in target_inbounds:
                if not inb_id:
                    continue
                try:
                    inb_url = f"{SENAI_PANEL_URL}/panel/api/inbounds/{inb_id}/resetClientTraffic/{encoded_email}"
                    async with HTTP_SESSION.post(
                        inb_url,
                        cookies={"3x-ui": cookie},
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        resp_text = await resp.text()
                        if resp.status == 200:
                            try:
                                data = json.loads(resp_text)
                                if data.get("success"):
                                    logger.info(f"✅ Client traffic {email} in inbound {inb_id} reset")
                                    success = True
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"⚠️ Error resetting traffic for inbound {inb_id} client {email}: {e}")

        # 3. تلاش با اندپوینت عمومی inbounds/resetClientTraffic/{email}
        if not success:
            try:
                alt_url = f"{SENAI_PANEL_URL}/panel/api/inbounds/resetClientTraffic/{encoded_email}"
                async with HTTP_SESSION.post(
                    alt_url,
                    cookies={"3x-ui": cookie},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp_text = await resp.text()
                    if resp.status == 200:
                        try:
                            data = json.loads(resp_text)
                            if data.get("success"):
                                logger.info(f"✅ Client traffic {email} reset via the public inbounds endpoint")
                                success = True
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"ℹ️ alt inbounds/resetClientTraffic: {e}")

        return success
    except Exception as e:
        logger.error(f"❌ Error in xui_reset_client_traffic for {email}: {e}")
        return False


async def test_panel_connection() -> dict:
    """تست کامل اتصال به پنل با پینگ هوشمند"""
    result = {
        'login': False,
        'inbounds': 0,
        'ping': None,
        'http_ping': None,
        'error': None,
    }

    if not SENAI_PANEL_ENABLED:
        result['error'] = 'غیرفعال'
        return result

    try:
        parsed = urlparse(SENAI_PANEL_URL)
        host = parsed.hostname

        if host:
            ping_result = await smart_ping(host)
            if ping_result is not None:
                result['ping'] = round(ping_result, 1)
            else:
                result['ping'] = None
                logger.warning(f"⚠️ Ping to {host} failed")
        else:
            result['ping'] = None

        start = time.time()
        await _ensure_session()
        try:
            async with HTTP_SESSION.get(
                SENAI_PANEL_URL,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                result['http_ping'] = int((time.time() - start) * 1000)
                result['http_status'] = response.status
        except asyncio.TimeoutError:
            result['http_ping'] = None
            logger.warning(f"⏰ HTTP timeout to {SENAI_PANEL_URL}")
        except Exception as e:
            result['http_ping'] = None
            logger.warning(f"⚠️ HTTP error: {e}")

        cookie = await xui_login()
        if cookie:
            result['login'] = True
            inbounds = await xui_get_inbounds()
            if inbounds:
                result['inbounds'] = len(inbounds)

    except Exception as e:
        result['error'] = str(e)[:80]
        logger.error(f"❌ Error testing the panel: {e}")

    return result


async def get_panel_status() -> Optional[dict]:
    """دریافت وضعیت سرور پنل (CPU, RAM, Disk, Uptime)"""
    cookie = await xui_login()
    if not cookie:
        return None

    try:
        await _ensure_session()
        csrf = await xui_get_csrf_token(HTTP_SESSION)
        headers = {"X-CSRF-Token": csrf} if csrf else {}
        async with HTTP_SESSION.get(
            f"{SENAI_PANEL_URL}/panel/api/server/status",
            cookies={"3x-ui": cookie},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("success"):
                    obj = data.get("obj", {})
                    mem = obj.get("mem", {})
                    mem_total = mem.get("total", 0)
                    mem_current = mem.get("current", 0)
                    mem_percent = mem.get("percent", 0)
                    if mem_total == 0:
                        try:
                            async with HTTP_SESSION.get(
                                f"{SENAI_PANEL_URL}/panel/api/server/meminfo",
                                cookies={"3x-ui": cookie},
                                headers=headers,
                                timeout=aiohttp.ClientTimeout(total=5),
                            ) as mem_response:
                                if mem_response.status == 200:
                                    mem_data = await mem_response.json()
                                    if mem_data.get("success"):
                                        mem_obj = mem_data.get("obj", {})
                                        mem_total = mem_obj.get("total", 0)
                                        mem_current = mem_obj.get("current", 0)
                                        mem_percent = mem_obj.get("percent", 0)
                        except Exception:
                            pass
                    net_io = obj.get("netIO", {})

                    return {
                        "cpu": obj.get("cpu", 0),
                        "mem": {
                            "total": mem_total,
                            "current": mem_current,
                            "percent": mem_percent,
                        },
                        "disk": obj.get("disk", {}),
                        "net": obj.get("net", {}),
                        "uptime": obj.get("uptime", 0),
                        "net_up": net_io.get("up", 0),
                        "net_down": net_io.get("down", 0),
                    }
            return None
    except Exception as e:
        logger.error(f"❌ Error retrieving panel status: {e}")
        return None


async def xui_get_client_links(email: str) -> Optional[list]:
    """دریافت لینک‌های کانفیگ از پنل"""
    cookie = await xui_login()
    if not cookie:
        return None

    try:
        await _ensure_session()
        csrf = await xui_get_csrf_token(HTTP_SESSION)
        headers = {"X-CSRF-Token": csrf} if csrf else {}

        async with HTTP_SESSION.get(
            f"{SENAI_PANEL_URL}/panel/api/clients/links/{email}",
            cookies={"3x-ui": cookie},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("success"):
                    links = data.get("obj", [])
                    logger.debug('Panel links retrieved (%s items)', len(links) if isinstance(links, list) else 0)
                    return links
            return None
    except Exception as e:
        logger.error(f"❌ Error retrieving links: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# توابع روتیشن هویت و تنظیمات کلیدهای کلاینت
# ═══════════════════════════════════════════════════════════════════════════

def _panel_success(response: Optional[dict]) -> bool:
    return bool(response and response.get("success") is True)


async def _panel_generate_uuid() -> str:
    response = await _api_request("GET", "/panel/api/server/getNewUUID")
    value = (response or {}).get("obj", {}).get("uuid")
    if not _panel_success(response) or not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
        value,
    ):
        raise RuntimeError("پنل UUID معتبر تولید نکرد")
    return value


async def _panel_generate_wireguard_keypair() -> tuple:
    response = await _api_request("GET", "/panel/api/server/getNewX25519Cert")
    values = (response or {}).get("obj")
    if not _panel_success(response) or not isinstance(values, dict):
        raise RuntimeError("پنل نتوانست کلید X25519 برای WireGuard تولید کند")

    normalized = []
    for name in ("privateKey", "publicKey"):
        value = values.get(name)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"پنل {name} معتبر برای WireGuard برنگرداند")
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        except (ValueError, base64.binascii.Error) as e:
            raise RuntimeError(f"کلید {name} برگشتی از پنل Base64 معتبر نیست") from e
        if len(raw) != 32:
            raise RuntimeError(f"کلید {name} برگشتی از پنل ۳۲ بایت نیست")
        normalized.append(base64.b64encode(raw).decode("ascii"))
    return tuple(normalized)


def _subscription_id_from_link(link: Optional[str]) -> Optional[str]:
    if not link:
        return None
    try:
        parsed = URL(link)
        base_sub = get_sub_base_url()
        configured = URL(base_sub) if base_sub else URL(SENAI_SUB_URL)
        if parsed.origin() != configured.origin():
            return None
        parts = parsed.path.rstrip("/").split("/")
        if parts and parts[-1]:
            return parts[-1]
    except (TypeError, ValueError):
        return None
    return None


def _as_allowed_ips(value) -> list:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _build_panel_client_update_payload(client: dict, email: str) -> dict:
    """Map the panel's read model to the complete client update request."""
    required_fields = (
        "email", "security", "password", "flow", "auth", "privateKey",
        "publicKey", "preSharedKey", "keepAlive", "secret", "adTag",
        "limitIp", "limitHwid", "totalGB", "expiryTime", "enable", "tgId",
        "subId", "group", "comment", "reset", "resetDay", "resetWeekday",
        "resetMax", "trafficReset", "trafficResetDay",
    )
    missing_fields = [field for field in required_fields if field not in client]
    if missing_fields:
        raise RuntimeError(
            "اطلاعات کامل کلاینت برای حفظ تنظیمات پنل دریافت نشد: "
            + ", ".join(missing_fields)
        )

    uuid_value = client.get("uuid")
    if not isinstance(uuid_value, str) or not uuid_value:
        candidate = client.get("id")
        uuid_value = candidate if isinstance(candidate, str) else ""

    payload = {
        "id": uuid_value,
        "security": client.get("security", ""),
        "password": client.get("password", ""),
        "flow": client.get("flow", ""),
        "auth": client.get("auth", ""),
        "privateKey": client.get("privateKey", ""),
        "publicKey": client.get("publicKey", ""),
        "allowedIPs": _as_allowed_ips(client.get("allowedIPs")),
        "preSharedKey": client.get("preSharedKey", ""),
        "keepAlive": client.get("keepAlive", 0),
        "forwardedPorts": client.get("forwardedPorts", ""),
        "secret": client.get("secret", ""),
        "adTag": client.get("adTag", ""),
        "email": email,
        "limitIp": client.get("limitIp", 0),
        "limitHwid": client.get("limitHwid", 0),
        "totalGB": client.get("totalGB", 0),
        "expiryTime": client.get("expiryTime", 0),
        "enable": client.get("enable", True),
        "tgId": client.get("tgId", 0),
        "subId": client.get("subId", ""),
        "group": client.get("group", ""),
        "comment": client.get("comment", ""),
        "reset": client.get("reset", 0),
        "resetDay": client.get("resetDay", 0),
        "resetWeekday": client.get("resetWeekday", 0),
        "resetMax": client.get("resetMax", 0),
        "trafficReset": client.get("trafficReset", "never"),
        "trafficResetDay": client.get("trafficResetDay", 1),
        "created_at": client.get("created_at", client.get("createdAt", 0)),
    }

    reverse = client.get("reverse")
    if reverse:
        if isinstance(reverse, str):
            try:
                reverse = json.loads(reverse)
            except json.JSONDecodeError as e:
                raise RuntimeError("تنظیم reverse کلاینت قابل حفظ نیست") from e
        if not isinstance(reverse, dict):
            raise RuntimeError("تنظیم reverse کلاینت قابل حفظ نیست")
        payload["reverse"] = reverse
    return payload


async def _fetch_panel_client(email: str) -> dict:
    response = await _api_request(
        "GET",
        f"/panel/api/clients/get/{quote(email, safe='')}",
    )
    obj = (response or {}).get("obj")
    client = obj.get("client") if isinstance(obj, dict) else None
    if not _panel_success(response) or not isinstance(client, dict):
        raise RuntimeError("کلاینت دقیقاً با این email در پنل پیدا نشد")
    return obj


def _decode_inbound_settings(inbound: dict) -> dict:
    settings = inbound.get("settings", {})
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"تنظیمات اینباند {inbound.get('id')} قابل خواندن نیست"
            ) from e
    if not isinstance(settings, dict):
        raise RuntimeError(f"تنظیمات اینباند {inbound.get('id')} معتبر نیست")
    return settings


async def _rotate_panel_client_identity(email: str, user_id: int, order_id: int) -> tuple:
    if not SENAI_PANEL_ENABLED:
        raise RuntimeError("اتصال به پنل فعال نیست")

    order = orders.get(str(order_id))
    if (
        not order
        or order.get("user_id") != user_id
        or order.get("status") not in ("approved", "inactive")
        or order.get("email") != email
    ):
        raise RuntimeError("سفارش یا مالکیت کانفیگ با درخواست تطبیق ندارد")

    matching_orders = [
        item for item in orders.values()
        if isinstance(item, dict) and item.get("email") == email
    ]
    if any(item.get("user_id") != user_id for item in matching_orders):
        raise RuntimeError("email کلاینت در سفارش کاربر دیگری هم ثبت شده؛ عملیات متوقف شد")

    panel_obj = await _fetch_panel_client(email)
    panel_client = panel_obj["client"]
    old_sub_id = panel_client.get("subId")
    related_orders = [
        item for item in matching_orders
        if item.get("status") in ("approved", "inactive")
    ]
    if not related_orders or order not in related_orders:
        raise RuntimeError("سفارش فعالی برای ثبت subId جدید در دیتابیس پیدا نشد")
    stored_sub_ids = {
        sub_id
        for item in related_orders
        for sub_id in (
            _subscription_id_from_link(item.get("config_link")),
            _subscription_id_from_link(item.get("sub_link")),
        )
        if sub_id
    }
    if not old_sub_id or stored_sub_ids != {old_sub_id}:
        raise RuntimeError("subId پنل با لینک ذخیره‌شده در سفارش‌ها یکسان نیست")

    comment = str(panel_client.get("comment", ""))
    comment_ids = re.findall(r"\(ID:\s*(\d+)\)", comment)
    panel_tg_id = panel_client.get("tgId", 0)
    try:
        panel_tg_id = int(panel_tg_id or 0)
    except (TypeError, ValueError):
        raise RuntimeError("شناسهٔ تلگرام ذخیره‌شده در پنل معتبر نیست")
    if panel_tg_id and panel_tg_id != user_id:
        raise RuntimeError("شناسهٔ تلگرام کلاینت پنل متعلق به این کاربر نیست")
    if comment_ids and any(int(value) != user_id for value in comment_ids):
        raise RuntimeError("شناسهٔ کاربر در توضیحات پنل با سفارش مطابقت ندارد")
    if panel_tg_id != user_id and str(user_id) not in comment_ids:
        raise RuntimeError("مالکیت کلاینت با tgId یا شناسهٔ داخل comment تأیید نشد")

    inbounds_response = await _api_request("GET", "/panel/api/inbounds/list")
    if not _panel_success(inbounds_response) or not isinstance(
        inbounds_response.get("obj"), list
    ):
        raise RuntimeError("فهرست اینباندها از پنل دریافت نشد")

    targets = []
    protocols = set()
    shadowsocks_key_sizes = set()
    wireguard_ips = {}
    panel_tunnel_ips = panel_obj.get("tunnelAllowedIPs", {})
    if not isinstance(panel_tunnel_ips, dict):
        panel_tunnel_ips = {}
    for inbound in inbounds_response["obj"]:
        if not isinstance(inbound, dict):
            continue
        settings = _decode_inbound_settings(inbound)
        clients = settings.get("clients", [])
        if not isinstance(clients, list):
            raise RuntimeError(f"فهرست کلاینت‌های اینباند {inbound.get('id')} معتبر نیست")
        matches = [
            item for item in clients
            if isinstance(item, dict) and item.get("email") == email
        ]
        if not matches:
            continue
        if len(matches) != 1:
            raise RuntimeError(
                f"کلاینت با email یکسان چندبار در اینباند {inbound.get('id')} وجود دارد"
            )
        inbound_id = inbound.get("id")
        if not isinstance(inbound_id, int):
            raise RuntimeError("شناسهٔ اینباند معتبر نیست")

        protocol = str(inbound.get("protocol", "")).lower()
        if protocol not in {
            "vless", "vmess", "trojan", "shadowsocks",
            "wireguard", "amneziawg", "hysteria", "tuic", "mtproto",
        }:
            raise RuntimeError(f"پروتکل {protocol or 'نامشخص'} پشتیبانی نمی‌شود")

        entry = {
            "id": inbound_id,
            "protocol": protocol,
            "client": matches[0],
            "settings": settings,
        }
        targets.append(entry)
        protocols.add(protocol)
        if protocol == "shadowsocks":
            method = str(settings.get("method", settings.get("cipher", ""))).lower()
            if method.startswith("2022-blake3-"):
                if "aes-128-gcm" in method:
                    shadowsocks_key_sizes.add(16)
                elif "aes-256-gcm" in method or "chacha20-poly1305" in method:
                    shadowsocks_key_sizes.add(32)
                else:
                    raise RuntimeError(f"روش رمزنگاری Shadowsocks پشتیبانی نمی‌شود: {method}")
        if protocol in ("wireguard", "amneziawg"):
            allowed_ips = _as_allowed_ips(matches[0].get("allowedIPs"))
            if allowed_ips:
                wireguard_ips[str(inbound_id)] = allowed_ips

    if not targets:
        raise RuntimeError("هیچ اینباندی با تطبیق دقیق email کلاینت پیدا نشد")
    wireguard_targets = [
        item for item in targets
        if item["protocol"] in ("wireguard", "amneziawg")
    ]
    for target in wireguard_targets:
        inbound_key = str(target["id"])
        if inbound_key not in wireguard_ips:
            allowed_ips = _as_allowed_ips(
                panel_tunnel_ips.get(inbound_key, panel_tunnel_ips.get(target["id"]))
            )
            if not allowed_ips and len(wireguard_targets) == 1:
                allowed_ips = _as_allowed_ips(panel_client.get("allowedIPs"))
            if not allowed_ips:
                raise RuntimeError(
                    f"Allowed IP کلاینت WireGuard در اینباند {target['id']} مشخص نیست"
                )
            wireguard_ips[inbound_key] = allowed_ips
    target_ids = {item["id"] for item in targets}
    attached_ids = panel_obj.get("inboundIds")
    if isinstance(attached_ids, list) and {
        int(value) for value in attached_ids if str(value).isdigit()
    } != target_ids:
        raise RuntimeError("فهرست اینباندهای کلاینت با تنظیمات پنل همخوانی ندارد")

    old_uuid = panel_client.get("uuid")
    if not isinstance(old_uuid, str) or not old_uuid:
        candidate = panel_client.get("id")
        old_uuid = candidate if isinstance(candidate, str) else ""
    if any(protocol in protocols for protocol in ("vless", "vmess", "tuic")) and not old_uuid:
        raise RuntimeError("UUID فعلی کلاینت قابل شناسایی نیست")
    if any(protocol in protocols for protocol in ("trojan", "shadowsocks", "tuic")):
        if not panel_client.get("password"):
            raise RuntimeError("رمز فعلی کلاینت قابل شناسایی نیست")
    if protocols.intersection({"wireguard", "amneziawg"}):
        if not panel_client.get("privateKey") or not panel_client.get("publicKey"):
            raise RuntimeError("کلیدهای فعلی WireGuard قابل شناسایی نیستند")

    old_links = await xui_get_client_links(email)
    url_protocols = protocols.intersection(
        {"vless", "vmess", "trojan", "shadowsocks", "mtproto"}
    )
    if url_protocols and not old_links:
        raise RuntimeError("لینک‌های فعلی از پنل قابل دریافت نیستند؛ عملیات متوقف شد")

    old_payload = _build_panel_client_update_payload(panel_client, email)
    if wireguard_ips:
        old_payload["allowedIPsByInbound"] = wireguard_ips
    new_payload = dict(old_payload)
    new_sub_id = await _panel_generate_uuid()
    while new_sub_id == old_sub_id:
        new_sub_id = await _panel_generate_uuid()
    new_payload["subId"] = new_sub_id

    mtproto_targets = [item for item in targets if item["protocol"] == "mtproto"]
    new_mtproto_secret = None
    if mtproto_targets:
        mtproto_settings = mtproto_targets[0]["settings"]
        mtproto_domain = str(
            mtproto_settings.get("fakeTlsDomain") or "www.cloudflare.com"
        ).strip()
        new_mtproto_secret = (
            f"ee{secrets.token_hex(16)}{mtproto_domain.encode('utf-8').hex()}"
        )

    if old_uuid or any(protocol in protocols for protocol in ("vless", "vmess", "tuic")):
        new_payload["id"] = await _panel_generate_uuid()
    if any(protocol in protocols for protocol in ("trojan", "shadowsocks", "tuic")):
        if len(shadowsocks_key_sizes) > 1:
            raise RuntimeError("این کلاینت به Shadowsocks با طول کلیدهای متناقض متصل است")
        if shadowsocks_key_sizes:
            key_size = next(iter(shadowsocks_key_sizes))
            new_payload["password"] = base64.b64encode(
                secrets.token_bytes(key_size)
            ).decode("ascii")
        else:
            new_payload["password"] = (await _panel_generate_uuid()).replace("-", "")
    if "hysteria" in protocols:
        new_payload["auth"] = (await _panel_generate_uuid()).replace("-", "")
    if protocols.intersection({"wireguard", "amneziawg"}):
        new_payload["privateKey"], new_payload["publicKey"] = (
            await _panel_generate_wireguard_keypair()
        )
        new_payload["allowedIPsByInbound"] = wireguard_ips

    attempted_ids = []
    old_order_values = {
        id(item): {
            "config_link": item.get("config_link"),
            "sub_link": item.get("sub_link"),
            "updated_at": item.get("updated_at"),
        }
        for item in related_orders
    }
    orders_modified = False
    try:
        for inbound_id in sorted(target_ids):
            attempted_ids.append(inbound_id)
            target = next(item for item in targets if item["id"] == inbound_id)
            target_payload = new_payload
            if target["protocol"] == "mtproto":
                target_payload = dict(new_payload)
                target_payload["secret"] = new_mtproto_secret
            response = await _api_request(
                "POST",
                f"/panel/api/clients/update/{quote(email, safe='')}?inboundIds={inbound_id}",
                json=target_payload,
            )
            if not _panel_success(response):
                raise RuntimeError(
                    f"پنل در به‌روزرسانی اینباند {inbound_id} خطا داد: "
                    f"{(response or {}).get('msg', 'پاسخ نامعتبر')}"
                )

        verified_obj = await _fetch_panel_client(email)
        verified_client = verified_obj["client"]
        if verified_client.get("subId") != new_sub_id:
            raise RuntimeError("subId جدید در پنل تأیید نشد")
        if "id" in new_payload:
            actual_uuid = verified_client.get("uuid") or verified_client.get("id")
            if actual_uuid != new_payload["id"]:
                raise RuntimeError("UUID جدید در پنل تأیید نشد")
        if "password" in new_payload and verified_client.get("password") != new_payload["password"]:
            raise RuntimeError("رمز جدید در پنل تأیید نشد")
        if "privateKey" in new_payload and (
            verified_client.get("privateKey") != new_payload["privateKey"]
            or verified_client.get("publicKey") != new_payload["publicKey"]
        ):
            raise RuntimeError("کلیدهای WireGuard جدید در پنل تأیید نشدند")

        fresh_inbounds = await _api_request("GET", "/panel/api/inbounds/list")
        if not _panel_success(fresh_inbounds) or not isinstance(fresh_inbounds.get("obj"), list):
            raise RuntimeError("تأیید نهایی تنظیمات اینباند از پنل ممکن نشد")
        for inbound in fresh_inbounds["obj"]:
            if inbound.get("id") not in target_ids:
                continue
            settings = _decode_inbound_settings(inbound)
            matched = [
                item for item in settings.get("clients", [])
                if isinstance(item, dict) and item.get("email") == email
            ]
            if len(matched) != 1:
                raise RuntimeError(f"کلاینت در اینباند {inbound.get('id')} تأیید نشد")
            protocol = str(inbound.get("protocol", "")).lower()
            client = matched[0]
            if protocol in ("vless", "vmess", "tuic") and client.get("id") != new_payload["id"]:
                raise RuntimeError(f"UUID جدید در اینباند {inbound.get('id')} تأیید نشد")
            if protocol in ("trojan", "shadowsocks", "tuic") and client.get("password") != new_payload["password"]:
                raise RuntimeError(f"رمز جدید در اینباند {inbound.get('id')} تأیید نشد")
            if protocol in ("wireguard", "amneziawg") and (
                client.get("privateKey") != new_payload["privateKey"]
                or client.get("publicKey") != new_payload["publicKey"]
            ):
                raise RuntimeError(f"کلید جدید در اینباند {inbound.get('id')} تأیید نشد")
            if protocol == "mtproto" and client.get("secret") != new_mtproto_secret:
                raise RuntimeError(f"MTProto secret جدید در اینباند {inbound.get('id')} تأیید نشد")

        new_links = await xui_get_client_links(email)
        if url_protocols and not new_links:
            raise RuntimeError("لینک‌های جدید از پنل دریافت نشدند")
        if old_links and new_links and set(old_links).intersection(new_links):
            raise RuntimeError("بعضی لینک‌های قبلی هنوز فعال هستند")

        new_subscription_link = build_sub_link_from_client(email, verified_client)
        if (
            not new_subscription_link
            or _subscription_id_from_link(new_subscription_link) != new_sub_id
        ):
            raise RuntimeError("لینک اشتراک جدید از subId تأییدشده ساخته نشد")

        for related_order in related_orders:
            related_order["config_link"] = new_subscription_link
            related_order["sub_link"] = new_subscription_link
            related_order["updated_at"] = now_tehran_iso()
        orders_modified = True
        if not save_json(DB_FILES["orders"], orders):
            raise RuntimeError("لینک جدید پنل ذخیره نشد؛ تغییرات در حال بازگردانی است")

    except Exception as operation_error:
        if orders_modified:
            for related_order in related_orders:
                previous = old_order_values[id(related_order)]
                for field, value in previous.items():
                    if value is None:
                        related_order.pop(field, None)
                    else:
                        related_order[field] = value
            if not save_json(DB_FILES["orders"], orders):
                logger.critical('Failed to save the previous order link after the operation failed')

        rollback_errors = []
        for inbound_id in reversed(attempted_ids):
            target = next(item for item in targets if item["id"] == inbound_id)
            rollback_payload = old_payload
            if target["protocol"] == "mtproto":
                rollback_payload = dict(old_payload)
                rollback_payload["secret"] = target["client"].get("secret", "")
            rollback = await _api_request(
                "POST",
                f"/panel/api/clients/update/{quote(email, safe='')}?inboundIds={inbound_id}",
                json=rollback_payload,
            )
            if not _panel_success(rollback):
                rollback_errors.append(inbound_id)
        if attempted_ids and not rollback_errors:
            try:
                restored_obj = await _fetch_panel_client(email)
                restored_client = restored_obj["client"]
                restored_uuid = restored_client.get("uuid") or restored_client.get("id")
                if (
                    restored_client.get("subId") != old_payload["subId"]
                    or restored_uuid != old_payload["id"]
                    or restored_client.get("password") != old_payload["password"]
                    or restored_client.get("privateKey") != old_payload["privateKey"]
                    or restored_client.get("publicKey") != old_payload["publicKey"]
                ):
                    rollback_errors.append("client-record")

                restored_inbounds = await _api_request("GET", "/panel/api/inbounds/list")
                if not _panel_success(restored_inbounds) or not isinstance(
                    restored_inbounds.get("obj"), list
                ):
                    rollback_errors.append("inbound-verification")
                else:
                    restored_by_id = {
                        inbound.get("id"): inbound
                        for inbound in restored_inbounds["obj"]
                        if isinstance(inbound, dict)
                    }
                    for inbound_id in attempted_ids:
                        inbound = restored_by_id.get(inbound_id)
                        if not inbound:
                            rollback_errors.append(inbound_id)
                            continue
                        settings = _decode_inbound_settings(inbound)
                        restored_matches = [
                            item for item in settings.get("clients", [])
                            if isinstance(item, dict) and item.get("email") == email
                        ]
                        expected = next(
                            item["client"] for item in targets if item["id"] == inbound_id
                        )
                        protocol = next(
                            item["protocol"] for item in targets if item["id"] == inbound_id
                        )
                        if len(restored_matches) != 1:
                            rollback_errors.append(inbound_id)
                            continue
                        restored = restored_matches[0]
                        credential_fields = []
                        if protocol in ("vless", "vmess", "tuic"):
                            credential_fields.append("id")
                        if protocol in ("trojan", "shadowsocks", "tuic"):
                            credential_fields.append("password")
                        if protocol == "hysteria":
                            credential_fields.append("auth")
                        if protocol == "mtproto":
                            credential_fields.append("secret")
                        if protocol in ("wireguard", "amneziawg"):
                            credential_fields.extend(("privateKey", "publicKey"))
                        if any(restored.get(field) != expected.get(field) for field in credential_fields):
                            rollback_errors.append(inbound_id)

                restored_links = await xui_get_client_links(email)
                if old_links and (
                    not restored_links or set(restored_links) != set(old_links)
                ):
                    rollback_errors.append("subscription-links")
            except Exception as rollback_verification_error:
                logger.error(
                    'Panel restore confirmation failed for client %s: %s',
                    email,
                    rollback_verification_error,
                    exc_info=True,
                )
                rollback_errors.append("verification-error")
        if rollback_errors:
            logger.critical(
                'Failed to restore client link rotation for %s; inbounds requiring review: %s',
                email,
                rollback_errors,
                exc_info=True,
            )
            raise RuntimeError(
                f"{operation_error}; بازگردانی پنل برای اینباندهای {rollback_errors} ناموفق بود"
            ) from operation_error
        raise RuntimeError(f"{operation_error}; تغییرات پنل بازگردانی شد") from operation_error

    for cached_order_id in list(CONFIG_LINKS_CACHE):
        cached_order = orders.get(str(cached_order_id), orders.get(cached_order_id))
        if any(cached_order is item for item in related_orders):
            CONFIG_LINKS_CACHE.pop(cached_order_id, None)
    return new_subscription_link, new_links or []


__all__ = [
    # State & Timers
    "LOGIN_TIMEOUT",
    "API_TIMEOUT",
    "COOKIE_TTL",
    "CSRF_TTL",
    "INBOUND_CACHE_TTL",
    "LOGIN_LOCK",
    "INBOUND_LOCK",
    "HTTP_SESSION",
    "CONNECTOR",
    "SENAI_COOKIE",
    "COOKIE_TIME",
    "SENAI_CSRF",
    "CSRF_TIME",
    "INBOUND_CACHE",
    "PANEL_SUB_PATH",
    "PANEL_SUB_URI",
    "PANEL_COMPUTED_SUB_BASE_URL",
    "panel_semaphore",
    "PanelRateLimiter",
    "panel_rate_limiter",
    # Sub URL helpers
    "_is_auto_sub_url",
    "get_sub_base_url",
    "ensure_sub_base_url",
    "_get_base_url",
    # Session & Auth
    "_ensure_session",
    "init_http_session",
    "close_http_session",
    "_get_cookie_from_session",
    "_do_login",
    "xui_login",
    "xui_get_csrf_token",
    "_api_request",
    # Sub Settings & Inbounds
    "xui_sync_sub_settings",
    "xui_get_inbounds",
    "get_inbound_display_names",
    "get_user_inbound",
    "filter_valid_inbounds",
    "reset_panel_rate_limits",
    # Client CRUD & Traffic
    "xui_create_client_with_inbound",
    "xui_get_client_info",
    "xui_delete_client",
    "extract_email_from_sub_link",
    "build_sub_link_from_client",
    "get_order_client_email",
    "find_email_by_sub_id",
    "xui_get_client_traffic",
    "get_client_inbounds",
    "xui_detach_inbounds",
    "xui_attach_inbounds",
    "xui_reset_client_traffic",
    "test_panel_connection",
    "get_panel_status",
    "xui_get_client_links",
    # Identity Rotation
    "_panel_success",
    "_panel_generate_uuid",
    "_panel_generate_wireguard_keypair",
    "_subscription_id_from_link",
    "_as_allowed_ips",
    "_build_panel_client_update_payload",
    "_fetch_panel_client",
    "_decode_inbound_settings",
    "_rotate_panel_client_identity",
]

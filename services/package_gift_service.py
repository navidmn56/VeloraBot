"""
services/package_gift_service.py
--------------------------------
سرویس کدهای یک‌بارمصرف امن برای دریافت مستقیم بسته (ویژه مشتریان خاص)
همراه با بررسی صحت فرمت و محدودیت نرخ تلاش کوپن.
"""

import re
import time
import hmac
import hashlib
import secrets
import asyncio
import logging
from typing import Optional, Dict, Any, Tuple, List

from database import (
    configs_pool,
    READY_PACKAGES,
    save_all,
    now_tehran_iso,
)

logger = logging.getLogger(__name__)

_GIFT_STORAGE_KEY = "package_gift_codes"
_GIFT_PREFIX = "VG-"
_CODE_VALID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_REDEEM_LOCK = asyncio.Lock()
_REDEEMING_GIFT_IDS: set[str] = set()

_FAILED_COUPON_ATTEMPTS: Dict[int, List[float]] = {}
_RATE_WINDOW_SECONDS = 60.0
_MAX_FAILED_ATTEMPTS_PER_WINDOW = 8


def validate_coupon_input(raw_text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """اعتبارسنجی سریع فرمت کد کوپن پیش از جستجو در دیتابیس.

    Returns:
        (normalized_code, error_reason)
        error_reason is None if valid, else 'empty' | 'invalid_format'.
    """
    if not raw_text or not isinstance(raw_text, str):
        return None, "empty"

    stripped = raw_text.strip()
    if not stripped:
        return None, "empty"

    # رد متن‌های چندخطی، متن‌های طولانی، یا دارای فاصله/کاراکتر غیرمجاز
    if "\n" in stripped or "\r" in stripped or len(stripped) > 64:
        return None, "invalid_format"

    if not _CODE_VALID_RE.fullmatch(stripped):
        return None, "invalid_format"

    return stripped, None


def is_coupon_rate_limited(user_id: int) -> bool:
    """بررسی محدودیت تلاش ناموفق برای جلوگیری از حدس‌زدن یا بروت‌فورس."""
    now = time.monotonic()
    recent = [
        ts for ts in _FAILED_COUPON_ATTEMPTS.get(user_id, [])
        if now - ts <= _RATE_WINDOW_SECONDS
    ]
    if recent:
        _FAILED_COUPON_ATTEMPTS[user_id] = recent
    else:
        _FAILED_COUPON_ATTEMPTS.pop(user_id, None)
    return len(recent) >= _MAX_FAILED_ATTEMPTS_PER_WINDOW


def record_failed_coupon_attempt(user_id: int) -> None:
    """ثبت یک تلاش ناموفق در پنجره زمانی فعلی."""
    now = time.monotonic()
    recent = [
        ts for ts in _FAILED_COUPON_ATTEMPTS.get(user_id, [])
        if now - ts <= _RATE_WINDOW_SECONDS
    ]
    recent.append(now)
    _FAILED_COUPON_ATTEMPTS[user_id] = recent


def hash_gift_code(raw_code: str) -> str:
    """محاسبه هش SHA-256 کد هدیه برای ذخیره امن بدون نگهداری متن خام."""
    return hashlib.sha256(raw_code.encode("utf-8")).hexdigest()


def get_package_gift_store() -> Dict[str, dict]:
    """دریافت دیکشنری کدهای یک‌بارمصرف بسته‌ها از configs_pool."""
    store = configs_pool.get(_GIFT_STORAGE_KEY)
    if not isinstance(store, dict):
        store = {}
        configs_pool[_GIFT_STORAGE_KEY] = store
    return store


def find_defined_package(category_id: int, package_id: int) -> Tuple[Optional[dict], Optional[dict]]:
    """پیدا کردن دسته‌بندی و بسته از READY_PACKAGES بدون توجه به فعال یا غیرفعال بودن آن."""
    for cat in READY_PACKAGES.get("categories", []):
        if cat.get("id") == category_id:
            for pkg in cat.get("packages", []):
                if pkg.get("id") == package_id:
                    return cat, pkg
            return cat, None
    return None, None


def resolve_category_inbound_ids(category: Optional[dict]) -> List[int]:
    """استخراج اینباندهای مرتبط با دسته‌بندی (با fallback به اینباند پیش‌فرض)."""
    inbound_ids: List[int] = []
    if isinstance(category, dict):
        raw_ids = category.get("inbound_ids") or []
        if isinstance(raw_ids, list) and raw_ids:
            inbound_ids = [i for i in raw_ids if i is not None]
        elif category.get("inbound_id") is not None:
            inbound_ids = [category.get("inbound_id")]

    if not inbound_ids:
        default_ids = configs_pool.get("default_inbound_ids", [])
        if isinstance(default_ids, list) and default_ids:
            inbound_ids = [i for i in default_ids if i is not None]
    return inbound_ids


def create_package_gift_code(
    category_id: int,
    package_id: int,
    admin_id: int,
    allowed_user_id: Optional[int] = None,
) -> Tuple[str, dict]:
    """ساخت یک کد یک‌بارمصرف امن برای بسته انتخاب‌شده."""
    category, package = find_defined_package(category_id, package_id)
    if not category or not package:
        raise ValueError("Package or category not found")

    store = get_package_gift_store()
    gift_id = secrets.token_hex(4)
    while gift_id in store:
        gift_id = secrets.token_hex(4)

    # 192 بیت آنتروپی رمزنگاری‌شده (35 کاراکتر URL-safe، غیرقابل کرک)
    raw_code = f"{_GIFT_PREFIX}{secrets.token_urlsafe(24)}"
    code_preview = f"{raw_code[:7]}...{raw_code[-4:]}"

    inbound_ids = resolve_category_inbound_ids(category)

    record = {
        "id": gift_id,
        "code_hash": hash_gift_code(raw_code),
        "code_preview": code_preview,
        "category_id": category.get("id"),
        "category_name": category.get("name", ""),
        "category_name_en": category.get("name_en", ""),
        "package_id": package.get("id"),
        "package_name": package.get("name_fa") or package.get("name") or "",
        "package_name_en": package.get("name_en") or package.get("name") or "",
        "volume": package.get("volume", 0),
        "days": package.get("days", 30),
        "ip_limit": package.get("ip_limit", 0),
        "inbound_ids": inbound_ids,
        "allowed_user_id": int(allowed_user_id) if allowed_user_id is not None else None,
        "status": "active",
        "created_at": now_tehran_iso(),
        "created_by": int(admin_id),
        "used_at": None,
        "used_by": None,
        "order_id": None,
    }
    store[gift_id] = record
    save_all()
    logger.info(
        "🎁 [package_gift] Created code %s (id=%s) for cat=%s pkg=%s lock=%s by admin=%s",
        code_preview,
        gift_id,
        category_id,
        package_id,
        allowed_user_id,
        admin_id,
    )
    return raw_code, record


def lookup_package_gift_by_code(raw_code: str) -> Optional[dict]:
    """جستجوی امن و زمان‌ثابت کد هدیه بر اساس هش SHA-256."""
    if not raw_code or not isinstance(raw_code, str):
        return None
    store = get_package_gift_store()
    if not store:
        return None

    candidate_hash = hash_gift_code(raw_code)
    matched: Optional[dict] = None
    for record in store.values():
        if not isinstance(record, dict):
            continue
        stored_hash = str(record.get("code_hash") or "")
        if stored_hash and hmac.compare_digest(stored_hash, candidate_hash):
            matched = record
    return matched


def delete_package_gift_code(gift_id: str) -> Optional[dict]:
    """حذف/ابطال کد یک‌بارمصرف بسته."""
    store = get_package_gift_store()
    removed = store.pop(gift_id, None)
    if removed is not None:
        save_all()
    return removed

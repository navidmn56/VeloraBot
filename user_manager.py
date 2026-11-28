"""User business logic, user state management, balance operations, and coupon handling."""

from strings import t
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from database import configs_pool, save_all, users, TEHRAN_TZ, now_tehran_iso
from db_storage import DATA_DIR, DB_FILES, save_json

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# Admin ID Resolution & Synchronization
# ═══════════════════════════════════════════════════════════

def _resolve_admin_id() -> int:
    try:
        from config import ADMIN_ID
        return int(ADMIN_ID)
    except (ValueError, TypeError, ImportError):
        return 0

_admin_id_cache: Optional[int] = None


def get_admin_id_int() -> int:
    """Return resolved numeric admin id."""
    global _admin_id_cache
    if _admin_id_cache is not None:
        return _admin_id_cache
    _admin_id_cache = _resolve_admin_id()
    return _admin_id_cache


def set_admin_id(admin_id: int) -> None:
    """Explicitly synchronize admin ID from caller (e.g. main.py)."""
    global _admin_id_cache, ADMIN_ID_INT
    try:
        _admin_id_cache = int(admin_id)
    except (ValueError, TypeError):
        _admin_id_cache = 0
    ADMIN_ID_INT = _admin_id_cache


ADMIN_ID_INT: int = get_admin_id_int()

# ═══════════════════════════════════════════════════════════
# Shared In-Memory State & Coupons Collections
# ═══════════════════════════════════════════════════════════

from utils.states import FSMStateManager, UserStateProxy

user_states: FSMStateManager = FSMStateManager()
logger.info("user_states FSM manager initialized")

from core.save_scheduler import schedule_save, schedule_file_save

COUPONS_FILE: str = os.path.join(DATA_DIR, "coupons.json")
COUPONS: Dict[str, dict] = {}


def load_coupons() -> dict:
    """Load coupons from disk into memory preserving dictionary reference."""
    try:
        if os.path.exists(COUPONS_FILE):
            with open(COUPONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    COUPONS.clear()
                    COUPONS.update(data)
                    return COUPONS
        COUPONS.clear()
        return COUPONS
    except Exception as e:
        logger.error(f"Error loading coupons: {e}")
        return COUPONS


def save_coupons(coupons: dict = None) -> bool:
    """Save coupons to disk."""
    if coupons is None:
        coupons = COUPONS
    try:
        with open(COUPONS_FILE, "w", encoding="utf-8") as f:
            json.dump(coupons, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving coupons: {e}")
        return False


# Initial load of coupons
load_coupons()


def is_coupon_valid_for_user(coupon_code: str, user_id: int) -> tuple:
    """
    بررسی اعتبار کوپن برای کاربر
    Returns:
        (is_valid: bool, reason: str)
    """
    if not coupon_code:
        return False, "کوپن خالی است"
    
    coupon = COUPONS.get(coupon_code)
    if not coupon:
        return False, "کوپن در دیتابیس نیست"
    if coupon.get('status') != 'active':
        return False, f"وضعیت: {coupon.get('status')}"
    expiry_date = coupon.get('expiry_date')
    if expiry_date:
        try:
            expiry = datetime.fromisoformat(expiry_date)
            ref_now = datetime.now(expiry.tzinfo) if expiry.tzinfo is not None else datetime.now(TEHRAN_TZ).replace(tzinfo=None)
            if expiry < ref_now:
                return False, "منقضی شده"
        except Exception:
            pass
    
    coupon_type = coupon.get('coupon_type', 'normal')
    
    if coupon_type == 'admin_special':
        locked_user_id = coupon.get('locked_user_id')
        if locked_user_id and locked_user_id != user_id:
            return False, f"قفل شده برای کاربر {locked_user_id}"
        user_usage = coupon.get('user_usage', {})
        user_used_count = user_usage.get(str(user_id), 0)
        max_usage = coupon.get('usage_limit', 1)
        
        if user_used_count >= max_usage:
            return False, f"به حداکثر رسیده ({user_used_count}/{max_usage})"
        
        return True, f"معتبر ({user_used_count}/{max_usage})"
    else:
        if user_id in coupon.get('used_by', []):
            return False, "قبلاً استفاده شده"
        
        return True, "معتبر"


def add_coupon_fields_to_user(user_id: int):
    """اطمینان از وجود فیلدهای کوپن در دیتابیس کاربر"""
    uid = str(user_id)
    if uid in users:
        modified = False
        
        if 'coupon_code' not in users[uid]:
            users[uid]['coupon_code'] = None
            modified = True
        
        if 'coupon_discount' not in users[uid]:
            users[uid]['coupon_discount'] = 0
            modified = True
        
        if 'coupon_applied' not in users[uid]:
            users[uid]['coupon_applied'] = False
            modified = True
        
        if modified:
            try:
                schedule_file_save('users', delay=2.0)
                logger.info(f"✅ Coupon fields added to user {user_id} added")
            except Exception as e:
                logger.error(f"❌ Error saving coupon fields: {e}")


# ═══════════════════════════════════════════════════════════
# User Business Logic & Creation
# ═══════════════════════════════════════════════════════════

def get_user_safe(user_id: Union[int, str, None]) -> Optional[dict]:
    """
    دریافت ایمن اطلاعات کاربر از دیتابیس بدون ایجاد خودکار رکورد جدید در صورت عدم وجود.
    کلید را به صورت رشته در دیکشنری users جستجو می‌کند.
    """
    if user_id is None:
        return None
    return users.get(str(user_id))


def get_user(user_id: int, username: str = None) -> dict:
    """دریافت اطلاعات کاربر یا ایجاد کاربر جدید با وضعیت‌های مختلف و بررسی خودکار کوپن"""
    uid = str(user_id)
    admin_id_val = get_admin_id_int()
    is_admin = (admin_id_val != 0 and user_id == admin_id_val)
    
    if uid not in users:
        user_name = username or f"کاربر_{user_id}"
        
        logger.info(f"👤 creating new user: {user_id} - name: {user_name}")
        manual_approval = configs_pool.get('manual_approval_settings', {})
        approval_enabled = manual_approval.get('enabled', False)
        
        users[uid] = {
            'id': user_id,
            'name': user_name,
            'username': username or '',
            'telegram_username': username or '',
            'balance': 0,
            'total_spent': 0,
            'total_purchases': 0,
            'last_purchase_date': None,
            'volume': 1,
            'days': 30,
            'lang': 'fa',
            'is_active': True,
            'verified': False,
            'has_purchased': False,
            'referred_by': None,
            'join_date': datetime.now(TEHRAN_TZ).strftime('%Y/%m/%d'),
            'created_at': now_tehran_iso(),
            'updated_at': now_tehran_iso(),
            'notes': '',
            'coupon_code': None,
            'coupon_discount': 0,
            'coupon_applied': False,
            'approved_by_admin': True if is_admin else False,
            'approved_date': now_tehran_iso() if is_admin else None,
            'requested_approval': False,
            'registration_status': 'approved' if is_admin else 'pending'
        }
        
        schedule_file_save('users', delay=1.0)
        
        if is_admin:
            logger.info(f"👑 Admin user {user_id} created - status: approved")
        else:
            logger.info(f"✅ New user {user_id} created - status: pending")
        
        return users[uid]
    
    user = users[uid]
    modified = False
    
    # ✅ به‌روزرسانی username
    if username and user.get('telegram_username') != username:
        user['telegram_username'] = username
        user['username'] = username
        modified = True
    
    # فیلدهای ضروری
    required_fields = {
        'name': f"کاربر_{user_id}",
        'username': '',
        'telegram_username': '',
        'balance': 0,
        'total_spent': 0,
        'total_purchases': 0,
        'last_purchase_date': None,
        'volume': 1,
        'days': 30,
        'lang': 'fa',
        'is_active': True,
        'verified': False,
        'has_purchased': False,
        'referred_by': None,
        'join_date': datetime.now(TEHRAN_TZ).strftime('%Y/%m/%d'),
        'created_at': now_tehran_iso(),
        'updated_at': now_tehran_iso(),
        'notes': '',
        'coupon_code': None,
        'coupon_discount': 0,
        'coupon_applied': False,
        'approved_by_admin': False,
        'approved_date': None,
        'requested_approval': False,
        'registration_status': 'pending'
    }
    
    for key, default_value in required_fields.items():
        if key not in user:
            user[key] = default_value
            modified = True
    
    # ✅ تایید خودکار ادمین
    if admin_id_val != 0 and user_id == admin_id_val:
        if not user.get('approved_by_admin', False):
            user['approved_by_admin'] = True
            user['approved_date'] = now_tehran_iso()
            user['registration_status'] = 'approved'
            modified = True
            logger.info(f"👑 Admin user {user_id} approved")
    
    # ✅ تایید خودکار کاربران دارای خرید
    if user.get('has_purchased', False) and not user.get('approved_by_admin', False):
        user['approved_by_admin'] = True
        user['approved_date'] = now_tehran_iso()
        user['registration_status'] = 'approved'
        modified = True
        logger.info(f"✅ user {user_id}auto-approved due to existing purchase")
    
    # ✅ تایید خودکار وقتی تایید دستی غیرفعال است
    if not user.get('approved_by_admin', False) and (admin_id_val == 0 or user_id != admin_id_val):
        manual_approval = configs_pool.get('manual_approval_settings', {})
        if not manual_approval.get('enabled', False):
            user['approved_by_admin'] = True
            user['approved_date'] = now_tehran_iso()
            user['registration_status'] = 'approved'
            modified = True
            logger.info(f"✅ user {user_id} automatically approved because manual approval is disabled")
    
    # ✅✅✅ بررسی خودکار کوپن - مهمترین بخش!
    coupon_code = user.get('coupon_code')
    coupon_discount = user.get('coupon_discount', 0)
    coupon_applied = user.get('coupon_applied', False)
    
    if coupon_code and coupon_applied:
        # بررسی اعتبار کوپن
        coupon_valid = True
        invalid_reason = ""
        
        # ✅ 1. بررسی وجود در COUPONS
        if coupon_code not in COUPONS:
            coupon_valid = False
            invalid_reason = "در لیست کوپن‌ها نیست"
            logger.warning(f"⚠️ Coupon {coupon_code} is not in the coupon list - removing from user {user_id} will be removed")
        else:
            coupon = COUPONS[coupon_code]
            
            # ✅ 2. بررسی وضعیت
            if coupon.get('status') != 'active':
                coupon_valid = False
                invalid_reason = f"وضعیت: {coupon.get('status')}"
                logger.warning(f"⚠️ Coupon {coupon_code} is inactive ({coupon.get('status')}) - from user {user_id} will be removed")
            
            # ✅ 3. بررسی تاریخ انقضا
            if coupon_valid:
                expiry_date = coupon.get('expiry_date')
                if expiry_date:
                    try:
                        expiry = datetime.fromisoformat(expiry_date)
                        ref_now = datetime.now(expiry.tzinfo) if expiry.tzinfo is not None else datetime.now(TEHRAN_TZ).replace(tzinfo=None)
                        if expiry < ref_now:
                            coupon_valid = False
                            invalid_reason = "منقضی شده"
                            coupon['status'] = 'expired'
                            save_coupons(COUPONS)
                            logger.warning(f"⚠️ Coupon {coupon_code} expired - from user {user_id} will be removed")
                    except ValueError:
                        logger.warning(f"⚠️ Invalid date for coupon {coupon_code}: {expiry_date}")
            
            # ✅ 4. بررسی تعداد استفاده
            if coupon_valid:
                usage_limit = coupon.get('usage_limit', 0)
                used_count = coupon.get('used_count', 0)
                
                if usage_limit > 0 and used_count >= usage_limit:
                    coupon_valid = False
                    invalid_reason = f"ظرفیت پر شده ({used_count}/{usage_limit})"
                    coupon['status'] = 'used'
                    save_coupons(COUPONS)
                    logger.warning(f"⚠️ Coupon {coupon_code} reached the maximum usage limit - user {user_id} will be removed")
            if coupon_valid:
                coupon_type = coupon.get('coupon_type', 'normal')
                
                if coupon_type == 'admin_special':
                    user_usage = coupon.get('user_usage', {})
                    user_used_count = user_usage.get(str(user_id), 0)
                    max_usage = coupon.get('usage_limit', 1)
                    
                    if user_used_count >= max_usage:
                        coupon_valid = False
                        invalid_reason = f"به حداکثر استفاده رسیده ({user_used_count}/{max_usage})"
                        logger.warning(f"⚠️ user {user_id} reached the maximum uses for admin coupon {coupon_code} reached the limit - will be deleted")
                    else:
                        logger.info(f"✅ Admin coupon {coupon_code} is still valid ({user_used_count}/{max_usage})")
                else:
                    if user_id in coupon.get('used_by', []):
                        coupon_valid = False
                        invalid_reason = "قبلاً توسط کاربر استفاده شده"
                        logger.warning(f"⚠️ user {user_id} has already used coupon {coupon_code} uses - will be deleted")        
        if coupon_valid:
            if user_id not in user_states:
                user_states[user_id] = {}
            if user_states[user_id].get('coupon_code') != coupon_code or \
               user_states[user_id].get('coupon_discount') != coupon_discount or \
               not user_states[user_id].get('coupon_applied'):
                user_states[user_id]['coupon_code'] = coupon_code
                user_states[user_id]['coupon_discount'] = coupon_discount
                user_states[user_id]['coupon_applied'] = True
                logger.info(f"🏷️ coupon {coupon_code} (discount: {coupon_discount}%) from the database into user_states for user {user_id} loaded")
        else:
            user['coupon_code'] = None
            user['coupon_discount'] = 0
            user['coupon_applied'] = False
            modified = True
            if user_id in user_states:
                user_states[user_id].pop('coupon_code', None)
                user_states[user_id].pop('coupon_discount', None)
                user_states[user_id].pop('coupon_applied', None)
            
            logger.info(f"🗑️ coupon {coupon_code} from user {user_id} removed - reason: {invalid_reason}")
    else:
        if user_id in user_states:
            has_coupon_in_state = (
                user_states[user_id].get('coupon_code') or 
                user_states[user_id].get('coupon_applied')
            )
            if has_coupon_in_state:
                user_states[user_id].pop('coupon_code', None)
                user_states[user_id].pop('coupon_discount', None)
                user_states[user_id].pop('coupon_applied', None)
                logger.debug(f"Coupon from user {user_id} cleared (not in the database)")
    if modified:
        user['updated_at'] = now_tehran_iso()
        schedule_file_save('users', delay=2.0)
        logger.debug(f"💾 user changes {user_id} saved")
    
    return user


def can_user_purchase(user_id: int) -> tuple:
    """
    بررسی اینکه کاربر مجاز به خرید و مشاهده موجودی است یا خیر
    
    Returns:
        (can_purchase: bool, message: str)
    """
    manual_approval = configs_pool.get('manual_approval_settings', {})
    if not manual_approval.get('enabled', False):
        return True, None
    
    user = get_user(user_id)
    if user.get('has_purchased', False):
        return True, None
    if user.get('approved_by_admin', False):
        return True, None
    lang = user.get('lang', 'fa')
    msg = t('your_account_is_pending_admi_49c4fd5521', lang)
    
    return False, msg


# ═══════════════════════════════════════════════════════════
# User Coupon Operations
# ═══════════════════════════════════════════════════════════

def save_coupon_to_user_db(user_id: int) -> bool:
    """ذخیره کوپن در دیتابیس کاربر
    
    Args:
        user_id: شناسه کاربر
        
    Returns:
        bool: True اگر موفق بود، False اگر خطا داشت
    """
    uid = str(user_id)
    
    # ✅ بررسی وجود کاربر
    if uid not in users:
        logger.warning(f"⚠️ user {user_id}not found in database - coupon not saved")
        return False
    
    # ✅ دریافت اطلاعات کوپن از user_states
    user_state = user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_discount = user_state.get('coupon_discount', 0)
    coupon_applied = user_state.get('coupon_applied', False)
    
    if not coupon_code:
        logger.debug("No active coupon in user state for user %s; nothing to save.", user_id)
        return False
    
    # ✅ اطمینان از وجود فیلدهای کوپن
    add_coupon_fields_to_user(user_id)
    
    # ✅ ذخیره در دیتابیس
    users[uid]['coupon_code'] = coupon_code
    users[uid]['coupon_discount'] = coupon_discount
    users[uid]['coupon_applied'] = coupon_applied
    
    try:
        schedule_file_save('users', delay=1.0)
        logger.info(f"✅ coupon {coupon_code} saved in user database {user_id}saved (discount: {coupon_discount}%)")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving coupon to the database: {e}")
        return False


def load_coupon_from_user_db(user_id: int) -> dict:
    """بازیابی کوپن از دیتابیس کاربر"""
    result = {
        'coupon_code': None,
        'coupon_discount': 0,
        'coupon_applied': False
    }
    
    try:
        uid = str(user_id)
        if uid not in users:
            return result
        
        user = users[uid]
        coupon_code = user.get('coupon_code')
        coupon_applied = user.get('coupon_applied', False)
        coupon_discount = user.get('coupon_discount', 0)
        
        if coupon_applied and coupon_code:
            is_valid, reason = is_coupon_valid_for_user(coupon_code, user_id)
            if is_valid:
                logger.info(f"📁 [load_coupon_from_user_db] Coupon {coupon_code} restored from the user\'s database - {reason}")
                return {
                    'coupon_code': coupon_code,
                    'coupon_discount': coupon_discount,
                    'coupon_applied': True
                }
            else:
                logger.warning(f"⚠️ [load_coupon_from_user_db] Coupon {coupon_code} invalid: {reason}")
                users[uid]['coupon_code'] = None
                users[uid]['coupon_discount'] = 0
                users[uid]['coupon_applied'] = False
                schedule_file_save('users', delay=2.0)
            
                
    except Exception as e:
        logger.error(f"❌ [load_coupon_from_user_db] Error: {e}")
    
    return result


def clear_coupon_from_user_db(user_id: int, force: bool = False) -> bool:
    """پاک کردن کوپن از دیتابیس کاربر با بررسی‌های امنیتی
    
    Args:
        user_id: شناسه کاربر
        force: اگر True باشد، بدون بررسی وضعیت کوپن پاک می‌شود
        
    Returns:
        bool: True اگر کوپن پاک شد، False اگر پاک نشد
    """
    uid = str(user_id)
    
    # ✅ بررسی وجود کاربر
    if uid not in users:
        logger.warning(f"⚠️ user {user_id}not found in database")
        return False
    
    # ✅ بررسی اینکه آیا اصلاً کوپنی دارد
    current_coupon = users[uid].get('coupon_code')
    if not current_coupon and not users[uid].get('coupon_applied'):
        logger.debug(f"User {user_id}has no coupon")
        return False
    
    # ✅ بررسی وضعیت کوپن (اگر force=False)
    if not force and current_coupon:
        if current_coupon in COUPONS:
            coupon = COUPONS[current_coupon]
            coupon_status = coupon.get('status', 'inactive')
            expiry = coupon.get('expiry_date')
            
            # بررسی فعال بودن
            if coupon_status == 'active':
                # بررسی تاریخ انقضا
                if expiry:
                    try:
                        expiry_date = datetime.fromisoformat(expiry)
                        ref_now = datetime.now(expiry_date.tzinfo) if expiry_date.tzinfo is not None else datetime.now(TEHRAN_TZ).replace(tzinfo=None)
                        if expiry_date > ref_now:
                            logger.info(f"⏳ Coupon {current_coupon} is still active (until {expiry}) - not deleted")
                            return False
                        else:
                            logger.info(f"⌛ Coupon {current_coupon} expired - deleting")
                    except ValueError:
                        logger.warning(f"⚠️ Invalid date for coupon {current_coupon}: {expiry}")
                else:
                    logger.info(f"⏳ Coupon {current_coupon} is active (no expiration date) - not deleted")
                    return False
            else:
                logger.info(f"🚫 Coupon {current_coupon} is inactive - clearing it")
        else:
            logger.warning(f"⚠️ Coupon {current_coupon} is not in the coupon list - removing")
    
    # ✅ ذخیره مقادیر قبلی برای لاگ
    old_coupon = users[uid].get('coupon_code')
    old_discount = users[uid].get('coupon_discount', 0)
    
    # ✅ پاک کردن کوپن
    users[uid]['coupon_code'] = None
    users[uid]['coupon_discount'] = 0
    users[uid]['coupon_applied'] = False
    
    # ✅ پاک کردن از user_states نیز
    if user_id in user_states:
        user_states[user_id].pop('coupon_code', None)
        user_states[user_id].pop('coupon_discount', None)
        user_states[user_id].pop('coupon_applied', None)
    
    # ✅ ذخیره‌سازی
    try:
        schedule_file_save('users', delay=1.0)
        logger.info(f"✅ user coupon {user_id}cleared:")
        logger.info(f"  - previous code: {old_coupon}")
        logger.info(f"  - previous discount: {old_discount}%")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving after removing coupon: {e}")
        return False


def fully_remove_coupon_from_user(user_id: int) -> bool:
    """حذف کامل کوپن از وضعیت کاربر و دیتابیس
    
    Args:
        user_id: شناسه کاربر
        
    Returns:
        bool: True اگر موفق بود، False اگر خطا داشت
    """
    uid = str(user_id)
    removed = False
    
    # ✅ 1. حذف از user_states
    if user_id in user_states:
        user_states[user_id].pop('coupon_code', None)
        user_states[user_id].pop('coupon_discount', None)
        user_states[user_id].pop('coupon_applied', None)
        logger.info(f"🏷️ Coupon from user_states for user {user_id} deleted")
        removed = True
    
    # ✅ 2. حذف از دیتابیس users
    if uid in users:
        old_coupon = users[uid].get('coupon_code')
        old_discount = users[uid].get('coupon_discount', 0)
        
        users[uid]['coupon_code'] = None
        users[uid]['coupon_discount'] = 0
        users[uid]['coupon_applied'] = False
        
        try:
            schedule_file_save('users', delay=1.0)
            logger.info(f"🏷️ Coupon from user database {user_id} deleted: {old_coupon} (discount: {old_discount}%)")
            removed = True
        except Exception as e:
            logger.error(f"❌ Error saving after coupon deletion: {e}")
            return False
    
    if not removed:
        logger.debug(f"User {user_id} had no coupon to remove")
    
    return removed


def consume_coupon(user_id: int) -> bool:
    """مصرف کوپن - با پشتیبانی از کوپن ادمین"""
    uid = str(user_id)
    
    coupon_code = None
    if user_id in user_states:
        coupon_code = user_states[user_id].get('coupon_code')
    
    if not coupon_code and uid in users:
        coupon_code = users[uid].get('coupon_code')
    
    if not coupon_code:
        return False
    
    coupon = COUPONS.get(coupon_code)
    if not coupon:
        logger.warning(f"⚠️ [consume_coupon] Coupon {coupon_code}not found in database")
        fully_remove_coupon_from_user(user_id)
        return False
    
    coupon_type = coupon.get('coupon_type', 'normal')
    
    # ✅✅✅ کوپن ادمین - فقط برای کاربر قفل شده
    if coupon_type == 'admin_special':
        locked_user_id = coupon.get('locked_user_id')
        
        if locked_user_id != user_id:
            logger.warning(f"⚠️ [consume_coupon] User {user_id} cannot use admin coupon {coupon_code} use it")
            fully_remove_coupon_from_user(user_id)
            return False
        
        # ✅ به‌روزرسانی شمارش استفاده کاربر
        user_usage = coupon.get('user_usage', {})
        user_usage[str(user_id)] = user_usage.get(str(user_id), 0) + 1
        coupon['user_usage'] = user_usage
        
        # ✅ به‌روزرسانی used_by
        used_by = coupon.get('used_by', [])
        if user_id not in used_by:
            used_by.append(user_id)
        coupon['used_by'] = used_by
        
        max_usage = coupon.get('usage_limit', 1)
        current_usage = user_usage[str(user_id)]
        
        save_coupons(COUPONS)
        
        # ✅✅✅✅✅ اصلاح اصلی: فقط اگر به حداکثر رسید، پاک کن
        if current_usage >= max_usage:
            coupon['status'] = 'used'
            save_coupons(COUPONS)
            logger.info(f"🔴 Admin coupon {coupon_code} reached its limit ({current_usage}/{max_usage}) - will be deleted")
            fully_remove_coupon_from_user(user_id)
        else:
            # ✅✅✅ کوپن هنوز اعتبار داره - فقط از user_states نگهدار، از دیتابیس پاک نکن
            logger.info(f"✅ Admin coupon {coupon_code} used ({current_usage}/{max_usage}) - still valid")
            
            # ✅ دوباره در user_states ذخیره کن (چون fully_remove صدا زده نشد، ولی مطمئن شو)
            if user_id not in user_states:
                user_states[user_id] = {}
            
            user_states[user_id]['coupon_code'] = coupon_code
            user_states[user_id]['coupon_applied'] = True
            user_states[user_id]['coupon_discount'] = coupon.get('discount', 0)
            
            # ✅ دیتابیس کاربر هم نگهدار
            if uid in users:
                users[uid]['coupon_code'] = coupon_code
                users[uid]['coupon_discount'] = coupon.get('discount', 0)
                users[uid]['coupon_applied'] = True
                schedule_file_save('users', delay=1.0)
        
        logger.info(f"✅ [consume_coupon] Admin coupon {coupon_code} - user: {user_id} ({current_usage}/{max_usage})")
        return True
    
    # ✅ کوپن معمولی
    if user_id in coupon.get('used_by', []):
        logger.warning(f"⚠️ [consume_coupon] User {user_id} has already used coupon {coupon_code}")
        fully_remove_coupon_from_user(user_id)
        return False
    
    used_by = coupon.get('used_by', [])
    used_by.append(user_id)
    coupon['used_by'] = used_by
    coupon['used_count'] = coupon.get('used_count', 0) + 1
    
    usage_limit = coupon.get('usage_limit', 0)
    if usage_limit > 0 and coupon['used_count'] >= usage_limit:
        coupon['status'] = 'used'
    
    save_coupons(COUPONS)
    
    # ✅ کوپن معمولی: همیشه پاک کن (چون هر کاربر فقط یک بار می‌تونه استفاده کنه)
    fully_remove_coupon_from_user(user_id)
    
    logger.info(f"✅ [consume_coupon] regular coupon {coupon_code} consumed - user: {user_id}")
    return True


def release_coupon_on_cancel(user_id: int) -> bool:
    """
    آزادسازی کوپن در صورت لغو سفارش (قبل از مصرف)
    کوپن باقی می‌ماند و کاربر می‌تواند دوباره استفاده کند
    """
    user_state = user_states.get(user_id, {})
    
    if not user_state.get('coupon_applied'):
        return False
    
    code = user_state.get('coupon_code')
    if not code or code not in COUPONS:
        return False
    
    coupon = COUPONS[code]
    coupon_type = coupon.get('coupon_type', 'normal')
    
    # ✅✅✅ بررسی بر اساس نوع کوپن
    if coupon_type == 'admin_special':
        # برای کوپن ادمین: بررسی user_usage
        user_usage = coupon.get('user_usage', {})
        user_used_count = user_usage.get(str(user_id), 0)
        max_usage = coupon.get('usage_limit', 1)
        
        if user_used_count >= max_usage:
            logger.info(f"🏷️ Admin coupon {code} has reached its limit ({user_used_count}/{max_usage}), cannot be released")
            return False
    else:
        # برای کوپن معمولی: بررسی used_by
        if user_id in coupon.get('used_by', []):
            clear_coupon_from_user_db(user_id)
            logger.info(f"🏷️ coupon {code} already used by user {user_id} was used and cannot be released")
            return False
    
    # بررسی وضعیت
    if coupon.get('status') != 'active':
        logger.info(f"🏷️ coupon {code} is no longer active (status: {coupon.get('status')})")
        return False
    
    # آزادسازی
    user_states[user_id]['coupon_applied'] = True
    user_states[user_id]['coupon_code'] = code
    user_states[user_id]['coupon_discount'] = coupon.get('discount', 0)
    
    logger.info(f"🏷️ coupon {code} for user {user_id} released (order cancelled before consumption)")
    return True


def debug_coupon_state(user_id: int, location: str):
    """دیباگ وضعیت کوپن در نقاط مختلف"""
    user_state = user_states.get(user_id, {})
    coupon_code = user_state.get('coupon_code')
    coupon_applied = user_state.get('coupon_applied', False)
    coupon_discount = user_state.get('coupon_discount', 0)
    
    logger.info(f"🔍 [{location}] complete user_states: {user_state}")
    logger.info(f"🔍 [{location}] coupon: code={coupon_code}, applied={coupon_applied}, discount={coupon_discount}")
    
    if coupon_code and coupon_code in COUPONS:
        coupon = COUPONS[coupon_code]
        logger.info(f"🔍 [{location}] Coupon in database: status={coupon.get('status')}, used_by={coupon.get('used_by', [])}")


def get_coupon_discount_for_category(coupon: Optional[dict], category_id=None) -> int:
    """Return effective discount percentage (0-100) for a coupon on a specific category."""
    if not isinstance(coupon, dict):
        return 0
    try:
        base_discount = max(0, min(100, int(coupon.get('discount', 0) or 0)))
    except (TypeError, ValueError):
        base_discount = 0
    if category_id is not None:
        cat_discounts = coupon.get('category_discounts') or {}
        if isinstance(cat_discounts, dict):
            cat_key = str(category_id)
            if cat_key in cat_discounts:
                try:
                    return max(0, min(100, int(cat_discounts[cat_key])))
                except (TypeError, ValueError):
                    pass
    return base_discount


def format_coupon_category_discounts_lines(
    coupon: Optional[dict],
    categories: Optional[List[dict]],
    lang: str = "fa",
) -> str:
    """Format per-category discount overrides configured on a coupon."""
    if not isinstance(coupon, dict):
        return ""
    cat_discounts = coupon.get('category_discounts') or {}
    if not isinstance(cat_discounts, dict) or not cat_discounts:
        return ""
    cat_by_id = {str(c.get('id')): c for c in (categories or []) if isinstance(c, dict)}
    lines = []
    for cid_str, pct in cat_discounts.items():
        cat = cat_by_id.get(str(cid_str))
        if cat:
            icon = cat.get('icon', '📦')
            name = (cat.get('name') if lang == "fa" else (cat.get('name_en') or cat.get('name'))) or f"#{cid_str}"
            label = f"{icon} {name}"
        else:
            label = f"📦 دسته #{cid_str}" if lang == "fa" else f"📦 Category #{cid_str}"
        lines.append(f"  • {label}: <b>{pct}%</b>")
    return "\n".join(lines)


def resolve_category_package_discount(
    user_id: int,
    category: Optional[dict],
    user_state: Optional[dict] = None,
) -> dict:
    """
    Resolve effective discount and banner source for a user purchasing from `category`.

    Precedence:
    1. Valid active `admin_special` coupon overrides category discounts completely.
    2. Otherwise, category `discount_percent > 0` applies and blocks regular coupons.
    3. Otherwise, valid active regular coupon applies (using per-category override or base %).
    """
    state = user_state if isinstance(user_state, dict) else user_states.get(user_id, {})
    cat_id = category.get('id') if isinstance(category, dict) else None
    try:
        cat_discount = max(0, min(99, int((category or {}).get('discount_percent') or 0)))
    except (TypeError, ValueError):
        cat_discount = 0

    coupon_code = state.get('coupon_code')
    coupon_applied = bool(state.get('coupon_applied', False))

    if not coupon_applied or not coupon_code:
        loaded = load_coupon_from_user_db(user_id)
        if loaded.get('coupon_applied') and loaded.get('coupon_code'):
            coupon_code = loaded.get('coupon_code')
            coupon_applied = True
            if user_id not in user_states:
                user_states[user_id] = {}
            user_states[user_id]['coupon_code'] = coupon_code
            user_states[user_id]['coupon_discount'] = loaded.get('coupon_discount', 0)
            user_states[user_id]['coupon_applied'] = True

    coupon_valid = False
    coupon_obj = None
    coupon_type = None
    coupon_effective_discount = 0

    if coupon_applied and coupon_code:
        is_valid, _reason = is_coupon_valid_for_user(coupon_code, user_id)
        if is_valid:
            coupon_obj = COUPONS.get(coupon_code)
            if coupon_obj:
                coupon_valid = True
                coupon_type = coupon_obj.get('coupon_type', 'normal')
                coupon_effective_discount = get_coupon_discount_for_category(coupon_obj, cat_id)
        else:
            if user_id in user_states:
                user_states[user_id].pop('coupon_code', None)
                user_states[user_id].pop('coupon_discount', None)
                user_states[user_id].pop('coupon_applied', None)
            clear_coupon_from_user_db(user_id)
            coupon_code = None

    if coupon_valid and coupon_type == 'admin_special':
        return {
            'discount_percent': coupon_effective_discount,
            'discount_source': 'coupon' if coupon_effective_discount > 0 else 'none',
            'banner_mode': 'coupon',
            'coupon_valid': True,
            'coupon_code': coupon_code,
            'coupon_type': 'admin_special',
            'coupon_effective_discount': coupon_effective_discount,
            'category_discount': cat_discount,
            'is_admin_coupon': True,
        }

    if cat_discount > 0:
        return {
            'discount_percent': cat_discount,
            'discount_source': 'category',
            'banner_mode': 'category',
            'coupon_valid': coupon_valid,
            'coupon_code': coupon_code if coupon_valid else None,
            'coupon_type': coupon_type if coupon_valid else None,
            'coupon_effective_discount': coupon_effective_discount,
            'category_discount': cat_discount,
            'is_admin_coupon': False,
        }

    if coupon_valid:
        return {
            'discount_percent': coupon_effective_discount,
            'discount_source': 'coupon' if coupon_effective_discount > 0 else 'none',
            'banner_mode': 'coupon',
            'coupon_valid': True,
            'coupon_code': coupon_code,
            'coupon_type': coupon_type or 'normal',
            'coupon_effective_discount': coupon_effective_discount,
            'category_discount': 0,
            'is_admin_coupon': False,
        }

    return {
        'discount_percent': 0,
        'discount_source': 'none',
        'banner_mode': 'none',
        'coupon_valid': False,
        'coupon_code': None,
        'coupon_type': None,
        'coupon_effective_discount': 0,
        'category_discount': 0,
        'is_admin_coupon': False,
    }


# ═══════════════════════════════════════════════════════════
# User Updates, Purchases & Balance
# ═══════════════════════════════════════════════════════════

def update_user(user_id: int, key: str, value):
    """بروزرسانی یک فیلد از کاربر"""
    uid = str(user_id)
    if uid in users:
        old_value = users[uid].get(key)
        users[uid][key] = value
        users[uid]['updated_at'] = now_tehran_iso()
        logger.debug(f"📝 user {user_id}: {key} from {old_value} to {value}")
        schedule_file_save('users', delay=1.0)
    else:
        logger.warning(f"⚠️ user {user_id}not found to update")


def record_purchase(user_id: int, amount: int):
    """ثبت خرید کاربر"""
    uid = str(user_id)
    if uid in users:
        users[uid]['total_purchases'] = users[uid].get('total_purchases', 0) + 1
        users[uid]['total_spent'] = users[uid].get('total_spent', 0) + amount
        users[uid]['last_purchase_date'] = datetime.now(TEHRAN_TZ).strftime('%Y/%m/%d %H:%M:%S')
        users[uid]['has_purchased'] = True
        users[uid]['updated_at'] = now_tehran_iso()
        schedule_file_save('users', delay=0.5)
        logger.info(f"🛒 user purchase {user_id}: {amount}tomans")


def add_balance(user_id: int, amount: int) -> int:
    """افزایش موجودی کاربر"""
    user = get_user(user_id)
    old_balance = user.get('balance', 0)
    user['balance'] = old_balance + amount
    user['updated_at'] = now_tehran_iso()
    schedule_file_save('users', delay=0.5)
    logger.info(f"💰 user {user_id}: {old_balance} + {amount} = {user['balance']}")
    return user['balance']


def reduce_balance(user_id: int, amount: int) -> int:
    """کاهش موجودی کاربر (بررسی میشود که موجودی کافی باشد)"""
    user = get_user(user_id)
    old_balance = user['balance']
    
    if amount > old_balance:
        amount = old_balance  # نمیتوان بیشتر از موجودی کم کرد
    
    user['balance'] -= amount
    logger.info(f"user balance decreased {user_id}: {old_balance} - {amount} = {user['balance']}")
    schedule_save(0.5)
    return user['balance']


def reset_balance(user_id: int) -> int:
    """صفر کردن کامل موجودی کاربر"""
    user = get_user(user_id)
    old_balance = user['balance']
    user['balance'] = 0
    logger.info(f"user balance reached zero {user_id}: {old_balance} -> 0")
    schedule_save(0.5)
    return 0


def calculate_price(volume: int, days: int, user_id: int = None) -> int:
    """محاسبه قیمت با اعمال تخفیف"""
    settings = configs_pool.get('price_settings', {})
    base = settings.get('base_price', 20000)
    per_gb = settings.get('per_gb_price', 20000)
    per_15days = settings.get('per_15days_price', 5000)
    
    extra_volume = max(0, volume - 1) * per_gb
    extra_days = max(0, days - 30)
    extra_price = ((extra_days + 14) // 15) * per_15days
    
    total = base + extra_volume + extra_price
    if user_id:
        user_state = user_states.get(user_id, {})
        if user_state.get('coupon_applied'):
            discount = user_state.get('coupon_discount', 0)
            if discount > 0:
                total = total - (total * discount // 100)
    
    logger.debug(f"💰 calculating price: {volume}GB/{days}day = {total}tomans")
    return total

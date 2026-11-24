"""Shared in-memory database repository, persistence operations, and collections."""

import json
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Callable, Dict, List, Optional, Set

from db_storage import DATA_DIR, DB_FILES, load_json, save_json

logger = logging.getLogger(__name__)

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def now_tehran() -> datetime:
    """Return current datetime in Asia/Tehran timezone."""
    return datetime.now(TEHRAN_TZ)


def now_tehran_iso() -> str:
    """Return ISO formatted string of current Asia/Tehran time."""
    return datetime.now(TEHRAN_TZ).isoformat()

# ═══════════════════════════════════════════════════════════
# Shared In-Memory Collections (Fixed references across runtime)
# ═══════════════════════════════════════════════════════════

users: Dict[str, dict] = {}
orders: Dict[str, dict] = {}
referrals: Dict[str, dict] = {}
configs_pool: Dict[str, Any] = {}
feedbacks: Dict[str, dict] = {}
chats: Dict[str, dict] = {}
BLACKLIST: Set[int] = set()

USER_TEST_USAGE: Dict[str, Any] = {}
TEST_SERVICE_STATUS: Dict[str, Any] = {
    'enabled': False,
    'volume': 0,
    'volume_mb': 1024,
    'days': 3,
    'max_tests': 1,
    'inbound_ids': [],
    'ip_limit': 0,
    'message': '🎁 یک سرویس تست {volume} / {days} روز برای شما فعال شد!',
    'last_updated': now_tehran_iso(),
}

SHOP_STATUS: Dict[str, Any] = {
    'open': True,
    'message': 'فروش به دلیل بروزرسانی موقتاً بسته شده است.',
    'last_updated': now_tehran_iso(),
}

READY_PACKAGES: Dict[str, Any] = {
    'enabled': True,
    'restrict_extend_to_same_category': False,
    'categories': [
        {
            'id': 1,
            'name': 'کانفیگ مخصوص جنگ',
            'name_en': 'War Config',
            'icon': '⚔️',
            'description': 'کانفیگ‌های بهینه شده برای دور زدن فیلترینگ در شرایط خاص',
            'description_en': 'Optimized configs for bypassing filtering in special conditions',
            'inbound_ids': [],
            'is_active': True,
            'order': 1,
            'packages': [
                {
                    'id': 1,
                    'volume': 10,
                    'days': 30,
                    'price': 100000,
                    'ip_limit': 2,
                    'is_active': True
                },
                {
                    'id': 2,
                    'volume': 20,
                    'days': 30,
                    'price': 180000,
                    'ip_limit': 3,
                    'is_active': True
                }
            ]
        },
        {
            'id': 2,
            'name': 'کانفیگ ملی',
            'name_en': 'National Config',
            'icon': '🇮🇷',
            'description': 'کانفیگ‌های بهینه شده برای اینترنت ملی و شبکه داخلی',
            'description_en': 'Optimized configs for national internet and internal network',
            'inbound_ids': [],
            'is_active': True,
            'order': 2,
            'packages': [
                {
                    'id': 3,
                    'volume': 10,
                    'days': 30,
                    'price': 80000,
                    'ip_limit': 3,
                    'is_active': True
                },
                {
                    'id': 4,
                    'volume': 0,
                    'days': 30,
                    'price': 120000,
                    'ip_limit': 5,
                    'is_active': True
                }
            ]
        }
    ],
    'last_updated': now_tehran_iso()
}

# Lifecycle Hooks
_post_load_hooks: List[Callable[[], None]] = []
_pre_save_hooks: List[Callable[[], None]] = []
_migration_hooks: List[Callable[[], None]] = []


def register_post_load_hook(hook: Callable[[], None]) -> None:
    """Register callback to execute immediately after loading all datasets."""
    if hook not in _post_load_hooks:
        _post_load_hooks.append(hook)


def register_pre_save_hook(hook: Callable[[], None]) -> None:
    """Register callback to execute immediately before saving datasets."""
    if hook not in _pre_save_hooks:
        _pre_save_hooks.append(hook)


def register_migration_hook(hook: Callable[[], None]) -> None:
    """Register callback to execute migration logic during startup."""
    if hook not in _migration_hooks:
        _migration_hooks.append(hook)


# ═══════════════════════════════════════════════════════════
# Base Order Operations
# ═══════════════════════════════════════════════════════════

def get_valid_orders() -> dict:
    """دریافت سفارشات معتبر"""
    return {k: v for k, v in orders.items() if isinstance(v, dict) and 'order_id' in v}


def update_order(order_id: int, **kwargs) -> bool:
    """بروزرسانی سفارش"""
    oid = str(order_id)
    if oid in orders and isinstance(orders[oid], dict):
        for k, v in kwargs.items():
            orders[oid][k] = v
        orders[oid]['updated_at'] = now_tehran_iso()
        logger.debug(f"📝 order #{order_id} updated: {list(kwargs.keys())}")
        save_json(DB_FILES['orders'], orders)
        return True
    logger.error(f"❌ order #{order_id} not found")
    return False


# ═══════════════════════════════════════════════════════════
# Config Pool Operations
# ═══════════════════════════════════════════════════════════

def add_config_to_pool(volume: int, days: int, link: str) -> int:
    """افزودن کانفیگ به مخزن"""
    configs_pool['last_id'] = configs_pool.get('last_id', 0) + 1
    if 'configs' not in configs_pool or not isinstance(configs_pool['configs'], list):
        configs_pool['configs'] = []
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


# ═══════════════════════════════════════════════════════════
# Test Usage Persistence
# ═══════════════════════════════════════════════════════════

def load_test_usage() -> dict:
    """بارگذاری اطلاعات تست کاربران"""
    try:
        test_file = os.path.join(DATA_DIR, "test_usage.json")
        if os.path.exists(test_file):
            with open(test_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            USER_TEST_USAGE.clear()
            if isinstance(data, dict):
                USER_TEST_USAGE.update(data)
            logger.info(f"✅ User test information loaded: {len(USER_TEST_USAGE)} user")
        else:
            USER_TEST_USAGE.clear()
            with open(test_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"❌ Error loading tests: {e}")
        USER_TEST_USAGE.clear()

    return USER_TEST_USAGE


def save_test_usage() -> bool:
    """ذخیره اطلاعات تست کاربران"""
    try:
        test_file = os.path.join(DATA_DIR, "test_usage.json")
        with open(test_file, 'w', encoding='utf-8') as f:
            json.dump(USER_TEST_USAGE, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"❌ Error saving tests: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# Default Settings & Initialization
# ═══════════════════════════════════════════════════════════

def _init_default_settings() -> None:
    """تنظیمات پیش‌فرض برای configs_pool"""
    defaults = {
        'configs': [],
        'last_id': 0,
        'price_settings': {
            'base_price': 20000,
            'per_gb_price': 20000,
            'per_15days_price': 5000,
            'referral_bonus': 5000,
            'min_charge': 10000,
            'max_charge': 5000000,
            'last_updated': now_tehran_iso(),
        },
        'force_join_settings': {
            'enabled': False,
            'channels': [],
            'check_interval': 300,
            'last_updated': now_tehran_iso(),
        },
        'auto_backup_settings': {
            'backup_enabled': True,
            'backup_interval_hours': 6,
            'last_backup_time': None,
            'sync_enabled': True,
            'sync_interval_hours': 6,
            'last_sync_time': None,
            'last_updated': now_tehran_iso(),
        },
    }

    modified = False
    for key, default_value in defaults.items():
        if key not in configs_pool:
            configs_pool[key] = default_value
            modified = True
            logger.info(f"⚙️ {key} added to configs_pool")

    if modified:
        save_json(DB_FILES['configs'], configs_pool)


def _init_default_settings_if_needed() -> None:
    """تنظیمات پیش‌فرض را فقط در صورت نبودن اضافه کن - بدون ذخیره خودکار"""
    if 'configs' not in configs_pool:
        configs_pool['configs'] = []
        logger.info('📦 configs array added to configs_pool')

    if 'last_id' not in configs_pool:
        configs_pool['last_id'] = 0
        logger.info('🔢 last_id set in configs_pool')

    if 'default_inbound_id' not in configs_pool:
        configs_pool['default_inbound_id'] = None
        logger.info('⚙️ default_inbound_id added to configs_pool')

    if 'ai_settings' not in configs_pool:
        configs_pool['ai_settings'] = {
            'button_enabled': True,
            'last_updated': now_tehran_iso(),
        }
        logger.info('⚙️ ai_settings added to configs_pool (default: active)')

    if 'test_service' not in configs_pool:
        configs_pool['test_service'] = {
            'enabled': False,
            'volume': 5,
            'days': 3,
            'max_tests': 1,
            'message': '🎁 یک سرویس تست {volume}GB / {days} روز برای شما فعال شد!',
            'last_updated': now_tehran_iso(),
        }
        TEST_SERVICE_STATUS.clear()
        TEST_SERVICE_STATUS.update(configs_pool['test_service'])
        logger.info('🧪 test_service added to configs_pool (default: disabled)')

    if 'ready_packages' not in configs_pool:
        configs_pool['ready_packages'] = READY_PACKAGES
        logger.info('📦 ready_packages added to configs_pool')

    if 'shop_status' not in configs_pool:
        configs_pool['shop_status'] = SHOP_STATUS
        logger.info('🛒 shop_status added to configs_pool')

    if 'auto_backup_settings' not in configs_pool:
        configs_pool['auto_backup_settings'] = {
            'backup_enabled': True,
            'backup_interval_hours': 6,
            'last_backup_time': None,
            'sync_enabled': True,
            'sync_interval_hours': 6,
            'last_sync_time': None,
            'last_updated': now_tehran_iso(),
        }
        logger.info('⚙️ auto_backup_settings added to configs_pool (default: 6h active)')

    defaults = {
        'price_settings': {
            'base_price': 20000,
            'per_gb_price': 20000,
            'per_15days_price': 5000,
            'referral_bonus': 5000,
            'min_charge': 10000,
            'max_charge': 5000000,
            'last_updated': now_tehran_iso(),
        },
        'force_join_settings': {
            'enabled': False,
            'channels': [],
            'check_interval': 300,
            'last_updated': now_tehran_iso(),
        },
        'auto_backup_settings': {
            'backup_enabled': True,
            'backup_interval_hours': 6,
            'last_backup_time': None,
            'sync_enabled': True,
            'sync_interval_hours': 6,
            'last_sync_time': None,
            'last_updated': now_tehran_iso(),
        },
    }

    modified = False
    for key, default_value in defaults.items():
        if key not in configs_pool:
            configs_pool[key] = default_value
            modified = True
            logger.info(f"⚙️ {key} added to configs_pool (default value)")

    if modified:
        save_json(DB_FILES['configs'], configs_pool)
        logger.info(f"✅ default settings saved in {DB_FILES['configs']} saved")
    else:
        logger.debug('✅ all settings existed already - no changes applied')


def _init_empty_databases() -> None:
    """ایجاد دیتابیس‌های خالی در صورت خطا"""
    users.clear()
    orders.clear()
    referrals.clear()
    configs_pool.clear()
    configs_pool.update({'configs': [], 'last_id': 0})
    feedbacks.clear()
    chats.clear()
    BLACKLIST.clear()

    _init_default_settings()
    logger.warning('⚠️ databases initialized with default values')


# ═══════════════════════════════════════════════════════════
# Backup Recovery
# ═══════════════════════════════════════════════════════════

def try_full_restore_from_backup() -> bool:
    """تلاش برای بازیابی کامل از آخرین بکاپ"""
    backup_dir = os.path.join(DATA_DIR, 'backups')
    if not os.path.exists(backup_dir):
        logger.warning('⚠️ no backup directory found')
        return False

    backups = [f for f in os.listdir(backup_dir) if f.startswith('full_backup_') and f.endswith('.json')]
    if not backups:
        logger.warning('⚠️ no complete backup found')
        return False

    backups.sort(reverse=True)
    latest_backup = os.path.join(backup_dir, backups[0])
    logger.info(f"🔄 attempting full restore from backup: {backups[0]}")

    try:
        with open(latest_backup, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if data.get('users'):
            users.clear()
            users.update(data['users'])
            logger.info(f"✅ {len(users)} user restored from backup")
        if data.get('orders'):
            orders.clear()
            orders.update(data['orders'])
            logger.info(f"✅ {len(orders)} order restored from backup")
        if data.get('referrals'):
            referrals.clear()
            referrals.update(data['referrals'])
            logger.info(f"✅ {len(referrals)} referral restored from backup")
        if data.get('configs'):
            configs_pool.clear()
            configs_pool.update(data['configs'])
            logger.info(f"✅ {len(configs_pool.get('configs', []))} config restored from backup")
        if data.get('feedback'):
            feedbacks.clear()
            feedbacks.update(data['feedback'])
        if data.get('chats'):
            chats.clear()
            chats.update(data['chats'])
        if data.get('blacklist'):
            BLACKLIST.clear()
            BLACKLIST.update(data['blacklist'].get('users', []))
        if data.get('daily_usage'):
            try:
                from daily_usage_system import usage_store
                usage_store.import_backup_data(data['daily_usage'])
                logger.info('✅ Daily usage data restored from backup')
            except Exception as ex_u:
                logger.warning(f"⚠️ Error restoring daily usage from backup: {ex_u}")

        save_all()
        logger.info("✅ complete backup restore succeeded")
        return True

    except Exception as e:
        logger.error(f"❌ Error performing full backup recovery: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# Core Persistence (save_all & load_all_data)
# ═══════════════════════════════════════════════════════════

def save_all(save_blacklist: bool = True) -> bool:
    """ذخیره تمام دیتابیس‌ها با لاگ کامل"""
    start_time = time.time()
    logger.debug('💾 starting save of all databases...')

    # Pre-save hooks (e.g. sync ready_packages / test_service into configs_pool)
    for hook in _pre_save_hooks:
        try:
            hook()
        except Exception as e:
            logger.error(f"Error in pre-save hook: {e}")

    db_mapping = {
        'users': (DB_FILES['users'], users),
        'orders': (DB_FILES['orders'], orders),
        'referrals': (DB_FILES['referrals'], referrals),
        'configs': (DB_FILES['configs'], configs_pool),
        'feedback': (DB_FILES['feedback'], feedbacks),
        'chats': (DB_FILES['chats'], chats),
    }

    success = True
    saved_count = 0
    failed_files = []

    for name, (file, data) in db_mapping.items():
        try:
            if save_json(file, data):
                saved_count += 1
            else:
                success = False
                failed_files.append(name)
        except Exception as e:
            logger.error(f"❌ error saving {name}: {e}")
            success = False
            failed_files.append(name)

    try:
        if 'ready_packages' in configs_pool:
            if save_json(DB_FILES['configs'], configs_pool):
                saved_count += 1
                logger.info('📦 Ready-made packages saved in configs_pool')
            else:
                success = False
                failed_files.append('configs (ready_packages)')
    except Exception as e:
        logger.error(f"❌ Error saving ready-made packages: {e}")
        success = False
        failed_files.append('ready_packages')

    try:
        if 'test_service' in configs_pool:
            if save_json(DB_FILES['configs'], configs_pool):
                saved_count += 1
                logger.info('🧪 Service test settings saved in configs_pool')
            else:
                success = False
                failed_files.append('configs (test_service)')
    except Exception as e:
        logger.error(f"❌ Error saving test settings: {e}")
        success = False
        failed_files.append('test_service')

    if save_blacklist:
        try:
            blacklist_data = {
                'users': list(BLACKLIST),
                'last_updated': now_tehran_iso(),
                'count': len(BLACKLIST),
            }
            if save_json(DB_FILES['blacklist'], blacklist_data):
                saved_count += 1
            else:
                success = False
                failed_files.append('blacklist')
        except Exception as e:
            logger.error(f"❌ Error saving blacklist: {e}")
            success = False
            failed_files.append('blacklist')

    try:
        save_test_usage()
        saved_count += 1
    except Exception as e:
        logger.error(f"❌ Error saving test_usage: {e}")
        success = False
        failed_files.append('test_usage')

    try:
        from user_manager import user_states
        if hasattr(user_states, 'save') and user_states.save():
            saved_count += 1
    except Exception as e:
        logger.debug(f"Note: user_states save: {e}")

    elapsed = time.time() - start_time
    if success:
        logger.info(f"✅ all databases saved ({saved_count} files, {elapsed:.2f} seconds)")
    else:
        logger.error(f"❌ error saving {len(failed_files)} file: {failed_files}")

    return success


def load_all_data() -> bool:
    """بارگذاری تمام دیتابیس‌ها - با بازیابی از بکاپ در صورت نیاز"""
    logger.info("=" * 60)
    logger.info('🔄 starting database loading...')
    for name, path in DB_FILES.items():
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        logger.info(f"{name}: {path} - {'exists' if exists else 'not found'} ({size:,} bytes)")

    try:
        users_data = load_json(DB_FILES['users'], use_cache=False)
        orders_data = load_json(DB_FILES['orders'], use_cache=False)
        referrals_data = load_json(DB_FILES['referrals'], use_cache=False)
        configs_data = load_json(DB_FILES['configs'], use_cache=False)
        feedbacks_data = load_json(DB_FILES['feedback'], use_cache=False)
        chats_data = load_json(DB_FILES['chats'], use_cache=False)

        # In-place mutations preserving object references across application
        users.clear()
        if users_data and isinstance(users_data, dict):
            users.update(users_data)

        orders.clear()
        if orders_data and isinstance(orders_data, dict):
            orders.update(orders_data)

        referrals.clear()
        if referrals_data and isinstance(referrals_data, dict):
            referrals.update(referrals_data)

        feedbacks.clear()
        if feedbacks_data and isinstance(feedbacks_data, dict):
            feedbacks.update(feedbacks_data)

        chats.clear()
        if chats_data and isinstance(chats_data, dict):
            chats.update(chats_data)

        configs_pool.clear()
        if configs_data and isinstance(configs_data, dict):
            configs_pool.update(configs_data)

        blacklist_data = load_json(DB_FILES['blacklist'], use_cache=False)
        BLACKLIST.clear()
        if blacklist_data and 'users' in blacklist_data:
            BLACKLIST.update(blacklist_data.get('users', []))

        # Test settings in configs_pool
        test_settings = configs_pool.get('test_service', {})
        if test_settings:
            TEST_SERVICE_STATUS.clear()
            TEST_SERVICE_STATUS.update(test_settings)
            logger.info(f"🧪 Test settings loaded: {'enabled' if TEST_SERVICE_STATUS.get('enabled') else 'disabled'}")
            logger.info(f"🧪 Test inbounds: {TEST_SERVICE_STATUS.get('inbound_ids', [])}")
        else:
            TEST_SERVICE_STATUS.clear()
            TEST_SERVICE_STATUS.update({
                'enabled': False,
                'volume': 5,
                'volume_mb': 5120,
                'days': 3,
                'max_tests': 1,
                'inbound_ids': [],
                'message': '🎁 یک سرویس تست {volume}GB / {days} روز برای شما فعال شد!',
                'last_updated': now_tehran_iso(),
            })
            configs_pool['test_service'] = TEST_SERVICE_STATUS
            logger.info('🧪 Default test settings created')

        load_test_usage()

        # Ready packages in configs_pool
        ready_pkgs = configs_pool.get('ready_packages', {})
        if ready_pkgs and isinstance(ready_pkgs, dict):
            READY_PACKAGES.clear()
            READY_PACKAGES.update(ready_pkgs)
            logger.info(f"📦 Ready packages loaded: {len(READY_PACKAGES.get('categories', []))} categories")
        else:
            configs_pool['ready_packages'] = READY_PACKAGES

        # Shop status in configs_pool
        shop_stat = configs_pool.get('shop_status', {})
        if shop_stat and isinstance(shop_stat, dict):
            SHOP_STATUS.clear()
            SHOP_STATUS.update(shop_stat)
            logger.info(f"🛒 Sales status: {'open' if SHOP_STATUS.get('open') else 'closed'}")
        else:
            configs_pool['shop_status'] = SHOP_STATUS

        try:
            from user_manager import user_states
            if hasattr(user_states, 'load'):
                user_states.load()
        except Exception as e:
            logger.debug(f"Note: user_states load: {e}")

        # Execute registered post-load hooks (ready packages, test settings, inbounds, etc.)
        for hook in _post_load_hooks:
            try:
                hook()
            except Exception as hook_err:
                logger.error(f"Error in post load hook {hook}: {hook_err}", exc_info=True)

        logger.info("=" * 60)
        logger.info("📊 load results:")
        logger.info(f"  users: {len(users)}")
        logger.info(f"  orders: {len(orders)}")
        logger.info(f"  referrals: {len(referrals)}")
        logger.info(f"  configs: {len(configs_pool.get('configs', []))}")
        logger.info(f"  feedback: {len(feedbacks)}")
        logger.info(f"  chats: {len(chats)}")
        logger.info(f"  blacklist: {len(BLACKLIST)}")
        logger.info(f"  test users: {len(USER_TEST_USAGE)}")
        logger.info(f"Test status: {'enabled' if TEST_SERVICE_STATUS.get('enabled') else 'disabled'}")
        logger.info(f"  test inbounds: {TEST_SERVICE_STATUS.get('inbound_ids', [])}")
        logger.info("=" * 60)

        if len(users) == 0 and len(orders) == 0:
            logger.warning('⚠️ All databases are empty! Attempting full backup recovery...')
            try_full_restore_from_backup()

        _init_default_settings_if_needed()

        # Execute registered migration hooks
        for hook in _migration_hooks:
            try:
                hook()
            except Exception as mig_err:
                logger.error(f"Error in migration hook {hook}: {mig_err}", exc_info=True)

        logger.info('✅ complete database loading succeeded')
        return True

    except Exception as e:
        logger.error(f"❌ Error loading database: {e}", exc_info=True)
        _init_empty_databases()
        return False


def reset_database_collections() -> None:
    """Clear all user/order runtime collections in-place while preserving settings in configs_pool."""
    saved_settings = {
        'price_settings': configs_pool.get('price_settings', {}),
        'force_join_settings': configs_pool.get('force_join_settings', {}),
        'ai_settings': configs_pool.get('ai_settings', {}),
        'shop_status': configs_pool.get('shop_status', {}),
        'test_service': configs_pool.get('test_service', {}),
        'ready_packages': configs_pool.get('ready_packages', {}),
        'default_inbound_ids': configs_pool.get('default_inbound_ids', []),
    }
    users.clear()
    orders.clear()
    referrals.clear()
    feedbacks.clear()
    chats.clear()
    BLACKLIST.clear()
    configs_pool.clear()
    configs_pool.update({
        'configs': [],
        'last_id': 0,
        **saved_settings,
    })

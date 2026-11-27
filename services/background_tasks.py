"""
services/background_tasks.py
----------------------------
وظایف پس‌زمینه (Background Tasks)، مانیتورینگ سیستم، بهینه‌سازی دیتابیس،
چرخش لاگ‌ها، گزارش‌های سلامت دوره‌ای و مدیریت چرخه‌حیات وظایف.
"""

import os
import gc
import sys
import time
import shutil
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from aiogram import Bot
from aiogram.enums import ParseMode

from config import (
    ADMIN_ID,
    ADMIN_ID_INT,
    SENAI_PANEL_ENABLED,
    is_senai_panel_enabled,
)
from db_storage import (
    DATA_DIR,
    DB_FILES,
    _db_cache,
    _db_modified,
    _storage_lock,
)
from database import (
    users,
    orders,
    referrals,
    chats,
    feedbacks,
    configs_pool,
    BLACKLIST,
    get_valid_orders,
    get_available_configs_count,
    save_all,
    TEHRAN_TZ,
    now_tehran,
    now_tehran_iso,
)
from user_manager import get_user
from core.save_scheduler import schedule_save
from core.state_stores import (
    user_states,
    TEMP_INBOUND_SELECTION,
    INBOUND_BACK_DATA,
    _tg_user_cache,
)
from core.task_manager import (
    consume_force_run,
    get_task_interval,
    is_task_enabled,
    record_task_finish,
    record_task_start,
    sleep_interruptible,
    wait_until_task_enabled,
)
from text_utils import format_size
from daily_usage_system import usage_collector
from services.panel_api import (
    xui_login,
    xui_get_inbounds,
    xui_get_client_traffic,
    get_order_client_email,
    reset_panel_rate_limits,
)

logger = logging.getLogger(__name__)

# بات و لاگ سیستم در سطح ماژول جهت دسترسی ایمن در تسک‌های مستقل
_bot_instance: Optional[Bot] = None
_log_system_instance: Any = None


def set_bot(bot: Bot) -> None:
    """تنظیم رفرنس فعال بات تلگرام برای تسک‌های پس‌زمینه"""
    global _bot_instance
    _bot_instance = bot


def get_bot() -> Optional[Bot]:
    """دریافت رفرنس فعال بات تلگرام"""
    global _bot_instance
    if _bot_instance is not None:
        return _bot_instance
    try:
        if 'main' in sys.modules and hasattr(sys.modules['main'], 'bot'):
            return sys.modules['main'].bot
    except Exception:
        pass
    return None


def set_log_system(log_system: Any) -> None:
    """تنظیم رفرنس سیستم لاگ خارجی"""
    global _log_system_instance
    _log_system_instance = log_system


def get_log_system() -> Any:
    """دریافت رفرنس سیستم لاگ خارجی"""
    global _log_system_instance
    if _log_system_instance is not None:
        return _log_system_instance
    try:
        if 'main' in sys.modules and hasattr(sys.modules['main'], 'log_system'):
            return sys.modules['main'].log_system
    except Exception:
        pass
    return None


def get_memory_usage() -> dict:
    """دریافت میزان استفاده از حافظه"""
    try:
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()

        rss_mb = memory_info.rss / (1024 * 1024)
        vms_mb = memory_info.vms / (1024 * 1024)
        percent = process.memory_percent()

        logger.debug(f"Memory usage: RSS={rss_mb:.1f}MB, VMS={vms_mb:.1f}MB, Percent={percent:.1f}%")

        return {
            'rss_mb': rss_mb,
            'vms_mb': vms_mb,
            'percent': percent,
            'db_cache_size': len(_db_cache),
            'user_states_size': len(user_states),
        }
    except ImportError:
        logger.debug('The psutil module is not installed; memory statistics are unavailable')
        return {
            'rss_mb': 0,
            'vms_mb': 0,
            'percent': 0,
            'db_cache_size': len(_db_cache),
            'user_states_size': len(user_states),
        }
    except Exception as e:
        logger.error(f"Error retrieving memory statistics: {e}")
        return {
            'rss_mb': 0,
            'vms_mb': 0,
            'percent': 0,
            'db_cache_size': len(_db_cache),
            'user_states_size': len(user_states),
        }


def get_database_size() -> dict:
    """دریافت حجم دیتابیس با نمایش هوشمند"""
    sizes = {}
    total = 0

    logger.info('🔍 calculating database size...')

    for name, file_path in DB_FILES.items():
        if os.path.exists(file_path):
            try:
                size = os.path.getsize(file_path)
                sizes[name] = size
                total += size
                logger.info(f"  ✅ {name}: {format_size(size)}")
            except Exception as e:
                logger.error(f"  ❌ Error reading {name}: {e}")
                sizes[name] = 0
        else:
            logger.warning(f"  ⚠️ File {name} does not exist: {file_path}")
            sizes[name] = 0

    sizes['total'] = total
    sizes['total_formatted'] = format_size(total)

    logger.info(f"📊 total size: {format_size(total)}")
    return sizes


def cleanup_expired_states() -> int:
    """پاک کردن وضعیت‌های منقضی شده کاربران با نگهداری آمار"""
    logger.debug('starting cleanup of expired statuses...')
    now = now_tehran()
    expired = []
    expired_count = 0
    no_timestamp_count = 0
    expired_types = {}

    for user_id, state in list(user_states.items()):
        should_delete = False
        state_type = 'unknown'

        if 'awaiting_receipt' in state:
            state_type = 'awaiting_receipt'
        elif 'awaiting_amount' in state:
            state_type = 'awaiting_amount'
        elif 'awaiting_chat' in state:
            state_type = 'awaiting_chat'
        elif 'awaiting_config' in state:
            state_type = 'awaiting_config'
        elif 'awaiting_manual_balance' in state:
            state_type = 'awaiting_manual_balance'

        if 'timestamp' in state:
            try:
                created = datetime.fromisoformat(str(state['timestamp']).strip())
                if created.tzinfo is None:
                    created = created.replace(tzinfo=TEHRAN_TZ)
                age_seconds = (now - created).total_seconds()
                if age_seconds > 1800:
                    should_delete = True
                    expired_count += 1
                    logger.debug(f"User status {user_id} expired (type: {state_type}, age: {age_seconds:.0f} seconds)")
            except (ValueError, TypeError) as e:
                should_delete = True
                expired_count += 1
                logger.debug(f"Invalid timestamp for user {user_id}: {state.get('timestamp')} - Error: {e}")
        elif len(state) > 0:
            # دادن فرصت به وضعیت‌هایی که timestamp ندارند تا در میانه کار کاربر حذف نشوند
            state['timestamp'] = now.isoformat()
            no_timestamp_count += 1
            logger.debug(f"Status without timestamp for user {user_id} was marked (type: {state_type})")

        if should_delete:
            expired.append(user_id)
            expired_types[state_type] = expired_types.get(state_type, 0) + 1

    for user_id in expired:
        user_states.pop(user_id, None)

    if expired_count > 0 or no_timestamp_count > 0:
        logger.info(f"🧹 Cleaning up states: {expired_count} with expired timestamps | {no_timestamp_count} without timestamps - total: {len(expired)}")
        if expired_types:
            logger.info(f"   Types cleared: {expired_types}")
    else:
        logger.debug('State cleanup: no expired states found')

    try:
        cleaned_inbounds = TEMP_INBOUND_SELECTION.cleanup()
        cleaned_back = INBOUND_BACK_DATA.cleanup()
        if cleaned_inbounds > 0 or cleaned_back > 0:
            logger.info(f"🧹 Temporary inbound stores cleaned: {cleaned_inbounds} selections, {cleaned_back} back data")
    except Exception as e:
        logger.warning(f"Error cleaning temp inbound stores: {e}")

    try:
        now_mono = time.monotonic()
        expired_tg = [k for k, (exp, _) in _tg_user_cache.items() if exp < now_mono]
        for k in expired_tg:
            _tg_user_cache.pop(k, None)
        if expired_tg:
            logger.debug(f"🧹 Cleaned {len(expired_tg)} expired Telegram user cache entries")
    except Exception as e:
        logger.warning(f"Error cleaning telegram user cache: {e}")

    return len(expired)


def _is_iso_older_than(ts: Any, cutoff_dt: datetime) -> bool:
    """Safely compare naive or timezone-aware ISO timestamps against cutoff_dt."""
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(str(ts).strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TEHRAN_TZ)
        return dt < cutoff_dt
    except Exception:
        return str(ts) < cutoff_dt.isoformat()


def optimize_storage(save: bool = True) -> int:
    """بهینه‌سازی فضای ذخیره‌سازی با پاکسازی رکوردهای قدیمی دیتابیس"""
    cleaned = 0
    cutoff_date = now_tehran() - timedelta(days=30)
    old_rejected = []
    for oid, order in list(orders.items()):
        if isinstance(order, dict) and order.get('status') == 'rejected':
            updated_at = order.get('updated_at', order.get('created_at', ''))
            if _is_iso_older_than(updated_at, cutoff_date):
                old_rejected.append(oid)

    for oid in old_rejected:
        del orders[oid]
        cleaned += 1

    old_cancelled = []
    for oid, order in list(orders.items()):
        if isinstance(order, dict) and order.get('status') == 'cancelled':
            updated_at = order.get('updated_at', order.get('created_at', ''))
            if _is_iso_older_than(updated_at, cutoff_date):
                old_cancelled.append(oid)

    for oid in old_cancelled:
        del orders[oid]
        cleaned += 1

    old_inactive = []
    cutoff_90days = now_tehran() - timedelta(days=90)

    for uid, user in list(users.items()):
        if not user.get('is_active', True):
            updated_at = user.get('updated_at', user.get('created_at', ''))
            if _is_iso_older_than(updated_at, cutoff_90days):
                if user.get('total_purchases', 0) == 0 and user.get('balance', 0) == 0:
                    old_inactive.append(uid)

    for uid in old_inactive:
        del users[uid]
        cleaned += 1

    if cleaned > 0:
        if save:
            schedule_save(0.5)
        logger.info("✅ optimization completed:")
        logger.info(f"  🗑 {len(old_rejected)} old rejected order")
        logger.info(f"  🗑 {len(old_cancelled)} old cancelled order")
        logger.info(f"  🗑 {len(old_inactive)} old inactive user")
    else:
        logger.info('✅ database is optimized - nothing to delete')

    return cleaned


def _get_active_chats_list() -> list:
    """دریافت لیست چت‌های باز پشتیبانی"""
    try:
        from routers.support import get_active_chats
        return get_active_chats()
    except Exception:
        return [c for c in chats.values() if isinstance(c, dict) and c.get('status') == 'open']


def _get_backup_list_safe() -> list:
    """دریافت لیست بکاپ‌ها به صورت ایمن"""
    try:
        from routers.admin_tools import get_backup_list
        return get_backup_list()
    except Exception:
        backup_dir = os.path.join(DATA_DIR, 'backups')
        if not os.path.exists(backup_dir):
            return []
        items = []
        for f in os.listdir(backup_dir):
            if f.endswith('.json') or f.endswith('.backup'):
                fp = os.path.join(backup_dir, f)
                items.append({'filename': f, 'size_mb': os.path.getsize(fp) / (1024 * 1024)})
        return items


async def send_health_report(chat_id: int, bot: Optional[Bot] = None) -> None:
    """ارسال گزارش سلامت با نمایش هوشمند حجم (دو زبانه فارسی/انگلیسی)"""
    b = bot or get_bot()
    if not b:
        logger.error("send_health_report failed: bot instance is not available")
        return

    lang = get_user(chat_id).get('lang', 'fa')
    db_size = get_database_size()
    total_bytes = db_size.get('total', 0)
    total_formatted = format_size(total_bytes)
    valid_orders = get_valid_orders()
    pending = len([o for o in valid_orders.values() if o.get('status') in ['pending', 'awaiting_payment']])

    states_count = len(user_states)
    memory_info = get_memory_usage()

    panel_status = ("🔴 Inactive" if lang == "en" else "🔴 غیرفعال")
    if is_senai_panel_enabled():
        try:
            cookie = await xui_login()
            if cookie:
                panel_status = ("🟢 Active" if lang == "en" else "🟢 فعال")
        except Exception:
            panel_status = ("🔴 Connection Error" if lang == "en" else "🔴 خطا در اتصال")

    total, used, free = shutil.disk_usage(".")
    free_gb = free / (1024**3)
    used_gb = used / (1024**3)
    total_gb = total / (1024**3)
    total_balance = sum(int(u.get('balance') or 0) for u in users.values())
    total_revenue = sum(int(o.get('price') or 0) for o in valid_orders.values() if o.get('status') == 'approved')
    backup_count = len(_get_backup_list_safe())
    now_str = now_tehran().strftime('%Y-%m-%d %H:%M:%S')
    today_str = now_tehran().strftime('%Y-%m-%d')

    if lang == "en":
        report = f"""
📊 <b>Bot Health Report</b>

🕐 Time: {now_str}

📁 <b>Database:</b>
• Total Size: {total_formatted}
"""
        for name, size in db_size.items():
            if name != 'total' and name != 'total_formatted':
                report += f"  • {name}: {format_size(size)}\n"

        report += f"""
• Users: {len(users)}
• Orders: {len(valid_orders)}
• Pending Approval: {pending}

💰 <b>Financial:</b>
• Total Balance: {total_balance:,} Toman
• Total Revenue: {total_revenue:,} Toman

💾 <b>System:</b>
• Free Disk Space: {free_gb:.2f} GB
• Used Disk Space: {used_gb:.2f} GB
• Total Disk Space: {total_gb:.2f} GB
• Backups Count: {backup_count}

⚙️ <b>Status:</b>
• Active States: {states_count}
• DB Cache: {memory_info.get('db_cache_size', 0)} items
• Panel: {panel_status}
• Date: {today_str}
"""
        if free_gb < 1.0:
            report += f"""

⚠️ <b>Warning: Low Disk Space!</b>
💾 Free Space: {free_gb:.2f} GB
📁 Please clean up old logs and backups.
"""
    else:
        report = f"""
📊 <b>گزارش سلامت ربات</b>

🕐 زمان: {now_str}

📁 <b>دیتابیس:</b>
• حجم کل: {total_formatted}
"""
        for name, size in db_size.items():
            if name != 'total' and name != 'total_formatted':
                report += f"  • {name}: {format_size(size)}\n"

        report += f"""
• کاربران: {len(users)}
• سفارشات: {len(valid_orders)}
• در انتظار تایید: {pending}

💰 <b>مالی:</b>
• مجموع موجودی: {total_balance:,} تومان
• درآمد کل: {total_revenue:,} تومان

💾 <b>سیستم:</b>
• فضای خالی دیسک: {free_gb:.2f} GB
• فضای استفاده شده: {used_gb:.2f} GB
• کل فضا: {total_gb:.2f} GB
• تعداد بکاپ‌ها: {backup_count}

⚙️ <b>وضعیت:</b>
• وضعیت‌های فعال: {states_count}
• حافظه کش: {memory_info.get('db_cache_size', 0)} آیتم
• پنل: {panel_status}
• آخرین بکاپ: {today_str}
"""
        if free_gb < 1.0:
            report += f"""

⚠️ <b>هشدار: فضای خالی دیسک کم است!</b>
💾 فضای خالی: {free_gb:.2f} GB
📁 لطفاً لاگ‌ها و بکاپ‌های قدیمی را پاکسازی کنید.
"""

    await b.send_message(chat_id, report, parse_mode=ParseMode.HTML)


async def send_disk_warning(chat_id: int, bot: Optional[Bot] = None) -> None:
    """ارسال هشدار دیسک (دو زبانه فارسی/انگلیسی)"""
    b = bot or get_bot()
    if not b:
        logger.error("send_disk_warning failed: bot instance is not available")
        return

    lang = get_user(chat_id).get('lang', 'fa')
    total, used, free = shutil.disk_usage(".")
    free_gb = free / (1024**3)
    used_gb = used / (1024**3)
    total_gb = total / (1024**3)
    large_files = []
    for file in ['bot_debug.log', 'events.log', 'bot_error.log']:
        if os.path.exists(file):
            size_mb = os.path.getsize(file) / (1024 * 1024)
            if size_mb > 1:
                large_files.append(f"• {file}: {size_mb:.1f} MB")

    if lang == "en":
        warning_msg = f"""
⚠️ <b>Warning: Low Disk Space!</b>

💾 Free Space: {free_gb:.1f} GB
📊 Used Space: {used_gb:.1f} GB
📊 Total Space: {total_gb:.1f} GB

📁 <b>Large Files:</b>
{chr(10).join(large_files) if large_files else '• No large files found'}

💡 Suggestions:
• Delete old backups
• Optimize the database

🕐 Time: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}
"""
    else:
        warning_msg = f"""
⚠️ <b>هشدار: فضای خالی دیسک کم است!</b>

💾 فضای خالی: {free_gb:.1f} GB
📊 فضای استفاده شده: {used_gb:.1f} GB
📊 کل فضا: {total_gb:.1f} GB

📁 <b>فایل‌های بزرگ:</b>
{chr(10).join(large_files) if large_files else '• هیچ فایل بزرگی یافت نشد'}

💡 راهکارها:
• بکاپ‌های قدیمی را حذف کنید
• دیتابیس را بهینه‌سازی کنید

🕐 زمان: {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}
"""

    await b.send_message(chat_id, warning_msg, parse_mode=ParseMode.HTML)


async def send_weekly_detailed_report(chat_id: int, bot: Optional[Bot] = None) -> None:
    """ارسال گزارش هفتگی با جزئیات کامل (دو زبانه فارسی/انگلیسی)"""
    b = bot or get_bot()
    if not b:
        logger.error("send_weekly_detailed_report failed: bot instance is not available")
        return

    lang = get_user(chat_id).get('lang', 'fa')
    db_size = get_database_size()
    total_mb = db_size.get('total', 0) / (1024 * 1024)

    valid_orders = get_valid_orders()
    approved_orders = len([o for o in valid_orders.values() if o.get('status') == 'approved'])
    pending_orders = len([o for o in valid_orders.values() if o.get('status') in ['pending', 'awaiting_payment']])
    rejected_orders = len([o for o in valid_orders.values() if o.get('status') == 'rejected'])
    total_users = len(users)
    active_users = len([u for u in users.values() if u.get('is_active', True)])
    verified_users = len([u for u in users.values() if u.get('verified', False)])
    blacklist_count = len(BLACKLIST)
    total_balance = sum(int(u.get('balance') or 0) for u in users.values())
    total_revenue = sum(int(o.get('price') or 0) for o in valid_orders.values() if o.get('status') == 'approved')
    panel_active = False
    panel_status = ("🔴 Inactive" if lang == "en" else "🔴 غیرفعال")
    inbounds_count = 0
    panel_clients = 0

    if is_senai_panel_enabled():
        try:
            cookie = await xui_login()
            if cookie:
                panel_active = True
                panel_status = ("🟢 Active" if lang == "en" else "🟢 فعال")
                inbounds = await xui_get_inbounds()
                inbounds_count = len(inbounds)
                for o in valid_orders.values():
                    if o.get('status') == 'approved' and o.get('config_link'):
                        panel_clients += 1
        except Exception as e:
            logger.warning(f"Error checking panel status for weekly report: {e}")

    memory_info = get_memory_usage()

    total, used, free = shutil.disk_usage(".")
    free_gb = free / (1024**3)
    used_gb = used / (1024**3)
    total_gb = total / (1024**3)
    total_referrals = len(referrals)
    paid_referrals = len([r for r in referrals.values() if r.get('reward_given', False)])
    backups = _get_backup_list_safe()
    backup_count = len(backups)
    backup_total_mb = sum(b.get('size_mb', 0) for b in backups) if backups else 0
    active_chats = len(_get_active_chats_list())
    total_chats = len(chats)
    total_feedbacks = len(feedbacks)
    available_configs = get_available_configs_count()

    if lang == "en":
        overall_status = '🟢 Excellent' if free_gb > 2 and panel_active else ('🟡 Acceptable' if free_gb > 0.5 else '🔴 Needs Attention')
        report = f"""
📊 <b>Weekly Detailed Bot Report</b>


🕐 <b>Time:</b> {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}
📅 <b>Week:</b> {now_tehran().strftime('%W')} (Year {now_tehran().strftime('%Y')})


📁 <b>Database:</b>
• Total Size: {total_mb:.2f} MB
• Total Users: {total_users}
• Active Users: {active_users}
• Verified Users: {verified_users}
• Blacklist: {blacklist_count}

📋 <b>Orders:</b>
• Total Orders: {len(valid_orders)}
• Approved: {approved_orders}
• Pending: {pending_orders}
• Rejected: {rejected_orders}

💰 <b>Financial:</b>
• Total Balance: {total_balance:,} Toman
• Total Revenue: {total_revenue:,} Toman
• Average Balance: {total_balance // total_users if total_users > 0 else 0:,} Toman

🎁 <b>Referrals:</b>
• Total Referrals: {total_referrals}
• Paid Rewards: {paid_referrals}
• Pending Rewards: {total_referrals - paid_referrals}

📡 <b>Panel:</b>
• Status: {panel_status}
• Inbounds: {inbounds_count}
• Active Clients: {panel_clients}

💬 <b>Support:</b>
• Active Chats: {active_chats}
• Total Chats: {total_chats}
• Feedbacks: {total_feedbacks}

📦 <b>Configs:</b>
• Available in Pool: {available_configs}
• Backups: {backup_count}
• Backups Size: {backup_total_mb:.1f} MB

💾 <b>System:</b>
• Free Disk Space: {free_gb:.1f} GB
• Used Disk Space: {used_gb:.1f} GB
• Total Disk Space: {total_gb:.1f} GB
• Usage Percentage: {(used / total * 100):.1f}%

🧠 <b>Memory:</b>
• RAM Usage: {memory_info.get('rss_mb', 0):.1f} MB
• RAM Percent: {memory_info.get('percent', 0):.1f}%
• DB Cache: {memory_info.get('db_cache_size', 0)} items
• Active States: {memory_info.get('user_states_size', 0)}

✅ <b>Overall Status:</b> {overall_status}

💡 <b>Recommendations:</b>
{f'⚠️ Low disk space ({free_gb:.1f} GB) - please clean up' if free_gb < 1.5 else '✅ Disk space is healthy'}
{f'⚠️ Too many backups ({backup_count})' if backup_count > 20 else '✅ Backup count is reasonable'}
{f'⚠️ Low pool configs ({available_configs})' if available_configs < 5 else '✅ Pool config supply is sufficient'}
"""
    else:
        overall_status = '🟢 عالی' if free_gb > 2 and panel_active else ('🟡 قابل قبول' if free_gb > 0.5 else '🔴 نیاز به توجه')
        report = f"""
📊 <b>گزارش کامل هفتگی ربات</b>


🕐 <b>زمان:</b> {now_tehran().strftime('%Y-%m-%d %H:%M:%S')}
📅 <b>هفته:</b> {now_tehran().strftime('%W')} (سال {now_tehran().strftime('%Y')})


📁 <b>دیتابیس:</b>
• حجم کل: {total_mb:.2f} MB
• کاربران کل: {total_users}
• کاربران فعال: {active_users}
• کاربران تایید شده: {verified_users}
• لیست سیاه: {blacklist_count}

📋 <b>سفارشات:</b>
• کل سفارشات: {len(valid_orders)}
• تایید شده: {approved_orders}
• در انتظار: {pending_orders}
• رد شده: {rejected_orders}

💰 <b>مالی:</b>
• مجموع موجودی: {total_balance:,} تومان
• درآمد کل: {total_revenue:,} تومان
• میانگین موجودی: {total_balance // total_users if total_users > 0 else 0:,} تومان

🎁 <b>رفرال‌ها:</b>
• کل رفرال‌ها: {total_referrals}
• پاداش داده شده: {paid_referrals}
• پاداش باقی‌مانده: {total_referrals - paid_referrals}

📡 <b>پنل:</b>
• وضعیت: {panel_status}
• اینباندها: {inbounds_count}
• کلاینت‌های فعال: {panel_clients}

💬 <b>پشتیبانی:</b>
• چت‌های فعال: {active_chats}
• کل چت‌ها: {total_chats}
• بازخوردها: {total_feedbacks}

📦 <b>کانفیگ‌ها:</b>
• موجود در مخزن: {available_configs}
• بکاپ‌ها: {backup_count} عدد
• حجم بکاپ‌ها: {backup_total_mb:.1f} MB

💾 <b>سیستم:</b>
• فضای خالی دیسک: {free_gb:.1f} GB
• فضای استفاده شده: {used_gb:.1f} GB
• کل فضا: {total_gb:.1f} GB
• درصد استفاده: {(used / total * 100):.1f}%

🧠 <b>حافظه:</b>
• مصرف RAM: {memory_info.get('rss_mb', 0):.1f} MB
• درصد مصرف RAM: {memory_info.get('percent', 0):.1f}%
• کش دیتابیس: {memory_info.get('db_cache_size', 0)} آیتم
• وضعیت‌های فعال: {memory_info.get('user_states_size', 0)}

✅ <b>وضعیت کلی:</b> {overall_status}

💡 <b>توصیه‌ها:</b>
{f'⚠️ فضای دیسک کم است ({free_gb:.1f} GB) - پاکسازی کنید' if free_gb < 1.5 else '✅ فضای دیسک مناسب است'}
{f'⚠️ تعداد بکاپ‌ها زیاد است ({backup_count} عدد)' if backup_count > 20 else '✅ تعداد بکاپ‌ها مناسب است'}
{f'⚠️ کانفیگ مخزن کم است ({available_configs} عدد)' if available_configs < 5 else '✅ کانفیگ‌های مخزن کافی است'}
"""

    await b.send_message(chat_id, report, parse_mode=ParseMode.HTML)


# ==================== وظایف پس‌زمینه (Background Tasks) ====================

async def cleanup_expired_states_task():
    """پاکسازی خودکار وضعیت‌های منقضی شده کاربران"""
    logger.info('Status cleanup task started')
    await sleep_interruptible("cleanup_expired_states", 10.0)

    while True:
        try:
            await wait_until_task_enabled("cleanup_expired_states")
            interval = get_task_interval("cleanup_expired_states")
            consume_force_run("cleanup_expired_states")

            started = record_task_start("cleanup_expired_states")
            try:
                cleaned = cleanup_expired_states()
                if cleaned > 0:
                    logger.info(f"🧹 Automatic cleanup: {cleaned} expired status deleted")
                else:
                    logger.debug('Automatic cleanup: no expired statuses found')
                record_task_finish("cleanup_expired_states", started)
            except Exception as inner_err:
                record_task_finish("cleanup_expired_states", started, str(inner_err))
                raise

            await sleep_interruptible("cleanup_expired_states", interval)
        except asyncio.CancelledError:
            logger.info('Status cleanup task canceled')
            break
        except Exception as e:
            logger.error(f"Error in status cleanup task: {e}", exc_info=True)
            await sleep_interruptible("cleanup_expired_states", 60.0)


async def sync_deleted_configs_task():
    """همگام‌سازی و آپدیت خودکار کانفیگ‌های حذف‌شده از پنل با قابلیت تنظیم زمان و فعال/غیرفعال‌سازی توسط ادمین"""
    logger.info('Configuration synchronization task started')
    await sleep_interruptible("sync_deleted_configs", 60.0)  # تاخیر اولیه

    while True:
        try:
            await wait_until_task_enabled("sync_deleted_configs")
            force = consume_force_run("sync_deleted_configs")
            interval_seconds = get_task_interval("sync_deleted_configs")

            if (is_task_enabled("sync_deleted_configs") or force) and is_senai_panel_enabled():
                started = record_task_start("sync_deleted_configs")
                try:
                    logger.info('Starting synchronization of deleted configs...')
                    from routers.admin_tools import sync_deleted_configs
                    sync_result = await sync_deleted_configs(batch_size=20)
                    deleted = sync_result.get('deleted', 0) if isinstance(sync_result, dict) else (sync_result if isinstance(sync_result, int) else 0)
                    if deleted > 0:
                        logger.info(f"🗑 Synchronization: {deleted} deleted config synchronized")
                    else:
                        logger.debug('Synchronization: no deleted configs found')
                    settings = configs_pool.setdefault('auto_backup_settings', {})
                    settings['last_sync_time'] = now_tehran_iso()
                    schedule_save(2.0)
                    record_task_finish("sync_deleted_configs", started)
                except asyncio.CancelledError:
                    raise
                except Exception as inner_err:
                    record_task_finish("sync_deleted_configs", started, str(inner_err))
                    raise

            await sleep_interruptible("sync_deleted_configs", get_task_interval("sync_deleted_configs"))
        except asyncio.CancelledError:
            logger.info('Config synchronization task canceled')
            break
        except Exception as e:
            logger.error(f"Error in config synchronization task: {e}", exc_info=True)
            await sleep_interruptible("sync_deleted_configs", 600.0)


async def auto_backup_task(bot: Optional[Bot] = None):
    """تسک زمان‌بندی‌شده بکاپ خودکار دیتابیس با امکان فعال/غیرفعال‌سازی و تنظیم زمان توسط ادمین"""
    logger.info('Auto-backup task started')
    await sleep_interruptible("auto_backup", 120.0)  # تاخیر اولیه ۲ دقیقه پس از راه‌اندازی ربات

    while True:
        try:
            await wait_until_task_enabled("auto_backup")
            force = consume_force_run("auto_backup")
            interval_seconds = get_task_interval("auto_backup")

            if is_task_enabled("auto_backup") or force:
                started = record_task_start("auto_backup")
                try:
                    logger.info('Starting scheduled auto-backup of database...')
                    from main import create_auto_backup
                    success = await asyncio.to_thread(create_auto_backup)
                    if success:
                        settings = configs_pool.setdefault('auto_backup_settings', {})
                        settings['last_backup_time'] = now_tehran_iso()
                        schedule_save(2.0)
                        logger.info(f"✅ Scheduled auto-backup completed successfully (Interval: {interval_seconds // 3600}h)")
                    else:
                        logger.warning("⚠️ Scheduled auto-backup failed to save")
                    record_task_finish("auto_backup", started)
                except asyncio.CancelledError:
                    raise
                except Exception as inner_err:
                    record_task_finish("auto_backup", started, str(inner_err))
                    raise

            await sleep_interruptible("auto_backup", get_task_interval("auto_backup"))
        except asyncio.CancelledError:
            logger.info('Auto-backup task canceled')
            break
        except Exception as e:
            logger.error(f"Error in auto_backup_task: {e}", exc_info=True)
            await sleep_interruptible("auto_backup", 600.0)


_weekly_cleanup_running = False


async def weekly_cleanup(bot: Optional[Bot] = None):
    """پاکسازی دوره‌ای دیتابیس (پیش‌فرض هر یکشنبه ساعت 00:00 یا طبق بازه انتخابی ادمین)"""
    global _weekly_cleanup_running
    b = bot or get_bot()
    logger.info('Weekly cleanup task started')
    await sleep_interruptible("weekly_cleanup", 30.0)

    while True:
        try:
            await wait_until_task_enabled("weekly_cleanup")
            force = consume_force_run("weekly_cleanup")
            interval_sec = get_task_interval("weekly_cleanup")

            if not force:
                if interval_sec == 604800:
                    now = now_tehran()
                    days_until_sunday = (6 - now.weekday()) % 7
                    next_sunday = (now + timedelta(days=days_until_sunday)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    if now.weekday() == 6:
                        next_sunday = (now + timedelta(days=7)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                    wait_seconds = max(3600.0, (next_sunday - now).total_seconds())
                else:
                    wait_seconds = float(interval_sec)

                logger.info(f"⏳ Time until periodic DB cleanup: {wait_seconds / 3600:.1f} hours")
                woken = await sleep_interruptible("weekly_cleanup", wait_seconds)
                if woken and not consume_force_run("weekly_cleanup"):
                    continue

            if not is_task_enabled("weekly_cleanup") and not force:
                continue

            if _weekly_cleanup_running:
                logger.warning('⚠️ Weekly cleanup is already running; duplicate run canceled')
                await sleep_interruptible("weekly_cleanup", 3600.0)
                continue

            _weekly_cleanup_running = True
            started = record_task_start("weekly_cleanup")
            try:
                await asyncio.sleep(2)
                logger.info('Starting periodic database cleanup...')

                cleaned = optimize_storage(save=False)
                if cleaned > 0:
                    await asyncio.to_thread(save_all)
                logger.info(f"🧹 Periodic database cleanup completed - {cleaned} records deleted")

                try:
                    total, used, free = shutil.disk_usage(".")
                    free_gb = free / (1024**3)
                    total_gb = total / (1024**3)
                    used_gb = used / (1024**3)
                    disk_percent = (used / total) * 100

                    logger.info(f"💾 Disk space: total={total_gb:.1f}GB, used={used_gb:.1f}GB, free={free_gb:.1f}GB ({disk_percent:.1f}%)")

                    if free_gb < 1.0:
                        logger.warning(f"⚠️ Low disk space: {free_gb:.1f} GB")

                        large_files = []
                        try:
                            for file in ['bot_debug.log', 'events.log', 'bot_error.log']:
                                if os.path.exists(file):
                                    size_mb = os.path.getsize(file) / (1024 * 1024)
                                    if size_mb > 10:
                                        large_files.append(f"{file} ({size_mb:.1f} MB)")
                        except Exception:
                            pass

                        admin_lang = get_user(ADMIN_ID_INT).get('lang', 'fa')
                        if admin_lang == "en":
                            warning_msg = (
                                f"⚠️ <b>Warning: Low Disk Space!</b>\n\n"
                                f"💾 Free Space: {free_gb:.1f} GB\n"
                                f"📊 Total Space: {total_gb:.1f} GB\n"
                                f"📊 Used Space: {used_gb:.1f} GB ({disk_percent:.1f}%)\n\n"
                                f"{'📁 Large Files: ' + ', '.join(large_files) if large_files else ''}\n\n"
                                f"💡 Suggestions:\n"
                                f"• Clear logs: /clear_logs\n"
                                f"• Remove old backups\n"
                                f"• Optimize database"
                            )
                        else:
                            warning_msg = f"""
        ⚠️ <b>هشدار: فضای خالی دیسک کم است!</b>

        💾 فضای خالی: {free_gb:.1f} GB
        📊 کل فضا: {total_gb:.1f} GB
        📊 فضای استفاده شده: {used_gb:.1f} GB ({disk_percent:.1f}%)

        {f'📁 فایل‌های بزرگ: ' + ', '.join(large_files) if large_files else ''}

        💡 راهکارها:
        • لاگ‌ها را پاکسازی کنید: /clear_logs
        • بکاپ‌های قدیمی را حذف کنید
        • دیتابیس را بهینه‌سازی کنید
        """
                        current_bot = b or get_bot()
                        if current_bot:
                            await current_bot.send_message(
                                ADMIN_ID_INT,
                                warning_msg,
                                parse_mode=ParseMode.HTML
                            )
                            logger.info('Disk space warning sent to admin')

                except Exception as e:
                    logger.error(f"Error checking disk space: {e}", exc_info=True)

                log_sys = get_log_system()
                if log_sys:
                    try:
                        await asyncio.sleep(2)
                        await log_sys.log_admin_action(
                            ADMIN_ID_INT,
                            "Automatic weekly database cleanup",
                            details=f"Deleted {cleaned} records"
                        )
                        logger.info('Weekly cleanup log recorded in external system')
                    except Exception as e:
                        logger.warning(f"Error sending cleanup log to external system: {e}")

                try:
                    backup_dir = os.path.join(DATA_DIR, 'backups')
                    if os.path.exists(backup_dir):
                        cutoff = time.time() - (30 * 24 * 3600)  # 30 روز
                        deleted_count = 0
                        for f in os.listdir(backup_dir):
                            if f.endswith('.json') or f.endswith('.backup'):
                                file_path = os.path.join(backup_dir, f)
                                if os.path.getmtime(file_path) < cutoff:
                                    os.remove(file_path)
                                    deleted_count += 1
                        if deleted_count > 0:
                            logger.info(f"🗑 {deleted_count} old backup deleted")
                except Exception as e:
                    logger.error(f"Error cleaning up backups: {e}")

                try:
                    mem = get_memory_usage()
                    if mem.get('rss_mb', 0) > 400:
                        logger.warning(f"⚠️ High memory usage: {mem.get('rss_mb', 0):.1f} MB")
                        with _storage_lock:
                            _db_cache.clear()
                        gc.collect()
                        logger.info('🧹 Database cache cleared')
                except Exception as e:
                    logger.error(f"Error checking memory: {e}")

                record_task_finish("weekly_cleanup", started)
                logger.info('Weekly cleanup finished')
                if get_task_interval("weekly_cleanup") == 604800 and not force:
                    await sleep_interruptible("weekly_cleanup", 86400.0)
            finally:
                _weekly_cleanup_running = False

        except asyncio.CancelledError:
            logger.info('❌ Weekly cleanup task canceled')
            break
        except Exception as e:
            logger.error(f"Error during weekly cleanup: {e}", exc_info=True)
            log_sys = get_log_system()
            if log_sys:
                try:
                    await log_sys.log_error(e, "weekly_cleanup")
                    logger.info('Weekly cleanup error recorded in external system')
                except Exception as log_err:
                    logger.error(f"Error recording error log: {log_err}")
            _weekly_cleanup_running = False
            await sleep_interruptible("weekly_cleanup", 3600.0)


async def health_monitor(bot: Optional[Bot] = None):
    """مانیتورینگ سلامت ربات و ارسال گزارش بر اساس بازه تنظیمی"""
    logger.info('Health monitoring task started')

    while True:
        try:
            await wait_until_task_enabled("health_monitor")
            force = consume_force_run("health_monitor")
            if not force:
                woken = await sleep_interruptible("health_monitor", get_task_interval("health_monitor"))
                if woken and not consume_force_run("health_monitor"):
                    continue
            if not is_task_enabled("health_monitor") and not force:
                continue

            started = record_task_start("health_monitor")
            try:
                logger.info('Starting health monitoring...')
                await send_health_report(ADMIN_ID_INT, bot=bot)
                record_task_finish("health_monitor", started)
            except asyncio.CancelledError:
                raise
            except Exception as inner_err:
                record_task_finish("health_monitor", started, str(inner_err))
                raise

        except asyncio.CancelledError:
            logger.info('Health monitoring task canceled')
            break
        except Exception as e:
            logger.error(f"Error in health monitoring: {e}", exc_info=True)
            await sleep_interruptible("health_monitor", 3600.0)


async def disk_space_monitor(bot: Optional[Bot] = None):
    """هشدار فضای دیسک بر اساس بازه تنظیمی (فقط در صورت کم بودن فضا)"""
    logger.info('Disk space alert task started')
    await sleep_interruptible("disk_space_monitor", 300.0)

    while True:
        try:
            await wait_until_task_enabled("disk_space_monitor")
            force = consume_force_run("disk_space_monitor")

            if is_task_enabled("disk_space_monitor") or force:
                started = record_task_start("disk_space_monitor")
                try:
                    total, used, free = shutil.disk_usage(".")
                    free_gb = free / (1024**3)

                    if free_gb < 1.0:
                        await send_disk_warning(ADMIN_ID_INT, bot=bot)
                        logger.info(f"Disk space warning sent (free space: {free_gb:.1f} GB)")
                    else:
                        logger.info(f"Disk space is sufficient: {free_gb:.1f} GB")
                    record_task_finish("disk_space_monitor", started)
                except asyncio.CancelledError:
                    raise
                except Exception as inner_err:
                    record_task_finish("disk_space_monitor", started, str(inner_err))
                    raise

            await sleep_interruptible("disk_space_monitor", get_task_interval("disk_space_monitor"))

        except asyncio.CancelledError:
            logger.info('Disk space alert task canceled')
            break
        except Exception as e:
            logger.error(f"Error in disk space alert: {e}", exc_info=True)
            await sleep_interruptible("disk_space_monitor", 3600.0)


async def weekly_detailed_report_task(bot: Optional[Bot] = None):
    """گزارش کامل هفتگی (پیش‌فرض یکشنبه‌ها ساعت ۰۰:۰۰ یا طبق بازه انتخابی)"""
    logger.info('📅 Weekly report task started')

    last_report_week = None

    while True:
        try:
            await wait_until_task_enabled("weekly_detailed_report")
            force = consume_force_run("weekly_detailed_report")
            interval_sec = get_task_interval("weekly_detailed_report")

            if not force:
                if interval_sec == 604800:
                    now = now_tehran()
                    days_until_sunday = (6 - now.weekday()) % 7
                    next_sunday = (now + timedelta(days=days_until_sunday)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    if now.weekday() == 6 and now.hour >= 0 and now.minute >= 0:
                        next_sunday = (now + timedelta(days=7)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                    wait_seconds = max(3600.0, (next_sunday - now).total_seconds())
                else:
                    wait_seconds = float(interval_sec)

                logger.info(f"⏳ Time until weekly report: {wait_seconds / 3600:.1f} hours")
                woken = await sleep_interruptible("weekly_detailed_report", wait_seconds)
                if woken and not consume_force_run("weekly_detailed_report"):
                    continue

            if not is_task_enabled("weekly_detailed_report") and not force:
                continue

            now = now_tehran()
            current_week_key = f"{now.isocalendar()[0]}-{now.isocalendar()[1]}"

            if not force and interval_sec == 604800 and last_report_week == current_week_key:
                logger.info(f"⏳ Report for week {current_week_key} was already sent; waiting 24 hours...")
                await sleep_interruptible("weekly_detailed_report", 86400.0)
                continue

            started = record_task_start("weekly_detailed_report")
            try:
                logger.info(f"📊 Starting weekly report delivery - week {current_week_key}")
                await send_weekly_detailed_report(ADMIN_ID_INT, bot=bot)
                logger.info('✅ Weekly report sent')

                last_report_week = current_week_key

                log_sys = get_log_system()
                if log_sys:
                    try:
                        await log_sys.log_admin_action(
                            ADMIN_ID_INT,
                            "Weekly health report",
                            details=f"Week: {current_week_key} | Users: {len(users)}, Orders: {len(get_valid_orders())}"
                        )
                    except Exception as e:
                        logger.warning(f"Error recording weekly report log: {e}")

                record_task_finish("weekly_detailed_report", started)
                if interval_sec == 604800 and not force:
                    await sleep_interruptible("weekly_detailed_report", 86400.0)
            except asyncio.CancelledError:
                raise
            except Exception as inner_err:
                record_task_finish("weekly_detailed_report", started, str(inner_err))
                raise

        except asyncio.CancelledError:
            logger.info('❌ Weekly report task canceled')
            break
        except Exception as e:
            logger.error(f"❌ Error in weekly report: {e}", exc_info=True)
            await sleep_interruptible("weekly_detailed_report", 3600.0)


async def config_pool_monitor(bot: Optional[Bot] = None):
    """بررسی مخزن کانفیگ و هشدار در صورت کمبود"""
    logger.info('Configuration repository monitoring task started')
    await sleep_interruptible("config_pool_monitor", 300.0)

    while True:
        try:
            await wait_until_task_enabled("config_pool_monitor")
            force = consume_force_run("config_pool_monitor")
            if not force:
                woken = await sleep_interruptible("config_pool_monitor", get_task_interval("config_pool_monitor"))
                if woken and not consume_force_run("config_pool_monitor"):
                    continue
            if not is_task_enabled("config_pool_monitor") and not force:
                continue

            started = record_task_start("config_pool_monitor")
            try:
                if not is_senai_panel_enabled():
                    available = get_available_configs_count()
                    logger.info(f"Checking config repository: {available} configs available")

                    if available < 10:
                        logger.warning(f"⚠️ Too few configs in repository: {available} number")
                        current_bot = bot or get_bot()
                        if current_bot:
                            await current_bot.send_message(
                                ADMIN_ID_INT,
                                f"⚠️ <b>هشدار: کمبود کانفیگ در مخزن!</b>\n\n"
                                f"📦 کانفیگ موجود: {available}\n"
                                f"🔔 لطفاً هر چه سریعتر کانفیگ جدید اضافه کنید.",
                                parse_mode=ParseMode.HTML
                            )
                    else:
                        logger.debug(f"Config repository is in good condition: {available} number")
                record_task_finish("config_pool_monitor", started)
            except asyncio.CancelledError:
                raise
            except Exception as inner_err:
                record_task_finish("config_pool_monitor", started, str(inner_err))
                raise

        except asyncio.CancelledError:
            logger.info('Config repository monitoring task canceled')
            break
        except Exception as e:
            logger.error(f"Error in repository monitoring: {e}", exc_info=True)
            await sleep_interruptible("config_pool_monitor", 3600.0)


def _rotate_logs_sync() -> tuple[int, int]:
    """اجرای همگام چرخش و پاک‌سازی لاگ‌ها در ترد جداگانه"""
    base_names = ['bot_debug.log', 'events.log', 'bot_error.log']
    search_dirs = []
    for d in ('.', DATA_DIR):
        abs_d = os.path.abspath(d)
        if abs_d not in search_dirs:
            search_dirs.append(abs_d)

    log_paths = []
    for directory in search_dirs:
        for base_name in base_names:
            log_paths.append((directory, base_name, os.path.join(directory, base_name)))

    rotated_count = 0
    deleted_count = 0
    cutoff = time.time() - 30 * 24 * 3600

    for directory, base_name, log_path in log_paths:
        if os.path.exists(log_path):
            size = os.path.getsize(log_path)
            size_mb = size / (1024 * 1024)
            logger.info(f"Checking log file {log_path}: {size_mb:.1f} MB")

            if size > 50 * 1024 * 1024:  # 50 MB
                backup_name = f"{log_path}.{now_tehran().strftime('%Y%m%d_%H%M%S')}.old"
                try:
                    os.rename(log_path, backup_name)
                except PermissionError:
                    shutil.copy2(log_path, backup_name)
                    with open(log_path, 'w', encoding='utf-8'):
                        pass
                rotated_count += 1
                logger.info(f"🔄 Log rotation: {log_path} -> {backup_name}")

        if os.path.isdir(directory):
            for old_file in os.listdir(directory):
                if old_file.startswith(base_name) and old_file.endswith('.old'):
                    file_path = os.path.join(directory, old_file)
                    try:
                        if os.path.getmtime(file_path) < cutoff:
                            os.remove(file_path)
                            deleted_count += 1
                            logger.debug(f"🗑 Deleting old log file: {file_path}")
                    except Exception as rm_err:
                        logger.warning(f"Failed to delete old log file {file_path} : {rm_err}")

    return rotated_count, deleted_count


async def log_rotation():
    """چرخش خودکار لاگ‌ها بر اساس بازه تنظیمی"""
    logger.info('Log rotation task started')

    while True:
        try:
            await wait_until_task_enabled("log_rotation")
            force = consume_force_run("log_rotation")
            if not force:
                woken = await sleep_interruptible("log_rotation", get_task_interval("log_rotation"))
                if woken and not consume_force_run("log_rotation"):
                    continue
            if not is_task_enabled("log_rotation") and not force:
                continue

            started = record_task_start("log_rotation")
            try:
                logger.info('Starting log rotation...')
                rotated_count, deleted_count = await asyncio.to_thread(_rotate_logs_sync)
                logger.info(f"Log rotation completed: {rotated_count} rotated files, {deleted_count} old files deleted")
                record_task_finish("log_rotation", started)
            except asyncio.CancelledError:
                raise
            except Exception as inner_err:
                record_task_finish("log_rotation", started, str(inner_err))
                raise

        except asyncio.CancelledError:
            logger.info('Log rotation task canceled')
            break
        except Exception as e:
            logger.error(f"Error during log rotation: {e}", exc_info=True)
            await sleep_interruptible("log_rotation", 24 * 3600.0)


async def panel_limits_reset():
    """ریست خودکار محدودیت‌های پنل بر اساس بازه تنظیمی"""
    logger.info('Panel limits reset task started')

    while True:
        try:
            await wait_until_task_enabled("panel_limits_reset")
            force = consume_force_run("panel_limits_reset")
            if not force:
                woken = await sleep_interruptible("panel_limits_reset", get_task_interval("panel_limits_reset"))
                if woken and not consume_force_run("panel_limits_reset"):
                    continue
            if not is_task_enabled("panel_limits_reset") and not force:
                continue

            started = record_task_start("panel_limits_reset")
            try:
                logger.info('Starting panel rate-limit reset...')

                if callable(reset_panel_rate_limits):
                    await reset_panel_rate_limits()
                    logger.info('🔄 Panel rate limits successfully reset')
                else:
                    logger.warning('Function reset_panel_rate_limits is unavailable')
                record_task_finish("panel_limits_reset", started)
            except asyncio.CancelledError:
                raise
            except Exception as inner_err:
                record_task_finish("panel_limits_reset", started, str(inner_err))
                raise

        except asyncio.CancelledError:
            logger.info('Panel rate-limit reset task canceled')
            break
        except Exception as e:
            logger.error(f"Error resetting panel rate limits: {e}", exc_info=True)
            await sleep_interruptible("panel_limits_reset", 3600.0)


async def memory_monitor():
    """بررسی مصرف حافظه و پاکسازی در صورت نیاز"""
    logger.info('Memory monitoring task started')
    await sleep_interruptible("memory_monitor", 60.0)  # تاخیر اولیه

    while True:
        try:
            await wait_until_task_enabled("memory_monitor")
            force = consume_force_run("memory_monitor")
            if not force:
                woken = await sleep_interruptible("memory_monitor", get_task_interval("memory_monitor"))
                if woken and not consume_force_run("memory_monitor"):
                    continue

            started = record_task_start("memory_monitor")
            try:
                mem = get_memory_usage()
                logger.debug(f"Memory usage: {mem['rss_mb']:.1f} MB ({mem['percent']:.1f}%)")

                if mem['rss_mb'] > 500 or force:
                    logger.warning(f"⚠️ High memory usage: {mem['rss_mb']:.1f} MB - cleaning up...")
                    with _storage_lock:
                        cache_size_before = len(_db_cache)
                        _db_cache.clear()
                    cleaned = cleanup_expired_states()
                    gc.collect()

                    mem_after = get_memory_usage()
                    logger.info(f"✅ Memory cleanup: cache {cache_size_before} -> 0, statuses cleared: {cleaned}")
                    logger.info(f"Memory usage after cleanup: {mem_after['rss_mb']:.1f} MB (reduced by {mem['rss_mb'] - mem_after['rss_mb']:.1f} MB)")
                record_task_finish("memory_monitor", started)
            except asyncio.CancelledError:
                raise
            except Exception as inner_err:
                record_task_finish("memory_monitor", started, str(inner_err))
                raise

        except asyncio.CancelledError:
            logger.info('Memory monitoring task canceled')
            break
        except Exception as e:
            logger.error(f"Error in memory monitoring: {e}", exc_info=True)
            await sleep_interruptible("memory_monitor", 300.0)


async def daily_usage_collector_worker():
    """ورکر جمع‌آوری روزانه مصرف ترافیک کلاینت‌ها"""
    # استگر اولیه برای جلوگیری از هم‌زمانی با alert_system در لحظه استارت
    await sleep_interruptible("daily_usage_collector", 20.0)

    def _get_approved_emails():
        valid = get_valid_orders()
        emails = set()
        for o in valid.values():
            e = get_order_client_email(o)
            if e:
                emails.add(str(e).strip())
        return emails

    await usage_collector.start(
        get_inbounds_func=xui_get_inbounds,
        get_approved_emails_func=_get_approved_emails,
        interval_seconds=get_task_interval("daily_usage_collector"),
        get_client_traffic_func=xui_get_client_traffic,
    )


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    """ایجاد و راه‌اندازی تمام تسک‌های پس‌زمینه با نام‌گذاری دقیق جهت مانیتورینگ"""
    set_bot(bot)
    from routers.admin_tools import auto_log_cleanup
    from services.server_guard import server_guard_worker

    tasks = [
        asyncio.create_task(cleanup_expired_states_task(), name="cleanup_expired_states"),
        asyncio.create_task(sync_deleted_configs_task(), name="sync_deleted_configs"),
        asyncio.create_task(auto_backup_task(bot=bot), name="auto_backup"),
        asyncio.create_task(weekly_cleanup(bot=bot), name="weekly_cleanup"),
        asyncio.create_task(health_monitor(bot=bot), name="health_monitor"),
        asyncio.create_task(disk_space_monitor(bot=bot), name="disk_space_monitor"),
        asyncio.create_task(config_pool_monitor(bot=bot), name="config_pool_monitor"),
        asyncio.create_task(log_rotation(), name="log_rotation"),
        asyncio.create_task(panel_limits_reset(), name="panel_limits_reset"),
        asyncio.create_task(weekly_detailed_report_task(bot=bot), name="weekly_detailed_report"),
        asyncio.create_task(memory_monitor(), name="memory_monitor"),
        asyncio.create_task(auto_log_cleanup(), name="auto_log_cleanup"),
        asyncio.create_task(daily_usage_collector_worker(), name="daily_usage_collector"),
        asyncio.create_task(server_guard_worker(bot=bot), name="server_guard"),
    ]

    logger.info(f"✅ {len(tasks)} Background tasks created:")
    for task in tasks:
        logger.info(f"  - {task.get_name()}")

    return tasks

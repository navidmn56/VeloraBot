# alert_system.py
from strings import t
import asyncio
import logging
import json
import math
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, Awaitable
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import TEHRAN_TZ, now_tehran, now_tehran_iso

logger = logging.getLogger(__name__)

RLM = "\u200F"
PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')

def to_persian_number(text) -> str:
    if text is None:
        return ''
    return str(text).translate(PERSIAN_DIGITS)


class AlertSystem:
    """سیستم مدیریت هشدارهای حجم و انقضای سرویس با ارسال یکبار برای هر آستانه"""
    
    def __init__(
        self,
        bot,
        orders_getter,
        user_getter,
        extract_email_func=None,           # نگه‌داری برای سازگاری
        cache_file="alert_cache.json",
        log_system=None,
        find_email_by_sub_id_func=None,    # ✅ جدید: async function
        update_order_func=None              # ✅ جدید: برای ذخیره email
    ):
        self.bot = bot
        self.get_orders = orders_getter
        self.get_user = user_getter
        self.extract_email = extract_email_func
        self.log_system = log_system
        self.find_email_by_sub_id = find_email_by_sub_id_func  # ✅
        self.update_order = update_order_func                    # ✅
        
        self.cache_file = cache_file
        
        self.volume_alert_cache = {}
        self.expiry_alert_cache = {}
        self.sent_alerts_history = {}
        self.service_info_cache = {}
        
        self._load_cache_from_disk()
        
        self.check_interval = 300
        self.cooldown_minutes = 120
        self.enabled = True
        
        # ✅ آستانه‌ها
        self.volume_thresholds = [10, 5]
        self.expiry_warnings = [7, 3, 1]
        self.test_volume_thresholds = [30]
        self.test_expiry_warnings = [0.25]
        
        self._lock = asyncio.Lock()
    
    # ═══════════════════════════════════════════
    # کش
    # ═══════════════════════════════════════════
    
    def _load_cache_from_disk(self):
        """بارگذاری کش از فایل"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    self.volume_alert_cache = {
                        k: datetime.fromisoformat(v) 
                        for k, v in data.get('volume_alerts', {}).items()
                        if isinstance(v, str)
                    }
                    self.expiry_alert_cache = {
                        k: datetime.fromisoformat(v) 
                        for k, v in data.get('expiry_alerts', {}).items()
                        if isinstance(v, str)
                    }
                    self.sent_alerts_history = data.get('history', {})
                    self.service_info_cache = data.get('service_info', {})
                    
                    logger.info(
                        f"Cache loaded: "
                        f"{len(self.volume_alert_cache)} volume, "
                        f"{len(self.expiry_alert_cache)} expiry"
                    )
            else:
                logger.info("Cache file not found, starting empty")
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            self.volume_alert_cache = {}
            self.expiry_alert_cache = {}
            self.sent_alerts_history = {}
            self.service_info_cache = {}
    
    def _save_cache_to_disk(self):
        """ذخیره کش در فایل"""
        try:
            data = {
                'volume_alerts': {
                    k: v.isoformat() 
                    for k, v in self.volume_alert_cache.items()
                    if isinstance(v, datetime)
                },
                'expiry_alerts': {
                    k: v.isoformat() 
                    for k, v in self.expiry_alert_cache.items()
                    if isinstance(v, datetime)
                },
                'history': self.sent_alerts_history,
                'service_info': self.service_info_cache,
                'last_updated': now_tehran_iso()
            }
            
            temp_file = f"{self.cache_file}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            os.replace(temp_file, self.cache_file)
            
        except Exception as e:
            logger.error(f"Error saving cache: {e}")
    
    # ═══════════════════════════════════════════
    # ✅ تابع کمکی جدید: دریافت email از سفارش
    # ═══════════════════════════════════════════
    
    async def _resolve_email(self, order: dict) -> Optional[str]:
        """
        دریافت email کلاینت از سفارش به صورت امن:
        ۱. اول از فیلد email مستقیم سفارش
        ۲. اگه نبود، از subId → email با query به پنل
        ۳. اگه پیدا شد، توی سفارش ذخیره می‌شه تا بار بعد سریع‌تر باشه
        
        Returns:
            email یا None
        """
        order_id = order.get('order_id')
        
        # ─── مرحله ۱: از فیلد email مستقیم ───
        email = order.get('email', '')
        if email and str(email).strip():
            return str(email).strip()
        
        # ─── مرحله ۲: از subId ───
        sub_link = order.get('sub_link', '') or order.get('config_link', '')
        if not sub_link:
            logger.debug(f"Order #{order_id}: No email or link available")
            return None

        # استخراج subId از آخر لینک
        try:
            sub_id = sub_link.rstrip('/').split('/')[-1]
            if not sub_id:
                return None
        except Exception:
            return None

        # اگه تابع lookup موجود نباشه، برنگردون
        if not self.find_email_by_sub_id:
            logger.warning(
                f"Order #{order_id}: Missing email and "
                f"find_email_by_sub_id function is not configured"
            )
            return None

        # ─── تلاش برای پیدا کردن email ───
        try:
            found_email = await self.find_email_by_sub_id(sub_id)
            if found_email:
                logger.info(
                    f"[resolve_email] Order #{order_id}: "
                    f"{sub_id[:20]}... -> {found_email}"
                )
                # ✅ ذخیره توی سفارش برای بارهای بعد
                if self.update_order and order_id:
                    try:
                        self.update_order(order_id, email=found_email)
                        logger.info(f"Email saved for order #{order_id}")
                    except Exception as e:
                        logger.warning(f"Error saving email for order #{order_id}: {e}")
                return found_email
            else:
                logger.debug(f"Order #{order_id}: Email not found for subId {sub_id[:20]}...")
                return None
        except Exception as e:
            logger.error(f"[resolve_email] Error for order #{order_id}: {e}")
            return None
    
    # ═══════════════════════════════════════════
    # لاگ
    # ═══════════════════════════════════════════
    
    async def _log_alert(self, alert_type: str, order: dict, details: str):
        """ارسال لاگ هشدار به کانال لاگ"""
        if not self.log_system:
            return
        
        try:
            user_id = order.get('user_id')
            order_id = order.get('order_id')
            is_test = order.get('is_test', False) or order.get('type') == 'test'
            
            type_emoji = "🎁" if is_test else "📡"
            type_text = "Welcome service" if is_test else "Normal"
            
            if alert_type == 'volume':
                emoji = "⚠️"
                title = "Volume Warning"
            elif alert_type == 'volume_exhausted':
                emoji = "❌"
                title = "Volume Exhausted"
            elif alert_type == 'expiry':
                emoji = "⏰"
                title = "Expiry Warning"
            else:
                emoji = "❌"
                title = "Service Expired"
            
            text = f"""
{emoji} <b>{title}</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>User:</b> <code>{user_id}</code>
🆔 <b>Order:</b> #{order_id}
{type_emoji} <b>Type:</b> {type_text}
📄 <b>Details:</b> {details}
"""
            await self.log_system.send_log(text)
        except Exception as e:
            logger.error(f"Error sending alert log: {e}")
    
    # ═══════════════════════════════════════════
    # Worker
    # ═══════════════════════════════════════════
    
    async def run_alert_worker(self):
        """کارگر پس‌زمینه"""
        logger.info("Alert system started (one-time per threshold)")
        
        self._save_cache_to_disk()
        
        while True:
            try:
                if self.enabled:
                    await self.check_all_services()
                    self._save_cache_to_disk()
                    
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                self._save_cache_to_disk()
                logger.info("Alert system stopped")
                break
            except Exception as e:
                logger.error(f"Error in alert system: {e}", exc_info=True)
                self._save_cache_to_disk()
                await asyncio.sleep(60)
    
    # ═══════════════════════════════════════════
    # ✅ اصلاح اصلی: check_all_services
    # ═══════════════════════════════════════════
    
    async def check_all_services(self):
        """بررسی تمام سرویس‌ها"""
        async with self._lock:
            try:
                valid_orders = self.get_orders()
                if not valid_orders:
                    return
                
                # بررسی تمام سفارش‌های سرویس فعال/تایید شده (بدون سفارش‌های لغوشده، ردشده، مالی یا تمدیدی)
                approved_orders = [
                    o for o in valid_orders.values()
                    if isinstance(o, dict)
                    and o.get('user_id')
                    and o.get('status') not in (
                        'cancelled', 'rejected', 'deleted',
                        'pending', 'awaiting_payment', 'pending_balance_charge'
                    )
                    and o.get('type') not in ('balance', 'extend')
                    and not o.get('is_extend')
                    and not o.get('parent_order_id')
                    and (o.get('config_link') or o.get('status') == 'approved')
                ]
                
                logger.debug(f"Checking {len(approved_orders)} services")
                
                for order in approved_orders:
                    order_id = order.get('order_id')
                    user_id = order.get('user_id')
                    
                    if not order_id or not user_id:
                        continue
                    
                    try:
                        email = await self._resolve_email(order)
                        client_info = None

                        if email:
                            try:
                                from services.panel_api import xui_get_client_info, xui_get_client_traffic
                            except ImportError:
                                from main import xui_get_client_info, xui_get_client_traffic

                            try:
                                client_info = await xui_get_client_info(email)
                            except Exception as client_err:
                                logger.warning(f"Order #{order_id}: error retrieving client_info for {email}: {client_err}")

                        if client_info and isinstance(client_info, dict):
                            # تشخیص تمدید
                            await self._check_service_renewal(order, client_info, email)
                            
                            # دریافت ترافیک
                            traffic_data = None
                            try:
                                traffic_data = await xui_get_client_traffic(email)
                                if traffic_data and not isinstance(traffic_data, dict):
                                    traffic_data = None
                            except Exception:
                                pass
                            
                            # بررسی حجم و انقضا بر اساس داده‌های دقیق پنل
                            await self._check_volume_alert(order, client_info, traffic_data)
                            await self._check_expiry_alert(order, client_info)
                        else:
                            # فال‌بک: در صورتی که کلاینت در پنل نبود یا ایمیل ست نشده بود، بررسی انقضا از طریق دیتابیس سفارش
                            await self._check_fallback_order_expiry(order)
                        
                    except Exception as e:
                        logger.error(
                            f"Error checking service #{order_id}: {e}",
                            exc_info=True
                        )
                        
            except Exception as e:
                logger.error(f"Error in check_all_services: {e}", exc_info=True)

    async def _check_fallback_order_expiry(self, order: dict):
        """بررسی فال‌بک انقضای سفارش از روی تاریخ انقضا یا تاریخ تایید و مدت پکیج در صورت عدم دسترسی به پنل"""
        order_id = order.get('order_id')
        user_id = order.get('user_id')
        if not order_id or not user_id:
            return

        expire_str = order.get('expire_date')
        if expire_str:
            try:
                exp_val = str(expire_str).strip().replace('Z', '+00:00')
                expiry_dt = datetime.fromisoformat(exp_val) if 'T' in exp_val else datetime.strptime(exp_val, "%Y-%m-%d %H:%M:%S")
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=TEHRAN_TZ)
                expiry_ms = int(expiry_dt.timestamp() * 1000)
                await self._check_expiry_alert(order, {'expiryTime': expiry_ms})
                return
            except Exception:
                pass

        approved_str = order.get('approved_date') or order.get('date') or order.get('created_at')
        days = int(order.get('days') or 0)
        if not approved_str or days <= 0:
            return

        try:
            str_val = str(approved_str).strip()
            if 'T' in str_val:
                approved_dt = datetime.fromisoformat(str_val)
            else:
                approved_dt = datetime.strptime(str_val, "%Y-%m-%d %H:%M:%S")

            if approved_dt.tzinfo is None:
                approved_dt = approved_dt.replace(tzinfo=TEHRAN_TZ)

            expiry_dt = approved_dt + timedelta(days=days)
            expiry_ms = int(expiry_dt.timestamp() * 1000)
            await self._check_expiry_alert(order, {'expiryTime': expiry_ms})
        except Exception as e:
            logger.debug(f"Order #{order_id}: fallback expiry calculation skipped: {e}")
    
    # ═══════════════════════════════════════════
    # تشخیص تمدید
    # ═══════════════════════════════════════════
    
    def _is_bot_owned_service(self, order: dict, email: str) -> bool:
        user_id = str(order.get('user_id', '')).strip()
        email = str(email or '').strip().lower()
        if not user_id or not email:
            return False

        order_email = str(order.get('email') or '').strip().lower()
        if order_email == email:
            return True

        prefixes = (
            f"user{user_id}_",
            f"u{user_id}_",
            f"test_{user_id}_",
        )
        return any(
            email.startswith(prefix) and email[len(prefix):]
            for prefix in prefixes
        )

    def _service_cache_key(self, email: str) -> str:
        return f"email:{email.strip().lower()}"

    async def _record_service_renewal(
        self, order: dict, email: str, previous: dict, current: dict,
        allow_non_increase: bool = False, require_bot_owned: bool = True
    ) -> bool:
        if require_bot_owned and not self._is_bot_owned_service(order, email):
            return False

        order_id = order.get('order_id')
        cache_key = self._service_cache_key(email)
        cached = self.service_info_cache.get(cache_key, {})
        current_total = current.get('totalGB', 0)
        current_expiry = current.get('expiryTime', 0)

        if (
            cached.get('last_renewal')
            and cached.get('totalGB') == current_total
            and cached.get('expiryTime') == current_expiry
        ):
            return False

        changes = []
        previous_total = previous.get('totalGB', 0)
        previous_expiry = previous.get('expiryTime', 0)
        volume_increased = previous_total > 0 and (
            current_total == 0 or current_total > previous_total
        )
        expiry_extended = current_expiry > previous_expiry
        if not allow_non_increase and not (volume_increased or expiry_extended):
            return False

        if current_total != previous_total:
            changes.append(
                f"📦 Volume: {self._format_bytes(previous_total)} → "
                f"{self._format_bytes(current_total)}"
            )
        if current_expiry != previous_expiry:
            changes.append(
                f"⏱ Expiry: {self._format_timestamp(previous_expiry)} → "
                f"{self._format_timestamp(current_expiry)}"
            )

        changes_text = "\n".join(changes)
        logger.info(f"Service #{order_id} renewed:\n{changes_text}")

        if self.log_system:
            text = f"""
🔄 <b>Service Renewed</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>User:</b> <code>{order.get('user_id')}</code>
🆔 <b>Order:</b> #{order_id}
{changes_text}
"""
            await self.log_system.send_log(text)

        self.volume_alert_cache = {
            key: value for key, value in self.volume_alert_cache.items()
            if not key.startswith(f"vol_{order_id}_")
        }
        self.expiry_alert_cache = {
            key: value for key, value in self.expiry_alert_cache.items()
            if not key.startswith(f"exp_{order_id}_")
        }
        self.sent_alerts_history = {
            key: value for key, value in self.sent_alerts_history.items()
            if not key.startswith(f"vol_{order_id}_")
            and not key.startswith(f"exp_{order_id}_")
        }
        now = now_tehran_iso()
        self.service_info_cache[cache_key] = {
            'totalGB': current_total,
            'expiryTime': current_expiry,
            'email': email,
            'last_updated': now,
            'last_renewal': now
        }
        self._save_cache_to_disk()
        return True

    async def record_service_renewal(
        self, order: dict, email: str, previous: dict, current: dict
    ) -> bool:
        async with self._lock:
            return await self._record_service_renewal(
                order, email, previous, current,
                allow_non_increase=True, require_bot_owned=False
            )

    async def _check_service_renewal(self, order: dict, client_info: dict, email: str):
        """تشخیص تمدید سرویس"""
        if not self._is_bot_owned_service(order, email):
            return

        cache_key = self._service_cache_key(email)
        current = {
            'totalGB': client_info.get('totalGB', 0),
            'expiryTime': client_info.get('expiryTime', 0)
        }
        previous = self.service_info_cache.get(cache_key)

        if not previous:
            self.service_info_cache[cache_key] = {
                **current,
                'email': email,
                'first_seen': now_tehran_iso(),
                'last_updated': now_tehran_iso()
            }
            self._save_cache_to_disk()
            return

        previous_total = previous.get('totalGB', 0)
        previous_expiry = previous.get('expiryTime', 0)
        is_volume_increased = previous_total > 0 and (
            current['totalGB'] == 0 or current['totalGB'] > previous_total
        )
        is_expiry_extended = current['expiryTime'] > previous_expiry

        if is_volume_increased or is_expiry_extended:
            await self._record_service_renewal(order, email, previous, current)
        else:
            previous.update(current)
            previous['email'] = email
            previous['last_updated'] = now_tehran_iso()
            self._save_cache_to_disk()
    
    # ═══════════════════════════════════════════
    # Formatters
    # ═══════════════════════════════════════════
    
    def _format_bytes(self, bytes_value: int) -> str:
        """فرمت بایت"""
        if bytes_value == 0:
            return "Unlimited"
        
        gb = bytes_value / (1024**3)
        if gb >= 1:
            return f"{gb:.2f} GB"
        else:
            mb = bytes_value / (1024**2)
            return f"{mb:.0f} MB"
    
    def _format_timestamp(self, timestamp: int) -> str:
        """فرمت timestamp"""
        try:
            if timestamp > 10000000000:
                dt = datetime.fromtimestamp(timestamp / 1000)
            else:
                dt = datetime.fromtimestamp(timestamp)
            return dt.strftime('%Y-%m-%d %H:%M')
        except Exception:
            return "Unknown"
    
    def _format_volume(self, gb: float, lang: str = "fa") -> str:
        """فرمت حجم"""
        if gb >= 1:
            return t('gb_b755d45a80', lang, fa_parts=lambda: (f"{to_persian_number(f'{gb:.2f}')}",), en_parts=lambda: (f'{gb:.2f}',))
        elif gb >= 0.001:
            mb = gb * 1024
            return t('mb_4062381407', lang, fa_parts=lambda: (f"{to_persian_number(f'{mb:.0f}')}",), en_parts=lambda: (f'{mb:.0f}',))
        else:
            return t('0_mb_b7659fbfbd', lang, fa_parts=lambda: (f"{to_persian_number('0')}",))
    
    # ═══════════════════════════════════════════
    # Cache Management
    # ═══════════════════════════════════════════
    
    def _clear_order_cache(self, order_id: int):
        """پاک کردن کش یک سفارش"""
        self.volume_alert_cache = {
            k: v for k, v in self.volume_alert_cache.items() 
            if not k.startswith(f"vol_{order_id}_")
        }
        
        self.expiry_alert_cache = {
            k: v for k, v in self.expiry_alert_cache.items() 
            if not k.startswith(f"exp_{order_id}_")
        }
        
        self.sent_alerts_history = {
            k: v for k, v in self.sent_alerts_history.items()
            if not k.startswith(f"vol_{order_id}_") and 
               not k.startswith(f"exp_{order_id}_")
        }
        
        logger.info(f"Cache cleared for order #{order_id}")
    
    def _should_send_once(self, cache_key: str) -> bool:
        """بررسی ارسال"""
        if cache_key in self.volume_alert_cache:
            return False
        
        if cache_key in self.expiry_alert_cache:
            return False
        
        if cache_key in self.sent_alerts_history:
            return False
        
        return True
    
    def _record_alert(self, cache_key: str, cache: dict, alert_type: str, order_id: int):
        """ثبت هشدار"""
        now = now_tehran()
        
        cache[cache_key] = now
        
        existing = self.sent_alerts_history.get(cache_key)
        total_sent = 1
        
        if isinstance(existing, dict):
            total_sent = existing.get('total_sent', 0) + 1
        
        self.sent_alerts_history[cache_key] = {
            'last_sent': now.isoformat(),
            'type': alert_type,
            'order_id': order_id,
            'total_sent': total_sent,
            'delivered': True
        }
        
        self._save_cache_to_disk()
    
    # ═══════════════════════════════════════════
    # Expiry Alert
    # ═══════════════════════════════════════════
    
    async def _check_expiry_alert(self, order: dict, client_info: dict):
        """بررسی هشدار انقضا"""
        order_id = order.get('order_id')
        is_test = order.get('is_test', False) or order.get('type') == 'test'
        
        volume_exhausted_key = f"vol_{order_id}_exhausted"
        if (volume_exhausted_key in self.volume_alert_cache or 
            volume_exhausted_key in self.sent_alerts_history):
            logger.debug(f"Order #{order_id}: Volume already exhausted, skipping expiry alert")
            return
        
        expiry_time = client_info.get('expiryTime', 0)
        if not isinstance(expiry_time, (int, float)) or expiry_time == 0:
            return
        
        # ✅ "Start After First Use" - مقدار منفی
        if expiry_time < 0:
            logger.debug(f"Order #{order_id}: Start After First Use - not started yet")
            return
        
        try:
            if expiry_time > 10000000000:
                expiry_date = datetime.fromtimestamp(expiry_time / 1000, TEHRAN_TZ)
            else:
                expiry_date = datetime.fromtimestamp(expiry_time, TEHRAN_TZ)
        except Exception:
            return
        
        now = now_tehran()
        time_left = expiry_date - now
        hours_left = time_left.total_seconds() / 3600
        
        days_left = int(math.ceil(hours_left / 24)) if hours_left > 24 else 0
        
        label = None
        alert_type = 'expiry'
        
        if hours_left <= 0:
            label = "expired"
            alert_type = 'expired'
        elif is_test:
            if hours_left <= 6:
                label = "6h"
        else:
            order_days = int(order.get('days') or 0)
            thresholds_sorted = sorted(self.expiry_warnings)
            
            for threshold in thresholds_sorted:
                # برای پکیج‌های کوتاه‌مدت (مثلاً ۳ یا ۷ روزه)، هشدار بلافاصله پس از خرید ارسال نمی‌شود
                if order_days > 0 and threshold >= order_days:
                    continue
                threshold_hours = threshold * 24
                if hours_left <= threshold_hours:
                    label = f"{int(threshold)}d"
                    break
        
        if not label:
            return
        
        cache_key = f"exp_{order_id}_{label}"
        
        if self._should_send_once(cache_key):
            sent_successfully = await self._notify_expiry(
                order, days_left, hours_left, is_test, label
            )
            
            if sent_successfully:
                self._record_alert(cache_key, self.expiry_alert_cache, alert_type, order_id)
                logger.info(f"Expiry alert ({label}) sent for order #{order_id}")
                
                details = "expired" if label == "expired" else f"{label} remaining"
                await self._log_alert(alert_type, order, details)
            else:
                logger.warning(f"Expiry alert ({label}) not sent for order #{order_id}")
    
    # ═══════════════════════════════════════════
    # Volume Alert
    # ═══════════════════════════════════════════
    
    async def _check_volume_alert(
        self, 
        order: dict, 
        client_info: dict, 
        traffic_data: Optional[dict]
    ):
        """بررسی هشدار حجم"""
        order_id = order.get('order_id')
        is_test = order.get('is_test', False) or order.get('type') == 'test'
        
        expiry_expired_key = f"exp_{order_id}_expired"
        if (expiry_expired_key in self.expiry_alert_cache or 
            expiry_expired_key in self.sent_alerts_history):
            logger.debug(f"Order #{order_id}: Service already expired, skipping volume alert")
            return
        
        total_bytes = client_info.get('totalGB', 0)
        if not isinstance(total_bytes, (int, float)) or total_bytes == 0:
            return
        
        total_gb = total_bytes / (1024**3)
        
        up_bytes = 0
        down_bytes = 0
        if traffic_data and isinstance(traffic_data, dict):
            up_bytes = traffic_data.get('up', 0)
            down_bytes = traffic_data.get('down', 0)
            if not isinstance(up_bytes, (int, float)):
                up_bytes = 0
            if not isinstance(down_bytes, (int, float)):
                down_bytes = 0
        
        used_gb = (up_bytes + down_bytes) / (1024**3)
        remaining_gb = max(0, total_gb - used_gb)
        remaining_percent = (remaining_gb / total_gb) * 100
        
        label = None
        alert_type = 'volume'
        
        if remaining_gb <= 0 or remaining_percent <= 0:
            label = "exhausted"
            alert_type = 'volume_exhausted'
        elif is_test:
            if remaining_percent <= 30:
                label = "30%"
        else:
            thresholds_sorted = sorted(self.volume_thresholds)
            
            for threshold in thresholds_sorted:
                if remaining_percent <= threshold:
                    label = f"{threshold}%"
                    break
        
        if not label:
            return
        
        cache_key = f"vol_{order_id}_{label}"
        
        if self._should_send_once(cache_key):
            sent_successfully = await self._notify_volume(
                order, used_gb, total_gb, remaining_gb, 
                remaining_percent, label, is_test
            )
            
            if sent_successfully:
                self._record_alert(cache_key, self.volume_alert_cache, alert_type, order_id)
                logger.info(f"Volume alert ({label}) sent for order #{order_id}")
                
                if label == "exhausted":
                    details = f"Volume exhausted ({used_gb:.2f}GB of {total_gb:.2f}GB)"
                else:
                    details = f"{label} remaining ({used_gb:.2f}GB of {total_gb:.2f}GB)"
                
                await self._log_alert(alert_type, order, details)
            else:
                logger.warning(f"Volume alert ({label}) not sent for order #{order_id}")
    
    # ═══════════════════════════════════════════
    # Notifications
    # ═══════════════════════════════════════════

    def _build_alert_keyboard(self, order_id: int, lang: str, is_test: bool) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=(
                    t('buy_service_21bce537d0', lang)
                ) if is_test else (
                    t('renew_this_service_36501ac148', lang)
                ),
                callback_data="buy_service" if is_test else f"extend_service_{order_id}",
                style="success",
            )],
            [
                InlineKeyboardButton(
                    text=t('view_config_ad93d47d82', lang),
                    callback_data=f"view_config_{order_id}",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text=t('main_menu_0cdd07a7cc', lang),
                    callback_data="back_to_main",
                    style="danger",
                ),
            ],
        ])
    
    async def _notify_volume(
        self, 
        order: dict, 
        used_gb: float, 
        total_gb: float, 
        remaining_gb: float, 
        remaining_percent: float, 
        threshold_label: str, 
        is_test: bool
    ) -> bool:
        """ارسال هشدار حجم"""
        user_id = order.get('user_id')
        order_id = order.get('order_id')
        
        user = self.get_user(user_id)
        lang = user.get('lang', 'fa') if user else 'fa'
        
        used_display = self._format_volume(used_gb, lang)
        total_display = self._format_volume(total_gb, lang)
        remaining_display = self._format_volume(remaining_gb, lang)
        exhausted = threshold_label == "exhausted"
        service_name = "سرویس خوشامد" if is_test else "سرویس"
        service_name_en = "welcome service" if is_test else "service"

        if exhausted:
            if is_test:
                text = (
                    t('b_welcome_service_data_allow_a1a6e1056d', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f'{RLM}', f'{to_persian_number(order_id)}', f'{RLM}', f'{used_display}', f'{total_display}', f'{RLM}'), en_parts=lambda: (f'{order_id}', f'{used_display}', f'{total_display}'))
                )
            else:
                text = (
                    t('b_service_data_allowance_exh_68f27342d0', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f'{service_name}', f'{RLM}', f'{to_persian_number(order_id)}', f'{RLM}', f'{used_display}', f'{total_display}', f'{RLM}', f'{remaining_display}', f'{RLM}'), en_parts=lambda: (f'{service_name_en}', f'{order_id}', f'{used_display}', f'{total_display}', f'{remaining_display}'))
                )
        else:
            if is_test:
                text = (
                    t('b_welcome_service_data_is_ru_d59f4522e3', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f'{RLM}', f'{to_persian_number(order_id)}', f'{RLM}', f'{used_display}', f'{total_display}', f'{RLM}', f'{remaining_display}', f"{to_persian_number(f'{remaining_percent:.1f}')}", f'{RLM}'), en_parts=lambda: (f'{order_id}', f'{used_display}', f'{total_display}', f'{remaining_display}', f'{remaining_percent:.1f}'))
                )
            else:
                text = (
                    t('b_service_data_is_running_lo_4da6da21d9', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f'{service_name}', f'{RLM}', f'{to_persian_number(order_id)}', f'{RLM}', f'{used_display}', f'{total_display}', f'{RLM}', f'{remaining_display}', f"{to_persian_number(f'{remaining_percent:.1f}')}", f'{RLM}'), en_parts=lambda: (f'{service_name_en}', f'{order_id}', f'{used_display}', f'{total_display}', f'{remaining_display}', f'{remaining_percent:.1f}'))
                )
        
        keyboard = self._build_alert_keyboard(order_id, lang, is_test)

        try:
            await self.bot.send_message(
                user_id, text, parse_mode="HTML", reply_markup=keyboard
            )
            logger.info(f"Volume alert {threshold_label} sent for order #{order_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending volume alert to user {user_id}: {e}")
            return False
    
    async def _notify_expiry(
        self, 
        order: dict, 
        days_left: int, 
        hours_left: float, 
        is_test: bool, 
        notify_label: str
    ) -> bool:
        """ارسال هشدار انقضا"""
        user_id = order.get('user_id')
        order_id = order.get('order_id')
        
        user = self.get_user(user_id)
        lang = user.get('lang', 'fa') if user else 'fa'

        if notify_label == "expired":
            time_left = t('expired_756d905f6f', lang)
        elif days_left > 0:
            time_left = t('days_a6a4667661', lang, fa_parts=lambda: (f'{to_persian_number(days_left)}',), en_parts=lambda: (f'{days_left}',))
        elif hours_left >= 1:
            display_hours = int(round(hours_left))
            time_left = t('hours_d0eee7cbea', lang, fa_parts=lambda: (f'{to_persian_number(display_hours)}',), en_parts=lambda: (f'{display_hours}',))
        else:
            minutes_left = max(1, int(round(hours_left * 60)))
            time_left = t('minutes_e0868f9f26', lang, fa_parts=lambda: (f'{to_persian_number(minutes_left)}',), en_parts=lambda: (f'{minutes_left}',))

        service_name = "سرویس خوشامد" if is_test else "سرویس"
        service_name_en = "welcome service" if is_test else "service"
        expired = notify_label == "expired"

        if expired:
            if is_test:
                text = (
                    t('b_your_welcome_service_has_e_40a46438c1', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f'{RLM}', f'{to_persian_number(order_id)}', f'{RLM}'), en_parts=lambda: (f'{order_id}',))
                )
            else:
                text = (
                    t('b_service_validity_has_expir_a2a1ec3bc8', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f'{service_name}', f'{RLM}', f'{to_persian_number(order_id)}', f'{RLM}'), en_parts=lambda: (f'{service_name_en}', f'{order_id}'))
                )
        else:
            if is_test:
                text = (
                    t('b_your_welcome_service_will_e6fde0f50b', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f'{time_left}', f'{RLM}', f'{to_persian_number(order_id)}', f'{RLM}'), en_parts=lambda: (f'{time_left}', f'{order_id}'))
                )
            else:
                text = (
                    t('b_service_expiry_reminder_b_78e205572a', lang, fa_parts=lambda: (f'{RLM}', f'{RLM}', f'{service_name}', f'{RLM}', f'{time_left}', f'{RLM}', f'{to_persian_number(order_id)}', f'{RLM}'), en_parts=lambda: (f'{service_name_en}', f'{time_left}', f'{order_id}'))
                )

        keyboard = self._build_alert_keyboard(order_id, lang, is_test)
        
        try:
            await self.bot.send_message(
                user_id, text, parse_mode="HTML", reply_markup=keyboard
            )
            logger.info(f"Expiry alert {notify_label} sent for order #{order_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending expiry alert to user {user_id}: {e}")
            return False
    
    # ═══════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════
    
    def clear_cache(self, order_id: Optional[int] = None):
        """پاک کردن کش"""
        if order_id:
            self._clear_order_cache(order_id)
            logger.info(f"Cache cleared for order #{order_id}")
        else:
            self.volume_alert_cache.clear()
            self.expiry_alert_cache.clear()
            self.sent_alerts_history.clear()
            self.service_info_cache.clear()
            logger.info("All alert cache cleared")
        
        self._save_cache_to_disk()
    
    def clear_all_history(self):
        """پاک کردن کامل"""
        self.volume_alert_cache.clear()
        self.expiry_alert_cache.clear()
        self.sent_alerts_history.clear()
        self.service_info_cache.clear()
        
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
        except Exception as e:
            logger.error(f"Error deleting cache file: {e}")
        
        self._save_cache_to_disk()
        logger.info("All alert history cleared")
    
    def update_settings(self, settings: dict):
        """به‌روزرسانی تنظیمات"""
        if 'volume_thresholds' in settings:
            self.volume_thresholds = settings['volume_thresholds']
            logger.info(f"📊 Volume thresholds: {self.volume_thresholds}% + auto exhaust")
        
        if 'expiry_warnings' in settings:
            self.expiry_warnings = settings['expiry_warnings']
            logger.info(f"📅 Expiry thresholds: {self.expiry_warnings} days + auto expire")
        
        if 'test_volume_thresholds' in settings:
            self.test_volume_thresholds = settings['test_volume_thresholds']
        
        if 'test_expiry_warnings' in settings:
            self.test_expiry_warnings = settings['test_expiry_warnings']
        
        if 'enabled' in settings:
            self.enabled = settings['enabled']
        
        logger.info(f"⚙️ Alert settings updated")
# alert_system.py
import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, Awaitable
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


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
        self.expiry_warnings = [3, 1]
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
                        f"✅ Cache loaded: "
                        f"{len(self.volume_alert_cache)} volume, "
                        f"{len(self.expiry_alert_cache)} expiry"
                    )
            else:
                logger.info("📝 Cache file not found, starting empty")
        except Exception as e:
            logger.error(f"❌ Error loading cache: {e}")
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
                'last_updated': datetime.now().isoformat()
            }
            
            temp_file = f"{self.cache_file}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            os.replace(temp_file, self.cache_file)
            
        except Exception as e:
            logger.error(f"❌ Error saving cache: {e}")
    
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
            logger.debug(f"⏭️ Order #{order_id}: هیچ email یا link موجود نیست")
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
                f"⚠️ Order #{order_id}: email نداره و "
                f"find_email_by_sub_id_func تنظیم نشده"
            )
            return None
        
        # ─── تلاش برای پیدا کردن email ───
        try:
            found_email = await self.find_email_by_sub_id(sub_id)
            if found_email:
                logger.info(
                    f"✅ [resolve_email] Order #{order_id}: "
                    f"{sub_id[:20]}... → {found_email}"
                )
                # ✅ ذخیره توی سفارش برای بارهای بعد
                if self.update_order and order_id:
                    try:
                        self.update_order(order_id, email=found_email)
                        logger.info(f"💾 email توی سفارش #{order_id} ذخیره شد")
                    except Exception as e:
                        logger.warning(f"⚠️ خطا در ذخیره email: {e}")
                return found_email
            else:
                logger.debug(f"⏭️ Order #{order_id}: email برای subId {sub_id[:20]}... پیدا نشد")
                return None
        except Exception as e:
            logger.error(f"❌ [resolve_email] خطا برای Order #{order_id}: {e}")
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
            
            type_emoji = "🧪" if is_test else "📡"
            type_text = "Test" if is_test else "Normal"
            
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
🕐 <b>Time:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
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
        logger.info("🧪 Alert system started (one-time per threshold)")
        
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
                
                # ✅ فقط config_link و user_id لازم است
                approved_orders = [
                    o for o in valid_orders.values() 
                    if isinstance(o, dict) 
                    and o.get('config_link')
                    and o.get('user_id')
                ]
                
                logger.debug(f"🔍 Checking {len(approved_orders)} services")
                
                for order in approved_orders:
                    order_id = order.get('order_id')
                    user_id = order.get('user_id')
                    
                    if not order_id or not user_id:
                        continue
                    
                    try:
                        # ✅ استفاده از تابع جدید برای دریافت email
                        email = await self._resolve_email(order)
                        
                        if not email:
                            logger.debug(
                                f"⏭️ Order #{order_id}: "
                                f"email قابل resolve نیست، رد شد"
                            )
                            continue
                        
                        # ✅ import توی تابع (به خاطر circular import)
                        from main import xui_get_client_info, xui_get_client_traffic
                        
                        client_info = await xui_get_client_info(email)
                        
                        if not client_info or not isinstance(client_info, dict):
                            logger.debug(
                                f"⏭️ Order #{order_id}: "
                                f"client_info برای {email} یافت نشد"
                            )
                            continue
                        
                        # ✅ تشخیص تمدید
                        await self._check_service_renewal(order, client_info)
                        
                        # ✅ دریافت ترافیک
                        traffic_data = await xui_get_client_traffic(email)
                        
                        if traffic_data and not isinstance(traffic_data, dict):
                            traffic_data = None
                        
                        # ✅ بررسی حجم و انقضا
                        await self._check_volume_alert(order, client_info, traffic_data)
                        await self._check_expiry_alert(order, client_info)
                        
                    except Exception as e:
                        logger.error(
                            f"Error checking service #{order_id}: {e}",
                            exc_info=True
                        )
                        
            except Exception as e:
                logger.error(f"Error in check_all_services: {e}", exc_info=True)
    
    # ═══════════════════════════════════════════
    # تشخیص تمدید
    # ═══════════════════════════════════════════
    
    async def _check_service_renewal(self, order: dict, client_info: dict):
        """تشخیص تمدید سرویس"""
        order_id = order.get('order_id')
        
        current_total = client_info.get('totalGB', 0)
        current_expiry = client_info.get('expiryTime', 0)
        
        previous = self.service_info_cache.get(str(order_id))
        
        if not previous:
            self.service_info_cache[str(order_id)] = {
                'totalGB': current_total,
                'expiryTime': current_expiry,
                'first_seen': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat()
            }
            self._save_cache_to_disk()
            return
        
        prev_total = previous.get('totalGB', 0)
        prev_expiry = previous.get('expiryTime', 0)
        
        is_volume_increased = current_total > prev_total
        is_expiry_extended = current_expiry > prev_expiry
        
        if is_volume_increased or is_expiry_extended:
            changes = []
            
            if is_volume_increased:
                changes.append(
                    f"📦 Volume: {self._format_bytes(prev_total)} → "
                    f"{self._format_bytes(current_total)}"
                )
            
            if is_expiry_extended:
                prev_date = self._format_timestamp(prev_expiry)
                current_date = self._format_timestamp(current_expiry)
                changes.append(f"⏱ Expiry: {prev_date} → {current_date}")
            
            changes_text = "\n".join(changes)
            
            logger.info(f"🔄 Service #{order_id} renewed:\n{changes_text}")
            
            if self.log_system:
                text = f"""
🔄 <b>Service Renewed</b>
🕐 <b>Time:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>User:</b> <code>{order.get('user_id')}</code>
🆔 <b>Order:</b> #{order_id}
{changes_text}
"""
                await self.log_system.send_log(text)
            
            # پاک کردن کش هشدارها برای این سفارش (چون سرویس تجدید شد)
            self._clear_order_cache(order_id)
            
            self.service_info_cache[str(order_id)] = {
                'totalGB': current_total,
                'expiryTime': current_expiry,
                'last_updated': datetime.now().isoformat(),
                'last_renewal': datetime.now().isoformat()
            }
            
            self._save_cache_to_disk()
        else:
            self.service_info_cache[str(order_id)] = {
                'totalGB': current_total,
                'expiryTime': current_expiry,
                'last_updated': datetime.now().isoformat()
            }
            
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
    
    def _format_volume(self, gb: float) -> str:
        """فرمت حجم"""
        if gb >= 1:
            return f"{gb:.2f} GB"
        elif gb >= 0.001:
            mb = gb * 1024
            return f"{mb:.0f} MB"
        else:
            return "0 MB"
    
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
        
        logger.info(f"🔄 Cache cleared for order #{order_id}")
    
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
        now = datetime.now()
        
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
                expiry_date = datetime.fromtimestamp(expiry_time / 1000)
            else:
                expiry_date = datetime.fromtimestamp(expiry_time)
        except Exception:
            return
        
        now = datetime.now()
        time_left = expiry_date - now
        hours_left = time_left.total_seconds() / 3600
        
        days_left = time_left.days
        
        label = None
        alert_type = 'expiry'
        
        if hours_left <= 0:
            label = "expired"
            alert_type = 'expired'
        elif is_test:
            if hours_left <= 6:
                label = "6h"
        else:
            thresholds_sorted = sorted(self.expiry_warnings)
            
            for threshold in thresholds_sorted:
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
                logger.info(f"📨 Expiry alert ({label}) sent for order #{order_id}")
                
                details = "expired" if label == "expired" else f"{label} remaining"
                await self._log_alert(alert_type, order, details)
            else:
                logger.warning(f"⚠️ Expiry alert ({label}) not sent for order #{order_id}")
    
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
                logger.info(f"📨 Volume alert ({label}) sent for order #{order_id}")
                
                if label == "exhausted":
                    details = f"Volume exhausted ({used_gb:.2f}GB of {total_gb:.2f}GB)"
                else:
                    details = f"{label} remaining ({used_gb:.2f}GB of {total_gb:.2f}GB)"
                
                await self._log_alert(alert_type, order, details)
            else:
                logger.warning(f"⚠️ Volume alert ({label}) not sent for order #{order_id}")
    
    # ═══════════════════════════════════════════
    # Notifications
    # ═══════════════════════════════════════════

    def _build_alert_keyboard(self, order_id: int, lang: str, is_test: bool) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=(
                    "🛒 خرید سرویس" if lang == 'fa' else "🛒 Buy Service"
                ) if is_test else (
                    "🔄 تمدید سرویس" if lang == 'fa' else "🔄 Renew Service"
                ),
                callback_data="buy_service" if is_test else f"extend_service_{order_id}",
                style="success" if is_test else "primary",
            )],
            [InlineKeyboardButton(
                text="📁 مشاهده کانفیگ" if lang == 'fa' else "📁 View Config",
                callback_data=f"view_config_{order_id}",
            )],
            [InlineKeyboardButton(
                text="🏠 منوی اصلی" if lang == 'fa' else "🏠 Main Menu",
                callback_data="back_to_main",
            )],
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
        
        used_display = self._format_volume(used_gb)
        total_display = self._format_volume(total_gb)
        remaining_display = self._format_volume(remaining_gb)
        exhausted = threshold_label == "exhausted"
        service_name = "سرویس آزمایشی" if is_test else "سرویس"
        service_name_en = "test service" if is_test else "service"

        if lang == 'fa':
            if exhausted:
                if is_test:
                    text = (
                        f"❌ <b>حجم سرویس آزمایشی به پایان رسیده است</b>\n\n"
                        f"🧪 حجم تست شما به‌طور کامل مصرف شده است.\n\n"
                        f"🆔 شماره سفارش: #{order_id}\n"
                        f"📊 میزان مصرف: {used_display} از {total_display}\n\n"
                        f"سرویس آزمایشی قابل تمدید نیست. برای ادامه استفاده، سرویس اصلی را از بخش خرید تهیه کنید."
                    )
                else:
                    text = (
                        f"❌ <b>حجم سرویس به پایان رسیده است</b>\n\n"
                        f"📡 حجم {service_name} شما به‌طور کامل مصرف شده است.\n\n"
                        f"🆔 شماره سفارش: #{order_id}\n"
                        f"📊 میزان مصرف: {used_display} از {total_display}\n"
                        f"📉 حجم باقی‌مانده: {remaining_display}\n\n"
                        f"برای ادامه استفاده، کانفیگ را مشاهده کنید یا سرویس خود را تمدید کنید."
                    )
            else:
                if is_test:
                    text = (
                        f"⚠️ <b>حجم سرویس آزمایشی رو به اتمام است</b>\n\n"
                        f"🧪 بخش عمده‌ای از حجم تست شما مصرف شده است.\n\n"
                        f"🆔 شماره سفارش: #{order_id}\n"
                        f"📊 میزان مصرف: {used_display} از {total_display}\n"
                        f"📉 حجم باقی‌مانده: {remaining_display} ({remaining_percent:.1f}٪)\n\n"
                        f"سرویس تست قابل تمدید نیست؛ برای ادامه پس از پایان تست، سرویس اصلی را خریداری کنید."
                    )
                else:
                    text = (
                        f"⚠️ <b>حجم سرویس رو به اتمام است</b>\n\n"
                        f"📡 بخش عمده‌ای از حجم {service_name} شما مصرف شده است.\n\n"
                        f"🆔 شماره سفارش: #{order_id}\n"
                        f"📊 میزان مصرف: {used_display} از {total_display}\n"
                        f"📉 حجم باقی‌مانده: {remaining_display} ({remaining_percent:.1f}٪)\n\n"
                        f"برای جلوگیری از وقفه، وضعیت کانفیگ را بررسی و در صورت نیاز آن را تمدید کنید."
                    )
        else:
            if exhausted:
                if is_test:
                    text = (
                        f"❌ <b>Test service data allowance exhausted</b>\n\n"
                        f"🧪 Your test data allowance has been fully used.\n\n"
                        f"🆔 Order: #{order_id}\n"
                        f"📊 Used: {used_display} of {total_display}\n\n"
                        f"Test services cannot be renewed. Purchase a full service to continue."
                    )
                else:
                    text = (
                        f"❌ <b>Service data allowance exhausted</b>\n\n"
                        f"📡 Your {service_name_en} has used its full data allowance.\n\n"
                        f"🆔 Order: #{order_id}\n"
                        f"📊 Used: {used_display} of {total_display}\n"
                        f"📉 Remaining: {remaining_display}\n\n"
                        f"View your config or renew the service to continue."
                    )
            else:
                if is_test:
                    text = (
                        f"⚠️ <b>Test service data is running low</b>\n\n"
                        f"🧪 Most of your test data allowance has been used.\n\n"
                        f"🆔 Order: #{order_id}\n"
                        f"📊 Used: {used_display} of {total_display}\n"
                        f"📉 Remaining: {remaining_display} ({remaining_percent:.1f}%)\n\n"
                        f"Test services cannot be renewed. Purchase a full service when you are ready to continue."
                    )
                else:
                    text = (
                        f"⚠️ <b>Service data is running low</b>\n\n"
                        f"📡 Most of the data allowance for your {service_name_en} has been used.\n\n"
                        f"🆔 Order: #{order_id}\n"
                        f"📊 Used: {used_display} of {total_display}\n"
                        f"📉 Remaining: {remaining_display} ({remaining_percent:.1f}%)\n\n"
                        f"Review your config and renew the service if needed to avoid interruption."
                    )
        
        keyboard = self._build_alert_keyboard(order_id, lang, is_test)

        try:
            await self.bot.send_message(
                user_id, text, parse_mode="HTML", reply_markup=keyboard
            )
            logger.info(f"📨 Volume alert {threshold_label} sent for order #{order_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error sending volume alert to user {user_id}: {e}")
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
            time_left = "منقضی شده" if lang == 'fa' else "Expired"
        elif days_left > 0:
            time_left = f"{days_left} روز" if lang == 'fa' else f"{days_left} days"
        elif hours_left >= 1:
            time_left = f"{int(hours_left)} ساعت" if lang == 'fa' else f"{int(hours_left)} hours"
        else:
            minutes_left = max(0, int(hours_left * 60))
            time_left = f"{minutes_left} دقیقه" if lang == 'fa' else f"{minutes_left} minutes"

        service_name = "سرویس آزمایشی" if is_test else "سرویس"
        service_name_en = "test service" if is_test else "service"
        expired = notify_label == "expired"

        if lang == 'fa':
            if expired:
                if is_test:
                    text = (
                        f"❌ <b>مهلت سرویس آزمایشی به پایان رسیده است</b>\n\n"
                        f"🧪 زمان استفاده از تست شما تمام شده است.\n\n"
                        f"🆔 شماره سفارش: #{order_id}\n\n"
                        f"سرویس تست قابل تمدید نیست. برای ادامه، یک سرویس اصلی خریداری کنید."
                    )
                else:
                    text = (
                        f"❌ <b>مهلت استفاده از سرویس به پایان رسیده است</b>\n\n"
                        f"📡 اعتبار زمانی {service_name} شما منقضی شده است.\n\n"
                        f"🆔 شماره سفارش: #{order_id}\n\n"
                        f"برای استفادهٔ دوباره، کانفیگ را بررسی کنید و در صورت نیاز سرویس را تمدید کنید."
                    )
            else:
                if is_test:
                    text = (
                        f"⚠️ <b>سرویس آزمایشی شما به‌زودی منقضی می‌شود</b>\n\n"
                        f"🧪 زمان باقی‌مانده: {time_left}\n"
                        f"🆔 شماره سفارش: #{order_id}\n\n"
                        f"تست قابل تمدید نیست؛ برای استفاده بدون وقفه، سرویس اصلی را خریداری کنید."
                    )
                else:
                    text = (
                        f"⚠️ <b>هشدار نزدیک‌شدن به انقضای سرویس</b>\n\n"
                        f"📡 اعتبار زمانی {service_name} شما به‌زودی به پایان می‌رسد.\n\n"
                        f"⏱ زمان باقی‌مانده: {time_left}\n"
                        f"🆔 شماره سفارش: #{order_id}\n\n"
                        f"برای جلوگیری از قطع دسترسی، وضعیت سرویس را بررسی و در صورت نیاز آن را تمدید کنید."
                    )
        else:
            if expired:
                if is_test:
                    text = (
                        f"❌ <b>Test service has expired</b>\n\n"
                        f"🧪 Your test period has ended.\n\n"
                        f"🆔 Order: #{order_id}\n\n"
                        f"Test services cannot be renewed. Purchase a full service to continue."
                    )
                else:
                    text = (
                        f"❌ <b>Service validity has expired</b>\n\n"
                        f"📡 The validity period for your {service_name_en} has ended.\n\n"
                        f"🆔 Order: #{order_id}\n\n"
                        f"Review your config and renew the service if you would like to continue."
                    )
            else:
                if is_test:
                    text = (
                        f"⚠️ <b>Your test service will expire soon</b>\n\n"
                        f"🧪 Time remaining: {time_left}\n"
                        f"🆔 Order: #{order_id}\n\n"
                        f"Test services cannot be renewed. Purchase a full service for uninterrupted access."
                    )
                else:
                    text = (
                        f"⚠️ <b>Service expiry reminder</b>\n\n"
                        f"📡 The validity period for your {service_name_en} will end soon.\n\n"
                        f"⏱ Time remaining: {time_left}\n"
                        f"🆔 Order: #{order_id}\n\n"
                        f"Review your service and renew it if needed to avoid an interruption."
                    )

        keyboard = self._build_alert_keyboard(order_id, lang, is_test)
        
        try:
            await self.bot.send_message(
                user_id, text, parse_mode="HTML", reply_markup=keyboard
            )
            logger.info(f"📨 Expiry alert {notify_label} sent for order #{order_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error sending expiry alert to user {user_id}: {e}")
            return False
    
    # ═══════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════
    
    def clear_cache(self, order_id: Optional[int] = None):
        """پاک کردن کش"""
        if order_id:
            self._clear_order_cache(order_id)
            logger.info(f"🧹 Cache cleared for order #{order_id}")
        else:
            self.volume_alert_cache.clear()
            self.expiry_alert_cache.clear()
            self.sent_alerts_history.clear()
            self.service_info_cache.clear()
            logger.info("🧹 All alert cache cleared")
        
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
        logger.info("🗑️ All alert history cleared")
    
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
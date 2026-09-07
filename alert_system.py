# alert_system.py
import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

class AlertSystem:
    """سیستم مدیریت هشدارهای حجم و انقضای سرویس با ارسال یکبار برای هر آستانه"""
    
    def __init__(self, bot, orders_getter, user_getter, extract_email_func, cache_file="alert_cache.json", log_system=None):
        self.bot = bot
        self.get_orders = orders_getter
        self.get_user = user_getter
        self.extract_email = extract_email_func
        self.log_system = log_system  # سیستم لاگ
        
        # فایل کش
        self.cache_file = cache_file
        
        # کش‌ها
        self.volume_alert_cache = {}
        self.expiry_alert_cache = {}
        self.sent_alerts_history = {}
        
        # کش اطلاعات سرویس برای تشخیص تمدید
        self.service_info_cache = {}
        
        # بارگذاری از فایل
        self._load_cache_from_disk()
        
        # تنظیمات
        self.check_interval = 600  # هر ۱۰ دقیقه
        self.cooldown_minutes = 120  # دیگر استفاده نمی‌شود (فقط یکبار ارسال)
        self.enabled = True
        
        # آستانه‌ها - فقط ۲ آستانه + اتمام خودکار
        self.volume_thresholds = [10, 5]      # سومی خودکار: ۰٪ = تمام شده
        self.expiry_warnings = [3, 1]         # سومی خودکار: ۰ = منقضی شده
        self.test_volume_thresholds = [10]    # تست: فقط ۱۰٪ + اتمام
        self.test_expiry_warnings = [0.25]    # تست: فقط ۶ ساعت + انقضا
        
        self._lock = asyncio.Lock()
    
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
                    
                    logger.info(f"✅ کش هشدارها بارگذاری شد: {len(self.volume_alert_cache)} حجم، {len(self.expiry_alert_cache)} انقضا")
            else:
                logger.info("📝 فایل کش وجود ندارد، شروع با کش خالی")
        except Exception as e:
            logger.error(f"❌ خطا در بارگذاری کش: {e}")
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
            logger.error(f"❌ خطا در ذخیره کش: {e}")
    
    async def _log_alert(self, alert_type: str, order: dict, details: str):
        """ارسال لاگ هشدار به کانال لاگ"""
        if not self.log_system:
            return
        
        try:
            user_id = order.get('user_id')
            order_id = order.get('order_id')
            is_test = order.get('is_test', False) or order.get('type') == 'test'
            
            type_emoji = "🧪" if is_test else "📡"
            type_text = "سرویس تست" if is_test else "سرویس عادی"
            
            if alert_type == 'volume':
                emoji = "⚠️"
                title = "هشدار مصرف حجم"
            elif alert_type == 'volume_exhausted':
                emoji = "❌"
                title = "اتمام حجم سرویس"
            elif alert_type == 'expiry':
                emoji = "⏰"
                title = "هشدار انقضا"
            else:  # expired
                emoji = "❌"
                title = "سرویس منقضی شد"
            
            text = f"""
{emoji} <b>{title}</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>کاربر:</b> <code>{user_id}</code>
🆔 <b>سفارش:</b> #{order_id}
{type_emoji} <b>نوع سرویس:</b> {type_text}
📄 <b>جزئیات:</b> {details}
"""
            await self.log_system.send_log(text)
        except Exception as e:
            logger.error(f"خطا در ارسال لاگ هشدار: {e}")
    
    async def run_alert_worker(self):
        """کارگر پس‌زمینه"""
        logger.info("🧪 سیستم هشدار راه‌اندازی شد (ارسال یکبار برای هر آستانه)")
        
        self._save_cache_to_disk()
        
        while True:
            try:
                if self.enabled:
                    await self.check_all_services()
                    self._save_cache_to_disk()
                    
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                self._save_cache_to_disk()
                logger.info("سیستم هشدار متوقف شد")
                break
            except Exception as e:
                logger.error(f"خطا در سیستم هشدار: {e}", exc_info=True)
                self._save_cache_to_disk()
                await asyncio.sleep(60)
    
    async def check_all_services(self):
        """بررسی تمام سرویس‌ها"""
        async with self._lock:
            try:
                valid_orders = self.get_orders()
                if not valid_orders:
                    return
                
                approved_orders = [
                    o for o in valid_orders.values() 
                    if isinstance(o, dict) 
                    and o.get('status') == 'approved' 
                    and o.get('config_link')
                    and o.get('is_active_in_panel', True)
                ]
                
                logger.debug(f"🔍 بررسی {len(approved_orders)} سرویس")
                
                for order in approved_orders:
                    order_id = order.get('order_id')
                    user_id = order.get('user_id')
                    
                    if not order_id or not user_id:
                        continue
                    
                    try:
                        # استخراج ایمیل از config_link
                        email = self.extract_email(order.get('config_link', ''))
                        if not email:
                            email = order.get('email')
                            if not email:
                                continue
                        
                        from main import xui_get_client_info, xui_get_client_traffic
                        
                        client_info = await xui_get_client_info(email)
                        await asyncio.sleep(2)
                        
                        if not client_info or not isinstance(client_info, dict):
                            continue
                        
                        if not client_info.get('enable', True):
                            continue
                        
                        # تشخیص تمدید سرویس
                        await self._check_service_renewal(order, client_info)
                        
                        # دریافت ترافیک
                        traffic_data = await xui_get_client_traffic(email)
                        
                        if traffic_data and not isinstance(traffic_data, dict):
                            traffic_data = None
                        
                        # بررسی حجم و انقضا
                        await self._check_volume_alert(order, client_info, traffic_data)
                        await self._check_expiry_alert(order, client_info)
                        
                    except Exception as e:
                        logger.error(f"خطا در بررسی سرویس #{order_id}: {e}", exc_info=True)
                        
            except Exception as e:
                logger.error(f"خطا در check_all_services: {e}", exc_info=True)
    
    async def _check_service_renewal(self, order: dict, client_info: dict):
        """تشخیص تمدید سرویس و پاک کردن کش - فقط وقتی حجم یا زمان بیشتر شده"""
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
                changes.append(f"📦 حجم: {self._format_bytes(prev_total)} → {self._format_bytes(current_total)}")
            
            if is_expiry_extended:
                prev_date = self._format_timestamp(prev_expiry)
                current_date = self._format_timestamp(current_expiry)
                changes.append(f"⏱ انقضا: {prev_date} → {current_date}")
            
            changes_text = "\n".join(changes)
            
            logger.info(f"🔄 سرویس #{order_id} تمدید شد:\n{changes_text}")
            
            if self.log_system:
                text = f"""
🔄 <b>تمدید سرویس</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>کاربر:</b> <code>{order.get('user_id')}</code>
🆔 <b>سفارش:</b> #{order_id}
{changes_text}
"""
                await self.log_system.send_log(text)
            
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

    def _format_bytes(self, bytes_value: int) -> str:
        """فرمت بایت به صورت خوانا"""
        if bytes_value == 0:
            return "نامحدود"
        
        gb = bytes_value / (1024**3)
        if gb >= 1:
            return f"{gb:.2f} GB"
        else:
            mb = bytes_value / (1024**2)
            return f"{mb:.0f} MB"

    def _format_timestamp(self, timestamp: int) -> str:
        """فرمت timestamp به تاریخ خوانا"""
        try:
            if timestamp > 10000000000:
                dt = datetime.fromtimestamp(timestamp / 1000)
            else:
                dt = datetime.fromtimestamp(timestamp)
            return dt.strftime('%Y-%m-%d %H:%M')
        except:
            return "نامشخص"
    
    def _clear_order_cache(self, order_id: int):
        """پاک کردن کش یک سفارش خاص"""
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
        
        logger.info(f"🔄 کش هشدارهای سفارش #{order_id} بعد از تمدید پاک شد")
    
    async def _check_expiry_alert(self, order: dict, client_info: dict):
        """بررسی هشدار انقضا - ۲ آستانه + انقضای خودکار"""
        order_id = order.get('order_id')
        is_test = order.get('is_test', False) or order.get('type') == 'test'
        
        expiry_time = client_info.get('expiryTime', 0)
        if not isinstance(expiry_time, (int, float)) or expiry_time == 0:
            return
        
        try:
            if expiry_time > 10000000000:
                expiry_date = datetime.fromtimestamp(expiry_time / 1000)
            else:
                expiry_date = datetime.fromtimestamp(expiry_time)
        except:
            return
        
        now = datetime.now()
        time_left = expiry_date - now
        hours_left = time_left.total_seconds() / 3600
        
        days_left = time_left.days
        
        label = None
        alert_type = 'expiry'
        
        # ✅ بررسی انقضای کامل
        if hours_left <= 0:
            label = "منقضی شده"
            alert_type = 'expired'
        elif is_test:
            # تست: فقط ۶ ساعت
            if hours_left <= 6:
                label = "۶ ساعت"
        else:
            # سرویس عادی: استفاده از تنظیمات (۲ آستانه)
            thresholds_sorted = sorted(self.expiry_warnings, reverse=True)
            
            for threshold in thresholds_sorted:
                threshold_hours = threshold * 24
                if hours_left <= threshold_hours:
                    label = f"{int(threshold)} روز"
                    break
        
        if not label:
            return
        
        cache_key = f"exp_{order_id}_{label}"
        
        # ✅ فقط یکبار ارسال می‌شود
        if self._should_send_once(cache_key):
            sent_successfully = await self._notify_expiry(order, days_left, hours_left, is_test, label)
            
            if sent_successfully:
                self._record_alert(cache_key, self.expiry_alert_cache, alert_type, order_id)
                logger.info(f"📨 هشدار انقضا ({label}) برای سفارش #{order_id} ارسال شد")
                
                details = "سرویس منقضی شده" if label == "منقضی شده" else f"{label} مانده به انقضا"
                await self._log_alert(alert_type, order, details)
            else:
                logger.warning(f"⚠️ هشدار انقضا ({label}) برای سفارش #{order_id} ارسال نشد")

    async def _check_volume_alert(self, order: dict, client_info: dict, traffic_data: Optional[dict]):
        """بررسی هشدار حجم - ۲ آستانه + اتمام خودکار"""
        order_id = order.get('order_id')
        is_test = order.get('is_test', False) or order.get('type') == 'test'
        
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
        
        # ✅ بررسی اتمام کامل حجم
        if remaining_gb <= 0 or remaining_percent <= 0:
            label = "تمام شده"
            alert_type = 'volume_exhausted'
        elif is_test:
            # تست: فقط ۱۰٪
            if remaining_percent <= 10:
                label = "۱۰٪"
        else:
            # سرویس عادی: استفاده از تنظیمات (۲ آستانه)
            thresholds_sorted = sorted(self.volume_thresholds)
            
            for threshold in thresholds_sorted:
                if remaining_percent <= threshold:
                    label = f"{threshold}٪"
                    break
        
        if not label:
            return
        
        cache_key = f"vol_{order_id}_{label}"
        
        # ✅ فقط یکبار ارسال می‌شود
        if self._should_send_once(cache_key):
            sent_successfully = await self._notify_volume(
                order, used_gb, total_gb, remaining_gb, 
                remaining_percent, label, is_test
            )
            
            if sent_successfully:
                self._record_alert(cache_key, self.volume_alert_cache, alert_type, order_id)
                logger.info(f"📨 هشدار حجم {label} برای سفارش #{order_id} ارسال شد")
                
                if label == "تمام شده":
                    details = f"حجم تمام شده ({used_gb:.2f}GB از {total_gb:.2f}GB)"
                else:
                    details = f"{label} باقی‌مانده ({used_gb:.2f}GB از {total_gb:.2f}GB)"
                
                await self._log_alert(alert_type, order, details)
            else:
                logger.warning(f"⚠️ هشدار حجم {label} برای سفارش #{order_id} ارسال نشد")
    
    def _should_send_once(self, cache_key: str) -> bool:
        """بررسی ارسال - فقط یکبار برای هر آستانه"""
        if cache_key in self.volume_alert_cache:
            return False
        
        if cache_key in self.expiry_alert_cache:
            return False
        
        if cache_key in self.sent_alerts_history:
            return False
        
        return True
    
    def _record_alert(self, cache_key: str, cache: dict, alert_type: str, order_id: int):
        """ثبت هشدار موفق در کش"""
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
    


    async def _notify_volume(self, order: dict, used_gb: float, total_gb: float, 
                            remaining_gb: float, remaining_percent: float, 
                            threshold_label: str, is_test: bool) -> bool:
        """ارسال هشدار حجم"""
        user_id = order.get('user_id')
        order_id = order.get('order_id')
        
        user = self.get_user(user_id)
        lang = user.get('lang', 'fa') if user else 'fa'
        
        used_display = self._format_volume(used_gb)
        total_display = self._format_volume(total_gb)
        remaining_display = self._format_volume(remaining_gb)
        
        if threshold_label == "تمام شده":
            # پیام اتمام حجم
            if is_test:
                text = (
                    f"❌ <b>حجم تست تمام شد</b>\n\n"
                    f"🧪 حجم سرویس تست شما به پایان رسید!\n\n"
                    f"📊 مصرف: {used_display} از {total_display}\n\n"
                    f"💡 برای ادامه استفاده، سرویس کامل تهیه کنید."
                    if lang == 'fa' else
                    f"❌ <b>Test Volume Exhausted</b>\n\n"
                    f"🧪 Your test service volume is exhausted!\n\n"
                    f"📊 Used: {used_display} of {total_display}\n\n"
                    f"💡 Purchase a full service to continue."
                )
                
                # ✅ تست: دکمه خرید سرویس
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🛒 خرید سرویس" if lang == 'fa' else "🛒 Buy Service",
                        callback_data="buy_service",
                        style="success"
                    )]
                ])
            else:
                text = (
                    f"❌ <b>حجم سرویس تمام شد</b>\n\n"
                    f"📡 حجم سرویس شما به پایان رسید!\n\n"
                    f"🆔 سفارش: #{order_id}\n"
                    f"📊 مصرف: {used_display} از {total_display}\n\n"
                    f"💡 می‌توانید از بخش «کانفیگ‌های من» سرویس خود را تمدید کنید."
                    if lang == 'fa' else
                    f"❌ <b>Service Volume Exhausted</b>\n\n"
                    f"📡 Your service volume is exhausted!\n\n"
                    f"🆔 Order: #{order_id}\n"
                    f"📊 Used: {used_display} of {total_display}\n\n"
                    f"💡 You can renew your service from 'My Configs'."
                )
                
                # ✅ عادی: دکمه تمدید
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔄 تمدید سرویس" if lang == 'fa' else "🔄 Renew Service",
                        callback_data="my_configs",
                        style="primary"
                    )]
                ])
        else:
            # پیام هشدار عادی
            if is_test:
                text = (
                    f"⚠️ <b>هشدار مصرف تست</b>\n\n"
                    f"🧪 سرویس تست شما در حال اتمام است!\n\n"
                    f"📊 مصرف: {used_display} از {total_display}\n"
                    f"📊 باقی‌مانده: {remaining_display} ({remaining_percent:.1f}%)\n\n"
                    f"💡 برای ادامه استفاده، سرویس کامل تهیه کنید."
                    if lang == 'fa' else
                    f"⚠️ <b>Test Service Warning</b>\n\n"
                    f"🧪 Your test service is running out!\n\n"
                    f"📊 Used: {used_display} of {total_display}\n"
                    f"📊 Remaining: {remaining_display} ({remaining_percent:.1f}%)\n\n"
                    f"💡 Purchase a full service to continue."
                )
                
                # ✅ تست: دکمه خرید سرویس
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🛒 خرید سرویس" if lang == 'fa' else "🛒 Buy Service",
                        callback_data="buy_service",
                        style="success"
                    )]
                ])
            else:
                text = (
                    f"⚠️ <b>هشدار مصرف سرویس</b>\n\n"
                    f"📡 سرویس شما در حال اتمام است!\n\n"
                    f"🆔 سفارش: #{order_id}\n"
                    f"📊 مصرف: {used_display} از {total_display}\n"
                    f"📊 باقی‌مانده: {remaining_display} ({remaining_percent:.1f}%)\n\n"
                    f"💡 می‌توانید از بخش «کانفیگ‌های من» سرویس خود را تمدید کنید."
                    if lang == 'fa' else
                    f"⚠️ <b>Service Usage Warning</b>\n\n"
                    f"📡 Your service is running out!\n\n"
                    f"🆔 Order: #{order_id}\n"
                    f"📊 Used: {used_display} of {total_display}\n"
                    f"📊 Remaining: {remaining_display} ({remaining_percent:.1f}%)\n\n"
                    f"💡 You can renew your service from 'My Configs'."
                )
                
                # ✅ عادی: دکمه تمدید
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔄 تمدید سرویس" if lang == 'fa' else "🔄 Renew Service",
                        callback_data="my_configs",
                        style="primary"
                    )]
                ])
        
        try:
            await self.bot.send_message(user_id, text, parse_mode="HTML", reply_markup=keyboard)
            logger.info(f"📨 هشدار حجم {threshold_label} برای سفارش #{order_id} ارسال شد")
            return True
        except Exception as e:
            logger.error(f"❌ خطا در ارسال هشدار حجم به کاربر {user_id}: {e}")
            return False
    
    

    async def _notify_expiry(self, order: dict, days_left: int, hours_left: float, 
                            is_test: bool, notify_label: str) -> bool:
        """ارسال هشدار انقضا"""
        user_id = order.get('user_id')
        order_id = order.get('order_id')
        
        user = self.get_user(user_id)
        lang = user.get('lang', 'fa') if user else 'fa'
        
        if notify_label == "منقضی شده":
            time_left = "منقضی شده" if lang == 'fa' else "Expired"
        elif days_left > 0:
            time_left = f"{days_left} روز" if lang == 'fa' else f"{days_left} days"
        elif hours_left >= 1:
            time_left = f"{int(hours_left)} ساعت" if lang == 'fa' else f"{int(hours_left)} hours"
        else:
            minutes_left = max(0, int(hours_left * 60))
            time_left = f"{minutes_left} دقیقه" if lang == 'fa' else f"{minutes_left} minutes"
        
        if notify_label == "منقضی شده":
            if is_test:
                text = (
                    f"❌ <b>سرویس تست منقضی شد</b>\n\n"
                    f"🧪 سرویس تست شما به پایان رسید!\n\n"
                    f"🆔 سفارش: #{order_id}\n\n"
                    f"💡 برای ادامه استفاده، سرویس کامل تهیه کنید."
                    if lang == 'fa' else
                    f"❌ <b>Test Service Expired</b>\n\n"
                    f"🧪 Your test service has expired!\n\n"
                    f"🆔 Order: #{order_id}\n\n"
                    f"💡 Purchase a full service to continue."
                )
                
                # ✅ تست: دکمه خرید سرویس
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🛒 خرید سرویس" if lang == 'fa' else "🛒 Buy Service",
                        callback_data="buy_service",
                        style="success"
                    )]
                ])
            else:
                text = (
                    f"❌ <b>سرویس منقضی شد</b>\n\n"
                    f"📡 سرویس شما به پایان رسید!\n\n"
                    f"🆔 سفارش: #{order_id}\n\n"
                    f"💡 می‌توانید از بخش «کانفیگ‌های من» سرویس خود را تمدید کنید."
                    if lang == 'fa' else
                    f"❌ <b>Service Expired</b>\n\n"
                    f"📡 Your service has expired!\n\n"
                    f"🆔 Order: #{order_id}\n\n"
                    f"💡 You can renew your service from 'My Configs'."
                )
                
                # ✅ عادی: دکمه تمدید
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔄 تمدید سرویس" if lang == 'fa' else "🔄 Renew Service",
                        callback_data="my_configs",
                        style="primary"
                    )]
                ])
        else:
            if is_test:
                text = (
                    f"⚠️ <b>هشدار انقضای تست</b>\n\n"
                    f"🧪 سرویس تست شما به زودی منقضی می‌شود!\n\n"
                    f"⏱ زمان باقی‌مانده: {time_left}\n"
                    f"🆔 سفارش: #{order_id}\n\n"
                    f"💡 برای ادامه استفاده، سرویس کامل تهیه کنید."
                    if lang == 'fa' else
                    f"⚠️ <b>Test Expiry Warning</b>\n\n"
                    f"🧪 Your test service is about to expire!\n\n"
                    f"⏱ Time left: {time_left}\n"
                    f"🆔 Order: #{order_id}\n\n"
                    f"💡 Purchase a full service to continue."
                )
                
                # ✅ تست: دکمه خرید سرویس
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🛒 خرید سرویس" if lang == 'fa' else "🛒 Buy Service",
                        callback_data="buy_service",
                        style="success"
                    )]
                ])
            else:
                text = (
                    f"⚠️ <b>هشدار انقضای سرویس</b>\n\n"
                    f"📡 سرویس شما به زودی منقضی می‌شود!\n\n"
                    f"⏱ زمان باقی‌مانده: {time_left}\n"
                    f"🆔 سفارش: #{order_id}\n\n"
                    f"💡 می‌توانید از بخش «کانفیگ‌های من» سرویس خود را تمدید کنید."
                    if lang == 'fa' else
                    f"⚠️ <b>Service Expiry Warning</b>\n\n"
                    f"📡 Your service is about to expire!\n\n"
                    f"⏱ Time left: {time_left}\n"
                    f"🆔 Order: #{order_id}\n\n"
                    f"💡 You can renew your service from 'My Configs'."
                )
                
                # ✅ عادی: دکمه تمدید
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🔄 تمدید سرویس" if lang == 'fa' else "🔄 Renew Service",
                        callback_data="my_configs",
                        style="primary"
                    )]
                ])
        
        try:
            await self.bot.send_message(user_id, text, parse_mode="HTML", reply_markup=keyboard)
            logger.info(f"📨 هشدار انقضا ({notify_label}) برای سفارش #{order_id} ارسال شد")
            return True
        except Exception as e:
            logger.error(f"❌ خطا در ارسال هشدار انقضا به کاربر {user_id}: {e}")
            return False
    
    def _format_volume(self, gb: float) -> str:
        """فرمت حجم"""
        if gb >= 1:
            return f"{gb:.2f} GB"
        elif gb >= 0.001:
            mb = gb * 1024
            return f"{mb:.0f} MB"
        else:
            return "0 MB"
    
    def clear_cache(self, order_id: Optional[int] = None):
        """پاک کردن کش (برای ارسال مجدد هشدارها)"""
        if order_id:
            self._clear_order_cache(order_id)
            logger.info(f"🧹 کش سفارش #{order_id} پاک شد")
        else:
            self.volume_alert_cache.clear()
            self.expiry_alert_cache.clear()
            self.sent_alerts_history.clear()
            self.service_info_cache.clear()
            logger.info("🧹 تمام کش هشدارها پاک شد")
        
        self._save_cache_to_disk()
    
    def clear_all_history(self):
        """پاک کردن کامل تاریخچه"""
        self.volume_alert_cache.clear()
        self.expiry_alert_cache.clear()
        self.sent_alerts_history.clear()
        self.service_info_cache.clear()
        
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
        except Exception as e:
            logger.error(f"خطا در حذف فایل کش: {e}")
        
        self._save_cache_to_disk()
        logger.info("🗑️ تمام تاریخچه هشدارها پاک شد")
    
    def update_settings(self, settings: dict):
        """به‌روزرسانی تنظیمات"""
        if 'volume_thresholds' in settings:
            self.volume_thresholds = settings['volume_thresholds']
            logger.info(f"📊 آستانه‌های حجم: {self.volume_thresholds}٪ + اتمام خودکار")
        
        if 'expiry_warnings' in settings:
            self.expiry_warnings = settings['expiry_warnings']
            logger.info(f"📅 آستانه‌های انقضا: {self.expiry_warnings} روز + انقضای خودکار")
        
        if 'test_volume_thresholds' in settings:
            self.test_volume_thresholds = settings['test_volume_thresholds']
        
        if 'test_expiry_warnings' in settings:
            self.test_expiry_warnings = settings['test_expiry_warnings']
        
        if 'enabled' in settings:
            self.enabled = settings['enabled']
        
        logger.info(f"⚙️ تنظیمات سیستم هشدار به‌روزرسانی شد")
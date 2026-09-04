import asyncio
import logging
from datetime import datetime
from typing import Optional
from aiogram import Bot
import html
import re

logger = logging.getLogger(__name__)


class LogSystem:
    """سیستم لاگ پیشرفته برای ثبت همه رویدادها با مدیریت flood control"""
    
    def __init__(self, bot_token: str, log_channel_id: int):
        self.bot = Bot(token=bot_token)
        self.log_channel_id = log_channel_id
        self.initialized = True
        self.log_queue = asyncio.Queue()
        self.is_sending = False
        self.last_send_time = 0
        self.min_interval = 1.0  # حداقل 1 ثانیه بین هر پیام
    
    @staticmethod
    def _safe(text) -> str:
        """امن کردن متن برای HTML"""
        if text is None:
            return ""
        return html.escape(str(text))
    
    async def _send_with_retry(self, message: str, parse_mode: str = "HTML", retry_count: int = 3):
        """ارسال پیام با قابلیت تلاش مجدد و مدیریت flood control"""
        for attempt in range(retry_count):
            try:
                # بررسی فاصله زمانی بین پیام‌ها
                now = datetime.now().timestamp()
                time_since_last = now - self.last_send_time
                if time_since_last < self.min_interval:
                    await asyncio.sleep(self.min_interval - time_since_last)
                
                await self.bot.send_message(
                    self.log_channel_id,
                    message,
                    parse_mode=parse_mode
                )
                self.last_send_time = datetime.now().timestamp()
                return True
                
            except Exception as e:
                error_msg = str(e)
                if "retry after" in error_msg.lower():
                    # استخراج زمان انتظار از خطا
                    match = re.search(r'retry after (\d+)', error_msg)
                    if match:
                        wait_time = int(match.group(1))
                        logger.warning(f"⏳ Flood control: waiting {wait_time} seconds")
                        await asyncio.sleep(wait_time + 1)
                    else:
                        await asyncio.sleep(5 * (attempt + 1))
                elif "can't parse entities" in error_msg.lower():
                    # اگر خطای HTML بود، بدون parse_mode تلاش کن
                    logger.warning(f"⚠️ خطای HTML در لاگ، تلاش بدون parse_mode")
                    try:
                        await self.bot.send_message(
                            self.log_channel_id,
                            message,
                            parse_mode=None
                        )
                        self.last_send_time = datetime.now().timestamp()
                        return True
                    except Exception as e2:
                        logger.error(f"❌ خطا در ارسال بدون parse_mode: {e2}")
                elif attempt < retry_count - 1:
                    logger.warning(f"⚠️ خطا در ارسال لاگ (تلاش {attempt + 1}): {e}")
                    await asyncio.sleep(2 * (attempt + 1))
                else:
                    logger.error(f"❌ خطا در ارسال لاگ پس از {retry_count} تلاش: {e}")
                    return False
        return False
    
    async def _process_queue(self):
        """پردازش صف لاگ‌ها با تاخیر مناسب"""
        if self.is_sending:
            return
        
        self.is_sending = True
        try:
            while not self.log_queue.empty():
                try:
                    item = await self.log_queue.get()
                    message = item.get('message', '')
                    parse_mode = item.get('parse_mode', 'HTML')
                    
                    await self._send_with_retry(message, parse_mode)
                    
                    # تاخیر بین پیام‌ها
                    await asyncio.sleep(1)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"خطا در پردازش صف لاگ: {e}")
                    await asyncio.sleep(2)
                    
        finally:
            self.is_sending = False
    
    async def send_log(self, message: str, parse_mode: str = "HTML"):
        """ارسال پیام لاگ به کانال با استفاده از صف"""
        # اضافه کردن timestamp به ابتدای پیام
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted_message = f"<code>[{timestamp}]</code>\n{message}"
        
        # اضافه کردن به صف
        await self.log_queue.put({
            'message': formatted_message,
            'parse_mode': parse_mode
        })
        
        # شروع پردازش صف اگر در حال اجرا نیست
        asyncio.create_task(self._process_queue())
    
    async def log_bot_start(self, bot_info, admin_id: int):
        """ثبت استارت ربات"""
        text = f"""
🚀 <b>ربات راه‌اندازی شد!</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
🤖 <b>نام:</b> {self._safe(bot_info.first_name)}
📛 <b>یوزرنیم:</b> @{self._safe(bot_info.username)}
🆔 <b>آیدی:</b> <code>{bot_info.id}</code>
👑 <b>ادمین:</b> <code>{admin_id}</code>
"""
        await self.send_log(text)
    
    async def log_bot_stop(self, admin_id: int):
        """ثبت توقف ربات"""
        text = f"""
🛑 <b>ربات متوقف شد!</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👑 <b>ادمین:</b> <code>{admin_id}</code>
"""
        await self.send_log(text)
    
    async def log_admin_action(self, admin_id: int, action: str, target_user: int = None, details: str = ""):
        """ثبت اقدامات ادمین"""
        target_text = f"\n🎯 <b>کاربر هدف:</b> <code>{target_user}</code>" if target_user else ""
        text = f"""
👑 <b>اقدام ادمین</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>ادمین:</b> <code>{admin_id}</code>
⚡ <b>اقدام:</b> {self._safe(action)}{target_text}
📄 <b>جزئیات:</b> {self._safe(details)}
"""
        await self.send_log(text)
    
    async def log_user_action(self, user_id: int, action: str, details: str = ""):
        """ثبت اقدامات کاربران عادی"""
        text = f"""
📝 <b>اقدام کاربر</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>کاربر:</b> <code>{user_id}</code>
⚡ <b>اقدام:</b> {self._safe(action)}
📄 <b>جزئیات:</b> {self._safe(details)}
"""
        await self.send_log(text)
    
    async def log_user_register(self, user_id: int, user_name: str, username: str):
        """ثبت ثبت‌نام کاربر جدید"""
        text = f"""
🆕 <b>کاربر جدید</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>نام:</b> {self._safe(user_name)}
🆔 <b>آیدی:</b> <code>{user_id}</code>
📛 <b>یوزرنیم:</b> @{self._safe(username) if username else 'ندارد'}
"""
        await self.send_log(text)
    
    async def log_purchase(self, user_id: int, order_id: int, volume: int, days: int, price: int, method: str):
        """ثبت خرید جدید"""
        text = f"""
🛒 <b>خرید جدید</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>کاربر:</b> <code>{user_id}</code>
🆔 <b>سفارش:</b> #{order_id}
📦 <b>حجم:</b> {volume} GB
⏱ <b>مدت:</b> {days} روز
💰 <b>مبلغ:</b> {price:,} تومان
💳 <b>روش پرداخت:</b> {self._safe(method)}
"""
        await self.send_log(text)
    
    async def log_balance_charge(self, user_id: int, order_id: int, amount: int):
        """ثبت درخواست شارژ حساب"""
        text = f"""
💰 <b>درخواست شارژ حساب</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>کاربر:</b> <code>{user_id}</code>
🆔 <b>سفارش:</b> #{order_id}
💵 <b>مبلغ:</b> {amount:,} تومان
"""
        await self.send_log(text)
    
    async def log_balance_charge_approved(self, order_id: int, user_id: int, amount: int):
        """ثبت تایید شارژ حساب"""
        text = f"""
✅ <b>تایید شارژ حساب</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
🆔 <b>سفارش:</b> #{order_id}
👤 <b>کاربر:</b> <code>{user_id}</code>
💵 <b>مبلغ:</b> {amount:,} تومان
"""
        await self.send_log(text)
    
    async def log_order_approved(self, order_id: int, user_id: int, volume: int, days: int, price: int):
        """ثبت تایید سفارش"""
        text = f"""
✅ <b>تایید سفارش</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
🆔 <b>سفارش:</b> #{order_id}
👤 <b>کاربر:</b> <code>{user_id}</code>
📦 <b>حجم:</b> {volume} GB
⏱ <b>مدت:</b> {days} روز
💰 <b>مبلغ:</b> {price:,} تومان
"""
        await self.send_log(text)
    
    async def log_order_rejected(self, order_id: int, user_id: int, reason: str = ""):
        """ثبت رد سفارش"""
        text = f"""
❌ <b>رد سفارش</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
🆔 <b>سفارش:</b> #{order_id}
👤 <b>کاربر:</b> <code>{user_id}</code>
📄 <b>دلیل:</b> {self._safe(reason) if reason else 'نامشخص'}
"""
        await self.send_log(text)
    
    async def log_balance_change(self, user_id: int, amount: int, new_balance: int, action: str, admin_id: int = None, details: str = ""):
        """ثبت تغییر موجودی"""
        action_text = "افزایش" if action == "add" else "کاهش"
        emoji = "➕" if action == "add" else "➖"
        admin_text = f"\n👑 <b>توسط ادمین:</b> <code>{admin_id}</code>" if admin_id else ""
        details_text = f"\n📄 <b>توضیحات:</b> {self._safe(details)}" if details else ""
        amount_abs = abs(amount)
        
        text = f"""
{emoji} <b>تغییر موجودی</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>کاربر:</b> <code>{user_id}</code>
⚡ <b>نوع:</b> {action_text}
💰 <b>مبلغ:</b> {amount_abs:,} تومان
💵 <b>موجودی جدید:</b> {new_balance:,} تومان{admin_text}{details_text}
"""
        await self.send_log(text)
    
    async def log_config_created(self, user_id: int, order_id: int, email: str, volume: int, days: int):
        """ثبت ساخت کانفیگ در پنل"""
        text = f"""
📡 <b>ساخت کانفیگ در پنل</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>کاربر:</b> <code>{user_id}</code>
🆔 <b>سفارش:</b> #{order_id}
📧 <b>ایمیل:</b> <code>{self._safe(email)}</code>
📦 <b>حجم:</b> {volume} GB
⏱ <b>مدت:</b> {days} روز
"""
        await self.send_log(text)
    
    async def log_config_view(self, user_id: int, order_id: int, view_type: str):
        """ثبت مشاهده کانفیگ"""
        text = f"""
👁️ <b>مشاهده کانفیگ</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>کاربر:</b> <code>{user_id}</code>
🆔 <b>سفارش:</b> #{order_id}
📱 <b>نوع مشاهده:</b> {self._safe(view_type)}
"""
        await self.send_log(text)
    
    async def log_feedback(self, user_id: int, order_id: int, rating: str, comment: str = ""):
        """ثبت بازخورد کاربر"""
        text = f"""
⭐ <b>بازخورد جدید</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>کاربر:</b> <code>{user_id}</code>
🆔 <b>سفارش:</b> #{order_id}
🎯 <b>امتیاز:</b> {self._safe(rating)}
💬 <b>نظر:</b> {self._safe(comment) if comment else 'بدون نظر'}
"""
        await self.send_log(text)
    
    async def log_chat_message(self, user_id: int, chat_id: int, message: str, sender: str = "user"):
        """ثبت پیام چت پشتیبانی"""
        sender_text = "کاربر" if sender == "user" else "ادمین"
        emoji = "💬" if sender == "user" else "👑"
        text = f"""
{emoji} <b>پیام چت پشتیبانی</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>فرستنده:</b> {sender_text} (<code>{user_id}</code>)
🆔 <b>چت:</b> #{chat_id}
📝 <b>متن:</b> {self._safe(message[:200])}
"""
        await self.send_log(text)
    
    async def log_chat_closed(self, chat_id: int, user_id: int, closed_by: str = "user"):
        """ثبت بسته شدن چت"""
        closer = "کاربر" if closed_by == "user" else "ادمین"
        text = f"""
🔒 <b>پایان چت</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
🆔 <b>چت:</b> #{chat_id}
👤 <b>کاربر:</b> <code>{user_id}</code>
🔚 <b>پایان‌دهنده:</b> {closer}
"""
        await self.send_log(text)
    
    async def log_user_deleted(self, admin_id: int, user_id: int, user_name: str):
        """ثبت حذف کاربر"""
        text = f"""
🗑️ <b>حذف کاربر</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👑 <b>ادمین:</b> <code>{admin_id}</code>
👤 <b>کاربر حذف شده:</b> {self._safe(user_name)} (<code>{user_id}</code>)
"""
        await self.send_log(text)
    
    async def log_price_update(self, admin_id: int, setting_key: str, old_value: int, new_value: int):
        """ثبت تغییر تنظیمات قیمت"""
        text = f"""
⚙️ <b>تغییر تنظیمات قیمت</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👑 <b>ادمین:</b> <code>{admin_id}</code>
📊 <b>تنظیمات:</b> {self._safe(setting_key)}
📉 <b>مقدار قدیم:</b> {old_value:,} تومان
📈 <b>مقدار جدید:</b> {new_value:,} تومان
"""
        await self.send_log(text)
    
    async def log_error(self, error: Exception, function_name: str, user_id: int = None):
        """ثبت خطا"""
        user_text = f"\n👤 <b>کاربر:</b> <code>{user_id}</code>" if user_id else ""
        text = f"""
⚠️ <b>خطا در سیستم</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
📁 <b>تابع:</b> {self._safe(function_name)}
❌ <b>خطا:</b> {self._safe(str(error)[:200])}{user_text}
"""
        await self.send_log(text)
    
    async def log_force_join_channel(self, admin_id: int, channel_name: str, channel_id: int, action: str = "add"):
        """ثبت افزودن یا حذف کانال عضویت اجباری"""
        action_text = "افزودن" if action == "add" else "حذف"
        emoji = "➕" if action == "add" else "➖"
        text = f"""
{emoji} <b>تغییر کانال عضویت اجباری</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👑 <b>ادمین:</b> <code>{admin_id}</code>
⚡ <b>عملیات:</b> {action_text}
📢 <b>کانال:</b> {self._safe(channel_name)}
🆔 <b>آیدی:</b> <code>{channel_id}</code>
"""
        await self.send_log(text)
    
    async def log_force_join_toggle(self, admin_id: int, enabled: bool):
        """ثبت فعال/غیرفعال کردن عضویت اجباری"""
        status = "فعال" if enabled else "غیرفعال"
        emoji = "🟢" if enabled else "🔴"
        text = f"""
{emoji} <b>تغییر وضعیت عضویت اجباری</b>
🕐 <b>زمان:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>
👑 <b>ادمین:</b> <code>{admin_id}</code>
⚙️ <b>وضعیت جدید:</b> {status}
"""
        await self.send_log(text)
    
    async def close(self):
        """بستن جلسه بات و انتظار برای ارسال لاگ‌های باقیمانده"""
        timeout = 30
        start = datetime.now()
        
        while not self.log_queue.empty() and (datetime.now() - start).seconds < timeout:
            await asyncio.sleep(1)
        
        try:
            await self.bot.session.close()
        except:
            pass


async def init_logger():
    """راه‌اندازی سیستم لاگ"""
    try:
        from config import LOG_BOT_TOKEN, LOG_CHANNEL_ID
        
        if not LOG_BOT_TOKEN or not LOG_CHANNEL_ID:
            logger.warning("⚠️ تنظیمات لاگ کامل نیست")
            return None
        
        log_system = LogSystem(LOG_BOT_TOKEN, int(LOG_CHANNEL_ID))
        await log_system.send_log("✅ <b>سیستم لاگ راه‌اندازی شد</b>")
        return log_system
    except ImportError:
        logger.warning("⚠️ ماژول config یافت نشد")
        return None
    except Exception as e:
        logger.error(f"❌ خطا در راه‌اندازی سیستم لاگ: {e}")
        return None
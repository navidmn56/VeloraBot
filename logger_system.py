import asyncio
import logging
from datetime import datetime
from typing import Optional
from aiogram import Bot
import html
import re

from database import TEHRAN_TZ, now_tehran

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
                    logger.warning(f"HTML entity parsing error in log message, retrying without parse_mode")
                    try:
                        await self.bot.send_message(
                            self.log_channel_id,
                            message,
                            parse_mode=None
                        )
                        self.last_send_time = datetime.now().timestamp()
                        return True
                    except Exception as e2:
                        logger.error(f"Failed to send log message without parse_mode: {e2}")
                elif attempt < retry_count - 1:
                    logger.warning(f"Error sending log message (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(2 * (attempt + 1))
                else:
                    logger.error(f"Failed to send log message after {retry_count} attempts: {e}")
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
                    logger.error(f"Error processing log queue: {e}")
                    await asyncio.sleep(2)
                    
        finally:
            self.is_sending = False
    
    async def send_log(self, message: str, parse_mode: str = "HTML"):
        """ارسال پیام لاگ به کانال با استفاده از صف"""
        timestamp = now_tehran().strftime('%H:%M:%S')
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
🚀 <b>Bot Started</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
🤖 <b>Name:</b> {self._safe(bot_info.first_name)}
📛 <b>Username:</b> @{self._safe(bot_info.username)}
🆔 <b>ID:</b> <code>{bot_info.id}</code>
👑 <b>Admin:</b> <code>{admin_id}</code>
"""
        await self.send_log(text)
    
    async def log_bot_stop(self, admin_id: int):
        """ثبت توقف ربات"""
        text = f"""
🛑 <b>Bot Stopped</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👑 <b>Admin:</b> <code>{admin_id}</code>
"""
        await self.send_log(text)
    
    async def log_admin_action(self, admin_id: int, action: str, target_user: int = None, details: str = ""):
        """ثبت اقدامات ادمین"""
        target_text = f"\n🎯 <b>Target User:</b> <code>{target_user}</code>" if target_user else ""
        text = f"""
👑 <b>Admin Action</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>Admin:</b> <code>{admin_id}</code>
⚡ <b>Action:</b> {self._safe(action)}{target_text}
📄 <b>Details:</b> {self._safe(details)}
"""
        await self.send_log(text)
    
    async def log_user_action(self, user_id: int, action: str, details: str = ""):
        """ثبت اقدامات کاربران عادی"""
        text = f"""
📝 <b>User Action</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>User:</b> <code>{user_id}</code>
⚡ <b>Action:</b> {self._safe(action)}
📄 <b>Details:</b> {self._safe(details)}
"""
        await self.send_log(text)
    
    async def log_user_register(self, user_id: int, user_name: str, username: str):
        """ثبت ثبت‌نام کاربر جدید"""
        text = f"""
🆕 <b>New User</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>Name:</b> {self._safe(user_name)}
🆔 <b>ID:</b> <code>{user_id}</code>
📛 <b>Username:</b> @{self._safe(username) if username else 'N/A'}
"""
        await self.send_log(text)
    
    async def log_purchase(self, user_id: int, order_id: int, volume: int, days: int, price: int, method: str):
        """ثبت خرید جدید"""
        text = f"""
🛒 <b>New Purchase</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>User:</b> <code>{user_id}</code>
🆔 <b>Order:</b> #{order_id}
📦 <b>Volume:</b> {volume} GB
⏱ <b>Duration:</b> {days} days
💰 <b>Amount:</b> {price:,} Toman
💳 <b>Payment Method:</b> {self._safe(method)}
"""
        await self.send_log(text)
    
    async def log_balance_charge(self, user_id: int, order_id: int, amount: int):
        """ثبت درخواست شارژ حساب"""
        text = f"""
💰 <b>Balance Top-Up Request</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>User:</b> <code>{user_id}</code>
🆔 <b>Order:</b> #{order_id}
💵 <b>Amount:</b> {amount:,} Toman
"""
        await self.send_log(text)
    
    async def log_balance_charge_approved(self, order_id: int, user_id: int, amount: int):
        """ثبت تایید شارژ حساب"""
        text = f"""
✅ <b>Balance Top-Up Approved</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
🆔 <b>Order:</b> #{order_id}
👤 <b>User:</b> <code>{user_id}</code>
💵 <b>Amount:</b> {amount:,} Toman
"""
        await self.send_log(text)
    
    async def log_order_approved(self, order_id: int, user_id: int, volume: int, days: int, price: int):
        """ثبت تایید سفارش"""
        text = f"""
✅ <b>Order Approved</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
🆔 <b>Order:</b> #{order_id}
👤 <b>User:</b> <code>{user_id}</code>
📦 <b>Volume:</b> {volume} GB
⏱ <b>Duration:</b> {days} days
💰 <b>Amount:</b> {price:,} Toman
"""
        await self.send_log(text)
    
    async def log_order_rejected(self, order_id: int, user_id: int, reason: str = ""):
        """ثبت رد سفارش"""
        text = f"""
❌ <b>Order Rejected</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
🆔 <b>Order:</b> #{order_id}
👤 <b>User:</b> <code>{user_id}</code>
📄 <b>Reason:</b> {self._safe(reason) if reason else 'Unspecified'}
"""
        await self.send_log(text)
    
    async def log_balance_change(self, user_id: int, amount: int, new_balance: int, action: str, admin_id: int = None, details: str = ""):
        """ثبت تغییر موجودی"""
        action_text = "Increase" if action == "add" else "Decrease"
        emoji = "➕" if action == "add" else "➖"
        admin_text = f"\n👑 <b>By Admin:</b> <code>{admin_id}</code>" if admin_id else ""
        details_text = f"\n📄 <b>Details:</b> {self._safe(details)}" if details else ""
        amount_abs = abs(amount)

        text = f"""
{emoji} <b>Balance Change</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>User:</b> <code>{user_id}</code>
⚡ <b>Type:</b> {action_text}
💰 <b>Amount:</b> {amount_abs:,} Toman
💵 <b>New Balance:</b> {new_balance:,} Toman{admin_text}{details_text}
"""
        await self.send_log(text)
    
    async def log_config_created(self, user_id: int, order_id: int, email: str, volume: int, days: int):
        """ثبت ساخت کانفیگ در پنل"""
        text = f"""
📡 <b>Configuration Created in Panel</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>User:</b> <code>{user_id}</code>
🆔 <b>Order:</b> #{order_id}
📧 <b>Email:</b> <code>{self._safe(email)}</code>
📦 <b>Volume:</b> {volume} GB
⏱ <b>Duration:</b> {days} days
"""
        await self.send_log(text)
    
    async def log_config_view(self, user_id: int, order_id: int, view_type: str):
        """ثبت مشاهده کانفیگ"""
        text = f"""
👁️ <b>Configuration Viewed</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>User:</b> <code>{user_id}</code>
🆔 <b>Order:</b> #{order_id}
📱 <b>View Type:</b> {self._safe(view_type)}
"""
        await self.send_log(text)
    
    async def log_feedback(self, user_id: int, order_id: int, rating: str, comment: str = ""):
        """ثبت بازخورد کاربر"""
        text = f"""
⭐ <b>New Feedback</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>User:</b> <code>{user_id}</code>
🆔 <b>Order:</b> #{order_id}
🎯 <b>Rating:</b> {self._safe(rating)}
💬 <b>Comment:</b> {self._safe(comment) if comment else 'No comment'}
"""
        await self.send_log(text)
    
    async def log_chat_message(self, user_id: int, chat_id: int, message: str, sender: str = "user"):
        """ثبت پیام چت پشتیبانی"""
        sender_text = "User" if sender == "user" else "Admin"
        emoji = "💬" if sender == "user" else "👑"
        text = f"""
{emoji} <b>Support Chat Message</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👤 <b>Sender:</b> {sender_text} (<code>{user_id}</code>)
🆔 <b>Chat:</b> #{chat_id}
📝 <b>Text:</b> {self._safe(message[:200])}
"""
        await self.send_log(text)
    
    async def log_chat_closed(self, chat_id: int, user_id: int, closed_by: str = "user"):
        """ثبت بسته شدن چت"""
        closer = "User" if closed_by == "user" else "Admin"
        text = f"""
🔒 <b>Chat Closed</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
🆔 <b>Chat:</b> #{chat_id}
👤 <b>User:</b> <code>{user_id}</code>
🔚 <b>Closed By:</b> {closer}
"""
        await self.send_log(text)
    
    async def log_user_deleted(self, admin_id: int, user_id: int, user_name: str):
        """ثبت حذف کاربر"""
        text = f"""
🗑️ <b>User Deleted</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👑 <b>Admin:</b> <code>{admin_id}</code>
👤 <b>Deleted User:</b> {self._safe(user_name)} (<code>{user_id}</code>)
"""
        await self.send_log(text)
    
    async def log_price_update(self, admin_id: int, setting_key: str, old_value: int, new_value: int):
        """ثبت تغییر تنظیمات قیمت"""
        text = f"""
⚙️ <b>Price Settings Updated</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👑 <b>Admin:</b> <code>{admin_id}</code>
📊 <b>Setting:</b> {self._safe(setting_key)}
📉 <b>Previous Value:</b> {old_value:,} Toman
📈 <b>New Value:</b> {new_value:,} Toman
"""
        await self.send_log(text)
    
    async def log_error(self, error: Exception, function_name: str, user_id: int = None):
        """ثبت خطا"""
        user_text = f"\n👤 <b>User:</b> <code>{user_id}</code>" if user_id else ""
        text = f"""
⚠️ <b>System Error</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
📁 <b>Function:</b> {self._safe(function_name)}
❌ <b>Error:</b> {self._safe(str(error)[:200])}{user_text}
"""
        await self.send_log(text)
    
    async def log_force_join_channel(self, admin_id: int, channel_name: str, channel_id: int, action: str = "add"):
        """ثبت افزودن یا حذف کانال عضویت اجباری"""
        action_text = "Add" if action == "add" else "Remove"
        emoji = "➕" if action == "add" else "➖"
        text = f"""
{emoji} <b>Required Membership Channel Updated</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👑 <b>Admin:</b> <code>{admin_id}</code>
⚡ <b>Action:</b> {action_text}
📢 <b>Channel:</b> {self._safe(channel_name)}
🆔 <b>ID:</b> <code>{channel_id}</code>
"""
        await self.send_log(text)
    
    async def log_force_join_toggle(self, admin_id: int, enabled: bool):
        """Log required-membership status changes"""
        status = "Enabled" if enabled else "Disabled"
        emoji = "🟢" if enabled else "🔴"
        text = f"""
{emoji} <b>Required Membership Status Updated</b>
🕐 <b>Time:</b> <code>{now_tehran().strftime('%Y-%m-%d %H:%M:%S')}</code>
👑 <b>Admin:</b> <code>{admin_id}</code>
⚙️ <b>New Status:</b> {status}
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
        except Exception:
            pass


async def init_logger():
    """راه‌اندازی سیستم لاگ"""
    try:
        from config import LOG_BOT_TOKEN, LOG_CHANNEL_ID
        
        if not LOG_BOT_TOKEN or not LOG_CHANNEL_ID:
            logger.warning("Logging system settings are incomplete")
            return None

        log_system = LogSystem(LOG_BOT_TOKEN, int(LOG_CHANNEL_ID))
        await log_system.send_log("✅ <b>Logging System Started</b>")
        return log_system
    except ImportError:
        logger.warning("Config module not found")
        return None
    except Exception as e:
        logger.error(f"Error initializing logging system: {e}")
        return None
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, "users.json")
ORDERS_FILE = os.path.join(DATA_DIR, "orders.json")
REFERRAL_FILE = os.path.join(DATA_DIR, "referral.json")
CONFIGS_FILE = os.path.join(DATA_DIR, "configs.json")








# ==================== 🔴 REQUIRED SETTINGS 🔴 ====================
# These settings MUST be filled for the bot to work properly
BOT_TOKEN = "Main_bot_token"  # Get from @BotFather
ADMIN_ID = "YOUR_TELEGRAM_USER_ID" # Your Telegram ID (get from @myidbot)
BANK_CARD_NUMBER = "1234567812345678" # Your bank card number (Only 16 digits (no spaces, dashes, or underscores))
BANK_CARD_HOLDER = "Navid" # Card holder's full name
BANK_NAME = "Blue Bank" # e.g., "Blue Bank", "Melli", "Mellat"
SENAI_PANEL_URL = "https://panel.Domain.com:2053/c7UvLu2tMjFjP8BwiW" # OR use localhost: "https://127.0.0.1:2053/your_Web_Path"
SENAI_PANEL_USERNAME = "Panel_username" # Panel admin username
SENAI_PANEL_PASSWORD = "Panel_password" # Panel admin password
SENAI_SUB_URL = "https://sub.Domain.com:2083" # Subscription URL for clients
SUPPORT_USERNAME = "@your_username_here"

# =============== 🟡 OPTIONAL: LOGS SETTINGS ===============
LOG_BOT_TOKEN = ""  # Token of the second bot (will work after make it admin in LOG Group)
LOG_CHANNEL_ID = None  # replace None to group ID where logs will be sent (how to get group id: add @myidbot to your Group then get group Id with this command "/getid@myidbot", output example: Your own ID is: -5165329724 (start with negetive))


# =============== 🟡 OPTIONAL:َAi Google Gemini ===============
GEMINI_ENABLED = False # Set to True to enable Gemini AI
GEMINI_API_KEY = "Gemini_API_Key" # Get from https://ai.google.dev/
GEMINI_MODEL = "gemini-2.5-flash" #you can set it to any model of gemini
GEMINI_TEMPERATURE = 0.7  # Controls randomness (0.0 to 1.0)
GEMINI_MAX_TOKENS = 90  # Maximum response length
GEMINI_DAILY_LIMIT = 3 # Max AI responses per user per day


# System Prompt you can costumize it
def load_configs_from_json():
    """بارگذاری اطلاعات از configs.json"""
    if not os.path.exists(CONFIGS_FILE):
        logger.warning(f"⚠️ فایل configs.json یافت نشد: {CONFIGS_FILE}")
        return {}
    
    try:
        with open(CONFIGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"❌ خطا در خواندن configs.json: {e}")
        return {}


def get_price_settings_text(configs_data: dict) -> str:
    """دریافت اطلاعات قیمت‌ها"""
    price_settings = configs_data.get('price_settings', {})
    
    referral_bonus = price_settings.get('referral_bonus', 5000) or 0
    min_charge = price_settings.get('min_charge', 10000) or 0
    max_charge = price_settings.get('max_charge', 5000000) or 0
    
    return f"""
💰 قیمت‌ها:
- پاداش معرفی: {referral_bonus:,} تومان
- حداقل شارژ: {min_charge:,} تومان
- حداکثر شارژ: {max_charge:,} تومان
"""


def get_ready_packages_text(configs_data: dict) -> str:
    """دریافت اطلاعات بسته‌های آماده"""
    ready_packages = configs_data.get('ready_packages', {})
    
    if not ready_packages.get('enabled', False):
        return "📦 بسته‌های آماده غیرفعال است"
    
    categories = ready_packages.get('categories', [])
    
    if not categories:
        return "📦 هیچ بسته آماده‌ای موجود نیست"
    
    text = "📦 بسته‌های آماده:\n"
    
    for cat in categories:
        if not cat.get('is_active', True):
            continue
        
        cat_name = cat.get('name', '') or ''
        cat_name_en = cat.get('name_en', '') or ''
        cat_icon = cat.get('icon', '📦') or '📦'
        cat_desc = cat.get('description', '') or ''
        
        text += f"\n{cat_icon} {cat_name}"
        if cat_name_en:
            text += f" ({cat_name_en})"
        text += "\n"
        
        if cat_desc:
            text += f"   {cat_desc}\n"
        
        packages = cat.get('packages', [])
        for pkg in packages:
            if not pkg.get('is_active', True):
                continue
            
            pkg_volume = pkg.get('volume', 0) or 0
            pkg_days = pkg.get('days', 30) or 30
            pkg_price = pkg.get('price', 0) or 0
            pkg_ip = pkg.get('ip_limit', 0) or 0
            
            volume_display = "♾️ نامحدود" if pkg_volume == 0 else f"{pkg_volume}GB"
            ip_display = "نامحدود" if pkg_ip == 0 else str(pkg_ip)
            
            text += f"   • {volume_display} / {pkg_days} روز / {pkg_price:,} تومان / {ip_display} IP\n"
    
    return text


def get_test_service_text(configs_data: dict) -> str:
    """دریافت اطلاعات تست رایگان"""
    test_service = configs_data.get('test_service', {})
    
    if not test_service.get('enabled', False):
        return "🧪 تست رایگان غیرفعال است"
    
    test_volume = test_service.get('volume', 0) or 0
    test_days = test_service.get('days', 0) or 0
    max_tests = test_service.get('max_tests', 0) or 0
    ip_limit = test_service.get('ip_limit', 0) or 0
    
    volume_display = "♾️ نامحدود" if test_volume == 0 else f"{test_volume}GB"
    ip_display = "نامحدود" if ip_limit == 0 else str(ip_limit)
    
    return f"""
🧪 تست رایگان:
- حجم: {volume_display}
- مدت: {test_days} روز
- حداکثر تست: {max_tests} بار
- محدودیت IP: {ip_display}
"""


def get_shop_status_text(configs_data: dict) -> str:
    """دریافت وضعیت فروشگاه"""
    shop_status = configs_data.get('shop_status', {})
    
    if not shop_status:
        return "🛍 فروشگاه باز است"
    
    is_open = shop_status.get('is_open', True)
    message = shop_status.get('message', '') or ''
    
    if is_open:
        return "🛍 فروشگاه باز است"
    else:
        return f"🚫 فروشگاه بسته است\n{message}"


def get_force_join_text(configs_data: dict) -> str:
    """دریافت اطلاعات عضویت اجباری"""
    force_join = configs_data.get('force_join_settings', {})
    
    if not force_join.get('enabled', False):
        return ""
    
    channels = force_join.get('channels', [])
    
    if not channels:
        return ""
    
    text = "📢 کانال‌های ما:\n"
    for ch in channels:
        ch_name = ch.get('name', '') or ''
        ch_username = ch.get('username', '') or ''
        if ch_username:
            text += f"• {ch_name} - {ch_username}\n"
    
    return text


def get_bank_card_text() -> str:
    """دریافت اطلاعات کارت بانکی"""
    # حذف همه کاراکترهای غیر عددی
    clean_card = ''.join(filter(str.isdigit, BANK_CARD_NUMBER))
    card_formatted = ' '.join([clean_card[i:i+4] for i in range(0, len(clean_card), 4)])    
    return f"""
💳 اطلاعات پرداخت:
- شماره کارت: {card_formatted}
- به نام: {BANK_CARD_HOLDER}
- بانک: {BANK_NAME}
"""


def get_support_text() -> str:
    """دریافت اطلاعات پشتیبانی"""
    return f"""
💬 پشتیبانی: {SUPPORT_USERNAME}
"""


def generate_dynamic_system_prompt() -> str:
    """تولید پرامپت داینامیک با اطلاعات دیتابیس"""
    
    # بارگذاری اطلاعات
    configs_data = load_configs_from_json()
    
    # دریافت بخش‌های مختلف
    price_text = get_price_settings_text(configs_data)
    packages_text = get_ready_packages_text(configs_data)
    test_text = get_test_service_text(configs_data)
    shop_text = get_shop_status_text(configs_data)
    force_join_text = get_force_join_text(configs_data)
    bank_card_text = get_bank_card_text()
    support_text = get_support_text()
    
    # ساخت پرامپت کامل
    prompt = f"""تو یک دستیار فروش کانفیگ VPN هستی.

⚠️ قوانین بسیار مهم برای پاسخ‌دهی:
1. فقط و فقط به زبان فارسی روان و قابل فهم جواب بده
2. پاسخ‌ها را کامل فارسی بنویس
3. از کلمات انگلیسی فقط برای نام برنامه‌ها و لینک‌ها استفاده کن
5. اگه انگلیسی نوشتی، حتماً معنی فارسی هم بنویس
6. لینک‌ها را جداگانه در خط بعدی بنویس
7. هر بخش را با ایموجی مناسب شروع کن
8. از فاصله مناسب بین بخش‌ها استفاده کن
9. پاسخ‌ها حداکثر 3 خط باشه
10. مستقیم و بدون حاشیه جواب بده

{shop_text}

⚡ سرعت کانفیگ‌ها:
- بالا، پایدار، تأخیر کم (مناسب بازی و استریم)
- بدون قطعی و افت سرعت
- تانل توی نت ملی وصله

{price_text}

{packages_text}

{test_text}

📱 راهنمای نصب:
- اندروید: برنامه V2RayNG (وی‌تو‌ری ان‌جی)
  لینک دانلود: https://github.com/2dust/v2rayng
- iOS: برنامه V2box (وی‌تو باکس)
  لینک دانلود: https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690
- ویندوز: برنامه V2rayN (وی‌تو‌ری ان)
  لینک دانلود: https://github.com/2dust/v2rayn

{bank_card_text}

{support_text}

{force_join_text}

📋 راهنمای پاسخ به سوالات متداول:

❓ اگه کاربر پرسید چطور وصل بشه:
1. اول برنامه مناسب دستگاهش رو معرفی کن
2. لینک دانلود رو بده
3. بگو لینک ساب رو کپی کنه
4. توی برنامه paste کنه
5. اگه وصل نشد، بگو از گوگل تحقیق میکنی

❓ اگه کاربر پرسید قیمت چند هست:
- قیمت بسته‌های آماده رو از اطلاعات بالا بگو
- اگه خرید سفارشی میخواد، بگو قیمت بر اساس حجم و مدت محاسبه میشه

❓ اگه کاربر مشکل اتصال داشت:
- ازش بپرس چه اروری میده
- راهنماییش کن برنامه رو آپدیت کنه
- لینک ساب رو دوباره import کنه
- اگه حل نشد، به پشتیبانی معرفی کن

❓ اگه کاربر پرسید شارژ حساب:
- بگو باید فیش واریزی بفرسته
- بعد از تایید، موجودیش شارژ میشه
- ممکنه چند دقیقه طول بکشه

⚠️ قوانین نهایی:
- حداقل شارژ: {configs_data.get('price_settings', {}).get('min_charge', 10000):,} تومان
- حداکثر شارژ: {configs_data.get('price_settings', {}).get('max_charge', 5000000):,} تومان
- اگه سوال تکراریه، کوتاه جواب بده
- فقط به سوال کاربر جواب بده
- از کاربر سوال بپرس تا مشکلش دقیق‌تر مشخص بشه
- راهنمایی کامل بده نه جواب نصفه
"""
    
    return prompt


# تلاش برای تولید پرامپت داینامیک
try:
    GEMINI_SYSTEM_PROMPT = generate_dynamic_system_prompt()
    logger.info("✅ GEMINI_SYSTEM_PROMPT با اطلاعات داینامیک تولید شد")
except Exception as e:
    logger.error(f"❌ خطا در تولید GEMINI_SYSTEM_PROMPT داینامیک: {e}")
    
    # برگشت به پرامپت ثابت
    GEMINI_SYSTEM_PROMPT = f"""دستیار فروش کانفیگ VPN. پاسخ‌ها کوتاه، مفید و مستقیم باشد.

⚡ سرعت کانفیگ‌ها:
- بالا، پایدار، تأخیر کم (مناسب بازی و استریم)
- بدون قطعی و افت سرعت
- تو نت ملی هم وصلیم

📦 قیمت‌ها:
- بر اساس حجم (GB) و مدت (روز) محاسبه می‌شود
- مقرون به صرفه و رقابتی

📱 نصب:
- اندروید: V2RayNG - https://github.com/2dust/v2rayng
- iOS: V2box - https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690
- ویندوز: V2rayN - https://github.com/2dust/v2rayn

💳 شماره کارت: {BANK_CARD_NUMBER}
به نام: {BANK_CARD_HOLDER}
بانک: {BANK_NAME}

💬 پشتیبانی: {SUPPORT_USERNAME}

⚠️ قوانین:
- پاسخ‌ها حداکثر ۳ خط
- مختصر، مفید و مستقیم
- فقط به سوال پاسخ بده
"""

def refresh_gemini_prompt():
    """بازسازی GEMINI_SYSTEM_PROMPT با اطلاعات جدید"""
    global GEMINI_SYSTEM_PROMPT
    
    try:
        GEMINI_SYSTEM_PROMPT = generate_dynamic_system_prompt()
        logger.info("🔄 GEMINI_SYSTEM_PROMPT با موفقیت به‌روزرسانی شد")
        return True
    except Exception as e:
        logger.error(f"❌ خطا در به‌روزرسانی GEMINI_SYSTEM_PROMPT: {e}")
        return False


#✅Configuration complete! Enjoy your bot.











# ⚠️ Note: This feature is currently not working, do not enable

OPENROUTER_ENABLED = False
OPENROUTER_API_KEY = "Api_Token"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS = [
    
    "mistralai/mistral-7b-instruct:free",      
    "meta-llama/llama-3.2-3b-instruct:free",   
    "microsoft/phi-3-mini-128k-instruct:free", 
    "qwen/qwen-2.5-7b-instruct:free",          
    
    
    "google/gemini-2.0-flash-exp:free",         
    "google/gemini-2.0-pro-exp:free",           
    "nvidia/nemotron-4-340b-instruct:free",     
    "deepseek/deepseek-chat:free",              
]
OPENROUTER_TEMPERATURE = 0.7
OPENROUTER_MAX_TOKENS = 500
OPENROUTER_TOP_P = 0.9
OPENROUTER_DAILY_LIMIT = 15
OPENROUTER_SYSTEM_PROMPT = """شما یک دستیار هوشمند و مختصر برای ربات تلگرام فروش کانفیگ VPN هستید.

⚠️ قوانین بسیار مهم:
1. فقط به سوالی که پرسیده شده پاسخ دهید
2. پاسخ‌ها باید مختصر، دقیق و مفید باشد
3. از توضیحات اضافی و تکراری خودداری کنید
4. مستقیماً به سوال کاربر پاسخ دهید
5. پاسخ‌ها را با ایموجی‌های مناسب مختصر کنید

اطلاعات کلی:
- کانفیگ‌ها با قیمت‌های رقابتی ارائه می‌شوند
- قیمت بر اساس حجم و مدت زمان محاسبه می‌شود
- قطع و وصلی ندارند و پایدار هستند
- پشتیبانی: @my_name_is_navid

اطلاعات فنی کلی:
- کانفیگ‌ها با پروتکل‌های VLESS ارائه می‌شوند
- برای اندروید: از V2RayNG یا Happ استفاده کنید
- برای iOS: از Shadowrocket یا V2Box استفاده کنید
- برای ویندوز: از Nekoray یا V2RayN استفاده کنید
- برای مک: از V2box یا Nekoray استفاده کنید

سبک پاسخ‌دهی: مختصر، مفید، بدون توضیحات اضافی
"""


AUTO_AI_RESPONSE = True
AI_KEYWORDS = [
    'چطور', 'چگونه', 'راهنمایی', 'مشکل', 'ارور', 'اتصال', 'قطع', 'وصل',
    'vpn', 'کانفیگ', 'کانفیک', 'v2ray', 'vless', 'trojan', 'حجم', 'قیمت',
    'خرید', 'شارژ', 'پرداخت', 'رفرال', 'اندروید', 'ios', 'ویندوز'
]
AI_BLOCKED_STATES = [
    'awaiting_receipt', 'awaiting_amount', 'awaiting_chat',
    'awaiting_feedback_comment', 'awaiting_config', 'awaiting_manual_balance'
]
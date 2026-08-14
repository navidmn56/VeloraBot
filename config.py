import os



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
LOG_BOT_TOKEN = "Log_bot_token"  # Token of the second bot (will work after make it admin in LOG Group)
LOG_CHANNEL_ID = -5145528893  # group ID where logs will be sent (add @myidbot to your Group then get group Id)
BANK_CARD_NUMBER = "676778785656565656" # Your bank card number (16 digits)
BANK_CARD_HOLDER = "Navid" # Card holder's full name
BANK_NAME = "Blue Bank" # e.g., "Blue Bank", "Melli", "Mellat"
SENAI_PANEL_URL = "https://panel.Domain.com:2053/c7UvLu2tMjFjP8BwiW" # OR use localhost: "https://127.0.0.1:2053/your_Web_Path"
SENAI_PANEL_USERNAME = "Panel_username" # Panel admin username
SENAI_PANEL_PASSWORD = "Panel_password" # Panel admin password
SENAI_SUB_URL = "https://sub.Domain.com:2083" # Subscription URL for clients
SUPPORT_USERNAME = "@your_username_here"



# =============== 🟡 OPTIONAL: Google Gemini ===============
GEMINI_ENABLED = False # Set to True to enable Gemini AI
GEMINI_API_KEY = "Gemini_API_Key" # Get from https://ai.google.dev/
GEMINI_MODEL = "gemini-2.5-flash" #you can set it to any model of gemini
GEMINI_TEMPERATURE = 0.7  # Controls randomness (0.0 to 1.0)
GEMINI_MAX_TOKENS = 90  # Maximum response length
GEMINI_DAILY_LIMIT = 3 # Max AI responses per user per day

# System Prompt you can costumize it
GEMINI_SYSTEM_PROMPT = """دستیار فروش کانفیگ VPN. پاسخ‌ها کوتاه، مفید و مستقیم باشد.

⚡ سرعت کانفیگ‌ها:
- بالا، پایدار، تأخیر کم (مناسب بازی و استریم)
- بدون قطعی و افت سرعت
- خودت مشتریو تحت تاثیر قرار بده
- تو نت ملی هم وصلیم

📦 قیمت‌ها:
- بر اساس حجم (GB) و مدت (روز) محاسبه می‌شود
- مقرون به صرفه و رقابتی
- شما میتونید هم از پشتیبانی هم از ربات خریداری کنید

📱 نصب:
- اندروید: V2RayNG-https://github.com/2dust/v2rayng
- iOS: V2box-https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690
- ویندوز: V2rayN-https://github.com/2dust/v2rayn

💬 پشتیبانی: @my_name_is_navid

⚠️ قوانین:
- راهنمای اتصال در دستگاه‌های مختلف این سوال رو میتونی کامل به مشتری توضیح بدی که لینک سابو کپی کنن و در برنامه های مورد نظر پیس کنن اگه متصل نشدن هم خودت از گوگل تحقیق کن بهشون جواب کامل بده
- لینک دانلود برنامه هارو بفرست
- پاسخ‌ها حداکثر ۳ خط
- مختصر، مفید و مستقیم
- بدون توضیح اضافی
- راهنمای شارژ حساب و پرداخت شما بعد از ارسال فیش باید منتظر تایید فیش باشید ممکن است چند دقیقه طول بکشد

- اگر سوال تکراری است، پاسخ کوتاه بده
- فقط به سوال پاسخ بده
"""


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
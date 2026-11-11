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
ADMIN_ID = "YOUR_TELEGRAM_USER_ID"  # Your Telegram ID (get from @myidbot)
BANK_CARD_NUMBER = "1234567812345678"  # Your bank card number (Only 16 digits)
BANK_CARD_HOLDER = "Navid"  # Card holder's full name
BANK_NAME = "Blue Bank"  # e.g., "Blue Bank", "Melli", "Mellat"
SENAI_PANEL_URL = "https://panel.Domain.com:2053/c7UvLu2tMjFjP8BwiW"
SENAI_PANEL_USERNAME = "Panel_username"
SENAI_PANEL_PASSWORD = "Panel_password"
# Optional: Set to "auto" to automatically fetch subscription link from Sanaei panel, or set a custom URL (e.g. "https://sub.Domain.com:2083/sub")
SENAI_SUB_URL = "auto"
SUPPORT_USERNAME = "@your_username_here"

# =============== 🟡 OPTIONAL: REACTION SETTINGS ===============
START_REACTION_EMOJI = "⚡"  # Emoji reaction for /start message (e.g. "🔥", "⚡", "👍", "❤️", "🎉")


# =============== 🟡 OPTIONAL: LOGS SETTINGS ===============
LOG_BOT_TOKEN = ""  # Token of the second bot
LOG_CHANNEL_ID = None  # replace None to group ID where logs will be sent


# =============== 🟡 OPTIONAL: AI Google Gemini ===============
GEMINI_ENABLED = False  # Set to True to enable Gemini AI
GEMINI_API_KEY = "Gemini_API_Key"  # Get from https://ai.google.dev/
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.7
GEMINI_MAX_TOKENS = 512
GEMINI_DAILY_LIMIT = 3


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


def format_volume_for_prompt(volume_gb) -> str:
    """نمایش حجم در پرامپت با واحد قابل‌فهم برای کاربر."""
    try:
        volume = float(volume_gb)
    except (TypeError, ValueError):
        return f"{volume_gb} گیگ"

    if volume == 0:
        return "نامحدود"
    if volume < 1:
        megabytes = int(round(volume * 1024))
        return f"{megabytes} مگابایت"
    volume_text = str(int(volume)) if volume.is_integer() else f"{volume:g}"
    return f"{volume_text} گیگابایت"


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

            volume_display = format_volume_for_prompt(pkg_volume)
            ip_display = "نامحدود" if pkg_ip == 0 else str(pkg_ip)

            text += f"   • {volume_display} / {pkg_days} روز / {pkg_price:,} تومان / {ip_display} IP\n"

    return text


def get_test_service_text(configs_data: dict) -> str:
    """دریافت اطلاعات تست رایگان"""
    test_service = configs_data.get('test_service', {})

    if not test_service.get('enabled', False):
        return "🧪 تست رایگان غیرفعال است"

    test_volume_mb = test_service.get('volume_mb')
    if test_volume_mb is not None:
        try:
            test_volume = float(test_volume_mb) / 1024
        except (TypeError, ValueError):
            test_volume = test_service.get('volume', 0) or 0
    else:
        test_volume = test_service.get('volume', 0) or 0
    test_days = test_service.get('days', 0) or 0
    max_tests = test_service.get('max_tests', 0) or 0
    ip_limit = test_service.get('ip_limit', 0) or 0

    volume_display = format_volume_for_prompt(test_volume)
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
    clean_card = ''.join(filter(str.isdigit, BANK_CARD_NUMBER))
    card_formatted = ' '.join([clean_card[i:i + 4] for i in range(0, len(clean_card), 4)])
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
    configs_data = load_configs_from_json()

    price_text = get_price_settings_text(configs_data)
    packages_text = get_ready_packages_text(configs_data)
    test_text = get_test_service_text(configs_data)
    shop_text = get_shop_status_text(configs_data)
    support_text = get_support_text()

    prompt = f"""دستیار فروش و پشتیبانی VPN هستی. فارسی طبیعی، خلاق و موجز پاسخ بده؛ فقط از داده‌های زیر و context همین کاربر استفاده کن و چیزی را حدس نزن. snapshot فقط خواندنی و متعلق به همان کاربر است. ادعای پرداخت، تغییر داده یا تحویل کانفیگ نکن مگر واقعاً انجام شده باشد. برای بسته‌ها فقط حجم درخواستی را پیشنهاد بده؛ دکمه را ربات می‌سازد و دستور دکمه در متن ننویس. فاکتور/رسید کارت و پرداخت موجودی از مسیرهای واقعی ربات انجام می‌شوند. حجم کمتر از ۱ گیگ را به مگابایت نمایش بده.

{shop_text}
{price_text}
{packages_text}
{test_text}
{support_text}"""
    return prompt


try:
    GEMINI_SYSTEM_PROMPT = generate_dynamic_system_prompt()
    logger.info("✅ GEMINI_SYSTEM_PROMPT با اطلاعات داینامیک تولید شد")
except Exception as e:
    logger.error(f"❌ خطا در تولید GEMINI_SYSTEM_PROMPT داینامیک: {e}")

    GEMINI_SYSTEM_PROMPT = (
        "دستیار فروش و پشتیبانی VPN هستی؛ فارسی طبیعی، خلاق و موجز پاسخ بده. "
        "فقط از اطلاعات context استفاده کن، snapshot را فقط خواندنی و متعلق به همان کاربر بدان، "
        "اطلاعات محرمانه را افشا نکن و پرداخت یا تحویل انجام‌نشده را ادعا نکن. "
        "دکمه‌ها را ربات می‌سازد؛ متن دستور دکمه را ننویس. "
        "حجم کمتر از ۱ گیگ را به مگابایت نمایش بده."
    )


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


# ✅Configuration complete! Enjoy your bot.


# =============== AUTO AI RESPONSE ===============
AUTO_AI_RESPONSE = True

"""
routers/ai_purchase_advisor.py
------------------------------
مشاور هوشمند خرید پکیج و سرویس با استفاده از هوش مصنوعی (AI Purchase Advisor)
"""

import os
import re
import json
import time
import html
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple, Union

from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.enums import ParseMode

from db_storage import DATA_DIR, DB_FILES, save_json
from database import (
    users,
    orders,
    configs_pool,
    save_all,
    now_tehran_iso,
    READY_PACKAGES,
    TEST_SERVICE_STATUS,
    USER_TEST_USAGE,
)
from user_manager import user_states, get_user, get_admin_id_int
from routers.admin_packages import format_package_volume
from routers.admin_test import get_user_test_settings
from services.ai_service import (
    get_gemini_client,
    AI_FEATURE_ENABLED,
)
from strings import t

logger = logging.getLogger(__name__)

router = Router(name="ai_purchase_advisor")

ADMIN_ID_INT = get_admin_id_int()

_bot: Optional[Bot] = None


def set_bot(b: Bot):
    global _bot
    _bot = b


def get_bot() -> Optional[Bot]:
    global _bot
    if _bot is not None:
        return _bot
    try:
        import main
        return getattr(main, "bot", None)
    except Exception:
        return None


class _GeminiClientProxy:
    def __getattr__(self, name):
        c = get_gemini_client()
        if c is not None:
            return getattr(c, name)
        raise RuntimeError("Gemini client not initialized")

    def __bool__(self):
        return get_gemini_client() is not None


gemini_client = _GeminiClientProxy()


def to_persian_digits(num):
    import main
    if hasattr(main, "to_persian_digits"):
        return main.to_persian_digits(num)
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    return "".join(fa_digits[int(c)] if c.isdigit() else c for c in str(num))


def get_user_support_configs(user_id: int) -> list:
    import main
    if hasattr(main, "get_user_support_configs"):
        return main.get_user_support_configs(user_id)
    return []


def build_ai_reply_keyboard(*args, **kwargs):
    from routers.ai_assistant import build_ai_reply_keyboard as bark
    return bark(*args, **kwargs)


async def get_ai_response(*args, **kwargs):
    from routers.ai_assistant import get_ai_response as gar
    return await gar(*args, **kwargs)


# ✅ لیست کلمات نامناسب فارسی و انگلیسی
BAD_WORDS_FA = [
    'کیر', 'کیرم', 'کیری', 'کس', 'کسم', 'کونی', 'کون', 'کونم',
    'مادرجنده', 'مادرقحبه', 'مادرکصه', 'جنده', 'قحبه', 'کص', 'کصم',
    'کصکش', 'کصخل', 'خارکصه', 'خواهرجنده', 'خواهرقحبه',
    'گوه', 'گه', 'گوه خور', 'گه خور',
    'دیوث', 'دیوس', 'بیشرف', 'بی شرف', 'حرومزاده', 'حرامزاده',
    'کسکش', 'کس کش', 'کیرم تو', 'کیر تو', 'زنا زاده', 'زنازاده',
    'بی پدر', 'بی مادر', 'پدرسگ', 'پدر سگ', 'مادرسگ', 'مادر سگ',
]

BAD_WORDS_EN = [
    'fuck', 'fucking', 'fucker', 'fucked', 'fuckyou', 'fuck you',
    'shit', 'shitty', 'bullshit', 'bull shit',
    'bitch', 'bitches', 'bitching', 'asshole', 'ass hole',
    'bastard', 'bastards', 'damn it', 'damnit', 'dammit',
    'motherfucker', 'mother fucker', 'motherfucking',
    'cunt', 'cunts', 'dick', 'dicks', 'dickhead',
    'pussy', 'pussies', 'whore', 'whores', 'slut', 'sluts',
    'retard', 'retards', 'retarded', 'nigger', 'nigga',
    'faggot', 'fag', 'fags', 'cock', 'cocks', 'douche', 'douchebag',
    'wanker', 'wankers', 'bollocks', 'bollock', 'arsehole',
    'twat', 'twats',
]

def contains_bad_words(text: str) -> tuple:
    if not text:
        return False, None, None

    normalized = (
        text.lower()
        .replace('ي', 'ی')
        .replace('ك', 'ک')
        .replace('\u200c', '')
    )
    words = re.findall(r'[a-z0-9]+|[\u0600-\u06ff]+', normalized)
    for word_list, language in ((BAD_WORDS_FA, 'fa'), (BAD_WORDS_EN, 'en')):
        for bad_word in word_list:
            phrase = bad_word.lower().replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', '')
            phrase_words = re.findall(r'[a-z0-9]+|[\u0600-\u06ff]+', phrase)
            size = len(phrase_words)
            if size and any(words[index:index + size] == phrase_words for index in range(len(words) - size + 1)):
                return True, bad_word.strip(), language

    return False, None, None



def get_ai_button_context(user_id: int, lang: str, message_text: str = "") -> str:
    """Build a per-user allowlist for AI-suggested inline actions."""
    actions = [
        ("CLEAR_MEMORY", t('clear_conversation_memory_775aa0920b', lang)),
        ("HUMAN_SUPPORT", t('contact_human_support_72202cb9aa', lang)),
        ("MY_ACCOUNT", t('my_account_2f25fa7274', lang)),
        ("MY_CONFIGS", t('my_configs_1cf46e8772', lang)),
        ("APPLY_COUPON", t('apply_coupon_ed76264fdb', lang)),
        ("INCREASE_BALANCE", t('add_balance_bd7cde0604', lang)),
        ("INVITE_FRIENDS", t('invite_friends_f9c1940e10', lang)),
        ("CHANGE_LANGUAGE", t('change_language_437c64b652', lang)),
    ]
    user = get_user(user_id)
    if user.get('registration_status') in ('approved', None) or user_id == ADMIN_ID_INT:
        actions.append(("BUY_SERVICE", t('buy_a_service_1a17758c92', lang)))

    test_settings = get_user_test_settings(user_id)
    test_usage = USER_TEST_USAGE.get(str(user_id), {})
    if (
        TEST_SERVICE_STATUS.get('enabled', False)
        and test_usage.get('count', 0) < test_settings.get('max_tests', TEST_SERVICE_STATUS.get('max_tests', 1))
    ):
        try:
            test_volume = float(test_settings.get(
                'volume_mb',
                TEST_SERVICE_STATUS.get('volume_mb', 0),
            )) / 1024
            test_volume_display = format_package_volume(test_volume, lang)
        except (TypeError, ValueError):
            test_volume_display = t('volume_unavailable_15d26778aa', lang)
        test_days = test_settings.get('days', TEST_SERVICE_STATUS.get('days', 0))
        test_label = (
            t('get_test_days_fe5811f82b', lang, fa_parts=lambda: (f'{test_volume_display}', f'{test_days}'), en_parts=lambda: (f'{test_volume_display}', f'{test_days}'))
        )
        actions.append(("GET_TEST_SERVICE", test_label))

    if re.search(r"تمدید|renew|extend", message_text, re.IGNORECASE):
        requested_order = re.search(
            r"(?:سفارش|order|#)\s*#?\s*(\d+)",
            message_text,
            re.IGNORECASE,
        )
        requested_order_id = requested_order.group(1) if requested_order else None
        renewals = []
        for order in get_user_support_configs(user_id):
            order_id = order.get('order_id')
            if requested_order_id and str(order_id) != requested_order_id:
                continue
            if order.get('status') not in ('approved', 'inactive'):
                continue
            is_test = (
                order.get('type') == 'test'
                or order.get('is_test', False)
                or str(order.get('email', '')).startswith('test_')
            )
            if order_id is not None and not is_test:
                renewals.append((
                    f"RENEW_ORDER:{order_id}",
                    t('renew_order_70b83dfb3f', lang, fa_parts=lambda: (f'{order_id}',), en_parts=lambda: (f'{order_id}',)),
                ))
        actions.extend(renewals[:3])

    available = "\n".join(f"- {action}: {label}" for action, label in actions)
    return (
        "\n\nفقط زمانی دکمه پیشنهاد بده که مستقیماً به سوال فعلی کاربر مربوط باشد. "
        "برای سلام و احوال‌پرسی یا سوالات عمومی هرگز دکمهٔ HUMAN_SUPPORT یا انتقال به پشتیبان ننویس و فقط وقتی HUMAN_SUPPORT را پیشنهاد بده که کاربر صریحاً پشتیبان انسانی بخواهد یا مشکلش نیاز به بررسی ادمین داشته باشد. "
        "اگر لازم است لینکی به کاربر معرفی کنی، حتماً آن را با قالب [عنوان کوتاه و خوانا](https://...) بنویس تا ربات آن را به دکمه شیشه‌ای تلگرام تبدیل کند. "
        "برای گزینه‌های بسته، ربات خودش بر اساس پیام کاربر دکمه‌های مناسب را می‌سازد؛ "
        "برای بسته‌ها نشانگر BUTTON ننویس و همهٔ بسته‌ها را پیشنهاد نده مگر کاربر صریحاً فهرست کامل بخواهد. "
        "برای عملیات دیگر فقط از شناسه‌های مجاز زیر استفاده کن و هر دکمه را در خط مستقل و دقیقاً با قالب "
        "[[BUTTON:شناسه|متن دکمه]] در انتهای پاسخ بنویس؛ جداکنندهٔ شناسه و متن فقط | است و بعد از شناسه دونقطه نگذار. "
        "شناسه جدید یا شماره سفارش نساز. "
        "اگر دکمه‌ای لازم نیست، هیچ نشانگر دکمه‌ای ننویس.\n"
        "اطلاعات بعدی فقط snapshot خواندنی دیتابیس کاربر فعلی، تراکنش‌های متعلق به همان کاربر و عملیات مجاز همین ربات است. "
        "هرگز ادعا نکن که دیتابیس را تغییر داده‌ای یا عملیاتی انجام داده‌ای.\n"
        f"شناسه‌ها و عنوان‌های مجاز:\n{available}"
    )


def strip_ai_button_directives(text: str) -> str:
    text = re.sub(
        r"(?m)^[ \t]*\[\[\s*BUTTON\b[^\r\n]*(?:\]\])?[ \t]*(?:\r?\n|$)",
        "",
        text,
    )
    text = re.sub(
        r"\[\[\s*BUTTON\b[^\]\r\n]*(?:\]\]|(?=\r?$))",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"\]\][ \t]*(?=\r?$)", "", text, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_ai_user_text(text: str) -> str:
    return (text or "").translate(str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )).lower()


def strip_repeated_ai_greeting(text: str) -> str:
    text = re.sub(
        r"^\s*(?:سلام|درود)(?:\s+[^،,!؟\n]{1,40})?\s*[,،!؟:؛-]\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^\s*(?:hi|hello|hey)(?:\s+[^,!\n]{1,40})?\s*[,!:.]\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^\s*(?:به [^.!؟\n]{1,80} خوش آمدید|خوش آمدید به [^.!؟\n]{1,80})[.!؟،]?\s*",
        "",
        text,
        count=1,
    )
    text = re.sub(
        r"^\s*welcome to [^.!?\n]{1,80}[.!?]?\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    return text.lstrip()


def parse_ai_volume_gb(text: str) -> Optional[float]:
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(گیگ(?:ابایت)?|gb|gig(?:abytes?)?|مگ(?:ابایت)?|mb)",
        normalize_ai_user_text(text),
        re.IGNORECASE,
    )
    if not match:
        return None
    volume = float(match.group(1).replace(",", "."))
    if match.group(2).startswith(("مگ", "mb")):
        volume /= 1024
    return volume


def parse_ai_budget(text: str) -> Optional[int]:
    normalized = normalize_ai_user_text(text).replace(",", "").replace("٬", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(میلیون|مليون|هزار|تومن|تومان)?", normalized)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    if unit in ("میلیون", "مليون"):
        amount *= 1_000_000
    elif unit == "هزار":
        amount *= 1_000
    return int(amount)


def get_active_ai_packages() -> list:
    active_packages = []
    if not READY_PACKAGES.get('enabled', True):
        return active_packages
    for category in READY_PACKAGES.get('categories', []):
        if not category.get('is_active', True):
            continue
        for package in category.get('packages', []):
            if package.get('is_active', True):
                active_packages.append((category, package))
    return active_packages


AI_PURCHASE_ADVISOR_COOLDOWN = timedelta(hours=24)


def get_ai_purchase_advisor_answers_text(answers: list) -> str:
    return "\n".join(
        f"{item.get('question', '')}: {item.get('answer', '')}"
        for item in answers
        if isinstance(item, dict)
    )


def get_ai_purchase_advisor_user_answers_text(answers: list) -> str:
    return "\n".join(
        str(item.get('answer', ''))
        for item in answers
        if isinstance(item, dict)
    )


def get_ai_purchase_advisor_package_search_text(category: dict, package: dict) -> str:
    return normalize_ai_user_text(" ".join(str(value or "") for value in (
        category.get('name'),
        category.get('name_en'),
        category.get('description'),
        category.get('description_en'),
        package.get('name'),
        package.get('name_fa'),
        package.get('name_en'),
        package.get('description'),
        package.get('description_en'),
    )))


def is_ai_purchase_advisor_high_stability_package(
    category: dict,
    package: dict,
) -> bool:
    package_text = get_ai_purchase_advisor_package_search_text(category, package)
    # 1. صریحاً پایداری بالا یا تانل یا کیفیت و پایداری بالاتر
    high_stability_patterns = [
        r"تانل|تونل|tunnel",
        r"پایدار(?:ی)?\s*(?:بالا(?:تر)?|عالی|حداکثر|بیشتر|فوق[\s‌]*العاده|تضمینی)",
        r"کیفیت\s*و\s*پایدار(?:ی)?",
        r"بدون\s*قطعی|اتصال\s*مطمئن|ثبات\s*بالا|ضد\s*قطعی",
        r"high(?:er)?\s*stability",
        r"quality\s*and\s*stability",
        r"ultra\s*stable|very\s*stable|rock\s*solid",
        r"high(?:ly)?\s*reliab\w*|high\s*availability|uninterrupted",
        r"dedicated\s*tunnel",
    ]
    if any(re.search(pat, package_text, re.IGNORECASE) for pat in high_stability_patterns):
        return True

    # 2. اگر صریحاً پایداری معمولی ذکر شده باشد
    if re.search(
        r"پایدار(?:ی)?\s*(?:معمولی|عادی|متوسط)|(?:normal|regular|moderate|standard)\s*(?:speed\s*and\s*)?stability",
        package_text,
        re.IGNORECASE,
    ):
        return False

    # 3. سایر عبارات عمومی پایداری
    return bool(re.search(r"بدون\s*قطعی|اتصال\s*مطمئن|high.?availability|uptime", package_text, re.IGNORECASE))


def is_ai_purchase_advisor_gaming_package(
    category: dict,
    package: dict,
) -> bool:
    package_text = get_ai_purchase_advisor_package_search_text(category, package)
    return bool(re.search(
        r"گیم(?:ینگ)?|بازی|gaming|games?",
        package_text,
    )) or is_ai_purchase_advisor_wireguard_package(category, package)


def is_ai_purchase_advisor_wireguard_package(
    category: dict,
    package: dict,
) -> bool:
    package_text = get_ai_purchase_advisor_package_search_text(category, package)
    return bool(re.search(
        r"wire\s*guard|وایر\s*گارد|(?<![a-z])wg(?![a-z])",
        package_text,
    ))


def get_ai_purchase_advisor_intent_terms(text: str) -> set[str]:
    normalized = normalize_ai_user_text(text).translate(str.maketrans({
        "ك": "ک",
        "ي": "ی",
        "ى": "ی",
        "\u200c": " ",
    }))
    terms = set(re.findall(r"[a-z0-9\u0600-\u06ff]+", normalized))
    stop_words = {
        "and", "for", "the", "with", "want", "need", "internet", "package",
        "service", "please", "just", "من", "میخوام", "میخواهم", "میخوامش",
        "میخواهمش", "یه", "یک", "برای", "از", "به", "با",
        "و", "در", "رو", "را", "که", "این", "اون", "هم", "لطفا", "لطفاً",
        "پکیج", "بسته", "سرویس", "کانفیگ", "اینترنت",
    }
    terms.difference_update(stop_words)
    if re.search(r"ترید|تریدر|معامل(?:ه|ات)|trade|trader|trading|forex", normalized):
        terms.update({
            "ترید", "تریدر", "معامله", "معاملات",
            "trade", "trader", "trading", "forex",
        })
    return terms


def ai_purchase_advisor_intent_matches_package(
    intent_text: str,
    category: dict,
    package: dict,
) -> bool:
    if (
        re.search(r"گیم(?:ینگ)?|بازی|gaming|games?", normalize_ai_user_text(intent_text))
        and is_ai_purchase_advisor_gaming_package(category, package)
    ):
        return True

    intent_terms = get_ai_purchase_advisor_intent_terms(intent_text)
    package_terms = get_ai_purchase_advisor_intent_terms(
        get_ai_purchase_advisor_package_search_text(category, package)
    )
    return any(
        intent_term == package_term
        or (
            min(len(intent_term), len(package_term)) >= 4
            and (
                intent_term.startswith(package_term)
                or package_term.startswith(intent_term)
            )
        )
        for intent_term in intent_terms
        for package_term in package_terms
    )


def get_ai_purchase_advisor_cooldown_remaining(user_id: int) -> Optional[timedelta]:
    last_started = get_user(user_id).get('ai_purchase_advisor_last_started_at')
    if not last_started:
        return None
    try:
        last_started_at = datetime.fromisoformat(str(last_started))
        if last_started_at.tzinfo is None:
            last_started_at = last_started_at.astimezone()
        now = datetime.now().astimezone()
    except (TypeError, ValueError, OverflowError):
        logger.warning(
            "Invalid smart-purchase timestamp for user %s; enforcing cooldown",
            user_id,
        )
        return AI_PURCHASE_ADVISOR_COOLDOWN
    remaining = AI_PURCHASE_ADVISOR_COOLDOWN - (now - last_started_at)
    return remaining if remaining.total_seconds() > 0 else None


def build_ai_purchase_advisor_question(
    question_number: int,
    answers: list,
    lang: str,
) -> tuple[str, list]:
    if question_number == 1:
        if lang == "fa":
            return t('advisor_q1_question', lang), [(t('advisor_q1_choice_1_label', lang), t('advisor_q1_choice_1_answer', lang)), (t('advisor_q1_choice_2_label', lang), t('advisor_q1_choice_2_answer', lang)), (t('advisor_q1_choice_3_label', lang), t('advisor_q1_choice_3_answer', lang)), (t('advisor_q1_choice_4_label', lang), t('advisor_q1_choice_4_answer', lang))]
        return t('advisor_q1_question', lang), [(t('advisor_q1_choice_1_label', lang), t('advisor_q1_choice_1_answer', lang)), (t('advisor_q1_choice_2_label', lang), t('advisor_q1_choice_2_answer', lang)), (t('advisor_q1_choice_3_label', lang), t('advisor_q1_choice_3_answer', lang)), (t('advisor_q1_choice_4_label', lang), t('advisor_q1_choice_4_answer', lang))]

    if question_number == 2:
        if lang == "fa":
            return t('advisor_q2_question', lang), [(t('advisor_q2_choice_1_label', lang), t('advisor_q2_choice_1_answer', lang)), (t('advisor_q2_choice_2_label', lang), t('advisor_q2_choice_2_answer', lang)), (t('advisor_q2_choice_3_label', lang), t('advisor_q2_choice_3_answer', lang)), (t('advisor_q2_choice_4_label', lang), t('advisor_q2_choice_4_answer', lang))]
        return t('advisor_q2_question', lang), [(t('advisor_q2_choice_1_label', lang), t('advisor_q2_choice_1_answer', lang)), (t('advisor_q2_choice_2_label', lang), t('advisor_q2_choice_2_answer', lang)), (t('advisor_q2_choice_3_label', lang), t('advisor_q2_choice_3_answer', lang)), (t('advisor_q2_choice_4_label', lang), t('advisor_q2_choice_4_answer', lang))]

    if lang == "fa":
        return t('advisor_q3_question', lang), [(t('advisor_q3_choice_1_label', lang), t('advisor_q3_choice_1_answer', lang)), (t('advisor_q3_choice_2_label', lang), t('advisor_q3_choice_2_answer', lang))]
    return t('advisor_q3_question', lang), [(t('advisor_q3_choice_1_label', lang), t('advisor_q3_choice_1_answer', lang)), (t('advisor_q3_choice_2_label', lang), t('advisor_q3_choice_2_answer', lang))]


def get_ai_purchase_advisor_package_map(lang: str) -> dict:
    package_map = {}
    for category, package in get_active_ai_packages():
        category_id = category.get('id')
        package_id = package.get('id')
        if not str(category_id).isdigit() or not str(package_id).isdigit():
            continue
        key = f"{category_id}:{package_id}"
        package_map[key] = (category, package)
    return package_map


def build_ai_purchase_advisor_catalog(lang: str) -> list:
    catalog = []
    for key, (category, package) in get_ai_purchase_advisor_package_map(lang).items():
        category_name = (
            category.get('name') or category.get('name_en') or ''
            if lang == "fa"
            else category.get('name_en') or category.get('name') or ''
        )
        category_description = (
            category.get('description') or category.get('description_en') or ''
            if lang == "fa"
            else category.get('description_en') or category.get('description') or ''
        )
        package_name = (
            package.get('name_fa') or package.get('name') or ''
            if lang == "fa"
            else package.get('name_en') or package.get('name') or ''
        )
        package_description = (
            package.get('description') or package.get('description_en') or ''
            if lang == "fa"
            else package.get('description_en') or package.get('description') or ''
        )
        catalog.append({
            "id": key,
            "category": str(category_name)[:120],
            "category_description": str(category_description),
            "package": str(package_name)[:120],
            "package_description": str(package_description),
            "volume_gb": package.get('volume', 0),
            "days": package.get('days', 30),
            "price_toman": int(package.get('price', 0) or 0),
            "ip_limit": package.get('ip_limit'),
        })
    return catalog


def get_ai_purchase_advisor_eligible_packages(answers: list, lang: str) -> dict:
    package_map = get_ai_purchase_advisor_package_map(lang)
    answer_text = get_ai_purchase_advisor_user_answers_text(answers)
    normalized = normalize_ai_user_text(answer_text)
    volume_target = parse_ai_volume_gb(answer_text)
    wants_unlimited = bool(re.search(r"نامحدود|unlimited", normalized))
    accepts_closest_volume = bool(re.search(
        r"نزدیک(?:ترین)?|حجم دیگر|حجم متفاوت|هر حجمی|حجم مهم نیست|فرقی در حجم|"
        r"nearest|closest|any volume|different volume",
        normalized,
    ))
    duration_match = re.search(r"(\d+)\s*(?:روز|day|days)", normalized)
    duration_target = int(duration_match.group(1)) if duration_match else None

    eligible = {}
    for key, (category, package) in package_map.items():
        volume = float(package.get('volume', 0) or 0)
        days = int(package.get('days', 30) or 30)
        if wants_unlimited and volume != 0:
            continue
        if volume_target is not None:
            if volume_target == 0 and not wants_unlimited:
                continue
            if volume_target > 0 and (
                volume == 0
                or (volume < volume_target and not accepts_closest_volume)
            ):
                continue
        if duration_target is not None and days < duration_target:
            continue
        eligible[key] = (category, package)

    purpose_answer = (
        str(answers[0].get('answer', ''))
        if answers and isinstance(answers[0], dict)
        else ""
    )
    if purpose_answer.strip():
        matching_intent = {
            key: item for key, item in eligible.items()
            if ai_purchase_advisor_intent_matches_package(
                purpose_answer,
                *item,
            )
        }
        if matching_intent:
            eligible = matching_intent

    return eligible


def is_tunnel_package(category: dict, package: dict) -> bool:
    """تشخیص سرویس تانل / پایداری بالاتر از روی نام یا صفت‌های برتر در توضیحات"""
    text = get_ai_purchase_advisor_package_search_text(category, package)
    return bool(re.search(
        r"تانل|تونل|tunnel|پایدار(?:ی)?\s*(?:بالا(?:تر)?|عالی|بیشتر)|کیفیت\s*و\s*پایدار|کیفیت\s*بالا(?:تر)?|تونل\s*اختصاصی|higher\s*stability|dedicated\s*tunnel",
        text,
        re.IGNORECASE,
    ))


def is_direct_package(category: dict, package: dict) -> bool:
    """تشخیص سرویس مستقیم / پایداری معمولی از روی نام یا توضیحات"""
    text = get_ai_purchase_advisor_package_search_text(category, package)
    if is_tunnel_package(category, package):
        return False
    return bool(re.search(
        r"مستقیم|direct|پایدار(?:ی)?\s*(?:معمولی|عادی)|استفاده\s*روزمره|وارپ|warp|normal\s*stability",
        text,
        re.IGNORECASE,
    ))


def choose_ai_recommended_package(
    user_id: int,
    answers: list,
    selected_package_id: Optional[str] = None,
    priority: str = "economy",
    lang: str = "fa",
):
    """انتخاب هوشمندانه بسته بر اساس پیشنهاد هوش مصنوعی یا منطق پشتیبان لوکال."""
    eligible = get_ai_purchase_advisor_eligible_packages(answers, lang)
    package_map = get_ai_purchase_advisor_package_map(lang)
    if not eligible:
        eligible = package_map
    if not eligible:
        return None

    answer_text = normalize_ai_user_text(
        get_ai_purchase_advisor_user_answers_text(answers)
    )
    budget_match = re.search(
        r"(?:بودجه|حداکثر|زیر|کمتر از|تا|budget|under|less than)"
        r"\D{0,16}(\d+(?:[.,]\d+)?)\s*(میلیون|مليون|هزار|تومان|تومن|toman|million|thousand)?",
        answer_text,
        re.IGNORECASE,
    )
    budget = None
    if budget_match:
        budget_text = " ".join(
            part for part in budget_match.groups() if part
        )
        budget = parse_ai_budget(budget_text)
    if budget is None:
        currency_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(میلیون|مليون|هزار|تومان|تومن|toman|million|thousand)",
            answer_text,
            re.IGNORECASE,
        )
        if currency_match:
            budget = parse_ai_budget(" ".join(currency_match.groups()))

    # ─── ۱. اولویت نخست: اعمال پیشنهاد مستقیم هوش مصنوعی ───
    if selected_package_id:
        selected_key = str(selected_package_id).strip()
        if selected_key in eligible:
            logger.info('🤖 AI suggestion approved and applied: %s', selected_key)
            return eligible[selected_key]
        if selected_key in package_map:
            cat, pkg = package_map[selected_key]
            pkg_price = int(pkg.get('price', 0) or 0)
            if budget is None or pkg_price <= budget:
                logger.info('🤖 AI suggestion from the active catalog approved: %s', selected_key)
                return cat, pkg

    # ─── ۲. منطق پشتیبان لوکال (در صورتی که هوش مصنوعی در دسترس نبود) ───
    is_sensitive_trade = bool(re.search(
        r"ترید|تریدر|معامله|صرافی|ارز دیجیتال|فارکس|کریپتو|trade|trader|trading|crypto|forex|binance",
        answer_text,
        re.IGNORECASE,
    ))
    requests_high_stability = bool(re.search(
        r"پایداری بالا|پایدار(?:ی)?\s*بالا(?:تر)?|اتصال مطمئن|بدون قطعی|"
        r"high stability|very stable|reliable|high reliability|uptime",
        answer_text,
        re.IGNORECASE,
    ))
    requests_normal_stability = bool(re.search(
        r"معمولی|عادی|پایداری معمولی|روزمره|regular|normal",
        answer_text,
        re.IGNORECASE,
    ))
    requests_gaming = bool(re.search(
        r"گیم(?:ینگ)?|بازی|gaming|games?",
        answer_text,
        re.IGNORECASE,
    ))

    # اگر کاربر ترید یا پایداری بالا خواسته بود -> حتماً تانل (پایداری بالاتر)
    if is_sensitive_trade or requests_high_stability:
        tunnel_packages = {
            key: item for key, item in eligible.items()
            if is_tunnel_package(*item)
        }
        if tunnel_packages:
            eligible = tunnel_packages

    # اگر بازی بود و وایرگارد موجود بود
    elif requests_gaming:
        gaming_wireguard = {
            key: item for key, item in eligible.items()
            if is_ai_purchase_advisor_wireguard_package(*item)
        }
        if gaming_wireguard:
            eligible = gaming_wireguard

    # اگر پایداری معمولی خواسته بود (و ترید هم نبود) -> مستقیم
    elif requests_normal_stability:
        direct_packages = {
            key: item for key, item in eligible.items()
            if is_direct_package(*item)
        }
        if direct_packages:
            eligible = direct_packages

    # اعمال فیلتر بودجه در صورت وجود
    if budget is not None:
        within_budget = {
            key: item for key, item in eligible.items()
            if int(item[1].get('price', 0) or 0) <= budget
        }
        if within_budget:
            eligible = within_budget

    return min(
        eligible.values(),
        key=lambda item: (
            int(item[1].get('price', 0) or 0),
            -int(item[1].get('days', 30) or 30),
        ),
    )


def clean_ai_purchase_advisor_reason(text: Any, max_chars: int = 250) -> str:
    """پاکسازی و اطمینان از کامل بودن جمله دلیل بدون قطع شدن وسط کلمه یا کلام"""
    raw = str(text or "").replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", raw).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        cleaned = re.sub(r"\s+(با|به|از|در|برای|که|و|with|to|for|and|in)\s*$", "", cleaned).strip()
        if cleaned and cleaned[-1] not in ".!?؛؟":
            cleaned += "."
        return cleaned

    trimmed = cleaned[:max_chars]
    for punct in ('.', '!', '؟', ';', '؛'):
        pos = trimmed.rfind(punct)
        if pos >= 50:
            return trimmed[:pos + 1].strip()
    last_space = trimmed.rfind(' ')
    if last_space >= 50:
        trimmed = trimmed[:last_space].strip()
        trimmed = re.sub(r"\s+(با|به|از|در|برای|که|و|with|to|for|and|in)\s*$", "", trimmed).strip()
        return trimmed + "."
    return trimmed


def build_ai_purchase_advisor_fallback_reason(
    answers: list,
    category: dict,
    package: dict,
    lang: str,
) -> str:
    purpose_answer = (
        str(answers[0].get('answer', ''))
        if answers and isinstance(answers[0], dict)
        else ""
    )
    answer_text = normalize_ai_user_text(
        get_ai_purchase_advisor_user_answers_text(answers)
    )
    if re.search(r"ترید|تریدر|معامله|صرافی|ارز دیجیتال|فارکس|trade|crypto", answer_text):
        return (
            t('for_trading_and_finance_high_782a44025d', lang)
        )
    if (
        re.search(r"گیم(?:ینگ)?|بازی|gaming|games?", normalize_ai_user_text(purpose_answer))
        and is_ai_purchase_advisor_wireguard_package(category, package)
    ):
        return (
            t('you_said_gaming_and_this_pac_ef175197cd', lang)
        )
    if is_tunnel_package(category, package):
        return (
            t('you_prioritized_stability_an_23b85814a1', lang)
        )
    if is_direct_package(category, package):
        return (
            t('selected_for_daily_use_with_3acd2399c9', lang)
        )
    return (
        t('this_option_best_fits_your_r_cac4d515f8', lang)
    )


def parse_ai_purchase_advisor_response(response: str) -> Optional[dict]:
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if not match:
        payload = None
    else:
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict) and payload.get("action") in ("ask", "recommend"):
        return payload

    # Recover the decision fields when only a trailing explanation was truncated.
    action_match = re.search(
        r'"action"\s*:\s*"(ask|recommend)"',
        response,
    )
    if not action_match:
        return None
    recovered = {"action": action_match.group(1)}
    for field, pattern in (
        ("selected_package_id", r'"selected_package_id"\s*:\s*"(\d+:\d+)"'),
        ("priority", r'"priority"\s*:\s*"(economy|quality|reliability)"'),
    ):
        field_match = re.search(pattern, response)
        if field_match:
            recovered[field] = field_match.group(1)
    if recovered["action"] == "recommend":
        return recovered
    return None


def build_ai_purchase_advisor_request(
    user_id: int,
    lang: str,
    advisor: dict,
) -> tuple[str, str]:
    answers = advisor.get('answers', [])
    eligible = get_ai_purchase_advisor_eligible_packages(answers, lang)
    catalog = build_ai_purchase_advisor_catalog(lang)
    eligible_ids = set(eligible)
    clarification_count = int(advisor.get('ai_clarification_count', 0))

    # دیتای تمیز، دقیق و بدون شلوغی برای هوش مصنوعی
    request_data = {
        "user_answers": [
            {"question": str(item.get("question", "")), "answer": str(item.get("answer", ""))}
            for item in answers if isinstance(item, dict)
        ],
        "available_packages": [
            {
                "id": p["id"],
                "category_name": p["category"],
                "category_description": p["category_description"],
                "package_name": p["package"],
                "package_description": p["package_description"],
                "volume_gb": p["volume_gb"],
                "days": p["days"],
                "price_toman": p["price_toman"],
            }
            for p in catalog
            if not eligible_ids or p["id"] in eligible_ids
        ],
        "can_ask_question": clarification_count < 2,
    }

    system_instruction = t('you_are_velorabot_s_ai_vpn_a_c6da2d63b3', lang)

    prompt = (
        "پاسخ‌های کاربر و بسته‌ها را بررسی کن و خروجی JSON بده:\n"
        + json.dumps(request_data, ensure_ascii=False)
    )
    return system_instruction, prompt


def save_ai_purchase_advisor_result(
    user_id: int,
    advisor: dict,
    category: dict,
    package: dict,
    reason: str,
) -> bool:
    user = get_user(user_id)
    history = user.get('ai_purchase_advisor_history', [])
    if not isinstance(history, list):
        history = []
    result = {
        "category_id": category.get('id'),
        "package_id": package.get('id'),
        "answers": advisor.get('answers', []),
        "reason": reason,
        "question_count": advisor.get('question_count', 0),
        "created_at": now_tehran_iso(),
    }
    history.append(result)
    user['ai_purchase_advisor_history'] = history[-5:]
    user['ai_purchase_advisor_result'] = result
    saved = save_json(DB_FILES['users'], users)
    if not saved:
        logger.error('❌ Smart choice for user %s was not saved', user_id)
    return saved


def get_ai_purchase_advisor_result(user_id: int) -> Optional[dict]:
    result = get_user(user_id).get('ai_purchase_advisor_result')
    if not isinstance(result, dict):
        return None
    package_key = f"{result.get('category_id')}:{result.get('package_id')}"
    if package_key not in get_ai_purchase_advisor_package_map(
        get_user(user_id).get('lang', 'fa')
    ):
        return None
    return result


def restore_ai_purchase_advisor_state(
    user_id: int,
    result: Optional[dict] = None,
) -> Optional[dict]:
    result = result or get_ai_purchase_advisor_result(user_id)
    if not isinstance(result, dict):
        return None

    state = user_states.setdefault(user_id, {})
    advisor = state.get('purchase_advisor')
    if not isinstance(advisor, dict) or advisor.get('status') not in (
        'recommended',
        'invoice_processing',
    ):
        advisor = {
            "status": "recommended",
            "category_id": result.get('category_id'),
            "package_id": result.get('package_id'),
            "answers": result.get('answers', []),
            "reason": result.get('reason', ''),
            "question_count": result.get('question_count', 0),
        }
        state['purchase_advisor'] = advisor

    if (
        str(advisor.get('category_id')) != str(result.get('category_id'))
        or str(advisor.get('package_id')) != str(result.get('package_id'))
    ):
        return None
    invoice_order_id = result.get('invoice_order_id')
    if invoice_order_id:
        state['purchase_advisor_invoice_order_id'] = invoice_order_id
    user_states[user_id] = state
    return advisor


def build_ai_purchase_advisor_result_text(
    user_id: int,
    lang: str,
    result: dict,
    saved_result: bool = False,
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    state = user_states.setdefault(user_id, {})
    category_id = result.get('category_id')
    package_id = result.get('package_id')
    state['purchase_advisor'] = {
        "status": "recommended",
        "category_id": category_id,
        "package_id": package_id,
        "answers": result.get('answers', []),
        "reason": result.get('reason', ''),
        "question_count": result.get('question_count', 0),
    }
    invoice_order_id = result.get('invoice_order_id')
    if invoice_order_id:
        state['purchase_advisor_invoice_order_id'] = invoice_order_id
    else:
        state.pop('purchase_advisor_invoice_order_id', None)
    state['ai_chat_mode'] = True
    user_states[user_id] = state

    category, package = get_ai_purchase_advisor_package_map(lang)[
        f"{category_id}:{package_id}"
    ]
    category_name = category.get('name') if lang == "fa" else category.get(
        'name_en', category.get('name')
    )
    package_name = (
        package.get('name_fa') or package.get('name') or category_name
        if lang == "fa"
        else package.get('name_en') or package.get('name') or category_name
    )
    package_name_core = re.sub(
        r"\d+(?:[.,]\d+)?\s*(?:gb|gib|گیگ(?:ابایت)?|روز|days?)",
        " ",
        str(package_name or ""),
        flags=re.IGNORECASE,
    )
    package_name_core = re.sub(r"[\s/|·-]+", " ", package_name_core).strip()
    recommendation_name = str(category_name or package_name_core or (t('package_8cf9cfc447', lang)))
    if (
        category_name
        and package_name_core
        and normalize_ai_user_text(str(category_name).strip())
        != normalize_ai_user_text(package_name_core)
    ):
        recommendation_name = f"{category_name} / {package_name_core}"
    recommendation_name = html.escape(re.sub(r"\s+", " ", recommendation_name).strip()[:40])
    reason_value = clean_ai_purchase_advisor_reason(result.get('reason'), max_chars=250)
    legacy_reasons = {
        "این پیشنهاد بر اساس پاسخ‌های تو و بسته‌های فعال انتخاب شده است.",
        "این بسته بر اساس پاسخ‌ها و قیمت گزینه‌های فعال انتخاب شد.",
        "This recommendation was selected from your answers and active packages.",
        "This package was selected based on your answers and active package prices.",
    }
    # بررسی ناقص بودن یا قطع شدن جمله ناشی از باگ‌های قبلی
    is_dangling = any(
        reason_value.rstrip('. ').endswith(f" {w}")
        for w in ('با', 'به', 'در', 'از', 'برای', 'که', 'و', 'with', 'to', 'for', 'and', 'in')
    )
    if not reason_value or reason_value in legacy_reasons or is_dangling:
        reason_value = build_ai_purchase_advisor_fallback_reason(
            result.get('answers', []), category, package, lang
        )
    reason = html.escape(clean_ai_purchase_advisor_reason(reason_value, max_chars=250))
    volume = format_package_volume(package.get('volume', 0), lang)
    days = package.get('days', 30)
    price = int(package.get('price', 0) or 0)
    title = t('saved_recommendation_77f64b0456', lang) if saved_result else t('your_recommendation_7f43b658b6', lang)
    if invoice_order_id:
        response = (
            t('days_toman_invoice_is_ready_6bd2bf8e63', lang, fa_parts=lambda: (f'{title}', f'{recommendation_name}', f'{volume}', f'{to_persian_digits(days)}', f'{price:,}', f'{reason}', f'{to_persian_digits(invoice_order_id)}'), en_parts=lambda: (f'{title}', f'{recommendation_name}', f'{volume}', f'{days}', f'{price:,}', f'{reason}', f'{invoice_order_id}'))
        )
    else:
        response = (
            t('days_toman_tap_invoice_to_pu_cdca1cb789', lang, fa_parts=lambda: (f'{title}', f'{recommendation_name}', f'{volume}', f'{to_persian_digits(days)}', f'{price:,}', f'{reason}'), en_parts=lambda: (f'{title}', f'{recommendation_name}', f'{volume}', f'{days}', f'{price:,}', f'{reason}'))
        )
    return build_ai_reply_keyboard(
        response,
        user_id,
        lang,
        include_chat_controls=True,
    )


async def send_ai_purchase_advisor_question(
    message: Message,
    user_id: int,
    lang: str,
    question_number: int,
    question_kind: Optional[str] = None,
    question_override: Optional[str] = None,
    choices_override: Optional[list] = None,
    edit_message: Optional[Message] = None,
) -> None:
    state = user_states.get(user_id, {})
    advisor = state.get('purchase_advisor', {})
    if question_override is None:
        question, choices = build_ai_purchase_advisor_question(
            question_number,
            advisor.get('answers', []),
            lang,
        )
    else:
        question = question_override.strip()[:240]
        choices = choices_override or []
    options = {}
    buttons = []
    for item in choices:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            label, answer = item
        elif isinstance(item, dict):
            label = item.get('label', '')
            answer = item.get('answer', label)
        else:
            continue
        index = str(len(options))
        options[index] = str(answer)
        buttons.append(InlineKeyboardButton(
            text=str(label)[:32],
            callback_data=f"ai_advisor_answer_{question_number}_{index}",
            style="primary",
        ))
    advisor.update({
        "status": "questions",
        "question_count": question_number,
        "question": question,
        "question_kind": question_kind or (
            "purpose" if question_number == 1
            else "volume" if question_number == 2
            else "stability"
        ),
        "options": options,
    })
    user_states[user_id] = state
    title = (
        t('question_b67604189a', lang, fa_parts=lambda: (f'{to_persian_digits(question_number)}',), en_parts=lambda: (f'{question_number}',))
    )
    question_text = (
        t('or_type_your_own_answer_ebfe22ae4b', lang, fa_parts=lambda: (f'{title}', f'{question}'), en_parts=lambda: (f'{title}', f'{question}'))
    )
    question_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                buttons[index:index + 2]
                for index in range(0, len(buttons), 2)
            ]
        ) if buttons else None
    if edit_message:
        await edit_message.edit_text(
            question_text,
            reply_markup=question_markup,
        )
    else:
        await message.reply(question_text, reply_markup=question_markup)


async def run_ai_purchase_advisor_turn(
    message: Message,
    user_id: int,
    lang: str,
) -> None:
    state = user_states.get(user_id, {})
    advisor = state.get('purchase_advisor', {})
    advisor['status'] = 'processing'
    user_states[user_id] = state
    processing = await message.reply(
        t('reviewing_your_answers_and_t_1eab3d19d0', lang)
    )
    parsed = None
    if gemini_client:
        system_instruction, prompt = build_ai_purchase_advisor_request(
            user_id, lang, advisor
        )
        response = await get_ai_response(
            prompt,
            system_instruction_override=system_instruction,
            response_mime_type="application/json",
            max_output_tokens=512,
        )
        parsed = parse_ai_purchase_advisor_response(response)
    MAX_AI_CLARIFICATIONS = 2
    clarification_count = int(advisor.get('ai_clarification_count', 0))
    if (
        parsed
        and parsed.get('action') == "ask"
        and clarification_count < MAX_AI_CLARIFICATIONS
    ):
        question = parsed.get('question')
        choices = parsed.get('choices', [])
        if isinstance(question, str) and question.strip() and isinstance(choices, list):
            valid_choices = []
            for choice in choices[:4]:
                if isinstance(choice, dict):
                    label = str(choice.get('label') or '').strip()[:32]
                    answer = str(choice.get('answer') or label).strip()[:120]
                    if label and answer:
                        valid_choices.append((label, answer))
                elif isinstance(choice, (list, tuple)) and len(choice) == 2:
                    label = str(choice[0]).strip()[:32]
                    answer = str(choice[1]).strip()[:120]
                    if label and answer:
                        valid_choices.append((label, answer))
            if valid_choices:
                advisor['ai_clarification_count'] = clarification_count + 1
                await send_ai_purchase_advisor_question(
                    message,
                    user_id,
                    lang,
                    int(advisor.get('question_count', 0)) + 1,
                    question_kind="ai_clarification",
                    question_override=question,
                    choices_override=valid_choices,
                    edit_message=processing,
                )
                return
    if parsed is None or parsed.get('action') != "recommend":
        logger.warning(
            "⚠️ Gemini did not return a usable purchase-advisor recommendation for user %s; "
            "using the local package selector",
            user_id,
        )
        parsed = {"action": "recommend", "priority": "economy"}

    action = parsed.get('action')
    selected_package_id = str(parsed.get('selected_package_id') or "")
    priority = str(parsed.get('priority') or "economy").lower()
    recommendation = choose_ai_recommended_package(
        user_id,
        advisor.get('answers', []),
        selected_package_id,
        priority,
        lang,
    )
    if not recommendation:
        advisor['status'] = 'retry'
        user_states[user_id] = state
        await processing.edit_text(
            t('no_active_package_matches_yo_f54cf9cd1b', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=t('retry_5550d5f4fa', lang),
                    callback_data="ai_advisor_retry",
                    style="primary",
                )
            ]]),
        )
        return

    category, package = recommendation
    final_package_id = f"{category.get('id')}:{package.get('id')}"
    model_reason = clean_ai_purchase_advisor_reason(parsed.get('reason'), max_chars=250)
    reason = (
        model_reason
        if selected_package_id == final_package_id and model_reason
        else build_ai_purchase_advisor_fallback_reason(
            advisor.get('answers', []), category, package, lang
        )
    )
    advisor.update({
        "status": "recommended",
        "category_id": category.get('id'),
        "package_id": package.get('id'),
        "reason": reason,
        "priority": priority,
    })
    user_states[user_id] = state
    persisted = save_ai_purchase_advisor_result(
        user_id, advisor, category, package, reason
    )
    result = {
        "category_id": category.get('id'),
        "package_id": package.get('id'),
        "answers": advisor.get('answers', []),
        "reason": reason,
        "question_count": advisor.get('question_count', 0),
    }
    text, keyboard = build_ai_purchase_advisor_result_text(
        user_id, lang, result
    )
    if not persisted:
        text += (
            t('the_recommendation_is_ready_1220b1b935', lang)
        )
    await processing.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "ai_purchase_advisor_start")
async def start_ai_purchase_advisor(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    if not get_active_ai_packages():
        await callback.answer(
            t('there_are_no_active_packages_110090817b', lang),
            show_alert=True,
        )
        return
    await callback.answer()
    saved_result = get_ai_purchase_advisor_result(user_id)
    if saved_result and user_id != ADMIN_ID_INT:
        saved_result = dict(saved_result)
        text, keyboard = build_ai_purchase_advisor_result_text(
            user_id,
            lang,
            saved_result,
            saved_result=True,
        )
        await callback.message.answer(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
        return
    await start_ai_purchase_advisor_flow(callback.message, user_id, lang)


async def start_ai_purchase_advisor_flow(
    message: Message,
    user_id: int,
    lang: str,
) -> None:
    remaining = get_ai_purchase_advisor_cooldown_remaining(user_id)
    if remaining and user_id != ADMIN_ID_INT:
        hours = max(1, int((remaining.total_seconds() + 3599) // 3600))
        await message.reply(
            t('you_can_take_the_smart_recom_09e95c74cc', lang, fa_parts=lambda: (f'{to_persian_digits(hours)}',), en_parts=lambda: (f'{hours}',))
        )
        return
    user = get_user(user_id)
    previous_started_at = user.get('ai_purchase_advisor_last_started_at')
    user['ai_purchase_advisor_last_started_at'] = datetime.now().astimezone().isoformat()
    if not save_json(DB_FILES['users'], users):
        if previous_started_at is None:
            user.pop('ai_purchase_advisor_last_started_at', None)
        else:
            user['ai_purchase_advisor_last_started_at'] = previous_started_at
        logger.error(
            "Could not persist smart-purchase cooldown for user %s",
            user_id,
        )
        await message.reply(
            t('the_assessment_cannot_start_fc6cb95dce', lang)
        )
        return
    state = user_states.setdefault(user_id, {})
    state['purchase_advisor'] = {
        'status': 'processing',
        'question_count': 0,
        'answers': [],
        'started_at': datetime.now().astimezone().isoformat(),
    }
    state.pop('purchase_advisor_invoice_order_id', None)
    state['ai_chat_mode'] = True
    state['timestamp'] = now_tehran_iso()
    user_states[user_id] = state
    await send_ai_purchase_advisor_question(message, user_id, lang, 1)


@router.callback_query(F.data == "ai_purchase_advisor_new")
async def start_new_ai_purchase_advisor(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    if not get_active_ai_packages():
        await callback.answer(
            t('there_are_no_active_packages_110090817b', lang),
            show_alert=True,
        )
        return
    await callback.answer()
    await start_ai_purchase_advisor_flow(callback.message, user_id, lang)


@router.callback_query(F.data == "ai_advisor_retry")
async def retry_ai_purchase_advisor(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    advisor = user_states.get(user_id, {}).get('purchase_advisor', {})
    if advisor.get('status') != 'retry':
        await callback.answer(
            t('this_step_is_no_longer_activ_6fb772230e', lang),
            show_alert=True,
        )
        return
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await run_ai_purchase_advisor_turn(callback.message, user_id, lang)


@router.callback_query(F.data.startswith("ai_advisor_answer_"))
async def answer_ai_purchase_advisor_option(callback: CallbackQuery):
    match = re.fullmatch(r"ai_advisor_answer_(\d+)_([a-zA-Z0-9]+)", callback.data or "")
    user_id = callback.from_user.id
    advisor = user_states.get(user_id, {}).get('purchase_advisor', {})
    if (
        not match
        or advisor.get('status') != 'questions'
        or int(advisor.get('question_count', -1)) != int(match.group(1))
    ):
        await callback.answer(
            t('this_option_is_no_longer_cur_73b8b65538', get_user(user_id).get('lang', 'fa')),
            show_alert=True,
        )
        return
    answer = advisor.get('options', {}).get(match.group(2))
    if not answer:
        await callback.answer(t('i18n_option_unavailable', get_user(user_id).get('lang', 'fa')), show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await handle_ai_purchase_advisor(
            callback.message,
            user_id,
            get_user(user_id).get('lang', 'fa'),
            answer_override=answer,
        )


async def handle_ai_purchase_advisor(
    message: Message,
    user_id: int,
    lang: str,
    answer_override: Optional[str] = None,
) -> bool:
    state = user_states.get(user_id, {})
    advisor = state.get('purchase_advisor')
    user_answer = answer_override if answer_override is not None else (message.text or "")

    if isinstance(advisor, dict) and advisor.get('status') == 'questions':
        question_kind = advisor.get('question_kind')
        answers = advisor.setdefault('answers', [])
        if not isinstance(answers, list):
            advisor['answers'] = []
            answers = advisor['answers']
        answers.append({
            "question": str(advisor.get('question', '')),
            "answer": user_answer.strip()[:500],
        })
        advisor['status'] = 'processing'
        user_states[user_id] = state
        if question_kind == "purpose":
            if parse_ai_volume_gb(user_answer) is None:
                await send_ai_purchase_advisor_question(
                    message,
                    user_id,
                    lang,
                    int(advisor.get('question_count', 1)) + 1,
                    question_kind="volume",
                )
                return True
        if question_kind in ("purpose", "volume"):
            await send_ai_purchase_advisor_question(
                message,
                user_id,
                lang,
                int(advisor.get('question_count', 1)) + 1,
                question_kind="stability",
            )
            return True
        await run_ai_purchase_advisor_turn(message, user_id, lang)
        return True

    if isinstance(advisor, dict) and advisor.get('status') == 'retry':
        answers = advisor.setdefault('answers', [])
        if user_answer.strip() and answers:
            answers[-1]['answer'] = user_answer.strip()[:500]
        advisor['status'] = 'processing'
        user_states[user_id] = state
        await run_ai_purchase_advisor_turn(message, user_id, lang)
        return True

    if isinstance(advisor, dict) and advisor.get('status') == 'processing':
        await message.reply(
            t('i_m_reviewing_your_answers_a_d484feefa5', lang)
        )
        return True

    return False



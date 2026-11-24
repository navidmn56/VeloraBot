from strings import t
import re
import unicodedata
from datetime import datetime
from typing import Any, Callable, Optional, Union


_DIGIT_MAP = str.maketrans({
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
    '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
})

_LETTER_MAP = str.maketrans({
    'ي': 'ی', 'ى': 'ی', 'ﻯ': 'ی', 'ﻰ': 'ی',
    'ك': 'ک', 'ﻙ': 'ک', 'ﻚ': 'ک',
    'ة': 'ه', 'ۀ': 'ه',
})

_DIACRITICS_RE = re.compile(r'[ً-ٰٟۖ-ۭ]')
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_DIGIT_MAP)
    text = text.translate(_LETTER_MAP)
    text = _DIACRITICS_RE.sub("", text)
    text = text.replace("‌", " ").replace("‏", "").replace("‎", "")
    return " ".join(text.split()).strip()


def strip_decorations(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s؀-ۿ‌]", "", text, flags=re.UNICODE)
    cleaned = cleaned.replace("_", " ")
    return " ".join(cleaned.split()).strip()


def clean_username(raw: Any) -> str:
    if raw is None:
        return ""
    value = str(raw).strip()
    if value.startswith("@"):
        value = value[1:]
    return re.sub(r"[^\w]", "", value, flags=re.UNICODE)


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def extract_numeric_id(query: str) -> Optional[int]:
    normalized = normalize_text(query)
    if not normalized or not normalized.isdigit():
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def format_size(size_bytes: Union[int, float]) -> str:
    if size_bytes is None or size_bytes == 0:
        return "0 B"
    try:
        size = float(size_bytes)
    except (TypeError, ValueError):
        return "0 B"
    if size < 0:
        return "0 B"
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    for unit in units:
        if size < 1024:
            if unit == 'B':
                return f"{int(size)} {unit}"
            if unit == 'KB':
                return f"{size:.1f} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def to_persian_digits(text: Any) -> str:
    return "".join(
        PERSIAN_DIGITS[int(ch)] if ch.isdigit() else ch
        for ch in str(text)
    )


def progress_bar(percent: float, length: int = 10) -> str:
    percent = max(0, min(100, percent))
    filled = round(length * percent / 100)
    empty = length - filled
    return "█" * filled + "░" * empty


def format_traffic_info(
    client: dict,
    traffic: dict = None,
    lang: str = "fa",
    premium_emoji_fn: Callable[[str, str], str] = None,
) -> str:
    if not client:
        return ""

    total_bytes = client.get("totalGB", 0)
    expiry = client.get("expiryTime", 0)
    stats_emoji = premium_emoji_fn('amar', '📊') if premium_emoji_fn else '📊'
    time_emoji = premium_emoji_fn('hourglass', '⏳') if premium_emoji_fn else '⏳'
    download_emoji = premium_emoji_fn('download', '📥') if premium_emoji_fn else '📥'

    time_left_text = t('unlimited_0d936642fc', lang)
    if expiry > 0:
        try:
            expire_dt = datetime.fromtimestamp(expiry / 1000)
            total_seconds = int((expire_dt - datetime.now()).total_seconds())
            if total_seconds <= 0:
                time_left_text = t('expired_756d905f6f', lang)
            else:
                days = total_seconds // 86400
                hours = (total_seconds % 86400) // 3600
                minutes = (total_seconds % 3600) // 60
                if lang == "fa":
                    if days > 0 and hours > 0:
                        time_left_text = t('d_h_left_067f2f1432', lang, fa_parts=lambda: (f'{to_persian_digits(days)}', f'{to_persian_digits(hours)}'))
                    elif days > 0:
                        time_left_text = t('days_left_0d58551cd3', lang, fa_parts=lambda: (f'{to_persian_digits(days)}',))
                    elif hours > 0 and minutes > 0:
                        time_left_text = t('h_m_left_ae486da160', lang, fa_parts=lambda: (f'{to_persian_digits(hours)}', f'{to_persian_digits(minutes)}'))
                    elif hours > 0:
                        time_left_text = t('h_left_1472acfd59', lang, fa_parts=lambda: (f'{to_persian_digits(hours)}',))
                    else:
                        time_left_text = t('min_left_38e6b3a2ae', lang, fa_parts=lambda: (f'{to_persian_digits(minutes)}',))
                elif days > 0 and hours > 0:
                    time_left_text = t('d_h_left_067f2f1432', lang, en_parts=lambda: (f'{days}', f'{hours}'))
                elif days > 0:
                    time_left_text = t('days_left_0d58551cd3', lang, en_parts=lambda: (f'{days}',))
                elif hours > 0:
                    if minutes > 0:
                        time_left_text = t('h_m_left_ae486da160', lang, en_parts=lambda: (f'{hours}', f'{minutes}'))
                    else:
                        time_left_text = t('h_left_1472acfd59', lang, en_parts=lambda: (f'{hours}',))
                else:
                    time_left_text = t('min_left_38e6b3a2ae', lang, en_parts=lambda: (f'{minutes}',))
        except Exception:
            pass

    if total_bytes == 0:
        return t('expiry_cfd17e0b09', lang, fa_parts=lambda: (f'{time_emoji}', f'{time_left_text}'), en_parts=lambda: (f'{time_emoji}', f'{time_left_text}'))

    total_gb = total_bytes / (1024 ** 3)
    up = traffic.get("up", 0) / (1024 ** 3) if traffic else 0
    down = traffic.get("down", 0) / (1024 ** 3) if traffic else 0
    used_gb = up + down
    percent = (used_gb / total_gb * 100) if total_gb > 0 else 0
    percent = min(percent, 100)
    percent_int = int(round(percent))
    bar = progress_bar(percent, length=10)

    def fmt_size(gb_val):
        if gb_val >= 1:
            val = f"{gb_val:.1f}".rstrip('0').rstrip('.')
            return t("i18n_volume_gig_format", lang, fa_parts=lambda: (val,), en_parts=lambda: (val,))
        value = f"{gb_val * 1024:.0f}"
        return t("i18n_volume_mb_format", lang, fa_parts=lambda: (value,), en_parts=lambda: (value,))

    used_str = fmt_size(used_gb)
    total_str = fmt_size(total_gb)
    percent_str = f"{percent_int}{t('i18n_percent_sign', lang)}"
    if lang == "fa":
        percent_str = to_persian_digits(percent_str)
    return t(
        "i18n_usage_progress_summary",
        lang,
        fa_format_args=lambda: ((stats_emoji, bar, percent_str, download_emoji, used_str, total_str, time_emoji, time_left_text), {}),
        en_format_args=lambda: ((stats_emoji, bar, percent_str, download_emoji, used_str, total_str, time_emoji, time_left_text), {}),
    )

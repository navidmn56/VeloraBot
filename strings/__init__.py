"""Bilingual text lookup helpers."""

import logging
from typing import Callable, Optional, Tuple, Dict, Any

from .en import STRINGS as EN_STRINGS
from .fa import STRINGS as FA_STRINGS

logger = logging.getLogger(__name__)


def t(
    key: str,
    lang: str,
    *,
    fa_parts: Optional[Callable[[], Tuple[str, ...]]] = None,
    en_parts: Optional[Callable[[], Tuple[str, ...]]] = None,
    fa_format_args: Optional[Callable[[], Tuple[Tuple[Any, ...], Dict[str, Any]]]] = None,
    en_format_args: Optional[Callable[[], Tuple[Tuple[Any, ...], Dict[str, Any]]]] = None,
    fa_transform: Optional[Callable[[str], str]] = None,
    en_transform: Optional[Callable[[str], str]] = None,
) -> str:
    """Return a catalog string, preserving lazy, locale-specific formatting."""
    is_fa = lang == "fa"
    catalog = FA_STRINGS if is_fa else EN_STRINGS
    value = catalog.get(key)
    if value is None:
        fallback_catalog = EN_STRINGS if is_fa else FA_STRINGS
        value = fallback_catalog.get(key)
        if value is None:
            logger.warning("Missing i18n key: %r (lang=%r)", key, lang)
            return key
        logger.warning("i18n key %r missing in %s catalog; used fallback", key, lang)

    parts = fa_parts if is_fa else en_parts
    format_args = fa_format_args if is_fa else en_format_args
    transform = fa_transform if is_fa else en_transform
    try:
        if parts is not None:
            value = value.format(*parts())
        elif format_args is not None:
            args, kwargs = format_args()
            value = value.format(*args, **kwargs)
    except Exception as exc:
        logger.warning("Failed formatting i18n key %r (lang=%r): %s", key, lang, exc)
    if transform is not None:
        value = transform(value)
    return value

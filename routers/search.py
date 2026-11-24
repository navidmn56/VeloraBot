"""
routers/search.py
-----------------
سیستم جستجوی پیشرفته کاربران تلگرام برای ادمین.
شامل تطبیق فازی بر اساس آیدی، نام، یوزرنیم و کد کوپن،
صفحه‌بندی، کش نتایج و ناوبری به پروفایل کاربر.
"""

import time
import html
import logging
import re
from typing import Optional, List, Dict, Any

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from config import ADMIN_ID
from database import users, orders, now_tehran_iso
from user_manager import user_states, get_user, get_admin_id_int
from strings import t
from text_utils import (
    clean_username,
    extract_numeric_id,
    normalize_text,
    safe_str,
    strip_decorations,
)
from utils.filters import IsAdmin
from utils.helpers import safe_answer

logger = logging.getLogger(__name__)

router = Router(name="search")

# ============================================================
# تنظیمات
# ============================================================

SEARCH_RESULTS_PER_PAGE = 8
SEARCH_CACHE_TTL_SECONDS = 600  # ۱۰ دقیقه

# Cache: {admin_id: {"results": [...], "query": str, "page": int, "ts": float}}
SEARCH_RESULTS_CACHE: Dict[int, Dict[str, Any]] = {}

# اولویت‌ها (هرچه بزرگ‌تر، مهم‌تر)
SCORE_EXACT_ID = 1_000_000
SCORE_EXACT_USERNAME = 900_000
SCORE_EXACT_TG_USERNAME = 880_000
SCORE_EXACT_NAME = 800_000
SCORE_USERNAME_STARTSWITH = 500_000
SCORE_NAME_STARTSWITH = 400_000
SCORE_ID_STARTSWITH = 350_000
SCORE_USERNAME_CONTAINS = 200_000
SCORE_NAME_CONTAINS = 150_000
SCORE_ID_CONTAINS = 100_000
SCORE_COUPON_EXACT = 90_000
SCORE_COUPON_STARTSWITH = 60_000
SCORE_COUPON_CONTAINS = 30_000


def _get_admin_id() -> int:
    try:
        aid = get_admin_id_int()
        if aid:
            return aid
    except Exception:
        pass
    try:
        return int(ADMIN_ID)
    except Exception:
        return 0


def _admin_ok(user_id: int) -> bool:
    return user_id == _get_admin_id()


def _get_lang(user_id: int) -> str:
    u = get_user(user_id) or {}
    return u.get("lang", "fa")


# ============================================================
# هسته اصلی جستجو
# ============================================================

def advanced_search_users(
    query: str,
    *,
    search_in: str = "all",
    exact_match: bool = False,
    case_sensitive: bool = False,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    جستجوی پیشرفته در کاربران.

    Args:
        query: عبارت جستجو
        search_in: یکی از "all" | "name" | "username" | "id" | "coupon"
        exact_match: اگر True، فقط تطابق‌های دقیق برگردانده می‌شوند
        case_sensitive: حساس به حروف بزرگ/کوچک
        limit: حداکثر تعداد نتایج

    Returns:
        لیست dict با کلیدهای user_id, name, username, telegram_username, balance,
        coupon_code, match_score, match_reasons, user_data
    """
    if not isinstance(query, str):
        query = safe_str(query)
    query = query.strip()
    if not query:
        return []

    valid_search_in = {"all", "name", "username", "id", "coupon"}
    if search_in not in valid_search_in:
        search_in = "all"

    do_name = search_in in ("all", "name")
    do_username = search_in in ("all", "username")
    do_id = search_in in ("all", "id")
    do_coupon = search_in in ("all", "coupon")

    # ---------- آماده‌سازی query ----------
    query_norm = normalize_text(query)
    query_for_decoration = strip_decorations(query_norm)

    query_as_username = clean_username(query)

    query_id_exact = extract_numeric_id(query)
    query_digits = re.sub(r"\D", "", query_norm) if query_norm else ""

    results: List[Dict[str, Any]] = []

    for uid_key, user_data in users.items():
        try:
            if not isinstance(user_data, dict):
                continue

            user_id = user_data.get("id")
            if user_id is None:
                try:
                    user_id = int(uid_key)
                except (TypeError, ValueError):
                    continue
            try:
                user_id_int = int(user_id)
            except (TypeError, ValueError):
                continue

            name_raw = user_data.get("name") or ""
            username_raw = user_data.get("username") or ""
            tg_username_raw = user_data.get("telegram_username") or ""
            coupon_raw = user_data.get("coupon_code") or ""
            balance = user_data.get("balance", 0) or 0

            total_score = 0
            reasons: List[str] = []
            exact_hit = False

            # 1) ID
            if do_id and query_digits:
                user_id_str = str(user_id_int)

                if query_id_exact is not None and user_id_int == query_id_exact:
                    total_score += SCORE_EXACT_ID
                    reasons.append("exact_id")
                    exact_hit = True
                elif query_digits in user_id_str:
                    if user_id_str.startswith(query_digits):
                        total_score += SCORE_ID_STARTSWITH
                        reasons.append("id_startswith")
                    else:
                        total_score += SCORE_ID_CONTAINS
                        reasons.append("id_contains")

            # 2) Username
            if do_username:
                for field_name, field_value, exact_sc, start_sc, cont_sc in [
                    ("username", username_raw, SCORE_EXACT_USERNAME,
                     SCORE_USERNAME_STARTSWITH, SCORE_USERNAME_CONTAINS),
                    ("telegram_username", tg_username_raw, SCORE_EXACT_TG_USERNAME,
                     SCORE_USERNAME_STARTSWITH, SCORE_USERNAME_CONTAINS),
                ]:
                    cleaned = clean_username(field_value)
                    if not cleaned:
                        continue

                    cleaned_cmp = cleaned.lower()
                    query_cmp = query_as_username.lower() if query_as_username else ""
                    if not query_cmp:
                        continue

                    if cleaned_cmp == query_cmp:
                        total_score += exact_sc
                        reasons.append(f"exact_{field_name}")
                        exact_hit = True
                    elif cleaned_cmp.startswith(query_cmp):
                        total_score += start_sc
                        reasons.append(f"{field_name}_startswith")
                    elif query_cmp in cleaned_cmp:
                        total_score += cont_sc
                        reasons.append(f"{field_name}_contains")

            # 3) Name
            if do_name:
                name_norm = normalize_text(name_raw)
                name_decor = strip_decorations(name_norm)

                if not case_sensitive:
                    name_norm_cmp = name_norm.lower()
                    name_decor_cmp = name_decor.lower()
                    query_norm_cmp = query_norm.lower()
                    query_decor_cmp = query_for_decoration.lower()
                else:
                    name_norm_cmp = name_norm
                    name_decor_cmp = name_decor
                    query_norm_cmp = query_norm
                    query_decor_cmp = query_for_decoration

                matched_name = False

                if name_norm_cmp and query_norm_cmp and name_norm_cmp == query_norm_cmp:
                    total_score += SCORE_EXACT_NAME
                    reasons.append("exact_name")
                    exact_hit = True
                    matched_name = True
                elif (name_decor_cmp and query_decor_cmp
                      and name_decor_cmp == query_decor_cmp):
                    total_score += SCORE_EXACT_NAME - 1
                    reasons.append("exact_name_clean")
                    exact_hit = True
                    matched_name = True

                if not matched_name:
                    if (name_norm_cmp and query_norm_cmp
                            and name_norm_cmp.startswith(query_norm_cmp)):
                        total_score += SCORE_NAME_STARTSWITH
                        reasons.append("name_startswith")
                    elif (name_decor_cmp and query_decor_cmp
                          and name_decor_cmp.startswith(query_decor_cmp)):
                        total_score += SCORE_NAME_STARTSWITH - 1
                        reasons.append("name_startswith_clean")
                    elif (name_norm_cmp and query_norm_cmp
                          and query_norm_cmp in name_norm_cmp):
                        total_score += SCORE_NAME_CONTAINS
                        reasons.append("name_contains")
                    elif (name_decor_cmp and query_decor_cmp
                          and query_decor_cmp in name_decor_cmp):
                        total_score += SCORE_NAME_CONTAINS - 1
                        reasons.append("name_contains_clean")

                if not matched_name:
                    query_words = [
                        w for w in query_decor_cmp.split() if w
                    ]
                    name_words = set(name_decor_cmp.split())
                    if len(query_words) > 1:
                        if all(
                            any(qw in nw for nw in name_words)
                            for qw in query_words
                        ):
                            total_score += SCORE_NAME_CONTAINS // 2
                            reasons.append("name_all_words")

            # 4) Coupon
            if do_coupon:
                coupon_str = safe_str(coupon_raw)
                if coupon_str:
                    c_cmp = coupon_str if case_sensitive else coupon_str.lower()
                    q_cmp = query if case_sensitive else query.lower()
                    c_cmp_norm = normalize_text(c_cmp)
                    q_cmp_norm = normalize_text(q_cmp)
                    if c_cmp_norm == q_cmp_norm:
                        total_score += SCORE_COUPON_EXACT
                        reasons.append("coupon_exact")
                        exact_hit = True
                    elif c_cmp_norm.startswith(q_cmp_norm):
                        total_score += SCORE_COUPON_STARTSWITH
                        reasons.append("coupon_startswith")
                    elif q_cmp_norm in c_cmp_norm:
                        total_score += SCORE_COUPON_CONTAINS
                        reasons.append("coupon_contains")

            if total_score <= 0:
                continue

            if exact_match and not exact_hit:
                continue

            results.append({
                "user_id": user_id_int,
                "name": safe_str(name_raw),
                "name_norm": normalize_text(name_raw),
                "name_clean": strip_decorations(normalize_text(name_raw)),
                "username": safe_str(username_raw),
                "username_clean": clean_username(username_raw),
                "telegram_username": safe_str(tg_username_raw),
                "telegram_username_clean": clean_username(tg_username_raw),
                "balance": balance,
                "coupon_code": safe_str(coupon_raw),
                "join_date": safe_str(user_data.get("join_date", "")),
                "match_score": total_score,
                "match_reasons": reasons,
                "user_data": user_data,
            })

        except Exception as e:
            logger.warning(f"Search: skipping broken user {uid_key}: {e}")
            continue

    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results[:limit]


# ============================================================
# Cache مدیریت
# ============================================================

def _cache_get(admin_id: int) -> Optional[Dict[str, Any]]:
    entry = SEARCH_RESULTS_CACHE.get(admin_id)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > SEARCH_CACHE_TTL_SECONDS:
        SEARCH_RESULTS_CACHE.pop(admin_id, None)
        return None
    return entry


def _cache_set(admin_id: int, results: List[Dict], query: str) -> None:
    SEARCH_RESULTS_CACHE[admin_id] = {
        "results": results,
        "query": query,
        "page": 0,
        "ts": time.time(),
    }


def _cache_update_page(admin_id: int, page: int) -> Optional[Dict[str, Any]]:
    entry = _cache_get(admin_id)
    if not entry:
        return None
    entry["page"] = page
    entry["ts"] = time.time()
    return entry


# ============================================================
# UI: ساخت متن و کیبورد
# ============================================================

def _reason_to_display(reason: str, lang: str = "fa") -> str:
    mapping_fa = {
        "exact_id": "🎯 آیدی دقیق",
        "id_startswith": "🆔 آیدی شروع",
        "id_contains": "🆔 آیدی شامل",
        "exact_username": "🎯 یوزرنیم دقیق",
        "username_startswith": "📛 یوزرنیم شروع",
        "username_contains": "📛 یوزرنیم شامل",
        "exact_telegram_username": "🎯 تلگرام دقیق",
        "telegram_username_startswith": "📛 تلگرام شروع",
        "telegram_username_contains": "📛 تلگرام شامل",
        "exact_name": "🎯 نام دقیق",
        "exact_name_clean": "🎯 نام دقیق",
        "name_startswith": "👤 نام شروع",
        "name_startswith_clean": "👤 نام شروع",
        "name_contains": "👤 نام شامل",
        "name_contains_clean": "👤 نام شامل",
        "name_all_words": "👤 همه کلمات",
        "coupon_exact": "🎟 کوپن دقیق",
        "coupon_startswith": "🎟 کوپن شروع",
        "coupon_contains": "🎟 کوپن شامل",
    }
    mapping_en = {
        "exact_id": "🎯 Exact ID",
        "id_startswith": "🆔 ID starts",
        "id_contains": "🆔 ID contains",
        "exact_username": "🎯 Exact username",
        "username_startswith": "📛 Username starts",
        "username_contains": "📛 Username contains",
        "exact_telegram_username": "🎯 Exact telegram",
        "telegram_username_startswith": "📛 Telegram starts",
        "telegram_username_contains": "📛 Telegram contains",
        "exact_name": "🎯 Exact name",
        "exact_name_clean": "🎯 Exact name",
        "name_startswith": "👤 Name starts",
        "name_startswith_clean": "👤 Name starts",
        "name_contains": "👤 Name contains",
        "name_contains_clean": "👤 Name contains",
        "name_all_words": "👤 All words",
        "coupon_exact": "🎟 Exact coupon",
        "coupon_startswith": "🎟 Coupon starts",
        "coupon_contains": "🎟 Coupon contains",
    }
    return (mapping_fa if lang == "fa" else mapping_en).get(reason, reason)


def _format_one_user(user: Dict[str, Any], lang: str = "fa") -> str:
    uid = user["user_id"]
    name = html.escape(safe_str(user.get("name"))[:32] or "—")

    uname_display = ""
    uname = user.get("username_clean") or ""
    tg_uname = user.get("telegram_username_clean") or ""
    if uname:
        uname_display = f"@{html.escape(uname)}"
    elif tg_uname:
        uname_display = f"@{html.escape(tg_uname)}"

    balance = user.get("balance", 0) or 0
    coupon = user.get("coupon_code") or ""
    reasons = user.get("match_reasons") or []

    reasons_disp = " | ".join(
        _reason_to_display(r, lang) for r in reasons[:2]
    )

    lines = [f"👤 <b>{name}</b>"]
    line2 = f"🆔 <code>{uid}</code>"
    if uname_display:
        line2 += f" | 📛 {uname_display}"
    lines.append(line2)

    line3 = f"💰 {balance:,}"
    if coupon:
        line3 += f" | 🎟 <code>{html.escape(safe_str(coupon))}</code>"
    lines.append(line3)

    if reasons_disp:
        lines.append(reasons_disp)

    return "\n".join(lines)


def format_search_results_text(
    results: List[Dict[str, Any]],
    page: int = 0,
    query: str = "",
    lang: str = "fa",
) -> str:
    total = len(results)
    total_pages = (total + SEARCH_RESULTS_PER_PAGE - 1) // SEARCH_RESULTS_PER_PAGE \
        if total > 0 else 1

    page = max(0, min(page, total_pages - 1))

    start = page * SEARCH_RESULTS_PER_PAGE
    end = min(start + SEARCH_RESULTS_PER_PAGE, total)
    page_items = results[start:end]

    header = t('b_search_results_b_query_cod_bcb4df21dd', lang, fa_parts=lambda: (f'{html.escape(query)}', f'{total}', f'{page + 1}', f'{total_pages}'), en_parts=lambda: (f'{html.escape(query)}', f'{total}', f'{page + 1}', f'{total_pages}'))

    if not page_items:
        return header + (t('no_results_found_3d05eb43f9', lang))

    body_parts = []
    for i, u in enumerate(page_items, start=start + 1):
        body_parts.append(f"<b>{i}.</b>\n{_format_one_user(u, lang)}")

    return header + "\n\n".join(body_parts)


def get_search_results_keyboard(
    results: List[Dict[str, Any]],
    page: int = 0,
    lang: str = "fa",
    orders_dict: dict = None,
) -> InlineKeyboardMarkup:
    total = len(results)
    total_pages = (total + SEARCH_RESULTS_PER_PAGE - 1) // SEARCH_RESULTS_PER_PAGE \
        if total > 0 else 1
    page = max(0, min(page, total_pages - 1))

    start = page * SEARCH_RESULTS_PER_PAGE
    end = min(start + SEARCH_RESULTS_PER_PAGE, total)
    page_items = results[start:end]

    buttons: List[List[InlineKeyboardButton]] = []

    if orders_dict is None:
        try:
            orders_dict = orders
        except Exception:
            orders_dict = {}

    for u in page_items:
        uid = u["user_id"]
        name = safe_str(u.get("name"))
        name_button = strip_decorations(normalize_text(name))[:20] or f"ID {uid}"
        balance = u.get("balance", 0) or 0

        orders_count = 0
        if orders_dict:
            orders_count = len([
                o for o in orders_dict.values()
                if isinstance(o, dict)
                and o.get("user_id") == uid
                and o.get("status") == "approved"
            ])

        score = u.get("match_score", 0)
        if score >= SCORE_EXACT_ID:
            emoji = "🎯"
        elif score >= SCORE_EXACT_NAME:
            emoji = "✅"
        elif score >= SCORE_NAME_STARTSWITH:
            emoji = "👤"
        else:
            emoji = "👤"

        label = f"{emoji} {name_button} - {balance:,} T ({orders_count})"
        buttons.append([InlineKeyboardButton(
            text=label[:60],
            callback_data=f"search_result_{uid}",
        )])

    # Pagination
    if total_pages > 1:
        nav: List[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text=t('prev_ad2dbc546b', lang),
                callback_data=f"search_page_{page - 1}",
            ))
        nav.append(InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data="noop",
        ))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(
                text=t('next_c99400f27f', lang),
                callback_data=f"search_page_{page + 1}",
            ))
        if nav:
            buttons.append(nav)

    # Actions
    buttons.append([
        InlineKeyboardButton(
            text=t('new_search_ff6b25d9d6', lang),
            callback_data="search_new",
        ),
        InlineKeyboardButton(
            text=t('back_460da353ef', lang),
            callback_data="admin_users",
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


class FakeCallback:
    """آبجکت Fake برای صدا زدن admin_user_detail"""
    def __init__(self, original_cb, new_data):
        self._original = original_cb
        self.data = new_data
    
    def __getattr__(self, name):
        return getattr(self._original, name)
    
    async def answer(self, *args, **kwargs):
        return await self._original.answer(*args, **kwargs)


# ============================================================
# Handlers: جستجو
# ============================================================

@router.callback_query(F.data == "admin_search_users")
async def admin_search_start(cb: CallbackQuery):
    if not _admin_ok(cb.from_user.id):
        return await cb.answer("⛔", show_alert=True)

    lang = _get_lang(cb.from_user.id)

    user_states[cb.from_user.id] = {
        "awaiting_user_search": True,
        "timestamp": now_tehran_iso(),
    }

    text = t('b_advanced_user_search_b_b_n_4c05c793fc', lang)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=t('back_14968ad63f', lang),
            callback_data="admin_users",
        )
    ]])

    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass

    await safe_answer(cb)


@router.message(IsAdmin(), lambda m: user_states.get(m.from_user.id, {}).get("awaiting_user_search"))
async def admin_search_input(msg: Message):
    admin_id = msg.from_user.id
    if not _admin_ok(admin_id):
        return
    
    lang = _get_lang(admin_id)
    query_raw = (msg.text or "").strip()

    if query_raw == "/cancel":
        user_states.pop(admin_id, None)
        return await msg.reply(
            t('search_cancelled_fb59f13abc', lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=t('back_to_panel_63039f103a', lang),
                    callback_data="admin_users",
                )
            ]]),
        )

    if not query_raw:
        return await msg.reply(t('please_enter_a_search_term_80bc3fa022', lang))

    results = advanced_search_users(query_raw, search_in="all", limit=200)

    _cache_set(admin_id, results, query_raw)

    user_states.pop(admin_id, None)

    text = format_search_results_text(results, page=0, query=query_raw, lang=lang)
    kb = get_search_results_keyboard(results, page=0, lang=lang)

    await msg.reply(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("search_page_"))
async def admin_search_page(cb: CallbackQuery):
    if not _admin_ok(cb.from_user.id):
        return await cb.answer("⛔", show_alert=True)

    admin_id = cb.from_user.id
    lang = _get_lang(admin_id)

    try:
        page = int(cb.data.split("_")[2])
    except (ValueError, IndexError):
        return await cb.answer("❌", show_alert=True)

    entry = _cache_get(admin_id)
    if not entry:
        return await cb.answer(
            t('expired_search_again_7ce3fb89f0', lang),
            show_alert=True,
        )

    results = entry["results"]
    query = entry["query"]
    total_pages = (len(results) + SEARCH_RESULTS_PER_PAGE - 1) // SEARCH_RESULTS_PER_PAGE
    if page < 0 or page >= total_pages:
        return await cb.answer(t('i18n_unknown', lang), show_alert=True)

    _cache_update_page(admin_id, page)

    text = format_search_results_text(results, page=page, query=query, lang=lang)
    kb = get_search_results_keyboard(results, page=page, lang=lang)
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"search page edit failed: {e}")

    await safe_answer(cb)


@router.callback_query(F.data == "search_new")
async def admin_search_new(cb: CallbackQuery):
    if not _admin_ok(cb.from_user.id):
        return await cb.answer("⛔", show_alert=True)
    await admin_search_start(cb)


@router.callback_query(F.data.startswith("search_result_"))
async def admin_search_result(cb: CallbackQuery):
    """نمایش پروفایل کاربر از نتایج جستجو"""
    admin_id_int = _get_admin_id()
    if not getattr(cb, "from_user", None) or cb.from_user.id != admin_id_int:
        return await cb.answer("⛔", show_alert=True)

    try:
        user_id = int(cb.data.split("_")[2])
    except (ValueError, IndexError):
        return await cb.answer("❌", show_alert=True)

    fake_cb = FakeCallback(cb, f"admin_user_{user_id}_0")
    try:
        import main
        if hasattr(main, "admin_user_detail"):
            await main.admin_user_detail(fake_cb)
        else:
            await cb.answer("خطا در فراخوانی جزئیات کاربر", show_alert=True)
    except Exception as e:
        logger.error(f"Error calling admin_user_detail: {e}", exc_info=True)
        await cb.answer("❌ خطا در نمایش جزئیات کاربر", show_alert=True)


def register_search_handlers(dp, admin_id_int: Optional[int] = None, get_user_func=None, get_lang_func=None):
    """
    تابع سازگاری backward-compatible برای ثبت router روی dispatcher
    """
    if hasattr(dp, "include_router") and dp != router:
        dp.include_router(router)
    return {
        "start": admin_search_start,
        "input": admin_search_input,
        "page": admin_search_page,
        "new": admin_search_new,
        "result": admin_search_result,
    }

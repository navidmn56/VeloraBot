"""
routers/configs_view.py
-----------------------
مدیریت نمایش کانفیگ‌ها، لینک‌های ساب، کیبوردهای پلتفرم، کد QR و خروجی‌های WireGuard
"""

import asyncio
import base64
import html
import json
import re
import sys
from io import BytesIO
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import aiohttp
from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    CopyTextButton,
)
from aiogram.enums import ParseMode

import config as app_config
from config import SENAI_PANEL_ENABLED, is_senai_panel_enabled
from database import (
    orders,
    READY_PACKAGES,
    BLACKLIST,
    get_valid_orders,
    get_test_service_display,
    now_tehran,
)
from user_manager import get_user, update_user, user_states
from strings import t
from utils.helpers import (
    safe_answer,
    get_back_only_keyboard,
    notify_blacklisted_user,
    premium_emoji,
)
from text_utils import format_traffic_info
from qr_file_system import (
    generate_qr_code as _generate_qr_code_impl,
    delete_downloaded_files as _delete_downloaded_files_impl,
    track_downloaded_file,
)
from wireguard_system import build_wireguard_config
from wireguard_card_generator import generate_wireguard_qr_code
from emoji_sticker_system import send_sticker as _send_sticker_impl
from logger_system import logger
from routers.admin_packages import log_system
from routers.admin_packages import format_volume
from routers.admin_tools import sync_user_configs

from core.state_stores import CONFIG_LINKS_CACHE

router = Router(name="configs_view")

_bot: Optional[Bot] = None

CONFIG_LINKS_CACHE_TTL = 300
CONFIG_PAGE_SIZE = 1
ALL_CONFIGS_PAGE_SIZE = 5


def _is_test_order(order: Optional[dict]) -> bool:
    """تشخیص یکپارچه سرویس تست/خوش‌آمد از روی نوع، پرچم یا پیشوند ایمیل"""
    if not isinstance(order, dict):
        return False
    order_type = order.get("type", "purchase")
    email = str(order.get("email", "") or "")
    return bool(
        order_type == "test"
        or order.get("is_test", False)
        or email.startswith("test_")
        or re.match(r"^t\d+_", email)
    )


def set_bot(bot_instance: Bot):
    global _bot
    _bot = bot_instance


def get_bot() -> Optional[Bot]:
    global _bot
    if _bot is not None:
        return _bot
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "bot"):
        return getattr(main_mod, "bot")
    return None


async def send_sticker(
    chat_id: int,
    sticker_key: str,
    fallback_emoji: str = "📌",
    reply_markup: Any = None,
) -> bool:
    bot_inst = get_bot()
    if bot_inst is None:
        return False
    return await _send_sticker_impl(
        bot_inst,
        chat_id,
        sticker_key,
        fallback_emoji,
        reply_markup,
        logger,
    )
    return None


def generate_qr_code(data: str, order_id: int):
    return _generate_qr_code_impl(data, order_id, logger)


from services.panel_api import (
    xui_get_inbounds,
    xui_get_client_links,
    xui_get_client_info,
    xui_get_client_traffic,
    get_order_client_email,
)


def _decode_inbound_settings(inbound: dict) -> dict:
    settings = inbound.get("settings", {})
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"تنظیمات اینباند {inbound.get('id')} قابل خواندن نیست"
            ) from e
    if not isinstance(settings, dict):
        raise RuntimeError(f"تنظیمات اینباند {inbound.get('id')} معتبر نیست")
    return settings


async def _get_order_wireguard_clients(order_id: int, force_refresh: bool = False) -> list:
    """Find enabled WireGuard inbounds that contain this order's client."""
    order = orders.get(str(order_id))
    email = get_order_client_email(order) if order else None
    if not email or not is_senai_panel_enabled():
        return []

    matches = []
    for inbound in await xui_get_inbounds(
        force_refresh=force_refresh,
        include_disabled=True,
    ):
        if not isinstance(inbound, dict):
            continue
        if str(inbound.get("protocol", "")).lower() != "wireguard":
            continue
        if not inbound.get("enable", True):
            continue

        try:
            settings = _decode_inbound_settings(inbound)
        except (RuntimeError, ValueError) as error:
            logger.error(
                'WireGuard inbound settings for %s are unreadable: %s',
                inbound.get("id"),
                error,
            )
            continue

        clients = settings.get("clients", [])
        if not isinstance(clients, list):
            logger.error(
                'Client list for WireGuard inbound %s is invalid',
                inbound.get("id"),
            )
            continue

        inbound_matches = [
            client
            for client in clients
            if isinstance(client, dict)
            and client.get("email") == email
            and client.get("enable", True)
        ]
        if len(inbound_matches) > 1:
            logger.error(
                'Client %s is duplicated in WireGuard inbound %s',
                email,
                inbound.get("id"),
            )
            continue
        if inbound_matches:
            matches.append(
                {
                    "inbound": inbound,
                    "settings": settings,
                    "client": inbound_matches[0],
                }
            )
    return matches


async def _order_has_wireguard(
    order_id: int,
    force_refresh: bool = False,
) -> bool:
    try:
        return bool(
            await _get_order_wireguard_clients(
                order_id,
                force_refresh=force_refresh,
            )
        )
    except Exception as error:
        logger.error(
            'WireGuard inbound check for order #%s failed: %s',
            order_id,
            error,
            exc_info=True,
        )
        return False


def _is_telegram_proxy(link: str) -> bool:
    """تشخیص اینکه آیا یک لینک، پروکسی تلگرام (MTProto یا Socks5) است یا خیر"""
    if not isinstance(link, str):
        return False
    clean = link.strip()
    lower = clean.lower()
    if lower.startswith("tg://proxy") or lower.startswith("tg://socks"):
        return True
    if lower.startswith("https://t.me/proxy") or lower.startswith("https://t.me/socks"):
        return True
    if lower.startswith("http://t.me/proxy") or lower.startswith("http://t.me/socks"):
        return True
    if lower.startswith("t.me/proxy") or lower.startswith("t.me/socks"):
        return True
    if lower.startswith("tg://") and ("server=" in lower or "secret=" in lower or "port=" in lower):
        return True
    return False


async def _fetch_proxy_from_subscription(sub_link: str) -> Optional[str]:
    """دریافت و استخراج لینک پروکسی تلگرام از محتوای ساب کاربر"""
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                sub_link,
                timeout=aiohttp.ClientTimeout(total=4),
                headers={"User-Agent": "v2rayNG/1.8.5"}
            ) as response:
                if response.status == 200:
                    text_content = await response.text()
                    if not text_content:
                        return None

                    raw_text = text_content.strip()
                    lines = []
                    try:
                        pad = "=" * (-len(raw_text) % 4)
                        decoded_bytes = base64.b64decode(raw_text + pad)
                        decoded_text = decoded_bytes.decode('utf-8', errors='ignore')
                        lines.extend(decoded_text.splitlines())
                    except Exception:
                        pass

                    lines.extend(raw_text.splitlines())

                    for line in lines:
                        line = line.strip()
                        if _is_telegram_proxy(line):
                            return line
    except Exception as e:
        logger.debug(f"Error fetching proxy from subscription {sub_link}: {e}")
    return None


async def _get_order_telegram_proxy(order_id: int) -> Optional[str]:
    """یافتن لینک پروکسی تلگرام برای سفارش"""
    try:
        links, _ = await _get_cached_config_links(order_id)
        for link in links:
            if _is_telegram_proxy(link):
                return link
    except Exception as e:
        logger.debug(f"Error checking Telegram proxy for order #{order_id}: {e}")
    return None


async def _get_cached_config_links(order_id: int, force_refresh: bool = False):
    """دریافت لینک‌های کانفیگ با کش (برای صفحه‌بندی)"""
    now = datetime.now()

    if not force_refresh and order_id in CONFIG_LINKS_CACHE:
        cached = CONFIG_LINKS_CACHE[order_id]
        if (now - cached['timestamp']).total_seconds() < CONFIG_LINKS_CACHE_TTL:
            return cached['links'], cached['email']

    order = orders.get(str(order_id))
    if not order:
        return [], None

    email = get_order_client_email(order)
    links = []

    if email and is_senai_panel_enabled():
        raw_links = await xui_get_client_links(email)
        if raw_links:
            for link in raw_links:
                if isinstance(link, str) and (
                    link.startswith('vless://') or
                    link.startswith('vmess://') or
                    link.startswith('trojan://') or
                    link.startswith('ss://') or
                    _is_telegram_proxy(link)
                ):
                    links.append(link.strip())

        for wireguard in await _get_order_wireguard_clients(order_id):
            try:
                links.append(
                    build_wireguard_config(
                        wireguard["inbound"],
                        wireguard["client"],
                        app_config.SENAI_PANEL_URL,
                    )
                )
            except (TypeError, ValueError) as error:
                logger.error(
                    'Failed to generate WireGuard text for order #%s: %s',
                    order_id,
                    error,
                    exc_info=True,
                )

    # اگر پروکسی تلگرام در لینک‌های دریافتی نبود، بررسی ساب کاربر
    if not any(_is_telegram_proxy(l) for l in links):
        sub_link = order.get('sub_link') or order.get('config_link')
        if sub_link and isinstance(sub_link, str) and sub_link.startswith('http'):
            proxy_from_sub = await _fetch_proxy_from_subscription(sub_link)
            if proxy_from_sub and proxy_from_sub not in links:
                links.append(proxy_from_sub)

    if not links and order.get('config_link'):
        links = [order['config_link']]

    CONFIG_LINKS_CACHE[order_id] = {
        'links': links,
        'email': email,
        'timestamp': now
    }
    return links, email


async def _delete_downloaded_files(user_id: int, chat_id: int = None):
    bot = get_bot()
    await _delete_downloaded_files_impl(user_id, chat_id, bot, logger)


def get_config_view_keyboard(
    order_id: int,
    show_qr: bool = False,
    lang: str = "fa",
    wireguard_available: bool = False,
    telegram_proxy_url: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """ساخت کیبورد نمایش کانفیگ با دکمه‌های پلتفرم"""

    order = orders.get(str(order_id))
    is_test = _is_test_order(order)

    buttons = []

    # ─── ردیف 1: تمدید همین سرویس ───
    if not is_test:
        buttons.append([InlineKeyboardButton(
            text=t('extend_this_service_473b3cd53a', lang),
            callback_data=f"extend_service_{order_id}",
            style="success"
        )])

    # ─── ردیف 2: QR / متن ───
    if show_qr:
        buttons.append([InlineKeyboardButton(
            text=t('config_text_c761ef46d2', lang),
            callback_data=f"show_text_{order_id}",
            style="primary"
        )])
    else:
        buttons.append([
            InlineKeyboardButton(
                text=t('config_text_c761ef46d2', lang),
                callback_data=f"show_text_{order_id}",
                style="primary"
            ),
            InlineKeyboardButton(
                text=t('subscription_qr_eae786b99a', lang),
                callback_data=f"sub_qr_{order_id}",
                style="primary"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text=t('change_subscription_link_85827e0359', lang),
            callback_data=f"change_link_{order_id}_{int(show_qr)}",
            style="primary",
        ),
        InlineKeyboardButton(
            text=t('daily_usage_stats_3f4c8ed1b6', lang),
            callback_data=f"daily_usage_{order_id}_{int(show_qr)}",
            style="primary",
        )
    ])

    if telegram_proxy_url is None and order_id in CONFIG_LINKS_CACHE:
        for l in CONFIG_LINKS_CACHE[order_id].get('links', []):
            if _is_telegram_proxy(l):
                telegram_proxy_url = l
                break

    if wireguard_available and telegram_proxy_url:
        wg_btn = InlineKeyboardButton(
            text=t('wireguard_config_a481860ec9', lang),
            callback_data=f"wireguard_config_{order_id}",
            style="danger",
        )
        proxy_btn = InlineKeyboardButton(
            text=t('telegram_proxy_4e5f4306b8', lang),
            url=telegram_proxy_url.strip(),
            style="primary",
        )
        buttons.append([wg_btn, proxy_btn])
    elif wireguard_available:
        buttons.append([InlineKeyboardButton(
            text=t('wireguard_config_a481860ec9', lang),
            callback_data=f"wireguard_config_{order_id}",
            style="danger",
        )])
    elif telegram_proxy_url:
        buttons.append([InlineKeyboardButton(
            text=t('telegram_proxy_4e5f4306b8', lang),
            url=telegram_proxy_url.strip(),
            style="primary",
        )])

    # ─── ردیف 3: راهنمای اتصال هر پلتفرم ───
    buttons.append([
        InlineKeyboardButton(
            text=t('android_6a43b1c1c3', lang),
            callback_data=f"platform_android_{order_id}_{int(show_qr)}"
        ),
        InlineKeyboardButton(
            text=t('ios_4891573c24', lang),
            callback_data=f"platform_ios_{order_id}_{int(show_qr)}"
        ),
        InlineKeyboardButton(
            text=t('windows_e8b5ae3e54', lang),
            callback_data=f"platform_windows_{order_id}_{int(show_qr)}"
        )
    ])

    # ─── ردیف 4: کانفیگ‌های من | منوی اصلی ───
    buttons.append([
        InlineKeyboardButton(
            text=t('my_configs_41f10fc06f', lang),
            callback_data="my_configs",
        ),
        InlineKeyboardButton(
            text=t('main_menu_0cdd07a7cc', lang),
            callback_data="back_to_main",
            style="primary",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


PLATFORM_GUIDES = {
    "android": {
        "url": "https://github.com/2dust/v2rayng",
        "fa_name": "اندروید (v2rayNG)",
        "en_name": "Android (v2rayNG)",
        "fa_steps": (
            "۱) برنامهٔ <b>v2rayNG</b> را از لینک زیر دانلود و نصب کن.\n"
            "۲) لینک اشتراک را از صفحهٔ کانفیگ کپی کن.\n"
            "۳) در v2rayNG روی منوی ☰ بزن و وارد بخش <b>Subscriptions</b> شو.\n"
            "۴) روی <b>＋</b> بزن، لینک را در قسمت آدرس وارد کن و ذخیره کن.\n"
            "۵) از منوی ⋮ گزینهٔ <b>Update subscription</b> را بزن.\n"
            "۶) یکی از سرورها را انتخاب کن و دکمهٔ اتصال را بزن ✅"
        ),
        "en_steps": (
            "1) Download and install <b>v2rayNG</b> from the link below.\n"
            "2) Copy the subscription link from the config page.\n"
            "3) In v2rayNG, open ☰ and go to <b>Subscriptions</b>.\n"
            "4) Tap <b>＋</b>, enter the link, and save it.\n"
            "5) From ⋮, choose <b>Update subscription</b>.\n"
            "6) Select a server and tap connect ✅"
        ),
    },
    "ios": {
        "url": "https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690",
        "fa_name": "آیفون (V2Box)",
        "en_name": "iPhone (V2Box)",
        "fa_steps": (
            "۱) برنامهٔ <b>V2Box</b> را از App Store نصب کن.\n"
            "۲) لینک اشتراک را از صفحهٔ کانفیگ کپی کن.\n"
            "۳) در V2Box روی <b>＋</b> بزن و افزودن کانفیگ از طریق URL را انتخاب کن.\n"
            "۴) لینک را وارد و ذخیره کن؛ اگر اجازهٔ دسترسی به کلیپ‌بورد خواسته شد، تأیید کن.\n"
            "۵) فهرست سرورها را به‌روزرسانی کن، یک سرور را انتخاب و اتصال را فعال کن ✅"
        ),
        "en_steps": (
            "1) Install <b>V2Box</b> from the App Store.\n"
            "2) Copy the subscription link from the config page.\n"
            "3) In V2Box, tap <b>＋</b> and choose the URL import option.\n"
            "4) Enter the link and save it; allow clipboard access if prompted.\n"
            "5) Refresh the server list, select a server, and connect ✅"
        ),
    },
    "windows": {
        "url": "https://github.com/2dust/v2rayN",
        "fa_name": "ویندوز (v2rayN)",
        "en_name": "Windows (v2rayN)",
        "fa_steps": (
            "۱) برنامهٔ <b>v2rayN</b> را از لینک زیر دانلود و نصب کن.\n"
            "۲) لینک اشتراکت را از صفحهٔ کانفیگ کپی کن.\n"
            "۳) منوی <b>Subscription group settings</b> را باز کن.\n"
            "۴) یک ردیف جدید بساز، لینک را در خانهٔ <b>URL</b> قرار بده و <b>OK</b> کن.\n"
            "۵) از منوی <b>Subscription</b> گزینهٔ <b>Update subscription</b> را بزن.\n"
            "۶) سرور را انتخاب کن و اتصال را فعال کن ✅"
        ),
        "en_steps": (
            "1) Download and install <b>v2rayN</b> from the link below.\n"
            "2) Copy your subscription link from the config page.\n"
            "3) Open <b>Subscription group settings</b>.\n"
            "4) Add a row, paste the link into <b>URL</b>, and click <b>OK</b>.\n"
            "5) From <b>Subscription</b>, choose <b>Update subscription</b>.\n"
            "6) Select a server and enable the connection ✅"
        ),
    },
}


def _parse_platform_callback(callback: CallbackQuery):
    try:
        parts = callback.data.split("_")
        if (
            len(parts) != 4
            or parts[0] != "platform"
            or parts[1] not in (*PLATFORM_GUIDES, "back")
        ):
            return None, False
        order_id = int(parts[2])
        show_qr_value = int(parts[3])
        if show_qr_value not in (0, 1):
            return None, False
        return order_id, bool(show_qr_value)
    except (AttributeError, IndexError, TypeError, ValueError):
        return None, False


async def show_platform_guide(callback: CallbackQuery, platform: str):
    """نمایش راهنمای اتصال و نگهداری اطلاعات صفحهٔ کانفیگ مبدأ."""
    lang = get_user(callback.from_user.id).get("lang", "fa")
    guide = PLATFORM_GUIDES[platform]
    order_id, show_qr = _parse_platform_callback(callback)
    if order_id is None:
        await callback.answer(
            t('could_not_return_to_the_conf_07a2fd0746', lang),
            show_alert=True,
        )
        return

    order = orders.get(str(order_id))
    if not order or order.get("user_id") != callback.from_user.id or not order.get("config_link"):
        await callback.answer(
            t('config_not_found_3169491e56', lang),
            show_alert=True,
        )
        return

    title = guide["fa_name"] if lang == "fa" else guide["en_name"]
    steps = guide["fa_steps"] if lang == "fa" else guide["en_steps"]
    text = (
        t('b_how_to_connect_with_b_acec0ad9bc', lang, fa_parts=lambda: (f'{title}', f'{steps}'), en_parts=lambda: (f'{title}', f'{steps}'))
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('download_app_4773da8a3c', lang),
            url=guide["url"],
            style="success",
        )],
        [
            InlineKeyboardButton(
                text=t('back_to_config_407e2c5446', lang),
                callback_data=f"platform_back_{order_id}_{int(show_qr)}",
            ),
            InlineKeyboardButton(
                text=t('main_menu_0cdd07a7cc', lang),
                callback_data="back_to_main",
                style="primary",
            ),
        ],
    ])

    try:
        await callback.message.delete()
    except Exception as e:
        logger.warning(f"Error deleting the config page before showing the guide: {e}")
    bot = get_bot()
    if bot:
        await bot.send_message(
            callback.message.chat.id,
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("platform_android_"))
async def platform_android(callback: CallbackQuery):
    await show_platform_guide(callback, "android")


@router.callback_query(F.data.startswith("platform_ios_"))
async def platform_ios(callback: CallbackQuery):
    await show_platform_guide(callback, "ios")


@router.callback_query(F.data.startswith("platform_windows_"))
async def platform_windows(callback: CallbackQuery):
    await show_platform_guide(callback, "windows")


def get_config_caption(
    order_id: int,
    volume: Union[int, float],
    days: int,
    price: int,
    config_link: str,
    lang: str = "fa",
    traffic_info: str = "",
    telegram_proxy_url: Optional[str] = None
) -> str:
    """ساخت کپشن با اطلاعات کامل + ترافیک"""
    order = orders.get(str(order_id))
    is_test = _is_test_order(order)
    category_name = ""
    category_name_en = ""

    if order:
        category_name = order.get('category_name', '') or ''
        category_name_en = order.get('category_name_en', '') or ''

    # ─── عنوان ───
    if is_test:
        test_emoji, test_name = get_test_service_display(lang)
        title = f"{test_emoji} {html.escape(test_name)}"
    elif category_name or category_name_en:
        title_emoji = premium_emoji('globe', '🌐')

        if lang == "fa":
            clean_name = category_name
            if clean_name.startswith(t('config_2056c9d609', lang)):
                clean_name = clean_name[len(t('config_2056c9d609', lang)):].strip()
            clean_name = clean_name.lstrip(" -—_:").strip()

            if clean_name:
                title = t('config_725587741f', lang, fa_parts=lambda: (f'{title_emoji}', f'{clean_name}'))
            else:
                title = t('your_config_68d7027629', lang, fa_parts=lambda: (f'{title_emoji}',))
        else:
            display_name = category_name_en if category_name_en else category_name
            clean_name = display_name
            for prefix in ["Config ", "config ", "Config-", "Config_"]:
                if clean_name.startswith(prefix):
                    clean_name = clean_name[len(prefix):]
                    break
            if clean_name.lower().startswith("config"):
                clean_name = clean_name[len("config"):].strip()
            clean_name = clean_name.lstrip(" -—_:").strip()

            if clean_name:
                title = t('config_725587741f', lang, en_parts=lambda: (f'{title_emoji}', f'{clean_name}'))
            else:
                title = t('your_config_68d7027629', lang, en_parts=lambda: (f'{title_emoji}',))
    else:
        title_emoji = premium_emoji('config', '📦')
        title = t('your_config_68d7027629', lang, fa_parts=lambda: (f'{title_emoji}',), en_parts=lambda: (f'{title_emoji}',))

    # ─── حجم ───
    if volume is None or volume == 0 or (isinstance(volume, float) and volume < 0.001):
        volume_display = t('unlimited_0d936642fc', lang)
    elif is_test:
        volume_display = format_volume(volume * 1024, is_test=True)
    else:
        volume_display = format_volume(volume, is_test=False)

    if lang == "fa":
        volume_display = volume_display.replace("GB", t("i18n_unit_gig", lang)).replace("MB", t("i18n_unit_mb", lang))

    # ─── لینک ───
    link_emoji = premium_emoji('link', '🔗')

    caption = t('b_subscription_link_b_a_href_c10939ae48', lang, fa_parts=lambda: (f'{title}', f'{volume_display}', f'{traffic_info}', f'{link_emoji}', f'{config_link}', f'{config_link}'), en_parts=lambda: (f'{title}', f'{volume_display}', f'{traffic_info}', f'{link_emoji}', f'{config_link}', f'{config_link}'))
    if telegram_proxy_url:
        caption += t('b_dedicated_telegram_proxy_b_aec84a447c', lang, fa_parts=lambda: (f'{telegram_proxy_url.strip()}',), en_parts=lambda: (f'{telegram_proxy_url.strip()}',))

    return caption


async def send_config_with_qr_option(
    chat_id: int,
    order_id: int,
    volume: Union[int, float],
    days: int,
    price: int,
    config_link: str,
    lang: str = "fa"
):
    """ارسال کانفیگ با QR Code"""
    bot = get_bot()
    if chat_id not in user_states:
        user_states[chat_id] = {}

    user_states[chat_id]['current_config'] = {
        'order_id': order_id,
        'volume': volume,
        'days': days,
        'price': price,
        'config_link': config_link
    }

    order = orders.get(str(order_id))
    is_test = _is_test_order(order)
    email = get_order_client_email(order) if order else None

    # ─── دریافت اطلاعات ترافیک از پنل ───
    traffic_info = ""
    if email and is_senai_panel_enabled():
        try:
            client_info = await xui_get_client_info(email)
            if client_info:
                traffic_data = await xui_get_client_traffic(email)
                traffic_info = format_traffic_info(client_info, traffic_data, lang)
        except Exception as e:
            logger.error(f"Error fetching traffic for caption: {e}")

    wireguard_available = await _order_has_wireguard(order_id)
    telegram_proxy_url = await _get_order_telegram_proxy(order_id)

    # ─── ساخت کپشن ───
    caption = get_config_caption(
        order_id, volume, days, price, config_link, lang, traffic_info,
        telegram_proxy_url=telegram_proxy_url
    )

    # ─── پیام تست ───
    if is_test:
        test_emoji, test_name = get_test_service_display(lang)
        light_emoji = premium_emoji('light', '💡')
        home_emoji = premium_emoji('home', '🏠')
        note_args = (test_emoji, html.escape(test_name), light_emoji, home_emoji)
        caption += t('test_service_note', lang, fa_parts=lambda: note_args, en_parts=lambda: note_args)

    # ─── ارسال ───
    try:
        qr_img = generate_qr_code(config_link, order_id)
        if bot:
            await bot.send_photo(
                chat_id,
                qr_img,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=get_config_view_keyboard(
                    order_id, show_qr=True, lang=lang,
                    wireguard_available=wireguard_available,
                    telegram_proxy_url=telegram_proxy_url,
                )
            )
        logger.info(f"QR Code for order #{order_id} to user {chat_id} sent")
    except Exception as e:
        logger.error(f"Error sending QR Code: {e}")
        if bot:
            await bot.send_message(
                chat_id,
                caption,
                parse_mode=ParseMode.HTML,
                reply_markup=get_config_view_keyboard(
                    order_id, show_qr=False, lang=lang,
                    wireguard_available=wireguard_available,
                    telegram_proxy_url=telegram_proxy_url,
                )
            )


async def _render_single_config_text(
    callback: CallbackQuery,
    order_id: int,
    order: dict,
    lang: str,
):
    """نمایش صفحه متنی کانفیگ با ویرایش پیام قبلی (بدون تولید خودکار عکس QR)."""
    user_id = callback.from_user.id
    if user_id not in user_states:
        user_states[user_id] = {}
    for k in ("is_extend", "extend_order_id", "current_volume", "current_days"):
        user_states[user_id].pop(k, None)

    volume = order.get("volume", 0)
    days = order.get("days", 0)
    price = order.get("price", 0)
    config_link = order["config_link"]

    user_states[user_id]["current_config"] = {
        "order_id": order_id,
        "volume": volume,
        "days": days,
        "price": price,
        "config_link": config_link,
    }

    traffic_info = ""
    email = get_order_client_email(order)
    if email and is_senai_panel_enabled():
        try:
            client_info = await xui_get_client_info(email)
            if client_info:
                traffic_data = await xui_get_client_traffic(email)
                traffic_info = format_traffic_info(client_info, traffic_data, lang)
        except Exception as e:
            logger.error(f"Error retrieving traffic information for config view: {e}")

    telegram_proxy_url = await _get_order_telegram_proxy(order_id)
    caption = get_config_caption(
        order_id,
        volume,
        days,
        price,
        config_link,
        lang,
        traffic_info,
        telegram_proxy_url=telegram_proxy_url,
    )
    if _is_test_order(order):
        test_emoji, test_name = get_test_service_display(lang)
        light_emoji = premium_emoji('light', '💡')
        home_emoji = premium_emoji('home', '🏠')
        note_args = (test_emoji, html.escape(test_name), light_emoji, home_emoji)
        caption += t('test_service_note', lang, fa_parts=lambda: note_args, en_parts=lambda: note_args)

    wireguard_available = await _order_has_wireguard(order_id)
    reply_markup = get_config_view_keyboard(
        order_id,
        show_qr=False,
        lang=lang,
        wireguard_available=wireguard_available,
        telegram_proxy_url=telegram_proxy_url,
    )

    try:
        await callback.message.edit_text(
            caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except Exception as e:
        err = str(e)
        if "message is not modified" in err:
            pass
        else:
            try:
                await callback.message.delete()
            except Exception:
                pass
            bot = get_bot()
            if bot:
                await bot.send_message(
                    callback.message.chat.id,
                    caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )


@router.callback_query(F.data.startswith("platform_back_"))
async def platform_back_to_config(callback: CallbackQuery):
    """بازسازی صفحهٔ کانفیگ قبلی از روی شناسه و حالت QR/متن."""
    lang = get_user(callback.from_user.id).get("lang", "fa")
    order_id, show_qr = _parse_platform_callback(callback)
    if order_id is None:
        await callback.answer(
            t('config_not_found_3169491e56', lang),
            show_alert=True,
        )
        return

    order = orders.get(str(order_id))
    if not order or order.get("user_id") != callback.from_user.id or not order.get("config_link"):
        await callback.answer(
            t('config_not_found_3169491e56', lang),
            show_alert=True,
        )
        return

    if show_qr:
        try:
            await callback.message.delete()
        except Exception as e:
            logger.warning(f"Error deleting the guide while returning to the config: {e}")
        await send_config_with_qr_option(
            callback.message.chat.id,
            order_id,
            order.get("volume", 0),
            order.get("days", 0),
            order.get("price", 0),
            order["config_link"],
            lang,
        )
    else:
        await _render_single_config_text(callback, order_id, order, lang)
    await callback.answer()


async def _render_config_page(callback: CallbackQuery, order_id: int, page: int = 0):
    """نمایش صفحه‌بندی‌شده کانفیگ - بدون هدر و بدون دکمه بروزرسانی"""
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')

    order = orders.get(str(order_id))
    if not order or order.get("user_id") != user_id:
        await callback.answer(t('config_not_found_3169491e56', lang), show_alert=True)
        return

    links, email = await _get_cached_config_links(order_id)
    if not links:
        await callback.answer(t('failed_to_fetch_links_79754f24f0', lang), show_alert=True)
        return

    total_links = len(links)
    total_pages = (total_links + CONFIG_PAGE_SIZE - 1) // CONFIG_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * CONFIG_PAGE_SIZE
    end_idx = min(start_idx + CONFIG_PAGE_SIZE, total_links)
    page_links = links[start_idx:end_idx]

    if lang == "fa":
        page_badge = f" ({page + 1}/{total_pages})" if total_pages > 1 else ""
        body = f"🔗 <b>لینک‌های اتصال{page_badge}</b>\n━━━━━━━━━━━━━━━\n\n"
    else:
        page_badge = f" ({page + 1}/{total_pages})" if total_pages > 1 else ""
        body = f"🔗 <b>Connection Links{page_badge}</b>\n━━━━━━━━━━━━━━━\n\n"

    for i, link in enumerate(page_links):
        abs_idx = start_idx + i + 1
        is_wireguard = link.strip().startswith("[Interface]")
        is_proxy = _is_telegram_proxy(link)

        if is_wireguard:
            protocol = "WireGuard"
            proto_icon = "🔴"
        elif is_proxy:
            protocol = "Telegram Proxy"
            proto_icon = "🔵"
        elif "://" in link:
            protocol = link.split("://")[0].upper()
            proto_icon = "⚡" if protocol == "VLESS" else ("🌐" if protocol == "VMESS" else "🛡")
        else:
            protocol = "Config"
            proto_icon = "🔗"

        display_link = link

        # پروکسی تلگرام: لینک مستقیم و بدون تگ کد
        if is_proxy:
            proxy_url_clean = link.strip()
            proxy_url_escaped = html.escape(proxy_url_clean)
            code_tag = (
                f'<a href="{proxy_url_escaped}">{proxy_url_escaped}</a>'
            )
        else:
            code_tag = f"<code>{html.escape(display_link)}</code>"

        body += (
            f"{proto_icon} <b>{abs_idx}. {protocol}</b>\n"
            f"{code_tag}\n\n"
        )

    body += "━━━━━━━━━━━━━━━"
    text = body.strip()

    # دکمه‌های ناوبری (فقط وقتی بیش از یک صفحه باشد)
    buttons = []
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(
                text="⬅️ قبلی" if lang == "fa" else "⬅️ Prev",
                callback_data=f"show_text_page_{order_id}_{page - 1}"
            ))
        nav_row.append(InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="noop"
        ))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                text="بعدی ➡️" if lang == "fa" else "Next ➡️",
                callback_data=f"show_text_page_{order_id}_{page + 1}"
            ))
        buttons.append(nav_row)

    # دکمه دریافت QR اختصاصی برای تک کانفیگ همین صفحه
    qr_buttons = []
    for local_idx, link_item in enumerate(page_links):
        abs_idx = start_idx + local_idx + 1
        is_wg = link_item.strip().startswith("[Interface]")
        qr_buttons.append(InlineKeyboardButton(
            text=f"📷 QR کانفیگ {abs_idx}" if lang == "fa" else f"📷 QR #{abs_idx}",
            callback_data=f"show_single_qr_{order_id}_{start_idx + local_idx}"
        ))
        if is_wg:
            qr_buttons.append(InlineKeyboardButton(
                text="📁 دانلود فایل WireGuard" if lang == "fa" else "📁 Download WireGuard File",
                callback_data=f"wireguard_file_{order_id}"
            ))

    if qr_buttons:
        for btn_chunk in [qr_buttons[i:i+2] for i in range(0, len(qr_buttons), 2)]:
            buttons.append(btn_chunk)

    # ردیف کپی تک کانفیگ صفحه جاری
    COPY_LIMIT = 200
    for local_idx, link_item in enumerate(page_links):
        abs_idx = start_idx + local_idx + 1
        clean_target = link_item.strip()
        if len(clean_target) <= COPY_LIMIT:
            buttons.append([
                InlineKeyboardButton(
                    text=f"📋 کپی کانفیگ {abs_idx}" if lang == "fa" else f"📋 Copy Config {abs_idx}",
                    copy_text=CopyTextButton(text=clean_target)
                )
            ])

    # دکمه دریافت تمام لینک‌ها در یک فایل متنی
    buttons.append([
        InlineKeyboardButton(
            text="📑 کپی همه لینک‌ها یکجا (فایل)" if lang == "fa" else "📑 Copy All Links (File)",
            callback_data=f"copy_all_links_file_{order_id}"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text=t('back_to_config_f15bf8e1cd', lang),
            callback_data=f"view_config_{order_id}",
            style="primary"
        ),
        InlineKeyboardButton(
            text=t('main_menu_0cdd07a7cc', lang),
            callback_data="back_to_main",
            style="danger"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    # پاک‌سازی فایل‌های دانلود قبلی
    await _delete_downloaded_files(user_id, callback.message.chat.id)

    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Error editing the config page: {e}")
            try:
                await callback.message.delete()
            except Exception:
                pass
            bot = get_bot()
            if bot:
                await bot.send_message(
                    callback.message.chat.id,
                    text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )

    await safe_answer(callback)


@router.callback_query(F.data.startswith("copy_all_links_file_"))
async def copy_all_links_file(callback: CallbackQuery):
    """ارسال تمام لینک‌های کانفیگ به صورت یک فایل متنی دانلودشدنی با دکمه بازگشت به صفحه کانفیگ"""
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    bot = get_bot()

    try:
        order_id = int(callback.data.split("_")[-1])
    except (IndexError, ValueError):
        await callback.answer(t('i18n_order_process_error', lang), show_alert=True)
        return

    order = orders.get(str(order_id))
    if not order or order.get("user_id") != user_id:
        await callback.answer(t('config_not_found_3169491e56', lang), show_alert=True)
        return

    links, email = await _get_cached_config_links(order_id)
    if not links:
        await callback.answer(t('failed_to_fetch_links_79754f24f0', lang), show_alert=True)
        return

    all_links_text = "\n\n".join(links)
    file_buffer = BytesIO(all_links_text.encode('utf-8'))
    filename = f"configs_{order_id}.txt"
    input_file = BufferedInputFile(file_buffer.getvalue(), filename=filename)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=t('back_to_config_f15bf8e1cd', lang),
                callback_data=f"back_to_config_page_{order_id}",
                style="primary"
            ),
            InlineKeyboardButton(
                text=t('main_menu_0cdd07a7cc', lang),
                callback_data="back_to_main_from_file",
                style="danger"
            )
        ]
    ])

    caption = (
        f"📄 <b>فایل تمام کانفیگ‌های سفارش #{order_id}</b>\n"
        f"تعداد کل کانفیگ‌ها: <code>{len(links)}</code>\n\n"
        f"<i>می‌توانید فایل بالا را ذخیره یا باز کنید و لینک‌ها را کامل کپی نمایید.</i>"
        if lang == "fa" else
        f"📄 <b>All configs for order #{order_id}</b>\n"
        f"Total configs: <code>{len(links)}</code>\n\n"
        f"<i>You can save or open the file above to copy all links easily.</i>"
    )

    try:
        try:
            await callback.message.delete()
        except Exception:
            pass

        if bot:
            sent_msg = await bot.send_document(
                chat_id=callback.message.chat.id,
                document=input_file,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
            track_downloaded_file(user_id, sent_msg.message_id, callback.message.chat.id)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error sending all links file: {e}")
        await callback.answer(
            "خطا در ایجاد فایل کانفیگ‌ها." if lang == "fa" else "Error generating configs file.",
            show_alert=True
        )


@router.callback_query(F.data.startswith("back_to_config_page_"))
async def back_to_config_page(callback: CallbackQuery):
    """حذف پیام فایل و بازگشت به صفحه نمایش کانفیگ‌ها"""
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')

    try:
        order_id = int(callback.data.split("_")[-1])
    except (IndexError, ValueError):
        await callback.answer(t('i18n_order_process_error', lang), show_alert=True)
        return

    await _delete_downloaded_files(user_id, callback.message.chat.id)
    try:
        await callback.message.delete()
    except Exception:
        pass

    await _render_config_page(callback, order_id, page=0)


@router.callback_query(F.data == "back_to_main_from_file")
async def back_to_main_from_file(callback: CallbackQuery):
    """حذف فایل دانلودی و بازگشت به منوی اصلی"""
    user_id = callback.from_user.id
    await _delete_downloaded_files(user_id, callback.message.chat.id)
    try:
        await callback.message.delete()
    except Exception:
        pass
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "back_to_main"):
        await main_mod.back_to_main(callback)


@router.callback_query(F.data.regexp(r'^show_text_\d+$'))
async def show_config_text(callback: CallbackQuery):
    """هندلر دکمه متن کانفیگ - نمایش صفحه اول بدون هدر"""
    order_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    if log_system:
        asyncio.create_task(log_system.log_config_view(user_id, order_id, "Show Text View"))

    await _render_config_page(callback, order_id, page=0)


@router.callback_query(F.data.regexp(r"^wireguard_config_\d+$"))
async def show_wireguard_config(callback: CallbackQuery):
    """نمایش کانفیگ WireGuard و دکمه بازگشت به صفحه کانفیگ."""
    lang = get_user(callback.from_user.id).get("lang", "fa")
    order_id = int(callback.data.split("_")[2])
    matches = await _get_order_wireguard_clients(order_id)
    if not matches:
        await callback.answer(
            t('wireguard_config_not_found_f_fba79541b5', lang),
            show_alert=True,
        )
        return

    wireguard = matches[0]
    try:
        config_text = build_wireguard_config(
            wireguard["inbound"],
            wireguard["client"],
            app_config.SENAI_PANEL_URL,
        )
    except (TypeError, ValueError) as error:
        logger.error(
            'Failed to generate WireGuard text for order #%s: %s',
            order_id,
            error,
            exc_info=True,
        )
        await callback.answer(
            t('failed_to_build_wireguard_con_532e1858a7', lang),
            show_alert=True,
        )
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t('download_wireguard_file_f04b2b2a8d', lang),
            callback_data=f"wireguard_file_{order_id}",
            style="success",
        )],
        [
            InlineKeyboardButton(
                text=t('back_to_config_f15bf8e1cd', lang),
                callback_data=f"view_config_{order_id}",
                style="primary",
            ),
            InlineKeyboardButton(
                text=t('main_menu_0cdd07a7cc', lang),
                callback_data="back_to_main",
                style="danger",
            ),
        ],
    ])

    try:
        await callback.message.delete()
    except Exception:
        pass

    bot = get_bot()
    if bot:
        qr_img = generate_wireguard_qr_code(config_text, order_id, order_data={'lang': lang})
        await bot.send_photo(
            callback.message.chat.id,
            qr_img,
            caption=(
                t('b_wireguard_configuration_b_30ebbaeb87', lang, fa_parts=lambda: (f'{html.escape(config_text)}',), en_parts=lambda: (f'{html.escape(config_text)}',))
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^wireguard_file_\d+$"))
async def send_wireguard_config_file(callback: CallbackQuery):
    """ارسال فایل متنی .conf برای کانفیگ WireGuard."""
    user_id = callback.from_user.id
    lang = get_user(user_id).get("lang", "fa")
    order_id = int(callback.data.split("_")[2])
    matches = await _get_order_wireguard_clients(order_id)
    if not matches:
        await callback.answer(
            t('wireguard_config_not_found_f_fba79541b5', lang),
            show_alert=True,
        )
        return

    wireguard = matches[0]
    try:
        config_text = build_wireguard_config(
            wireguard["inbound"],
            wireguard["client"],
            app_config.SENAI_PANEL_URL,
        )
    except (TypeError, ValueError) as error:
        logger.error(
            'Failed to generate WireGuard file for order #%s: %s',
            order_id,
            error,
            exc_info=True,
        )
        await callback.answer(
            t('failed_to_build_wireguard_con_532e1858a7', lang),
            show_alert=True,
        )
        return

    document = BufferedInputFile(
        config_text.encode("utf-8"),
        filename=f"wireguard-order-{order_id}.conf",
    )
    bot = get_bot()
    if bot:
        sent_msg = await bot.send_document(
            callback.message.chat.id,
            document,
            caption=(
                t('wireguard_conf_file_for_orde_09c37e6f80', lang, fa_parts=lambda: (f'{order_id}',), en_parts=lambda: (f'{order_id}',))
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=t('back_to_config_f15bf8e1cd', lang),
                    callback_data=f"view_config_{order_id}",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text=t('main_menu_0cdd07a7cc', lang),
                    callback_data="back_to_main",
                    style="danger",
                ),
            ]]),
        )
        track_downloaded_file(user_id, sent_msg.message_id, callback.message.chat.id)
    await callback.answer()


@router.callback_query(F.data.startswith("show_text_page_"))
async def show_config_text_page(callback: CallbackQuery):
    """هندلر تعویض صفحه کانفیگ"""
    parts = callback.data.split("_")
    order_id = int(parts[3])
    page = int(parts[4])

    await _render_config_page(callback, order_id, page=page)


@router.callback_query(F.data.startswith("show_text_refresh_"))
async def show_config_text_refresh(callback: CallbackQuery):
    """هندلر بازخوانی اجباری کانفیگ از پنل"""
    parts = callback.data.split("_")
    order_id = int(parts[3])
    page = int(parts[4])
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')

    if order_id in CONFIG_LINKS_CACHE:
        del CONFIG_LINKS_CACHE[order_id]

    await callback.answer(t('updating_e72a44bb4f', lang))
    await _render_config_page(callback, order_id, page=page)


@router.callback_query(F.data.startswith("show_single_qr_"))
async def show_single_qr(callback: CallbackQuery):
    """تولید و نمایش QR Code اختصاصی برای یک کانفیگ خاص بدون متن زیر آن"""
    user_id = callback.from_user.id
    lang = get_user(user_id).get('lang', 'fa')
    parts = callback.data.split("_")
    try:
        order_id = int(parts[3])
        link_index = int(parts[4])
    except (IndexError, ValueError):
        await callback.answer(t('i18n_order_process_error', lang), show_alert=True)
        return

    links, _ = await _get_cached_config_links(order_id)
    if not links or link_index >= len(links):
        await callback.answer(t('config_not_found_3169491e56', lang), show_alert=True)
        return

    target_link = links[link_index]

    if log_system:
        asyncio.create_task(log_system.log_config_view(user_id, order_id, f"Single QR #{link_index + 1}"))

    try:
        if target_link.strip().startswith("[Interface]"):
            qr_img = generate_wireguard_qr_code(target_link, order_id, order_data={'lang': lang})
        else:
            qr_img = generate_qr_code(target_link, order_id)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t('back_to_links', lang),
                    callback_data=f"show_text_page_{order_id}_{link_index // CONFIG_PAGE_SIZE}",
                    style="primary"
                ),
                InlineKeyboardButton(
                    text=t('main_menu_0cdd07a7cc', lang),
                    callback_data="back_to_main",
                    style="danger"
                )
            ]
        ])

        try:
            await callback.message.delete()
        except Exception:
            pass

        bot = get_bot()
        if bot:
            await bot.send_photo(
                callback.message.chat.id,
                qr_img,
                caption=None,
                reply_markup=keyboard
            )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in show_single_qr: {e}", exc_info=True)
        await callback.answer(t('error_generating_qr_code_74d85ad903', lang), show_alert=True)


@router.callback_query(F.data.startswith("sub_qr_") | F.data.startswith("show_qr_"))
async def show_subscription_qr(callback: CallbackQuery):
    """تولید و ارسال فقط تصویر QR Code اشتراک بدون هیچ متن زیر آن"""
    user_id = callback.from_user.id
    try:
        parts = callback.data.split("_")
        order_id = int(parts[-1])
    except (IndexError, ValueError):
        await callback.answer(t('i18n_order_process_error', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    lang = get_user(user_id).get('lang', 'fa')
    order = orders.get(str(order_id))
    if not order or order.get('user_id') != user_id or not order.get('config_link'):
        await callback.answer(t('config_not_found_3169491e56', lang), show_alert=True)
        return

    if log_system:
        asyncio.create_task(log_system.log_config_view(user_id, order_id, "Subscription QR"))

    try:
        sub_link = order.get('sub_link') or order.get('config_link')
        qr_img = generate_qr_code(sub_link, order_id)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t('back_to_config_f15bf8e1cd', lang),
                    callback_data=f"view_config_{order_id}",
                    style="primary"
                ),
                InlineKeyboardButton(
                    text=t('main_menu_0cdd07a7cc', lang),
                    callback_data="back_to_main",
                    style="danger"
                )
            ]
        ])

        try:
            await callback.message.delete()
        except Exception:
            pass

        bot = get_bot()
        if bot:
            await bot.send_photo(
                callback.message.chat.id,
                qr_img,
                caption=None,
                reply_markup=keyboard
            )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in show_subscription_qr: {e}", exc_info=True)
        await callback.answer(t('error_generating_qr_code_74d85ad903', lang), show_alert=True)


@router.callback_query(F.data == "my_configs")
async def my_configs(callback: CallbackQuery):
    """نمایش کانفیگ‌های کاربر با اطلاعات زنده از پنل (بدون دسته‌بندی؛ بازگشت به ظاهر قبلی)"""
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    lang = get_user(user_id).get('lang', 'fa')
    user_state = user_states.get(user_id, {})
    for k in ("is_extend", "extend_order_id", "current_volume", "current_days"):
        user_state.pop(k, None)

    try:
        await sync_user_configs(user_id)
    except Exception as e:
        logger.warning(f"Error auto-syncing configs for user {user_id}: {e}")

    valid_orders = get_valid_orders()
    configs_list = [
        o for o in valid_orders.values()
        if o.get('user_id') == user_id
        and o.get('status') in ("approved", "inactive")
        and o.get('config_link')
    ]

    if log_system:
        asyncio.create_task(log_system.log_user_action(
            user_id, "Viewed configurations", f"Count: {len(configs_list)}"
        ))

    RLM = "\u200F"
    LRM = "\u200E"
    test_emoji, test_name = get_test_service_display(lang)

    def get_category_name(order: dict) -> str:
        if lang == "en":
            name = order.get('category_name_en')
            if name and str(name).strip() and not any('\u0600' <= c <= '\u06FF' for c in str(name)):
                return str(name).strip()
        else:
            name = order.get('category_name')
            if name and str(name).strip():
                return str(name).strip()

        cat_id = order.get('category_id')
        if cat_id:
            for cat in READY_PACKAGES.get('categories', []):
                if cat.get('id') == cat_id:
                    if lang == "en":
                        en_name = cat.get('name_en') or ''
                        if en_name and not any('\u0600' <= c <= '\u06FF' for c in en_name):
                            return en_name
                    return cat.get('name') or ""
        if lang == "en":
            return order.get('category_name_en') or order.get('category_name') or ""
        return order.get('category_name') or ""

    def build_category_label(raw_name: str) -> str:
        name = (raw_name or "").strip()
        if lang == "fa":
            if name.startswith("کانفیگ"):
                name = name[len("کانفیگ"):].strip()
            name = name.lstrip("·-—: ").strip()
            if name.startswith("اشتراک"):
                base = name
            elif not name:
                base = "اشتراک"
            else:
                base = f"اشتراک {name}"
            if len(base) > 18:
                base = base[:17].rstrip() + "…"
            return base
        if name.lower().startswith("config"):
            name = name[len("config"):].strip()
        name = name.lstrip("·-—: ").strip()
        if name.lower().endswith("sub") or name.lower().endswith("subscription"):
            base = name
        elif not name:
            base = "Subscription"
        else:
            base = f"{name} Sub"
        if len(base) > 18:
            base = base[:17].rstrip() + "…"
        return base

    def format_cfg_volume(vol_gb: float, is_test: bool, is_unlimited: bool) -> str:
        if (is_unlimited and not is_test) or vol_gb is None or vol_gb == 0:
            return "∞"
        mb = vol_gb * 1024
        if is_test:
            if mb >= 1024:
                gb = mb / 1024
                gb_str = f"{int(gb)}" if gb == int(gb) else f"{gb:.1f}"
                return f"{gb_str} گیگ" if lang == "fa" else f"{gb_str}GB"
            mb_str = f"{int(round(mb))}"
            return f"{mb_str} مگ" if lang == "fa" else f"{mb_str}MB"
        if vol_gb < 1:
            mb_str = f"{int(round(mb))}"
            return f"{mb_str} مگ" if lang == "fa" else f"{mb_str}MB"
        gb_str = f"{int(vol_gb)}" if vol_gb >= 100 else f"{vol_gb:.0f}"
        return f"{gb_str} گیگ" if lang == "fa" else f"{gb_str}GB"

    def format_time_left(expire_dt: datetime) -> str:
        delta = expire_dt - datetime.now()
        secs = int(delta.total_seconds())
        if secs <= 0:
            return "منقضی" if lang == "fa" else "Expired"
        if secs < 60:
            return f"{secs} ثانیه" if lang == "fa" else f"{secs}s"
        if secs < 3600:
            return f"{secs // 60} دقیقه" if lang == "fa" else f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600} ساعت" if lang == "fa" else f"{secs // 3600}h"
        days = secs // 86400
        return f"{days} روز" if lang == "fa" else f"{days}d"

    if not configs_list:
        await send_sticker(user_id, 'config', '📦')
        text = t(
            'you_have_no_active_configs_4e86fc3538',
            lang,
            fa_parts=lambda: (f"{premium_emoji('config', '📦')}",),
            en_parts=lambda: (f"{premium_emoji('config', '📦')}",),
        )
        no_config_buttons = [
            [InlineKeyboardButton(
                text=f"🛒 {t('buy_subscription_44cfc4a638', lang)}",
                callback_data="buy_service",
                style="success",
            )],
            [InlineKeyboardButton(
                text=f"{test_emoji} {test_name}",
                callback_data="get_test_service",
                style="primary",
            )],
            [InlineKeyboardButton(
                text=t('main_menu_0cdd07a7cc', lang),
                callback_data="back_to_main",
                style="danger",
            )],
        ]
        kb = InlineKeyboardMarkup(inline_keyboard=no_config_buttons)
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        await safe_answer(callback)
        return

    configs_list.sort(key=lambda x: str(x.get('date', '')), reverse=True)

    async def fetch_one(order: dict) -> dict:
        email = get_order_client_email(order)
        is_test = _is_test_order(order)
        status = order.get('status', 'approved')
        is_active = (status == 'approved')

        remaining_percent = None
        time_left_text = None
        volume_gb = order.get('volume', 0) or 0
        panel_is_active = None
        is_unlimited = (volume_gb == 0)

        if email and is_senai_panel_enabled() and is_active:
            try:
                client_info = await xui_get_client_info(email)
                if client_info:
                    panel_is_active = client_info.get('enable', True)
                    total_bytes = client_info.get('totalGB', 0)
                    total_gb = total_bytes / (1024 ** 3) if total_bytes else 0
                    if total_gb > 0:
                        volume_gb = total_gb
                        is_unlimited = False
                    else:
                        volume_gb = 0
                        is_unlimited = True

                    if not is_unlimited:
                        traffic = await xui_get_client_traffic(email)
                        up = (traffic.get('up', 0) if traffic else 0) / (1024 ** 3)
                        down = (traffic.get('down', 0) if traffic else 0) / (1024 ** 3)
                        used = up + down
                        if total_gb > 0:
                            used_pct = min(100, int((used / total_gb) * 100))
                            remaining_percent = max(0, 100 - used_pct)

                    expiry = client_info.get('expiryTime', 0)
                    if expiry > 0:
                        try:
                            expire_dt = datetime.fromtimestamp(expiry / 1000)
                            time_left_text = format_time_left(expire_dt)
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"⚠️ Error retrieving information {email}: {e}")

        if time_left_text is None and order.get('days'):
            d = order['days']
            time_left_text = f"{d} روز" if lang == "fa" else f"{d}d"

        return {
            'order': order,
            'is_test': is_test,
            'is_active': is_active and (panel_is_active is not False),
            'remaining_percent': remaining_percent,
            'time_left_text': time_left_text,
            'volume_gb': volume_gb,
            'is_unlimited': is_unlimited,
        }

    config_data = await asyncio.gather(*[fetch_one(c) for c in configs_list], return_exceptions=False)

    buttons = []
    if len(configs_list) > 1:
        buttons.append([InlineKeyboardButton(
            text="نمایش تمام ساب‌ها" if lang == "fa" else "Show All Configs",
            callback_data="show_all_my_configs",
            style="primary",
        )])

    for item in config_data:
        c = item['order']
        order_id = c['order_id']
        is_test = item['is_test']
        is_active = item['is_active']
        rem_pct = item['remaining_percent']
        time_left = item['time_left_text']
        vol = item['volume_gb']
        is_unlimited = item['is_unlimited']

        if not is_active:
            emoji = "🔴"
        elif is_test:
            emoji = test_emoji
        else:
            emoji = "💳"

        if is_test:
            label_parts = [test_name]
        else:
            cat_name = get_category_name(c)
            label_parts = [build_category_label(cat_name)]

        label_parts.append(format_cfg_volume(vol, is_test, is_unlimited))
        if not is_unlimited and rem_pct is not None:
            label_parts.append(f"{rem_pct}%")
        if time_left:
            label_parts.append(time_left)

        prefix_dir = RLM if lang == "fa" else LRM
        label = f"{prefix_dir}{emoji} " + " · ".join(label_parts)
        if len(label) > 64:
            label = label[:61] + "…"

        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"view_config_{order_id}",
            style="success" if is_active else "danger",
        )])

    buttons.append([InlineKeyboardButton(
        text="🛒 خرید سرویس" if lang == "fa" else "🛒 Buy Service",
        callback_data="buy_service",
        style="primary",
    )])
    buttons.append([InlineKeyboardButton(
        text=t('main_menu_0cdd07a7cc', lang),
        callback_data="back_to_main",
        style="danger",
    )])

    count = len(configs_list)
    if lang == "fa":
        text = (
            f"{premium_emoji('config', '🌐')} <b>کانفیگ‌های من ({count})</b>\n\n"
            f"روی هرکدوم بزن تا لینک و وضعیتش رو ببینی 👇"
        )
    else:
        text = (
            f"{premium_emoji('config', '🌐')} <b>My Configs ({count})</b>\n\n"
            f"Tap on any config to see the link and status 👇"
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception as e:
        err = str(e)
        if "message is not modified" in err:
            pass
        else:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    await safe_answer(callback)


async def _render_all_configs_page(callback: CallbackQuery, page: int = 0):
    """نمایش تمام کانفیگ‌های کاربر با مشخصات کامل و صفحه‌بندی ۵ تایی"""
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    lang = get_user(user_id).get('lang', 'fa')
    valid_orders = get_valid_orders()
    configs_list = [
        o for o in valid_orders.values()
        if o.get('user_id') == user_id
        and o.get('status') in ("approved", "inactive")
        and o.get('config_link')
    ]

    if not configs_list:
        await callback.answer(
            "❌ شما هیچ کانفیگ فعالی ندارید" if lang == "fa" else "❌ You have no active configs",
            show_alert=True,
        )
        return

    configs_list.sort(key=lambda x: str(x.get('date', '')), reverse=True)
    total_configs = len(configs_list)
    total_pages = (total_configs + ALL_CONFIGS_PAGE_SIZE - 1) // ALL_CONFIGS_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    start_idx = page * ALL_CONFIGS_PAGE_SIZE
    end_idx = min(start_idx + ALL_CONFIGS_PAGE_SIZE, total_configs)
    page_configs = configs_list[start_idx:end_idx]

    test_emoji, test_name = get_test_service_display(lang)
    link_emoji = premium_emoji('link', '🔗')

    async def fetch_traffic_one(c: dict) -> str:
        email = get_order_client_email(c)
        if email and is_senai_panel_enabled():
            try:
                client_info = await xui_get_client_info(email)
                if client_info:
                    traffic_data = await xui_get_client_traffic(email)
                    return format_traffic_info(client_info, traffic_data, lang)
            except Exception as e:
                logger.debug(f"Error fetching traffic for {email}: {e}")
        return ""

    traffic_results = await asyncio.gather(*[fetch_traffic_one(c) for c in page_configs], return_exceptions=False)

    if total_pages > 1:
        text = (
            f"📋 <b>همه کانفیگ‌ها ({start_idx + 1}-{end_idx} از {total_configs})</b>\n\n"
            if lang == "fa"
            else f"📋 <b>All Configs ({start_idx + 1}-{end_idx} of {total_configs})</b>\n\n"
        )
    else:
        text = ""

    for c, traffic_info in zip(page_configs, traffic_results):
        volume = c.get('volume', 0) or 0
        config_link = c.get('config_link', '')
        is_test = _is_test_order(c)
        category_name = (c.get('category_name') or '') if lang == "fa" else (c.get('category_name_en') or c.get('category_name') or '')

        if is_test:
            title = f"{test_emoji} {html.escape(test_name)}"
        elif category_name:
            clean_name = category_name.replace("کانفیگ ", "").strip()
            title_emoji = premium_emoji('globe', '🌐')
            title = f"{title_emoji} کانفیگ {html.escape(clean_name)}" if lang == "fa" else f"{title_emoji} {html.escape(category_name)}"
        else:
            title_emoji = premium_emoji('config', '📦')
            title = f"{title_emoji} کانفیگ شما" if lang == "fa" else f"{title_emoji} Your Config"

        if volume == 0:
            volume_display = "نامحدود" if lang == "fa" else "Unlimited"
        elif volume < 1:
            mb = volume * 1024
            volume_display = f"{mb:.0f} مگ" if lang == "fa" else f"{mb:.0f} MB"
        else:
            v = f"{volume:.1f}".rstrip('0').rstrip('.')
            volume_display = f"{v} گیگ" if lang == "fa" else f"{v} GB"

        link_label = "لینک اشتراک" if lang == "fa" else "Subscription Link"
        text += (
            f"{title} ({volume_display}){traffic_info}\n\n"
            f"{link_emoji} <b>{link_label}</b>\n"
            f'<a href="{config_link}">{config_link}</a>\n\n'
            f"   ━━━━━━━━━━━━━━━━━━━━\n\n"
        )

    buttons = []
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(
                text="⬅️ قبلی" if lang == "fa" else "⬅️ Prev",
                callback_data=f"show_all_configs_page_{page - 1}",
            ))
        nav_row.append(InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="noop",
        ))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                text="بعدی ➡️" if lang == "fa" else "Next ➡️",
                callback_data=f"show_all_configs_page_{page + 1}",
            ))
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton(
            text="🔙 کانفیگ‌های من" if lang == "fa" else "🔙 My Configs",
            callback_data="my_configs",
            style="primary",
        ),
        InlineKeyboardButton(
            text=t('main_menu_0cdd07a7cc', lang),
            callback_data="back_to_main",
            style="danger",
        ),
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await callback.message.edit_text(
            text.strip(),
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            try:
                await callback.message.delete()
            except Exception:
                pass
            bot = get_bot()
            if bot:
                await bot.send_message(
                    user_id,
                    text.strip(),
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
    await safe_answer(callback)


@router.callback_query(F.data == "show_all_my_configs")
async def show_all_my_configs(callback: CallbackQuery):
    """نمایش صفحه اول تمام کانفیگ‌های کاربر"""
    await _render_all_configs_page(callback, page=0)


@router.callback_query(F.data.startswith("show_all_configs_page_"))
async def show_all_my_configs_page(callback: CallbackQuery):
    """جابجایی بین صفحات لیست کامل کانفیگ‌ها (۵ تایی)"""
    lang = get_user(callback.from_user.id).get('lang', 'fa')
    try:
        page = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer(t('i18n_process_error', lang), show_alert=True)
        return
    await _render_all_configs_page(callback, page=page)


@router.callback_query(F.data.startswith("view_config_"))
async def view_single_config(callback: CallbackQuery):
    """نمایش یک کانفیگ خاص با ویرایش پیام (بدون تولید QR خودکار)"""
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await notify_blacklisted_user(user_id)
        await callback.answer(t('access_blocked_96a5fa848b', get_user(callback.from_user.id).get('lang', 'fa')), show_alert=True)
        return

    lang = get_user(user_id).get('lang', 'fa')

    try:
        order_id = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer(t('i18n_order_process_error', lang), show_alert=True)
        return

    order = orders.get(str(order_id))
    if not order or order.get('user_id') != user_id or not order.get('config_link'):
        await callback.answer(t('config_not_found_3169491e56', lang), show_alert=True)
        return

    await _render_single_config_text(callback, order_id, order, lang)
    await safe_answer(callback)

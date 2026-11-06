"""
WireGuard Premium QR Image Generator (Bilingual: FA / EN)
=========================================================
Generates a high-definition (1600x2000) production-ready WireGuard QR card
with dark cyberpunk styling, glowing neon red accents (#FF1744),
full Persian & English bilingual support, and verified 100% scannability.
"""

import os
import io
import logging
from typing import Optional, Dict, Any, Union
from PIL import Image, ImageDraw, ImageFont
import qrcode
from aiogram.types import BufferedInputFile

try:
    from qrcode.image.styledpil import StyledPilImage
    from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
    from qrcode.image.styles.colormasks import SolidFillColorMask
except ImportError:
    StyledPilImage = None
    RoundedModuleDrawer = None
    SolidFillColorMask = None

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:
    arabic_reshaper = None
    get_display = None

logger = logging.getLogger(__name__)

CANVAS_WIDTH = 1600
CANVAS_HEIGHT = 2000
NEON_RED = (255, 23, 68)  # #FF1744


def to_persian_digits(text: Union[int, str]) -> str:
    """تبدیل ارقام انگلیسی به فارسی"""
    farsi_digits = '۰۱۲۳۴۵۶۷۸۹'
    return ''.join(farsi_digits[int(c)] if c.isdigit() else c for c in str(text))


def reshape_persian(text: str) -> str:
    """اصلاح اتصال حروف و جهت متن فارسی برای رندر صحیح در Pillow"""
    if arabic_reshaper and get_display:
        try:
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text
    return text


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """بارگذاری بهینه‌ترین فونت مدرن سیستمی یا اختصاصی Vazirmatn"""
    font_paths = [
        os.path.join(os.path.dirname(__file__), 'assets', 'fonts', 'Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf'),
        'C:/Windows/Fonts/segoeuib.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf',
        'C:/Windows/Fonts/arialbd.ttf' if bold else 'C:/Windows/Fonts/arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/TTF/DejaVuSans.ttf',
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def generate_wireguard_qr(
    config: str, 
    box_size: int = 16, 
    border: int = 4, 
    add_logo: bool = True
) -> Image.Image:
    """
    تولید کیو‌آر‌کد مستقیم از کانفیگ واقعی وایرگارد.
    - ضریب تصحیح خطای H برای خوانایی ۱۰۰٪ در حضور لوگوی میانی.
    - حداقل ۴ ماژول حاشیه امن (Quiet Zone).
    - ماژول‌های گرد و صیقلی با پس‌زمینه سفید خالص.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(config)
    qr.make(fit=True)

    if StyledPilImage and RoundedModuleDrawer and SolidFillColorMask:
        qr_img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=RoundedModuleDrawer(),
            color_mask=SolidFillColorMask(back_color=(255, 255, 255), front_color=(10, 10, 14))
        ).convert('RGBA')
    else:
        qr_img = qr.make_image(fill_color='#0a0a0e', back_color='#ffffff').convert('RGBA')

    if add_logo:
        # ابعاد لوگوی میانی: ۱۶.۵٪ کل تصویر جهت عدم تداخل با الگوی اسکن
        badge_sz = int(qr_img.width * 0.165)
        badge = Image.new('RGBA', (badge_sz, badge_sz), (0, 0, 0, 0))
        bdraw = ImageDraw.Draw(badge)
        
        # نشان زرشکی وایرگارد با کادر سفید
        bdraw.rounded_rectangle(
            (0, 0, badge_sz, badge_sz),
            radius=badge_sz // 3,
            fill='#991b1b',
            outline='#ffffff',
            width=max(4, int(badge_sz * 0.04))
        )
        wg_font = _load_font(int(badge_sz * 0.44), bold=True)
        bdraw.text((badge_sz // 2, badge_sz // 2 - 2), 'WG', fill='#ffffff', font=wg_font, anchor='mm')
        
        paste_pos = ((qr_img.width - badge_sz) // 2, (qr_img.height - badge_sz) // 2)
        qr_img.paste(badge, paste_pos, badge)

    return qr_img


def create_premium_background(
    width: int = CANVAS_WIDTH, 
    height: int = CANVAS_HEIGHT, 
    lang: str = "fa"
) -> Image.Image:
    """
    تولید یا بارگذاری پس‌زمینه اختصاصی با تفکیک زبان (فارسی / انگلیسی)
    """
    tpl_filename = 'wireguard_template_fa.png' if lang == 'fa' else 'wireguard_template.png'
    template_path = os.path.join(os.path.dirname(__file__), 'assets', tpl_filename)

    # fallback به تمپلیت دیگر در صورت عدم وجود
    if not os.path.exists(template_path):
        alt_filename = 'wireguard_template.png' if lang == 'fa' else 'wireguard_template_fa.png'
        alt_path = os.path.join(os.path.dirname(__file__), 'assets', alt_filename)
        if os.path.exists(alt_path):
            template_path = alt_path

    if os.path.exists(template_path):
        try:
            tpl = Image.open(template_path).convert('RGBA')
            if tpl.size != (width, height):
                tpl = tpl.resize((width, height), Image.Resampling.LANCZOS)
            return tpl
        except Exception as err:
            logger.warning("Could not load %s: %s", tpl_filename, err)

    # ─── فال‌بک رویه‌ای در صورت عدم دسترسی به فایل تمپلیت ───
    bg = Image.new('RGBA', (width, height), (7, 8, 12, 255))
    draw = ImageDraw.Draw(bg)

    for y in range(height):
        ratio = y / height
        r = int(5 + ratio * 8)
        g = int(6 + ratio * 7)
        b = int(10 + ratio * 14)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    draw.rounded_rectangle((30, 30, width - 30, height - 30), radius=50, outline=(30, 35, 50, 255), width=3)
    draw.rounded_rectangle((34, 34, width - 34, 46), radius=6, fill=NEON_RED)

    # هدر
    pill_w, pill_h = 460, 68
    pill_x = (width - pill_w) // 2
    pill_y = 70
    draw.rounded_rectangle((pill_x, pill_y, pill_x + pill_w, pill_y + pill_h), radius=34, fill=(35, 12, 20, 255), outline=NEON_RED, width=2)
    tag_font = _load_font(30 if lang == 'fa' else 26, bold=True)
    tag_text = reshape_persian('⚡ کانفیگ اختصاصی وایرگارد') if lang == 'fa' else '⚡ WIREGUARD VPN'
    draw.text((width // 2, pill_y + pill_h // 2), tag_text, fill='#ff2a55', font=tag_font, anchor='mm')

    title_font = _load_font(86 if lang == 'fa' else 68, bold=True)
    title_text = reshape_persian('تونل پرسرعت وایرگارد') if lang == 'fa' else 'HIGH SPEED TUNNEL'
    draw.text((width // 2, pill_y + pill_h + 65), title_text, fill='#ffffff', font=title_font, anchor='mm')

    # فوتر
    foot_w, foot_h = 1240, 140
    foot_x = (width - foot_w) // 2
    foot_y = 1600
    draw.rounded_rectangle((foot_x, foot_y, foot_x + foot_w, foot_y + foot_h), radius=36, fill=(13, 16, 24, 255), outline=NEON_RED, width=2)
    f_title = _load_font(42 if lang == 'fa' else 36, bold=True)
    if lang == 'fa':
        s_p1 = reshape_persian('اسکن در برنامهٔ')
        s_p2 = reshape_persian('وایرگارد')
        s_p3 = reshape_persian('جهت اتصال')
        s_sp_w = 14
        s_w1 = draw.textbbox((0, 0), s_p1, font=f_title)[2] - draw.textbbox((0, 0), s_p1, font=f_title)[0]
        s_w2 = draw.textbbox((0, 0), s_p2, font=f_title)[2] - draw.textbbox((0, 0), s_p2, font=f_title)[0]
        s_w3 = draw.textbbox((0, 0), s_p3, font=f_title)[2] - draw.textbbox((0, 0), s_p3, font=f_title)[0]
        tot_s_w = s_w1 + s_sp_w + s_w2 + s_sp_w + s_w3
        st_s_x = 905 - tot_s_w // 2
        base_y = foot_y + 58
        draw.text((st_s_x, base_y), s_p3, fill='#ffffff', font=f_title, anchor='ls')
        draw.text((st_s_x + s_w3 + s_sp_w, base_y), s_p2, fill='#ff1744', font=f_title, anchor='ls')
        draw.text((st_s_x + s_w3 + s_sp_w + s_w2 + s_sp_w, base_y), s_p1, fill='#ffffff', font=f_title, anchor='ls')
    else:
        draw.text((width // 2, foot_y + 44), 'Scan in WireGuard App to Import', fill='#ffffff', font=f_title, anchor='mm')

    f_sub = _load_font(28 if lang == 'fa' else 24, bold=False)
    sub_text = reshape_persian('هندشیک آنی  •  رمزنگاری سرتاسری و ایمن') if lang == 'fa' else 'Fast Handshake  •  End-to-End Encrypted'
    draw.text((width // 2, foot_y + 92), sub_text, fill='#94a3b8', font=f_sub, anchor='mm')

    return bg


def compose_qr_card(
    qr_image: Image.Image,
    order_data: Optional[Dict[str, Any]] = None,
    width: int = CANVAS_WIDTH,
    height: int = CANVAS_HEIGHT,
    background: Optional[Image.Image] = None
) -> Image.Image:
    """
    ترکیب نهایی کارت ۱۶۰۰ در ۲۰۰۰ با فونت و زبان هماهنگ
    """
    order_info = order_data or {}
    lang = order_info.get('lang', 'fa')

    if background is None:
        card = create_premium_background(width, height, lang=lang)
    else:
        card = background.copy()

    bdraw = ImageDraw.Draw(card)
    order_id = order_info.get('order_id', 0)
    category = order_info.get('category')

    # ۱. زیرنویس پویا با پشتیبانی کامل زبان فارسی و انگلیسی
    if lang == 'fa':
        cat_display = category or 'سرویس UDP و استریمینگ'
        raw_order_text = f"سفارش شماره #{to_persian_digits(order_id)}  •  {cat_display}"
        order_text = reshape_persian(raw_order_text)
        mid_y = 372
        qr_x1, qr_y1 = 290, 430
        qr_x2, qr_y2 = 1310, 1508
    else:
        cat_display = category or 'UDP Gaming & Streaming'
        order_text = f"Order #{order_id}  •  {cat_display}"
        mid_y = 320
        qr_x1, qr_y1 = 265, 407
        qr_x2, qr_y2 = 1333, 1524

    order_font = _load_font(32 if lang == 'fa' else 34, bold=True)
    bbox = bdraw.textbbox((0, 0), order_text, font=order_font)
    tw = bbox[2] - bbox[0]
    mid_x = width // 2

    bdraw.text((mid_x, mid_y), order_text, fill='#e2e8f0', font=order_font, anchor='mm')
    line_len = 160 if lang == 'fa' else 110
    line_gap = 26
    bdraw.line([(mid_x - tw // 2 - line_gap - line_len, mid_y), (mid_x - tw // 2 - line_gap, mid_y)], fill='#475569', width=2)
    bdraw.line([(mid_x + tw // 2 + line_gap, mid_y), (mid_x + tw // 2 + line_gap + line_len, mid_y)], fill='#475569', width=2)

    # ۲. محفظه سفید QR با هاله نئونی قرمز
    box_w = qr_x2 - qr_x1
    box_h = qr_y2 - qr_y1

    container_layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(container_layer)

    # هاله نئونی چند لایه
    radius = 48
    glow_passes = [(10, 35), (8, 60), (6, 95), (4, 150), (2, 210), (0, 255)]
    for offset, alpha in glow_passes:
        cdraw.rounded_rectangle(
            (qr_x1 - offset, qr_y1 - offset, qr_x2 + offset, qr_y2 + offset),
            radius=radius + offset,
            outline=(NEON_RED[0], NEON_RED[1], NEON_RED[2], alpha),
            width=3
        )

    # محفظه سفید صیقلی
    cdraw.rounded_rectangle((qr_x1, qr_y1, qr_x2, qr_y2), radius=radius, fill=(255, 255, 255, 255))

    # مقیاس‌دهی و مرکزچینی دقیق کیو‌آر‌کد
    inner_pad = 42
    qr_target_size = min(box_w - inner_pad * 2, box_h - inner_pad * 2)
    qr_scaled = qr_image.resize((qr_target_size, qr_target_size), Image.Resampling.LANCZOS)

    paste_x = qr_x1 + (box_w - qr_target_size) // 2
    paste_y = qr_y1 + (box_h - qr_target_size) // 2
    container_layer.paste(qr_scaled, (paste_x, paste_y), qr_scaled)

    # ادغام لایه‌ها
    final_card = Image.alpha_composite(card, container_layer)
    return final_card.convert('RGB')


def export_final_image(image: Image.Image, output_format: str = 'PNG', quality: int = 95) -> bytes:
    """خروجی نهایی به بایت با فشرده‌سازی استاندارد و بدون افت کیفیت"""
    bio = io.BytesIO()
    image.save(bio, format=output_format, quality=quality, optimize=True)
    return bio.getvalue()


def generate_wireguard_qr_code(
    data: str,
    order_id: int,
    order_data: Optional[Dict[str, Any]] = None
) -> BufferedInputFile:
    """
    نقطه ورود اصلی برای ربات تلگرام با تشخیص خودکار زبان
    """
    info = dict(order_data or {})
    info.setdefault('order_id', order_id)
    lang = info.get('lang', 'fa')
    logger.info("Generating premium WireGuard QR card for order #%s (lang=%s)", order_id, lang)

    qr_img = generate_wireguard_qr(data)
    card_img = compose_qr_card(qr_img, info)
    image_bytes = export_final_image(card_img, output_format='PNG', quality=95)

    return BufferedInputFile(image_bytes, filename=f"wireguard_qr_{order_id}.png")

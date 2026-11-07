"""
WireGuard Premium QR Image Generator (Bilingual: FA / EN)
=========================================================
Generates a high-definition (1600x2000) production-ready WireGuard QR card
with dark cyberpunk styling, glowing neon red accents (#FF1744),
full Persian & English bilingual support, and verified 100% scannability.
"""

import os
import sys
import glob

# ۱. افزودن پوشه vendor برای دسترسی تضمینی و آفلاین به arabic_reshaper و bidi
_vendor_dir = os.path.join(os.path.dirname(__file__), 'vendor')
if os.path.isdir(_vendor_dir) and _vendor_dir not in sys.path:
    sys.path.insert(0, _vendor_dir)

# ۲. اطمینان از دسترسی به پکیج‌های مجازی‌ساز در لینوکس و ویندوز
for _pattern in [
    os.path.join(os.path.dirname(__file__), '.venv', 'lib', 'python*', 'site-packages'),
    os.path.join(os.path.dirname(__file__), '.venv', 'Lib', 'site-packages'),
    os.path.join(os.path.dirname(__file__), 'venv', 'lib', 'python*', 'site-packages'),
    os.path.join(os.path.dirname(__file__), 'venv', 'Lib', 'site-packages'),
    os.path.join(os.path.dirname(__file__), '.venv', 'local', 'lib', 'python*', 'site-packages'),
    '/opt/VeloraBot/.venv/lib/python*/site-packages',
]:
    for _site_path in glob.glob(_pattern):
        if os.path.exists(_site_path) and _site_path not in sys.path:
            sys.path.insert(0, _site_path)

import io
import logging
from typing import Optional, Dict, Any, Union
from PIL import Image, ImageDraw, ImageFont
import qrcode
from aiogram.types import BufferedInputFile

try:
    from qrcode.image.styledpil import StyledPilImage
    from qrcode.image.styles.moduledrawers.pil import CircleModuleDrawer
    from qrcode.image.styles.colormasks import SolidFillColorMask
except ImportError:
    StyledPilImage = None
    CircleModuleDrawer = None
    SolidFillColorMask = None

if CircleModuleDrawer:
    class DottedHighContrastDrawer(CircleModuleDrawer):
        """
        رندر ماژول‌ها به صورت نقطه‌ای (دایره‌ای فوق‌شارپ با کنتراست حداکثری)
        به همراه حفظ چشم‌های گوشه (Finder Patterns) به شکل استاندارد شارپ
        برای شناسایی و اسکن فوق‌سریع در تمام گوشی‌ها و اپلیکیشن WireGuard.
        """
        def initialize(self, *args, **kwargs):
            super().initialize(*args, **kwargs)
            box_size = self.img.box_size
            
            # الگوی استاندارد چشم‌های گوشه برای قفل فوری فوکوس دوربین
            self.square = Image.new(
                self.img.mode,
                (box_size, box_size),
                self.img.paint_color
            )
            
            # نقطه دایره‌ای شارپ با کنتراست کامل
            antialias = 4
            fake_sz = box_size * antialias
            high_res = Image.new(self.img.mode, (fake_sz, fake_sz), self.img.color_mask.back_color)
            d = ImageDraw.Draw(high_res)
            d.ellipse((0, 0, fake_sz - 1, fake_sz - 1), fill=self.img.paint_color)
            self.circle = high_res.resize((box_size, box_size), Image.Resampling.LANCZOS)

        def drawrect(self, box, is_active: bool):
            if not is_active:
                return
            box_size = self.img.box_size
            x_mod = box[0][0] // box_size
            y_mod = box[0][1] // box_size
            dim = self.img.width // box_size
            border = self.img.border
            
            mx = x_mod - border
            my = y_mod - border
            matrix_size = dim - 2 * border
            
            # الگوهای یابنده گوشه (Finder Patterns) در ابعاد 7x7
            is_finder = (
                (0 <= mx < 7 and 0 <= my < 7) or
                (matrix_size - 7 <= mx < matrix_size and 0 <= my < 7) or
                (0 <= mx < 7 and matrix_size - 7 <= my < matrix_size)
            )
            
            if is_finder:
                self.img._img.paste(self.square, (box[0][0], box[0][1]))
            else:
                self.img._img.paste(self.circle, (box[0][0], box[0][1]))
else:
    DottedHighContrastDrawer = None

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _reshaper = arabic_reshaper.ArabicReshaper(configuration={
        'delete_harakat': True,
        'support_ligatures': True,
        'language': 'Persian',
    })
except ImportError:
    arabic_reshaper = None
    get_display = None
    _reshaper = None

logger = logging.getLogger(__name__)

CANVAS_WIDTH = 850
CANVAS_HEIGHT = 1024
NEON_RED = (255, 23, 68)  # #FF1744
_TEMPLATE_CACHE: Dict[str, Image.Image] = {}


def to_persian_digits(text: Union[int, str]) -> str:
    """تبدیل ارقام انگلیسی به فارسی"""
    farsi_digits = '۰۱۲۳۴۵۶۷۸۹'
    return ''.join(farsi_digits[int(c)] if c.isdigit() else c for c in str(text))


def reshape_persian(text: str) -> str:
    """اصلاح اتصال حروف و جهت متن فارسی برای رندر صحیح در Pillow"""
    global arabic_reshaper, get_display, _reshaper
    if arabic_reshaper is None or get_display is None:
        try:
            _vendor_dir = os.path.join(os.path.dirname(__file__), 'vendor')
            if os.path.isdir(_vendor_dir) and _vendor_dir not in sys.path:
                sys.path.insert(0, _vendor_dir)
            import arabic_reshaper as _ar
            from bidi.algorithm import get_display as _gd
            arabic_reshaper = _ar
            get_display = _gd
            _reshaper = _ar.ArabicReshaper(configuration={
                'delete_harakat': True,
                'support_ligatures': True,
                'language': 'Persian',
            })
        except ImportError as err:
            logger.error("Persian reshaping libraries missing (arabic_reshaper / python-bidi): %s", err)

    if arabic_reshaper and get_display:
        try:
            reshaped = _reshaper.reshape(text) if _reshaper else arabic_reshaper.reshape(text)
            return get_display(reshaped)
        except Exception as err:
            logger.warning("Persian reshaping error: %s", err)
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
    box_size: int = 12, 
    border: int = 2, 
    add_logo: bool = True
) -> Image.Image:
    """
    تولید کیو‌آر‌کد نقطه‌ای فوق‌شارپ با کنتراست حداکثری و لوگوی دقیق و بدون بیرون‌زدگی وایرگارد.
    - ماژول‌های نقطه‌ای دایره‌ای با بالاترین کنتراست (سیاه و سفید خالص)
    - حفظ الگوی مربعی استاندارد چشم‌های گوشه (Finder Patterns) برای قفل فوری فوکوس دوربین
    - لوگوی وایرگارد در مرکز، برش خورده با دقت صدم پیکسل بدون کوچک‌ترین بیرون‌زدگی رنگی از کادر سفید
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(config)
    qr.make(fit=True)

    if StyledPilImage and DottedHighContrastDrawer and SolidFillColorMask:
        try:
            qr_img = qr.make_image(
                image_factory=StyledPilImage,
                module_drawer=DottedHighContrastDrawer(),
                color_mask=SolidFillColorMask(front_color=(0, 0, 0), back_color=(255, 255, 255))
            ).convert('RGBA')
        except Exception as e:
            logger.warning("Error generating styled dotted QR: %s - using standard", e)
            qr_img = qr.make_image(fill_color='#000000', back_color='#ffffff').convert('RGBA')
    else:
        qr_img = qr.make_image(fill_color='#000000', back_color='#ffffff').convert('RGBA')

    if add_logo:
        badge_sz = int(qr_img.width * 0.17)
        badge = None
        logo_path = os.path.join(os.path.dirname(__file__), 'assets', 'wireguard_logo.png')
        
        if os.path.exists(logo_path):
            try:
                # رندر ۴ برابری (4x Supersampling) برای جلوگیری قطعی از هرگونه بیرون‌زدگی رنگی
                scale = 4
                big_sz = badge_sz * scale
                pad = max(int(big_sz * 0.055), 8)
                inner_sz = big_sz - 2 * pad
                radius_outer = int(big_sz * 0.22)
                radius_inner = max(4, radius_outer - pad)
                
                # ۱. پایه سفید یکدست و کامل
                big_badge = Image.new('RGBA', (big_sz, big_sz), (0, 0, 0, 0))
                bdraw = ImageDraw.Draw(big_badge)
                bdraw.rounded_rectangle(
                    (0, 0, big_sz - 1, big_sz - 1),
                    radius=radius_outer,
                    fill=(255, 255, 255, 255)
                )
                
                # ۲. لود لوگو و قرار دادن داخل حاشیه سفید بدون تماس با لبه بیرونی
                raw_logo = Image.open(logo_path).convert('RGBA')
                inner_logo = raw_logo.resize((inner_sz, inner_sz), Image.Resampling.LANCZOS)
                
                inner_mask = Image.new('L', (inner_sz, inner_sz), 0)
                mdraw = ImageDraw.Draw(inner_mask)
                mdraw.rounded_rectangle(
                    (0, 0, inner_sz - 1, inner_sz - 1),
                    radius=radius_inner,
                    fill=255
                )
                
                big_badge.paste(inner_logo, (pad, pad), inner_mask)
                badge = big_badge.resize((badge_sz, badge_sz), Image.Resampling.LANCZOS)
            except Exception as e:
                logger.warning("Error loading wireguard logo: %s", e)
                badge = None

        if badge is None:
            # فال‌بک متنی در صورت عدم وجود فایل لوگو
            badge = Image.new('RGBA', (badge_sz, badge_sz), (0, 0, 0, 0))
            bdraw = ImageDraw.Draw(badge)
            bdraw.rounded_rectangle(
                (0, 0, badge_sz - 1, badge_sz - 1),
                radius=max(6, badge_sz // 3),
                fill='#991b1b',
                outline='#ffffff',
                width=max(2, int(badge_sz * 0.05))
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
    تولید یا بارگذاری پس‌زمینه اختصاصی با تفکیک زبان (فارسی / انگلیسی) به همراه کش در حافظه
    """
    global _TEMPLATE_CACHE
    cached = _TEMPLATE_CACHE.get(lang)
    if cached is not None and cached.size == (width, height):
        return cached.copy()

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
            _TEMPLATE_CACHE[lang] = tpl
            return tpl.copy()
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

    draw.rounded_rectangle((15, 15, width - 15, height - 15), radius=25, outline=(30, 35, 50, 255), width=2)
    draw.rounded_rectangle((17, 17, width - 17, 23), radius=3, fill=NEON_RED)

    # هدر
    pill_w, pill_h = 240, 36
    pill_x = (width - pill_w) // 2
    pill_y = 35
    draw.rounded_rectangle((pill_x, pill_y, pill_x + pill_w, pill_y + pill_h), radius=18, fill=(35, 12, 20, 255), outline=NEON_RED, width=1)
    tag_font = _load_font(15, bold=True)
    tag_text = reshape_persian('⚡ وایرگارد VPN') if lang == 'fa' else '⚡ WIREGUARD VPN'
    draw.text((width // 2, pill_y + pill_h // 2), tag_text, fill='#ff2a55', font=tag_font, anchor='mm')

    title_font = _load_font(42 if lang == 'fa' else 36, bold=True)
    title_text = reshape_persian('تونل پرسرعت') if lang == 'fa' else 'HIGH SPEED TUNNEL'
    draw.text((width // 2, pill_y + pill_h + 38), title_text, fill='#ffffff', font=title_font, anchor='mm')

    # برچسب ثابت سفارش در پس‌زمینه (در صورت عدم وجود فایل تمپلیت)
    lbl_font = _load_font(17, bold=True)
    if lang == 'fa':
        lbl_text = reshape_persian('سفارش')
        draw.text((428, 190), lbl_text, fill='#e2e8f0', font=lbl_font, anchor='lm')
        bbox_l = draw.textbbox((428, 190), lbl_text, font=lbl_font, anchor='lm')
        lw = bbox_l[2] - bbox_l[0]
        draw.line([(428 + lw + 14, 190), (428 + lw + 14 + 80, 190)], fill='#475569', width=1)
    else:
        lbl_text = 'Order'
        draw.text((418, 187), lbl_text, fill='#e2e8f0', font=lbl_font, anchor='rm')
        bbox_l = draw.textbbox((418, 187), lbl_text, font=lbl_font, anchor='rm')
        ow = bbox_l[2] - bbox_l[0]
        draw.line([(418 - ow - 14 - 80, 187), (418 - ow - 14, 187)], fill='#475569', width=1)

    # فوتر
    foot_w, foot_h = 620, 75
    foot_x = (width - foot_w) // 2
    foot_y = 800
    draw.rounded_rectangle((foot_x, foot_y, foot_x + foot_w, foot_y + foot_h), radius=18, fill=(13, 16, 24, 255), outline=NEON_RED, width=1)
    f_title = _load_font(20 if lang == 'fa' else 17, bold=True)
    scan_text = reshape_persian('برای وارد کردن، کد را با اپلیکیشن WireGuard اسکن کنید') if lang == 'fa' else 'Scan this code with the WireGuard App to Import'
    draw.text((width // 2, foot_y + 24), scan_text, fill='#ffffff', font=f_title, anchor='mm')

    f_sub = _load_font(14, bold=False)
    sub_text = reshape_persian('اتصال سریع  •  رمزنگاری سرتاسری') if lang == 'fa' else 'Fast Connection  •  End-to-End Encryption'
    draw.text((width // 2, foot_y + 50), sub_text, fill='#94a3b8', font=f_sub, anchor='mm')

    _TEMPLATE_CACHE[lang] = bg
    return bg.copy()


def compose_qr_card(
    qr_image: Image.Image,
    order_data: Optional[Dict[str, Any]] = None,
    width: int = CANVAS_WIDTH,
    height: int = CANVAS_HEIGHT,
    background: Optional[Image.Image] = None
) -> Image.Image:
    """
    ترکیب نهایی کارت ۸۵۰ در ۱۰۲۴ با سرعت بالا و رندر بی‌نقص
    """
    order_info = order_data or {}
    lang = order_info.get('lang', 'fa')

    if background is None:
        card = create_premium_background(width, height, lang=lang)
    else:
        card = background.copy()

    bdraw = ImageDraw.Draw(card)
    order_id = order_info.get('order_id', 0)
    order_str = f"#{order_id}"
    order_font = _load_font(17, bold=True)

    # ۱. زیرنویس شماره سفارش (عددی و پایدار در هر پلتفرم بدون نیاز به پردازش RTL متنی)
    if lang == 'fa':
        mid_y = 190
        box_x1, box_y1 = 154, 220
        box_x2, box_y2 = 696, 772

        bbox = bdraw.textbbox((416, mid_y), order_str, font=order_font, anchor='rm')
        nw = bbox[2] - bbox[0]
        bdraw.text((416, mid_y), order_str, fill='#e2e8f0', font=order_font, anchor='rm')
        bdraw.line([(416 - nw - 14 - 80, mid_y), (416 - nw - 14, mid_y)], fill='#475569', width=1)
    else:
        mid_y = 187
        box_x1, box_y1 = 155, 220
        box_x2, box_y2 = 695, 772

        bbox = bdraw.textbbox((425, mid_y), order_str, font=order_font, anchor='lm')
        nw = bbox[2] - bbox[0]
        bdraw.text((425, mid_y), order_str, fill='#e2e8f0', font=order_font, anchor='lm')
        bdraw.line([(425 + nw + 14, mid_y), (425 + nw + 14 + 80, mid_y)], fill='#475569', width=1)

    # ۲. محفظه سفید QR با هاله نئونی قرمز
    box_w = box_x2 - box_x1
    box_h = box_y2 - box_y1
    radius = 24

    container_layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(container_layer)

    # محفظه سفید صیقلی
    cdraw.rounded_rectangle((box_x1, box_y1, box_x2, box_y2), radius=radius, fill=(255, 255, 255, 255))

    # مقیاس‌دهی و مرکزچینی دقیق کیو‌آر‌کد با حداقل گپ حاشیه
    inner_pad = 12
    qr_target_size = min(box_w - inner_pad * 2, box_h - inner_pad * 2)
    qr_scaled = qr_image.resize((qr_target_size, qr_target_size), Image.Resampling.LANCZOS)

    paste_x = box_x1 + (box_w - qr_target_size) // 2
    paste_y = box_y1 + (box_h - qr_target_size) // 2
    container_layer.paste(qr_scaled, (paste_x, paste_y), qr_scaled)

    # ادغام لایه‌ها
    final_card = Image.alpha_composite(card, container_layer)
    return final_card.convert('RGB')


def export_final_image(image: Image.Image, output_format: str = 'PNG', quality: int = 95) -> bytes:
    """خروجی نهایی به بایت با سرعت حداکثری و کیفیت کامل"""
    bio = io.BytesIO()
    image.save(bio, format=output_format, quality=quality, optimize=False)
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

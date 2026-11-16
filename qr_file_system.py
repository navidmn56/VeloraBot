from io import BytesIO

import qrcode
from aiogram.types import BufferedInputFile


DOWNLOADED_FILES = {}


def track_downloaded_file(user_id: int, message_id: int, chat_id: int):
    if user_id not in DOWNLOADED_FILES:
        DOWNLOADED_FILES[user_id] = []
    DOWNLOADED_FILES[user_id].append({
        'message_id': message_id,
        'chat_id': chat_id
    })


def generate_qr_code(data: str, order_id: int, logger):
    """ساخت QR Code و برگردوندن به فرمت مناسب aiogram 3.x"""
    logger.debug(f"QR Code generation for order #{order_id}")
    qr = qrcode.QRCode(
        version=5,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=14,
        border=2
    )
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#000000", back_color="#FFFFFF").convert('RGB')
    bio = BytesIO()
    bio.name = f'qrcode_{order_id}.png'
    qr_img.save(bio, 'PNG', quality=95)
    bio.seek(0)
    return BufferedInputFile(bio.read(), filename=f'qrcode_{order_id}.png')


async def delete_downloaded_files(user_id: int, chat_id: int, bot, logger):
    """پاک کردن همه فایل‌های ارسال‌شده به کاربر"""
    if user_id not in DOWNLOADED_FILES:
        return

    for item in list(DOWNLOADED_FILES[user_id]):
        try:
            await bot.delete_message(
                chat_id=item.get('chat_id', chat_id),
                message_id=item['message_id']
            )
            logger.info(f"🗑 Download file for user {user_id} deleted (msg_id: {item['message_id']})")
        except Exception as e:
            logger.debug(f"Error deleting file: {e}")

    DOWNLOADED_FILES[user_id].clear()
    del DOWNLOADED_FILES[user_id]

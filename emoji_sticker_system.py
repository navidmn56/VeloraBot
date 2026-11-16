from typing import Any


PREMIUM_EMOJI_IDS = {
    'warning': 5447644880824181073,
    'danger': 5420323339723881652,
    'success': 5048892927288280410,
    'fail': 5974083768233760323,
    'cancel': 5974083768233760323,
    'check': 6269163801178804220,
    'access_denied': 5445350865776941647,
    'info': 6203791465471022369,
    'wallet': 5215420556089776398,
    'money': 5375296873982604963,
    'card': 5974575468974705730,
    'receipt': 5444856076954520455,
    'shopping_cart': 5431499171045581032,
    'discount': 6098435638527266289,
    'label': 5296348778012361146,
    'config': 5431736674147114227,
    'box': 5472335930549347896,
    'link': 5271604874419647061,
    'qr': 5443021125191739647,
    'user': 5440764424820377609,
    'user1': 5262690351969215936,
    'users': 5453957997418004470,
    'invite': 5251601734253421368,
    'id': 5965485570124681987,
    'order_id': 6323600780783781848,
    'time': 5451732530048802485,
    'timer': 5413704112220949842,
    'calendar': 5834822129425584578,
    'hourglass': 6071317996704370355,
    'loading': 5334675996714999970,
    'reload': 5408891085969700325,
    'cpu': 5431376038628171216,
    'ram': 5237799019329105246,
    'disk': 5462956611033117422,
    'net_up': 5449683594425410231,
    'net_down': 5451675802120764617,
    'upload': 5783105032350076195,
    'download': 5443127283898405358,
    'note': 5334882760735598374,
    'chat': 5440889232275036277,
    'hint': 5472146462362048818,
    'light': 5328175963144466763,
    'star': 5451636889717062286,
    'rocket': 5445284980978621387,
    'gift': 5199749070830197566,
    'globe': 5447410659077661506,
    'language': 4974345716802519903,
    'robot': 5310170944843579391,
    'test': 5411512278740640309,
    'amar': 5231200819986047254,
    'cubes': 5226513232549664618,
    'count': 5226702984204797593,
    'email': 5253742260054409879,
    'anime': 5382310787505221582,
    'primary': None,
    'admin': None,
    'back': None,
    'plus': None,
    'minus': None,
    'next': None,
    'previous': None,
}

STICKER_IDS = {
    'welcome': 'CAACAgQAAxkBAAERYvFqLYSw1e7mqt0LreZQ5iAXYLYgwQACmRIAAnZ5WVFtqjwTk98wTTwE',
    'halloween': 'CAACAgIAAxkBAAESI_Jq5i2BFCUOaY6qP7yuNzGyTU7Y7gACQAEAAladvQps6VtALEnWJT0E',
    'success': 'CAACAgIAAxkBAAERYvNqLYUtRvn80WovxY4pmS_w0Gl4IAAC_gADVp29CtoEYTAu-df_PAQ',
    'error': 'CAACAgIAAxkBAAEB',
    'payment': 'CAACAgQAAxkBAAERYvVqLYW--BzhGTmOkLiUrL0Nqi0IewAC9BMAAkziGVLzMxdaDdc2ojwE',
    'config': 'CAACAgEAAxkBAAERYxpqLZ_BdzW1SHvfF8lclSlkQ2bkDwACEgAD-wn4TyfquP1sDazXPAQ',
    'balance_insufficient': 'CAACAgIAAxkBAAERYxhqLZ-DqmtKnvuOezC6qxlmw3JxrgACQxgAArbIKUh1S6tFvSw1WDwE',
    'balance_added': 'CAACAgQAAxkBAAERYv9qLYkLt5qnysZ7WfDLVK6xvYZvjwACZBEAAtZJ0FFLoFGBKZ7uXzwE',
    'order_created': 'CAACAgIAAxkBAAEB',
    'order_approved': 'CAACAgIAAxkBAAERYvNqLYUtRvn80WovxY4pmS_w0Gl4IAAC_gADVp29CtoEYTAu-df_PAQ',
    'order_rejected': 'CAACAgIAAxkBAAERYtdqLYNgjzOUQi8uRFj-ZxHiOhEZvwACRh4AAvyUOEnTIzZfgD7FIDwE',
    'referral': 'CAACAgQAAxkBAAERYvtqLYdkDe9oPhYCCzd5jRmj9eo-tgAC6xQAAndYgVIvZzhm7RBW9jwE',
    'warning': 'CAACAgIAAxkBAAEB',
    'gift': 'CAACAgIAAxkBAAEB',
    'robot': 'CAACAgQAAxkBAAER3Odqnd93G152g-w4Q6ydGd74vbHRegACyxQAAn7WaFEz_uHI6TxiXz0E',
    'money': 'CAACAgQAAxkBAAERYv1qLYg2VGtarsPxg7UUuJE5cJwsxgACbRIAAkMYUVBj6dJT6kRbJjwE',
    'cart': 'CAACAgIAAxkBAAEB',
}


def premium_emoji(name: str, fallback: str = "📌") -> str:
    emoji_id = PREMIUM_EMOJI_IDS.get(name)
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>' if emoji_id else fallback


async def send_sticker(
    bot: Any,
    chat_id: int,
    sticker_key: str,
    fallback_emoji: str = "📌",
    reply_markup: Any = None,
    logger: Any = None,
) -> bool:
    sticker_id = STICKER_IDS.get(sticker_key)

    if sticker_id:
        try:
            if reply_markup is not None:
                await bot.send_sticker(chat_id, sticker_id, reply_markup=reply_markup)
            else:
                await bot.send_sticker(chat_id, sticker_id)
            return True
        except Exception as e:
            if logger is not None:
                logger.warning(f"Error sending sticker {sticker_key}: {e}")

    if reply_markup is not None:
        await bot.send_message(chat_id, fallback_emoji, reply_markup=reply_markup)
    else:
        await bot.send_message(chat_id, fallback_emoji)
    return False

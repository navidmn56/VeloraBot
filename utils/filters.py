"""Custom aiogram filters for authorization and chat scopes."""

from typing import Optional
from aiogram.filters import BaseFilter
from aiogram.types import Message, TelegramObject

from user_manager import get_admin_id_int


class IsAdmin(BaseFilter):
    """فیلتر بررسی دسترسی ادمین با قابلیت محدودسازی به چت خصوصی"""

    def __init__(self, private_only: bool = True):
        self.private_only = private_only

    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        admin_id = get_admin_id_int()
        if not user or user.id != admin_id:
            return False

        if self.private_only and isinstance(event, Message):
            chat = getattr(event, "chat", None)
            if chat and chat.type != "private":
                return False

        return True

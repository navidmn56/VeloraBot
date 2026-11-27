"""Rate limiting utilities for Telegram bot user actions."""

import time
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar, cast
from aiogram.types import CallbackQuery
from utils.helpers import safe_answer

F = TypeVar("F", bound=Callable[..., Any])


class ActionRateLimiter:
    """In-memory rate limiter per user/action with automatic cleanup."""

    def __init__(self, default_cooldown: float = 1.5, max_entries: int = 10000):
        self.default_cooldown = default_cooldown
        self.max_entries = max_entries
        self._last_action: Dict[Tuple[int, str], float] = {}

    def is_rate_limited(
        self,
        user_id: int,
        action: str = "default",
        cooldown: Optional[float] = None
    ) -> bool:
        """
        Check if an action is rate limited for a user.
        Returns True if the action is too frequent (should be blocked),
        False if the action is allowed.
        """
        limit = cooldown if cooldown is not None else self.default_cooldown
        now = time.monotonic()
        key = (int(user_id), str(action))
        last_time = self._last_action.get(key, 0.0)

        if now - last_time < limit:
            try:
                from services.server_guard import record_bot_user_block
                record_bot_user_block(user_id, action=action)
            except Exception:
                pass
            return True

        self._last_action[key] = now

        # Periodic cleanup if dictionary grows large
        if len(self._last_action) > self.max_entries:
            cutoff = now - 300.0
            self._last_action = {k: v for k, v in self._last_action.items() if v > cutoff}

        return False

    def reset(self, user_id: int, action: str = "default") -> None:
        """Reset rate limit for a specific user and action."""
        self._last_action.pop((int(user_id), str(action)), None)


# Default rate limiter for buy and checkout flows
buy_rate_limiter = ActionRateLimiter(default_cooldown=1.5)


def rate_limit(
    cooldown: float = 1.5,
    action: str = "default",
    message_fa: str = "⏳ لطفاً کمی صبر کنید...",
    message_en: str = "⏳ Please wait a moment...",
    alert: bool = False,
):
    """Decorator to rate-limit callback query handlers."""
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            event = args[0] if args else None
            user = getattr(event, "from_user", None)
            if user:
                user_id = user.id
                if buy_rate_limiter.is_rate_limited(user_id, action=action, cooldown=cooldown):
                    if isinstance(event, CallbackQuery):
                        try:
                            from database import users
                            lang = users.get(str(user_id), {}).get("lang", "fa")
                        except Exception:
                            lang = getattr(user, "language_code", "fa") or "fa"
                        msg = message_en if str(lang).startswith("en") else message_fa
                        await safe_answer(event, msg, alert=alert)
                    return None
            return await func(*args, **kwargs)

        return cast(F, wrapper)

    return decorator

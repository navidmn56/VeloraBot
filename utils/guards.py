"""Reusable authorization decorators for bot handlers."""

from functools import wraps
from typing import Any, Callable, Optional, TypeVar, cast

from aiogram.types import CallbackQuery

from user_manager import get_admin_id_int

F = TypeVar("F", bound=Callable[..., Any])


def admin_only(
    func: Optional[F] = None,
    *,
    message: str = "⛔",
    show_alert: bool = True,
    answer_on_denied: bool = True,
    return_answer: bool = True,
    admin_id_getter: Optional[Callable[[], int]] = None,
    on_denied: Optional[Callable[[CallbackQuery], Any]] = None,
) -> Any:
    """Restrict a callback handler to the configured administrator.

    Bare ``@admin_only`` preserves the common alert and return behavior.
    The keyword options let handlers retain existing silent denials, custom
    alert text, or denial-side logging while sharing the authorization check.
    """
    get_admin_id = admin_id_getter or get_admin_id_int

    def decorate(handler: F) -> F:
        @wraps(handler)
        async def wrapper(callback: CallbackQuery, *args: Any, **kwargs: Any) -> Any:
            user = getattr(callback, "from_user", None)
            if not user or user.id != get_admin_id():
                if on_denied is not None:
                    on_denied(callback)
                if not answer_on_denied:
                    return None

                try:
                    answer_result = await callback.answer(message, show_alert=show_alert)
                    if return_answer:
                        return answer_result
                except Exception:
                    pass
                return None

            return await handler(callback, *args, **kwargs)

        return cast(F, wrapper)

    if func is not None:
        return decorate(func)
    return decorate

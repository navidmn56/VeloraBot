"""
core package
------------
Core components, state stores, and background workers for the bot.
"""

from core.state_stores import (
    TempStore,
    TEMP_INBOUND_SELECTION,
    INBOUND_BACK_DATA,
    USER_INBOUND_SELECTION,
    USER_TEST_SETTINGS,
    CONFIG_LINKS_CACHE,
    _tg_user_cache,
)
from core.save_scheduler import (
    schedule_save,
    _debounced_save_worker,
    _save_queue,
    set_save_task,
    get_save_task,
)

__all__ = [
    "TempStore",
    "TEMP_INBOUND_SELECTION",
    "INBOUND_BACK_DATA",
    "USER_INBOUND_SELECTION",
    "USER_TEST_SETTINGS",
    "CONFIG_LINKS_CACHE",
    "_tg_user_cache",
    "schedule_save",
    "_debounced_save_worker",
    "_save_queue",
    "set_save_task",
    "get_save_task",
]

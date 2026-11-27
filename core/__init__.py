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
    schedule_file_save,
    _debounced_save_worker,
    _save_queue,
    set_save_task,
    get_save_task,
)
from core.task_manager import (
    TASK_DEFINITIONS,
    get_all_task_definitions,
    get_task_definition,
    is_task_enabled,
    get_task_interval,
    set_task_enabled,
    set_task_interval,
    sync_legacy_task_setting,
    request_task_run_now,
    wake_task,
    format_interval_human,
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
    "schedule_file_save",
    "_debounced_save_worker",
    "_save_queue",
    "set_save_task",
    "get_save_task",
    "TASK_DEFINITIONS",
    "get_all_task_definitions",
    "get_task_definition",
    "is_task_enabled",
    "get_task_interval",
    "set_task_enabled",
    "set_task_interval",
    "sync_legacy_task_setting",
    "request_task_run_now",
    "wake_task",
    "format_interval_human",
]

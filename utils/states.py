"""Formal FSM (Finite State Machine) architecture for Telegram bot users.

Provides aiogram StatesGroups and an intelligent, 100% backward-compatible,
persistently-backed FSMStateManager that replaces raw in-memory dictionaries
so user states survive bot restarts, reboots, and crashes without data loss.
"""

import os
import json
import logging
import asyncio
from typing import Any, Callable, Dict, List, Optional, Set, Union
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import BaseFilter

logger = logging.getLogger(__name__)
TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def _timestamp_age_seconds(ts: Any) -> Optional[float]:
    """Compute elapsed seconds since ISO timestamp, handling naive and aware values."""
    if not ts:
        return None
    created = datetime.fromisoformat(str(ts).strip())
    if created.tzinfo is None:
        created = created.replace(tzinfo=TEHRAN_TZ)
    return (datetime.now(TEHRAN_TZ) - created).total_seconds()


# ═══════════════════════════════════════════════════════════
# Formal FSM States Groups
# ═══════════════════════════════════════════════════════════

class OrderStates(StatesGroup):
    """User states during order creation, payments, and checkout."""
    awaiting_receipt = State()
    awaiting_coupon_code = State()
    awaiting_order_number = State()
    awaiting_payment = State()
    awaiting_payment_removed = State()
    awaiting_custom_payment_receipt_amount = State()
    awaiting_custom_payment_receipt_confirm = State()
    awaiting_custom_payment_receipt_manual_days = State()
    awaiting_custom_payment_receipt_manual_volume = State()


class BalanceStates(StatesGroup):
    """User states during wallet and balance operations."""
    awaiting_amount = State()
    awaiting_balance_selection = State()


class SupportStates(StatesGroup):
    """User states during ticketing, support chat, and feedback."""
    awaiting_chat = State()
    awaiting_feedback_comment = State()


class AIStates(StatesGroup):
    """User states in AI interactions."""
    ai_chat_mode = State()
    purchase_advisor = State()


class AdminStates(StatesGroup):
    """Admin states for panel management and broadcasts."""
    awaiting_config = State()
    awaiting_broadcast = State()
    awaiting_broadcast_button_setup = State()
    awaiting_broadcast_url = State()
    awaiting_chat_reply = State()
    awaiting_manual_balance = State()
    awaiting_new_config = State()
    awaiting_price_edit = State()
    awaiting_blacklist_add = State()
    awaiting_category_add = State()
    awaiting_category_edit = State()
    awaiting_package_add = State()
    awaiting_package_edit = State()
    awaiting_coupon_create = State()
    awaiting_coupon_cat_discount = State()
    awaiting_shop_message = State()
    awaiting_user_search = State()
    awaiting_channel_id = State()
    awaiting_test_edit = State()
    awaiting_test_user_id = State()
    awaiting_test_user_select = State()
    awaiting_test_user_setting = State()
    awaiting_default_test_setting = State()


# ═══════════════════════════════════════════════════════════
# Mapping Between String Flags and Official State Objects
# ═══════════════════════════════════════════════════════════

STATE_MAP: Dict[str, State] = {
    # Order / Checkout
    "awaiting_receipt": OrderStates.awaiting_receipt,
    "awaiting_coupon_code": OrderStates.awaiting_coupon_code,
    "awaiting_order_number": OrderStates.awaiting_order_number,
    "awaiting_payment": OrderStates.awaiting_payment,
    "awaiting_payment_removed": OrderStates.awaiting_payment_removed,
    "awaiting_custom_payment_receipt_amount": OrderStates.awaiting_custom_payment_receipt_amount,
    "awaiting_custom_payment_receipt_confirm": OrderStates.awaiting_custom_payment_receipt_confirm,
    "awaiting_custom_payment_receipt_manual_days": OrderStates.awaiting_custom_payment_receipt_manual_days,
    "awaiting_custom_payment_receipt_manual_volume": OrderStates.awaiting_custom_payment_receipt_manual_volume,

    # Balance
    "awaiting_amount": BalanceStates.awaiting_amount,
    "awaiting_balance_selection": BalanceStates.awaiting_balance_selection,

    # Support
    "awaiting_chat": SupportStates.awaiting_chat,
    "awaiting_feedback_comment": SupportStates.awaiting_feedback_comment,

    # AI
    "ai_chat_mode": AIStates.ai_chat_mode,
    "purchase_advisor": AIStates.purchase_advisor,

    # Admin
    "awaiting_config": AdminStates.awaiting_config,
    "awaiting_broadcast": AdminStates.awaiting_broadcast,
    "awaiting_broadcast_button_setup": AdminStates.awaiting_broadcast_button_setup,
    "awaiting_broadcast_url": AdminStates.awaiting_broadcast_url,
    "awaiting_chat_reply": AdminStates.awaiting_chat_reply,
    "awaiting_manual_balance": AdminStates.awaiting_manual_balance,
    "awaiting_new_config": AdminStates.awaiting_new_config,
    "awaiting_price_edit": AdminStates.awaiting_price_edit,
    "awaiting_blacklist_add": AdminStates.awaiting_blacklist_add,
    "awaiting_category_add": AdminStates.awaiting_category_add,
    "awaiting_category_edit": AdminStates.awaiting_category_edit,
    "awaiting_package_add": AdminStates.awaiting_package_add,
    "awaiting_package_edit": AdminStates.awaiting_package_edit,
    "awaiting_coupon_create": AdminStates.awaiting_coupon_create,
    "awaiting_coupon_cat_discount": AdminStates.awaiting_coupon_cat_discount,
    "awaiting_shop_message": AdminStates.awaiting_shop_message,
    "awaiting_user_search": AdminStates.awaiting_user_search,
    "awaiting_channel_id": AdminStates.awaiting_channel_id,
    "awaiting_test_edit": AdminStates.awaiting_test_edit,
    "awaiting_test_user_id": AdminStates.awaiting_test_user_id,
    "awaiting_test_user_select": AdminStates.awaiting_test_user_select,
    "awaiting_test_user_setting": AdminStates.awaiting_test_user_setting,
    "awaiting_default_test_setting": AdminStates.awaiting_default_test_setting,
}

REVERSE_STATE_MAP: Dict[State, str] = {v: k for k, v in STATE_MAP.items()}


# ═══════════════════════════════════════════════════════════
# Per-User State Proxy (dict subclass)
# ═══════════════════════════════════════════════════════════

class UserStateProxy(dict):
    """
    Subclass of dict representing a single user's state.
    Provides 100% dictionary compatibility while maintaining FSM awareness
    and notifying the parent manager on changes for instant disk persistence.
    """

    def __init__(self, *args: Any, on_change: Optional[Callable[[], None]] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._on_change = on_change

    def _notify(self) -> None:
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        self._notify()

    def __delitem__(self, key: Any) -> None:
        super().__delitem__(key)
        self._notify()

    def pop(self, key: Any, *args: Any) -> Any:
        res = super().pop(key, *args)
        self._notify()
        return res

    def clear(self) -> None:
        super().clear()
        self._notify()

    def update(self, *args: Any, **kwargs: Any) -> None:
        super().update(*args, **kwargs)
        self._notify()

    def setdefault(self, key: Any, default: Any = None) -> Any:
        res = super().setdefault(key, default)
        self._notify()
        return res

    @property
    def active_fsm_state(self) -> Optional[State]:
        """Return the current active aiogram State object, or None."""
        for flag, state in STATE_MAP.items():
            if self.get(flag):
                return state
        return None

    @property
    def active_fsm_key(self) -> Optional[str]:
        """Return the current active state key string (e.g. 'awaiting_receipt'), or None."""
        for flag in STATE_MAP:
            if self.get(flag):
                return flag
        return None

    def set_fsm_state(self, state: Union[State, str], **extra: Any) -> None:
        """Switch user to a specific state and optionally update extra data."""
        target_key = REVERSE_STATE_MAP.get(state) if isinstance(state, State) else str(state)
        # Clear any other awaiting flags
        for flag in STATE_MAP:
            super().pop(flag, None)
        if target_key:
            super().__setitem__(target_key, True)
        super().update(extra)
        self._notify()

    def clear_fsm_state(self) -> None:
        """Clear all active FSM awaiting flags while preserving other state data."""
        for flag in STATE_MAP:
            super().pop(flag, None)
        self._notify()


# ═══════════════════════════════════════════════════════════
# Central FSM State Manager (dict subclass replacing user_states)
# ═══════════════════════════════════════════════════════════

class FSMStateManager(dict):
    """
    Central FSM manager for user states, subclassed from dict.
    Provides automatic disk persistence so user states survive bot restarts, reboots, and crashes.
    Preserves exact dict behavior for all existing codebase references:
      - user_states[user_id]
      - user_states.get(user_id, {})
      - user_states[user_id] = {...}
      - user_states.pop(user_id, None)
      - user_states.clear()
      - len(user_states)
      - list(user_states.items())
      - key in user_states (supports both int and str keys seamlessly)

    Adds formal aiogram FSM capabilities:
      - get_fsm_state(user_id) -> Optional[State]
      - set_fsm_state(user_id, state: State, **extra)
      - clear_fsm_state(user_id)
      - is_in_fsm_state(user_id, state: Union[State, str]) -> bool
    """

    def __init__(self, *args: Any, file_path: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if file_path:
            self._file_path = file_path
        else:
            try:
                from db_storage import DB_FILES
                self._file_path = DB_FILES.get('user_states', os.path.join("data", "user_states.json"))
            except Exception:
                self._file_path = os.path.join("data", "user_states.json")
        self._is_dirty = False
        self._save_task: Optional[asyncio.Task] = None
        self.load()

    def _norm_key(self, key: Any) -> Union[int, str]:
        """Normalize numeric keys to integers so int and str match the same entry."""
        if isinstance(key, int):
            return key
        if isinstance(key, str) and (key.isdigit() or (key.startswith('-') and key[1:].isdigit())):
            try:
                return int(key)
            except ValueError:
                pass
        return key

    def __getitem__(self, key: Any) -> UserStateProxy:
        norm_key = self._norm_key(key)
        val = super().__getitem__(norm_key)
        if isinstance(val, dict) and not isinstance(val, UserStateProxy):
            val = UserStateProxy(val, on_change=self._schedule_save)
            super().__setitem__(norm_key, val)
        elif isinstance(val, UserStateProxy) and val._on_change is None:
            val._on_change = self._schedule_save
        return val

    def __setitem__(self, key: Any, value: Any) -> None:
        norm_key = self._norm_key(key)
        if isinstance(value, dict) and not isinstance(value, UserStateProxy):
            value = UserStateProxy(value, on_change=self._schedule_save)
        elif isinstance(value, UserStateProxy):
            value._on_change = self._schedule_save
        super().__setitem__(norm_key, value)
        self._schedule_save()

    def __contains__(self, key: Any) -> bool:
        norm_key = self._norm_key(key)
        return super().__contains__(norm_key)

    def __delitem__(self, key: Any) -> None:
        norm_key = self._norm_key(key)
        super().__delitem__(norm_key)
        self._schedule_save()

    def get(self, key: Any, default: Any = None) -> Any:
        norm_key = self._norm_key(key)
        if not super().__contains__(norm_key):
            return default
        val = super().__getitem__(norm_key)
        if isinstance(val, dict) and not isinstance(val, UserStateProxy):
            val = UserStateProxy(val, on_change=self._schedule_save)
            super().__setitem__(norm_key, val)
        elif isinstance(val, UserStateProxy) and val._on_change is None:
            val._on_change = self._schedule_save
        return val

    def pop(self, key: Any, *args: Any) -> Any:
        norm_key = self._norm_key(key)
        res = super().pop(norm_key, *args)
        self._schedule_save()
        return res

    def clear(self) -> None:
        super().clear()
        self._schedule_save()

    def setdefault(self, key: Any, default: Any = None) -> Any:
        norm_key = self._norm_key(key)
        if isinstance(default, dict) and not isinstance(default, UserStateProxy):
            default = UserStateProxy(default, on_change=self._schedule_save)
        val = super().setdefault(norm_key, default)
        if isinstance(val, dict) and not isinstance(val, UserStateProxy):
            val = UserStateProxy(val, on_change=self._schedule_save)
            super().__setitem__(norm_key, val)
        self._schedule_save()
        return val

    # ─── Persistence Methods ───

    def _schedule_save(self) -> None:
        """Schedule an atomic save to disk with a brief debounce."""
        self._is_dirty = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            if self._save_task is None or self._save_task.done():
                self._save_task = loop.create_task(self._debounced_save())
        else:
            self.save()

    async def _debounced_save(self) -> None:
        try:
            while self._is_dirty:
                await asyncio.sleep(0.3)  # 300ms debounce
                if not self._is_dirty:
                    break
                self._is_dirty = False
                snapshot = self.build_snapshot()
                from db_storage import save_json
                await asyncio.to_thread(save_json, self._file_path, snapshot)
        except asyncio.CancelledError:
            self.save()
        except Exception as e:
            logger.debug(f"Debounced save note: {e}")

    def build_snapshot(self) -> Dict[str, Any]:
        """Build an isolated serializable snapshot of active unexpired user states."""
        from db_storage import fast_snapshot
        data_to_save: Dict[str, Any] = {}
        for k, v in list(super().items()):
            if isinstance(v, dict) and v:
                ts = v.get("timestamp")
                if ts:
                    try:
                        age = _timestamp_age_seconds(ts)
                        if age is not None and age > 86400:
                            continue
                    except Exception:
                        pass
                data_to_save[str(k)] = fast_snapshot(dict(v))
        return data_to_save

    def save(self) -> bool:
        """Save all active unexpired user states atomically to disk."""
        try:
            data_to_save = self.build_snapshot()
            from db_storage import save_json
            return save_json(self._file_path, data_to_save)
        except Exception as e:
            logger.error(f"Error saving user_states to disk: {e}")
            return False

    def load(self) -> bool:
        """Load user states from disk into memory, restoring active sessions."""
        try:
            if not os.path.exists(self._file_path):
                return False
            from db_storage import load_json
            raw = load_json(self._file_path, use_cache=False)
            if not isinstance(raw, dict):
                return False

            loaded_count = 0
            for k_str, val in raw.items():
                if isinstance(val, dict) and val:
                    ts = val.get("timestamp")
                    if ts:
                        try:
                            age = _timestamp_age_seconds(ts)
                            if age is not None and age > 86400:
                                continue
                        except Exception:
                            pass
                    norm_k = self._norm_key(k_str)
                    proxy = UserStateProxy(val, on_change=self._schedule_save)
                    super().__setitem__(norm_k, proxy)
                    loaded_count += 1
            if loaded_count > 0:
                logger.info(f"💾 Restored {loaded_count} active user states from disk")
            return True
        except Exception as e:
            logger.error(f"Error loading user_states from disk: {e}")
            return False

    # ─── FSM Interface Methods ───

    def get_fsm_state(self, user_id: int) -> Optional[State]:
        """Get the current active State for a user, or None."""
        st = self.get(user_id)
        if isinstance(st, UserStateProxy):
            return st.active_fsm_state
        elif isinstance(st, dict):
            for flag, state in STATE_MAP.items():
                if st.get(flag):
                    return state
        return None

    def get_active_fsm_key(self, user_id: int) -> Optional[str]:
        """Get the active state string key for a user (e.g. 'awaiting_receipt')."""
        st = self.get(user_id)
        if isinstance(st, UserStateProxy):
            return st.active_fsm_key
        elif isinstance(st, dict):
            for flag in STATE_MAP:
                if st.get(flag):
                    return flag
        return None

    def set_fsm_state(self, user_id: int, state: Union[State, str], **extra: Any) -> UserStateProxy:
        """
        Formally set a user's FSM state.
        Automatically updates corresponding flag, extra attributes, and persists to disk.
        """
        norm_key = self._norm_key(user_id)
        current = super().get(norm_key)
        if current is None or not isinstance(current, dict):
            current = UserStateProxy(on_change=self._schedule_save)
            super().__setitem__(norm_key, current)
        elif not isinstance(current, UserStateProxy):
            current = UserStateProxy(current, on_change=self._schedule_save)
            super().__setitem__(norm_key, current)

        current.set_fsm_state(state, **extra)
        self._schedule_save()
        return current

    def clear_fsm_state(self, user_id: int) -> None:
        """Clear active FSM state for a user while preserving non-state context."""
        st = self.get(user_id)
        if isinstance(st, UserStateProxy):
            st.clear_fsm_state()
        elif isinstance(st, dict):
            for flag in STATE_MAP:
                st.pop(flag, None)
            self._schedule_save()

    def is_in_fsm_state(self, user_id: int, state: Union[State, str]) -> bool:
        """Check if user is in a given state (State object or string flag)."""
        current_state = self.get_fsm_state(user_id)
        if isinstance(state, State):
            return current_state == state
        current_key = self.get_active_fsm_key(user_id)
        if current_key == state:
            return True
        st = self.get(user_id)
        return bool(isinstance(st, dict) and st.get(state))

    def get_data(self, user_id: int) -> Dict[str, Any]:
        """Get user state data dictionary."""
        return self.get(user_id, {})

    def update_data(self, user_id: int, **data: Any) -> Dict[str, Any]:
        """Update extra data in user's state."""
        st = self.setdefault(user_id, UserStateProxy(on_change=self._schedule_save))
        st.update(data)
        return st


# ═══════════════════════════════════════════════════════════
# Aiogram Filter for FSM States
# ═══════════════════════════════════════════════════════════

class InState(BaseFilter):
    """
    Aiogram BaseFilter checking whether an incoming event comes from a user
    in one of the specified FSM States or state flags.

    Usage:
      @dp.message(InState(OrderStates.awaiting_receipt))
      @dp.message(InState("awaiting_receipt", "awaiting_coupon_code"))
    """

    def __init__(self, *states: Union[State, str]) -> None:
        self.target_states = states

    async def __call__(self, event: Any, user_states: Optional[FSMStateManager] = None) -> bool:
        user = getattr(event, "from_user", None)
        if not user:
            return False

        user_id = user.id
        from user_manager import user_states as manager
        states_mgr = user_states or manager

        current_state = states_mgr.get_fsm_state(user_id)
        current_key = states_mgr.get_active_fsm_key(user_id)
        user_dict = states_mgr.get(user_id, {})

        for target in self.target_states:
            if isinstance(target, State) and current_state == target:
                return True
            if isinstance(target, str):
                if current_key == target or user_dict.get(target):
                    return True

        return False

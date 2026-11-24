"""
core/state_stores.py
--------------------
Global in-memory stores and TTL-backed temporary dictionary stores.
"""

from typing import Any
from time import monotonic
from collections.abc import MutableMapping


class TempStore(MutableMapping):
    """دیکشنری موقت با قابلیت انقضای خودکار داده‌ها (TTL) جهت جلوگیری از نشت حافظه"""

    def __init__(self, ttl: int = 900):
        self.ttl = ttl
        self._data: dict[Any, tuple[float, Any]] = {}

    def _is_expired(self, exp: float) -> bool:
        return monotonic() > exp

    def __getitem__(self, key):
        if key not in self._data:
            raise KeyError(key)
        exp, val = self._data[key]
        if self._is_expired(exp):
            del self._data[key]
            raise KeyError(key)
        return val

    def __setitem__(self, key, value):
        self._data[key] = (monotonic() + self.ttl, value)

    def __delitem__(self, key):
        del self._data[key]

    def __contains__(self, key):
        if key not in self._data:
            return False
        exp, _ = self._data[key]
        if self._is_expired(exp):
            del self._data[key]
            return False
        return True

    def __iter__(self):
        now = monotonic()
        valid_keys = [k for k, (exp, _) in self._data.items() if exp > now]
        return iter(valid_keys)

    def __len__(self):
        now = monotonic()
        return sum(1 for exp, _ in self._data.values() if exp > now)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key, default=None):
        if key not in self._data:
            return default
        exp, val = self._data.pop(key)
        if self._is_expired(exp):
            return default
        return val

    def cleanup(self) -> int:
        now = monotonic()
        expired_keys = [k for k, (exp, _) in self._data.items() if exp <= now]
        for k in expired_keys:
            self._data.pop(k, None)
        return len(expired_keys)


class BoundedTTLCache(dict):
    """دیکشنری با ظرفیت محدود و پاکسازی خودکار ورودی‌های منقضی‌شده جهت جلوگیری از نشت حافظه"""

    def __init__(self, maxsize: int = 2000):
        super().__init__()
        self.maxsize = maxsize

    def __setitem__(self, key: Any, value: Any):
        if len(self) >= self.maxsize:
            now = monotonic()
            expired = [
                k for k, v in self.items()
                if isinstance(v, tuple) and len(v) > 0 and isinstance(v[0], (int, float)) and v[0] < now
            ]
            for k in expired:
                super().__delitem__(k)
            if len(self) >= self.maxsize:
                to_remove = len(self) - self.maxsize + 1
                for k in list(self.keys())[:to_remove]:
                    super().__delitem__(k)
        super().__setitem__(key, value)


# Singletons used across inbound selection and admin flows
TEMP_INBOUND_SELECTION: TempStore = TempStore(ttl=900)
INBOUND_BACK_DATA: TempStore = TempStore(ttl=900)
USER_INBOUND_SELECTION: dict[str, Any] = {}
USER_TEST_SETTINGS: dict[str, Any] = {}
CONFIG_LINKS_CACHE: dict[int, dict] = {}
_tg_user_cache: dict[int, tuple[float, dict]] = BoundedTTLCache(maxsize=2000)



from user_manager import user_states


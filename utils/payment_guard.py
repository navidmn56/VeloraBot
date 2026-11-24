"""Concurrency control and idempotency guards for user financial transactions."""

import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Set


class PaymentInProgressError(Exception):
    """Raised when a payment transaction is already actively running for the user."""
    pass


class UserPaymentGuard:
    """
    Guarantees mutual exclusion and prevents race conditions / double spending
    during user payment transactions (e.g. paying via account balance).
    """

    def __init__(self):
        self._active_users: Set[int] = set()
        self._user_locks: Dict[int, asyncio.Lock] = {}
        self._master_lock = asyncio.Lock()

    async def _get_lock(self, user_id: int) -> asyncio.Lock:
        async with self._master_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            return self._user_locks[user_id]

    @asynccontextmanager
    async def lock_user(self, user_id: int):
        """
        Context manager to lock a user for a payment operation.
        Raises PaymentInProgressError immediately if a payment is already in flight.
        """
        uid = int(user_id)
        lock = await self._get_lock(uid)

        async with self._master_lock:
            if uid in self._active_users:
                raise PaymentInProgressError(f"Payment already in progress for user {uid}")
            self._active_users.add(uid)

        await lock.acquire()
        try:
            yield
        finally:
            try:
                lock.release()
            finally:
                async with self._master_lock:
                    self._active_users.discard(uid)

    def is_in_progress(self, user_id: int) -> bool:
        """Check if payment is currently active for user."""
        return int(user_id) in self._active_users


class OrderApprovalGuard:
    """
    Guarantees mutual exclusion and idempotency during admin order approvals.
    Prevents duplicate config creation if an admin clicks approve multiple times
    or multiple admins approve the same order simultaneously.
    """

    def __init__(self):
        self._active_orders: Set[int] = set()
        self._order_locks: Dict[int, asyncio.Lock] = {}
        self._master_lock = asyncio.Lock()

    async def _get_lock(self, order_id: int) -> asyncio.Lock:
        async with self._master_lock:
            if order_id not in self._order_locks:
                self._order_locks[order_id] = asyncio.Lock()
            return self._order_locks[order_id]

    @asynccontextmanager
    async def lock_order(self, order_id: int):
        """
        Context manager to lock an order for approval / fulfillment.
        Raises PaymentInProgressError immediately if the order is already in flight.
        """
        oid = int(order_id)
        lock = await self._get_lock(oid)

        async with self._master_lock:
            if oid in self._active_orders:
                raise PaymentInProgressError(f"Approval already in progress for order {oid}")
            self._active_orders.add(oid)

        await lock.acquire()
        try:
            yield
        finally:
            try:
                lock.release()
            finally:
                async with self._master_lock:
                    self._active_orders.discard(oid)

    def is_in_progress(self, order_id: int) -> bool:
        """Check if order approval is currently active."""
        return int(order_id) in self._active_orders


# Global singleton instances
payment_guard = UserPaymentGuard()
order_guard = OrderApprovalGuard()


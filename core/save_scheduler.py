"""
core/save_scheduler.py
----------------------
Debounced background database save worker and scheduler.
"""

import asyncio
import logging
import time
from typing import Optional, Set

from database import build_save_snapshots, save_all, save_snapshots

logger = logging.getLogger(__name__)

_save_queue: asyncio.Queue = asyncio.Queue()
_save_task: asyncio.Task | None = None
_pending_keys: Set[str] = set()
_pending_all: bool = False


def set_save_task(task: asyncio.Task | None) -> None:
    """تنظیم Task مربوط به ورکر debounce"""
    global _save_task
    _save_task = task


def get_save_task() -> asyncio.Task | None:
    """دریافت Task مربوط به ورکر debounce"""
    global _save_task
    return _save_task


def _is_worker_active() -> bool:
    if _save_task is None or _save_task.done():
        return False
    try:
        loop = asyncio.get_running_loop()
        return _save_task.get_loop() is loop
    except RuntimeError:
        return False


def schedule_save(delay: float = 2.0) -> None:
    """درخواست ذخیره‌سازی پایگاه‌داده با debounce برای کاهش فشار I/O دیسک"""
    global _pending_all
    if not _is_worker_active():
        try:
            save_all()
        except Exception as e:
            logger.error(f"Error executing synchronous save_all: {e}")
        return

    try:
        _pending_all = True
        _save_queue.put_nowait(("all", delay))
    except Exception as e:
        logger.error(f"Error queueing save request: {e}")
        try:
            save_all()
        except Exception:
            pass


def schedule_file_save(db_key: str, delay: float = 1.0) -> None:
    """درخواست ذخیره‌سازی debounce شده فقط برای یک فایل دیتابیس مشخص"""
    if not db_key:
        schedule_save(delay=delay)
        return

    if not _is_worker_active():
        try:
            bundle = build_save_snapshots(keys={db_key})
            save_snapshots(bundle)
        except Exception as e:
            logger.error(f"Error executing synchronous save for {db_key}: {e}")
        return

    try:
        if not _pending_all:
            _pending_keys.add(db_key)
        _save_queue.put_nowait((db_key, delay))
    except Exception as e:
        logger.error(f"Error queueing save request for {db_key}: {e}")
        try:
            bundle = build_save_snapshots(keys={db_key})
            save_snapshots(bundle)
        except Exception:
            pass


def _flush_pending_sync() -> None:
    global _pending_all
    if _pending_all:
        _pending_all = False
        _pending_keys.clear()
        save_all()
    elif _pending_keys:
        keys = set(_pending_keys)
        _pending_keys.clear()
        bundle = build_save_snapshots(keys=keys)
        save_snapshots(bundle)


async def _debounced_save_worker():
    """Worker پس‌زمینه برای جمع‌آوری و اجرای debounce شده‌ی save_all"""
    global _pending_all
    logger.info("💾 Debounced save worker started")
    max_batch_wait = 8.0
    while True:
        try:
            item = await _save_queue.get()
            _save_queue.task_done()

            if isinstance(item, tuple):
                req_key, delay = item
            else:
                req_key, delay = "all", item

            if req_key == "all":
                _pending_all = True
                _pending_keys.clear()
            else:
                if not _pending_all:
                    _pending_keys.add(req_key)

            wait_time = delay if isinstance(delay, (int, float)) and delay > 0 else 2.0
            batch_start = time.monotonic()

            while True:
                remaining_max = max_batch_wait - (time.monotonic() - batch_start)
                if remaining_max <= 0:
                    break
                timeout = min(wait_time, remaining_max)
                try:
                    next_item = await asyncio.wait_for(_save_queue.get(), timeout=timeout)
                    _save_queue.task_done()
                    if isinstance(next_item, tuple):
                        next_key, next_delay = next_item
                    else:
                        next_key, next_delay = "all", next_item

                    if next_key == "all":
                        _pending_all = True
                        _pending_keys.clear()
                    elif not _pending_all:
                        _pending_keys.add(next_key)

                    if isinstance(next_delay, (int, float)) and next_delay > 0:
                        wait_time = min(wait_time, next_delay)
                except asyncio.TimeoutError:
                    break

            if _pending_all:
                _pending_all = False
                _pending_keys.clear()
                bundle = build_save_snapshots(save_blacklist=True)
            elif _pending_keys:
                keys = set(_pending_keys)
                _pending_keys.clear()
                bundle = build_save_snapshots(keys=keys)
            else:
                continue

            await asyncio.to_thread(save_snapshots, bundle)
            logger.debug("💾 Debounced save executed successfully")
        except asyncio.CancelledError:
            logger.info("💾 Debounced save worker cancelled")
            try:
                _flush_pending_sync()
            except Exception:
                pass
            break
        except Exception as e:
            logger.error(f"Error in debounced save worker: {e}", exc_info=True)
            await asyncio.sleep(1)

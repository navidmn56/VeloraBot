"""
core/save_scheduler.py
----------------------
Debounced background database save worker and scheduler.
"""

import asyncio
import logging
from database import save_all

logger = logging.getLogger(__name__)

_save_queue: asyncio.Queue = asyncio.Queue()
_save_task: asyncio.Task | None = None


def set_save_task(task: asyncio.Task | None) -> None:
    """تنظیم Task مربوط به ورکر debounce"""
    global _save_task
    _save_task = task


def get_save_task() -> asyncio.Task | None:
    """دریافت Task مربوط به ورکر debounce"""
    global _save_task
    return _save_task


def schedule_save(delay: float = 2.0) -> None:
    """درخواست ذخیره‌سازی پایگاه‌داده با debounce برای کاهش فشار I/O دیسک"""
    global _save_task
    if _save_task is None or _save_task.done():
        try:
            save_all()
        except Exception as e:
            logger.error(f"Error executing synchronous save_all: {e}")
        return

    try:
        _save_queue.put_nowait(delay)
    except Exception as e:
        logger.error(f"Error queueing save request: {e}")
        try:
            save_all()
        except Exception:
            pass


async def _debounced_save_worker():
    """Worker پس‌زمینه برای جمع‌آوری و اجرای debounce شده‌ی save_all"""
    logger.info("💾 Debounced save worker started")
    while True:
        try:
            delay = await _save_queue.get()
            _save_queue.task_done()

            wait_time = delay if isinstance(delay, (int, float)) and delay > 0 else 2.0
            while True:
                try:
                    next_delay = await asyncio.wait_for(_save_queue.get(), timeout=wait_time)
                    _save_queue.task_done()
                    if isinstance(next_delay, (int, float)) and next_delay > 0:
                        wait_time = next_delay
                except asyncio.TimeoutError:
                    break

            await asyncio.to_thread(save_all)
            logger.debug("💾 Debounced save_all executed successfully")
        except asyncio.CancelledError:
            logger.info("💾 Debounced save worker cancelled")
            try:
                save_all()
            except Exception:
                pass
            break
        except Exception as e:
            logger.error(f"Error in debounced save worker: {e}", exc_info=True)
            await asyncio.sleep(1)

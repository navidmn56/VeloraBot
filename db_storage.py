"""Low-level file storage, atomic writes, and disk cache management."""

import json
import logging
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)
    logger.info(f"Created data folder {DATA_DIR}")

DB_FILES = {
    'users': os.path.join(DATA_DIR, "users.json"),
    'orders': os.path.join(DATA_DIR, "orders.json"),
    'referrals': os.path.join(DATA_DIR, "referral.json"),
    'configs': os.path.join(DATA_DIR, "configs.json"),
    'feedback': os.path.join(DATA_DIR, "feedback.json"),
    'chats': os.path.join(DATA_DIR, "chats.json"),
    'blacklist': os.path.join(DATA_DIR, "blacklist.json"),
    'user_states': os.path.join(DATA_DIR, "user_states.json"),
}

_DB_CACHEABLE_NAMES = {os.path.basename(p) for p in DB_FILES.values()}
_storage_lock = threading.RLock()

_db_cache: Dict[str, Any] = {}
_db_modified: Set[str] = set()
_last_save_time: Dict[str, float] = {}


def fast_snapshot(obj: Any) -> Any:
    """Create a thread-safe structural snapshot of JSON-like collections without deepcopy memo overhead."""
    if isinstance(obj, dict):
        return {k: fast_snapshot(v) for k, v in list(obj.items())}
    if isinstance(obj, list):
        return [fast_snapshot(item) for item in list(obj)]
    if isinstance(obj, tuple):
        return [fast_snapshot(item) for item in obj]
    if isinstance(obj, set):
        return list(obj)
    return obj


def _is_cacheable_db_path(file_path: str) -> bool:
    """Only cache primary database files, never timestamped backup archives."""
    try:
        abs_target = os.path.abspath(file_path)
        for db_path in DB_FILES.values():
            if os.path.abspath(db_path) == abs_target:
                return True
    except Exception:
        pass
    return False


def ensure_data_directory():
    """Ensure data and backup directories exist and initialize database files."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
        logger.info(f"Data folder {DATA_DIR} created")

    backup_dir = os.path.join(DATA_DIR, "backups")
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir, exist_ok=True)
        logger.info(f"✅ folder {backup_dir} created")

    for name, file_path in DB_FILES.items():
        if not os.path.exists(file_path):
            if name == 'configs':
                default_data = {'configs': [], 'last_id': 0}
            elif name == 'blacklist':
                default_data = {'users': [], 'last_updated': datetime.now(TEHRAN_TZ).isoformat()}
            else:
                default_data = {}

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, ensure_ascii=False, indent=2)
            logger.info(f"File {name}.json created (new)")
        else:
            size = os.path.getsize(file_path)
            logger.info(f"File {name}.json already exists (size: {size:,} bytes) - unchanged")

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content:
                        logger.warning(f"File {name}.json is empty! Skipping rewrite.")
                    else:
                        json.loads(content)
                        logger.info(f"   File content for {name}.json is valid")
            except json.JSONDecodeError as e:
                logger.error(f"File {name}.json is corrupted: {e}")
                logger.info("   Run a manual repair using the backup")


def save_json(file_path: str, data: Any) -> bool:
    """Save data to file_path atomically using a unique temporary file."""
    temp_file = None
    try:
        filename = os.path.basename(file_path)
        file_dir = os.path.dirname(file_path)

        logger.debug(f"Saving {filename} to path: {os.path.abspath(file_path)}")

        if file_dir:
            os.makedirs(file_dir, exist_ok=True)

        if data is None:
            data = {}

        # Serialize in memory before touching disk; retry with snapshot if a live dict mutated concurrently
        payload = None
        for attempt in range(3):
            try:
                source = data if attempt == 0 else fast_snapshot(data)
                payload = json.dumps(source, ensure_ascii=False, indent=2)
                break
            except RuntimeError:
                if attempt == 2:
                    raise

        temp_file = f"{file_path}.{os.getpid()}.{threading.get_ident()}.tmp"

        with _storage_lock:
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())

            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                os.replace(temp_file, file_path)
                temp_file = None
            else:
                logger.error(f"Temporary file {temp_file} was not created or is empty")
                return False

        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            record_count = len(data) if isinstance(data, dict) else 'N/A'
            logger.debug(f"{filename} saved successfully ({file_size:,} bytes, {record_count} record(s))")
        else:
            logger.error(f"{filename} was not saved!")
            return False

        if _is_cacheable_db_path(file_path):
            try:
                _db_cache[file_path] = data.copy() if isinstance(data, dict) else data
            except RuntimeError:
                pass
        if filename == 'configs.json':
            try:
                from config import refresh_gemini_prompt
                refresh_gemini_prompt()
                logger.debug("Gemini system prompt refreshed after saving configs.json")
            except ImportError:
                logger.debug("Skipping refresh - config.py not available")
            except Exception as e:
                logger.warning(f"⚠️ Error refreshing prompt: {e}")

        return True

    except Exception as e:
        logger.error(f"Failed to save {os.path.basename(file_path)}: {e}", exc_info=True)
        return False
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


def load_json(file_path: str, use_cache: bool = True) -> dict:
    """Load JSON from disk or in-memory cache."""
    filename = os.path.basename(file_path)

    if use_cache and file_path in _db_cache and file_path not in _db_modified:
        logger.debug(f"📂 {filename} loaded from cache")
        return _db_cache[file_path]

    logger.info(f"📂 loading {filename} from disk... path: {os.path.abspath(file_path)}")

    if not os.path.exists(file_path):
        logger.error(f"❌ file {filename} does not exist! Path: {file_path}")

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        logger.info(f"✅ file {filename} created (empty)")
        return {}

    if os.path.getsize(file_path) == 0:
        logger.warning(f"⚠️ file {filename} is empty - size: 0 bytes")
        return {}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

            if not content or content.strip() == '':
                logger.warning(f"⚠️ file {filename} has no content")
                return {}

            data = json.loads(content)

            if use_cache and _is_cacheable_db_path(file_path):
                _db_cache[file_path] = data.copy() if isinstance(data, dict) else data

            logger.info(f"✅ {filename} loaded - {len(data) if isinstance(data, dict) else 'N/A'} items")
            logger.info(
                f"   Sample data: {str(list(data.keys())[:3]) if isinstance(data, dict) and data else 'empty'}"
            )
            if filename == 'configs.json':
                try:
                    from config import refresh_gemini_prompt
                    refresh_gemini_prompt()
                    logger.info('🔄 GEMINI_SYSTEM_PROMPT updated after loading configs.json')
                except ImportError:
                    logger.debug("Skipping refresh - config.py not available")
                except Exception as e:
                    logger.warning(f"Refresh prompt failed: {e}")

            return data

    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON error in {filename}: {e}")
        logger.error(f"   JSON file content omitted for security; filename: {filename}")
        return {}

    except Exception as e:
        logger.error(f"❌ Error loading {filename}: {e}", exc_info=True)
        return {}


def clear_db_cache():
    """Clear memory cache for database files."""
    _db_cache.clear()
    _db_modified.clear()


def get_db_cache_size() -> int:
    """Return number of cached database files."""
    return len(_db_cache)

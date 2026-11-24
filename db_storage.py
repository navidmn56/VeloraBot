"""Low-level file storage, atomic writes, and disk cache management."""

import json
import logging
import os
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

_db_cache: Dict[str, Any] = {}
_db_modified: Set[str] = set()
_last_save_time: Dict[str, float] = {}


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
    """Save data to file_path atomically using a temporary file."""
    try:
        filename = os.path.basename(file_path)
        file_dir = os.path.dirname(file_path)

        logger.info(f"Saving {filename} to path: {os.path.abspath(file_path)}")

        os.makedirs(file_dir, exist_ok=True)

        temp_file = file_path + '.tmp'

        if data is None:
            data = {}

        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            if os.path.exists(file_path):
                os.replace(temp_file, file_path)
            else:
                os.rename(temp_file, file_path)
        else:
            logger.error(f"Temporary file {temp_file} was not created or is empty")
            return False

        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            logger.info(f"{filename} saved successfully ({file_size:,} bytes)")

            with open(file_path, 'r', encoding='utf-8') as f:
                verify_data = json.load(f)
            logger.info(
                f"✅ Final confirmation: {len(verify_data) if isinstance(verify_data, dict) else 'N/A'} record(s) in {filename}"
            )
        else:
            logger.error(f"{filename} was not saved!")
            return False

        _db_cache[file_path] = data.copy() if isinstance(data, dict) else data
        if filename == 'configs.json':
            try:
                from config import refresh_gemini_prompt
                refresh_gemini_prompt()
                logger.info("Gemini system prompt refreshed after saving configs.json")
            except ImportError:
                logger.debug("Skipping refresh - config.py not available")
            except Exception as e:
                logger.warning(f"⚠️ Error refreshing prompt: {e}")

        return True

    except Exception as e:
        logger.error(f"Failed to save {os.path.basename(file_path)}: {e}", exc_info=True)
        return False


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

            if use_cache:
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

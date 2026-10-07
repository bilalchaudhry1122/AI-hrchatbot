"""Small JSON files that must survive a crash.

Writes go to a temp file next to the target and are swapped in with
os.replace, which is atomic. A reader therefore sees either the whole old
file or the whole new one, never a half-written mix.
"""

import json
import os
import time
from pathlib import Path


def read_json(file_path, default=None, *, logger=None, quarantine=True):
    """Read a JSON file, tolerating a missing or damaged one."""
    path = Path(file_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        if quarantine:
            _quarantine(path, logger)
        return default


def _quarantine(path, logger=None):
    broken = path.with_suffix(path.suffix + ".broken")
    try:
        os.replace(path, broken)
    except OSError:
        return
    if logger:
        logger.error("file was unreadable and was set aside", {
            "file": str(path),
            "movedTo": str(broken),
        })


def write_json_atomic(file_path, data):
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, default=str)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    last_error = None
    for attempt in range(6):
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            return
        except OSError as error:
            last_error = error
            if getattr(error, "winerror", None) != 32 and getattr(error, "errno", None) not in {11, 13, 16}:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise last_error

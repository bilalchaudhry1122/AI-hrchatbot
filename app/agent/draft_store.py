"""Half-filled leave forms, kept on disk.

A leave draft used to live only in memory, so restarting the bot silently threw
away a form someone was in the middle of. This behaves like the plain dict it
replaces, and saves after every change.
"""

import threading
from collections.abc import MutableMapping
from datetime import date

from app.json_store import read_json, write_json_atomic

DATE_FIELDS = ("start_date", "end_date")


def _encode(draft):
    out = {}
    for key, value in (draft or {}).items():
        if isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def _decode(draft):
    out = {}
    for key, value in (draft or {}).items():
        if key in DATE_FIELDS and isinstance(value, str) and value:
            try:
                out[key] = date.fromisoformat(value[:10])
                continue
            except ValueError:
                pass
        out[key] = value
    return out


class DraftStore(MutableMapping):
    """A dict of channel id -> leave draft that writes itself to disk."""

    def __init__(self, file_path=None, logger=None):
        self.file_path = file_path
        self.logger = logger
        self.lock = threading.RLock()
        self.data = self._load()

    def _load(self):
        if not self.file_path:
            return {}
        parsed = read_json(self.file_path, default={}, logger=self.logger)
        if not isinstance(parsed, dict):
            return {}
        drafts = parsed.get("drafts")
        if not isinstance(drafts, dict):
            return {}
        return {str(key): _decode(value) for key, value in drafts.items() if isinstance(value, dict)}

    def _save(self):
        if not self.file_path:
            return
        try:
            write_json_atomic(self.file_path, {"drafts": {key: _encode(value) for key, value in self.data.items()}})
        except OSError as error:
            if self.logger:
                self.logger.warn("Could not save leave drafts", {"message": str(error)})

    def __getitem__(self, key):
        return self.data[str(key)]

    def __setitem__(self, key, value):
        # Store the object itself, not a copy: callers mutate the draft they
        # handed over and expect to see those changes back, exactly as a plain
        # dict behaves. save() flushes anything mutated after assignment.
        with self.lock:
            self.data[str(key)] = value if isinstance(value, dict) else dict(value or {})
            self._save()

    def save(self):
        """Persist changes made to a draft after it was stored."""
        with self.lock:
            self._save()

    def __delitem__(self, key):
        with self.lock:
            del self.data[str(key)]
            self._save()

    def __iter__(self):
        return iter(dict(self.data))

    def __len__(self):
        return len(self.data)

    def pop(self, key, default=None):
        with self.lock:
            found = self.data.pop(str(key), default)
            self._save()
            return found

    def clear(self):
        with self.lock:
            self.data.clear()
            self._save()


def create_draft_store(file_path=None, logger=None):
    return DraftStore(file_path, logger=logger)

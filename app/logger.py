import json
import re
from datetime import datetime, timezone

LEVELS = {"error": 0, "warn": 1, "info": 2, "debug": 3}

_SECRET = re.compile(r"(sk-|nvapi-|AIza|ghp_|pcsk_)[A-Za-z0-9_\-]+")
_LONG = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")


def _redact(value):
    if not isinstance(value, str):
        return value
    return _LONG.sub("[redacted]", _SECRET.sub("[redacted]", value))


def _serialize(meta):
    if meta is None:
        return ""
    try:
        return " " + _redact(json.dumps(meta, default=str))
    except Exception:
        return " [unserializable]"


class Logger:
    def __init__(self, level="debug"):
        self.min = LEVELS.get(level, LEVELS["debug"])

    def _write(self, name, message, meta=None):
        line = f"[{datetime.now(timezone.utc).isoformat()}] [{name}] {message}{_serialize(meta)}"
        print(line)

    def error(self, message, meta=None):
        if self.min >= LEVELS["error"]:
            self._write("error", message, meta)

    def warn(self, message, meta=None):
        if self.min >= LEVELS["warn"]:
            self._write("warn", message, meta)

    def info(self, message, meta=None):
        if self.min >= LEVELS["info"]:
            self._write("info", message, meta)

    def debug(self, message, meta=None):
        if self.min >= LEVELS["debug"]:
            self._write("debug", message, meta)


def create_logger(level="debug"):
    return Logger(level)

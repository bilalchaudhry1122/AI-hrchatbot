"""Shared field helpers for HR record rows (MySQL client shape)."""

import re
import time

from app.errors import AppError, ErrorCodes

UNKNOWN_FIELD_RE = re.compile(r'Unknown field name:\s*"([^"]+)"', re.I)

RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.6


def escape_formula_value(value):
    """Escape a value for use inside single quotes in equality filters."""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _status_of(error):
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status:
        return status
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None)


def is_retryable(error):
    status = _status_of(error)
    if status in RETRY_STATUSES:
        return True
    if status:
        return False
    text = str(error).lower()
    return "429" in text or "too many requests" in text or "lock wait" in text


def db_call(action, *, op="", logger=None, sleep=time.sleep):
    """Run one DB call, retrying briefly on transient errors."""
    last_error = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return action()
        except Exception as error:  # noqa: BLE001 - re-raised below
            last_error = error
            if attempt == RETRY_ATTEMPTS - 1 or not is_retryable(error):
                break
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            if logger:
                logger.warn("Database is busy; retrying", {"op": op, "attempt": attempt + 1, "delay": delay})
            sleep(delay)
    if logger:
        logger.error("Database error", {"op": op, "message": str(last_error)[:300]})
    raise wrap_db_error(last_error) from last_error


def db_error_text(error):
    parts = [str(error or "")]
    cause = getattr(error, "cause", None)
    if cause:
        parts.append(str(cause))
    origin = getattr(error, "__cause__", None)
    if origin:
        parts.append(str(origin))
    for item in (error, cause, origin):
        response = getattr(item, "response", None) if item is not None else None
        if response is None:
            continue
        try:
            parts.append(str(response.text)[:500])
        except Exception:
            pass
    return " ".join(parts)


def is_unknown_select_option(error):
    text = db_error_text(error).upper()
    return "INVALID_MULTIPLE_CHOICE" in text or "UNKNOWN_FIELD_OPTION" in text


def is_unknown_field_name(error):
    text = db_error_text(error).upper()
    return "UNKNOWN_FIELD_NAME" in text or "UNKNOWN COLUMN" in text


def missing_field_name(error):
    match = UNKNOWN_FIELD_RE.search(db_error_text(error))
    return match.group(1) if match else None


def field(record, *names, default=None):
    fields = record.get("fields") if isinstance(record, dict) else {}
    fields = fields or {}
    for name in names:
        if name in fields and fields[name] not in (None, ""):
            return fields[name]
    return default


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        if not value:
            return ""
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("name") or first.get("id") or first)
        return str(first)
    return str(value)


def as_number(value, default=0):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_record_id(value):
    text = as_text(value).strip()
    return text or None


def wrap_db_error(error):
    text = str(error)
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status in {401, 403} or "1045" in text or "Access denied" in text or "Unauthorized" in text:
        return AppError(ErrorCodes.DB_AUTH, "Database authentication failed.", cause=error, status=status)
    return AppError(ErrorCodes.DB_UNAVAILABLE, "Database is unavailable.", cause=error, status=status)

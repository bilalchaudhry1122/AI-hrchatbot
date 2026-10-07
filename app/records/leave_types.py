import time

from app.records.fields import db_call, as_text, field
from app.errors import AppError, ErrorCodes

# Leave types change about once a year but are read on every HR message.
# Cache them per client for a short window to stay well under Airtable's
# per-base rate limit. Set to 0 to disable.
CACHE_TTL_SECONDS = 300
_CACHE_ATTR = "_leave_types_cache"


def _cached_types(client):
    if not CACHE_TTL_SECONDS:
        return None
    cached = getattr(client, _CACHE_ATTR, None)
    if not cached:
        return None
    stored_at, types = cached
    if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
        return None
    return types


def _store_types(client, types):
    if not CACHE_TTL_SECONDS:
        return
    try:
        setattr(client, _CACHE_ATTR, (time.monotonic(), types))
    except AttributeError:
        # Clients that do not accept attributes simply go uncached.
        pass


def clear_leave_type_cache(client):
    try:
        delattr(client, _CACHE_ATTR)
    except AttributeError:
        pass


def record_to_leave_type(record):
    if not record:
        return None
    active = field(record, "Active", "active", default=True)
    if isinstance(active, str):
        active = active.lower() in {"1", "true", "yes", "active"}
    return {
        "id": record.get("id"),
        "name": as_text(field(record, "Leave Type", "Name", "name")),
        "code": as_text(field(record, "Code", "code")).upper(),
        "description": as_text(field(record, "Description", "description")),
        "active": bool(active),
    }


def get_active_leave_types(client, *, logger=None):
    cached = _cached_types(client)
    if cached is not None:
        return list(cached)
    records = db_call(
        lambda: client.table("leaveTypes").all(),
        op="leave_types",
        logger=logger,
    )
    types = [record_to_leave_type(item) for item in records or []]
    active = [item for item in types if item and item.get("active") and item.get("name")]
    _store_types(client, active)
    return list(active)


def get_leave_type_by_name(client, name, *, logger=None):
    wanted = _normalize_leave_query(name)
    if not wanted:
        raise AppError(ErrorCodes.LEAVE_TYPE_INVALID, "That leave type is not available. Please choose Annual Leave, Sick Leave, or Casual Leave.", expose=True)
    for item in get_active_leave_types(client, logger=logger):
        if _leave_type_matches(item, wanted):
            return item
    raise AppError(
        ErrorCodes.LEAVE_TYPE_INVALID,
        "I can help with Annual Leave, Sick Leave, or Casual Leave. Which one do you mean?",
        expose=True,
    )


def _normalize_leave_query(name):
    wanted = str(name or "").strip().lower()
    wanted = wanted.replace("anual", "annual").replace("annnual", "annual")
    return wanted


def _leave_type_matches(item, wanted):
    item_name = str(item.get("name") or "").lower()
    code = str(item.get("code") or "").lower()
    item_id = str(item.get("id") or "").lower()
    short_name = item_name.replace(" leave", "")
    short_wanted = wanted.replace(" leave", "").replace("leaves", "").strip()
    if wanted in {item_name, code, item_id, short_name}:
        return True
    if short_wanted and short_wanted in {item_name, code, item_id, short_name}:
        return True
    if short_wanted and (short_wanted in item_name or short_wanted in code or short_wanted == item_id):
        return True
    return False


def resolve_leave_type_label(raw, leave_types):
    wanted = str(raw or "").strip()
    if not wanted:
        return ""
    for item in leave_types or []:
        if _leave_type_matches(item, wanted.lower()) or wanted == item.get("id"):
            return item.get("name") or wanted
    return wanted


def looks_like_record_id(value):
    text = str(value or "").strip()
    return text.startswith("rec") and " " not in text and len(text) >= 10


def public_leave_type_name(raw, leave_types=None, fallback="Leave"):
    wanted = str(raw or "").strip()
    if not wanted:
        return fallback
    label = resolve_leave_type_label(wanted, leave_types or [])
    if looks_like_record_id(label):
        return fallback
    return label or fallback


def public_leave_type_name_for_client(client, raw, *, logger=None, fallback="Leave"):
    types = get_active_leave_types(client, logger=logger) if client is not None else []
    return public_leave_type_name(raw, types, fallback=fallback)

"""Company holidays. Optional: if the table is missing, only weekends are off."""

import time

from app.records.fields import db_call, as_text, field

CACHE_TTL_SECONDS = 900
_CACHE_ATTR = "_holidays_cache"


def record_to_holiday(record):
    day = as_text(field(record, "Date", "date"))[:10]
    if not day:
        return None
    return {
        "id": record.get("id"),
        "date": day,
        "name": as_text(field(record, "Holiday", "Name", "name")) or "Holiday",
    }


def _cached(client):
    if not CACHE_TTL_SECONDS:
        return None
    cached = getattr(client, _CACHE_ATTR, None)
    if not cached:
        return None
    stored_at, holidays = cached
    if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
        return None
    return holidays


def clear_holiday_cache(client):
    try:
        delattr(client, _CACHE_ATTR)
    except AttributeError:
        pass


def get_holidays(client, *, logger=None):
    """Every company holiday. A missing or unreadable table means none."""
    if client is None:
        return []
    cached = _cached(client)
    if cached is not None:
        return list(cached)
    try:
        records = db_call(
            lambda: client.table("holidays").all(),
            op="holidays",
            logger=None,
        )
    except Exception:
        # The table is optional. Weekends still apply.
        if logger:
            logger.debug("No Holidays table; only weekends are treated as off days")
        records = []
    holidays = [item for item in (record_to_holiday(row) for row in records or []) if item]
    try:
        setattr(client, _CACHE_ATTR, (time.monotonic(), holidays))
    except AttributeError:
        pass
    return list(holidays)


def holiday_name_for(client, day, *, logger=None):
    wanted = str(day)[:10]
    for item in get_holidays(client, logger=logger):
        if item["date"] == wanted:
            return item["name"]
    return ""

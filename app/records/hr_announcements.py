"""HR-scheduled announcements: SQL-backed, posted to #announcements later.

Same idea as birthdays (structured HR data, not the vector DB): HR fills in a
form (Title, Date, Time, Description) in the #hr-announcements channel, the
row is stored here with Status='Scheduled', and a periodic task posts it to
#announcements once its scheduled Pakistan-time moment arrives.
"""

from datetime import datetime, timedelta, timezone

from app.records.fields import as_text, db_call, field

# Pakistan Standard Time is UTC+5 year-round (no DST). "Scheduled At" is
# stored as PKT wall-clock text ("YYYY-MM-DD HH:MM"), matching the modal's
# Date/Time inputs, so the due-check below must compare against PKT "now" —
# not UTC — or announcements only fire ~5 hours late.
PAKISTAN_TZ = timezone(timedelta(hours=5), name="PKT")

STATUS_SCHEDULED = "Scheduled"
STATUS_POSTED = "Posted"
STATUS_CANCELLED = "Cancelled"


def record_to_announcement(record):
    if not record:
        return None
    return {
        "id": record.get("id"),
        "title": as_text(field(record, "Title", "title")),
        "description": as_text(field(record, "Description", "description")),
        "announceDate": as_text(field(record, "Announce Date", "announceDate"))[:10],
        "announceTime": as_text(field(record, "Announce Time", "announceTime")),
        "scheduledAt": as_text(field(record, "Scheduled At", "scheduledAt")),
        "status": as_text(field(record, "Status", "status")),
        "createdByDiscordId": as_text(field(record, "Created By Discord ID", "createdByDiscordId")),
        "createdByName": as_text(field(record, "Created By Name", "createdByName")),
        "postedAt": as_text(field(record, "Posted At", "postedAt")),
        "cancelledAt": as_text(field(record, "Cancelled At", "cancelledAt")),
        "cancelledBy": as_text(field(record, "Cancelled By", "cancelledBy")),
    }


def create_announcement(
    client,
    *,
    title,
    description,
    announce_date,
    announce_time,
    scheduled_at,
    created_by_id,
    created_by_name,
    logger=None,
):
    """Insert a new Status='Scheduled' row. Returns the saved announcement dict."""
    fields = {
        "Title": str(title or "").strip(),
        "Description": str(description or "").strip(),
        "Announce Date": announce_date,
        "Announce Time": str(announce_time or "").strip(),
        "Scheduled At": scheduled_at,
        "Status": STATUS_SCHEDULED,
        "Created By Discord ID": str(created_by_id or "").strip(),
        "Created By Name": str(created_by_name or "").strip(),
    }
    created = db_call(
        lambda: client.table("hrAnnouncements").create(fields, typecast=True),
        op="hr_announcement_created",
        logger=logger,
    )
    if logger:
        logger.info("HR announcement scheduled", {"title": fields["Title"], "scheduledAt": scheduled_at})
    return record_to_announcement(created)


def list_scheduled_announcements(client, *, logger=None):
    """Every announcement still awaiting its post time, soonest first."""
    if client is None:
        return []
    records = db_call(
        lambda: client.table("hrAnnouncements").all(),
        op="hr_announcements_list",
        logger=logger,
    )
    items = [record_to_announcement(item) for item in records or []]
    items = [item for item in items if item and item.get("status") == STATUS_SCHEDULED]
    items.sort(key=lambda item: item.get("scheduledAt") or "")
    return items


def list_due_announcements(client, *, now=None, logger=None):
    """Scheduled announcements whose Scheduled At has already passed (Python-side, like birthdays).

    "Scheduled At" is stored as Pakistan wall-clock text, so "now" must be
    Pakistan time too (a naive `now` passed in by callers/tests is assumed to
    already be in that wall-clock frame).
    """
    if client is None:
        return []
    now_text = (now or datetime.now(PAKISTAN_TZ)).strftime("%Y-%m-%d %H:%M")
    due = [
        item
        for item in list_scheduled_announcements(client, logger=logger)
        if str(item.get("scheduledAt") or "") <= now_text
    ]
    return due


def mark_announcement_posted(client, record, *, logger=None):
    now = datetime.now(timezone.utc).isoformat()
    updated = db_call(
        lambda: client.table("hrAnnouncements").update(record["id"], {
            "Status": STATUS_POSTED,
            "Posted At": now,
        }),
        op="hr_announcement_posted",
        logger=logger,
    )
    if logger:
        logger.info("HR announcement posted", {"id": record.get("id"), "title": record.get("title")})
    return record_to_announcement(updated)


def cancel_announcement(client, record, *, cancelled_by, logger=None):
    now = datetime.now(timezone.utc).isoformat()
    updated = db_call(
        lambda: client.table("hrAnnouncements").update(record["id"], {
            "Status": STATUS_CANCELLED,
            "Cancelled At": now,
            "Cancelled By": str(cancelled_by or "").strip(),
        }),
        op="hr_announcement_cancelled",
        logger=logger,
    )
    if logger:
        logger.info("HR announcement cancelled", {"id": record.get("id"), "title": record.get("title")})
    return record_to_announcement(updated)

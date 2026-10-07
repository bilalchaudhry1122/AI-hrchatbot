"""HR announcement scheduling: validation, DB round-trip, trigger phrases."""

from datetime import datetime, timedelta

from app.discord.announcements import PAKISTAN_TZ
from app.discord.hr_announcements import (
    _validate_announcement,
    looks_like_cancel_announcement_request,
    looks_like_new_announcement_request,
)
from app.records.hr_announcements import (
    STATUS_CANCELLED,
    STATUS_POSTED,
    STATUS_SCHEDULED,
    cancel_announcement,
    create_announcement,
    list_due_announcements,
    list_scheduled_announcements,
    mark_announcement_posted,
)


class FakeTable:
    def __init__(self):
        self.records = []

    def all(self, formula=None):
        return list(self.records)

    def create(self, fields, **kwargs):
        record = {"id": f"rec{len(self.records) + 1}", "fields": dict(fields)}
        self.records.append(record)
        return record

    def update(self, record_id, fields, **kwargs):
        for record in self.records:
            if record["id"] == record_id:
                record["fields"].update(fields)
                return record
        raise KeyError(record_id)

    def get(self, record_id):
        for record in self.records:
            if record["id"] == record_id:
                return record
        return None


class FakeClient:
    def __init__(self):
        self.tables = {"hrAnnouncements": FakeTable()}

    def table(self, key):
        return self.tables[key]


# ---------------------------------------------------------------------------
# Validation


def test_validate_announcement_accepts_future_date_time():
    now = datetime(2026, 1, 1, 10, 0, tzinfo=PAKISTAN_TZ)
    errors, scheduled_at = _validate_announcement(
        "Office closed", "2026-01-02", "4:20 PM", "Everyone gets a day off.", now=now
    )
    assert errors == []
    assert scheduled_at == datetime(2026, 1, 2, 16, 20, tzinfo=PAKISTAN_TZ)


def test_validate_announcement_accepts_lowercase_and_no_space_am_pm():
    now = datetime(2026, 1, 1, 10, 0, tzinfo=PAKISTAN_TZ)
    errors, scheduled_at = _validate_announcement(
        "Office closed", "2026-01-02", "6:20pm", "Everyone gets a day off.", now=now
    )
    assert errors == []
    assert scheduled_at == datetime(2026, 1, 2, 18, 20, tzinfo=PAKISTAN_TZ)


def test_validate_announcement_rejects_past_date_time():
    now = datetime(2026, 1, 5, 10, 0, tzinfo=PAKISTAN_TZ)
    errors, scheduled_at = _validate_announcement(
        "Old news", "2026-01-01", "9:00 AM", "Should be rejected.", now=now
    )
    assert scheduled_at is None
    assert any("future" in error for error in errors)


def test_validate_announcement_rejects_bad_format():
    errors, scheduled_at = _validate_announcement("Title", "not-a-date", "25:99", "Body")
    assert scheduled_at is None
    assert any("Date" in error for error in errors)
    assert any("Time" in error for error in errors)


def test_validate_announcement_requires_title_and_description():
    errors, scheduled_at = _validate_announcement("", "2099-01-01", "10:00 AM", "")
    assert scheduled_at is None
    assert any("Title" in error for error in errors)
    assert any("Description" in error for error in errors)


# ---------------------------------------------------------------------------
# DB round-trip


def test_create_list_mark_posted_and_cancel_round_trip():
    client = FakeClient()
    created = create_announcement(
        client,
        title="Payroll day",
        description="Salaries go out today.",
        announce_date="2099-01-02",
        announce_time="16:20",
        scheduled_at="2099-01-02 16:20",
        created_by_id="111",
        created_by_name="HR Person",
    )
    assert created["status"] == STATUS_SCHEDULED
    assert created["title"] == "Payroll day"

    scheduled = list_scheduled_announcements(client)
    assert len(scheduled) == 1
    assert scheduled[0]["id"] == created["id"]

    # Not due yet: scheduled far in the future relative to "now".
    due = list_due_announcements(client, now=datetime(2099, 1, 1, 0, 0))
    assert due == []

    # Due once "now" has passed the scheduled time.
    due = list_due_announcements(client, now=datetime(2099, 1, 2, 16, 30))
    assert len(due) == 1

    posted = mark_announcement_posted(client, created)
    assert posted["status"] == STATUS_POSTED
    assert list_scheduled_announcements(client) == []


def test_cancel_announcement_removes_it_from_scheduled_list():
    client = FakeClient()
    created = create_announcement(
        client,
        title="To be cancelled",
        description="Oops, wrong date.",
        announce_date="2099-05-05",
        announce_time="10:00",
        scheduled_at="2099-05-05 10:00",
        created_by_id="222",
        created_by_name="HR Person",
    )
    cancelled = cancel_announcement(client, created, cancelled_by="HR Person")
    assert cancelled["status"] == STATUS_CANCELLED
    assert cancelled["cancelledBy"] == "HR Person"
    assert list_scheduled_announcements(client) == []


# ---------------------------------------------------------------------------
# Trigger phrases


def test_looks_like_new_announcement_request_matches_english_and_roman_urdu():
    assert looks_like_new_announcement_request("I have an announcement")
    assert looks_like_new_announcement_request("mujhe announcement karni hai")
    assert looks_like_new_announcement_request("mujhai announcement krni hai")
    assert not looks_like_new_announcement_request("what's the leave policy")


def test_looks_like_cancel_announcement_request_needs_both_words():
    assert looks_like_cancel_announcement_request("cancel the announcement")
    assert looks_like_cancel_announcement_request("please cancel that announcement now")
    assert not looks_like_cancel_announcement_request("cancel my leave")
    assert not looks_like_cancel_announcement_request("I have an announcement")

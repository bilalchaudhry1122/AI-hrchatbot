"""Tests for the plumbing: ticket storage, Airtable resilience, wiring.

These cover the parts that used to have no tests at all, where a silent
failure loses tickets or double-sends a leave request to HR.
"""

import asyncio
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from app.agent.router import _sticky_locale
from app.records.fields import db_call, escape_formula_value, is_retryable
from app.records.leave_requests import get_requests_for_discord_id
from app.records.leave_types import clear_leave_type_cache, get_active_leave_types
from app.errors import AppError, ErrorCodes
from app.hr.dates import resolve_attendance_range, resolve_date_phrase
from app.logger import create_logger
from app.tickets.store import create_ticket_store


# --- ticket store ---------------------------------------------------------


def _ticket(channel_id="1", user_id="42"):
    return {"channelId": channel_id, "userId": user_id, "namespace": "hr", "status": "open"}


def test_store_survives_a_truncated_file(tmp_path):
    path = tmp_path / "tickets.json"
    path.write_text('{"tickets": {"1": {"channelId"', encoding="utf-8")
    store = create_ticket_store(path, logger=create_logger("error"))
    assert store.all() == {}
    # The damaged file is kept for inspection rather than silently dropped.
    assert (tmp_path / "tickets.json.broken").exists()
    store.upsert(_ticket())
    assert create_ticket_store(path).get_by_channel("1")["userId"] == "42"


def test_store_ignores_unexpected_shapes(tmp_path):
    path = tmp_path / "tickets.json"
    path.write_text('["not", "a", "map"]', encoding="utf-8")
    assert create_ticket_store(path).all() == {}
    path.write_text('{"tickets": []}', encoding="utf-8")
    assert create_ticket_store(path).all() == {}


def test_store_write_leaves_no_temp_file(tmp_path):
    path = tmp_path / "tickets.json"
    store = create_ticket_store(path)
    store.upsert(_ticket())
    store.close("1")
    assert not (tmp_path / "tickets.json.tmp").exists()
    assert create_ticket_store(path).get_by_channel("1")["status"] == "closed"


def test_store_round_trips_through_a_missing_directory(tmp_path):
    path = tmp_path / "nested" / "tickets.json"
    store = create_ticket_store(path)
    store.upsert(_ticket())
    assert path.exists()
    assert create_ticket_store(path).find_open("42") is not None


# --- Airtable resilience --------------------------------------------------


class Boom(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


def test_rate_limits_are_retried_then_succeed():
    calls = []
    slept = []

    def action():
        calls.append(1)
        if len(calls) < 3:
            raise Boom(429)
        return "ok"

    result = db_call(action, op="test", sleep=slept.append)
    assert result == "ok"
    assert len(calls) == 3
    assert slept  # backed off rather than hammering the API


def test_client_errors_are_not_retried():
    calls = []

    def action():
        calls.append(1)
        raise Boom(422)

    with pytest.raises(AppError) as caught:
        db_call(action, op="test", sleep=lambda _: None)
    assert len(calls) == 1
    assert caught.value.code == ErrorCodes.DB_UNAVAILABLE


def test_auth_failure_keeps_its_own_code():
    with pytest.raises(AppError) as caught:
        db_call(lambda: (_ for _ in ()).throw(Boom(401)), op="test", sleep=lambda _: None)
    assert caught.value.code == ErrorCodes.DB_AUTH


def test_retry_gives_up_and_reports_unavailable():
    calls = []

    def action():
        calls.append(1)
        raise Boom(503)

    with pytest.raises(AppError):
        db_call(action, op="test", sleep=lambda _: None)
    assert len(calls) == 3


def test_is_retryable_reads_plain_rate_limit_text():
    assert is_retryable(Exception("429 Too Many Requests")) is True
    assert is_retryable(Boom(404)) is False


def test_formula_values_are_escaped():
    assert escape_formula_value("O'Brien") == "O\\'Brien"
    assert escape_formula_value("back\\slash") == "back\\\\slash"


# --- fewer Airtable round trips ------------------------------------------


class CountingTable:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def all(self, formula=None):
        self.calls.append(formula)
        return list(self.records)


class CountingClient:
    def __init__(self, tables):
        self.tables = tables

    def table(self, key):
        return self.tables[key]


def test_leave_types_are_cached_between_calls():
    table = CountingTable([
        {"id": "recType1", "fields": {"Leave Type": "Annual Leave", "Code": "ANNUAL", "Active": True}},
    ])
    client = CountingClient({"leaveTypes": table})
    clear_leave_type_cache(client)
    first = get_active_leave_types(client)
    second = get_active_leave_types(client)
    assert [item["name"] for item in first] == ["Annual Leave"]
    assert first == second
    assert len(table.calls) == 1  # second read came from the cache

    # Callers get their own list; mutating it must not poison the cache.
    second.clear()
    assert len(get_active_leave_types(client)) == 1
    clear_leave_type_cache(client)
    get_active_leave_types(client)
    assert len(table.calls) == 2


def test_leave_requests_are_filtered_by_airtable_not_in_python():
    table = CountingTable([
        {"id": "recReq1", "fields": {"Discord User ID": "111", "Status": "PENDING", "Requested At": "2026-01-01"}},
    ])
    client = CountingClient({"leaveRequests": table})
    rows = get_requests_for_discord_id(client, "111")
    assert len(rows) == 1
    assert table.calls == ["{Discord User ID}='111'"]


# --- dates ----------------------------------------------------------------


def test_kal_means_yesterday_for_attendance():
    today = date(2026, 9, 9)
    start, end = resolve_attendance_range("kal ki attendance batao", today=today)
    assert start == end == today - timedelta(days=1)


def test_tomorrow_is_still_tomorrow_for_leave():
    today = date(2026, 9, 9)
    assert resolve_date_phrase("kal", today=today) == today + timedelta(days=1)
    assert resolve_date_phrase("tomorrow", today=today) == today + timedelta(days=1)


def test_attendance_reads_an_explicit_past_date():
    today = date(2026, 9, 9)
    start, end = resolve_attendance_range("was i present on 3 sep", today=today)
    assert start == end == date(2026, 9, 3)


def test_attendance_falls_back_to_this_month():
    today = date(2026, 9, 9)
    start, end = resolve_attendance_range("show my attendance", today=today)
    assert start == date(2026, 9, 1)
    assert end == date(2026, 9, 30)


def test_leave_dates_still_prefer_the_future():
    today = date(2026, 9, 9)
    # A day that has passed this year means next year when booking leave.
    assert resolve_date_phrase("3 sep", today=today) == date(2027, 9, 3)
    # The same phrase in a lookup stays in the past.
    assert resolve_date_phrase("3 sep", today=today, prefer_future=False) == date(2026, 9, 3)


# --- reply language -------------------------------------------------------


def test_short_confirmation_keeps_the_draft_language():
    assert _sticky_locale("yes", "roman") == "roman"
    assert _sticky_locale("ok", "urdu") == "urdu"
    assert _sticky_locale("no", "roman") == "roman"


def test_a_real_sentence_still_switches_language():
    assert _sticky_locale("I want to apply for sick leave tomorrow", "roman") == "english"
    assert _sticky_locale("mujhe kal chutti chahiye", "english") in {"roman", "mix"}


def test_locale_defaults_to_english_without_a_draft():
    assert _sticky_locale("yes", None) == "english"


# --- Discord wiring -------------------------------------------------------


def _config(tmp_path):
    return {
        "rootDir": Path(tmp_path),
        "echoMode": False,
        "logLevel": "error",
        "discord": {
            "token": "x",
            "clientId": "",
            "respondMode": "slash",
            "channels": {"1": "hr"},
            "tickets": {"enabled": True, "categoryId": "", "staffRoleId": "", "adminRoleId": ""},
        },
        "hr": {"hrRoleId": "", "whoamiEnabled": False},
        "messages": {"userError": "error", "fallback": "fallback"},
    }


def _build_bot(tmp_path):
    # Go through the factory: that is where event listeners get registered.
    from app.discord.bot import create_discord_bot

    return create_discord_bot(config=_config(tmp_path), logger=create_logger("error"), rag=None, hr=None)


def _uses_default_callback(item):
    func = getattr(item.callback, "__func__", item.callback)
    return func is discord.ui.Item.callback


def test_bot_does_not_listen_for_interactions_itself(tmp_path):
    """discord.py already routes buttons to views and commands to the tree.

    An on_interaction listener here would fire *in addition* to that, running
    every button callback twice - including Submit to HR.
    """
    bot = _build_bot(tmp_path)
    assert "on_interaction" not in getattr(bot, "extra_events", {})
    assert not hasattr(bot, "on_interaction")


class FakeChannel:
    def __init__(self, channel_id=1):
        self.id = channel_id
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append({"content": content, **kwargs})
        return SimpleNamespace(id=len(self.sent))


def test_close_button_posted_in_a_ticket_actually_closes(tmp_path):
    """The posted view must carry the callback, not just the right custom_id.

    Buttons only work through the view they were sent with (or a persistent
    view registered for the same custom_id), so a callback-less view here
    would render a Close ticket button that silently does nothing.
    """
    bot = _build_bot(tmp_path)
    bot.store.upsert(_ticket(channel_id="1", user_id="42"))
    channel = FakeChannel(1)

    asyncio.run(bot.tickets.publish_close_row(channel))

    assert channel.sent, "no close row was posted"
    view = channel.sent[0]["view"]
    assert view.children, "close view must have a button"
    assert not _uses_default_callback(view.children[0]), "close button would do nothing"
    # And it is remembered so closing the ticket can clean it up.
    assert bot.store.get_by_channel("1")["closeMessageId"] == "1"


def test_open_ticket_view_has_a_real_callback(tmp_path):
    from app.discord.bot import OpenTicketView

    bot = _build_bot(tmp_path)
    view = OpenTicketView(bot)
    assert not _uses_default_callback(view.children[0])


def test_leave_views_have_real_callbacks(tmp_path):
    from app.discord.leave_ui import LeaveActionView, LeavePendingView

    bot = _build_bot(tmp_path)
    from app.discord.leave_review import LeaveReviewView

    for view in (LeaveActionView(bot), LeavePendingView(bot), LeaveReviewView(bot)):
        for item in view.children:
            assert not _uses_default_callback(item), f"{item} would do nothing"

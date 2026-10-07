from datetime import date, timedelta

from app.agent.router import AgentRouter, apply_cancel_leave_form, apply_cancel_leave_pick
from app.agent.verification import is_cancel_approved_leave, is_explicit_leave_apply, is_withdraw_leave
from app.hr.leave_status import APPROVED, CANCELLED
from app.logger import create_logger
from tests.test_hr import make_hr

PHRASES = [
    "i want to cancel my leave",
    "cancel my leave",
    "mujhai leave cancel krni hai",
    "leave cancel krdo",
]


def _future_workday(days=21):
    day = date.today() + timedelta(days=days)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day


def _approve_future(hr, *, ticket="980"):
    future = _future_workday()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id=ticket,
        leave_type_name="Annual Leave",
        start_date=future,
        end_date=future,
        reason="trip",
    )
    hr.leave.approve_in_ticket(ticket_channel_id=ticket, hr_discord_id="hr", hr_name="HR")
    return future


def test_cancel_approved_phrases_open_form_not_apply_or_withdraw():
    for text in PHRASES:
        assert is_cancel_approved_leave(text) is True, text
        assert is_explicit_leave_apply(text) is False, text
        assert is_withdraw_leave(text) is False, text


def test_router_opens_cancel_form_with_approved_dates():
    hr = make_hr()
    future = _approve_future(hr)
    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=None, hr=hr)
    result = router.handle(
        question="cancel my leave",
        namespace="hr",
        channel_id="980",
        discord_user_id="111",
        identity={"memberName": "Abdullah"},
        conversation_history=[],
    )
    assert result.get("ui") == "leave_cancel_form"
    card = result.get("leaveCard") or {}
    assert card.get("approved")
    assert card["approved"][0]["start_date"] == future.isoformat()
    assert "copy" not in (card.get("hint") or "").lower()
    picked = apply_cancel_leave_pick(router, "980", card["approved"][0]["id"])
    assert picked.get("ui") == "leave_cancel_form"
    assert picked.get("leaveCard", {}).get("start_date") == future.isoformat()
    filled = apply_cancel_leave_form(
        router,
        "980",
        reason="Trip called off",
        today=date.today(),
    )
    assert filled.get("ui") == "leave_cancel_form"
    assert "Trip called off" in (filled.get("leaveCard") or {}).get("reason", "")
    submitted = router._submit_cancel_leave("980", "111", {"memberName": "Abdullah"})
    assert submitted.get("ui") == "leave_approved_cancelled"
    assert submitted.get("saved", {}).get("status") == CANCELLED
    assert hr.leave.get_pending_for_member("111") is None
    remaining = [
        item for item in hr.client.table("leaveRequests").records
        if str(item["fields"].get("Status") or "").upper() == APPROVED
    ]
    assert remaining == []


def test_roman_cancel_phrase_opens_the_same_form():
    hr = make_hr()
    _approve_future(hr, ticket="981")
    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=None, hr=hr)
    result = router.handle(
        question="mujhai leave cancel krni hai",
        namespace="hr",
        channel_id="981",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert result.get("ui") == "leave_cancel_form"


def test_cancel_without_approved_leave_does_not_open_form():
    hr = make_hr()
    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=None, hr=hr)
    result = router.handle(
        question="i want to cancel my leave",
        namespace="hr",
        channel_id="982",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert result.get("ui") == "leave_cancel_none"
    assert not result.get("leaveCard")
    assert "no leave to be cancelled" in (result.get("answer") or "").lower()

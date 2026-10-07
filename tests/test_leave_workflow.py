"""Weekends, half days, two-step approval, and Admin above HR."""

from datetime import date, timedelta

import pytest

from app.agent.draft_store import create_draft_store
from app.errors import AppError, ErrorCodes
from app.hr import create_hr_services
from app.hr.leave_status import (
    ADMIN,
    APPROVED,
    CANCELLED,
    EMPLOYEE,
    HR,
    MANAGER,
    PENDING_HR,
    PENDING_MANAGER,
    can_act_on,
    is_open,
    stage_for,
)
from app.hr.permissions import tier_for
from app.hr.workdays import count_leave_days, working_days
from app.logger import create_logger

from tests.test_hr import FakeStore

# September 2026: 12/19 Saturday, 13/20 Sunday. 14-18 and 21-25 are working days.
MON = date(2026, 9, 14)
TUE = date(2026, 9, 15)
FRI = date(2026, 9, 18)
SAT = date(2026, 9, 19)
SUN = date(2026, 9, 20)
NEXT_MON = date(2026, 9, 21)


def make_hr(config=None):
    return create_hr_services(FakeStore(), create_logger("error"), config)


def two_step_config(**airtable):
    base = {"twoStepApproval": True, "hrRoleId": "9", "adminRoleId": "8", "managerRoleId": ""}
    base.update(airtable)
    return {"hr": base}


def add_manager(hr, *, employee_discord="111", manager_discord="222"):
    """Point one fake employee at another as their line manager."""
    employees = hr.client.table("employees").records
    by_discord = {row["fields"]["Discord User ID"]: row for row in employees}
    manager_record = by_discord[manager_discord]
    by_discord[employee_discord]["fields"]["Manager"] = [manager_record["id"]]
    return manager_record


# --- weekends and holidays -------------------------------------------------


def test_weekend_days_are_not_counted():
    # Friday to Monday is two working days, not four.
    assert count_leave_days(FRI, NEXT_MON) == 2.0
    assert count_leave_days(MON, TUE) == 2.0
    assert count_leave_days(SAT, SUN) == 0.0


def test_holidays_are_skipped_as_well():
    holidays = [{"date": TUE.isoformat(), "name": "Founders Day"}]
    assert count_leave_days(MON, TUE, holidays=holidays) == 1.0
    assert [day for day in working_days(MON, TUE, holidays=holidays)] == [MON]


def test_booking_only_a_weekend_is_refused():
    hr = make_hr()
    with pytest.raises(AppError) as caught:
        hr.leave.create_pending_request(
            discord_user_id="111",
            ticket_channel_id="900",
            leave_type_name="Annual Leave",
            start_date=SAT,
            end_date=SUN,
        )
    assert caught.value.code == ErrorCodes.LEAVE_NO_WORKING_DAYS
    assert "Saturday and Sunday" in str(caught.value)


def test_a_range_spanning_a_weekend_only_costs_working_days():
    hr = make_hr()
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="901",
        leave_type_name="Annual Leave",
        start_date=FRI,
        end_date=NEXT_MON,
    )
    assert created["daysRequested"] == 2.0
    hr.leave.approve_in_ticket(ticket_channel_id="901", hr_discord_id="hr", hr_name="HR")
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 2.0
    # And no utilisation rows for the Saturday or Sunday.
    dates = {row["fields"]["Date"] for row in hr.client.table("leaveUtilization").records}
    assert dates == {FRI.isoformat(), NEXT_MON.isoformat()}


# --- half days -------------------------------------------------------------


def test_half_day_costs_half_a_day():
    hr = make_hr()
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="902",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
        half_day="first",
    )
    assert created["daysRequested"] == 0.5
    assert created["halfDay"] == "First half"
    hr.leave.approve_in_ticket(ticket_channel_id="902", hr_discord_id="hr", hr_name="HR")
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 0.5


def test_half_day_is_ignored_on_a_range():
    hr = make_hr()
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="903",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=TUE,
        half_day="second",
    )
    assert created["halfDay"] == ""
    assert created["daysRequested"] == 2.0


# --- two-step approval -----------------------------------------------------


def test_status_helpers_describe_the_chain():
    assert stage_for(PENDING_MANAGER) == MANAGER
    assert stage_for(PENDING_HR) == HR
    # Rows written before two-step approval existed still count as open.
    assert is_open("PENDING") is True
    assert stage_for("PENDING") == HR


def test_manager_stage_only_when_employee_has_a_department():
    hr = make_hr(two_step_config())
    without = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="904",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    assert without["status"] == PENDING_HR

    hr2 = make_hr(two_step_config())
    hr2.client.table("employees").records[0]["fields"]["Department"] = "BI"
    with_dept = hr2.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="905",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    # HR-only flow: department is resolved (for the HOD notification) but
    # every request still lands as PENDING_HR, never PENDING_MANAGER.
    assert with_dept["status"] == PENDING_HR
    assert with_dept["needsHod"] is False


def test_hod_can_no_longer_approve_only_hr_finishes():
    """HOD is notify-only now: their tier can never approve, and HR/Admin
    finalises the request immediately (no intermediate PENDING_MANAGER hop)."""
    hr = make_hr(two_step_config())
    hr.client.table("employees").records[0]["fields"]["Department"] = "BI"
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="906",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    with pytest.raises(AppError) as caught:
        hr.leave.decide_in_ticket(
            ticket_channel_id="906",
            actor_id="333",
            actor_name="BI HOD",
            tier=MANAGER,
            decision="approve",
        )
    assert caught.value.code == ErrorCodes.HR_PERMISSION
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 0
    final = hr.leave.decide_in_ticket(
        ticket_channel_id="906", actor_id="hr", actor_name="HR", tier=HR, decision="approve"
    )
    assert final["status"] == APPROVED
    assert final["finalised"] is True
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 1.0


def test_hr_can_approve_immediately_without_any_hod_step():
    hr = make_hr(two_step_config())
    hr.client.table("employees").records[0]["fields"]["Department"] = "BI"
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="908",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    final = hr.leave.decide_in_ticket(
        ticket_channel_id="908", actor_id="hr", actor_name="HR", tier=HR, decision="approve"
    )
    assert final["status"] == APPROVED
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 1.0


def test_hr_can_approve_leave():
    hr = make_hr(two_step_config())
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="909",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    final = hr.leave.decide_in_ticket(
        ticket_channel_id="909", actor_id="hr", actor_name="HR", tier=HR, decision="approve"
    )
    assert final["status"] == APPROVED
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 1.0


def test_admin_or_hr_can_act_on_open_leave():
    assert can_act_on(PENDING_MANAGER, ADMIN) is True
    assert can_act_on(PENDING_HR, ADMIN) is True
    assert can_act_on(PENDING_MANAGER, HR) is False
    assert can_act_on(PENDING_HR, HR) is True
    assert can_act_on(PENDING_MANAGER, MANAGER, is_line_manager=True) is True
    assert can_act_on(PENDING_HR, MANAGER, is_line_manager=True) is False
    assert can_act_on(PENDING_HR, EMPLOYEE) is False
    assert can_act_on(APPROVED, ADMIN) is False


def test_other_department_hod_cannot_approve():
    hr = make_hr(two_step_config())
    hr.client.table("employees").records[0]["fields"]["Department"] = "BI"
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="907",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    with pytest.raises(AppError) as caught:
        hr.leave.decide_in_ticket(
            ticket_channel_id="907",
            actor_id="444",
            actor_name="Marketing HOD",
            tier=MANAGER,
            decision="approve",
        )
    assert caught.value.code == ErrorCodes.HR_PERMISSION
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 0


# --- rejection needs a reason ----------------------------------------------


def test_declining_without_a_reason_is_allowed():
    """A reason is optional: HR is never blocked from declining."""
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="909",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    saved = hr.leave.reject_in_ticket(
        ticket_channel_id="909", hr_discord_id="hr", hr_name="HR", reason="  "
    )
    assert saved["status"] == "REJECTED"
    assert saved["rejectionReason"] == ""
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 0
    assert hr.leave.get_pending_for_member("111") is None


def test_rejection_reason_does_not_overwrite_the_employees_reason():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="910",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
        reason="Family wedding",
    )
    saved = hr.leave.reject_in_ticket(
        ticket_channel_id="910",
        hr_discord_id="hr",
        hr_name="HR",
        reason="Two people already off that day",
    )
    assert saved["reason"] == "Family wedding"
    assert saved["rejectionReason"] == "Two people already off that day"


# --- cancelling an approved leave ------------------------------------------


def test_employee_can_cancel_their_own_future_leave_and_get_days_back():
    hr = make_hr()
    future = date.today() + timedelta(days=21)
    while future.weekday() > 4:
        future += timedelta(days=1)
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="911",
        leave_type_name="Annual Leave",
        start_date=future,
        end_date=future,
    )
    hr.leave.approve_in_ticket(ticket_channel_id="911", hr_discord_id="hr", hr_name="HR")
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 1.0

    saved = hr.leave.cancel_approved_for_member(
        "111", actor_id="111", actor_name="Abdullah", tier=EMPLOYEE, reason="Trip called off"
    )
    assert saved["status"] == CANCELLED
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 0.0


def test_cancel_approved_requires_matching_from_to_dates():
    hr = make_hr()
    future = date.today() + timedelta(days=21)
    while future.weekday() > 4:
        future += timedelta(days=1)
    later = future + timedelta(days=7)
    while later.weekday() > 4:
        later += timedelta(days=1)
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="911",
        leave_type_name="Annual Leave",
        start_date=future,
        end_date=future,
    )
    hr.leave.approve_in_ticket(ticket_channel_id="911", hr_discord_id="hr", hr_name="HR")
    listed = hr.leave.list_cancellable_approved("111")
    assert listed[0]["start_date"] == future.isoformat()
    with pytest.raises(AppError) as caught:
        hr.leave.cancel_approved_for_member(
            "111",
            start_date=later,
            end_date=later,
            actor_id="111",
            actor_name="Abdullah",
            tier=EMPLOYEE,
            reason="wrong dates",
        )
    assert caught.value.code == ErrorCodes.LEAVE_REQUEST_MISSING
    saved = hr.leave.cancel_approved_for_member(
        "111",
        start_date=future,
        end_date=future,
        actor_id="111",
        actor_name="Abdullah",
        tier=EMPLOYEE,
        reason="Trip called off",
    )
    assert saved["status"] == CANCELLED


def test_employee_cannot_cancel_leave_that_already_started():
    hr = make_hr()
    past = date.today() - timedelta(days=3)
    while past.weekday() > 4:
        past -= timedelta(days=1)
    hr.client.table("leaveRequests").create({
        "Request ID": "LR-PAST",
        "Discord User ID": "111",
        "Ticket Channel ID": "912",
        "Leave Type": "Annual Leave",
        "Start Date": past.isoformat(),
        "End Date": past.isoformat(),
        "Days Requested": 1,
        "Status": "APPROVED",
    })
    with pytest.raises(AppError) as caught:
        hr.leave.cancel_approved_for_member(
            "111", actor_id="111", actor_name="Abdullah", tier=EMPLOYEE, reason="oops"
        )
    assert caught.value.code == ErrorCodes.HR_PERMISSION
    # Admin may still do it.
    saved = hr.leave.cancel_approved_for_member(
        "111", actor_id="1", actor_name="Boss", tier=ADMIN, reason="Recorded in error"
    )
    assert saved["status"] == CANCELLED


# --- queue and calendar ----------------------------------------------------


def test_queue_is_admin_and_hr_only():
    hr = make_hr(two_step_config())
    add_manager(hr)
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="913",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    assert hr.leave.queue_for_actor(discord_user_id="222", tier=MANAGER) == []
    assert hr.leave.queue_for_actor(discord_user_id="111", tier=EMPLOYEE) == []
    assert [item["discordUserId"] for item in hr.leave.queue_for_actor(discord_user_id="hr", tier=HR)] == ["111"]
    assert [item["discordUserId"] for item in hr.leave.queue_for_actor(discord_user_id="1", tier=ADMIN)] == ["111"]


def test_calendar_lists_upcoming_leave_only():
    hr = make_hr()
    future = date.today() + timedelta(days=30)
    while future.weekday() > 4:
        future += timedelta(days=1)
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="914",
        leave_type_name="Annual Leave",
        start_date=future,
        end_date=future,
    )
    hr.leave.approve_in_ticket(ticket_channel_id="914", hr_discord_id="hr", hr_name="HR")
    hr.client.table("leaveRequests").create({
        "Request ID": "LR-OLD2",
        "Discord User ID": "111",
        "Ticket Channel ID": "915",
        "Leave Type": "Annual Leave",
        "Start Date": "2020-01-06",
        "End Date": "2020-01-06",
        "Days Requested": 1,
        "Status": "APPROVED",
    })
    calendar = hr.leave.leave_calendar("111")
    starts = [item["startDate"] for item in calendar["approved"]]
    assert future.isoformat() in starts
    assert "2020-01-06" not in starts


# --- one open request at a time --------------------------------------------


def test_only_one_open_request_at_a_time():
    hr = make_hr(two_step_config())
    add_manager(hr)
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="916",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    with pytest.raises(AppError) as caught:
        hr.leave.create_pending_request(
            discord_user_id="111",
            ticket_channel_id="917",
            leave_type_name="Annual Leave",
            start_date=NEXT_MON,
            end_date=NEXT_MON,
        )
    assert caught.value.code == ErrorCodes.LEAVE_REQUEST_OPEN


# --- role tiers ------------------------------------------------------------


class FakeRole:
    def __init__(self, role_id, name=""):
        self.id = role_id
        self.name = name or str(role_id)


class FakeMember:
    def __init__(self, roles=(), administrator=False):
        self.roles = [FakeRole(item) for item in roles]
        self.guild_permissions = type("P", (), {"administrator": administrator})()


class FakeGuild:
    def __init__(self, roles=()):
        self.roles = [FakeRole(item) for item in roles]


def test_staff_cannot_mute_the_bot_but_admin_and_hr_can():
    from app.discord.bot import can_ask_bot_to_leave

    config = {
        "discord": {"tickets": {"adminRoleId": "8", "staffRoleId": "7"}},
        "hr": {"hrRoleId": "9", "adminRoleId": "8"},
    }
    guild = FakeGuild(["7", "8", "9"])
    assert can_ask_bot_to_leave(FakeMember(roles=["7"]), config, guild) is False
    assert can_ask_bot_to_leave(FakeMember(roles=["9"]), config, guild) is True
    assert can_ask_bot_to_leave(FakeMember(roles=["8"]), config, guild) is True
    assert can_ask_bot_to_leave(FakeMember(roles=[], administrator=True), config, guild) is True


def test_tier_ranking_puts_admin_above_hr():
    config = two_step_config()
    assert tier_for(FakeMember(roles=["8"]), config) == ADMIN
    assert tier_for(FakeMember(roles=["9"]), config) == HR
    # Holding both means the higher tier wins.
    assert tier_for(FakeMember(roles=["8", "9"]), config) == ADMIN
    assert tier_for(FakeMember(roles=[]), config) == EMPLOYEE
    assert tier_for(FakeMember(roles=[]), config, is_line_manager=True) == MANAGER
    # A Discord server administrator counts as Admin even without the role.
    assert tier_for(FakeMember(roles=[], administrator=True), config) == ADMIN


# --- drafts survive a restart ----------------------------------------------


def test_leave_draft_is_restored_after_a_restart(tmp_path):
    path = tmp_path / "leave_drafts.json"
    drafts = create_draft_store(path)
    drafts["chan-1"] = {
        "leave_type": "Sick Leave",
        "start_date": MON,
        "end_date": MON,
        "reason": "flu",
        "awaiting_confirm": True,
        "locale": "roman",
    }
    reopened = create_draft_store(path)
    restored = reopened["chan-1"]
    assert restored["leave_type"] == "Sick Leave"
    assert restored["start_date"] == MON  # came back as a date, not a string
    assert restored["awaiting_confirm"] is True
    assert restored["locale"] == "roman"


def test_draft_flags_set_after_storing_are_saved(tmp_path):
    path = tmp_path / "leave_drafts.json"
    drafts = create_draft_store(path)
    draft = {"leave_type": "Annual Leave"}
    drafts["chan-2"] = draft
    # The router mutates the draft while building the reply, then flushes.
    draft["awaiting_details"] = True
    drafts.save()
    assert create_draft_store(path)["chan-2"]["awaiting_details"] is True


def test_draft_store_without_a_file_still_behaves_like_a_dict():
    drafts = create_draft_store()
    drafts["a"] = {"leave_type": "Sick Leave"}
    assert drafts.get("a")["leave_type"] == "Sick Leave"
    assert drafts.pop("a")["leave_type"] == "Sick Leave"
    assert drafts.get("a") is None


# --- what the employee is told when leave is declined -----------------------


def test_hr_is_always_prompted_for_a_decline_reason():
    """Optional to fill in, but the field must always be put in front of HR."""
    from app.discord.leave_review import RejectReasonModal

    modal = RejectReasonModal(object(), tier=HR, is_line_manager=False)
    assert "Decline" in modal.title
    field = modal.reason_input
    assert "reason" in field.label.lower()
    assert field.required is False, "HR is never blocked from declining"
    assert "optional" in field.label.lower() or "optional" in (field.placeholder or "").lower()


def test_declined_employee_sees_the_reason_when_one_is_given():
    from app.discord.notify import decision_embed

    embed = decision_embed(
        {
            "leaveType": "Sick Leave",
            "startDate": MON.isoformat(),
            "endDate": MON.isoformat(),
            "daysRequested": 1,
            "reason": "flu",
            "rejectionReason": "Two people are already off that day",
        },
        outcome="rejected",
    )
    body = " ".join(f"{f.name} {f.value}" for f in embed.fields)
    assert "Two people are already off that day" in body


def test_declined_with_no_reason_still_tells_the_employee_what_to_do():
    """Silence is worse than an optional field. They get a next step."""
    from app.discord.notify import decision_embed

    embed = decision_embed(
        {
            "leaveType": "Sick Leave",
            "startDate": MON.isoformat(),
            "endDate": MON.isoformat(),
            "daysRequested": 1,
            "rejectionReason": "",
        },
        outcome="rejected",
    )
    body = " ".join(f"{f.name} {f.value}" for f in embed.fields).lower()
    assert "no reason was recorded" in body
    assert "ask hr" in body


def test_the_reviewer_sees_that_no_reason_was_recorded():
    from app.discord.leave_review import decision_summary_embed

    embed = decision_summary_embed(
        {"leaveType": "Sick Leave", "daysRequested": 1, "employeeName": "Omar",
         "startDate": MON.isoformat(), "endDate": MON.isoformat(), "rejectionReason": ""},
        outcome="rejected",
        actor="HR",
    )
    body = " ".join(f"{f.name} {f.value}" for f in embed.fields).lower()
    assert "none recorded" in body


def test_the_decline_message_follows_the_employees_own_language():
    """Nobody records the employee's language, so their own reason is the clue."""
    from app.discord.notify import decision_embed, employee_locale

    request = {
        "leaveType": "Sick Leave",
        "startDate": MON.isoformat(),
        "endDate": MON.isoformat(),
        "daysRequested": 1,
        "reason": "mujhe bukhar hai, kal chutti chahiye",
        "rejectionReason": "",
    }
    assert employee_locale(request) in {"roman", "mix"}
    embed = decision_embed(request, outcome="rejected", locale=employee_locale(request))
    body = " ".join(f"{f.name} {f.value}" for f in embed.fields).lower()
    assert "wajah" in body or "poochh" in body
    # An English reason keeps the English wording.
    english = dict(request, reason="I have a fever and need tomorrow off")
    assert employee_locale(english) == "english"


def test_a_declined_request_keeps_both_reasons_apart():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="930",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
        reason="mujhe bukhar hai",
    )
    saved = hr.leave.reject_in_ticket(
        ticket_channel_id="930",
        hr_discord_id="hr",
        hr_name="HR",
        reason="Team is short-staffed on Monday",
    )
    assert saved["reason"] == "mujhe bukhar hai"
    assert saved["rejectionReason"] == "Team is short-staffed on Monday"


def test_approval_and_rejection_keep_the_staff_discord_id():
    """The inbox DM needs this id after Airtable only returns the patched fields."""
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="931",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    approved = hr.leave.approve_in_ticket(ticket_channel_id="931", hr_discord_id="hr", hr_name="HR")
    assert approved["discordUserId"] == "111"

    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="932",
        leave_type_name="Annual Leave",
        start_date=NEXT_MON,
        end_date=NEXT_MON,
    )
    rejected = hr.leave.reject_in_ticket(ticket_channel_id="932", hr_discord_id="hr", hr_name="HR")
    assert rejected["discordUserId"] == "111"


def test_inbox_line_names_approval_and_rejection():
    from app.discord.notify import inbox_line

    assert "approved" in inbox_line("approved", "english").lower()
    assert "not approved" in inbox_line("rejected", "english").lower()


def test_notify_decision_dms_the_staff_member():
    import asyncio

    from app.discord.notify import notify_decision

    class FakeUser:
        def __init__(self):
            self.sent = []

        async def send(self, content=None, embed=None):
            self.sent.append((content, embed))

    class FakeBot:
        def __init__(self, user):
            self._user = user
            self.logger = type("L", (), {"info": staticmethod(lambda *a, **k: None)})()

        def get_user(self, _user_id):
            return self._user

        async def fetch_user(self, _user_id):
            return self._user

    user = FakeUser()
    sent = asyncio.run(
        notify_decision(
            FakeBot(user),
            {
                "discordUserId": "111",
                "leaveType": "Annual Leave",
                "startDate": MON.isoformat(),
                "endDate": MON.isoformat(),
                "daysRequested": 1,
            },
            outcome="approved",
            actor="Approved by HR",
        )
    )
    assert sent is True
    content, embed = user.sent[0]
    assert "approved" in (content or "").lower()
    assert "approved" in (embed.title or "").lower()


# --- what actually gets written to Airtable ---------------------------------


def _created_fields(hr):
    return hr.client.table("leaveRequests").records[-1]["fields"]


def test_pending_hr_falls_back_when_status_select_is_legacy():
    """Live bases from setup_airtable used to only allow PENDING.

    Writing PENDING_HR is rejected with INVALID_MULTIPLE_CHOICE_OPTIONS.
    """
    from tests.test_hr import FakeTable

    hr = make_hr()
    existing = hr.client.table("leaveRequests")

    class LegacyStatus(FakeTable):
        def create(self, fields, **kwargs):
            if fields.get("Status") in {PENDING_HR, PENDING_MANAGER}:
                raise RuntimeError("422 INVALID_MULTIPLE_CHOICE_OPTIONS")
            return super().create(fields)

        def update(self, record_id, fields, **kwargs):
            if fields.get("Status") in {PENDING_HR, PENDING_MANAGER}:
                raise RuntimeError("422 INVALID_MULTIPLE_CHOICE_OPTIONS")
            return super().update(record_id, fields)

    hr.client.tables["leaveRequests"] = LegacyStatus(existing.records)
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="939",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    assert created["status"] == PENDING_HR
    assert _created_fields(hr)["Status"] == "PENDING"


def test_withdraw_works_when_cancel_audit_fields_are_missing():
    """Live Leave Requests has CANCELLED but no Cancelled At / Rejection Reason."""
    from tests.test_hr import FakeTable

    hr = make_hr()
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="938",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    existing = hr.client.table("leaveRequests")
    known = {
        "Request ID",
        "Discord User ID",
        "Ticket Channel ID",
        "Leave Type",
        "Start Date",
        "End Date",
        "Days Requested",
        "Reason",
        "Status",
        "Balance Before",
        "Requested At",
        "Employee",
    }

    class LegacyRequests(FakeTable):
        def update(self, record_id, fields):
            extra = [name for name in fields if name not in known]
            if extra:
                raise RuntimeError(
                    "422 UNKNOWN_FIELD_NAME Unknown field name: \"%s\"" % extra[0]
                )
            return super().update(record_id, fields)

    hr.client.tables["leaveRequests"] = LegacyRequests(existing.records)
    saved = hr.leave.withdraw_pending_for_member("111", withdrawn_by="Abdullah (111)")
    assert saved["status"] in {"CANCELLED", "REJECTED"}
    assert hr.leave.get_pending_for_member("111") is None
    assert created["id"]


def test_a_full_day_request_never_sends_an_empty_half_day():
    """An empty string in a single select is rejected by Airtable.

    It reads "" as a request to create a new blank option and refuses with
    INVALID_MULTIPLE_CHOICE_OPTIONS, which broke every full-day request.
    """
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="940",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    fields = _created_fields(hr)
    assert "Half Day" not in fields, "an unset select must be omitted, not sent empty"


def test_a_half_day_request_does_send_the_value():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="941",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
        half_day="first",
    )
    assert _created_fields(hr)["Half Day"] == "First half"


def test_linked_fields_are_written_as_record_id_arrays():
    """Linked-record fields only accept arrays; a bare name is rejected."""
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="942",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    fields = _created_fields(hr)
    assert isinstance(fields["Employee"], list) and fields["Employee"]
    assert isinstance(fields["Leave Type"], list) and fields["Leave Type"]


def test_approval_survives_a_missing_utilisation_table():
    """The audit table is optional and written after the balance has moved.

    Raising there would report failure for an approval that already applied,
    and tempt the reviewer into approving a second time.
    """
    hr = make_hr()

    class Refusing:
        def all(self, formula=None):
            raise RuntimeError("403 Forbidden: table not found")

        def create(self, fields):
            raise RuntimeError("403 Forbidden: table not found")

    hr.client.tables["leaveUtilization"] = Refusing()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="943",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    saved = hr.leave.approve_in_ticket(
        ticket_channel_id="943", hr_discord_id="hr", hr_name="HR"
    )
    assert saved["status"] == APPROVED
    # The balance still moved exactly once.
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 1.0


def test_utilisation_rows_carry_the_weekday_and_proper_links():
    """HR browses this table directly, so the columns must be populated."""
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="950",
        leave_type_name="Annual Leave",
        start_date=FRI,
        end_date=NEXT_MON,
    )
    hr.leave.approve_in_ticket(ticket_channel_id="950", hr_discord_id="hr", hr_name="HR")

    rows = [row["fields"] for row in hr.client.table("leaveUtilization").records]
    assert len(rows) == 2, "one row per working day, weekend excluded"
    by_date = {row["Date"]: row for row in rows}
    assert by_date[FRI.isoformat()]["Day of Week"] == "Friday"
    assert by_date[NEXT_MON.isoformat()]["Day of Week"] == "Monday"
    for row in rows:
        assert row["Status"] == "UTILISED"
        assert isinstance(row["Employee"], list) and row["Employee"]
        assert isinstance(row["Leave Type"], list) and row["Leave Type"]
        assert isinstance(row["Leave Request"], list) and row["Leave Request"]
        assert row["Year"] == FRI.year


def test_queue_and_calendar_show_leave_type_and_employee_names_for_sql_ids():
    """MySQL leave-type ids (e.g. 'seed-annual') are not Airtable 'rec' ids, so
    /pending and /myleave must resolve them to names instead of printing the id."""
    hr = make_hr(two_step_config())
    for row in hr.client.table("leaveTypes").records:
        row["id"] = "seed-" + row["fields"]["Code"].lower()
    for row in hr.client.table("leaveBalances").records:
        row["fields"]["Leave Type"] = [
            "seed-" + next(t["fields"]["Code"].lower() for t in hr.client.table("leaveTypes").records
                           if t["fields"]["Leave Type"] == "Annual Leave")
        ] if row["fields"].get("Leave Type") == ["recType1"] else row["fields"].get("Leave Type")
    future = date.today() + timedelta(days=30)
    while future.weekday() > 4:
        future += timedelta(days=1)
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="916",
        leave_type_name="Annual Leave",
        start_date=future,
        end_date=future,
    )
    [queued] = hr.leave.queue_for_actor(discord_user_id="1", tier=ADMIN)
    assert queued["leaveType"] == "Annual Leave"
    assert queued["employeeName"]
    [waiting] = hr.leave.leave_calendar("111")["waiting"]
    assert waiting["leaveType"] == "Annual Leave"


def test_reject_and_withdraw_carry_the_employee_name():
    """Request rows do not store the name; the decision card must not fall back to 'Staff'."""
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111", ticket_channel_id="917", leave_type_name="Annual Leave", start_date=MON, end_date=MON,
    )
    rejected = hr.leave.reject_in_ticket(ticket_channel_id="917", hr_discord_id="hr", hr_name="HR", reason="Busy week")
    assert rejected["employeeName"] == "Abdullah"

    hr.leave.create_pending_request(
        discord_user_id="111", ticket_channel_id="918", leave_type_name="Annual Leave", start_date=TUE, end_date=TUE,
    )
    withdrawn = hr.leave.withdraw_pending_for_member("111", withdrawn_by="Abdullah (111)")
    assert withdrawn["employeeName"] == "Abdullah"

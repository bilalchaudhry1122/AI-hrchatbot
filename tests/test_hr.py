from datetime import date
from types import SimpleNamespace
import re

import pytest

from app.records.employees import get_employee_by_discord_id
from app.errors import AppError, ErrorCodes
from app.hr import create_hr_services, is_hr_member
from app.hr.staff_onboard import employee_id_for, staff_kind_from_roles, upsert_staff_employee
from app.hr.dates import each_date, parse_day_count, resolve_date_phrase, resolve_date_range
from app.logger import create_logger
from app.agent.extraction import extract_leave_fields, infer_leave_type
from app.agent.router import AgentRouter, _ask_leave_details, _leave_draft_ready, _merge_leave_draft
from app.agent.verification import (
    in_leave_intake,
    is_cancel_submit,
    is_explicit_leave_apply,
    is_new_leave_start,
    is_quota_or_status_question,
    is_reject_leave,
    is_withdraw_leave,
    looks_like_leave_form_reply,
)
from app.routing.intent import classify_hr_intent, classify_social, is_conversation_continue, social_fallback_reply
from app.routing.language import detect_reply_language
from app.routing.roman_urdu import prefer_roman


def test_leave_apply_requires_explicit_request():
    assert is_quota_or_status_question("i want sick leave can you check my quota") is True
    assert is_explicit_leave_apply("i want sick leave can you check my quota") is False
    assert is_explicit_leave_apply("I want to apply for sick leave tomorrow") is True
    assert is_explicit_leave_apply("i want a leave") is True
    assert is_explicit_leave_apply("i want the leave") is True
    assert is_explicit_leave_apply("tomorrow sick leave") is False
    assert is_explicit_leave_apply("recXmcQopyDGO3tWR i want this leave") is False
    assert is_explicit_leave_apply("Annual leave chahiyay mujhai") is True
    assert is_quota_or_status_question("Annual leave chahiyay mujhai") is False
    assert classify_hr_intent("Annual leave chahiyay mujhai") == "LEAVE_REQUEST"
    assert prefer_roman("Annual leave chahiyay mujhai")


def test_leave_query_training_cases():
    apply_yes = [
        "I want to apply for sick leave tomorrow",
        "i want a leave",
        "Annual leave chahiyay mujhai",
        "mujhe kal sick leave chahiye",
        "apply karo",
    ]
    apply_no = [
        "nhi chahiyay leave",
        "nahi chahiye leave",
        "I don't want leave",
        "no i dont need",
        "dont need leave",
        "leave nahi chahiye",
        "or btao?",
        "how many leaves do i have?",
        "bhai mughe apni leave ka batao",
        "What is our annual leave policy?",
    ]
    cancel_yes = [
        "nhi chahiyay leave",
        "nahi chahiye",
        "no i dont need",
        "cancel",
        "I don't want leave",
        "dont need leave",
    ]
    for text in apply_yes:
        assert is_explicit_leave_apply(text) is True, text
        assert is_cancel_submit(text) is False, text
    for text in apply_no:
        assert is_explicit_leave_apply(text) is False, text
    for text in cancel_yes:
        assert is_cancel_submit(text) is True, text
        assert is_reject_leave(text) is True or is_cancel_submit(text) is True, text
    assert classify_hr_intent("nhi chahiyay leave") != "LEAVE_REQUEST"
    assert classify_hr_intent("or btao?") != "LEAVE_REQUEST"
    assert classify_social("or btao?") == "chitchat"
    closed = [
        {"role": "user", "content": "nhi chahiyay leave"},
        {"role": "assistant", "content": "Kaunsi leave: Annual, Sick, ya Casual? Kitne din?"},
        {"role": "user", "content": "no i dont need"},
        {"role": "assistant", "content": "Cancelled. No leave request was sent to HR."},
    ]
    assert in_leave_intake(closed) is False
    assert classify_hr_intent("or btao?", closed) != "LEAVE_REQUEST"
    assert is_conversation_continue("or btao?") is True
    assert is_conversation_continue("tell me more") is True
    assert is_conversation_continue("mujhe kal sick leave chahiye") is False


def test_company_leave_allowance_is_policy_not_cancel():
    corrections = [
        "no i mean in webairy how many leaves are allowrd",
        "no i mean how many leaves are allowed",
        "how many leaves are there",
        "how many leaves are allowed",
        "how many leaves are allowed in total",
    ]
    for text in corrections:
        assert is_cancel_submit(text) is False, text
        assert is_quota_or_status_question(text) is False, text
        assert classify_hr_intent(text) == "POLICY", text
    assert classify_hr_intent("how many leaves do i have?") == "LEAVE_BALANCE"
    assert is_cancel_submit("no") is True
    assert is_cancel_submit("cancel") is True
    class FakeRag:
        def answer_question(self, **kwargs):
            return {"answer": "from handbook", "fallback": False, "chunks": []}

    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=FakeRag(), hr=None)
    result = router.handle(
        question="no i mean how many leaves are allowed",
        namespace="hr",
        channel_id="99",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert result.get("ui") != "leave_cancelled"
    assert "handbook" in (result.get("answer") or "").lower() or result.get("answer")


def test_policy_retrieval_query_includes_handbook_hint():
    from app.agent.verification import is_workplace_clarification
    from app.rag.query import expand_retrieval_query

    q = "how many leaves are allowed in total?"
    expanded = expand_retrieval_query(q)
    assert "policy" in expanded.lower()
    assert "handbook" in expanded.lower()
    assert q.rstrip("?") in expanded or "how many leaves are allowed in total" in expanded.lower()
    assert is_workplace_clarification("i am talking about this workplace") is True
    follow = expand_retrieval_query(
        "i am talking about this workplace",
        [{"role": "user", "content": q}],
    )
    assert "how many leaves are allowed" in follow.lower()
    assert "handbook" in follow.lower()
    history = [{"role": "user", "content": q}]
    assert classify_hr_intent("i am talking about this workplace", history) == "POLICY"
    assert classify_hr_intent("in total", history) == "POLICY"
    assert classify_hr_intent("how many leaves are there in policy") == "POLICY"
    from app.agent.verification import is_company_handbook_question
    from app.rag.query import HANDBOOK_RETRIEVE_HINT, should_retry_policy_retrieve

    for ask in (
        "company policy",
        "company policie",
        "what are the company policies",
        "i want to know about company policy",
    ):
        assert classify_hr_intent(ask) == "POLICY", ask
        assert is_company_handbook_question(ask), ask
        expanded_ask = expand_retrieval_query(ask)
        assert "handbook" in expanded_ask.lower(), ask
        assert HANDBOOK_RETRIEVE_HINT.split()[0] in expanded_ask
        assert should_retry_policy_retrieve(ask) is True
    from app.agent.verification import is_broad_policy_catalog_question
    assert is_broad_policy_catalog_question("what are the policies") is True
    assert is_broad_policy_catalog_question("how many leaves are there in policy") is False


def test_stray_yes_does_not_dump_leave_balance():
    live_history = [
        {
            "role": "assistant",
            "content": (
                "Here is your live leave balance.\n"
                "Pending approval: none\n"
                "Recently approved: Sick Leave 10 Sep 2026\n"
                "I did not create an HR approval. If you want to apply, say for example: "
                "I want to apply for sick leave tomorrow."
            ),
        }
    ]
    assert classify_hr_intent("yes", live_history) != "LEAVE_REQUEST"
    hr = make_hr()
    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=None, hr=hr)
    result = router.handle(
        question="yes",
        namespace="hr",
        channel_id="77",
        discord_user_id="111",
        identity={},
        conversation_history=live_history,
    )
    text = (result.get("answer") or "").lower()
    assert "did not create" not in text
    assert "available now" not in text
    assert result.get("ui") != "leave_balance"


class FakeTable:
    def __init__(self, records=None):
        self.records = list(records or [])

    def all(self, formula=None):
        records = list(self.records)
        if not formula:
            return records
        text = str(formula)
        discord = re.search(r"Discord User ID\}='([^']+)'", text)
        role_id = re.search(r"Discord Role ID\}='([^']+)'", text)
        channel = re.search(r"Ticket Channel ID\}='([^']+)'", text)
        status = re.search(r"Status\}='([^']+)'", text)

        def matches(item):
            fields = item.get("fields") or {}
            if discord and str(fields.get("Discord User ID")) != discord.group(1):
                return False
            if role_id and str(fields.get("Discord Role ID")) != role_id.group(1):
                return False
            if channel and str(fields.get("Ticket Channel ID")) != channel.group(1):
                return False
            if status and str(fields.get("Status")) != status.group(1):
                return False
            return True

        if discord or role_id or channel or status:
            return [item for item in records if matches(item)]
        return records

    def create(self, fields, **kwargs):
        record = {"id": f"rec{len(self.records)+1}", "fields": dict(fields)}
        self.records.append(record)
        return record

    def update(self, record_id, fields, **kwargs):
        for record in self.records:
            if record["id"] == record_id:
                record["fields"].update(fields)
                return record
        raise KeyError(record_id)

    def delete(self, record_id):
        self.records = [item for item in self.records if item["id"] != record_id]
        return True


class FakeStore:
    def __init__(self):
        self.tables = {
            "employees": FakeTable([
                {"id": "recEmp1", "fields": {
                    "Employee Name": "Abdullah",
                    "Employee ID": "EMP-001",
                    "Discord User ID": "111",
                    "Department": "IT",
                    "Status": "Active",
                }},
                {"id": "recEmp2", "fields": {
                    "Employee Name": "Other",
                    "Employee ID": "EMP-002",
                    "Discord User ID": "222",
                    "Department": "HR",
                    "Status": "Active",
                }},
                {"id": "recEmp3", "fields": {
                    "Employee Name": "BI HOD",
                    "Employee ID": "EMP-003",
                    "Discord User ID": "333",
                    "Department": "BI",
                    "HR Role": "HOD",
                    "Status": "Active",
                }},
                {"id": "recEmp4", "fields": {
                    "Employee Name": "Marketing HOD",
                    "Employee ID": "EMP-004",
                    "Discord User ID": "444",
                    "Department": "Marketing",
                    "HR Role": "HOD",
                    "Status": "Active",
                }},
            ]),
            "leaveTypes": FakeTable([
                {"id": "recType1", "fields": {"Leave Type": "Annual Leave", "Code": "ANNUAL", "Active": True}},
                {"id": "recType3", "fields": {"Leave Type": "Sick Leave", "Code": "SICK", "Active": True}},
                {"id": "recType4", "fields": {"Leave Type": "Casual Leave", "Code": "CASUAL", "Active": True}},
            ]),
            "leaveBalances": FakeTable([
                {"id": "recBal1", "fields": {
                    "Employee": ["recEmp1"],
                    "Leave Type": "Annual Leave",
                    "Year": date.today().year,
                    "Total Entitlement": 16,
                    "Used": 0,
                    "Remaining": 16,
                }},
                {"id": "recBal2", "fields": {
                    "Employee": ["recEmp2"],
                    "Leave Type": "Annual Leave",
                    "Year": date.today().year,
                    "Total Entitlement": 10,
                    "Used": 1,
                    "Remaining": 9,
                }},
            ]),
            "attendance": FakeTable([
                {"id": "recAtt1", "fields": {
                    "Employee": ["recEmp1"],
                    "Date": date.today().replace(day=1).isoformat(),
                    "Status": "Present",
                }},
                {"id": "recAtt2", "fields": {
                    "Employee": ["recEmp2"],
                    "Date": date.today().replace(day=1).isoformat(),
                    "Status": "Absent",
                }},
            ]),
            "leaveRequests": FakeTable([]),
            "leaveUtilization": FakeTable([]),
            "discordRoles": FakeTable([]),
        }

    def table(self, key):
        return self.tables[key]


def make_hr():
    return create_hr_services(FakeStore(), create_logger("error"))


def test_employee_lookup_by_discord_id():
    hr = make_hr()
    employee = get_employee_by_discord_id(hr.client, "111")
    assert employee["name"] == "Abdullah"
    assert employee["employeeId"] == "EMP-001"


def test_unknown_discord_user():
    hr = make_hr()
    with pytest.raises(AppError) as caught:
        get_employee_by_discord_id(hr.client, "999")
    assert caught.value.code == ErrorCodes.EMPLOYEE_NOT_FOUND


def test_employee_cannot_read_another_balance():
    hr = make_hr()
    mine = hr.leave.get_my_leave_balance("111", "Annual Leave")
    theirs = hr.leave.get_my_leave_balance("222", "Annual Leave")
    assert mine["balance"]["remaining"] == 16
    assert theirs["balance"]["remaining"] == 9
    assert mine["employee"]["discordUserId"] == "111"


def test_leave_balance_lookup_text():
    hr = make_hr()
    result = hr.leave.get_my_leave_balance("111", "Annual Leave")
    assert "16" in result["text"]
    assert "Annual Leave" in result["text"]
    assert result["employee"]["name"] == "Abdullah"


def test_leave_balance_router_includes_asker_name():
    from app.agent.router import AgentRouter
    from app.logger import create_logger

    hr = make_hr()
    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=None, hr=hr)
    result = router.handle(
        question="what is my leave balance",
        namespace="hr",
        channel_id="77",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert result.get("ui") == "leave_balance"
    assert result.get("employeeName") == "Abdullah"


def test_leave_balance_matches_airtable_record_id():
    hr = make_hr()
    hr.client.tables["leaveBalances"].records[0]["fields"]["Leave Type"] = ["recType1"]
    named = hr.leave.get_my_leave_balance("111", "annual")
    by_id = hr.leave.get_my_leave_balance("111", "recType1")
    assert "Annual Leave" in named["text"]
    assert "Annual Leave" in by_id["text"]
    assert "16" in named["text"]


def test_attendance_lookup_is_self_only():
    hr = make_hr()
    start = date.today().replace(day=1)
    end = date.today()
    mine = hr.attendance.get_my_attendance("111", start, end)
    assert mine["summary"].get("Present") == 1
    assert "Absent" not in mine["summary"]


def test_leave_request_creation():
    hr = make_hr()
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="555",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
    )
    assert created["status"] == "PENDING_HR"
    assert created["daysRequested"] == 1
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 0
    snap = hr.leave.get_my_leave_snapshot("111")
    assert "Pending" in snap["text"]
    assert "16 of 16 available" in snap["text"]
    assert "If pending is approved" in snap["text"]
    assert "LR-" not in snap["text"]
    assert "Here is your live leave balance." in snap["text"]


def test_second_pending_leave_is_blocked():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="555",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
    )
    with pytest.raises(AppError) as caught:
        hr.leave.create_pending_request(
            discord_user_id="111",
            ticket_channel_id="556",
            leave_type_name="Sick Leave",
            start_date=date(2026, 9, 15),
            end_date=date(2026, 9, 15),
        )
    assert caught.value.code == ErrorCodes.LEAVE_REQUEST_OPEN
    assert "LR-" not in str(caught.value)
    other = hr.leave.create_pending_request(
        discord_user_id="222",
        ticket_channel_id="557",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
    )
    assert other["status"] == "PENDING_HR"
    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=None, hr=hr)
    blocked = router.handle(
        question="I want to apply for sick leave tomorrow",
        namespace="hr",
        channel_id="ticket-new",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert "waiting for HR" in blocked["answer"]
    assert blocked.get("ui") != "leave_form"


def test_leave_allowed_after_pending_is_processed():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="555",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
    )
    hr.leave.approve_in_ticket(ticket_channel_id="555", hr_discord_id="hr", hr_name="HR")
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="556",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 22),
        end_date=date(2026, 9, 22),
    )
    assert created["status"] == "PENDING_HR"
    hr.leave.reject_in_ticket(ticket_channel_id="556", hr_discord_id="hr", hr_name="HR", reason="Team is short-staffed")
    again = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="557",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 23),
        end_date=date(2026, 9, 23),
    )
    assert again["status"] == "PENDING_HR"


def test_staff_can_withdraw_pending_leave():
    assert is_withdraw_leave("withdraw") is True
    assert is_withdraw_leave("wapas le lo") is True
    assert is_withdraw_leave("how many leaves") is False
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="555",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 16),
        end_date=date(2026, 9, 17),
        reason="family",
    )
    hr.client.table("leaveRequests").create({
        "Request ID": "LR-OLD",
        "Discord User ID": "111",
        "Ticket Channel ID": "554",
        "Leave Type": "Annual Leave",
        "Start Date": "2026-09-10",
        "End Date": "2026-09-10",
        "Days Requested": 1,
        "Status": "PENDING",
        "Reason": "leftover",
    })
    assert len(hr.leave.list_pending_for_member("111")) == 2
    card = hr.leave.pending_card_for_member("111", "english")
    assert card["start_date"]
    saved = hr.leave.withdraw_pending_for_member("111", withdrawn_by="Abdullah (111)")
    assert saved["status"] in {"CANCELLED", "REJECTED"}
    assert saved.get("withdrawnCount") == 2
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 0
    assert hr.leave.get_pending_for_member("111") is None
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="556",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
    )
    assert created["status"] == "PENDING_HR"
    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=None, hr=hr)
    withdrawn = router.handle(
        question="withdraw",
        namespace="hr",
        channel_id="556",
        discord_user_id="111",
        identity={"memberName": "Abdullah"},
        conversation_history=[],
    )
    assert withdrawn.get("ui") == "leave_withdrawn"
    assert hr.leave.get_pending_for_member("111") is None
    with pytest.raises(AppError) as caught:
        hr.leave.approve_in_ticket(ticket_channel_id="556", hr_discord_id="hr", hr_name="HR")
    assert caught.value.code in {ErrorCodes.LEAVE_REQUEST_WITHDRAWN, ErrorCodes.LEAVE_REQUEST_MISSING, ErrorCodes.LEAVE_REQUEST_PROCESSED}


def test_hr_permission_helper():
    member = SimpleNamespace(roles=[SimpleNamespace(id="hr-1")])
    assert is_hr_member(member, "hr-1") is True
    assert is_hr_member(member, "hr-2") is False
    assert is_hr_member(member, "") is False


def test_approval_updates_used_and_status():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="555",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
    )
    saved = hr.leave.approve_in_ticket(ticket_channel_id="555", hr_discord_id="hr", hr_name="HR")
    assert saved["status"] == "APPROVED"
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 1
    snap = hr.leave.get_my_leave_snapshot("111")
    assert "15 of 16 available" in snap["text"]
    assert "Approved" in snap["text"]
    assert "LR-" not in snap["text"]
    used_days = hr.client.table("leaveUtilization").records
    assert len(used_days) == 1
    assert used_days[0]["fields"]["Date"] == "2026-09-14"


def test_rejected_does_not_deduct():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="556",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
    )
    hr.leave.reject_in_ticket(ticket_channel_id="556", hr_discord_id="hr", hr_name="HR", reason="Team is short-staffed")
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 0
    assert hr.client.table("leaveRequests").records[0]["fields"]["Status"] == "REJECTED"


def test_duplicate_granted_does_not_deduct_twice():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="557",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
    )
    hr.leave.approve_in_ticket(ticket_channel_id="557", hr_discord_id="hr", hr_name="HR")
    with pytest.raises(AppError) as caught:
        hr.leave.approve_in_ticket(ticket_channel_id="557", hr_discord_id="hr", hr_name="HR")
    assert caught.value.code == ErrorCodes.LEAVE_REQUEST_PROCESSED
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 1


def test_cannot_submit_dates_that_are_already_approved():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="560",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 15),
    )
    hr.leave.approve_in_ticket(ticket_channel_id="560", hr_discord_id="hr", hr_name="HR")
    with pytest.raises(AppError) as caught:
        hr.leave.create_pending_request(
            discord_user_id="111",
            ticket_channel_id="561",
            leave_type_name="Annual Leave",
            start_date=date(2026, 9, 15),
            end_date=date(2026, 9, 16),
        )
    assert caught.value.code == ErrorCodes.LEAVE_DATES_APPROVED
    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=None, hr=hr)
    router.drafts["562"] = {
        "leave_type": "Annual Leave",
        "start_date": date(2026, 9, 14),
        "end_date": date(2026, 9, 14),
        "days_count": 1,
        "range_complete": True,
        "reason": "again",
        "awaiting_confirm": True,
        "locale": "english",
    }
    result = router._handle_leave_request(
        question="yes",
        channel_id="562",
        discord_user_id="111",
        conversation_history=[],
    )
    assert result.get("ui") in {"leave_form", "leave_confirm"}
    assert "overlap" in result["answer"].lower() or "approved" in result["answer"].lower()
    assert router.drafts["562"].get("awaiting_confirm") or router.drafts["562"].get("awaiting_details")
    assert hr.leave.get_pending_for_member("111") is None
    later = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="563",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 22),
        end_date=date(2026, 9, 22),
    )
    assert later["status"] == "PENDING_HR"


def test_rejected_request_cannot_be_approved():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="558",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
    )
    hr.leave.reject_in_ticket(ticket_channel_id="558", hr_discord_id="hr", hr_name="HR", reason="Not enough cover")
    with pytest.raises(AppError) as caught:
        hr.leave.approve_in_ticket(ticket_channel_id="558", hr_discord_id="hr", hr_name="HR")
    assert caught.value.code == ErrorCodes.LEAVE_REQUEST_PROCESSED
    assert hr.client.table("leaveBalances").records[0]["fields"]["Used"] == 0


def test_insufficient_balance_blocks_request():
    hr = make_hr()
    with pytest.raises(AppError) as caught:
        hr.leave.create_pending_request(
            discord_user_id="111",
            ticket_channel_id="559",
            leave_type_name="Annual Leave",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )
    assert caught.value.code == ErrorCodes.INSUFFICIENT_LEAVE


def test_intent_routing_examples():
    assert classify_hr_intent("What is our annual leave policy?") == "POLICY"
    assert classify_hr_intent("How many annual leaves do I have?") == "LEAVE_BALANCE"
    assert classify_hr_intent("i want sick leave can you check my quota is it avalaible or not") == "LEAVE_BALANCE"
    assert classify_hr_intent("Show my attendance this month.") == "HUMAN_HR"
    assert classify_hr_intent("what is the attendance policy") == "POLICY"
    assert classify_hr_intent(
        "mujhe 28 september ko 1 chutti chahiye annual kyunke mere ghar me shaadi hai"
    ) == "LEAVE_REQUEST"
    assert classify_hr_intent("I need annual leave Monday.") == "LEAVE_REQUEST"
    assert classify_hr_intent("tomorrow sick leave") != "LEAVE_REQUEST"
    assert classify_hr_intent("random hello leave maybe") != "LEAVE_REQUEST"
    assert classify_hr_intent("I want to speak to HR.") == "HUMAN_HR"
    assert classify_hr_intent("chutti kitni hai") == "LEAVE_BALANCE"
    assert classify_hr_intent("meri salana chutti kitni baqi hai") == "LEAVE_BALANCE"
    assert classify_hr_intent("mujhe kal chutti chahiye") == "LEAVE_REQUEST"
    assert classify_hr_intent("hr se baat karni hai") == "HUMAN_HR"
    assert classify_hr_intent("bhai mughe apni leave ka batao") == "LEAVE_BALANCE"
    assert classify_hr_intent("tell me about my leave") == "LEAVE_BALANCE"
    assert is_quota_or_status_question("bhai mughe apni leave ka batao") is True
    assert is_explicit_leave_apply("bhai mughe apni leave ka batao") is False
    live_history = [
        {
            "role": "assistant",
            "content": "Here is your live leave balance.\n\nAvailable now\nCasual Leave: 5 remaining",
        }
    ]
    assert classify_hr_intent("bhai mughe apni leave ka batao", live_history) == "LEAVE_BALANCE"
    assert classify_hr_intent("What is our annual leave policy?") == "POLICY"
    assert classify_hr_intent("leave policy and how many days do I have") == "MIXED"
    from app.routing.data_source import source_for_intent
    assert source_for_intent("LEAVE_BALANCE") == "mysql"
    assert source_for_intent("POLICY") == "pinecone"
    assert source_for_intent("MIXED") == "pinecone+mysql"
    assert is_quota_or_status_question("chutti kitni hai") is True
    assert is_explicit_leave_apply("chutti kitni hai") is False
    assert is_explicit_leave_apply("mujhe kal sick leave chahiye") is True
    assert is_explicit_leave_apply("apply karo") is True
    assert resolve_date_phrase("kal", today=date(2026, 9, 8)) == date(2026, 9, 9)
    assert resolve_date_phrase("aaj", today=date(2026, 9, 8)) == date(2026, 9, 8)


def test_roman_urdu_language_and_types():
    assert prefer_roman("chutti kitni hai")
    assert infer_leave_type("salana chutti") == "Annual Leave"
    assert infer_leave_type("bimar chutti") == "Sick Leave"
    assert infer_leave_type("sirf chutti") is None
    assert classify_social("salam") == "greeting"
    assert classify_social("kia haal hai") == "greeting"
    assert classify_social("kesay ho?") == "greeting"
    reply = social_fallback_reply("greeting", "salam")
    assert "madad" in reply.lower()
    assert "میں" not in reply
    assert detect_reply_language("how many leaves do i have?") == "english"
    assert detect_reply_language("bhai mughe apni leave ka batao") == "roman"
    assert detect_reply_language("میرے پاس کتنی چھٹیاں باقی ہیں") == "urdu"
    assert detect_reply_language("bhai how many leaves do i have") == "mix"


def test_staff_role_syncs_to_airtable():
    assert employee_id_for("813840798863982602") == "EMP-2602"
    assert staff_kind_from_roles(["staff-1"], staff_role_id="staff-1", admin_role_id="admin-1") == "Staff"
    assert staff_kind_from_roles(["admin-1"], staff_role_id="staff-1", admin_role_id="admin-1") == "HR"
    assert staff_kind_from_roles(["other"], staff_role_id="staff-1", admin_role_id="admin-1") is None
    hr = make_hr()
    record = upsert_staff_employee(
        hr.client,
        discord_id="999888777",
        name="New Staff",
        username="newstaff",
        joined_at="2026-09-09",
        kind="Staff",
        logger=create_logger("error"),
    )
    assert record["fields"]["Discord User ID"] == "999888777"
    assert record["fields"]["Department"] == "Staff"
    names = [item["fields"].get("Name") for item in hr.client.table("leaveBalances").records]
    assert any("New Staff Annual Leave" in str(name) for name in names)
    assert any("New Staff Sick Leave" in str(name) for name in names)
    assert any("New Staff Casual Leave" in str(name) for name in names)


def test_date_resolution():
    today = date(2026, 9, 8)
    assert resolve_date_phrase("tomorrow", today=today) == date(2026, 9, 9)
    saturday = resolve_date_phrase("this Saturday", today=today)
    assert saturday.weekday() == 5
    start, end = resolve_date_range("Monday to Friday", today=today)
    assert start.weekday() == 0
    assert end.weekday() == 4
    nine_eleven = resolve_date_range("9 to 11 sep", today=today)
    assert nine_eleven == (date(2026, 9, 9), date(2026, 9, 11))
    assert resolve_date_range("9-11 sep", today=today) == (date(2026, 9, 9), date(2026, 9, 11))
    assert resolve_date_range("9 se 11 sep", today=today) == (date(2026, 9, 9), date(2026, 9, 11))
    assert resolve_date_range("sep 9 to 11", today=today) == (date(2026, 9, 9), date(2026, 9, 11))
    assert resolve_date_range("9 sep to 11 sep", today=today) == (date(2026, 9, 9), date(2026, 9, 11))
    assert resolve_date_range("20 sep say 25 tak", today=today) == (date(2026, 9, 20), date(2026, 9, 25))
    assert resolve_date_range("20 sep se 25 tak", today=today) == (date(2026, 9, 20), date(2026, 9, 25))
    assert resolve_date_range("2 to 3 days", today=today) == (None, None)
    from app.hr.dates import format_display_date
    assert format_display_date("2026-12-10") == "10 Dec 2026"
    assert parse_day_count("2 days from tomorrow") == 2
    assert parse_day_count("do din") == 2
    assert [item.isoformat() for item in each_date(date(2026, 9, 9), date(2026, 9, 11))] == [
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
    ]


def test_leave_application_format():
    today = date(2026, 9, 8)
    natural = extract_leave_fields("sick leave 1 day 10 sep", today=today)
    assert natural["complete"] is True
    assert natural["start_date"] == date(2026, 9, 10)
    assert natural["days_requested"] == 1

    spoken = extract_leave_fields("10 sep for one day", today=today)
    assert spoken["start_date"] == date(2026, 9, 10)
    assert spoken["days_count"] == 1

    slash = extract_leave_fields("sick leave 10/9", today=today)
    assert slash["start_date"] == date(2026, 9, 10)

    annual_one = extract_leave_fields("I want to apply for annual leave Monday", today=today)
    assert annual_one["leave_type"] == "Annual Leave"
    assert annual_one["complete"] is True

    annual_range = extract_leave_fields("I want to apply for annual leave Monday to Friday", today=today)
    assert annual_range["complete"] is True
    assert annual_range["end_date"] > annual_range["start_date"]

    sick = extract_leave_fields("I want to apply for sick leave tomorrow", today=today)
    assert sick["complete"] is True
    assert sick["start_date"] == sick["end_date"] == date(2026, 9, 9)

    sick_days = extract_leave_fields("apply karo sick leave 2 days kal se", today=today)
    assert sick_days["complete"] is True
    assert sick_days["days_requested"] == 2

    no_date = extract_leave_fields(
        "Sick 1 din ki",
        today=today,
        conversation_history=[{"role": "user", "content": "11 oct"}, {"role": "user", "content": "leave chahiyay"}],
    )
    assert no_date["leave_type"] == "Sick Leave"
    assert no_date["days_count"] == 1
    assert no_date["start_date"] is None
    assert no_date["complete"] is False

    draft_days = {}
    _merge_leave_draft(draft_days, no_date, "Sick 1 din ki")
    assert _leave_draft_ready(draft_days) is False
    asked_days = _ask_leave_details(draft_days, "english").lower()
    assert "from" in asked_days and "to" in asked_days

    draft = {}
    _merge_leave_draft(draft, extract_leave_fields("I want to apply for the leave", today=today), "")
    assert _leave_draft_ready(draft) is False
    asked = _ask_leave_details(draft, "english")
    assert "leave type" in asked.lower()

    _merge_leave_draft(draft, extract_leave_fields("sick leave", today=today), "sick leave")
    assert draft["leave_type"] == "Sick Leave"
    assert _leave_draft_ready(draft) is False
    assert "from" in _ask_leave_details(draft, "english").lower()

    _merge_leave_draft(draft, extract_leave_fields("10 sep for one day", today=today), "10 sep for one day")
    assert _leave_draft_ready(draft) is True
    assert draft["start_date"] == date(2026, 9, 10)

    cricket_prompt = extract_leave_fields(
        "I want leave next Monday for a cricket match — open the form",
        today=today,
    )
    assert "cricket" in (cricket_prompt["reason"] or "").lower()
    fever = extract_leave_fields("sick leave tomorrow because I have a fever", today=today)
    assert "fever" in (fever["reason"] or "").lower()
    wedding = extract_leave_fields("casual leave 20 sep for family wedding", today=today)
    assert "wedding" in (wedding["reason"] or "").lower()
    from app.agent.extraction import infer_leave_reason

    assert "family function" in infer_leave_reason(
        "mujhe kal casual leave chahiye family function ki waja se"
    ).lower()
    assert not infer_leave_reason("I want to apply for annual leave Monday")
    assert not infer_leave_reason("10 sep for one day")
    assert infer_leave_reason("i want a leave tomorrow sick leave as i am ill").lower() == "i am ill"
    assert infer_leave_reason(
        "i want one leave on 23rd september as i am sick and i want a sick leave"
    ).lower() == "i am sick"
    reason_draft = {}
    _merge_leave_draft(
        reason_draft,
        extract_leave_fields("I want casual leave Monday for a cricket match", today=today),
        "",
    )
    assert "cricket" in (reason_draft.get("reason") or "").lower()

    multi = {}
    _merge_leave_draft(multi, extract_leave_fields("apply for sick leave 3 days", today=today), "")
    assert _leave_draft_ready(multi) is False
    assert "from" in _ask_leave_details(multi, "english").lower()

    history = [{"role": "assistant", "content": "Which leave: Annual, Sick, or Casual? How many days?"}]
    assert classify_hr_intent("10 sep", history) == "LEAVE_REQUEST"
    assert classify_hr_intent("sick", history) == "LEAVE_REQUEST"


def test_leave_date_scenarios():
    today = date(2026, 9, 8)
    span = extract_leave_fields("9 to 11 sep", today=today)
    assert span["explicit_range"] is True
    assert span["start_date"] == date(2026, 9, 9)
    assert span["end_date"] == date(2026, 9, 11)
    assert span["days_requested"] == 3

    two = extract_leave_fields("sick leave 2 days 9 sep", today=today)
    assert two["start_date"] == date(2026, 9, 9)
    assert two["end_date"] == date(2026, 9, 10)
    assert two["days_requested"] == 2

    kal = extract_leave_fields("2 days kal", today=today)
    assert kal["start_date"] == date(2026, 9, 9)
    assert kal["days_requested"] == 2

    draft = {"leave_type": "Sick Leave", "days_count": 1}
    _merge_leave_draft(draft, extract_leave_fields("9 to 11 sep", today=today), "9 to 11 sep")
    assert draft["start_date"] == date(2026, 9, 9)
    assert draft["end_date"] == date(2026, 9, 11)
    assert draft["days_count"] == 3
    assert _leave_draft_ready(draft) is True

    slash = extract_leave_fields("10/9 to 12/9", today=today)
    assert slash["start_date"] == date(2026, 9, 10)
    assert slash["end_date"] == date(2026, 9, 12)
    assert slash["days_requested"] == 3

    roman = extract_leave_fields("20 sep say 25 tak", today=today)
    assert roman["explicit_range"] is True
    assert roman["start_date"] == date(2026, 9, 20)
    assert roman["end_date"] == date(2026, 9, 25)
    assert roman["days_requested"] == 6

    router = AgentRouter(config={"hr": {}}, logger=None, rag=None, hr=object())
    router.drafts["7"] = {"leave_type": "Sick Leave", "awaiting_details": True, "locale": "roman"}
    # Chat must not auto-fill dates — user fills via the Fill form modal.
    preview = router._handle_leave_request(
        question="20 sep say 25 tak",
        channel_id="7",
        discord_user_id="1",
        conversation_history=[],
    )
    assert preview["ui"] == "leave_form"
    assert not preview["leaveCard"].get("start_date")
    assert not preview["leaveCard"].get("end_date")
    assert not preview["leaveCard"].get("reason")
    still_empty = router._handle_leave_request(
        question="bukhar",
        channel_id="7",
        discord_user_id="1",
        conversation_history=[],
    )
    assert still_empty["ui"] == "leave_form"
    assert not still_empty["leaveCard"].get("reason")


def test_want_leave_opens_blank_form_without_chat_autofill():
    """Saying 'i want leave' (even with dates in the same message) must open a
    blank leave card — details only come from Fill form / leave-type select."""
    from app.agent.router import apply_leave_form

    router = AgentRouter(config={"hr": {}}, logger=None, rag=None, hr=object())
    opened = router._handle_leave_request(
        question="i want sick leave tomorrow because fever",
        channel_id="77",
        discord_user_id="1",
        conversation_history=[],
    )
    assert opened["ui"] == "leave_form"
    card = opened["leaveCard"]
    assert not card.get("leave_type")
    assert not card.get("start_date")
    assert not card.get("end_date")
    assert not card.get("reason")
    # Leave type comes from the dropdown; dates/reason from Fill form only.
    router.drafts["77"]["leave_type"] = "Sick Leave"
    filled = apply_leave_form(
        router,
        "77",
        from_text="23 Sep 2026",
        to_text="23 Sep 2026",
        reason="fever",
        today=date(2026, 9, 23),
    )
    assert filled["ui"] == "leave_confirm"
    assert filled["leaveCard"]["start_date"] == "2026-09-23"
    assert filled["leaveCard"]["reason"] == "fever"


def test_leave_details_modal_defaults_from_and_to_to_today():
    from app.discord.leave_ui import LeaveDetailsModal

    today = date.today().isoformat()
    modal = LeaveDetailsModal(object(), {})
    assert modal.from_input.default == today
    assert modal.to_input.default == today
    assert modal.from_input.placeholder == today
    assert modal.to_input.placeholder == today
    assert "YYYY-MM-DD" in modal.from_input.label
    # Editing an already-filled draft keeps those dates, not forced today.
    filled = LeaveDetailsModal(
        object(),
        {"start_date": date(2026, 10, 1), "end_date": date(2026, 10, 3)},
    )
    assert filled.from_input.default == "2026-10-01"
    assert filled.to_input.default == "2026-10-03"


def test_cancel_clears_draft_on_new_apply():
    assert is_cancel_submit("nahi") is True
    assert is_new_leave_start("i need leave") is True
    assert is_new_leave_start("Sick 1 din ki") is False

    reused = extract_leave_fields(
        "i need leave",
        today=date(2026, 9, 8),
        conversation_history=[
            {"role": "user", "content": "casual leave 11 to 15 sep"},
        ],
    )
    assert reused["leave_type"] is None
    assert reused["start_date"] is None

    router = AgentRouter(config={"hr": {}}, logger=None, rag=None, hr=object())
    router.drafts["99"] = {
        "leave_type": "Casual Leave",
        "start_date": date(2026, 9, 11),
        "end_date": date(2026, 9, 15),
        "days_count": 5,
        "range_complete": True,
        "awaiting_confirm": True,
        "roman": True,
    }
    cancelled = router._handle_leave_request(
        question="nahi",
        channel_id="99",
        discord_user_id="1",
        conversation_history=[],
    )
    assert "99" not in router.drafts
    assert "cancel" in cancelled["answer"].lower() or "cancel" in cancelled["answer"]

    fresh = router._handle_leave_request(
        question="i need leave",
        channel_id="99",
        discord_user_id="1",
        conversation_history=[{"role": "user", "content": "casual 11 to 15 sep"}],
    )
    assert "2026-09-11" not in fresh["answer"]
    assert "2026-09-15" not in fresh["answer"]
    assert router.drafts["99"].get("awaiting_confirm") is not True
    assert router.drafts["99"].get("start_date") is None


def test_intake_followup_keeps_apply_flow():
    assert is_explicit_leave_apply("need a leav") is True
    history = [{"role": "assistant", "content": "Which leave: Annual, Sick, or Casual? How many days?"}]
    assert classify_hr_intent("sick", history) == "LEAVE_REQUEST"

    router = AgentRouter(config={"hr": {}}, logger=None, rag=None, hr=object())
    first = router._handle_leave_request(
        question="need a leav",
        channel_id="12",
        discord_user_id="1",
        conversation_history=[],
    )
    assert first["ui"] == "leave_form"
    assert "leave type" in first["answer"].lower() or "fill form" in first["answer"].lower()

    second = router._handle_leave_request(
        question="sick",
        channel_id="12",
        discord_user_id="1",
        conversation_history=history + [{"role": "user", "content": "need a leav"}],
    )
    # Chat must not set leave type — that comes from the dropdown only.
    assert "did not create" not in second["answer"].lower()
    assert second["ui"] == "leave_form"
    assert not second["leaveCard"].get("leave_type")


def test_from_to_column_format():
    from app.discord.leave_ui import split_from_to_columns
    from app.agent.router import apply_leave_form

    assert split_from_to_columns("10 Sep 2026  -  25 Sep 2026") == ("10 Sep 2026", "25 Sep 2026")
    assert split_from_to_columns("10 Sep 2026  |  25 Sep 2026") == ("10 Sep 2026", "25 Sep 2026")
    assert split_from_to_columns("10 Sep 2026") == ("10 Sep 2026", "10 Sep 2026")
    left, right = split_from_to_columns("20 sep say 25 tak")
    assert "20" in left and "25" in right

    router = AgentRouter(config={"hr": {}}, logger=None, rag=None, hr=object())
    router.drafts["8"] = {"leave_type": "Sick Leave", "awaiting_details": True, "locale": "english"}
    result = apply_leave_form(
        router,
        "8",
        from_text="10 Sep 2026",
        to_text="25 Sep 2026",
        reason="fever",
        today=date(2026, 9, 8),
    )
    assert result["ui"] == "leave_confirm"
    assert result["leaveCard"]["start_date"] == "2026-09-10"
    assert result["leaveCard"]["end_date"] == "2026-09-25"


def test_leave_balance_embed_shows_asker_name():
    from app.discord.leave_ui import leave_balance_embed

    embed = leave_balance_embed(
        "Here is your live leave balance.\nAvailable now\n• **Annual Leave** — 16 of 16 available (0 used)",
        name="Abdullah",
    )
    assert embed.title == "Abdullah's live leave balance"
    assert embed.author.name is None
    assert "Annual Leave" in embed.description
    unnamed = leave_balance_embed("Available now")
    assert unnamed.title == "Your live leave balance"


def test_leave_card_display_helpers():
    from app.discord.leave_ui import _leave_type_label, _qty, _reason_display, leave_template_embed, leave_pending_embed

    assert _leave_type_label("reczrrTLiX4Wp5Zjv", "Sick Leave") == "Sick Leave"
    assert _qty(10.0) == "10"
    assert "…" in _reason_display("x" * 400)
    form = leave_template_embed({
        "stage": "form",
        "locale": "english",
        "leave_type": "Sick Leave",
    })
    names = [field.name for field in form.fields]
    assert names[:3] == ["Leave type", "Days", "Status"]
    pending = leave_pending_embed({
        "locale": "english",
        "leave_type": "recABC1234567",
        "start_date": "2026-09-11",
        "end_date": "2026-09-12",
        "days": 2,
        "name": "Bilal",
        "reason": "ill",
        "remaining": 10.0,
    })
    assert "recABC" not in pending.description
    assert any(field.name == "From" and "11 Sep 2026" in field.value for field in pending.fields)
    assert "Withdraw" in pending.footer.text


def test_leave_form_does_not_stick_on_other_questions():
    assert looks_like_leave_form_reply("what is my last message you remember?") is False
    assert looks_like_leave_form_reply("sick") is True
    assert looks_like_leave_form_reply("10 sep") is True
    after_submit = [
        {"role": "user", "content": "i need leave"},
        {"role": "assistant", "content": "Leave request submitted"},
        {"role": "assistant", "content": "Here is your live leave balance."},
    ]
    assert in_leave_intake(after_submit) is False
    assert classify_hr_intent("what is my last message you remember?", after_submit) != "LEAVE_REQUEST"

    class DummyRag:
        def answer_question(self, **kwargs):
            return {"answer": "namespace answer", "fallback": True, "chunks": []}

    router = AgentRouter(config={"hr": {}}, logger=None, rag=DummyRag(), hr=object())
    router.drafts["c1"] = {"leave_type": "Sick Leave", "awaiting_details": True, "locale": "english"}
    result = router.handle(
        question="what is my last message you remember?",
        namespace="web airy",
        channel_id="c1",
        discord_user_id="1",
        identity={},
        conversation_history=after_submit,
    )
    assert result.get("ui") not in {"leave_form", "leave_confirm"}
    assert "namespace answer" in result["answer"]


def test_second_want_leave_keeps_one_open_form():
    router = AgentRouter(config={"hr": {}}, logger=None, rag=None, hr=object())
    first = router._handle_leave_request(
        question="i want leave",
        channel_id="form-1",
        discord_user_id="1",
        conversation_history=[],
    )
    assert first.get("ui") == "leave_form"
    router.drafts["form-1"]["leave_type"] = "Sick Leave"
    second = router._handle_leave_request(
        question="i want leave",
        channel_id="form-1",
        discord_user_id="1",
        conversation_history=[],
    )
    assert second.get("ui") == "leave_form"
    assert second["leaveCard"]["leave_type"] == "Sick Leave"

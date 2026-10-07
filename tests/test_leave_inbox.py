"""Private Admin/HR leave inbox: footer lookup and Approve/Reject buttons."""

from types import SimpleNamespace

from app.discord.leave_inbox import inbox_embed, is_leave_review_channel, ticket_channel_id_from_message, ticket_field_text, ticket_id_from_footer
from app.discord.leave_review import LEAVE_APPROVE_ID, LEAVE_REJECT_ID, LeaveReviewView


def test_ticket_field_shows_display_name_not_a_channel_mention():
    assert ticket_field_text(display_name="Mohib Hasan", channel_name="ticket-mohibhasan09-6920") == (
        "Mohib Hasan\n#ticket-mohibhasan09-6920"
    )
    assert "<#" not in ticket_field_text(display_name="Mohib Hasan", channel_id="123")


def test_ticket_id_is_read_from_the_inbox_footer():
    assert ticket_id_from_footer("ticket:123456789") == "123456789"
    assert ticket_id_from_footer("Decided by Alex · ticket:123456789") == "123456789"
    assert ticket_id_from_footer("not a ticket") == ""


def test_ticket_id_is_read_from_the_ticket_field_when_footer_is_empty():
    embed = SimpleNamespace(
        footer=SimpleNamespace(text=""),
        fields=[SimpleNamespace(name="Ticket", value="<#9001>")],
    )
    message = SimpleNamespace(embeds=[embed], id=99)
    assert ticket_channel_id_from_message(message) == "9001"


def test_polish_reviewer_card_hides_ids_and_file_urls():
    from app.discord.leave_inbox import polish_reviewer_card

    card = polish_reviewer_card(
        {
            "leave_type": "recXmcQopyDGO3tWR",
            "name": "Employee",
            "reason": "yyy\nAttachments:\nHR_Confirmed_Scope.docx: https://cdn.discordapp.com/ephemeral-attachments/1/file.docx",
            "requestId": "recXmcQopyDGO3tWR",
        },
        employee={"name": "Bilal chaudhry"},
        display_name="Bilal",
        ticket_name="ticket-bilal-1",
    )
    assert card["leaveType"] == "Leave"
    assert "rec" not in card["leave_type"]
    assert card["name"] == "Bilal chaudhry"
    assert "cdn.discordapp.com" not in card["reason"]
    assert "HR_Confirmed_Scope.docx" in card["reason"]
    assert card["requestId"] == "—"


def test_inbox_embed_hides_record_ids():
    embed = inbox_embed(
        {
            "leave_type": "Casual Leave",
            "start_date": "2026-10-05",
            "end_date": "2026-10-05",
            "days": 1,
            "name": "Bilal chaudhry",
            "reason": "yyy\nAttached file: HR_Confirmed_Scope.docx",
        },
        ticket_channel_id="9001",
        ticket_name="ticket-bilal-1",
    )
    assert "Casual Leave" in embed.description
    assert "recXmc" not in (embed.description or "")
    reason = next(field.value for field in embed.fields if field.name == "Reason")
    assert "cdn.discordapp.com" not in reason


def test_inbox_embed_points_at_the_staff_ticket():
    embed = inbox_embed(
        {
            "leave_type": "Annual Leave",
            "start_date": "2026-09-21",
            "end_date": "2026-09-22",
            "days": 2,
            "name": "Alex",
            "reason": "Family",
        },
        ticket_channel_id="9001",
        employee_mention="<@42>",
        ticket_name="ticket-alex-9001",
    )
    assert embed.footer.text == "Waiting for a decision"
    ticket_field = next(field.value for field in embed.fields if field.name == "Ticket")
    assert "Alex" in ticket_field
    assert "#ticket-alex-9001" in ticket_field
    assert "<#" not in ticket_field
    assert "ticket:9001" not in (embed.footer.text or "")
    assert "Annual Leave" in embed.description


def test_leave_review_view_is_approve_and_reject():
    view = LeaveReviewView(bot=SimpleNamespace())
    labels = [item.label for item in view.children]
    ids = [item.custom_id for item in view.children]
    assert labels == ["Approve", "Reject"]
    assert ids == [LEAVE_APPROVE_ID, LEAVE_REJECT_ID]
    assert view.timeout is None


def test_decision_card_shows_approved_or_rejected_status():
    from datetime import date

    from app.discord.leave_review import decision_summary_embed

    day = date(2026, 9, 21).isoformat()
    request = {
        "employeeName": "Alex",
        "leaveType": "Annual Leave",
        "startDate": day,
        "endDate": day,
        "daysRequested": 1,
        "status": "PENDING_HR",
    }
    approved = decision_summary_embed(
        request, outcome="approved", actor="Admin", ticket_channel_id="9001", ticket_name="ticket-alex-9001"
    )
    rejected = decision_summary_embed(request, outcome="rejected", actor="Bilal", ticket_channel_id="9001")
    moved = decision_summary_embed(request, outcome="moved", actor="HOD", ticket_channel_id="9001")
    assert approved.title == "Leave approved"
    assert any(field.name == "Status" and "Approved" in field.value for field in approved.fields)
    assert rejected.title == "Leave declined"
    assert any(field.name == "Status" and "Rejected" in field.value for field in rejected.fields)
    assert any(field.name == "Status" and "Waiting for HR" in field.value for field in moved.fields)
    ticket_field = next(field.value for field in approved.fields if field.name == "Ticket")
    assert "Alex" in ticket_field
    assert "#ticket-alex-9001" in ticket_field
    assert "<#" not in ticket_field


def test_leave_requests_channel_is_recognised_by_name_or_id():
    config = {"discord": {"tickets": {"leaveReviewChannelId": "55"}}}
    by_id = SimpleNamespace(id=55, name="something-else")
    by_name = SimpleNamespace(id=1, name="leave-requests")
    other = SimpleNamespace(id=2, name="hr-help")
    assert is_leave_review_channel(by_id, config)
    assert is_leave_review_channel(by_name, config)
    assert not is_leave_review_channel(other, config)
    assert not is_leave_review_channel(None, config)

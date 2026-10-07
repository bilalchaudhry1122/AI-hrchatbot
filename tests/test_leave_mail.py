from tests.test_leave_workflow import make_hr


def _seed_reviewers(hr):
    employees = hr.client.table("employees")
    employees.records[0]["fields"]["Email"] = "member@example.com"
    employees.records[0]["fields"]["HR Role"] = "Member"
    employees.records[2]["fields"]["Email"] = "bi.hod@example.com"
    employees.records[2]["fields"]["HR Role"] = "HOD"
    employees.records[2]["fields"]["Department"] = "BI"
    employees.records[3]["fields"]["Email"] = "mkt.hod@example.com"
    employees.records[3]["fields"]["HR Role"] = "HOD"
    employees.records[3]["fields"]["Department"] = "Marketing"
    employees.records.append({
        "id": "recEmpHr",
        "fields": {
            "Employee Name": "HR Desk",
            "Discord User ID": "999",
            "Department": "HR",
            "HR Role": "HR",
            "Status": "Active",
            "Email": "hr@example.com",
        },
    })
    employees.records.append({
        "id": "recEmpCsHod",
        "fields": {
            "Employee Name": "CS HOD",
            "Discord User ID": "888",
            "Department": "CS",
            "HR Role": "HOD",
            "Status": "Active",
            "Email": "cs.hod@example.com",
        },
    })
    return {"mail": {"hod": {}, "hr": ""}}


def test_split_and_validate_emails():
    from app.mail.leave import is_email, split_emails

    assert is_email("bi.hod@webairy.com") is True
    assert is_email("not-an-email") is False
    assert split_emails("a@x.com; b@y.com,a@x.com") == ["a@x.com", "b@y.com"]


def test_hod_mail_only_matches_that_channel():
    from app.mail.leave import notice_emails

    hr = make_hr()
    config = _seed_reviewers(hr)
    cs = notice_emails(hr.client, config, waiting_hod=True, department="CS")
    bi = notice_emails(hr.client, config, waiting_hod=True, department="BI")
    assert cs == ["cs.hod@example.com"]
    assert bi == ["bi.hod@example.com"]
    assert "hr@example.com" not in cs
    assert "mkt.hod@example.com" not in cs


def test_hr_mail_only_for_leave_requests():
    from app.mail.leave import notice_emails

    hr = make_hr()
    config = _seed_reviewers(hr)
    to_hr = notice_emails(hr.client, config, waiting_hod=False, department="CS")
    assert to_hr == ["hr@example.com"]
    assert "cs.hod@example.com" not in to_hr


def test_hod_mail_from_discord_roles():
    from app.mail.leave import notice_emails

    hr = make_hr()
    config = _seed_reviewers(hr)
    hr.client.table("employees").records.append({
        "id": "recEmpCsHodRoles",
        "fields": {
            "Employee Name": "CS HOD roles",
            "Discord User ID": "777",
            "Department": "CS",
            "HR Role": "Member",
            "Status": "Active",
            "Email": "cs.roles@example.com",
            "Discord Roles": "CS Member\nCS HOD",
        },
    })
    assert notice_emails(hr.client, config, waiting_hod=True, department="CS") == [
        "cs.hod@example.com",
        "cs.roles@example.com",
    ]


def test_airtable_hr_and_hod_emails_are_used():
    from app.mail.leave import notice_emails

    hr = make_hr()
    config = _seed_reviewers(hr)
    config["mail"] = {"hod": {"BI": "ignored.bi@example.com", "CS": "ignored.cs@example.com"}, "hr": ""}
    assert notice_emails(hr.client, config, waiting_hod=True, department="BI") == ["bi.hod@example.com"]
    assert notice_emails(hr.client, config, waiting_hod=True, department="CS") == ["cs.hod@example.com"]
    assert notice_emails(hr.client, config, waiting_hod=False) == ["hr@example.com"]


def test_env_hr_is_leave_mail_to():
    from app.mail.leave import approved_mail_recipients, notice_emails

    hr = make_hr()
    config = _seed_reviewers(hr)
    config["mail"] = {
        "hod": {"BI": "", "CS": "env.cs@example.com", "Marketing": ""},
        "hr": "syed.mohib@webairy.com",
    }
    assert notice_emails(hr.client, config, waiting_hod=True, department="CS") == ["cs.hod@example.com"]
    assert notice_emails(hr.client, config, waiting_hod=False) == ["syed.mohib@webairy.com"]
    to_addr, cc_addr = approved_mail_recipients(
        hr.client,
        config,
        {"department": "BI", "managerApprovedBy": "BI HOD (333)"},
    )
    assert to_addr == ["syed.mohib@webairy.com"]
    assert cc_addr == ["bi.hod@example.com"]


def test_exclude_applicant_when_another_hr_exists():
    from app.mail.leave import notice_emails

    hr = make_hr()
    config = _seed_reviewers(hr)
    hr.client.table("employees").records.append({
        "id": "recEmpHr2",
        "fields": {
            "Employee Name": "HR Two",
            "Discord User ID": "998",
            "Department": "HR",
            "HR Role": "HR",
            "Status": "Active",
            "Email": "hr2@example.com",
        },
    })
    assert notice_emails(hr.client, config, waiting_hod=False, exclude=["hr@example.com"]) == [
        "hr2@example.com"
    ]


def test_leave_mail_hides_airtable_ids():
    from app.mail.leave import leave_mail_html, leave_mail_subject, leave_mail_text
    from app.records.leave_types import public_leave_type_name

    types = [{"id": "recXmcQopyDGO3tWR", "name": "Casual Leave", "code": "CASUAL"}]
    assert public_leave_type_name("recXmcQopyDGO3tWR", types) == "Casual Leave"
    card = {
        "name": "Bilal chaudhry",
        "leave_type": "recXmcQopyDGO3tWR",
        "department": "BI",
        "start_date": "2026-10-05",
        "end_date": "2026-10-05",
        "days": 1,
        "reason": "yyy\nAttachments:\nHR_Confirmed_Scope.docx: https://cdn.discordapp.com/ephemeral-attachments/1/file.docx",
        "id": "recXmcQopyDGO3tWR",
        "requestId": "LR-20260916-1",
    }
    polished = {
        **card,
        "leave_type": public_leave_type_name(card["leave_type"], types),
        "leaveType": public_leave_type_name(card["leave_type"], types),
    }
    subject = leave_mail_subject(polished)
    assert "Casual Leave" in subject
    assert "approved" in subject.lower()
    assert "recXmc" not in subject
    text = leave_mail_text(polished)
    assert "Casual Leave" in text
    assert "cdn.discordapp.com" not in text
    html = leave_mail_html(polished)
    assert "Casual Leave" in html
    assert "cdn.discordapp.com" not in html


def test_leave_mail_copy():
    from app.mail.leave import leave_mail_html, leave_mail_subject, leave_mail_text

    card = {
        "name": "Shahzad",
        "leave_type": "Casual Leave",
        "department": "BI",
        "start_date": "2026-10-01",
        "end_date": "2026-10-01",
        "days": 1,
        "reason": "personal",
        "requestId": "LR-1",
        "ticketName": "ticket-shahzad",
    }
    card["managerApprovedBy"] = "Shahzad (333)"
    card["approvedBy"] = "HR Desk (999)"
    assert "[WebAiry]" in leave_mail_subject(card)
    assert "approved" in leave_mail_subject(card).lower()
    assert "HOD review" not in leave_mail_subject(card)
    text = leave_mail_text(card)
    assert "Shahzad" in text
    assert "no-reply" in text.lower()
    assert "Do not reply" in text
    assert "Start date" in text
    assert "Approved by HOD" in text
    html = leave_mail_html(card)
    assert "Dear HR" in html
    assert "Shahzad" in html
    assert "noreply@webairy.com" in html
    assert "Get Global. Go WebAiry" in html
    assert "https://www.webairy.com/assets/img/logo-A.png" in html
    assert "facebook.com/webairy" not in html
    assert "Client Area" not in html
    assert 'bgcolor="#5b01a3"' in html
    assert "background-color:#5b01a3" in html
    assert "border-radius:22px 22px 0 0" in html
    assert "border-radius:0 0 22px 22px" in html


def test_approved_mail_ccs_the_hod_who_approved():
    from app.mail.leave import actor_discord_id, approved_mail_recipients

    assert actor_discord_id("BI HOD (333)") == "333"
    hr = make_hr()
    config = _seed_reviewers(hr)
    to_addr, cc_addr = approved_mail_recipients(
        hr.client,
        config,
        {"managerApprovedBy": "BI HOD (333)", "department": "BI"},
    )
    assert to_addr == ["hr@example.com"]
    assert cc_addr == ["bi.hod@example.com"]
    # HOD no longer approves anything, so the "who approved" bookkeeping is
    # gone. The department's HOD is Cc'd purely as a notification, always.
    to_notify, cc_notify = approved_mail_recipients(
        hr.client,
        config,
        {"approvedBy": "HR Desk (999)", "department": "BI"},
    )
    assert to_notify == ["hr@example.com"]
    assert cc_notify == ["bi.hod@example.com"]


def test_approved_mail_cc_uses_airtable_hod_email():
    from app.mail.leave import approved_mail_recipients

    hr = make_hr()
    config = _seed_reviewers(hr)
    hr.client.table("employees").records[2]["fields"]["Email"] = "nc6asdoztdwnbmof@ethereal.email"
    config["mail"] = {
        "hod": {"BI": "syed.mohib@example.com", "CS": "", "Marketing": ""},
        "hr": "hr@example.com",
    }
    _to, cc_skip = approved_mail_recipients(
        hr.client,
        config,
        {"managerApprovedBy": "BI HOD (333)", "department": "BI"},
    )
    assert "ethereal" not in ",".join(cc_skip).lower()
    assert "syed.mohib@example.com" not in cc_skip
    hr.client.table("employees").records[2]["fields"]["Email"] = "bi.live@example.com"
    _to, cc_addr = approved_mail_recipients(
        hr.client,
        config,
        {"managerApprovedBy": "BI HOD (333)", "department": "BI"},
    )
    assert cc_addr == ["bi.live@example.com"]


def test_approved_mail_ccs_department_hod_when_hod_inbox_was_used():
    from app.mail.leave import approved_mail_recipients, leave_mail_text

    hr = make_hr()
    config = _seed_reviewers(hr)
    to_addr, cc_addr = approved_mail_recipients(
        hr.client,
        config,
        {"department": "BI", "hodInboxChannelId": "1549"},
    )
    assert to_addr == ["hr@example.com"]
    assert cc_addr == ["bi.hod@example.com"]
    text = leave_mail_text({
        "name": "Bilal chaudhry",
        "leave_type": "Sick Leave",
        "department": "BI",
        "hodInboxChannelId": "1549",
        "approvedBy": "IBTIHAJ (1)",
    })
    assert "Head of Department" in text
    assert "Approved by HOD" in text


def test_cancelled_mail_shows_details_and_ccs_approving_hod():
    from app.mail.leave import approved_mail_recipients, leave_mail_html, leave_mail_subject, leave_mail_text

    hr = make_hr()
    config = _seed_reviewers(hr)
    card = {
        "name": "Abdullah",
        "employeeName": "Abdullah",
        "leave_type": "Sick Leave",
        "department": "BI",
        "start_date": "2026-10-05",
        "end_date": "2026-10-05",
        "days": 1,
        "reason": "fever",
        "rejectionReason": "Plans changed",
        "cancelledBy": "Abdullah (111)",
        "requestId": "LR-CANCEL-1",
        "ticketName": "ticket-abdullah",
        "managerApprovedBy": "BI HOD (333)",
        "approvedBy": "HR Desk (999)",
    }
    to_addr, cc_addr = approved_mail_recipients(hr.client, config, card, outcome="cancelled")
    assert to_addr == ["hr@example.com"]
    assert cc_addr == ["bi.hod@example.com"]
    subject = leave_mail_subject(card, outcome="cancelled")
    assert "cancelled" in subject.lower()
    assert "Sick Leave" in subject
    text = leave_mail_text(card, outcome="cancelled")
    assert "has been cancelled" in text
    assert "Plans changed" in text
    assert "Sick Leave" in text
    html = leave_mail_html(card, outcome="cancelled")
    assert "leave cancelled" in html
    assert "Plans changed" in html
    assert "This leave is now cancelled in the HR record." in html
    assert "Get Global. Go WebAiry" in html
    assert "https://www.webairy.com/assets/img/logo-A.png" in html


def test_cancelled_mail_ccs_department_hod_without_hod_label():
    from app.mail.leave import approved_mail_recipients

    hr = make_hr()
    config = _seed_reviewers(hr)
    to_addr, cc_addr = approved_mail_recipients(
        hr.client,
        config,
        {"department": "Marketing", "approvedBy": "HR Desk (999)"},
        outcome="cancelled",
    )
    assert to_addr == ["hr@example.com"]
    assert cc_addr == ["mkt.hod@example.com"]
    # Same department HOD is Cc'd on the approved outcome too — the HOD Cc
    # is unconditional now, not tied to an "approving HOD" bookkeeping trail.
    to_approved, cc_approved = approved_mail_recipients(
        hr.client,
        config,
        {"department": "Marketing", "approvedBy": "HR Desk (999)"},
        outcome="approved",
    )
    assert to_approved == ["hr@example.com"]
    assert cc_approved == ["mkt.hod@example.com"]


def test_mail_to_falls_back_to_smtp_username():
    from app.mail.leave import approved_mail_recipients

    hr = make_hr()
    for rec in hr.client.table("employees").records:
        rec["fields"]["HR Role"] = "Member"
        rec["fields"]["Email"] = ""
        rec["fields"]["Discord Roles"] = "CS Member"
    config = {"mail": {"hod": {}, "hr": "", "username": "desk@webairy.com"}}
    to_addr, cc_addr = approved_mail_recipients(
        hr.client,
        config,
        {"department": "CS"},
        extra_to=["employee@webairy.com"],
    )
    assert to_addr == ["desk@webairy.com"]
    assert cc_addr == []


def test_mail_to_is_hr_role_only_not_employee():
    from app.mail.leave import approved_mail_recipients

    hr = make_hr()
    config = _seed_reviewers(hr)
    to_addr, cc_addr = approved_mail_recipients(
        hr.client,
        config,
        {"department": "BI", "managerApprovedBy": "BI HOD (333)"},
        extra_to=["member@example.com"],
    )
    assert to_addr == ["hr@example.com"]
    assert "member@example.com" not in to_addr
    assert cc_addr == ["bi.hod@example.com"]


def test_discord_hr_role_on_member_is_not_mail_to():
    from app.mail.leave import notice_emails

    hr = make_hr()
    config = _seed_reviewers(hr)
    hr.client.table("employees").records[0]["fields"]["HR Role"] = "Member"
    hr.client.table("employees").records[0]["fields"]["Email"] = "m.abdullah@example.com"
    hr.client.table("employees").records[0]["fields"]["Discord Roles"] = "BI Member\nHR"
    assert notice_emails(hr.client, config, waiting_hod=False) == ["hr@example.com"]
    assert "m.abdullah@example.com" not in notice_emails(hr.client, config, waiting_hod=False)



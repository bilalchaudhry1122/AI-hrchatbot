"""Who gets leave request emails, and the message body."""

import re

from app.hr.dates import format_display_date
from app.hr.departments import DEPARTMENTS, normalize_department

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

WEBAIRY_SITE = "https://www.webairy.com"
WEBAIRY_LOGO = "https://www.webairy.com/assets/img/logo-A.png"
WEBAIRY_PURPLE = "#5b01a3"
WEBAIRY_NAVY = "#020185"
WEBAIRY_BAND = (
    f"background-color:{WEBAIRY_PURPLE};"
    f"background:{WEBAIRY_PURPLE};"
    f"background-image:linear-gradient(180deg, {WEBAIRY_NAVY}, {WEBAIRY_PURPLE});"
    "color:#ffffff;"
)


def is_email(value):
    return bool(EMAIL_RE.match(str(value or "").strip()))


def is_reviewer_email(value):
    email = str(value or "").strip()
    if not is_email(email):
        return False
    return not email.lower().endswith("@ethereal.email")


def split_emails(raw):
    found = []
    for part in re.split(r"[,\s;]+", str(raw or "")):
        text = part.strip()
        if is_email(text) and text.lower() not in {item.lower() for item in found}:
            found.append(text)
    return found


def _from_employees(client, logger=None):
    from app.records.employees import list_employees
    from app.hr.departments import hod_department_from_role_names

    hods = {key: [] for key in DEPARTMENTS}
    hr = []
    if client is None:
        return hods, hr
    try:
        people = list_employees(client, logger=logger)
    except Exception as error:
        if logger:
            logger.warn("Could not load employee emails", {"message": str(error)[:200]})
        return hods, hr
    for person in people:
        if not person.get("active"):
            continue
        email = str(person.get("email") or "").strip()
        if not is_reviewer_email(email):
            continue
        role = str(person.get("hrRole") or "").strip()
        names = [line.strip() for line in str(person.get("discordRoles") or "").splitlines() if line.strip()]
        named_hod = hod_department_from_role_names(names)
        dept = named_hod or normalize_department(person.get("department"))
        is_hr = role in {"HR", "Admin"}
        is_hod = (role == "HOD" or bool(named_hod)) and role not in {"HR", "Admin"}
        if is_hod and dept in DEPARTMENTS:
            if email.lower() not in {item.lower() for item in hods[dept]}:
                hods[dept].append(email)
        if is_hr:
            if email.lower() not in {item.lower() for item in hr}:
                hr.append(email)
    return hods, hr


def _unique(emails, *, exclude=None):
    skip = {str(item).strip().lower() for item in (exclude or []) if str(item or "").strip()}
    out = []
    seen = set()
    for email in emails or []:
        key = str(email or "").strip().lower()
        if not key or key in seen or key in skip:
            continue
        seen.add(key)
        out.append(str(email).strip())
    if out or not skip:
        return out
    # Applicant is also the only inbox address (shared test mailbox). Still send.
    return _unique(emails)


def hod_emails(client, config, department, *, logger=None, exclude=None):
    """HOD Email on the Employees row for that department."""
    del config
    hods, _hr = _from_employees(client, logger=logger)
    dept = normalize_department(department)
    found = list(hods.get(dept) or []) if dept in DEPARTMENTS else []
    return _unique(found, exclude=exclude)


def smtp_fallback_emails(config):
    """SMTP login only if env and Employees have no HR Email."""
    mail = (config or {}).get("mail") or {}
    return split_emails(mail.get("username") or "")


def env_hr_emails(config):
    mail = (config or {}).get("mail") or {}
    return split_emails(mail.get("hr") or "")


def hr_emails(client, config, *, logger=None, exclude=None):
    """LEAVE_MAIL_HR from env, then Employees HR Role, then SMTP login."""
    found = _unique(env_hr_emails(config), exclude=exclude)
    if found:
        return found
    _hods, hr = _from_employees(client, logger=logger)
    found = _unique(hr, exclude=exclude)
    if found:
        return found
    return _unique(smtp_fallback_emails(config), exclude=exclude)


def notice_emails(client, config, *, waiting_hod=False, department="", logger=None, exclude=None):
    if waiting_hod:
        return hod_emails(client, config, department, logger=logger, exclude=exclude)
    return hr_emails(client, config, logger=logger, exclude=exclude)


def actor_discord_id(label):
    text = str(label or "").strip()
    if text.endswith(")") and "(" in text:
        inner = text[text.rfind("(") + 1 : -1].strip()
        if inner.isdigit():
            return inner
    return ""


def actor_display_name(label):
    text = str(label or "").strip()
    if text.endswith(")") and "(" in text:
        name = text[: text.rfind("(")].strip()
        return name or text
    return text


def _email_for_discord_id(client, discord_id, *, logger=None):
    from app.records.employees import lookup_employee_by_discord_id

    user_id = str(discord_id or "").strip()
    if not user_id or client is None:
        return []
    try:
        person = lookup_employee_by_discord_id(client, user_id, logger=logger)
    except Exception:
        return []
    email = str((person or {}).get("email") or "").strip()
    if is_reviewer_email(email):
        return [email]
    return []


def approving_hod_emails(client, config, request, *, logger=None, outcome="approved"):
    """Cc the department's HOD. HOD no longer approves — they are always Cc'd
    on every decision for their department, purely as a notification."""
    del outcome
    card = request or {}
    dept = normalize_department(card.get("department"))
    if dept in DEPARTMENTS:
        return hod_emails(client, config, dept, logger=logger)
    return []


def approved_mail_recipients(
    client,
    config,
    request,
    *,
    logger=None,
    exclude=None,
    extra_to=None,
    outcome="approved",
):
    to_addresses = hr_emails(client, config, logger=logger, exclude=exclude)
    del extra_to
    if not to_addresses:
        to_addresses = _unique(smtp_fallback_emails(config), exclude=exclude)
    skip = list(to_addresses or []) + list(exclude or [])
    cc_addresses = _unique(
        approving_hod_emails(client, config, request, logger=logger, outcome=outcome),
        exclude=skip,
    )
    if not to_addresses and cc_addresses:
        to_addresses = cc_addresses
        cc_addresses = []
    return to_addresses, cc_addresses


def _field(card, *keys, fallback="—"):
    for key in keys:
        value = (card or {}).get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return fallback


def _hod_name(card):
    named = actor_display_name(_field(card, "managerApprovedBy", "hodApprovedBy", fallback=""))
    if named and named != "—":
        return named
    extra = _field(card, "hodApprovedName", fallback="")
    if extra and extra != "—":
        return extra
    if (card or {}).get("hodInboxChannelId") or (card or {}).get("hodApprovedId"):
        return "Head of Department"
    return "—"


def _hr_name(card):
    return actor_display_name(_field(card, "approvedBy", fallback="")) or "—"


def _action_copy(card, *, outcome="approved"):
    hod = _hod_name(card)
    if outcome == "cancelled":
        if hod != "—":
            return (
                f"This approved leave has been cancelled by the employee. "
                f"The Head of Department ({hod}) is copied. "
                "The days were returned to the leave balance."
            )
        return (
            "This approved leave has been cancelled by the employee. "
            "The days were returned to the leave balance. This message is a record for HR."
        )
    if hod != "—":
        return (
            f"This leave has been approved by the Head of Department ({hod}) "
            "and by Human Resources. This message is a record for HR. "
            "The approving HOD is copied."
        )
    return (
        "This leave has been approved by Human Resources. "
        "This message is a record for HR."
    )


def _cancel_reason_for_mail(card):
    from app.discord.attachments import public_reason_text

    return public_reason_text(
        _field(card, "rejectionReason", "cancelReason", "cancelledReason"),
        empty="—",
    )


def _reason_for_mail(card):
    from app.discord.attachments import public_reason_text

    return public_reason_text(_field(card, "reason"), empty="—")


def _leave_type_for_mail(card):
    from app.records.leave_types import looks_like_record_id, public_leave_type_name

    raw = _field(card, "leave_type", "leaveType", fallback="Leave")
    label = public_leave_type_name(raw)
    if looks_like_record_id(label):
        return "Leave"
    return label


def _request_id_for_mail(card):
    from app.records.leave_types import looks_like_record_id

    rid = _field(card, "requestId", fallback="—")
    if looks_like_record_id(rid):
        return "—"
    return rid


def leave_mail_subject(card, *, waiting_hod=False, outcome="approved"):
    name = _field(card, "name", "employeeName", fallback="Employee")
    leave_type = _leave_type_for_mail(card)
    if outcome == "cancelled":
        return f"[WebAiry] Leave cancelled — {leave_type} — {name}"
    return f"[WebAiry] Leave approved — {leave_type} — {name}"


def leave_mail_text(card, *, waiting_hod=False, company="WebAiry", outcome="approved"):
    name = _field(card, "name", "employeeName", fallback="Employee")
    leave_type = _leave_type_for_mail(card)
    days = _field(card, "days", "daysRequested")
    department = normalize_department((card or {}).get("department")) or "—"
    reason = _reason_for_mail(card)
    request_id = _request_id_for_mail(card)
    ticket = _field(card, "ticketName", "channelName")
    action = _action_copy(card, outcome=outcome)
    start = format_display_date((card or {}).get("start_date") or (card or {}).get("startDate")) or "—"
    end = format_display_date((card or {}).get("end_date") or (card or {}).get("endDate")) or start
    hod = _hod_name(card)
    hr_name = _hr_name(card)
    cancelled = outcome == "cancelled"
    title = "leave cancelled" if cancelled else "leave approved"
    headline = (
        f"{name}'s approved leave has been cancelled."
        if cancelled
        else f"{name}'s leave request has been approved."
    )
    extra = ""
    if cancelled:
        extra = (
            f"  Cancellation reason: {_cancel_reason_for_mail(card)}\n"
            f"  Cancelled by: {actor_display_name(_field(card, 'cancelledBy', fallback='Employee'))}\n"
        )
    return (
        f"{company} HR — {title}\n"
        "This is an automated no-reply message. Do not reply to this email.\n\n"
        f"Dear HR,\n\n"
        f"{headline}\n\n"
        "Request details\n"
        f"  Employee: {name}\n"
        f"  Department: {department}\n"
        f"  Leave type: {leave_type}\n"
        f"  Start date: {start}\n"
        f"  End date: {end}\n"
        f"  Working days: {days}\n"
        f"  Reason: {reason}\n"
        f"{extra}"
        f"  Request ID: {request_id}\n"
        f"  Staff ticket: {ticket}\n"
        f"  Approved by HOD: {hod}\n"
        f"  Approved by HR: {hr_name}\n\n"
        f"{action}\n\n"
        "Replies to this mailbox are not monitored.\n\n"
        f"Kind regards,\n{company} HR assistant\n"
        "noreply@webairy.com"
    )


def leave_mail_html(card, *, waiting_hod=False, company="WebAiry", outcome="approved"):
    import html as html_lib

    def esc(value):
        return html_lib.escape(str(value or ""), quote=True)

    name = esc(_field(card, "name", "employeeName", fallback="Employee"))
    leave_type = esc(_leave_type_for_mail(card))
    days = esc(_field(card, "days", "daysRequested"))
    department = esc(normalize_department((card or {}).get("department")) or "—")
    reason = esc(_reason_for_mail(card))
    request_id = esc(_request_id_for_mail(card))
    ticket = esc(_field(card, "ticketName", "channelName"))
    action = esc(_action_copy(card, outcome=outcome))
    start = esc(format_display_date((card or {}).get("start_date") or (card or {}).get("startDate")) or "—")
    end = esc(format_display_date((card or {}).get("end_date") or (card or {}).get("endDate")) or start)
    hod = esc(_hod_name(card))
    hr_name = esc(_hr_name(card))
    company_e = esc(company)
    cancelled = outcome == "cancelled"
    headline = (
        f"{name}'s approved leave has been cancelled."
        if cancelled
        else f"{name}'s leave request has been approved."
    )
    banner = f"{company_e} leave cancelled" if cancelled else f"{company_e} leave approved"
    followup = (
        "This leave is now cancelled in the HR record."
        if cancelled
        else "No further action is required in Discord for this request."
    )
    rows = [
        ("Employee", name),
        ("Department", department),
        ("Leave type", leave_type),
        ("Start date", start),
        ("End date", end),
        ("Working days", days),
        ("Reason", reason),
    ]
    if cancelled:
        rows.append(("Cancellation reason", esc(_cancel_reason_for_mail(card))))
        rows.append(("Cancelled by", esc(actor_display_name(_field(card, "cancelledBy", fallback="Employee")))))
    rows.extend([
        ("Request ID", request_id),
        ("Staff ticket", ticket),
        ("Approved by HOD", hod),
        ("Approved by HR", hr_name),
    ])
    row_html = "".join(
        f'<tr><td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#6b7280;width:160px;">{esc(label)}</td>'
        f'<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#111827;">{value}</td></tr>'
        for label, value in rows
    )
    status_bar = (
        f'<div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#e9d5ff;">{esc("Automated no-reply")}</div>'
        f'<div style="font-size:18px;font-weight:600;margin-top:6px;color:#ffffff;">{banner}</div>'
    )
    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="color-scheme" content="light" />
    <meta name="supported-color-schemes" content="light" />
  </head>
  <body style="margin:0; padding:0; background-color:#f4f4f4; font-family:Helvetica, Arial, sans-serif;">
    <center>
      <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" bgcolor="#f4f4f4" role="presentation">
        <tr>
          <td align="center">
            <table width="600" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" role="presentation" style="border-radius:22px; border:1px solid #dddddd; overflow:hidden;">
              <tr>
                <td align="center" bgcolor="{WEBAIRY_PURPLE}" style="{WEBAIRY_BAND} padding:30px 20px 18px; border-radius:22px 22px 0 0;">
                  <a href="{WEBAIRY_SITE}" style="text-decoration:none;">
                    <img src="{WEBAIRY_LOGO}" alt="{company_e}" width="180" style="display:block; width:180px; max-width:180px; height:auto; border:0; margin:0 auto;" />
                  </a>
                  <div style="font-size:16px; font-weight:500; letter-spacing:1px; margin-top:8px; margin-bottom:5px; color:#ffffff;">
                    Get Global. Go WebAiry
                  </div>
                  {status_bar}
                </td>
              </tr>
              <tr>
                <td bgcolor="#ffffff" style="padding:25px 20px; font-size:14px; color:#333333; line-height:1.6; background-color:#ffffff;">
                  <p style="margin:0 0 16px;color:#111827;font-size:15px;">Dear HR,</p>
                  <p style="margin:0 0 20px;color:#374151;font-size:15px;line-height:1.5;">{headline}</p>
                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#ffffff" style="border:1px solid #e5e7eb;border-radius:6px;background-color:#ffffff;">{row_html}</table>
                  <p style="margin:20px 0 0;color:#374151;font-size:15px;line-height:1.5;">{action}</p>
                  <p style="margin:16px 0 0;color:#111827;font-size:15px;font-weight:600;">{followup}</p>
                  <p style="margin:16px 0 0;color:#6b7280;font-size:12px;line-height:1.5;">
                    This mailbox is not monitored. Do not reply.<br>
                    Kind regards,<br>{company_e} HR assistant · noreply@webairy.com
                  </p>
                </td>
              </tr>
              <tr>
                <td align="center" bgcolor="{WEBAIRY_PURPLE}" style="{WEBAIRY_BAND} padding:25px 20px; font-size:13px; border-radius:0 0 22px 22px;">
                  <div style="font-size:13px; font-weight:500; color:#ffffff; margin-bottom:12px; margin-top:4px;">
                    For security purposes, we request you not to share this sensitive information with anyone.
                  </div>
                  <div style="color:#e9d5ff; font-size:12px;">
                    Copyright © {company_e}, All rights reserved.
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </center>
  </body>
</html>"""

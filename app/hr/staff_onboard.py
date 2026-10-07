import re
from datetime import datetime, timezone

from app.records.employees import _escape
from app.records.fields import is_unknown_field_name
from app.records.leave_types import get_active_leave_types
from app.hr.departments import department_from_role_names, hod_department_from_role_names, normalize_department
from app.tickets.helpers import find_admin_role_id, find_staff_role_id

def _grant(name, fallback):
    from app.config import optional

    raw = optional(name, "")
    try:
        return float(raw) if raw else fallback
    except ValueError:
        return fallback


# Days granted to a new employee, per leave type code. Changing these affects
# people created from now on; balances that already exist are left alone.
LEAVE_GRANTS = {
    "ANNUAL": _grant("LEAVE_GRANT_ANNUAL", 16),
    "SICK": _grant("LEAVE_GRANT_SICK", 8),
    "CASUAL": _grant("LEAVE_GRANT_CASUAL", 8),
}


def employee_id_for(discord_id):
    suffix = re.sub(r"\D", "", str(discord_id))[-4:] or "0000"
    return f"EMP-{suffix}"


def staff_kind_from_roles(role_ids, *, staff_role_id, admin_role_id, role_names=None):
    ids = {str(item) for item in (role_ids or [])}
    names = {str(item).strip().lower() for item in (role_names or [])}
    hod = hod_department_from_role_names(role_names)
    dept = hod or department_from_role_names(role_names)
    is_admin = bool(admin_role_id and str(admin_role_id) in ids) or bool(
        names.intersection({"admin", "administrator", "admins"})
    )
    is_hr = bool(names.intersection({"hr"}))
    member_like = any("member" in str(item).lower() for item in (role_names or []))
    if dept:
        return dept
    if is_admin or is_hr:
        return "HR"
    if staff_role_id and str(staff_role_id) in ids:
        return "Staff"
    if "staff" in names:
        return "Staff"
    if member_like:
        return "Staff"
    return None


def kind_for_guild_member(member, config):
    if member is None or getattr(member, "bot", False):
        return None
    guild = getattr(member, "guild", None)
    roles = [{"id": str(role.id), "name": role.name} for role in getattr(guild, "roles", []) or []]
    tickets = (config.get("discord") or {}).get("tickets") or {}
    staff_id = find_staff_role_id(roles, tickets.get("staffRoleId"))
    admin_id = find_admin_role_id(roles, tickets.get("adminRoleId"))
    member_roles = list(getattr(member, "roles", []) or [])
    return staff_kind_from_roles(
        [getattr(role, "id", role) for role in member_roles],
        staff_role_id=staff_id,
        admin_role_id=admin_id,
        role_names=[getattr(role, "name", "") for role in member_roles],
    )


def hod_for_guild_member(member, config):
    from app.hr.departments import is_hod_member

    return is_hod_member(member, config)


def member_sync_key(member, config):
    return (
        kind_for_guild_member(member, config),
        hod_for_guild_member(member, config),
        hr_role_for_guild_member(member, config),
    )


def hr_role_for_guild_member(member, config):
    from app.hr.departments import hod_department_from_role_names, is_department_member_role
    from app.hr.permissions import is_hr_admin, is_hr_member

    names = [getattr(role, "name", "") for role in getattr(member, "roles", []) or []]
    if hod_department_from_role_names(names):
        return "HOD"
    if any(is_department_member_role(name) for name in names):
        return "Member"
    hr_cfg = (config or {}).get("hr") or {}
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    admin_id = hr_cfg.get("adminRoleId") or tickets.get("adminRoleId")
    hr_id = hr_cfg.get("hrRoleId")
    named = {str(name).strip().lower() for name in names}
    if "hr" in named:
        return "HR"
    if named.intersection({"admin", "admins", "administrator"}):
        return "Admin"
    if is_hr_admin(member, admin_id):
        return "Admin"
    if is_hr_member(member, hr_id):
        return "HR"
    return ""


def discord_role_list(role_names):
    names = []
    for item in role_names or []:
        text = str(item or "").strip()
        if text and text != "@everyone" and text not in names:
            names.append(text)
    return "\n".join(names)


def upsert_staff_employee(
    client, *, discord_id, name, username="", joined_at=None, kind="Staff", hod=False, hr_role="", role_names=None,
    cnic="", dob="", contact_number="", address="", email="", designation="", photo_path="",
    grant_leave=True, logger=None,
):
    discord_id = str(discord_id or "").strip()
    if not discord_id or client is None:
        return None
    year = datetime.now(timezone.utc).year
    dept = normalize_department(kind) or kind or "Staff"
    if hr_role == "Admin":
        title = "Admin"
        if dept in {"Staff", ""}:
            dept = "HR"
    elif hr_role == "HR" or kind == "HR":
        title = "HR"
        if dept in {"Staff", ""}:
            dept = "HR"
    elif hod or hr_role == "HOD":
        title = "HOD"
        dept = normalize_department(kind) or dept
    else:
        title = "Member"
    formula = f"{{Discord User ID}}='{_escape(discord_id)}'"
    existing = client.table("employees").all(formula=formula)
    fields = {
        "Employee ID": employee_id_for(discord_id),
        "Discord User ID": discord_id,
        "Department": dept,
        "Status": "Active",
        "Discord Username": username or "",
        "HR Role": title,
    }
    # Formal Employee Name comes from the onboarding form. Role-driven syncs
    # (join / role change) must not overwrite it with the Discord display
    # name, or /profile by form name stops working. Only set the name when
    # creating a brand-new row or when this call is actual onboarding.
    display_name = name or username or "Staff"
    if (not existing) or grant_leave:
        fields["Employee Name"] = display_name
    roles_text = discord_role_list(role_names)
    fields["Discord Roles"] = roles_text
    if joined_at:
        fields["Join Date"] = str(joined_at)[:10]
    # Onboarding-form-only fields. Left out when empty so the Discord-role
    # driven auto-sync (on_member_update etc.) never clobbers profile data
    # that only the onboarding form collects.
    if str(cnic or "").strip():
        fields["CNIC"] = str(cnic).strip()
    if str(dob or "").strip():
        fields["DOB"] = str(dob).strip()[:10]
    if str(contact_number or "").strip():
        fields["Contact Number"] = str(contact_number).strip()
    if str(address or "").strip():
        fields["Address"] = str(address).strip()
    if str(email or "").strip():
        fields["Email"] = str(email).strip()
    if str(designation or "").strip():
        fields["Designation"] = str(designation).strip()
    if str(photo_path or "").strip():
        fields["Photo Path"] = str(photo_path).strip()

    def write(payload):
        if existing:
            return client.table("employees").update(existing[0]["id"], payload), False
        return client.table("employees").create(payload), True

    try:
        record, created = write(fields)
    except Exception as error:
        if is_unknown_field_name(error):
            fallback = dict(fields)
            fallback.pop("Discord Roles", None)
            fallback.pop("Designation", None)
            fallback.pop("Photo Path", None)
            if fallback == fields:
                raise
            record, created = write(fallback)
        else:
            raise
    # Leave quota is granted only when onboarding actually happened
    # (grant_leave=True). Role-driven syncs (join, role change, role-only
    # backfill) must never hand out a quota to someone who has not filled in
    # the onboarding form. CS Member / Sales Member never get leave quota.
    from app.hr.leave_access import leave_disabled_for_employee

    employee_view = {
        "department": dept,
        "hrRole": title,
        "discordRoles": roles_text,
    }
    if grant_leave and not leave_disabled_for_employee(employee_view, role_names):
        _ensure_default_balances(client, record, year=year, logger=logger)
    if logger:
        logged_name = fields.get("Employee Name") or (
            (existing[0].get("fields") or {}).get("Employee Name") if existing else display_name
        )
        logger.info("Staff sync", {
            "discordUserId": discord_id,
            "name": logged_name,
            "kind": kind,
            "created": created,
            "grantLeave": grant_leave,
        })
    return record


def _ensure_default_balances(client, employee_record, *, year, logger=None):
    types = {item["code"]: item for item in get_active_leave_types(client, logger=logger) if item.get("code")}
    balances = client.table("leaveBalances").all(formula=f"{{Year}}={year}")
    have = set()
    emp_id = employee_record["id"]
    for item in balances or []:
        fields = item.get("fields") or {}
        emp = fields.get("Employee") or []
        leave = fields.get("Leave Type") or []
        emp_ref = emp[0] if isinstance(emp, list) and emp else emp
        leave_ref = leave[0] if isinstance(leave, list) and leave else leave
        if str(emp_ref) == str(emp_id) and leave_ref:
            have.add(str(leave_ref))
    name = (employee_record.get("fields") or {}).get("Employee Name") or "Employee"
    for code, entitlement in LEAVE_GRANTS.items():
        leave = types.get(code)
        if not leave or str(leave["id"]) in have:
            continue
        client.table("leaveBalances").create({
            "Name": f"{name} {leave['name']} {year}",
            "Employee": [emp_id],
            "Leave Type": [leave["id"]],
            "Year": year,
            "Total Entitlement": entitlement,
            "Used": 0,
        })

from app.records.fields import db_call, as_text, escape_formula_value, field
from app.errors import AppError, ErrorCodes


INACTIVE_STATUSES = {"inactive", "terminated", "left", "disabled", "archived"}

# Kept as an alias: staff_onboard builds its own formula with this name.
_escape = escape_formula_value


def record_to_employee(record):
    if not record:
        return None
    status = as_text(field(record, "Status", "status")).strip()
    return {
        "id": record.get("id"),
        "name": as_text(field(record, "Employee Name", "Name", "name")),
        "employeeId": as_text(field(record, "Employee ID", "employeeId")),
        "discordUserId": as_text(field(record, "Discord User ID", "discordUserId")),
        "email": as_text(field(record, "Email", "email")),
        "department": as_text(field(record, "Department", "department")),
        "joinDate": as_text(field(record, "Join Date", "joinDate")),
        "status": status,
        "discordUsername": as_text(field(record, "Discord Username", "discordUsername")),
        "hrRole": as_text(field(record, "HR Role", "hrRole")),
        "discordRoles": as_text(field(record, "Discord Roles", "discordRoles")),
        # Linked record id(s) of this person's line manager, if one is set.
        "manager": field(record, "Manager", "manager"),
        "managerDiscordId": as_text(field(record, "Manager Discord ID", "managerDiscordId")),
        "cnic": as_text(field(record, "CNIC", "cnic")),
        "dob": as_text(field(record, "DOB", "dob"))[:10],
        "contactNumber": as_text(field(record, "Contact Number", "contactNumber")),
        "address": as_text(field(record, "Address", "address")),
        "designation": as_text(field(record, "Designation", "designation")),
        "photoPath": as_text(field(record, "Photo Path", "photoPath")),
        "active": status.lower() not in INACTIVE_STATUSES,
    }


def completed_onboarding(employee):
    """True only for a row written by the onboarding form.

    Role-driven syncs (join, role change, startup backfill) create bare rows
    without CNIC/DOB; only the form sets them.
    """
    if not employee or not employee.get("active"):
        return False
    return bool(str(employee.get("cnic") or "").strip() or str(employee.get("dob") or "").strip())


def lookup_employee_by_discord_id(client, discord_user_id, *, logger=None):
    """Employee row for this Discord id, or None. Does not raise if missing."""
    discord_id = str(discord_user_id or "").strip()
    if not discord_id or client is None:
        return None
    formula = f"{{Discord User ID}}='{escape_formula_value(discord_id)}'"
    records = db_call(
        lambda: client.table("employees").all(formula=formula),
        op="employee_lookup",
        logger=logger,
    )
    employees = [record_to_employee(item) for item in records or []]
    employees = [item for item in employees if item and item.get("discordUserId") == discord_id]
    return employees[0] if employees else None


def get_employee_by_discord_id(client, discord_user_id, *, logger=None):
    discord_id = str(discord_user_id or "").strip()
    if not discord_id:
        raise AppError(ErrorCodes.EMPLOYEE_NOT_FOUND, "Your Discord account is not linked to an employee record. Please contact HR.", expose=True)
    formula = f"{{Discord User ID}}='{escape_formula_value(discord_id)}'"
    records = db_call(
        lambda: client.table("employees").all(formula=formula),
        op="employee_lookup",
        logger=logger,
    )
    employees = [record_to_employee(item) for item in records or []]
    employees = [item for item in employees if item and item.get("discordUserId") == discord_id]
    if logger:
        logger.info("employee lookup", {"found": len(employees)})
    if not employees:
        raise AppError(ErrorCodes.EMPLOYEE_NOT_FOUND, "Your Discord account is not linked to an employee record. Please contact HR.", expose=True)
    if len(employees) > 1:
        raise AppError(ErrorCodes.EMPLOYEE_DUPLICATE, "Your Discord account is linked to more than one employee record. Please contact HR.", expose=True)
    employee = employees[0]
    if not employee.get("active"):
        raise AppError(ErrorCodes.EMPLOYEE_INACTIVE, "Your employee record is not active. Please contact HR.", expose=True)
    return employee


def get_employee_by_record_id(client, record_id, *, logger=None):
    """Look up an employee by Airtable record id. Returns None if unknown."""
    wanted = str(record_id or "").strip()
    if not wanted:
        return None
    records = db_call(
        lambda: client.table("employees").all(),
        op="employee_by_record",
        logger=logger,
    )
    for item in records or []:
        if str(item.get("id")) == wanted:
            return record_to_employee(item)
    return None


def _linked_ids(value):
    if isinstance(value, list):
        return [str(item) for item in value if item]
    text = str(value or "").strip()
    return [text] if text else []


def manager_of(client, employee, *, logger=None):
    """The employee's line manager, from the Manager link or a Discord ID."""
    if not employee:
        return None
    for record_id in _linked_ids(employee.get("manager")):
        if record_id.startswith("rec"):
            found = get_employee_by_record_id(client, record_id, logger=logger)
            if found:
                return found
    discord_id = str(employee.get("managerDiscordId") or "").strip()
    if discord_id:
        try:
            return get_employee_by_discord_id(client, discord_id, logger=logger)
        except AppError:
            return None
    return None


def reports_of(client, employee, *, logger=None):
    """Everyone who lists this person as their manager."""
    if not employee or not employee.get("id"):
        return []
    records = db_call(
        lambda: client.table("employees").all(),
        op="employee_reports",
        logger=logger,
    )
    mine = []
    for item in records or []:
        parsed = record_to_employee(item)
        if not parsed or parsed.get("id") == employee.get("id"):
            continue
        links = _linked_ids(parsed.get("manager"))
        if str(employee["id"]) in links:
            mine.append(parsed)
            continue
        if parsed.get("managerDiscordId") and employee.get("discordUserId"):
            if str(parsed["managerDiscordId"]) == str(employee["discordUserId"]):
                mine.append(parsed)
    return mine


def list_employee_discord_ids(client, *, logger=None):
    """Every Discord id already mapped to an employee, in one read.

    Used by the startup backfill so it can skip people who are already in
    Airtable instead of issuing a lookup per member.
    """
    records = db_call(
        lambda: client.table("employees").all(),
        op="employee_discord_ids",
        logger=logger,
    )
    ids = set()
    for item in records or []:
        discord_id = as_text(field(item, "Discord User ID", "discordUserId")).strip()
        if discord_id:
            ids.add(discord_id)
    return ids


def list_employees(client, *, logger=None):
    records = db_call(
        lambda: client.table("employees").all(),
        op="employee_list",
        logger=logger,
    )
    people = [record_to_employee(item) for item in records or []]
    return [item for item in people if item]


def list_birthdays_today(client, *, today=None, logger=None):
    """Active employees whose DOB (month + day) matches today. No SQL DATE
    function support in the formula translator, so this filters in Python —
    the same approach already used for holidays/attendance lookups."""
    from datetime import date as _date

    if client is None:
        return []
    target = today or _date.today()
    records = db_call(
        lambda: client.table("employees").all(),
        op="employee_birthdays",
        logger=logger,
    )
    people = [record_to_employee(item) for item in records or []]
    matches = []
    for person in people:
        if not person or not person.get("active"):
            continue
        raw = str(person.get("dob") or "")[:10]
        try:
            year, month, day = [int(part) for part in raw.split("-")]
        except (TypeError, ValueError):
            continue
        if month == target.month and day == target.day:
            matches.append(person)
    if logger:
        logger.info("birthday lookup", {"date": target.isoformat(), "count": len(matches)})
    return matches


def find_employees_by_name(client, query, *, logger=None):
    """Active-or-not employees whose name (or Discord username) contains the query."""
    text = str(query or "").strip().lower()
    if not text or client is None:
        return []
    people = list_employees(client, logger=logger)
    matches = []
    for item in people:
        name = str(item.get("name") or "").lower()
        username = str(item.get("discordUsername") or "").lower()
        if text in name or text in username:
            matches.append(item)
            continue
        # Multi-word queries: every word must appear in the name (order-free),
        # so "Muhammad Bilal" still matches "Bilal Muhammad" and partial typos
        # don't wipe the whole search when one token matches.
        words = [part for part in text.split() if part]
        if len(words) > 1 and all(part in name for part in words):
            matches.append(item)
    return matches


def update_employee_profile(client, employee_id, *, fields, logger=None):
    """Patch onboarding/contact fields on an existing employee row.

    `fields` keys are Airtable-style names: Employee Name, Email, Contact Number,
    CNIC, DOB, Address. Empty strings are written as-is so HR can clear a value.
    Returns the updated employee dict, or None if the row is missing.
    """
    record_id = str(employee_id or "").strip()
    if not record_id or client is None:
        return None
    payload = {}
    allowed = {
        "Employee Name",
        "Email",
        "Contact Number",
        "CNIC",
        "DOB",
        "Address",
        "Designation",
        "Photo Path",
    }
    for key, value in (fields or {}).items():
        if key not in allowed:
            continue
        text = str(value if value is not None else "").strip()
        if key == "DOB" and text:
            text = text[:10]
        payload[key] = text
    if not payload:
        rows = db_call(
            lambda: client.table("employees").all(),
            op="employee_list",
            logger=logger,
        )
        for item in rows or []:
            if str(item.get("id") or "") == record_id:
                return record_to_employee(item)
        return None
    updated = db_call(
        lambda: client.table("employees").update(record_id, payload),
        op="employee_profile_update",
        logger=logger,
    )
    if logger:
        logger.info("Employee profile updated", {
            "employeeId": record_id,
            "fields": sorted(payload.keys()),
        })
    return record_to_employee(updated)


def _row_links_employee(raw, employee):
    """True if a linked Employee field points at this employee row."""
    targets = {employee.get("id"), employee.get("name"), employee.get("employeeId")}
    targets = {str(item) for item in targets if item}
    if not targets:
        return False
    if isinstance(raw, list):
        return bool(targets.intersection(str(item) for item in raw if item is not None))
    return str(raw or "") in targets


def wipe_employee_leave_rows(client, employee, *, logger=None):
    """Delete leave utilization, requests, and balances for one employee. Keeps the employee row."""
    if client is None or not employee or not employee.get("id"):
        return None
    discord_id = str(employee.get("discordUserId") or "").strip()
    deleted = {
        "employeeId": str(employee["id"]),
        "discordUserId": discord_id,
        "name": employee.get("name") or "",
        "leaveUtilization": 0,
        "leaveRequests": 0,
        "leaveBalances": 0,
    }

    def _wipe(table_key, op, counter_key, match_fn):
        rows = db_call(
            lambda: client.table(table_key).all(),
            op=op,
            logger=logger,
        )
        for item in rows or []:
            if not match_fn(item):
                continue
            db_call(
                lambda rid=item["id"]: client.table(table_key).delete(rid),
                op=f"{op}_delete",
                logger=logger,
            )
            deleted[counter_key] += 1

    _wipe(
        "leaveUtilization",
        "employee_wipe_utilization",
        "leaveUtilization",
        lambda item: _row_links_employee(field(item, "Employee", "employee"), employee),
    )
    _wipe(
        "leaveRequests",
        "employee_wipe_requests",
        "leaveRequests",
        lambda item: (
            _row_links_employee(field(item, "Employee", "employee"), employee)
            or (discord_id and as_text(field(item, "Discord User ID", "discordUserId")).strip() == discord_id)
        ),
    )
    _wipe(
        "leaveBalances",
        "employee_wipe_balances",
        "leaveBalances",
        lambda item: _row_links_employee(field(item, "Employee", "employee"), employee),
    )
    if logger:
        logger.info("Employee leave rows wiped", deleted)
    return deleted


def delete_employee_profile(client, employee, *, logger=None):
    """Hard-delete an employee and all leave rows tied to them.

    Removes leave utilization, leave requests, and leave balances that link
    to this employee (by record id / name / employee id), then deletes the
    employee row. Returns a count summary. Does not touch Discord.
    """
    if client is None or not employee or not employee.get("id"):
        return None
    record_id = str(employee["id"])
    deleted = wipe_employee_leave_rows(client, employee, logger=logger) or {
        "employeeId": record_id,
        "discordUserId": str(employee.get("discordUserId") or "").strip(),
        "name": employee.get("name") or "",
        "leaveUtilization": 0,
        "leaveRequests": 0,
        "leaveBalances": 0,
    }
    deleted["employees"] = 0

    db_call(
        lambda: client.table("employees").delete(record_id),
        op="employee_delete",
        logger=logger,
    )
    deleted["employees"] = 1
    if logger:
        logger.info("Employee profile deleted", deleted)
    return deleted
from datetime import datetime, timezone

from app.records.fields import db_call, as_number, as_text, field
from app.records.leave_types import get_active_leave_types, resolve_leave_type_label
from app.errors import AppError, ErrorCodes


def current_year():
    return datetime.now(timezone.utc).year


def record_to_balance(record):
    if not record:
        return None
    used = as_number(field(record, "Used", "used"), 0)
    entitlement = as_number(field(record, "Total Entitlement", "Total", "entitlement"), 0)
    remaining = entitlement - used
    return {
        "id": record.get("id"),
        "employee": field(record, "Employee", "employee"),
        "leaveType": as_text(field(record, "Leave Type", "leaveType")),
        "leaveTypeId": as_text(field(record, "Leave Type", "leaveType")),
        "year": int(as_number(field(record, "Year", "year"), current_year())),
        "totalEntitlement": entitlement,
        "used": used,
        "remaining": remaining,
    }


def _matches_employee(balance, employee):
    raw = balance.get("employee")
    targets = {employee.get("id"), employee.get("name"), employee.get("employeeId")}
    targets = {str(item) for item in targets if item}
    if isinstance(raw, list):
        values = [str(item) for item in raw]
        return bool(targets.intersection(values))
    return str(raw) in targets


def get_employee_leave_balances(client, employee, *, year=None, logger=None):
    year = int(year or current_year())
    records = db_call(
        lambda: client.table("leaveBalances").all(formula=f"{{Year}}={year}"),
        op="leave_balance_lookup",
        logger=logger,
    )
    balances = [record_to_balance(item) for item in records or []]
    matched = [item for item in balances if item and _matches_employee(item, employee)]
    try:
        types = get_active_leave_types(client, logger=logger)
    except Exception:
        types = []
    for item in matched:
        label = resolve_leave_type_label(item.get("leaveType"), types)
        if label:
            item["leaveType"] = label
    if logger:
        logger.info("leave balance lookup", {"count": len(matched), "year": year})
    return matched


def get_leave_balance(client, employee, leave_type, *, year=None, logger=None):
    wanted = str(leave_type or "").strip().lower().replace("anual", "annual")
    short = wanted.replace(" leave", "").replace("leaves", "").strip()
    for item in get_employee_leave_balances(client, employee, year=year, logger=logger):
        name = str(item.get("leaveType") or "").lower()
        type_id = str(item.get("leaveTypeId") or "").lower()
        if wanted in {name, type_id} or short in {name.replace(" leave", ""), type_id}:
            return item
        if short and (short in name or wanted in name or wanted == type_id or short == type_id):
            return item
    raise AppError(
        ErrorCodes.LEAVE_BALANCE_MISSING,
        "That leave type is not set up on your balance yet. Please contact HR.",
        expose=True,
    )


def update_used_leave(client, balance, extra_days, *, logger=None):
    extra = as_number(extra_days, 0)
    new_used = as_number(balance.get("used"), 0) + extra
    updated = db_call(
        lambda: client.table("leaveBalances").update(balance["id"], {"Used": new_used}),
        op="update_used_leave",
        logger=logger,
    )
    return record_to_balance(updated)

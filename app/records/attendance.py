from collections import Counter
from datetime import datetime

from app.records.fields import db_call, as_text, field


def record_to_attendance(record):
    if not record:
        return None
    return {
        "id": record.get("id"),
        "employee": field(record, "Employee", "employee"),
        "date": as_text(field(record, "Date", "date")),
        "checkIn": as_text(field(record, "Check In", "checkIn")),
        "checkOut": as_text(field(record, "Check Out", "checkOut")),
        "status": as_text(field(record, "Status", "status")),
        "notes": as_text(field(record, "Notes", "notes")),
    }


def _parse_date(value):
    text = str(value or "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _matches_employee(row, employee):
    raw = row.get("employee")
    targets = {employee.get("id"), employee.get("name"), employee.get("employeeId")}
    targets = {str(item) for item in targets if item}
    if isinstance(raw, list):
        return bool(targets.intersection(str(item) for item in raw))
    return str(raw) in targets


def get_attendance_for_date_range(client, employee, start_date, end_date, *, logger=None):
    # Attendance table is optional (dropped from MySQL). Empty = no punch records.
    try:
        records = db_call(
            lambda: client.table("attendance").all(),
            op="attendance_lookup",
            logger=logger,
        )
    except Exception:
        if logger:
            logger.debug("No Attendance table; returning empty attendance")
        return []
    rows = [record_to_attendance(item) for item in records or []]
    matched = []
    for row in rows:
        if not row or not _matches_employee(row, employee):
            continue
        day = _parse_date(row.get("date"))
        if not day:
            continue
        if start_date <= day <= end_date:
            matched.append(row)
    matched.sort(key=lambda item: item.get("date") or "")
    if logger:
        logger.info("attendance lookup", {"count": len(matched)})
    return matched


def get_month_attendance_summary(client, employee, year, month, *, logger=None):
    from datetime import date
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1)
        from datetime import timedelta
        end = end - timedelta(days=1)
    rows = get_attendance_for_date_range(client, employee, start, end, logger=logger)
    counts = Counter((row.get("status") or "Unknown").strip() or "Unknown" for row in rows)
    return {"rows": rows, "summary": dict(counts), "start": start.isoformat(), "end": end.isoformat()}

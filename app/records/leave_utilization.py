from datetime import date

from app.records.fields import db_call, as_text, field

# Nothing here imports app.hr at module level on purpose. This is the lower
# layer, and app.hr imports it: a module-level import back up creates a cycle
# that only shows itself when this module happens to be imported first. The
# one helper needed from above is imported inside the function that uses it.


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _parse_day(value):
    raw = str(value or "")[:10]
    return date.fromisoformat(raw)


def list_utilization(client, *, logger=None):
    try:
        records = client.table("leaveUtilization").all()
    except Exception as error:
        if logger:
            logger.warn("Leave Utilization table is not available", {"message": str(error)})
        return []
    rows = []
    for record in records or []:
        day = as_text(field(record, "Date", "date"))[:10]
        rows.append({
            "id": record.get("id"),
            "employee": field(record, "Employee", "employee"),
            "leaveType": field(record, "Leave Type", "leaveType"),
            "leaveRequest": field(record, "Leave Request", "leaveRequest"),
            "date": day,
            "dayOfWeek": as_text(field(record, "Day of Week", "dayOfWeek")) or (
                WEEKDAYS[_parse_day(day).weekday()] if day else ""
            ),
            "status": as_text(field(record, "Status", "status")).upper(),
        })
    return rows


def _same_link(raw, record_id):
    if isinstance(raw, list):
        return str(record_id) in {str(item) for item in raw}
    return str(raw) == str(record_id)


def record_utilized_days(client, *, employee, leave_type, request, logger=None, holidays=None):
    try:
        table = client.table("leaveUtilization")
    except Exception:
        return []
    start = _parse_day(request.get("startDate"))
    end = _parse_day(request.get("endDate"))
    existing = list_utilization(client, logger=logger)
    created = []
    name = employee.get("name") or "Employee"
    type_name = leave_type.get("name") or "Leave"
    from app.hr.workdays import working_days

    # Weekends and company holidays are not leave, so they get no row.
    for day in working_days(start, end, holidays=holidays):
        already = any(
            item.get("date") == day.isoformat()
            and item.get("status") != "CANCELLED"
            and _same_link(item.get("employee"), employee.get("id"))
            and (
                _same_link(item.get("leaveType"), leave_type.get("id"))
                or str(item.get("leaveType") or "") == type_name
            )
            for item in existing
        )
        if already:
            continue
        weekday = WEEKDAYS[day.weekday()]
        fields = {
            "Record Name": f"{name} | {type_name} | {day.isoformat()} | {weekday}",
            "Date": day.isoformat(),
            # Written rather than left to be derived on read, so the column is
            # populated for anyone browsing the table in Airtable.
            "Day of Week": weekday,
            "Days": 1,
            "Status": "UTILISED",
            "Year": day.year,
            "Notes": f"Taken from {request.get('requestId') or 'leave request'}",
        }
        # Linked-record fields only accept arrays of record ids; a bare name is
        # rejected, so the link is left off rather than sent in a shape that
        # would fail the whole write.
        if employee.get("id"):
            fields["Employee"] = [employee["id"]]
        if leave_type.get("id"):
            fields["Leave Type"] = [leave_type["id"]]
        if request.get("id"):
            fields["Leave Request"] = [request["id"]]
        try:
            saved = db_call(
                lambda: table.create(fields),
                op="leave_utilization_created",
                logger=logger,
            )
        except Exception as error:
            # This table is an optional audit trail, and by the time it is
            # written the balance has already moved and the request is already
            # approved. Raising here would report a failure for a decision that
            # actually succeeded, and would leave the reviewer unsure whether to
            # approve again. It is logged and skipped instead.
            if logger:
                logger.warn("Could not record a utilised leave day", {
                    "requestId": request.get("requestId"),
                    "date": day.isoformat(),
                    "message": str(error)[:200],
                })
            return created
        created.append(saved)
        existing.append({
            "employee": fields["Employee"],
            "leaveType": fields["Leave Type"],
            "date": day.isoformat(),
            "status": "UTILISED",
        })
    if logger and created:
        logger.info("leave utilization recorded", {
            "requestId": request.get("requestId"),
            "days": len(created),
        })
    return created


def release_utilized_days(client, *, request, logger=None):
    """Mark this request's utilised days cancelled so the calendar clears.

    Rows are updated rather than deleted so the audit trail stays intact.
    """
    request_id = str(request.get("id") or "")
    released = []
    try:
        table = client.table("leaveUtilization")
    except Exception:
        return released
    for row in list_utilization(client, logger=logger):
        if row.get("status") == "CANCELLED":
            continue
        if not _same_link(row.get("leaveRequest"), request_id):
            continue
        try:
            table.update(row["id"], {"Status": "CANCELLED"})
            released.append(row["id"])
        except Exception as error:
            if logger:
                logger.warn("Could not release a utilised leave day", {"message": str(error)})
    if logger and released:
        logger.info("leave utilization released", {
            "requestId": request.get("requestId"),
            "days": len(released),
        })
    return released

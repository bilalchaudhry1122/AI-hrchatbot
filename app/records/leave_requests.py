from datetime import datetime, timezone
from uuid import uuid4

from app.records.fields import (
    db_call,
    as_number,
    as_text,
    escape_formula_value,
    field,
    is_unknown_field_name,
    is_unknown_select_option,
    missing_field_name,
)
from app.errors import AppError, ErrorCodes

LEGACY_OPEN_STATUS = "PENDING"
TWO_STEP_OPEN_STATUSES = frozenset({"PENDING_HR", "PENDING_MANAGER"})


def _table_create(table, fields):
    try:
        return table.create(fields, typecast=True)
    except TypeError:
        return table.create(fields)


def _table_update(table, record_id, fields):
    try:
        return table.update(record_id, fields, typecast=True)
    except TypeError:
        return table.update(record_id, fields)


def make_request_id():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"LR-{stamp}-{uuid4().hex[:6].upper()}"


def merge_request(previous, updated):
    """Keep identity fields if Airtable's update response omitted them."""
    saved = record_to_request(updated) if updated and updated.get("id") else {}
    if not saved:
        saved = dict(previous or {})
    prior = previous or {}
    for key in (
        "discordUserId",
        "ticketChannelId",
        "leaveType",
        "startDate",
        "endDate",
        "daysRequested",
        "reason",
        "employeeName",
        "requestId",
        "managerApprovedBy",
        "managerApprovedAt",
        "department",
    ):
        if not saved.get(key) and prior.get(key) not in (None, ""):
            saved[key] = prior[key]
    return saved


def record_to_request(record):
    if not record:
        return None
    return {
        "id": record.get("id"),
        "requestId": as_text(field(record, "Request ID", "requestId")),
        "employee": field(record, "Employee", "employee"),
        "discordUserId": as_text(field(record, "Discord User ID", "discordUserId")),
        "ticketChannelId": as_text(field(record, "Ticket Channel ID", "ticketChannelId")),
        "leaveType": as_text(field(record, "Leave Type", "leaveType")),
        "startDate": as_text(field(record, "Start Date", "startDate"))[:10],
        "endDate": as_text(field(record, "End Date", "endDate"))[:10],
        "daysRequested": as_number(field(record, "Days Requested", "daysRequested"), 0),
        "reason": as_text(field(record, "Reason", "reason")),
        # HR/manager rejection notes live in their own field so the employee's
        # stated reason is never overwritten.
        "rejectionReason": as_text(field(record, "Rejection Reason", "rejectionReason")),
        "halfDay": as_text(field(record, "Half Day", "halfDay")),
        "status": as_text(field(record, "Status", "status")).upper(),
        "balanceBefore": as_number(field(record, "Balance Before", "balanceBefore"), 0),
        "balanceAfter": field(record, "Balance After", "balanceAfter"),
        "requestedAt": as_text(field(record, "Requested At", "requestedAt")),
        "approvedAt": as_text(field(record, "Approved At", "approvedAt")),
        "approvedBy": as_text(field(record, "Approved By", "approvedBy")),
        "rejectedAt": as_text(field(record, "Rejected At", "rejectedAt")),
        "rejectedBy": as_text(field(record, "Rejected By", "rejectedBy")),
        "managerApprovedAt": as_text(field(record, "Manager Approved At", "managerApprovedAt")),
        "managerApprovedBy": as_text(field(record, "Manager Approved By", "managerApprovedBy")),
        "cancelledAt": as_text(field(record, "Cancelled At", "cancelledAt")),
        "cancelledBy": as_text(field(record, "Cancelled By", "cancelledBy")),
    }


def create_leave_request(client, payload, *, logger=None):
    fields = {
        "Request ID": payload["requestId"],
        "Discord User ID": str(payload["discordUserId"]),
        "Ticket Channel ID": str(payload["ticketChannelId"]),
        "Start Date": payload["startDate"],
        "End Date": payload["endDate"],
        "Days Requested": payload["daysRequested"],
        "Reason": payload.get("reason") or "",
        "Status": payload.get("status") or "PENDING_HR",
        "Requested At": payload.get("requestedAt") or datetime.now(timezone.utc).isoformat(),
    }
    if payload.get("balanceBefore") is not None:
        fields["Balance Before"] = payload.get("balanceBefore")
    # A single select rejects an empty string: Airtable reads it as a request to
    # create a new blank option and refuses. Optional selects are omitted
    # instead, which leaves the cell empty as intended.
    half_day = str(payload.get("halfDay") or "").strip()
    if half_day:
        fields["Half Day"] = half_day
    # Linked-record fields only accept an array of record ids. Sending a bare
    # name is rejected outright, so the link is omitted and the row is still
    # matchable by Discord User ID.
    for key, value in (
        ("Employee", payload.get("employeeLink")),
        ("Leave Type", payload.get("leaveTypeLink")),
    ):
        if isinstance(value, list) and value:
            fields[key] = value
        elif logger:
            logger.warn("Leave request written without a link", {"field": key})
    created = _create_leave_request_row(client, fields, logger=logger)
    saved = record_to_request(created)
    if payload.get("leaveType"):
        from app.records.leave_types import looks_like_record_id

        if looks_like_record_id(saved.get("leaveType")):
            saved["leaveType"] = payload["leaveType"]
    if payload.get("employeeName"):
        saved["employeeName"] = payload["employeeName"]
    if payload.get("requestId"):
        saved["requestId"] = payload["requestId"]
    intended = str(payload.get("status") or "").upper()
    stored = str((saved or {}).get("status") or "").upper()
    if saved and intended in TWO_STEP_OPEN_STATUSES and stored != intended:
        saved = _restore_two_step_status(client, saved, intended, logger=logger)
    if payload.get("leaveType"):
        from app.records.leave_types import looks_like_record_id

        if looks_like_record_id((saved or {}).get("leaveType")):
            saved["leaveType"] = payload["leaveType"]
    if payload.get("employeeName") and saved:
        saved["employeeName"] = payload["employeeName"]
    if payload.get("requestId") and saved:
        saved["requestId"] = payload["requestId"]
    if logger:
        logger.info("leave request created", {"requestId": payload["requestId"]})
    return saved


def _restore_two_step_status(client, saved, intended, *, logger=None):
    """Airtable may store PENDING if the select has no two-step options yet."""
    record_id = saved.get("id")
    if record_id:
        try:
            patched = db_call(
                lambda: _table_update(client.table("leaveRequests"), record_id, {"Status": intended}),
                op="leave_request_status_restored",
                logger=logger,
            )
            restored = record_to_request(patched)
            if restored and str(restored.get("status") or "").upper() == intended:
                return restored
        except Exception as error:
            if logger:
                logger.warn(
                    "Leave request Status is still PENDING; add PENDING_MANAGER and PENDING_HR to Airtable",
                    {"message": str(error)},
                )
    saved["status"] = intended
    return saved


def _create_leave_request_row(client, fields, *, logger=None):
    """Write the row; older bases only know PENDING, and may lack Half Day."""
    try:
        return db_call(
            lambda: _table_create(client.table("leaveRequests"), fields),
            op="leave_request_created",
            logger=logger,
        )
    except Exception as error:
        if is_unknown_field_name(error) and "Half Day" in fields:
            fields = dict(fields)
            fields.pop("Half Day", None)
            if logger:
                logger.warn("Leave request written without Half Day; field is missing in Airtable")
            return _create_leave_request_row(client, fields, logger=logger)
        if is_unknown_select_option(error) and fields.get("Status") in TWO_STEP_OPEN_STATUSES:
            fields = dict(fields)
            fields["Status"] = LEGACY_OPEN_STATUS
            if logger:
                logger.warn("Leave request Status fell back to PENDING; add PENDING_HR to the Airtable select")
            return db_call(
                lambda: _table_create(client.table("leaveRequests"), fields),
                op="leave_request_created",
                logger=logger,
            )
        raise


def all_leave_requests(client, *, logger=None):
    """Every leave request. Used for the approval queue only."""
    records = db_call(
        lambda: client.table("leaveRequests").all(),
        op="leave_requests_all",
        logger=logger,
    )
    return [item for item in (record_to_request(row) for row in records or []) if item]


def get_requests_by_ticket_channel(client, ticket_channel_id, *, logger=None):
    """Every request raised in this ticket, newest first."""
    channel_id = escape_formula_value(str(ticket_channel_id or "").strip())
    formula = f"{{Ticket Channel ID}}='{channel_id}'"
    records = db_call(
        lambda: client.table("leaveRequests").all(formula=formula),
        op="leave_request_lookup",
        logger=logger,
    )
    requests = [item for item in (record_to_request(row) for row in records or []) if item]
    requests.sort(key=lambda item: item.get("requestedAt") or "", reverse=True)
    return requests


def get_open_request_by_ticket_channel(client, ticket_channel_id, *, logger=None):
    """The request still awaiting a decision in this ticket, or None.

    Status is filtered here rather than in the formula so that legacy PENDING
    rows and the two-step statuses are all picked up.
    """
    from app.hr.leave_status import is_open

    for item in get_requests_by_ticket_channel(client, ticket_channel_id, logger=logger):
        if is_open(item.get("status")):
            return item
    return None


def get_pending_request_by_ticket_channel(client, ticket_channel_id, *, logger=None):
    found = get_open_request_by_ticket_channel(client, ticket_channel_id, logger=logger)
    if not found:
        raise AppError(ErrorCodes.LEAVE_REQUEST_MISSING, "There is no pending leave request in this ticket.", expose=True)
    return found


def get_requests_for_discord_id(client, discord_user_id, *, logger=None):
    discord_id = str(discord_user_id or "").strip()
    # Ask Airtable for this person's rows instead of scanning the whole table.
    formula = f"{{Discord User ID}}='{escape_formula_value(discord_id)}'"
    records = db_call(
        lambda: client.table("leaveRequests").all(formula=formula),
        op="leave_requests_for_employee",
        logger=logger,
    )
    requests = [record_to_request(item) for item in records or []]
    matched = [item for item in requests if item and str(item.get("discordUserId") or "") == discord_id]
    matched.sort(key=lambda item: item.get("requestedAt") or "", reverse=True)
    return matched


def get_request_by_ticket_channel(client, ticket_channel_id, *, logger=None):
    channel_id = escape_formula_value(str(ticket_channel_id or "").strip())
    formula = f"{{Ticket Channel ID}}='{channel_id}'"
    records = db_call(
        lambda: client.table("leaveRequests").all(formula=formula),
        op="leave_request_by_ticket",
        logger=logger,
    )
    requests = [record_to_request(item) for item in records or []]
    requests = [item for item in requests if item]
    requests.sort(key=lambda item: item.get("requestedAt") or "", reverse=True)
    return requests[0] if requests else None


def approve_leave_request(client, request, *, approved_by, balance_after, logger=None):
    now = datetime.now(timezone.utc).isoformat()
    updated = db_call(
        lambda: client.table("leaveRequests").update(request["id"], {
            "Status": "APPROVED",
            "Approved At": now,
            "Approved By": approved_by,
            "Balance After": balance_after,
        }),
        op="leave_request_approved",
        logger=logger,
    )
    if logger:
        logger.info("leave approved", {"requestId": request.get("requestId")})
    return merge_request(request, updated)


def reject_leave_request(client, request, *, rejected_by, reason="", logger=None):
    now = datetime.now(timezone.utc).isoformat()
    fields = {
        "Status": "REJECTED",
        "Rejected At": now,
        "Rejected By": rejected_by,
    }
    if reason:
        # Its own field: the employee's stated reason must survive a rejection.
        fields["Rejection Reason"] = reason
    updated = update_known_request_fields(
        client, request["id"], fields, op="leave_request_rejected", logger=logger
    )
    if logger:
        logger.info("leave rejected", {"requestId": request.get("requestId")})
    return merge_request(request, updated)


def cancel_leave_request(client, request, *, cancelled_by, logger=None):
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "Status": "CANCELLED",
        "Cancelled At": now,
        "Cancelled By": cancelled_by,
    }
    try:
        updated = update_known_request_fields(
            client, request["id"], payload, op="leave_request_cancelled", logger=logger
        )
    except Exception:
        # Bases whose Status field has no CANCELLED option fall back to
        # REJECTED. Older bases also lack Rejection Reason, so that field
        # is omitted; Rejected By still records that it was withdrawn.
        payload = {
            "Status": "REJECTED",
            "Rejected At": now,
            "Rejected By": f"Withdrawn · {cancelled_by}",
        }
        updated = update_known_request_fields(
            client, request["id"], payload, op="leave_request_withdrawn", logger=logger
        )
    if logger:
        logger.info("leave withdrawn", {"requestId": request.get("requestId")})
    record = merge_request(request, updated)
    if record and record.get("status") == "REJECTED":
        record["status"] = "CANCELLED"
    return record


def update_known_request_fields(client, record_id, fields, *, op, logger=None):
    """Write fields, dropping any column this Airtable base does not have."""
    current = dict(fields)
    while current:
        payload = dict(current)
        try:
            return db_call(
                lambda body=payload: _table_update(client.table("leaveRequests"), record_id, body),
                op=op,
                logger=logger,
            )
        except Exception as error:
            name = missing_field_name(error)
            if not name or name not in current:
                raise
            if logger:
                logger.warn("Skipped missing Airtable field", {"op": op, "field": name})
            current.pop(name)
    raise AppError(ErrorCodes.DB_UNAVAILABLE, "Database is unavailable.")


def update_request_status(client, request, fields, *, logger=None, op="leave_request_update"):
    """Write raw field updates against a request row."""
    try:
        updated = update_known_request_fields(
            client, request["id"], fields, op=op, logger=logger
        )
    except Exception as error:
        if is_unknown_select_option(error) and fields.get("Status") in TWO_STEP_OPEN_STATUSES:
            fields = dict(fields)
            fields["Status"] = LEGACY_OPEN_STATUS
            updated = update_known_request_fields(
                client, request["id"], fields, op=op, logger=logger
            )
        else:
            raise
    return merge_request(request, updated)


def mark_manager_approved(client, request, *, approved_by, next_status, logger=None):
    """First step of two-step approval. No balance moves yet."""
    now = datetime.now(timezone.utc).isoformat()
    saved = update_request_status(
        client,
        request,
        {
            "Status": next_status,
            "Manager Approved At": now,
            "Manager Approved By": approved_by,
        },
        logger=logger,
        op="leave_manager_approved",
    )
    if logger:
        logger.info("leave manager approved", {"requestId": request.get("requestId")})
    saved["managerApprovedBy"] = saved.get("managerApprovedBy") or approved_by
    saved["managerApprovedAt"] = saved.get("managerApprovedAt") or now
    return saved

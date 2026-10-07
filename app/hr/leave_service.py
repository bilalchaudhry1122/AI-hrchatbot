from datetime import date, timezone, datetime

from app.records.employees import manager_of, reports_of
from app.records.holidays import get_holidays
from app.records.leave_balances import get_employee_leave_balances, get_leave_balance, update_used_leave
from app.records.leave_utilization import record_utilized_days, release_utilized_days
from app.records.leave_requests import (
    all_leave_requests,
    approve_leave_request,
    cancel_leave_request,
    create_leave_request,
    get_open_request_by_ticket_channel,
    get_pending_request_by_ticket_channel,
    get_request_by_ticket_channel,
    get_requests_for_discord_id,
    make_request_id,
    reject_leave_request,
    update_request_status,
)
from app.records.leave_types import get_active_leave_types, get_leave_type_by_name, resolve_leave_type_label
from app.errors import AppError, ErrorCodes
from app.hr.dates import format_display_date
from app.hr.departments import is_hod_title, normalize_department
from app.hr.employee_service import EmployeeService, require_db
from app.hr.leave_status import (
    ADMIN,
    APPROVED,
    CANCELLED,
    HR,
    MANAGER,
    PENDING_HR,
    REJECTED,
    can_act_on,
    display_status,
    is_open,
    next_status_after_approval,
    normalize,
    stage_for,
)
from app.hr.workdays import count_leave_days, describe_skipped, normalize_half_day, working_days
from app.routing.language import pick_locale_text


def is_unpaid(leave_type):
    name = str(leave_type.get("name") or "").lower()
    code = str(leave_type.get("code") or "").upper()
    return code == "UNPAID" or "unpaid" in name


def _qty(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number.is_integer():
        return int(number)
    return number


def _public_leave_label(raw, leave_types):
    label = resolve_leave_type_label(raw, leave_types) or _leave_label({"leaveType": raw}, leave_types)
    text = str(label or "").strip()
    if text.startswith("rec") and " " not in text:
        return "Leave"
    return text or "Leave"


def _leave_span(item):
    start = format_display_date(item.get("startDate"))
    end = format_display_date(item.get("endDate")) or start
    if start and end and start != end:
        return f"{start} – {end}"
    return start or end or ""


def _as_day(value):
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def ranges_overlap(start, end, other_start, other_end):
    return start <= other_end and other_start <= end


def _leave_label(item, leave_types):
    raw = str(item.get("leaveType") or "")
    for leave in leave_types:
        if raw.lower() in {leave.get("name", "").lower(), leave.get("code", "").lower(), str(leave.get("id") or "").lower()}:
            return leave.get("name") or raw
    return raw or "Leave"


class LeaveService:
    def __init__(self, client, logger, *, lock, config=None):
        self.client = client
        self.logger = logger
        self.lock = lock
        self.config = config or {}
        self.employees = EmployeeService(client, logger)

    # -- company calendar ---------------------------------------------------

    def holidays(self):
        return get_holidays(self.client, logger=self.logger)

    def count_days(self, start_date, end_date, half_day=""):
        """Working days this booking costs, weekends and holidays excluded."""
        return count_leave_days(
            start_date, end_date, half_day=half_day, holidays=self.holidays()
        )

    def no_working_days_error(self, start_date, end_date, locale=None):
        """All weekend or holiday: there is nothing to deduct."""
        skipped = describe_skipped(start_date, end_date, holidays=self.holidays())
        weekend_only = all(item["reason"] == "weekend" for item in skipped)
        if weekend_only:
            return AppError(
                ErrorCodes.LEAVE_NO_WORKING_DAYS,
                pick_locale_text(
                    locale,
                    english="Saturday and Sunday are already off, so you do not need leave for those dates. Pick a working day.",
                    roman="Saturday aur Sunday pehle se off hain, in dates ke liye leave ki zarurat nahi. Working day chunein.",
                    urdu="ہفتہ اور اتوار پہلے سے چھٹی ہیں، ان تاریخوں کے لیے لیو کی ضرورت نہیں۔ کوئی ورکنگ ڈے منتخب کریں۔",
                    mix="Saturday aur Sunday already off hain. Pick a working day.",
                ),
                expose=True,
            )
        return AppError(
            ErrorCodes.LEAVE_NO_WORKING_DAYS,
            pick_locale_text(
                locale,
                english="Those dates are all company holidays or weekends, so no leave is needed. Pick a working day.",
                roman="Yeh sab company holidays ya weekend hain, leave ki zarurat nahi. Working day chunein.",
                urdu="یہ سب چھٹیاں یا ویک اینڈ ہیں، لیو کی ضرورت نہیں۔ کوئی ورکنگ ڈے منتخب کریں۔",
                mix="Yeh sab holidays ya weekend hain. Pick a working day.",
            ),
            expose=True,
        )

    # -- who approves -------------------------------------------------------

    def two_step_enabled(self):
        hr_cfg = (self.config or {}).get("hr") or {}
        return bool(hr_cfg.get("twoStepApproval", True))

    def manager_for(self, employee):
        if self.client is None:
            return None
        try:
            return manager_of(self.client, employee, logger=self.logger)
        except AppError:
            return None

    def is_line_manager_of(self, manager_discord_id, employee_discord_id):
        """Does this Discord user manage that employee?"""
        if not manager_discord_id or not employee_discord_id:
            return False
        if str(manager_discord_id) == str(employee_discord_id):
            return False
        try:
            employee = self.employees.get_me(employee_discord_id)
        except AppError:
            return False
        manager = self.manager_for(employee)
        return bool(manager and str(manager.get("discordUserId") or "") == str(manager_discord_id))

    def reports_for(self, manager_discord_id):
        try:
            manager = self.employees.get_me(manager_discord_id)
        except AppError:
            return []
        return reports_of(self.client, manager, logger=self.logger)

    def get_my_leave_snapshot(self, discord_user_id, leave_type=None, locale=None, role_names=None):
        from app.hr.leave_access import leave_disabled_for_employee, leave_disabled_message

        client = require_db(self.client)
        employee = self.employees.get_me(discord_user_id)
        if leave_disabled_for_employee(employee, role_names):
            raise AppError(
                ErrorCodes.LEAVE_NOT_AVAILABLE,
                leave_disabled_message(locale),
                expose=True,
            )
        live_balances = get_employee_leave_balances(client, employee, logger=self.logger)
        if not live_balances:
            message = pick_locale_text(
                locale,
                english="Your leave balance is not set up yet. Please contact HR and they will sort it out.",
                roman="Aapka leave balance abhi set nahi hua. HR se rabta karein, woh set kar denge.",
                urdu="آپ کا لیو بیلنس ابھی سیٹ نہیں ہوا۔ براہ کرم HR سے رابطہ کریں۔",
                mix="Aapka leave balance abhi set nahi hua. Please contact HR.",
            )
            raise AppError(ErrorCodes.LEAVE_BALANCE_MISSING, message, expose=True)
        if leave_type:
            wanted = str(leave_type).lower()
            focused = [item for item in live_balances if wanted in str(item.get("leaveType") or "").lower()]
            rest = [item for item in live_balances if item not in focused]
            live_balances = focused + rest
        types = get_active_leave_types(client, logger=self.logger)
        requests = get_requests_for_discord_id(client, discord_user_id, logger=self.logger)
        pending = [item for item in requests if is_open(item.get("status"))]
        approved = [item for item in requests if normalize(item.get("status")) == APPROVED][:5]
        pending_by_type = {}
        for item in pending:
            label = _public_leave_label(item.get("leaveType"), types)
            pending_by_type[label] = pending_by_type.get(label, 0) + float(item.get("daysRequested") or 0)

        lines = [
            pick_locale_text(
                locale,
                english="Here is your live leave balance.",
                roman="Yeh raha aapka live leave balance.",
                urdu="یہ رہا آپ کا موجودہ لیو بیلنس۔",
                mix="Here is your live leave balance.",
            ),
            "",
            pick_locale_text(
                locale,
                english="Available now",
                roman="Ab available",
                urdu="اب دستیاب",
                mix="Available now",
            ),
        ]
        for item in live_balances:
            label = _public_leave_label(item.get("leaveType"), types)
            remaining = _qty(item["remaining"])
            used = _qty(item["used"])
            total = _qty(item["totalEntitlement"])
            lines.append(pick_locale_text(
                locale,
                english=f"• **{label}** — {remaining} of {total} available ({used} used)",
                roman=f"• **{label}** — {remaining} of {total} available ({used} used)",
                urdu=f"• **{label}** — {remaining} از {total} دستیاب ({used} استعمال)",
                mix=f"• **{label}** — {remaining} of {total} available ({used} used)",
            ))
            pending_days = pending_by_type.get(label) or 0
            if pending_days:
                after = _qty(float(item["remaining"]) - pending_days)
                lines.append(pick_locale_text(
                    locale,
                    english=f"    If pending is approved: **{after}** remaining",
                    roman=f"    Agar pending approve ho: **{after}** baqi",
                    urdu=f"    اگر التوا منظور ہو: **{after}** باقی",
                    mix=f"    If pending is approved: **{after}** remaining",
                ))
        lines.append("")
        if pending:
            lines.append(pick_locale_text(
                locale,
                english="Pending approval (not deducted yet)",
                roman="Pending approval (abhi deduct nahi hua)",
                urdu="زیر التوا منظوری (ابھی کٹوتی نہیں ہوئی)",
                mix="Pending approval (not deducted yet)",
            ))
            for item in pending:
                label = _public_leave_label(item.get("leaveType"), types)
                span = _leave_span(item)
                days = _qty(item.get("daysRequested"))
                # Say who it is sitting with, so nobody has to ask.
                where = display_status(item.get("status"), locale)
                lines.append(f"• **{label}** — {span} · {days} day(s) · {where}")
        else:
            lines.append(pick_locale_text(
                locale,
                english="Pending approval: none",
                roman="Pending approval: koi nahi",
                urdu="زیر التوا منظوری: کوئی نہیں",
                mix="Pending approval: none",
            ))
        if approved:
            lines.append("")
            lines.append(pick_locale_text(
                locale,
                english="Recently approved",
                roman="Recently approved",
                urdu="حال ہی میں منظور",
                mix="Recently approved",
            ))
            for item in approved:
                label = _public_leave_label(item.get("leaveType"), types)
                span = _leave_span(item)
                after = item.get("balanceAfter")
                extra = f" · remaining {_qty(after)}" if after not in (None, "") else ""
                lines.append(f"• **{label}** — {span} · {_qty(item.get('daysRequested'))} day(s) · Approved{extra}")
        text = "\n".join(lines)
        return {
            "employee": employee,
            "balances": live_balances,
            "pending": pending,
            "approved": approved,
            "text": text,
        }

    def get_my_leave_balance(self, discord_user_id, leave_type=None, locale=None, role_names=None):
        snapshot = self.get_my_leave_snapshot(
            discord_user_id, leave_type, locale=locale, role_names=role_names
        )
        live_balances = snapshot["balances"]
        balance = None
        if leave_type:
            wanted = str(leave_type).lower()
            for item in live_balances:
                if wanted in str(item.get("leaveType") or "").lower():
                    balance = item
                    break
        if not balance and live_balances:
            balance = live_balances[0]
        snapshot["balance"] = balance
        return snapshot

    def list_pending_for_member(self, discord_user_id):
        """Requests still awaiting any decision. Only one is allowed open."""
        client = require_db(self.client)
        requests = get_requests_for_discord_id(client, discord_user_id, logger=self.logger)
        return [item for item in requests if is_open(item.get("status"))]

    def get_pending_for_member(self, discord_user_id):
        pending = self.list_pending_for_member(discord_user_id)
        return pending[0] if pending else None

    def pending_already_open_error(self, discord_user_id, locale=None):
        pending = self.get_pending_for_member(discord_user_id)
        if not pending:
            return None
        span = _leave_span(pending)
        extra = f" ({span})" if span else ""
        message = pick_locale_text(
            locale,
            english=(
                f"You already have a leave request waiting for HR{extra}. "
                "Withdraw it from the pending card if you want to apply again."
            ),
            roman=(
                f"Aapki ek leave request pehle se HR ke paas pending hai{extra}. "
                "Naya apply se pehle pending card se Withdraw karein."
            ),
            urdu=(
                f"آپ کی ایک لیو درخواست پہلے سے HR کے پاس زیر التوا ہے{extra}۔ "
                "نئی درخواست سے پہلے کارڈ سے Withdraw دبائیں۔"
            ),
            mix=(
                f"Aapki ek leave request pehle se HR ke paas pending hai{extra}. "
                "Withdraw it from the pending card before applying again."
            ),
        )
        return AppError(ErrorCodes.LEAVE_REQUEST_OPEN, message, expose=True)

    def require_no_open_pending(self, discord_user_id, locale=None):
        error = self.pending_already_open_error(discord_user_id, locale)
        if error:
            raise error

    def pending_card_for_member(self, discord_user_id, locale=None, name=None):
        pending = self.get_pending_for_member(discord_user_id)
        if not pending:
            return None
        client = require_db(self.client)
        types = get_active_leave_types(client, logger=self.logger)
        display_name = name
        if not display_name:
            try:
                display_name = self.employees.get_me(discord_user_id).get("name")
            except AppError:
                display_name = pending.get("employeeName") or "Member"
        return {
            "locale": locale or "english",
            "leave_type": _public_leave_label(pending.get("leaveType"), types),
            "start_date": pending.get("startDate"),
            "end_date": pending.get("endDate"),
            "days": pending.get("daysRequested") or 1,
            "name": display_name,
            "remaining": pending.get("balanceBefore"),
            "reason": pending.get("reason") or "",
        }

    def withdraw_pending_for_member(self, discord_user_id, *, withdrawn_by, locale=None):
        client = require_db(self.client)
        with self.lock:
            pending_rows = self.list_pending_for_member(discord_user_id)
            if not pending_rows:
                message = pick_locale_text(
                    locale,
                    english="You do not have a leave request waiting for HR.",
                    roman="HR ke paas aapki koi pending leave request nahi hai.",
                    urdu="HR کے پاس آپ کی کوئی زیر التوا لیو درخواست نہیں ہے۔",
                    mix="HR ke paas aapki koi pending leave request nahi hai.",
                )
                raise AppError(ErrorCodes.LEAVE_REQUEST_MISSING, message, expose=True)
            saved = None
            for item in pending_rows:
                saved = cancel_leave_request(
                    client,
                    item,
                    cancelled_by=withdrawn_by,
                    logger=self.logger,
                )
        saved = saved or pending_rows[0]
        saved["employeeName"] = pending_rows[0].get("employeeName") or self._employee_name(discord_user_id)
        saved["withdrawnCount"] = len(pending_rows)
        return saved

    def approved_overlap_error(self, discord_user_id, start_date, end_date, locale=None):
        requests = get_requests_for_discord_id(
            require_db(self.client), discord_user_id, logger=self.logger
        )
        clashes = []
        for item in requests:
            if str(item.get("status") or "").upper() != "APPROVED":
                continue
            other_start = _as_day(item.get("startDate"))
            other_end = _as_day(item.get("endDate")) or other_start
            if not other_start or not other_end:
                continue
            if ranges_overlap(start_date, end_date, other_start, other_end):
                clashes.append(item)
        if not clashes:
            return None
        span = _leave_span(clashes[0])
        extra = f" ({span})" if span else ""
        message = pick_locale_text(
            locale,
            english=(
                f"Those dates overlap leave that is already approved{extra}. "
                "Change From and To on the form, then submit again."
            ),
            roman=(
                f"Yeh dates pehle se approved leave se overlap karti hain{extra}. "
                "Form par From/To badlein, phir submit karein."
            ),
            urdu=(
                f"یہ تاریخیں پہلے سے منظور شدہ لیو سے ٹکراتی ہیں{extra}۔ "
                "فارم پر From/To تبدیل کر کے دوبارہ جمع کریں۔"
            ),
            mix=(
                f"Yeh dates approved leave se overlap karti hain{extra}. "
                "Change From/To on the form, then submit again."
            ),
        )
        return AppError(ErrorCodes.LEAVE_DATES_APPROVED, message, expose=True)

    def create_pending_request(self, *, discord_user_id, ticket_channel_id, leave_type_name, start_date, end_date, reason="", locale=None, half_day="", role_names=None):
        from app.hr.leave_access import leave_disabled_for_employee, leave_disabled_message

        client = require_db(self.client)
        with self.lock:
            employee = self.employees.get_me(discord_user_id)
            if leave_disabled_for_employee(employee, role_names):
                raise AppError(
                    ErrorCodes.LEAVE_NOT_AVAILABLE,
                    leave_disabled_message(locale),
                    expose=True,
                )
            self.require_no_open_pending(discord_user_id, locale)
            leave_type = get_leave_type_by_name(client, leave_type_name, logger=self.logger)
            if end_date < start_date:
                raise AppError(ErrorCodes.INVALID_DATES, "The end date cannot be before the start date.", expose=True)
            clash = self.approved_overlap_error(discord_user_id, start_date, end_date, locale)
            if clash:
                raise clash
            half_day = normalize_half_day(half_day)
            if half_day and start_date != end_date:
                # A half day only makes sense on one day.
                half_day = ""
            days = self.count_days(start_date, end_date, half_day)
            if not days:
                raise self.no_working_days_error(start_date, end_date, locale)
            balance = None
            remaining = None
            if not is_unpaid(leave_type):
                balance = get_leave_balance(client, employee, leave_type["name"], logger=self.logger)
                remaining = balance["remaining"]
                if days > remaining:
                    raise AppError(
                        ErrorCodes.INSUFFICIENT_LEAVE,
                        f"You requested {days} day(s) of {leave_type['name']} but only {int(remaining) if float(remaining).is_integer() else remaining} remain. Contact HR or choose another option.",
                        expose=True,
                    )
            # Every request goes straight to HR. The department HOD gets a
            # simultaneous, view-only notification (see app.discord.leave_inbox)
            # but never a decision queue — only HR/Admin can approve/reject.
            from app.hr.departments import DEPARTMENTS, hod_queue_department, should_skip_hod_step

            names = [str(item or "").strip() for item in (role_names or []) if str(item or "").strip()]
            department = hod_queue_department(names, employee.get("department"))
            skip_hod = should_skip_hod_step(employee.get("hrRole"), names)
            needs_hod = False
            status = PENDING_HR
            payload = {
                "requestId": make_request_id(),
                "employeeLink": [employee["id"]] if employee.get("id") else employee.get("name"),
                "employeeName": employee.get("name"),
                "discordUserId": str(discord_user_id),
                "ticketChannelId": str(ticket_channel_id),
                "leaveTypeLink": [leave_type["id"]] if leave_type.get("id") else leave_type["name"],
                "leaveType": leave_type["name"],
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "daysRequested": days,
                "reason": reason,
                "halfDay": half_day,
                "status": status,
                "balanceBefore": remaining,
            }
            created = create_leave_request(client, payload, logger=self.logger)
        if self.logger:
            self.logger.info(
                "leave routing",
                {
                    "department": department,
                    "needsHod": needs_hod,
                    "status": created.get("status"),
                    "skipHod": skip_hod,
                    "roles": names,
                },
            )
        created["employeeName"] = employee.get("name")
        created["remaining"] = remaining
        created["daysRequested"] = days
        created["halfDay"] = half_day
        created["department"] = department
        created["needsHod"] = needs_hod
        created["skippedDays"] = describe_skipped(start_date, end_date, holidays=self.holidays())
        return created

    # -- decisions ----------------------------------------------------------

    def _already_decided_error(self, status):
        current = normalize(status)
        if current == APPROVED:
            return AppError(ErrorCodes.LEAVE_REQUEST_PROCESSED, "This leave request has already been approved.", expose=True)
        if current == REJECTED:
            return AppError(ErrorCodes.LEAVE_REQUEST_PROCESSED, "This leave request has already been rejected.", expose=True)
        if current == CANCELLED:
            return AppError(ErrorCodes.LEAVE_REQUEST_WITHDRAWN, "This leave request was withdrawn.", expose=True)
        return AppError(ErrorCodes.LEAVE_REQUEST_PROCESSED, f"This leave request has already been {current.lower()}.", expose=True)

    def _permission_error(self, request, tier):
        stage = stage_for(request.get("status")) if request else None
        if stage == MANAGER:
            return AppError(
                ErrorCodes.HR_PERMISSION,
                "Only the department HOD can approve or decline this leave request.",
                expose=True,
            )
        return AppError(
            ErrorCodes.HR_PERMISSION,
            "Only Admin or HR can approve or decline this leave request.",
            expose=True,
        )

    def is_hod_of_employee(self, actor_id, employee_discord_id):
        if not actor_id or not employee_discord_id:
            return False
        if str(actor_id) == str(employee_discord_id):
            return False
        try:
            actor = self.employees.get_me(actor_id)
            employee = self.employees.get_me(employee_discord_id)
        except AppError:
            return False
        dept = normalize_department(employee.get("department"))
        actor_dept = normalize_department(actor.get("department"))
        return bool(dept and actor_dept == dept and is_hod_title(actor.get("hrRole")))

    def _apply_approval(self, client, request, *, actor_label, tier):
        """Final approval: re-check the balance, deduct, record the days."""
        employee = self.employees.get_me(request["discordUserId"])
        leave_type = get_leave_type_by_name(client, request["leaveType"], logger=self.logger)
        days = request["daysRequested"]
        remaining_after = None
        if not is_unpaid(leave_type):
            balance = get_leave_balance(client, employee, leave_type["name"], logger=self.logger)
            if days > balance["remaining"]:
                raise AppError(
                    ErrorCodes.INSUFFICIENT_LEAVE,
                    f"Current {leave_type['name']} balance ({balance['remaining']}) is not enough for {days} day(s). Approval was not applied.",
                    expose=True,
                )
            updated = update_used_leave(client, balance, days, logger=self.logger)
            remaining_after = updated["remaining"]
        saved = approve_leave_request(
            client,
            request,
            approved_by=actor_label,
            balance_after=remaining_after,
            logger=self.logger,
        )
        record_utilized_days(
            client,
            employee=employee,
            leave_type=leave_type,
            request=saved,
            logger=self.logger,
            holidays=self.holidays(),
        )
        saved["remaining"] = remaining_after
        saved["employeeName"] = employee.get("name")
        saved["approvedBy"] = actor_label
        saved["decidedBy"] = tier
        saved["finalised"] = True
        saved["discordUserId"] = saved.get("discordUserId") or request.get("discordUserId")
        saved["department"] = normalize_department(employee.get("department")) or request.get("department") or ""
        if not saved.get("managerApprovedBy"):
            saved["managerApprovedBy"] = request.get("managerApprovedBy") or ""
        return saved

    def decide_request(self, request, *, actor_id, actor_name, tier, decision, reason="", is_line_manager=False, hod_first=False):
        """Approve or reject one request. HR/Admin only — HOD is notify-only.

        `hod_first` and `is_line_manager` remain on the signature so older
        call sites keep working, but neither can bypass the HR-only check:
        every request is created as PENDING_HR, so `can_act_on` already
        limits this to HR/Admin.
        """
        del hod_first
        client = require_db(self.client)
        with self.lock:
            fresh = self._reload(request)
            if not is_open(fresh.get("status")):
                raise self._already_decided_error(fresh.get("status"))
            if not can_act_on(fresh.get("status"), tier, is_line_manager=is_line_manager):
                raise self._permission_error(fresh, tier)
            actor_label = f"{actor_name} ({actor_id})"

            if decision == "reject":
                # A reason is optional: HR is never blocked from declining. When
                # one is given it goes in its own field so the employee's
                # stated reason survives.
                note = str(reason or "").strip()
                saved = reject_leave_request(
                    client, fresh, rejected_by=actor_label, reason=note, logger=self.logger
                )
                saved["employeeName"] = fresh.get("employeeName") or self._employee_name(fresh.get("discordUserId"))
                saved["rejectionReason"] = note
                saved["decidedBy"] = tier
                saved["finalised"] = True
                saved["discordUserId"] = saved.get("discordUserId") or fresh.get("discordUserId")
                return saved

            # Every open request is PENDING_HR, and can_act_on above already
            # required HR/Admin, so approval always finalises here.
            return self._apply_approval(client, fresh, actor_label=actor_label, tier=tier)

    def _reload(self, request):
        """Re-read the row so a decision never acts on a stale copy."""
        client = require_db(self.client)
        for item in get_requests_for_discord_id(client, request.get("discordUserId"), logger=self.logger):
            if item.get("id") == request.get("id"):
                return item
        return request

    def decide_in_ticket(self, *, ticket_channel_id, actor_id, actor_name, tier, decision, reason="", is_line_manager=False, hod_first=False):
        client = require_db(self.client)
        existing = get_request_by_ticket_channel(client, ticket_channel_id, logger=self.logger)
        if existing and not is_open(existing.get("status")):
            raise self._already_decided_error(existing.get("status"))
        request = get_pending_request_by_ticket_channel(client, ticket_channel_id, logger=self.logger)
        if tier == MANAGER and not is_line_manager:
            is_line_manager = self.is_hod_of_employee(actor_id, request.get("discordUserId"))
        return self.decide_request(
            request,
            actor_id=actor_id,
            actor_name=actor_name,
            tier=tier,
            decision=decision,
            reason=reason,
            is_line_manager=is_line_manager,
            hod_first=hod_first,
        )

    def approve_in_ticket(self, *, ticket_channel_id, hr_discord_id, hr_name, tier=ADMIN, is_line_manager=False):
        return self.decide_in_ticket(
            ticket_channel_id=ticket_channel_id,
            actor_id=hr_discord_id,
            actor_name=hr_name,
            tier=tier,
            decision="approve",
            is_line_manager=is_line_manager,
        )

    def reject_in_ticket(self, *, ticket_channel_id, hr_discord_id, hr_name, reason="", tier=ADMIN, is_line_manager=False):
        return self.decide_in_ticket(
            ticket_channel_id=ticket_channel_id,
            actor_id=hr_discord_id,
            actor_name=hr_name,
            tier=tier,
            decision="reject",
            reason=reason,
            is_line_manager=is_line_manager,
        )

    # -- reversing an approved leave ----------------------------------------

    def cancel_approved_request(self, request, *, actor_id, actor_name, tier, reason=""):
        """Undo an approved leave and give the days back.

        Employees may cancel their own future leave. Leave that has already
        started, and anyone else's leave, is HR or Admin only.
        """
        client = require_db(self.client)
        with self.lock:
            fresh = self._reload(request)
            status = normalize(fresh.get("status"))
            if status != APPROVED:
                raise AppError(
                    ErrorCodes.LEAVE_REQUEST_MISSING,
                    "That leave is not approved, so there is nothing to cancel.",
                    expose=True,
                )
            start = _as_day(fresh.get("startDate"))
            if start and start <= date.today() and tier not in {HR, ADMIN}:
                raise AppError(
                    ErrorCodes.HR_PERMISSION,
                    "Leave that has already started can only be cancelled by HR or Admin.",
                    expose=True,
                )
            employee = self.employees.get_me(fresh["discordUserId"])
            leave_type = get_leave_type_by_name(client, fresh["leaveType"], logger=self.logger)
            days = fresh.get("daysRequested") or 0
            remaining_after = None
            if not is_unpaid(leave_type) and days:
                balance = get_leave_balance(client, employee, leave_type["name"], logger=self.logger)
                # A negative delta hands the days back.
                updated = update_used_leave(client, balance, -float(days), logger=self.logger)
                remaining_after = updated["remaining"]
            actor_label = f"{actor_name} ({actor_id})"
            saved = update_request_status(
                client,
                fresh,
                {
                    "Status": CANCELLED,
                    "Cancelled At": datetime.now(timezone.utc).isoformat(),
                    "Cancelled By": actor_label,
                    "Rejection Reason": str(reason or "").strip() or "Cancelled after approval",
                },
                logger=self.logger,
                op="leave_cancel_approved",
            )
            release_utilized_days(client, request=fresh, logger=self.logger)
            saved["remaining"] = remaining_after
            saved["employeeName"] = employee.get("name")
            saved["cancelledBy"] = actor_label
            saved["department"] = normalize_department(employee.get("department")) or fresh.get("department") or ""
            if not saved.get("managerApprovedBy"):
                saved["managerApprovedBy"] = fresh.get("managerApprovedBy") or ""
            if not saved.get("approvedBy"):
                saved["approvedBy"] = fresh.get("approvedBy") or ""
            if self.logger:
                self.logger.info("approved leave cancelled", {
                    "requestId": fresh.get("requestId"),
                    "days": days,
                    "tier": tier,
                })
            return saved

    def list_cancellable_approved(self, discord_user_id, *, upcoming_only=True):
        """Approved leave the member can cancel (future dates for staff)."""
        client = require_db(self.client)
        types = get_active_leave_types(client, logger=self.logger)
        today = date.today()
        rows = []
        for item in get_requests_for_discord_id(client, discord_user_id, logger=self.logger):
            if normalize(item.get("status")) != APPROVED:
                continue
            start = _as_day(item.get("startDate"))
            end = _as_day(item.get("endDate")) or start
            if upcoming_only and start and start <= today:
                continue
            rows.append({
                "id": item.get("id"),
                "requestId": item.get("requestId"),
                "leave_type": _public_leave_label(item.get("leaveType"), types),
                "start_date": start.isoformat() if start else "",
                "end_date": end.isoformat() if end else "",
                "days": item.get("daysRequested") or 1,
            })
        rows.sort(key=lambda row: row.get("start_date") or "")
        return rows

    def cancel_approved_for_member(self, discord_user_id, *, request_id=None, start_date=None, end_date=None, actor_id=None, actor_name="", tier="employee", reason=""):
        approved = [
            item
            for item in get_requests_for_discord_id(require_db(self.client), discord_user_id, logger=self.logger)
            if normalize(item.get("status")) == APPROVED
        ]
        if request_id:
            approved = [item for item in approved if request_id in {item.get("id"), item.get("requestId")}]
        if start_date:
            wanted_start = _as_day(start_date)
            wanted_end = _as_day(end_date) or wanted_start
            matched = [
                item
                for item in approved
                if _as_day(item.get("startDate")) == wanted_start
                and (_as_day(item.get("endDate")) or _as_day(item.get("startDate"))) == wanted_end
            ]
            if not matched:
                raise AppError(
                    ErrorCodes.LEAVE_REQUEST_MISSING,
                    "Those dates do not match an approved leave. Choose the leave from the form.",
                    expose=True,
                )
            approved = matched
        if not approved:
            raise AppError(
                ErrorCodes.LEAVE_REQUEST_MISSING,
                "You do not have an approved leave to cancel.",
                expose=True,
            )
        upcoming = [item for item in approved if (_as_day(item.get("startDate")) or date.today()) > date.today()]
        target = (upcoming or approved)[0]
        return self.cancel_approved_request(
            target,
            actor_id=actor_id or discord_user_id,
            actor_name=actor_name or "Employee",
            tier=tier,
            reason=reason,
        )

    # -- queues and calendar -------------------------------------------------

    def open_requests(self):
        """Every request still awaiting a decision, oldest first."""
        client = require_db(self.client)
        rows = all_leave_requests(client, logger=self.logger)
        open_rows = [item for item in rows if is_open(item.get("status"))]
        open_rows.sort(key=lambda item: item.get("requestedAt") or "")
        return open_rows

    def _employee_name(self, discord_user_id):
        """Employee name for a Discord id; request rows do not store it."""
        if not discord_user_id:
            return ""
        try:
            return self.employees.get_me(str(discord_user_id)).get("name") or ""
        except AppError:
            return ""

    def _with_leave_names(self, rows):
        """Fill in the leave-type name and employee name; embeds show these rows as-is."""
        if not rows:
            return rows
        types = get_active_leave_types(require_db(self.client), logger=self.logger)
        names = {}
        out = []
        for item in rows:
            row = {**item, "leaveType": _public_leave_label(item.get("leaveType"), types)}
            discord_id = str(item.get("discordUserId") or "")
            if not row.get("employeeName") and discord_id:
                if discord_id not in names:
                    names[discord_id] = self._employee_name(discord_id)
                row["employeeName"] = names[discord_id]
            out.append(row)
        return out

    def queue_for_actor(self, *, discord_user_id, tier):
        """What is waiting for this person to decide."""
        return self._with_leave_names(self._queue_rows(discord_user_id=discord_user_id, tier=tier))

    def _queue_rows(self, *, discord_user_id, tier):
        rows = self.open_requests()
        if tier == ADMIN:
            return rows
        if tier == HR:
            return [item for item in rows if stage_for(item.get("status")) == HR]
        if tier != MANAGER:
            return []
        try:
            actor = self.employees.get_me(discord_user_id)
        except AppError:
            return []
        dept = normalize_department(actor.get("department"))
        if not dept or not is_hod_title(actor.get("hrRole")):
            return []
        out = []
        for item in rows:
            if stage_for(item.get("status")) != MANAGER:
                continue
            try:
                employee = self.employees.get_me(item.get("discordUserId"))
            except AppError:
                continue
            if normalize_department(employee.get("department")) == dept:
                out.append(item)
        return out

    def leave_calendar(self, discord_user_id, *, upcoming_only=True, role_names=None):
        """This person's booked leave: approved first, then anything waiting."""
        from app.hr.leave_access import leave_disabled_for_employee, leave_disabled_message

        client = require_db(self.client)
        try:
            employee = self.employees.get_me(discord_user_id)
        except AppError:
            employee = None
        if leave_disabled_for_employee(employee, role_names):
            raise AppError(
                ErrorCodes.LEAVE_NOT_AVAILABLE,
                leave_disabled_message("english"),
                expose=True,
            )
        rows = get_requests_for_discord_id(client, discord_user_id, logger=self.logger)
        today = date.today()
        approved = []
        waiting = []
        for item in rows:
            status = normalize(item.get("status"))
            start = _as_day(item.get("startDate"))
            end = _as_day(item.get("endDate")) or start
            if upcoming_only and end and end < today:
                continue
            if status == APPROVED:
                approved.append(item)
            elif is_open(status):
                waiting.append(item)
        approved.sort(key=lambda item: item.get("startDate") or "")
        waiting.sort(key=lambda item: item.get("startDate") or "")
        return {"approved": self._with_leave_names(approved), "waiting": self._with_leave_names(waiting), "today": today}

    def entitlement_summary(self, discord_user_id, locale=None):
        """What this employee is entitled to per year, from their balances.

        Used when someone asks how much leave is allowed and the handbook has
        nothing on it. These are recorded entitlements, not a quote from a
        policy document, and the wording says so.
        """
        client = require_db(self.client)
        employee = self.employees.get_me(discord_user_id)
        balances = get_employee_leave_balances(client, employee, logger=self.logger)
        if not balances:
            return None
        types = get_active_leave_types(client, logger=self.logger)
        lines = [pick_locale_text(
            locale,
            english="This is the leave recorded against your account for this year.",
            roman="Is saal aapke account par yeh leave record hai.",
            urdu="اس سال آپ کے اکاؤنٹ پر یہ لیو ریکارڈ ہے۔",
            mix="Is saal aapke account par yeh leave record hai.",
        ), ""]
        for item in balances:
            label = _public_leave_label(item.get("leaveType"), types)
            total = _qty(item.get("totalEntitlement"))
            remaining = _qty(item.get("remaining"))
            lines.append(pick_locale_text(
                locale,
                english=f"• **{label}** — {total} day(s) per year, {remaining} still available",
                roman=f"• **{label}** — saal mein {total} din, {remaining} abhi baqi",
                urdu=f"• **{label}** — سال میں {total} دن، {remaining} ابھی باقی",
                mix=f"• **{label}** — saal mein {total} day(s), {remaining} available",
            ))
        lines.append("")
        lines.append(pick_locale_text(
            locale,
            english="If you need the written policy wording, I can bring in HR.",
            roman="Agar likhi hui policy chahiye to main HR ko bula deta hoon.",
            urdu="اگر تحریری پالیسی درکار ہو تو میں HR کو بلا دیتا ہوں۔",
            mix="Likhi hui policy chahiye to main HR ko bula deta hoon.",
        ))
        return {"employee": employee, "balances": balances, "text": "\n".join(lines)}

    def active_leave_type_names(self):
        types = get_active_leave_types(require_db(self.client), logger=self.logger)
        return [item["name"] for item in types]

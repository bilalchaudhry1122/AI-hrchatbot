from app.records.attendance import get_attendance_for_date_range
from app.hr.dates import resolve_attendance_range
from app.hr.employee_service import EmployeeService, require_db


class AttendanceService:
    def __init__(self, client, logger):
        self.client = client
        self.logger = logger
        self.employees = EmployeeService(client, logger)

    def get_my_attendance(self, discord_user_id, start_date, end_date):
        employee = self.employees.get_me(discord_user_id)
        rows = get_attendance_for_date_range(
            require_db(self.client),
            employee,
            start_date,
            end_date,
            logger=self.logger,
        )
        summary = {}
        for row in rows:
            key = (row.get("status") or "Unknown").strip() or "Unknown"
            summary[key] = summary.get(key, 0) + 1
        lines = [f"{name}: {count}" for name, count in sorted(summary.items())] or ["No attendance records in that range."]
        return {
            "employee": employee,
            "rows": rows,
            "summary": summary,
            "text": (
                f"Attendance {start_date.isoformat()} to {end_date.isoformat()}:\n" + "\n".join(lines)
            ),
        }

    def get_my_month(self, discord_user_id, question=""):
        start, end = resolve_attendance_range(question)
        return self.get_my_attendance(discord_user_id, start, end)

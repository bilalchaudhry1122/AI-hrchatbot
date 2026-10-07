import threading

from app.hr.attendance_service import AttendanceService
from app.hr.employee_service import EmployeeService
from app.hr.leave_service import LeaveService
from app.hr.permissions import is_hr_admin, is_hr_member, tier_for


class HrServices:
    def __init__(self, client, logger, config=None):
        self.client = client
        self.logger = logger
        self.config = config or {}
        self.lock = threading.Lock()
        self.employees = EmployeeService(client, logger)
        self.leave = LeaveService(client, logger, lock=self.lock, config=self.config)
        self.attendance = AttendanceService(client, logger)


def create_hr_services(client, logger, config=None):
    return HrServices(client, logger, config)


__all__ = ["HrServices", "create_hr_services", "is_hr_admin", "is_hr_member", "tier_for"]

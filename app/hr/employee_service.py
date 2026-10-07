from app.records.employees import get_employee_by_discord_id
from app.errors import AppError, ErrorCodes


def require_db(client):
    if client is None:
        raise AppError(ErrorCodes.DB_UNAVAILABLE, "HR data is not connected yet. Please contact HR.", expose=True)
    return client


# Back-compat alias used by older call sites during the MySQL cutover.
require_airtable = require_db


class EmployeeService:
    def __init__(self, client, logger):
        self.client = client
        self.logger = logger

    def get_me(self, discord_user_id):
        return get_employee_by_discord_id(require_db(self.client), discord_user_id, logger=self.logger)

    def whoami_text(self, discord_user_id):
        employee = self.get_me(discord_user_id)
        return (
            f"Employee: {employee.get('name') or 'Unknown'}\n"
            f"Employee ID: {employee.get('employeeId') or 'Unknown'}\n"
            f"Department: {employee.get('department') or 'Unknown'}"
        )

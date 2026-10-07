"""Remove leave balances/requests/utilization for CS Member and Sales Member."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_config
from app.db.client import MysqlClient
from app.hr.leave_access import leave_disabled_for_employee
from app.logger import create_logger
from app.records.employees import list_employees, wipe_employee_leave_rows


def main():
    config = load_config()
    logger = create_logger("info")
    client = MysqlClient(config, logger)
    people = list_employees(client, logger=logger)
    targets = [p for p in people if leave_disabled_for_employee(p)]
    print(f"matched_employees={len(targets)}")
    total = {"leaveUtilization": 0, "leaveRequests": 0, "leaveBalances": 0}
    for person in targets:
        summary = wipe_employee_leave_rows(client, person, logger=logger) or {}
        print(
            f"wiped {person.get('name')} dept={person.get('department')} "
            f"hrRole={person.get('hrRole')} roles={person.get('discordRoles')!r} {summary}"
        )
        for key in total:
            total[key] += int(summary.get(key) or 0)
    print("TOTAL", total)


if __name__ == "__main__":
    main()

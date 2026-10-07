"""Print HR and HOD Emails currently on Employees in MySQL."""

from app.records.employees import list_employees
from app.config import load_config
from app.db.client import create_mysql_client
from app.hr.departments import hod_department_from_role_names, normalize_department
from app.logger import create_logger
from app.mail.leave import is_reviewer_email


def _role_names(person):
    return [line.strip() for line in str(person.get("discordRoles") or "").splitlines() if line.strip()]


def main():
    config = load_config()
    logger = create_logger("info")
    client = create_mysql_client(config, logger)
    if client is None:
        raise SystemExit("MySQL is not configured (set DATABASE_URL)")
    print("HR / HOD mailboxes on Employees:")
    for person in list_employees(client, logger=logger):
        if not person.get("active"):
            continue
        email = str(person.get("email") or "").strip()
        role = str(person.get("hrRole") or "").strip()
        names = _role_names(person)
        hod = hod_department_from_role_names(names)
        if not hod and role == "HOD":
            hod = normalize_department(person.get("department"))
        is_hr = role in {"HR", "Admin"} or any(line.lower() == "hr" for line in names)
        if not (hod or is_hr):
            continue
        mark = "ok" if is_reviewer_email(email) else "missing Email"
        label = "HR" if is_hr else f"{hod} HOD"
        print(f"  {person.get('name')}: {label} {email or '(empty)'} [{mark}]")


if __name__ == "__main__":
    main()

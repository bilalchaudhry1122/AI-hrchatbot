# Database

HR live data is **MySQL only** via `DATABASE_URL` (or `MYSQL_*`). Drop-in client: `app/db/client.py`. Domain helpers: `app/records/`.

Tables: `employees`, `leave_types`, `leave_balances`, `leave_requests`, `leave_utilization`, `holidays`, `discord_roles`, `hr_announcements`.

Feature mapping:
- Birthdays / cake reminders → `employees.DOB` (+ address/contact for HR eve reminder)
- Scheduled HR announcements → `hr_announcements` (Status Scheduled/Posted/Cancelled)
- Onboarding welcome → live Discord post to `#announcements` (no DB row); profile stored on `employees`

## `sessions.json`

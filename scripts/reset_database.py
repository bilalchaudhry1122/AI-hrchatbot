"""Reset the `hr` MySQL database for the onboarding overhaul.

Idempotent:
  1. Adds the new employees profile columns (CNIC, DOB, Contact Number, Address)
     if they are missing.
  2. TRUNCATEs all 7 tables (wipes every row; schema/columns stay).
  3. Re-seeds the 4 default leave types.

Run this AFTER you have manually removed the Discord server members, and
BEFORE the bot is restarted with the new onboarding flow.

Usage:
  python scripts/reset_database.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.config import optional  # noqa: E402
from scripts.setup_mysql import SEED_LEAVE_TYPES, connect, db_settings  # noqa: E402

# Order matters: children before parents, so FK-less TRUNCATE never fails on
# a stale reference (MySQL still checks FK constraints during TRUNCATE even
# though this schema has none — order kept defensive for future FKs).
TABLES_IN_DELETE_ORDER = [
    "leave_utilization",
    "leave_requests",
    "leave_balances",
    "hr_announcements",
    "holidays",
    "discord_roles",
    "leave_types",
    "employees",
]

NEW_EMPLOYEE_COLUMNS = [
    ("CNIC", "VARCHAR(32) NULL"),
    ("DOB", "DATE NULL"),
    ("Contact Number", "VARCHAR(32) NULL"),
    ("Address", "VARCHAR(500) NULL"),
    ("Designation", "VARCHAR(120) NULL"),
    ("Photo Path", "VARCHAR(255) NULL"),
]


def _column_exists(cursor, database, table, column):
    cursor.execute(
        """
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        [database, table, column],
    )
    (count,) = cursor.fetchone()
    return count > 0


def ensure_profile_columns(cursor, database):
    for name, ddl in NEW_EMPLOYEE_COLUMNS:
        if _column_exists(cursor, database, "employees", name):
            print(f"Column already present: employees.{name}")
            continue
        cursor.execute(f"ALTER TABLE `employees` ADD COLUMN `{name}` {ddl}")
        print(f"Added column: employees.{name}")


def truncate_all(cursor):
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    for table in TABLES_IN_DELETE_ORDER:
        cursor.execute(f"TRUNCATE TABLE `{table}`")
        print(f"Truncated: {table}")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")


def reseed_leave_types(cursor):
    for fields in SEED_LEAVE_TYPES:
        record_id = f"seed-{fields['Code'].lower()}"
        cursor.execute(
            """
            INSERT INTO leave_types (id, `Leave Type`, `Code`, `Description`, `Active`)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [record_id, fields["Leave Type"], fields["Code"], fields["Description"], 1 if fields["Active"] else 0],
        )
        print(f"Re-seeded leave type: {fields['Leave Type']}")


def main():
    try:
        import pymysql  # noqa: F401
    except ImportError:
        print("PyMySQL is missing. Run: pip install PyMySQL")
        sys.exit(1)

    settings = db_settings()
    database = settings.get("name") or optional("MYSQL_DATABASE", "hr")

    confirm = optional("RESET_DB_CONFIRM", "")
    if confirm.lower() not in {"yes", "y", "true", "1"}:
        answer = input(
            f"This will ERASE every row in every table of `{database}` on "
            f"{settings.get('host')}. Type 'yes' to continue: "
        ).strip().lower()
        if answer not in {"yes", "y"}:
            print("Aborted. No changes made.")
            sys.exit(1)

    conn = connect(settings, database=database)
    try:
        with conn.cursor() as cursor:
            ensure_profile_columns(cursor, database)
            truncate_all(cursor)
            reseed_leave_types(cursor)
        print(f"Database `{database}` reset complete: same schema, empty tables, fresh leave types.")
        print("Restart the bot to pick up the new onboarding flow.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

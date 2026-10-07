"""Create the `hr` MySQL schema and seed leave types.

Uses DATABASE_URL (preferred) or MYSQL_* from .env.

Usage:
  python scripts/setup_mysql.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.config import load_config, optional  # noqa: E402


SEED_LEAVE_TYPES = [
    {"Leave Type": "Annual Leave", "Code": "ANNUAL", "Description": "Paid annual leave", "Active": True},
    {"Leave Type": "Sick Leave", "Code": "SICK", "Description": "Sick leave", "Active": True},
    {"Leave Type": "Casual Leave", "Code": "CASUAL", "Description": "Casual leave", "Active": True},
]


def db_settings():
    config = load_config()
    db = dict(config.get("db") or {})
    if not db.get("name"):
        db["name"] = optional("MYSQL_DATABASE", "hr")
    return db


def connect(settings, database=None):
    import pymysql

    return pymysql.connect(
        host=settings.get("host") or "127.0.0.1",
        port=int(settings.get("port") or 3306),
        user=settings.get("user") or "root",
        password=settings.get("password") or "",
        database=database,
        charset="utf8mb4",
        autocommit=True,
    )


def main():
    try:
        import pymysql  # noqa: F401
    except ImportError:
        print("PyMySQL is missing. Run: pip install PyMySQL")
        sys.exit(1)

    settings = db_settings()
    database = settings.get("name") or "hr"
    schema_path = ROOT / "scripts" / "schema_mysql.sql"
    sql = schema_path.read_text(encoding="utf-8")
    # Rewrite CREATE DATABASE / USE to match DATABASE_URL db name.
    sql = sql.replace("CREATE DATABASE IF NOT EXISTS hr", f"CREATE DATABASE IF NOT EXISTS `{database}`")
    sql = sql.replace("USE hr;", f"USE `{database}`;")

    print(f"Connecting to MySQL at {settings.get('host')}:{settings.get('port')} as {settings.get('user')}")
    conn = connect(settings, database=None)
    try:
        with conn.cursor() as cursor:
            for statement in sql.split(";"):
                lines = [
                    line
                    for line in statement.splitlines()
                    if line.strip() and not line.strip().startswith("--")
                ]
                chunk = "\n".join(lines).strip()
                if not chunk:
                    continue
                cursor.execute(chunk)
        print(f"Schema ready in database `{database}`.")
    finally:
        conn.close()

    conn = connect(settings, database=database)
    try:
        with conn.cursor() as cursor:
            # Drop leftover unused tables from earlier drafts.
            for leftover in ("attendance",):
                cursor.execute(f"DROP TABLE IF EXISTS `{leftover}`")
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'employees' AND COLUMN_NAME = 'Designation'
                """,
                [database],
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE `employees` ADD COLUMN `Designation` VARCHAR(120) NULL")
                print("Added column: employees.Designation")
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'employees' AND COLUMN_NAME = 'Photo Path'
                """,
                [database],
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE `employees` ADD COLUMN `Photo Path` VARCHAR(255) NULL")
                print("Added column: employees.Photo Path")
            cursor.execute("SELECT `Code` FROM leave_types")
            have = {str(row[0] or "").upper() for row in cursor.fetchall()}
            for fields in SEED_LEAVE_TYPES:
                code = fields["Code"].upper()
                if code in have:
                    print(f"Leave type already present: {fields['Leave Type']}")
                    continue
                record_id = f"seed-{code.lower()}"
                cursor.execute(
                    """
                    INSERT INTO leave_types
                      (id, `Leave Type`, `Code`, `Description`, `Active`)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [
                        record_id,
                        fields["Leave Type"],
                        fields["Code"],
                        fields["Description"],
                        1 if fields["Active"] else 0,
                    ],
                )
                print(f"Seeded leave type: {fields['Leave Type']}")
        print("MySQL HR schema is ready.")
        print("Set DB_BACKEND=mysql (or leave DATABASE_URL set) and restart the bot.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

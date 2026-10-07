"""MySQL client with the same surface as AirtableClient / FakeStore."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from uuid import uuid4

from app.records.fields import wrap_db_error
from app.db.schema import BOOL_FIELDS, DATE_FIELDS, LINK_FIELDS, TABLE_COLUMNS, TABLE_NAMES
from app.errors import AppError, ErrorCodes

FORMULA_EQ = re.compile(r"\{([^}]+)\}='((?:\\.|[^'\\])*)'")
FORMULA_NUM = re.compile(r"\{([^}]+)\}=(-?\d+(?:\.\d+)?)")


def _quote(name):
    return "`" + str(name).replace("`", "``") + "`"


def _new_id():
    return f"sql{uuid4().hex[:14]}"


def _unescape_formula(value):
    return str(value).replace("\\'", "'").replace("\\\\", "\\")


def translate_formula(formula):
    """Turn the few Airtable formulas this bot uses into SQL WHERE + params."""
    text = str(formula or "").strip()
    if not text:
        return "", []
    match = FORMULA_EQ.fullmatch(text)
    if match:
        return f"{_quote(match.group(1))} = %s", [_unescape_formula(match.group(2))]
    match = FORMULA_NUM.fullmatch(text)
    if match:
        return f"{_quote(match.group(1))} = %s", [float(match.group(2))]
    raise AppError(
        ErrorCodes.CONFIG,
        f"Unsupported MySQL formula: {text}",
        expose=False,
    )


def _encode_value(key, value, *, link_fields, bool_fields, date_fields):
    if value is None:
        return None
    if key in link_fields:
        if isinstance(value, list):
            return json.dumps([str(item) for item in value if item is not None])
        text = str(value).strip()
        return json.dumps([text]) if text else None
    if key in bool_fields:
        return 1 if value in (True, 1, "1", "true", "True") else 0
    if key in date_fields:
        text = str(value)[:10]
        return text or None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10] if key in date_fields else value.isoformat()
    return value


def _decode_value(key, value, *, link_fields, bool_fields):
    if value is None:
        return None
    if key in link_fields:
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", errors="replace")
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return [text]
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item is not None]
            return [str(parsed)]
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]
    if key in bool_fields:
        return bool(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class MysqlTable:
    def __init__(self, client, key):
        self.client = client
        self.key = key
        self.name = TABLE_NAMES[key]
        self.columns = list(TABLE_COLUMNS[key])
        self.link_fields = LINK_FIELDS.get(key, set())
        self.bool_fields = BOOL_FIELDS.get(key, set())
        self.date_fields = DATE_FIELDS.get(key, set())

    def _row_to_record(self, row):
        if not row:
            return None
        fields = {}
        for key, value in row.items():
            if key == "id":
                continue
            fields[key] = _decode_value(
                key,
                value,
                link_fields=self.link_fields,
                bool_fields=self.bool_fields,
            )
        return {"id": str(row["id"]), "fields": fields}

    def all(self, formula=None):
        where, params = translate_formula(formula)
        sql = f"SELECT * FROM {_quote(self.name)}"
        if where:
            sql += f" WHERE {where}"
        with self.client.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def create(self, fields, typecast=True):  # noqa: ARG002 - matches pyairtable
        payload = dict(fields or {})
        record_id = str(payload.pop("id", "") or "").strip() or _new_id()
        columns = ["id"]
        values = [record_id]
        for key in self.columns:
            if key not in payload:
                continue
            columns.append(key)
            values.append(
                _encode_value(
                    key,
                    payload[key],
                    link_fields=self.link_fields,
                    bool_fields=self.bool_fields,
                    date_fields=self.date_fields,
                )
            )
        placeholders = ", ".join(["%s"] * len(columns))
        col_sql = ", ".join(_quote(name) for name in columns)
        sql = f"INSERT INTO {_quote(self.name)} ({col_sql}) VALUES ({placeholders})"
        with self.client.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, values)
            conn.commit()
        return self.get(record_id)

    def update(self, record_id, fields, typecast=True):  # noqa: ARG002
        payload = dict(fields or {})
        if not payload:
            return self.get(record_id)
        assignments = []
        values = []
        for key, value in payload.items():
            if key == "id" or key not in self.columns:
                continue
            assignments.append(f"{_quote(key)} = %s")
            values.append(
                _encode_value(
                    key,
                    value,
                    link_fields=self.link_fields,
                    bool_fields=self.bool_fields,
                    date_fields=self.date_fields,
                )
            )
        if not assignments:
            return self.get(record_id)
        values.append(str(record_id))
        sql = f"UPDATE {_quote(self.name)} SET {', '.join(assignments)} WHERE {_quote('id')} = %s"
        with self.client.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, values)
            conn.commit()
        return self.get(record_id)

    def delete(self, record_id):
        with self.client.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {_quote(self.name)} WHERE {_quote('id')} = %s",
                    [str(record_id)],
                )
            conn.commit()
        return True

    def get(self, record_id):
        with self.client.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT * FROM {_quote(self.name)} WHERE {_quote('id')} = %s",
                    [str(record_id)],
                )
                row = cursor.fetchone()
        return self._row_to_record(row)


class MysqlClient:
    def __init__(self, config, logger):
        db = (config or {}).get("db") or {}
        if not db.get("enabled"):
            raise AppError(ErrorCodes.CONFIG, "MySQL is not configured.")
        self.config = config
        self.logger = logger
        self.settings = {
            "host": db.get("host") or "127.0.0.1",
            "port": int(db.get("port") or 3306),
            "user": db.get("user") or "root",
            "password": db.get("password") or "",
            "database": db.get("name") or "webairy_hr",
            "charset": "utf8mb4",
            "autocommit": False,
            "cursorclass": None,
        }
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as error:
            raise AppError(
                ErrorCodes.CONFIG,
                "PyMySQL is not installed. Run: pip install PyMySQL",
                cause=error,
            ) from error
        self._pymysql = pymysql
        self.settings["cursorclass"] = DictCursor
        # Fail fast if Workbench MySQL is down or credentials are wrong.
        with self.connection():
            pass
        self._ensure_employee_extra_columns()

    def _ensure_employee_extra_columns(self):
        extras = (
            ("Designation", "VARCHAR(120) NULL"),
            ("Photo Path", "VARCHAR(255) NULL"),
        )
        database = self.settings.get("database")
        with self.connection() as conn:
            with conn.cursor() as cursor:
                for name, ddl in extras:
                    cursor.execute(
                        """
                        SELECT COUNT(*) AS c FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'employees' AND COLUMN_NAME = %s
                        """,
                        [database, name],
                    )
                    row = cursor.fetchone() or {}
                    count = row.get("c") if isinstance(row, dict) else row[0]
                    if not count:
                        cursor.execute(f"ALTER TABLE `employees` ADD COLUMN `{name}` {ddl}")
            conn.commit()

    def connection(self):
        try:
            return self._pymysql.connect(**self.settings)
        except Exception as error:
            raise wrap_db_error(error) from error

    def table(self, key):
        if key not in TABLE_NAMES:
            raise AppError(ErrorCodes.CONFIG, f"MySQL table '{key}' is not configured.")
        return MysqlTable(self, key)


def create_mysql_client(config, logger):
    if not ((config or {}).get("db") or {}).get("enabled"):
        return None
    return MysqlClient(config, logger)

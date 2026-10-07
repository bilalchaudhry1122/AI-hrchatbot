"""MySQL client unit tests (no live Workbench required)."""

from app.config import parse_database_url
from app.db.client import _decode_value, _encode_value, translate_formula
from app.db.schema import LINK_FIELDS, TABLE_NAMES


def test_parse_database_url():
    parsed = parse_database_url("mysql://root:123456@localhost:3306/hr")
    assert parsed["host"] == "localhost"
    assert parsed["port"] == 3306
    assert parsed["user"] == "root"
    assert parsed["password"] == "123456"
    assert parsed["name"] == "hr"


def test_attendance_not_in_mysql_schema():
    assert "attendance" not in TABLE_NAMES


def test_formula_equality_and_year():
    where, params = translate_formula("{Discord User ID}='980548748725866516'")
    assert "Discord User ID" in where
    assert params == ["980548748725866516"]

    where, params = translate_formula("{Year}=2026")
    assert "Year" in where
    assert params == [2026.0]


def test_formula_escapes_quotes():
    where, params = translate_formula("{Employee Name}='O\\'Brien'")
    assert params == ["O'Brien"]


def test_link_fields_round_trip_as_lists():
    links = LINK_FIELDS["leaveBalances"]
    encoded = _encode_value("Employee", ["recEmp1"], link_fields=links, bool_fields=set(), date_fields=set())
    assert encoded == '["recEmp1"]'
    decoded = _decode_value("Employee", encoded, link_fields=links, bool_fields=set())
    assert decoded == ["recEmp1"]


def test_bool_and_date_encode():
    encoded = _encode_value("Active", True, link_fields=set(), bool_fields={"Active"}, date_fields=set())
    assert encoded == 1
    encoded = _encode_value(
        "Join Date",
        "2026-09-22T11:00:00+00:00",
        link_fields=set(),
        bool_fields=set(),
        date_fields={"Join Date"},
    )
    assert encoded == "2026-09-22"

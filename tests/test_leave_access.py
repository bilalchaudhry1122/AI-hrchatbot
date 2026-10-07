def test_leave_disabled_for_cs_and_sales_member_roles():
    from app.hr.leave_access import (
        leave_disabled_for_department_level,
        leave_disabled_for_employee,
        leave_disabled_for_roles,
        leave_disabled_message,
    )

    assert leave_disabled_for_roles(["CS Member"]) is True
    assert leave_disabled_for_roles(["Sales Member"]) is True
    assert leave_disabled_for_roles(["BI Member"]) is False
    assert leave_disabled_for_roles(["CS HOD"]) is False
    assert leave_disabled_for_employee({"department": "CS", "hrRole": "Member"}) is True
    assert leave_disabled_for_employee({"department": "Sales", "hrRole": "Member"}) is True
    assert leave_disabled_for_employee({"department": "CS", "hrRole": "HOD"}) is False
    assert leave_disabled_for_department_level("CS", "Member") is True
    assert leave_disabled_for_department_level("CS", "HOD") is False
    assert "CS Member" in leave_disabled_message("english")


def test_leave_service_blocks_cs_member_balance(monkeypatch):
    from app.errors import AppError, ErrorCodes
    from tests.test_hr import make_hr

    hr = make_hr()
    # Mark Abdullah as CS Member in the fake store.
    emp = next(item for item in hr.client.table("employees").records if item["id"] == "recEmp1")
    emp["fields"]["Department"] = "CS"
    emp["fields"]["HR Role"] = "Member"
    emp["fields"]["Discord Roles"] = "CS Member"

    try:
        hr.leave.get_my_leave_balance("111", role_names=["CS Member"])
        raised = False
    except AppError as error:
        raised = error.code == ErrorCodes.LEAVE_NOT_AVAILABLE and error.expose
    assert raised is True

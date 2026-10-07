"""Discord roles creating and updating employee records."""

from datetime import date
from types import SimpleNamespace

from app.hr import create_hr_services
from app.logger import create_logger

from tests.test_hr import FakeStore
from tests.test_leave_workflow import MON, PENDING_HR, APPROVED, make_hr


# --- role assignment puts people into Airtable ------------------------------
def test_entitlements_are_sixteen_eight_eight():
    from app.hr.staff_onboard import LEAVE_GRANTS

    assert LEAVE_GRANTS["ANNUAL"] == 16
    assert LEAVE_GRANTS["SICK"] == 8
    assert LEAVE_GRANTS["CASUAL"] == 8
    # Only Annual / Sick / Casual are granted; unpaid leave is not a type.
    assert "UNPAID" not in LEAVE_GRANTS


def test_the_sync_script_shares_one_set_of_numbers():
    """The numbers must not drift between the bot and the bulk script."""
    import app.hr.staff_onboard as onboard
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "sync_discord_staff.py"
    text = script.read_text(encoding="utf-8")
    assert "from app.hr.staff_onboard import LEAVE_GRANTS" in text
    assert "LEAVE_GRANTS = {" not in text
    assert onboard.LEAVE_GRANTS["SICK"] == 8


def test_staff_role_marks_an_employee_and_hr_role_marks_hr():
    from app.hr.staff_onboard import staff_kind_from_roles

    staff, admin = "staff-1", "hr-1"
    assert staff_kind_from_roles([staff], staff_role_id=staff, admin_role_id=admin) == "Staff"
    assert staff_kind_from_roles([admin], staff_role_id=staff, admin_role_id=admin) == "HR"
    # Holding both: HR is the higher one and wins.
    assert staff_kind_from_roles([staff, admin], staff_role_id=staff, admin_role_id=admin) == "HR"
    # Nobody without a role is an employee here, since every employee has Staff.
    assert staff_kind_from_roles(["random"], staff_role_id=staff, admin_role_id=admin) is None
    assert staff_kind_from_roles([], staff_role_id=staff, admin_role_id=admin) is None
    assert staff_kind_from_roles(
        ["x"], staff_role_id=staff, admin_role_id=admin, role_names=["Team Member"]
    ) == "Staff"


def test_a_new_member_role_is_enough_to_create_an_employee():
    from app.hr.staff_onboard import staff_kind_from_roles, upsert_staff_employee

    assert staff_kind_from_roles(
        ["bi-member"],
        staff_role_id="staff-1",
        admin_role_id="admin-1",
        role_names=["@everyone", "BI Member"],
    ) == "BI"
    hr = make_hr()
    record = upsert_staff_employee(
        hr.client,
        discord_id="7001",
        name="New Joiner",
        kind="BI",
        logger=create_logger("error"),
    )
    assert record["fields"]["Department"] == "BI"
    assert record["fields"]["HR Role"] == "Member"
    balances = [
        row for row in hr.client.table("leaveBalances").records
        if row["fields"].get("Employee") == [record["id"]]
    ]
    assert len(balances) == 3


def test_assigning_a_role_creates_the_employee_and_their_balances():
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    record = upsert_staff_employee(
        hr.client,
        discord_id="555000111",
        name="Ayesha",
        username="ayesha",
        kind="Staff",
        logger=create_logger("error"),
    )
    assert record["fields"]["Discord User ID"] == "555000111"
    assert record["fields"]["Department"] == "Staff"
    assert record["fields"]["Status"] == "Active"

    balances = {
        row["fields"]["Leave Type"][0]: row["fields"]["Total Entitlement"]
        for row in hr.client.table("leaveBalances").records
        if row["fields"].get("Employee") == [record["id"]]
    }
    by_type = {}
    for row in hr.client.table("leaveTypes").records:
        by_type[row["id"]] = row["fields"]["Leave Type"]
    granted = {by_type[key]: value for key, value in balances.items()}
    assert granted == {"Annual Leave": 16, "Sick Leave": 8, "Casual Leave": 8}


def test_member_hod_and_admin_all_get_leave_quota():
    from app.hr.staff_onboard import staff_kind_from_roles, upsert_staff_employee

    assert staff_kind_from_roles(
        ["x"], staff_role_id="staff-1", admin_role_id="admin-1", role_names=["BI Member"]
    ) == "BI"
    hr = make_hr()
    logger = create_logger("error")
    member = upsert_staff_employee(
        hr.client, discord_id="1", name="Mem", kind="BI", logger=logger
    )
    hod = upsert_staff_employee(
        hr.client, discord_id="2", name="Hod", kind="CS", hod=True, hr_role="HOD", logger=logger
    )
    admin = upsert_staff_employee(
        hr.client, discord_id="3", name="Adm", kind="HR", hr_role="Admin", logger=logger
    )
    assert member["fields"]["Department"] == "BI"
    assert member["fields"]["HR Role"] == "Member"
    assert hod["fields"]["HR Role"] == "HOD"
    assert admin["fields"]["HR Role"] == "Admin"
    for record in (member, hod, admin):
        granted = [
            row for row in hr.client.table("leaveBalances").records
            if row["fields"].get("Employee") == [record["id"]]
        ]
        assert len(granted) == 3


def test_promoting_someone_to_hr_updates_the_same_row():
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    logger = create_logger("error")
    first = upsert_staff_employee(
        hr.client, discord_id="555000222", name="Bilal", kind="Staff", logger=logger
    )
    second = upsert_staff_employee(
        hr.client, discord_id="555000222", name="Bilal", kind="HR", logger=logger
    )
    # Same record, not a duplicate employee.
    assert first["id"] == second["id"]
    assert second["fields"]["HR Role"] == "HR"
    assert second["fields"]["Department"] == "HR"
    rows = [
        row for row in hr.client.table("employees").records
        if row["fields"].get("Discord User ID") == "555000222"
    ]
    assert len(rows) == 1


def test_losing_the_hr_role_clears_the_hr_flag():
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    logger = create_logger("error")
    upsert_staff_employee(hr.client, discord_id="555000333", name="Sara", kind="HR", logger=logger)
    demoted = upsert_staff_employee(
        hr.client, discord_id="555000333", name="Sara", kind="Staff", logger=logger
    )
    assert demoted["fields"]["HR Role"] == "Member"


def test_resyncing_does_not_duplicate_balances():
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    logger = create_logger("error")
    for _ in range(3):
        upsert_staff_employee(
            hr.client, discord_id="555000444", name="Repeat", kind="Staff", logger=logger
        )
    rows = [
        row for row in hr.client.table("leaveBalances").records
        if "Repeat" in str(row["fields"].get("Name", ""))
    ]
    assert len(rows) == 3, "one row per leave type, however many times the sync runs"


def test_a_new_employee_can_immediately_see_their_balance():
    """The whole point: role assigned, then the bot can answer 'how many left'."""
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    upsert_staff_employee(
        hr.client, discord_id="555000555", name="Zara", kind="Staff", logger=create_logger("error")
    )
    snapshot = hr.leave.get_my_leave_snapshot("555000555")
    text = snapshot["text"]
    assert "16 of 16 available" in text
    assert "8 of 8 available" in text
    assert "Pending approval: none" in text


def test_a_new_employee_can_request_leave_end_to_end():
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    upsert_staff_employee(
        hr.client, discord_id="555000666", name="Omar", kind="Staff", logger=create_logger("error")
    )
    created = hr.leave.create_pending_request(
        discord_user_id="555000666",
        ticket_channel_id="920",
        leave_type_name="Sick Leave",
        start_date=MON,
        end_date=MON,
        reason="fever",
    )
    assert created["daysRequested"] == 1
    assert created["status"] == PENDING_HR

    approved = hr.leave.approve_in_ticket(
        ticket_channel_id="920", hr_discord_id="hr", hr_name="HR"
    )
    assert approved["status"] == APPROVED
    # Sick leave started at 8, one day taken.
    after = hr.leave.get_my_leave_snapshot("555000666")["text"]
    assert "7 of 8 available" in after


def test_discord_roles_catalog_upserts_and_renames():
    from app.records.discord_roles import delete_discord_role, skip_role, upsert_discord_role

    everyone = SimpleNamespace(id="1", name="@everyone", managed=False, mentionable=False, position=0, colour=SimpleNamespace(value=0))
    assert skip_role(everyone) is True
    hr = make_hr()
    logger = create_logger("error")
    first = upsert_discord_role(
        hr.client,
        SimpleNamespace(id="99", name="CS Member", managed=False, mentionable=True, position=4, colour=SimpleNamespace(value=12)),
        logger=logger,
    )
    renamed = upsert_discord_role(
        hr.client,
        SimpleNamespace(id="99", name="CS", managed=False, mentionable=True, position=4, colour=SimpleNamespace(value=12)),
        logger=logger,
    )
    assert first["id"] == renamed["id"]
    assert renamed["fields"]["Role Name"] == "CS"
    assert len(hr.client.table("discordRoles").records) == 1
    assert delete_discord_role(hr.client, "99", logger=logger) is True
    assert hr.client.table("discordRoles").records == []


def test_discord_roles_catalog_drops_deleted_roles():
    from app.records.discord_roles import sync_guild_roles

    hr = make_hr()
    logger = create_logger("error")
    sync_guild_roles(
        hr.client,
        [
            SimpleNamespace(id="1", name="@everyone", managed=False, mentionable=False, position=0, colour=SimpleNamespace(value=0)),
            SimpleNamespace(id="10", name="BI Member", managed=False, mentionable=True, position=2, colour=SimpleNamespace(value=1)),
            SimpleNamespace(id="11", name="Old Role", managed=False, mentionable=True, position=3, colour=SimpleNamespace(value=2)),
        ],
        logger=logger,
    )
    assert {row["fields"]["Discord Role ID"] for row in hr.client.table("discordRoles").records} == {"10", "11"}
    sync_guild_roles(
        hr.client,
        [
            SimpleNamespace(id="10", name="BI Member", managed=False, mentionable=True, position=2, colour=SimpleNamespace(value=1)),
        ],
        logger=logger,
    )
    rows = hr.client.table("discordRoles").records
    assert len(rows) == 1
    assert rows[0]["fields"]["Role Name"] == "BI Member"


def test_employee_stores_discord_role_names():
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    record = upsert_staff_employee(
        hr.client,
        discord_id="7002",
        name="Talha",
        kind="CS",
        role_names=["@everyone", "Staff", "Sales Member", "CS Member"],
        logger=create_logger("error"),
    )
    assert "CS Member" in record["fields"]["Discord Roles"]
    assert "@everyone" not in record["fields"]["Discord Roles"]
    assert record["fields"]["Department"] == "CS"


def test_adding_a_new_role_updates_the_employee_discord_roles():
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    logger = create_logger("error")
    first = upsert_staff_employee(
        hr.client,
        discord_id="7003",
        name="Sana",
        kind="BI",
        role_names=["BI Member"],
        logger=logger,
    )
    second = upsert_staff_employee(
        hr.client,
        discord_id="7003",
        name="Sana",
        kind="BI",
        role_names=["BI Member", "New Desk Role"],
        logger=logger,
    )
    assert first["id"] == second["id"]
    assert "New Desk Role" in second["fields"]["Discord Roles"]
    assert "BI Member" in second["fields"]["Discord Roles"]


def test_hr_role_name_is_not_written_as_admin():
    from app.hr.staff_onboard import hr_role_for_guild_member

    guild_member = SimpleNamespace(roles=[SimpleNamespace(id="hr-1", name="HR")])
    config = {
        "hr": {"adminRoleId": "hr-1", "hrRoleId": "hr-1"},
        "discord": {"tickets": {"adminRoleId": "hr-1"}},
    }
    assert hr_role_for_guild_member(guild_member, config) == "HR"

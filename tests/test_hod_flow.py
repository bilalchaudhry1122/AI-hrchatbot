from app.hr.departments import (
    department_from_role_names,
    hod_channel_name,
    hod_department_from_role_names,
    normalize_department,
)
from app.hr.staff_onboard import staff_kind_from_roles
from app.hr.leave_status import PENDING_HR
from tests.test_leave_workflow import MON, make_hr, two_step_config


def test_department_aliases():
    assert normalize_department("bi") == "BI"
    assert normalize_department("Customer Success") == "CS"
    assert normalize_department("marketing hod") == "Marketing"
    assert hod_channel_name("BI") == "bi-hod"
    assert hod_department_from_role_names(["Staff", "BI HOD"]) == "BI"
    assert department_from_role_names(["Staff", "CS"]) == "CS"
    assert normalize_department("BI Member") == "BI"
    assert normalize_department("CS Member") == "CS"
    assert normalize_department("Marketing Member") == "Marketing"
    assert department_from_role_names(["Staff", "Sales Member", "CS Member"]) == "CS"
    assert department_from_role_names(["Sales Member"]) == "Sales"


def test_staff_kind_uses_department_roles():
    assert staff_kind_from_roles(
        ["staff-1"], staff_role_id="staff-1", admin_role_id="admin-1", role_names=["Staff", "BI"]
    ) == "BI"
    assert staff_kind_from_roles(
        ["hod-1"], staff_role_id="staff-1", admin_role_id="admin-1", role_names=["BI HOD"]
    ) == "BI"
    assert staff_kind_from_roles(
        ["admin-1"], staff_role_id="staff-1", admin_role_id="admin-1", role_names=["Admin"]
    ) == "HR"


def test_cs_member_beats_stale_sales_airtable():
    hr = make_hr(two_step_config())
    hr.client.table("employees").records[0]["fields"]["Department"] = "Sales"
    hr.client.table("employees").records[0]["fields"]["HR Role"] = "Member"
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="934",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
        role_names=["Staff", "Sales Member", "CS Member"],
    )
    # HR-only flow: every request goes straight to PENDING_HR. Department is
    # still resolved so the HOD gets a simultaneous, view-only notification.
    assert created["department"] == "CS"
    assert created["needsHod"] is False
    assert created["status"] == PENDING_HR


def test_bi_and_marketing_members_go_to_hod():
    for dept, role in (("BI", "BI Member"), ("Marketing", "Marketing Member")):
        hr = make_hr(two_step_config())
        hr.client.table("employees").records[0]["fields"]["Department"] = "Sales"
        created = hr.leave.create_pending_request(
            discord_user_id="111",
            ticket_channel_id=f"94{len(dept)}",
            leave_type_name="Annual Leave",
            start_date=MON,
            end_date=MON,
            role_names=["Staff", role],
        )
        assert created["department"] == dept
        assert created["needsHod"] is False
        assert created["status"] == PENDING_HR


def test_hod_applying_for_themselves_goes_to_hr():
    hr = make_hr(two_step_config())
    hr.client.table("employees").records[0]["fields"]["Department"] = "BI"
    hr.client.table("employees").records[0]["fields"]["HR Role"] = "HOD"
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="930",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
        role_names=["Staff", "BI HOD"],
    )
    assert created["status"] == PENDING_HR
    assert created["needsHod"] is False
    assert created["department"] == "BI"


def test_admin_leave_skips_hod():
    hr = make_hr(two_step_config())
    hr.client.table("employees").records[0]["fields"]["Department"] = "BI"
    hr.client.table("employees").records[0]["fields"]["HR Role"] = "Admin"
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="933",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
        role_names=["Admin"],
    )
    assert created["status"] == PENDING_HR
    assert created["needsHod"] is False


def test_bi_member_goes_to_hod_even_with_hr_role():
    hr = make_hr(two_step_config())
    hr.client.table("employees").records[0]["fields"]["Department"] = "HR"
    hr.client.table("employees").records[0]["fields"]["HR Role"] = "HR"
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="935",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
        role_names=["HR", "BI Member"],
    )
    assert created["department"] == "BI"
    assert created["needsHod"] is False
    assert created["status"] == PENDING_HR


def test_leave_form_messages_are_recognised():
    from types import SimpleNamespace
    from app.discord.leave_ui import is_leave_form_message

    form = SimpleNamespace(
        embeds=[SimpleNamespace(title="Leave request", footer=SimpleNamespace(text="Fill form  ·  Cancel anytime"))]
    )
    inbox = SimpleNamespace(
        embeds=[SimpleNamespace(title="Leave request", footer=SimpleNamespace(text="ticket:9001"))]
    )
    assert is_leave_form_message(form) is True
    assert is_leave_form_message(inbox) is False


def test_cs_member_role_goes_to_hod_even_if_airtable_says_hod():
    hr = make_hr(two_step_config())
    hr.client.table("employees").records[0]["fields"]["Department"] = ""
    hr.client.table("employees").records[0]["fields"]["HR Role"] = "HOD"
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="932",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
        role_names=["Staff", "CS Member"],
    )
    assert created["status"] == PENDING_HR
    assert created["needsHod"] is False
    assert created["department"] == "CS"


def test_hod_inbox_notifies_on_department_alone():
    from app.discord.leave_inbox import hod_inbox_department

    # HOD notification depends only on department now, never on status/stage.
    assert hod_inbox_department({"status": "PENDING_HR", "department": "CS"}) == "CS"
    assert hod_inbox_department({"status": "APPROVED", "department": "Marketing"}) == "Marketing"
    assert hod_inbox_department({"status": "PENDING_HR", "department": "Sales"}) == ""
    assert hod_inbox_department({"status": "PENDING_HR", "department": ""}) == ""


def test_hod_queue_is_always_empty_notify_only():
    from app.hr.leave_status import MANAGER

    hr = make_hr(two_step_config())
    hr.client.table("employees").records[0]["fields"]["Department"] = "BI"
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="931",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
    )
    # HOD is notify-only: nothing is ever queued for their decision.
    rows = hr.leave.queue_for_actor(discord_user_id="333", tier=MANAGER)
    assert rows == []


def test_ticket_overwrites_hide_every_hod():
    from app.discord.tickets import ticket_overwrites

    class Role:
        def __init__(self, rid, name):
            self.id = rid
            self.name = name

    cs = Role(11, "CS HOD")
    bi = Role(12, "BI HOD")
    marketing = Role(15, "Marketing HOD")
    admin = Role(13, "Admin")
    staff = Role(14, "Staff")
    everyone = Role(1, "@everyone")

    class Guild:
        default_role = everyone
        roles = [everyone, cs, bi, marketing, admin, staff]

        def get_role(self, rid):
            return {11: cs, 12: bi, 13: admin, 14: staff, 15: marketing}.get(int(rid))

    overwrites = ticket_overwrites(
        guild=Guild(),
        user=None,
        bot=None,
        staff_role_id="14",
        admin_role_id="13",
        hod_role_ids=["11", "12", "15"],
    )
    assert overwrites[cs].view_channel is False
    assert overwrites[bi].view_channel is False
    assert overwrites[marketing].view_channel is False
    assert overwrites[admin].view_channel is True
    assert overwrites[staff].view_channel is False


def test_hod_inbox_allows_hr_to_view():
    from app.discord.leave_inbox import _hod_overwrites

    class Role:
        def __init__(self, rid, name):
            self.id = rid
            self.name = name

    everyone = Role(1, "@everyone")
    hr = Role(20, "HR")
    cs = Role(21, "CS HOD")
    staff = Role(22, "Staff")

    class Guild:
        default_role = everyone
        me = None
        roles = [everyone, hr, cs, staff]

        def get_role(self, rid):
            return {20: hr, 21: cs, 22: staff}.get(int(rid))

    config = {
        "discord": {"tickets": {"adminRoleId": "20", "staffRoleId": "22"}},
        "hr": {"hrRoleId": "20", "adminRoleId": "20"},
    }
    overwrites = _hod_overwrites(Guild(), config, "CS")
    assert overwrites[hr].view_channel is True
    assert overwrites[cs].view_channel is True


def test_hod_inbox_allows_named_hr_role():
    from app.discord.leave_inbox import _hod_overwrites

    class Role:
        def __init__(self, rid, name):
            self.id = rid
            self.name = name

    everyone = Role(1, "@everyone")
    hr = Role(20, "Human Resources")
    cs = Role(21, "CS HOD")

    class Guild:
        default_role = everyone
        me = None
        roles = [everyone, hr, cs]

        def get_role(self, rid):
            return {20: hr, 21: cs}.get(int(rid))

    config = {
        "discord": {"tickets": {"adminRoleId": "20", "staffRoleId": ""}},
        "hr": {"hrRoleId": "20"},
    }
    overwrites = _hod_overwrites(Guild(), config, "CS")
    assert overwrites[hr].view_channel is True
    assert overwrites[cs].view_channel is True


def test_hr_and_hod_are_separate_categories():
    from app.discord.leave_inbox import HOD_CATEGORY_NAME, HR_CATEGORY_NAME, _hod_category_overwrites

    assert HR_CATEGORY_NAME == "hr"
    assert HOD_CATEGORY_NAME == "hod"

    class Role:
        def __init__(self, rid, name):
            self.id = rid
            self.name = name

    everyone = Role(1, "@everyone")
    hr = Role(20, "HR")
    cs = Role(21, "CS HOD")
    bi = Role(22, "BI HOD")

    class Guild:
        default_role = everyone
        me = None
        roles = [everyone, hr, cs, bi]

        def get_role(self, rid):
            return {20: hr, 21: cs, 22: bi}.get(int(rid))

    config = {
        "discord": {"tickets": {"adminRoleId": "20", "hodRoleIds": {"CS": "21", "BI": "22"}}},
        "hr": {"hrRoleId": "20"},
    }
    overwrites = _hod_category_overwrites(Guild(), config)
    assert overwrites[hr].view_channel is True
    assert overwrites[cs].view_channel is True
    assert overwrites[bi].view_channel is True


def test_hr_approval_always_finalises_even_with_stale_hod_first_flag():
    """`hod_first` is kept on the signature for old callers, but it can no
    longer create an intermediate stage: every request is PENDING_HR, so
    HR/Admin approval always finalises immediately."""
    from app.hr.leave_status import HR, APPROVED

    hr = make_hr(two_step_config())
    hr.client.table("employees").records[0]["fields"]["Department"] = "BI"
    created = hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="940",
        leave_type_name="Annual Leave",
        start_date=MON,
        end_date=MON,
        role_names=["Staff", "BI Member"],
    )
    saved = hr.leave.decide_request(
        created,
        actor_id="333",
        actor_name="HR Person",
        tier=HR,
        decision="approve",
        hod_first=True,
    )
    assert saved["finalised"] is True
    assert saved["status"] == APPROVED


def test_ticket_overwrites_let_hr_read_and_reply():
    from app.discord.tickets import ticket_overwrites

    class Role:
        def __init__(self, rid, name):
            self.id = rid
            self.name = name

    hr = Role(16, "HR")
    cs = Role(11, "CS HOD")
    staff = Role(14, "Staff")
    everyone = Role(1, "@everyone")

    class Guild:
        default_role = everyone
        roles = [everyone, cs, staff, hr]

        def get_role(self, rid):
            return {11: cs, 14: staff, 16: hr}.get(int(rid))

    overwrites = ticket_overwrites(
        guild=Guild(), user=None, bot=None, staff_role_id="14", admin_role_id=None,
        hr_role_id="16", hod_role_ids=["11"],
    )
    assert overwrites[hr].view_channel is True
    assert overwrites[hr].send_messages is True
    assert overwrites[cs].view_channel is False
    assert overwrites[staff].view_channel is False
    assert overwrites[everyone].view_channel is False

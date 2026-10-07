"""Onboarding profile fields, birthday/name lookups, and form validation."""

from datetime import date

from tests.test_hr import make_hr


def test_upsert_staff_employee_writes_profile_fields():
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    upsert_staff_employee(
        hr.client,
        discord_id="555",
        name="New Joiner",
        username="newjoiner",
        kind="BI",
        role_names=["BI"],
        cnic="12345-1234567-1",
        dob="1998-05-20",
        contact_number="03001234567",
        address="123 Main Street",
        email="new.joiner@example.com",
        designation="Software Engineer",
        photo_path="data/employee-photos/555.jpg",
    )
    record = next(
        item for item in hr.client.table("employees").records if item["fields"]["Discord User ID"] == "555"
    )
    assert record["fields"]["CNIC"] == "12345-1234567-1"
    assert record["fields"]["DOB"] == "1998-05-20"
    assert record["fields"]["Contact Number"] == "03001234567"
    assert record["fields"]["Address"] == "123 Main Street"
    assert record["fields"]["Email"] == "new.joiner@example.com"
    assert record["fields"]["Designation"] == "Software Engineer"
    assert record["fields"]["Photo Path"] == "data/employee-photos/555.jpg"


def test_upsert_staff_employee_skips_quota_when_grant_leave_is_false():
    """Role-driven syncs (join, role change) must not grant a leave quota —
    only the onboarding form does that."""
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    upsert_staff_employee(
        hr.client, discord_id="556", name="Role Synced", kind="BI", role_names=["BI"], grant_leave=False
    )
    record = next(
        item for item in hr.client.table("employees").records if item["fields"]["Discord User ID"] == "556"
    )
    balances = [
        row for row in hr.client.table("leaveBalances").records if row["fields"].get("Employee") == [record["id"]]
    ]
    assert balances == []


def test_upsert_staff_employee_grants_quota_by_default_and_via_onboarding():
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    upsert_staff_employee(
        hr.client, discord_id="557", name="Onboarded", kind="BI", role_names=["BI"], grant_leave=True
    )
    record = next(
        item for item in hr.client.table("employees").records if item["fields"]["Discord User ID"] == "557"
    )
    balances = [
        row for row in hr.client.table("leaveBalances").records if row["fields"].get("Employee") == [record["id"]]
    ]
    assert len(balances) == 3


def test_upsert_staff_employee_leaves_profile_fields_alone_when_empty():
    """Role-sync calls (no onboarding data) must never wipe a saved profile."""
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    upsert_staff_employee(
        hr.client, discord_id="555", name="New Joiner", kind="BI", role_names=["BI"], cnic="12345-1234567-1"
    )
    upsert_staff_employee(hr.client, discord_id="555", name="New Joiner", kind="BI", role_names=["BI"])
    record = next(
        item for item in hr.client.table("employees").records if item["fields"]["Discord User ID"] == "555"
    )
    assert record["fields"]["CNIC"] == "12345-1234567-1"


def test_role_sync_does_not_overwrite_onboarded_employee_name():
    """After onboarding saves the form Full Name, a Discord role change must
    not replace it with the Discord display name — otherwise /profile by
    form name returns 'No profile found'."""
    from app.hr.staff_onboard import upsert_staff_employee

    hr = make_hr()
    upsert_staff_employee(
        hr.client,
        discord_id="7100",
        name="Muhammad Bilal",
        username="bilalchaudhry7",
        kind="BI",
        role_names=["BI Member"],
        cnic="12345-1234567-1",
        dob="2002-09-16",
        grant_leave=True,
    )
    upsert_staff_employee(
        hr.client,
        discord_id="7100",
        name="Bilal chaudhry",
        username="bilalchaudhry7",
        kind="BI",
        role_names=["BI Member"],
        grant_leave=False,
    )
    record = next(
        item for item in hr.client.table("employees").records if item["fields"]["Discord User ID"] == "7100"
    )
    assert record["fields"]["Employee Name"] == "Muhammad Bilal"
    assert record["fields"]["Discord Username"] == "bilalchaudhry7"


def test_list_birthdays_today_matches_month_and_day_only():
    from app.records.employees import list_birthdays_today

    hr = make_hr()
    employees = hr.client.table("employees").records
    employees[0]["fields"]["DOB"] = "1990-06-15"
    employees[1]["fields"]["DOB"] = "1985-06-16"
    matches = list_birthdays_today(hr.client, today=date(2026, 6, 15))
    assert [item["discordUserId"] for item in matches] == ["111"]


def test_list_birthdays_today_skips_inactive():
    from app.records.employees import list_birthdays_today

    hr = make_hr()
    employees = hr.client.table("employees").records
    employees[0]["fields"]["DOB"] = "1990-06-15"
    employees[0]["fields"]["Status"] = "Inactive"
    matches = list_birthdays_today(hr.client, today=date(2026, 6, 15))
    assert matches == []


def test_hr_birthday_cake_embed_includes_name_address_and_contact():
    from datetime import date as date_cls

    from app.discord.announcements import birthday_embed, hr_birthday_cake_embed

    person = {
        "name": "Abdullah",
        "discordUserId": "111",
        "department": "BI",
        "designation": "Analyst",
        "contactNumber": "03001234567",
        "address": "123 Main Street, Karachi",
    }
    embed = hr_birthday_cake_embed(person, birthday_date=date_cls(2026, 6, 16))
    assert "Abdullah" in embed.description
    assert "<@111>" in embed.description
    assert "cake" in embed.description.lower()
    assert "03001234567" in embed.description
    assert "123 Main Street, Karachi" in embed.description
    public = birthday_embed(person)
    assert "03001234567" not in public.description
    assert "123 Main Street" not in public.description


def test_hr_birthday_eve_posts_to_leave_inbox_not_announcements():
    import asyncio
    from datetime import date as date_cls
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from app.discord.announcements import post_hr_birthday_eve_reminders
    from app.logger import create_logger

    class FakeChannel:
        def __init__(self, name):
            self.name = name
            self.sent = []

        async def send(self, **kwargs):
            self.sent.append(kwargs)

    class FakeMember:
        def __init__(self, mid):
            self.id = mid
            self.bot = False

    class FakeRole:
        def __init__(self, rid, members):
            self.id = rid
            self.members = members

    hr_inbox = FakeChannel("leave-requests")
    public = FakeChannel("announcements")
    hr_role = FakeRole(10, [FakeMember(7001), FakeMember(7002)])

    class FakeGuild:
        roles = [SimpleNamespace(id=10, name="HR")]

        def get_channel(self, channel_id):
            return {111: public, 222: hr_inbox}.get(int(channel_id))

        def get_role(self, role_id):
            return hr_role if int(role_id) == 10 else None

    hr = make_hr()
    hr.client.table("employees").records[0]["fields"]["DOB"] = "1990-06-16"
    hr.client.table("employees").records[0]["fields"]["Contact Number"] = "03001234567"
    hr.client.table("employees").records[0]["fields"]["Address"] = "House 9, Lahore"
    bot = SimpleNamespace(
        hr=hr,
        logger=create_logger("error"),
        config={
            "discord": {"tickets": {"announcementChannelId": "111", "leaveReviewChannelId": "222"}},
            "hr": {"hrRoleId": "10"},
        },
    )
    dm = AsyncMock(return_value=True)
    with patch("app.discord.announcements._pakistan_today", return_value=date_cls(2026, 6, 15)):
        with patch("app.discord.notify.dm_member", dm):
            asyncio.run(post_hr_birthday_eve_reminders(bot, FakeGuild()))
    assert public.sent == []
    assert len(hr_inbox.sent) == 1
    embed = hr_inbox.sent[0]["embed"]
    assert "Abdullah" in embed.description
    assert "03001234567" in embed.description
    assert "House 9, Lahore" in embed.description
    assert dm.await_count == 2
    assert {call.args[1] for call in dm.await_args_list} == {"7001", "7002"}


def test_birthday_greeting_posts_at_11am_pakistan_time():
    from datetime import timedelta, timezone, time

    from app.discord.announcements import BIRTHDAY_POST_TIME, PAKISTAN_TZ, _announcement_overwrites

    assert PAKISTAN_TZ == timezone(timedelta(hours=5), name="PKT")
    assert BIRTHDAY_POST_TIME == time(11, 0, tzinfo=timezone(timedelta(hours=5), name="PKT"))

    class Role:
        def __init__(self, rid, name):
            self.id = rid
            self.name = name

    everyone = Role(1, "@everyone")
    hr = Role(10, "HR")
    admin = Role(11, "Admin")

    class Guild:
        default_role = everyone
        me = None
        roles = [everyone, hr, admin]

        def get_role(self, rid):
            return {10: hr, 11: admin}.get(int(rid))

    config = {
        "discord": {"tickets": {"adminRoleId": "11"}},
        "hr": {"hrRoleId": "10", "adminRoleId": "11"},
    }
    overwrites = _announcement_overwrites(Guild(), config)
    assert overwrites[everyone].view_channel is True
    assert overwrites[everyone].send_messages is False
    assert overwrites[hr].send_messages is True
    assert overwrites[admin].send_messages is True


def test_find_employees_by_name_is_case_insensitive_substring():
    from app.records.employees import find_employees_by_name

    hr = make_hr()
    matches = find_employees_by_name(hr.client, "abdul")
    assert [item["discordUserId"] for item in matches] == ["111"]
    assert find_employees_by_name(hr.client, "nobody-like-this") == []


def test_ticket_gate_requires_actual_onboarding_not_just_a_bare_role_synced_row():
    """A role-driven sync row (no CNIC/DOB) must not unlock tickets; only a
    row written by the onboarding form (which always sets CNIC or DOB) does."""
    import asyncio
    from types import SimpleNamespace

    from app.discord.bot import _onboarded_employee
    from app.hr.staff_onboard import upsert_staff_employee
    from app.logger import create_logger

    hr = make_hr()
    upsert_staff_employee(
        hr.client, discord_id="601", name="Role Synced Only", kind="BI", role_names=["BI"], grant_leave=False
    )
    upsert_staff_employee(
        hr.client,
        discord_id="602",
        name="Actually Onboarded",
        kind="BI",
        role_names=["BI"],
        cnic="12345-1234567-1",
        dob="1998-05-20",
        grant_leave=True,
    )
    bot = SimpleNamespace(hr=hr, logger=create_logger("error"))
    assert asyncio.run(_onboarded_employee(bot, "601")) is None
    assert asyncio.run(_onboarded_employee(bot, "602")) is not None
    assert asyncio.run(_onboarded_employee(bot, "999-unknown")) is None


def test_role_change_updates_department_dynamically_without_touching_onboarding_data():
    """When Admin/HR change someone's Discord role, on_member_update ->
    sync_staff_member picks up the new department/HR-role automatically.
    Everything else (onboarding data already on file, granted leave
    balances) must stay exactly as it was — only the role-derived fields
    move."""
    import asyncio
    from types import SimpleNamespace

    from app.discord.bot import _member_roles_changed, sync_staff_member
    from app.hr.staff_onboard import upsert_staff_employee
    from app.logger import create_logger

    hr = make_hr()
    logger = create_logger("error")
    # This person already completed onboarding: CNIC/DOB on file and a
    # granted leave quota, while holding a plain department role.
    upsert_staff_employee(
        hr.client,
        discord_id="7010",
        name="Hina",
        kind="BI",
        role_names=["BI Member"],
        cnic="12345-1234567-1",
        dob="1997-03-10",
        grant_leave=True,
    )

    config = {
        "discord": {"tickets": {"staffRoleId": "", "adminRoleId": ""}},
        "hr": {"hrRoleId": "", "adminRoleId": ""},
    }

    def make_role(role_id, name):
        return SimpleNamespace(id=role_id, name=name)

    guild = SimpleNamespace(id="1", roles=[make_role("1", "BI Member"), make_role("2", "Marketing HOD")])
    before = SimpleNamespace(
        id=7010, bot=False, guild=guild, name="hina", display_name="Hina",
        joined_at=None, roles=[make_role("1", "BI Member")],
    )
    # Admin/HR promote this person: BI Member -> Marketing HOD.
    after = SimpleNamespace(
        id=7010, bot=False, guild=guild, name="hina", display_name="Hina",
        joined_at=None, roles=[make_role("2", "Marketing HOD")],
    )

    assert _member_roles_changed(before, after, config) is True

    bot = SimpleNamespace(hr=hr, logger=logger, config=config, _staff_syncing=set())
    asyncio.run(sync_staff_member(bot, after, reason="role"))

    record = next(
        item for item in hr.client.table("employees").records if item["fields"]["Discord User ID"] == "7010"
    )
    # The role dynamically flipped from BI Member to Marketing HOD.
    assert record["fields"]["Department"] == "Marketing"
    assert record["fields"]["HR Role"] == "HOD"
    # Onboarding-only fields survive a role-driven sync untouched.
    assert record["fields"]["CNIC"] == "12345-1234567-1"
    assert record["fields"]["DOB"] == "1997-03-10"
    # No second quota is granted just because the role changed.
    balances = [
        row for row in hr.client.table("leaveBalances").records
        if row["fields"].get("Employee") == [record["id"]]
    ]
    assert len(balances) == 3


def test_finalize_onboarding_assigns_the_exact_server_role_names():
    """Onboarding always assigns '<Department> Member' (or HR). HOD is not
    chosen on the form. A typed designation becomes '<Department> · title'."""
    import asyncio
    from types import SimpleNamespace

    from app.discord.onboarding import _finalize_onboarding
    from app.logger import create_logger

    class FakeRole:
        def __init__(self, name):
            self.name = name

    class FakeMember:
        def __init__(self, roles, discord_id=9001):
            self.id = discord_id
            self.name = "newperson"
            self.joined_at = None
            self.roles = roles
            self.added = []

        async def add_roles(self, *roles, reason=""):
            del reason
            for role in roles:
                self.roles = self.roles + [role]
                self.added.append(role.name)

    class FakeResponse:
        def __init__(self, interaction):
            self._interaction = interaction
            self.sent = None
            self.deferred = False

        def is_done(self):
            return self.sent is not None or self.deferred

        async def defer(self, ephemeral=False):
            del ephemeral
            self.deferred = True

        async def send_message(self, content=None, **kwargs):
            self.sent = {"content": content, **kwargs}

        async def edit_message(self, content=None, **kwargs):
            self.sent = {"content": content, **kwargs}

    class FakeFollowup:
        def __init__(self, response):
            self._response = response

        async def send(self, content=None, **kwargs):
            self._response.sent = {"content": content, **kwargs}

    class FakeInteraction:
        def __init__(self, guild, member):
            self.guild = guild
            self.user = member
            self.message = None
            self.response = FakeResponse(self)
            self.followup = FakeFollowup(self.response)

        async def edit_original_response(self, content=None, **kwargs):
            self.response.sent = {"content": content, **kwargs}

    class FakeGuild:
        def __init__(self, roles):
            self.roles = list(roles)
            self.text_channels = []
            self.me = None

        async def create_role(self, name, reason=""):
            del reason
            role = FakeRole(name)
            self.roles.append(role)
            return role

        def get_channel(self, channel_id):
            del channel_id
            return None

    profile = {
        "full_name": "New Person",
        "cnic": "12345-1234567-1",
        "dob": "1998-05-20",
        "contact_number": "03001234567",
        "address": "123 Main Street",
        "email": "new.person@example.com",
        "designation": "Account Executive",
    }

    guild = FakeGuild([
        FakeRole("HR"),
        FakeRole("BI Member"),
        FakeRole("CS Member"),
        FakeRole("Sales Member"),
        FakeRole("Marketing Member"),
        FakeRole("CS HOD"),
        FakeRole("Marketing HOD"),
        FakeRole("BI HOD"),
    ])

    hr = make_hr()
    bot = SimpleNamespace(
        hr=hr,
        logger=create_logger("error"),
        config={"discord": {"tickets": {}}, "hr": {}},
    )

    member = FakeMember(roles=[])
    interaction = FakeInteraction(guild, member)
    asyncio.run(_finalize_onboarding(interaction, bot, profile, department="Sales"))
    assert member.added == ["Sales Member", "Sales · Account Executive"]
    assert "Welcome," in interaction.response.sent["content"]
    assert "Sales Member" in interaction.response.sent["content"]
    sales_record = next(
        item for item in hr.client.table("employees").records if item["fields"]["Discord User ID"] == "9001"
    )
    assert sales_record["fields"]["HR Role"] == "Member"
    assert sales_record["fields"]["Designation"] == "Account Executive"

    # Typed title never grants HOD; HR/Admin assign HOD later.
    hod_profile = dict(profile, cnic="12345-1234567-2", designation="Team Lead")
    hod_member = FakeMember(roles=[], discord_id=9002)
    hod_interaction = FakeInteraction(guild, hod_member)
    asyncio.run(_finalize_onboarding(hod_interaction, bot, hod_profile, department="BI"))
    assert hod_member.added[0] == "BI Member"
    assert "BI · Team Lead" in hod_member.added
    bi_record = next(
        item for item in hr.client.table("employees").records if item["fields"]["Discord User ID"] == "9002"
    )
    assert bi_record["fields"]["HR Role"] == "Member"

    hr_profile = dict(profile, cnic="12345-1234567-3", designation="HR Executive")
    hr_member = FakeMember(roles=[], discord_id=9003)
    hr_interaction = FakeInteraction(guild, hr_member)
    asyncio.run(_finalize_onboarding(hr_interaction, bot, hr_profile, department="HR"))
    assert hr_member.added[0] == "HR"
    hr_record = next(
        item for item in hr.client.table("employees").records if item["fields"]["Discord User ID"] == "9003"
    )
    assert hr_record["fields"]["HR Role"] == "HR"
    assert hr_record["fields"]["Department"] == "HR"
    assert hr_record["fields"]["Designation"] == "HR Executive"


def test_welcome_onboard_embed_mentions_person_and_role():
    from app.discord.announcements import welcome_onboard_embed

    embed = welcome_onboard_embed(
        {"full_name": "New Person", "designation": "Account Executive"},
        discord_user_id="9001",
        role_name="Sales Member",
    )
    assert embed.title == "Welcome to the team"
    assert "<@9001>" in embed.description
    assert "New Person" in embed.description
    assert "Sales Member" in embed.description
    assert "Account Executive" in embed.description


def test_finalize_onboarding_posts_welcome_in_announcements():
    import asyncio
    from types import SimpleNamespace

    from app.discord.onboarding import _finalize_onboarding
    from app.logger import create_logger

    class FakeRole:
        _next_id = 1

        def __init__(self, name):
            self.id = FakeRole._next_id
            FakeRole._next_id += 1
            self.name = name

    class FakeMember:
        def __init__(self):
            self.id = 9001
            self.name = "newperson"
            self.joined_at = None
            self.roles = []
            self.added = []

        async def add_roles(self, *roles, reason=""):
            del reason
            for role in roles:
                self.roles = self.roles + [role]
                self.added.append(role.name)

    class FakeChannel:
        def __init__(self):
            self.id = 111
            self.name = "announcements"
            self.sent = []

        async def send(self, **kwargs):
            self.sent.append(kwargs)

        async def edit(self, **kwargs):
            del kwargs

    class FakeGuild:
        def __init__(self, roles, channel):
            self.roles = list(roles)
            self.default_role = FakeRole("@everyone")
            self._channel = channel
            self.text_channels = [channel]
            self.me = None

        def get_channel(self, channel_id):
            if int(channel_id) == int(self._channel.id):
                return self._channel
            return None

        def get_role(self, role_id):
            for role in self.roles:
                if int(role.id) == int(role_id):
                    return role
            return None

        async def create_role(self, name, reason=""):
            del reason
            role = FakeRole(name)
            self.roles.append(role)
            return role

    class FakeResponse:
        def __init__(self):
            self.sent = None
            self.deferred = False

        def is_done(self):
            return self.sent is not None or self.deferred

        async def defer(self, ephemeral=False):
            del ephemeral
            self.deferred = True

        async def send_message(self, content=None, **kwargs):
            self.sent = {"content": content, **kwargs}

    class FakeFollowup:
        def __init__(self, response):
            self._response = response

        async def send(self, content=None, **kwargs):
            self._response.sent = {"content": content, **kwargs}

    channel = FakeChannel()
    guild = FakeGuild([FakeRole("Sales Member")], channel)
    member = FakeMember()
    bot = SimpleNamespace(
        hr=make_hr(),
        logger=create_logger("error"),
        config={"discord": {"tickets": {"announcementChannelId": "111"}}, "hr": {}, "rootDir": None},
    )
    response = FakeResponse()

    async def edit_original_response(content=None, **kwargs):
        response.sent = {"content": content, **kwargs}

    interaction = SimpleNamespace(
        guild=guild,
        user=member,
        message=None,
        response=response,
        followup=FakeFollowup(response),
        edit_original_response=edit_original_response,
    )
    profile = {
        "full_name": "New Person",
        "cnic": "12345-1234567-1",
        "dob": "1998-05-20",
        "contact_number": "03001234567",
        "address": "123 Main Street",
        "email": "new.person@example.com",
        "designation": "Account Executive",
    }
    asyncio.run(_finalize_onboarding(interaction, bot, profile, department="Sales"))
    assert len(channel.sent) == 1
    assert "New teammate" in (channel.sent[0].get("content") or "")
    embed = channel.sent[0]["embed"]
    assert "<@9001>" in embed.description
    assert "Sales Member" in embed.description
    assert "Account Executive" in embed.description


def test_department_dropdown_offers_hr_alongside_departments():
    """The onboarding department dropdown must let people self-onboard as
    HR as well as BI/CS/Sales/Marketing. Level (Member/HOD) is not on the form."""
    from app.discord.onboarding import DEPARTMENT_OPTIONS, DepartmentSelect

    assert "HR" in DEPARTMENT_OPTIONS
    select = DepartmentSelect(bot=None, profile={})
    labels = {option.label for option in select.options}
    assert labels == {"BI", "CS", "Sales", "Marketing", "HR"}


def test_onboarding_channel_hides_workplace_roles_keeps_hr():
    from app.discord.onboarding import _is_onboarded_workplace_role, _onboarding_overwrites

    assert _is_onboarded_workplace_role("BI Member") is True
    assert _is_onboarded_workplace_role("CS HOD") is True
    assert _is_onboarded_workplace_role("HR") is False
    assert _is_onboarded_workplace_role("Admin") is False

    class Role:
        def __init__(self, rid, name):
            self.id = rid
            self.name = name

    everyone = Role(1, "@everyone")
    hr = Role(10, "HR")
    bi = Role(11, "BI Member")
    hod = Role(12, "BI HOD")

    class Guild:
        default_role = everyone
        me = None
        roles = [everyone, hr, bi, hod]

        def get_role(self, rid):
            return {10: hr, 11: bi, 12: hod}.get(int(rid))

    config = {
        "discord": {"tickets": {"adminRoleId": "", "staffRoleId": ""}},
        "hr": {"hrRoleId": "10", "adminRoleId": ""},
    }
    overwrites = _onboarding_overwrites(Guild(), config)
    assert overwrites[everyone].view_channel is True
    assert overwrites[bi].view_channel is False
    assert overwrites[hod].view_channel is False
    assert overwrites[hr].view_channel is True


def test_profile_pii_requests_are_refused_outside_hr_profiles():
    from app.agent.router import AgentRouter
    from app.routing.scope import is_profile_pii_request, profile_privacy_reply

    assert is_profile_pii_request("what is my CNIC?") is True
    assert is_profile_pii_request("show me their address") is True
    assert is_profile_pii_request("I want leave tomorrow") is False
    assert "private" in profile_privacy_reply("cnic", "english").lower()

    router = AgentRouter(config={"hr": {}}, logger=None, rag=None, hr=object())
    result = router.handle(
        question="what is my CNIC number?",
        namespace="web airy",
        channel_id="1",
        discord_user_id="1",
        identity={},
        conversation_history=[],
    )
    assert result.get("ui") == "profile_privacy"
    assert "private" in result["answer"].lower() or "hr profiles" in result["answer"].lower()


def test_hr_can_update_employee_profile_contact_fields():
    from app.records.employees import update_employee_profile

    hr = make_hr()
    employee = next(item for item in hr.client.table("employees").records if item["id"] == "recEmp1")
    updated = update_employee_profile(
        hr.client,
        employee["id"],
        fields={
            "Employee Name": "Abdullah Updated",
            "Email": "abdullah.new@webairy.com",
            "Contact Number": "03009998877",
            "CNIC": "12345-1234567-1",
            "DOB": "1990-01-15",
            "Address": "New street 1",
        },
    )
    assert updated["name"] == "Abdullah Updated"
    assert updated["email"] == "abdullah.new@webairy.com"
    assert updated["contactNumber"] == "03009998877"
    assert updated["cnic"] == "12345-1234567-1"
    assert updated["dob"] == "1990-01-15"
    assert updated["address"] == "New street 1"
    # Department / Discord link must stay untouched.
    assert updated["discordUserId"] == "111"
    assert updated["department"] == employee["fields"]["Department"]


def test_profile_edit_modal_prefills_current_values():
    from app.discord.profile_lookup import ProfileEditModalOne, ProfileEditModalTwo, profile_embed

    employee = {
        "id": "rec1",
        "name": "Muhammad Bilal",
        "email": "muhammad.bilal@webairy.com",
        "contactNumber": "03043203347",
        "cnic": "45402-8490685-1",
        "dob": "2002-09-16",
        "address": "model colony",
        "discordUserId": "980548748725866516",
        "employeeId": "EMP-6516",
        "department": "BI",
        "hrRole": "Member",
        "status": "Active",
        "designation": "Software Engineer",
    }
    one = ProfileEditModalOne(object(), employee)
    assert one.full_name.default == "Muhammad Bilal"
    assert one.contact_number.default == "03043203347"
    assert one.cnic.default == "45402-8490685-1"
    two = ProfileEditModalTwo(object(), employee)
    assert two.email.default == "muhammad.bilal@webairy.com"
    assert two.dob.default == "2002-09-16"
    assert two.address.default == "model colony"
    assert two.designation.default == "Software Engineer"
    embed = profile_embed(employee)
    assert "Edit" in (embed.footer.text or "")


def test_delete_employee_profile_wipes_related_leave_rows():
    from app.records.employees import delete_employee_profile, record_to_employee
    from tests.test_hr import make_hr

    hr = make_hr()
    client = hr.client
    # Seed leave rows linked to Abdullah (recEmp1 / Discord 111).
    client.table("leaveBalances").create({
        "Name": "Abdullah Annual",
        "Employee": ["recEmp1"],
        "Leave Type": ["recType1"],
        "Year": 2026,
        "Total Entitlement": 14,
        "Used": 2,
    })
    client.table("leaveRequests").create({
        "Request ID": "LR-DEL-1",
        "Employee": ["recEmp1"],
        "Discord User ID": "111",
        "Leave Type": ["recType1"],
        "Start Date": "2026-04-01",
        "End Date": "2026-04-01",
        "Days Requested": 1,
        "Status": "APPROVED",
    })
    client.table("leaveUtilization").create({
        "Record Name": "Abdullah 2026-04-01",
        "Employee": ["recEmp1"],
        "Leave Type": ["recType1"],
        "Leave Request": ["recReqDel"],
        "Date": "2026-04-01",
        "Status": "APPROVED",
    })
    employee = record_to_employee(
        next(item for item in client.table("employees").records if item["id"] == "recEmp1")
    )
    summary = delete_employee_profile(client, employee)
    assert summary["employees"] == 1
    assert summary["leaveBalances"] >= 1
    assert summary["leaveRequests"] == 1
    assert summary["leaveUtilization"] == 1
    assert all(item["id"] != "recEmp1" for item in client.table("employees").records)
    assert not any(
        "recEmp1" in (item["fields"].get("Employee") or [])
        for item in client.table("leaveRequests").records
    )
    # Other employees untouched.
    assert any(item["id"] == "recEmp2" for item in client.table("employees").records)


def test_deleteprofile_command_is_registered():
    import inspect
    from app.discord import bot as bot_module

    source = inspect.getsource(bot_module.SupportBot.setup_hook)
    assert "deleteprofile_command" in source
    assert bot_module.deleteprofile_command.name == "deleteprofile"


def test_onboarding_step_one_validation():
    from app.discord.onboarding import _validate_step_one, _validate_step_two

    ok = _validate_step_one("Jane Doe", "03001234567", "12345-1234567-1")
    assert ok == []

    errors = _validate_step_one("", "abc", "not-a-cnic")
    assert any("Full Name" in item for item in errors)
    assert any("CNIC" in item for item in errors)
    assert any("Contact Number" in item for item in errors)

    ok2 = _validate_step_two("jane@example.com", "1995-01-01", "Street 1")
    assert ok2 == []
    errors2 = _validate_step_two("not-an-email", "not-a-date", "")
    assert any("Email" in item for item in errors2)
    assert any("Date of Birth" in item for item in errors2)
    assert any("Address" in item for item in errors2)


def test_onboarding_step_one_accepts_cnic_without_dashes():
    from app.discord.onboarding import _validate_step_one

    errors = _validate_step_one("Jane Doe", "03001234567", "1234512345671")
    assert errors == []


class _FakeResponse:
    def __init__(self):
        self.sent_modal = None
        self.sent_message = None

    async def send_modal(self, modal):
        self.sent_modal = modal

    async def send_message(self, *args, **kwargs):
        self.sent_message = {"args": args, "kwargs": kwargs}


class _FakeUser:
    def __init__(self, user_id="999"):
        self.id = int(user_id)


class _FakeInteraction:
    def __init__(self, user_id="999"):
        self.response = _FakeResponse()
        self.user = _FakeUser(user_id)


def test_onboarding_step_one_never_chains_directly_into_a_modal():
    """Discord's API rejects responding to a modal_submit interaction with
    another modal (only a message/component response is allowed there).
    Step 1's on_submit must reply with a message + Continue button, never
    with send_modal directly, or the client shows its own silent
    'Something went wrong. Try again.' banner and the flow gets stuck."""
    import asyncio

    import discord

    from app.discord.onboarding import OnboardingModalOne

    class Bot:
        pass

    bot = Bot()
    modal = OnboardingModalOne(bot=bot)
    modal.full_name._value = "Jane Doe"
    modal.contact_number._value = "03001234567"
    modal.cnic._value = "12345-1234567-1"

    interaction = _FakeInteraction()
    asyncio.run(modal.on_submit(interaction))

    assert interaction.response.sent_modal is None
    assert interaction.response.sent_message is not None
    view = interaction.response.sent_message["kwargs"].get("view")
    assert view is not None
    assert any(isinstance(item, discord.ui.Button) and item.label == "Continue" for item in view.children)


def test_onboarding_modal_prefills_draft_values():
    from app.discord.onboarding import OnboardingModalOne, OnboardingModalTwo

    draft = {
        "full_name": "Jane Doe",
        "cnic": "12345-1234567-1",
        "dob": "1995-01-01",
        "contact_number": "03001234567",
        "email": "jane@example.com",
        "address": "Model Town",
    }
    one = OnboardingModalOne(bot=object(), draft=draft)
    assert one.full_name.default == "Jane Doe"
    assert one.contact_number.default == "03001234567"
    assert one.cnic.default == "12345-1234567-1"
    two = OnboardingModalTwo(bot=object(), profile=draft)
    assert two.email.default == "jane@example.com"
    assert two.dob.default == "1995-01-01"
    assert two.address.default == "Model Town"


def test_onboarding_validation_error_keeps_draft_for_edit():
    import asyncio

    import discord

    from app.discord.onboarding import OnboardingModalOne, _load_draft

    class Bot:
        pass

    bot = Bot()
    modal = OnboardingModalOne(bot=bot)
    modal.full_name._value = "Jane Doe"
    modal.contact_number._value = "03001234567"
    modal.cnic._value = "bad-cnic"

    interaction = _FakeInteraction("4242")
    asyncio.run(modal.on_submit(interaction))

    assert interaction.response.sent_message is not None
    content = interaction.response.sent_message["args"][0]
    assert "Edit & try again" in content or "kept" in content.lower()
    view = interaction.response.sent_message["kwargs"].get("view")
    assert any(isinstance(item, discord.ui.Button) and "Edit" in (item.label or "") for item in view.children)
    draft = _load_draft(bot, "4242")
    assert draft["full_name"] == "Jane Doe"
    assert draft["cnic"] == "bad-cnic"
    assert draft["contact_number"] == "03001234567"


def test_hr_with_role_synced_row_can_still_onboard_and_gets_leave():
    """HR is often given the HR role before onboarding, so role sync writes a
    bare row. That row must not count as onboarded; finishing the form as HR
    fills the profile and grants the leave quota."""
    import asyncio
    from types import SimpleNamespace

    from app.discord.onboarding import _finalize_onboarding
    from app.hr.staff_onboard import upsert_staff_employee
    from app.logger import create_logger
    from app.records.employees import completed_onboarding, lookup_employee_by_discord_id

    class FakeRole:
        def __init__(self, name):
            self.name = name

    hr_role = FakeRole("HR")

    class FakeMember:
        id = 9100
        name = "hrperson"
        joined_at = None
        roles = [hr_role]

        async def add_roles(self, role, reason=""):
            del role, reason

    class FakeResponse:
        sent = None
        deferred = False

        def is_done(self):
            return self.deferred or self.sent is not None

        async def defer(self, ephemeral=False):
            del ephemeral
            self.deferred = True

        async def edit_message(self, **kwargs):
            self.sent = kwargs

        async def send_message(self, content=None, **kwargs):
            self.sent = {"content": content, **kwargs}

    hr = make_hr()
    upsert_staff_employee(
        hr.client, discord_id="9100", name="hrperson", kind="HR", role_names=["HR"], grant_leave=False
    )
    assert not completed_onboarding(lookup_employee_by_discord_id(hr.client, "9100"))

    response = FakeResponse()

    async def edit_original_response(content=None, **kwargs):
        response.sent = {"content": content, **kwargs}

    interaction = SimpleNamespace(
        guild=SimpleNamespace(roles=[hr_role], text_channels=[], me=None),
        user=FakeMember(),
        message=None,
        response=response,
        followup=SimpleNamespace(send=edit_original_response),
        edit_original_response=edit_original_response,
    )
    bot = SimpleNamespace(
        hr=hr,
        logger=create_logger("error"),
        config={"discord": {"tickets": {}}, "hr": {}},
    )
    profile = {
        "full_name": "HR Person",
        "cnic": "12345-1234567-9",
        "dob": "1990-01-01",
        "contact_number": "03001234567",
        "address": "1 Office Road",
        "email": "hr.person@example.com",
    }
    asyncio.run(_finalize_onboarding(interaction, bot, profile, department="HR"))

    employee = lookup_employee_by_discord_id(hr.client, "9100")
    assert completed_onboarding(employee)
    assert employee["name"] == "HR Person"
    record = next(
        item for item in hr.client.table("employees").records if item["fields"]["Discord User ID"] == "9100"
    )
    balances = [
        row for row in hr.client.table("leaveBalances").records if row["fields"].get("Employee") == [record["id"]]
    ]
    assert len(balances) == 3


def test_roles_to_strip_after_profile_delete_keeps_hr_admin():
    from types import SimpleNamespace

    from app.discord.onboarding import roles_to_strip_after_profile_delete

    member = SimpleNamespace(
        roles=[
            SimpleNamespace(name="@everyone"),
            SimpleNamespace(name="BI Member"),
            SimpleNamespace(name="BI · Analyst"),
            SimpleNamespace(name="HR"),
            SimpleNamespace(name="Admin"),
        ]
    )
    stripped = [role.name for role in roles_to_strip_after_profile_delete(member)]
    assert stripped == ["BI Member", "BI · Analyst"]


def test_restore_onboarding_access_clears_member_overwrite():
    import asyncio
    from types import SimpleNamespace

    from app.discord.onboarding import restore_onboarding_access

    calls = []

    class FakeChannel:
        id = 55

        async def set_permissions(self, target, **kwargs):
            calls.append((target.id, kwargs))

    member = SimpleNamespace(id=111, bot=False, guild=SimpleNamespace())
    channel = FakeChannel()
    member.guild.get_channel = lambda _cid: channel
    bot = SimpleNamespace(config={"discord": {"tickets": {"onboardingChannelId": "55"}}}, logger=None)

    asyncio.run(restore_onboarding_access(bot, member))
    assert calls == [(111, {"overwrite": None, "reason": "Profile deleted — onboarding required again"})]


def test_ensure_new_joiner_sees_onboarding_when_profile_missing():
    import asyncio
    from types import SimpleNamespace

    from app.discord.onboarding import ensure_new_joiner_sees_onboarding
    from tests.test_hr import make_hr

    calls = []

    class FakeChannel:
        async def set_permissions(self, target, **kwargs):
            calls.append(kwargs)

    member = SimpleNamespace(id=4242, bot=False, guild=SimpleNamespace())
    channel = FakeChannel()
    member.guild.get_channel = lambda _cid: channel
    bot = SimpleNamespace(
        hr=make_hr(),
        logger=None,
        config={"discord": {"tickets": {"onboardingChannelId": "55"}}},
    )
    asyncio.run(ensure_new_joiner_sees_onboarding(bot, member))
    assert calls and calls[0].get("overwrite") is None


def test_ensure_new_joiner_skips_when_already_onboarded():
    import asyncio
    from types import SimpleNamespace

    from app.discord.onboarding import ensure_new_joiner_sees_onboarding
    from tests.test_hr import make_hr

    calls = []

    class FakeChannel:
        async def set_permissions(self, target, **kwargs):
            calls.append(kwargs)

    hr = make_hr()
    # completed_onboarding requires CNIC or DOB — bare sync rows must still see #onboarding.
    for row in hr.client.table("employees").records:
        if row["id"] == "recEmp1":
            row["fields"]["CNIC"] = "12345-1234567-1"
            row["fields"]["DOB"] = "1990-01-01"
    member = SimpleNamespace(id=111, bot=False, guild=SimpleNamespace())
    channel = FakeChannel()
    member.guild.get_channel = lambda _cid: channel
    bot = SimpleNamespace(
        hr=hr,
        logger=None,
        config={"discord": {"tickets": {"onboardingChannelId": "55"}}},
    )
    asyncio.run(ensure_new_joiner_sees_onboarding(bot, member))
    assert calls == []


def test_execute_profile_delete_restores_onboarding_and_wipes_disk_photo(tmp_path):
    import asyncio
    from types import SimpleNamespace

    from app.discord.profile_lookup import _execute_profile_delete
    from app.records.employees import lookup_employee_by_discord_id, record_to_employee
    from tests.test_hr import make_hr

    hr = make_hr()
    employee = record_to_employee(
        next(item for item in hr.client.table("employees").records if item["id"] == "recEmp1")
    )
    photo = tmp_path / "employees" / "photos" / "111.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"fake-photo")
    employee["photoPath"] = "employees/photos/111.jpg"

    removed_roles = []
    permission_calls = []
    kicked = []
    designation = "BI" + " \u00b7 " + "Analyst"

    class FakeRole:
        def __init__(self, name):
            self.name = name

    class FakeMember:
        id = 111
        bot = False
        roles = [FakeRole("@everyone"), FakeRole("BI Member"), FakeRole(designation), FakeRole("HR")]

        async def remove_roles(self, *roles, reason=None):
            removed_roles.extend(role.name for role in roles)
            self.roles = [role for role in self.roles if role not in roles]

        async def kick(self, reason=None):
            kicked.append(reason)

    class FakeChannel:
        async def set_permissions(self, target, **kwargs):
            permission_calls.append(kwargs)

    guild = SimpleNamespace()
    member = FakeMember()
    channel = FakeChannel()
    guild.get_member = lambda _uid: member
    guild.get_channel = lambda _cid: channel
    member.guild = guild

    class FakeLogger:
        def info(self, *a, **k):
            pass

        def warn(self, *a, **k):
            pass

        def error(self, *a, **k):
            pass

    bot = SimpleNamespace(
        hr=hr,
        logger=FakeLogger(),
        config={
            "rootDir": str(tmp_path),
            "discord": {"tickets": {"onboardingChannelId": "55"}},
        },
        _onboarding_drafts={"111": {"full_name": "Abdullah"}},
    )
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=999, __str__=lambda self: "HR#1"),
        guild=guild,
    )

    message = asyncio.run(_execute_profile_delete(interaction, bot, employee))
    assert "Deleted" in message
    assert kicked
    assert "BI Member" in removed_roles
    assert designation in removed_roles
    assert "HR" not in removed_roles
    assert permission_calls and permission_calls[0].get("overwrite") is None
    assert not photo.exists()
    assert "111" not in bot._onboarding_drafts
    assert all(item["id"] != "recEmp1" for item in hr.client.table("employees").records)
    assert lookup_employee_by_discord_id(hr.client, "111") is None

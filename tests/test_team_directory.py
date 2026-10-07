from types import SimpleNamespace

from app.discord.team_directory import (
    active_directory_people,
    directory_intro_embed,
    parse_department_roster_query,
    person_directory_embed,
)


def test_active_directory_people_skips_inactive_and_sorts():
    people = active_directory_people([
        {"name": "Zara", "department": "CS", "active": True},
        {"name": "Ali", "department": "BI", "active": True},
        {"name": "Old", "department": "BI", "active": False},
        {"name": "Bilal", "department": "BI", "active": True},
    ])
    assert [item["name"] for item in people] == ["Ali", "Bilal", "Zara"]


def test_active_directory_people_filters_department():
    people = active_directory_people(
        [
            {"name": "Zara", "department": "CS", "active": True},
            {"name": "Ali", "department": "BI", "active": True},
            {"name": "Noor", "department": "HR", "active": True},
        ],
        department="BI",
    )
    assert [item["name"] for item in people] == ["Ali"]


def test_active_directory_people_filters_hr():
    people = active_directory_people(
        [
            {"name": "Ali", "department": "BI", "active": True},
            {"name": "Noor", "department": "HR", "active": True},
        ],
        department="HR",
    )
    assert [item["name"] for item in people] == ["Noor"]


def test_person_directory_embed_has_name_department_designation():
    embed = person_directory_embed(
        {
            "name": "Muhammad Bilal",
            "department": "BI",
            "designation": "Software Engineer",
            "discordUserId": "9001",
        },
        image_filename="9001.jpg",
    )
    assert embed.title == "Muhammad Bilal"
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Department"] == "BI"
    assert fields["Designation"] == "Software Engineer"
    assert "<@9001>" in fields["Discord"]
    assert embed.thumbnail.url.endswith("9001.jpg")


def test_directory_intro_embed_for_department():
    embed = directory_intro_embed(count=3, department="BI")
    assert embed.title == "BI team"
    assert "3 people" in embed.description
    assert "BI" in embed.description


def test_parse_department_roster_query():
    assert parse_department_roster_query("who are in BI") == "BI"
    assert parse_department_roster_query("Who is in cs?") == "CS"
    assert parse_department_roster_query("show marketing team") == "Marketing"
    assert parse_department_roster_query("people in HR") == "HR"
    assert parse_department_roster_query("kon kon hai BI mein") == "BI"
    assert parse_department_roster_query("hello") is None
    assert parse_department_roster_query("who are you") is None
    assert parse_department_roster_query("I need to talk to HR") is None


def test_post_team_directory_skips_without_hr():
    import asyncio
    from app.discord.team_directory import post_team_directory

    sent = []

    class Channel:
        async def send(self, **kwargs):
            sent.append(kwargs)

    bot = SimpleNamespace(hr=None, logger=None, config={})
    asyncio.run(post_team_directory(bot, Channel(), department="BI"))
    assert sent == []

"""On-demand team directory: name, designation, photo for a department."""

import re

import discord

from app.hr.departments import normalize_department
from app.records.employee_photos import resolve_photo_path
from app.records.employees import list_employees

DIRECTORY_BATCH = 8
DIRECTORY_COLOR = 0x0F766E

_ROSTER_DEPARTMENTS = ("BI", "CS", "Marketing", "Sales", "HR")
_ALIAS_TO_DEPT = (
    ("business intelligence", "BI"),
    ("customer success", "CS"),
    ("human resources", "HR"),
    ("human resource", "HR"),
    ("marketing", "Marketing"),
    ("sales", "Sales"),
    ("hr", "HR"),
    ("bi", "BI"),
    ("cs", "CS"),
)
_ROSTER_ASK = re.compile(
    r"\b("
    r"who(?:'s|s| is| are)?|"
    r"people|members?|team|staff|names?|"
    r"list|show|tell|"
    r"kon|kaun"
    r")\b",
    re.I,
)
_BOT_IDENTITY = re.compile(
    r"\b(who are you|who r u|tum kaun ho|aap kaun ho)\b",
    re.I,
)


def parse_department_roster_query(question):
    """Return BI/CS/Marketing/Sales/HR when the user asks who is in that team."""
    text = " ".join(str(question or "").strip().lower().split())
    if not text or len(text) > 200:
        return None
    if _BOT_IDENTITY.search(text):
        return None
    found = ""
    for alias, key in _ALIAS_TO_DEPT:
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text):
            found = key
            break
    if not found:
        return None
    if not _ROSTER_ASK.search(text):
        return None
    return found if found in _ROSTER_DEPARTMENTS else None


def active_directory_people(employees, department=None):
    wanted = normalize_department(department) if department else ""
    if department and not wanted:
        # HR is not in leave DEPARTMENTS; accept exact roster keys.
        raw = str(department or "").strip()
        wanted = raw if raw in _ROSTER_DEPARTMENTS else ""
    people = []
    for item in employees or []:
        if not item or not item.get("active"):
            continue
        if wanted:
            person_dept = normalize_department(item.get("department")) or str(item.get("department") or "").strip()
            if person_dept.casefold() != wanted.casefold():
                continue
        people.append(item)
    people.sort(
        key=lambda item: (
            str(item.get("department") or "zzz").lower(),
            str(item.get("name") or "").lower(),
        )
    )
    return people


def directory_intro_embed(*, count, department="", member_name=""):
    dept = str(department or "").strip()
    if dept:
        if count == 0:
            description = f"I do not have anyone listed in **{dept}** right now."
        elif count == 1:
            description = f"Here is the person currently in **{dept}**."
        else:
            description = f"Here are the {count} people currently in **{dept}**."
        return discord.Embed(
            title=f"{dept} team",
            description=description,
            color=DIRECTORY_COLOR,
        )
    hello = f"Hello {member_name}," if member_name else "Hello,"
    return discord.Embed(
        title="Meet your teammates",
        description=(
            f"{hello} this is everyone currently in the company "
            f"({count} people). Name, department, designation, and photo when we have one."
        ),
        color=DIRECTORY_COLOR,
    )


def person_directory_embed(person, *, image_filename=None):
    name = str((person or {}).get("name") or "Teammate").strip() or "Teammate"
    department = str((person or {}).get("department") or "—").strip() or "—"
    designation = str((person or {}).get("designation") or "—").strip() or "—"
    discord_id = str((person or {}).get("discordUserId") or "").strip()
    embed = discord.Embed(title=name, color=DIRECTORY_COLOR)
    embed.add_field(name="Department", value=department, inline=True)
    embed.add_field(name="Designation", value=designation, inline=True)
    if discord_id.isdigit():
        embed.add_field(name="Discord", value=f"<@{discord_id}>", inline=True)
    if image_filename:
        embed.set_thumbnail(url=f"attachment://{image_filename}")
    return embed


def _chunks(items, size):
    for index in range(0, len(items), size):
        yield items[index:index + size]


async def post_team_directory(bot, channel, *, member_name="", department=None):
    """Post a department roster into a ticket. Never raise to the opener."""
    if bot is None or channel is None or getattr(bot, "hr", None) is None or bot.hr.client is None:
        return
    try:
        import asyncio

        people = await asyncio.to_thread(list_employees, bot.hr.client, logger=getattr(bot, "logger", None))
        people = active_directory_people(people, department=department)
        await channel.send(
            embed=directory_intro_embed(
                count=len(people),
                department=department or "",
                member_name=member_name,
            )
        )
        if not people:
            return
        root = (getattr(bot, "config", None) or {}).get("rootDir")
        for batch in _chunks(people, DIRECTORY_BATCH):
            embeds = []
            files = []
            for person in batch:
                photo = resolve_photo_path(root, person.get("photoPath"))
                filename = None
                if photo is not None:
                    filename = f"{person.get('discordUserId') or 'photo'}{photo.suffix.lower()}"
                    files.append(discord.File(str(photo), filename=filename))
                embeds.append(person_directory_embed(person, image_filename=filename))
            try:
                kwargs = {"embeds": embeds}
                if files:
                    kwargs["files"] = files
                await channel.send(**kwargs)
            except discord.HTTPException:
                await channel.send(embeds=embeds)
    except Exception as error:
        logger = getattr(bot, "logger", None)
        if logger:
            logger.warn("Could not post team directory", {"message": str(error)[:300]})

"""On-demand team directory: name, designation, photo for a department."""

import re

import discord

from app.hr.departments import (
    department_from_role_names,
    hod_department_from_role_names,
    normalize_department,
)
from app.records.employee_photos import resolve_photo_path
from app.records.employees import list_employees, lookup_employee_by_discord_id

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
    r"list|show|tell|display|"
    r"kon|kaun"
    r")\b",
    re.I,
)
# Own department (no named BI/CS/…): "my team", "team members", "mera team", …
_OWN_TEAM_ASK = re.compile(
    r"(?:"
    r"\b(?:what(?:'s| is)|who(?:'s|s| is| are)|show|list|tell(?:\s+me)?|display|share|give)\b"
    r".{0,48}\b(?:my|our|mera|meri|hamara|hamari)\s+"
    r"(?:team|teammates?|department|dept)(?:\s+members?)?\b"
    r"|"
    r"\b(?:my|our|mera|meri|hamara|hamari)\s+"
    r"(?:team|teammates?|department|dept)(?:\s+members?)?\b"
    r"|"
    r"\b(?:team|department)\s+members?\b"
    r"|"
    r"\bteammates?\b"
    r"|"
    r"\bwho\s+works?\s+with\s+me\b"
    r"|"
    r"\b(?:kon|kaun)\s+kon\b.{0,40}\b(?:mera|meri|hamara|hamari)\s+team\b"
    r"|"
    r"\b(?:mera|meri)\s+team\s+(?:kon|kaun|members?|log)\b"
    r")",
    re.I,
)
_HANDOFF_HR = re.compile(
    r"\b(talk|speak|contact|call|ping|bring|baat|bulao|connect)\b.{0,40}\bhr\b"
    r"|\bhr\b.{0,40}\b(talk|speak|baat|bulao)\b",
    re.I,
)
_BOT_IDENTITY = re.compile(
    r"\b(who are you|who r u|tum kaun ho|aap kaun ho)\b",
    re.I,
)


def _named_department(text):
    for alias, key in _ALIAS_TO_DEPT:
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text):
            return key if key in _ROSTER_DEPARTMENTS else ""
    return ""


def resolve_my_department(*, identity=None, hr=None, discord_user_id="", logger=None):
    """Best-effort department for 'my team' from Discord roles, then employee row."""
    roles = list((identity or {}).get("memberRoleNames") or [])
    dept = hod_department_from_role_names(roles) or department_from_role_names(roles)
    if dept in _ROSTER_DEPARTMENTS:
        return dept
    if dept:
        raw = normalize_department(dept) or str(dept).strip()
        if raw in _ROSTER_DEPARTMENTS:
            return raw
    if hr is None or getattr(hr, "client", None) is None or not str(discord_user_id or "").strip():
        return ""
    try:
        person = lookup_employee_by_discord_id(
            hr.client,
            str(discord_user_id),
            logger=logger,
        )
    except Exception:
        person = None
    if not person:
        return ""
    stored = normalize_department(person.get("department")) or str(person.get("department") or "").strip()
    return stored if stored in _ROSTER_DEPARTMENTS else ""


def parse_roster_query(question, *, my_department=""):
    """Detect a team-directory ask.

    Returns None when not a roster question, otherwise:
      {"department": "BI"|"CS"|...} when resolved
      {"department": "", "needDepartment": True} for own-team with unknown dept
    """
    text = " ".join(str(question or "").strip().lower().split())
    if not text or len(text) > 200:
        return None
    if _BOT_IDENTITY.search(text):
        return None
    if _HANDOFF_HR.search(text):
        return None

    named = _named_department(text)
    own = bool(_OWN_TEAM_ASK.search(text))

    if named and (_ROSTER_ASK.search(text) or own):
        return {"department": named, "needDepartment": False}

    if own:
        mine = str(my_department or "").strip()
        if mine in _ROSTER_DEPARTMENTS:
            return {"department": mine, "needDepartment": False}
        return {"department": "", "needDepartment": True}

    return None


def parse_department_roster_query(question, *, my_department=""):
    """Return BI/CS/Marketing/Sales/HR when the roster department is known."""
    parsed = parse_roster_query(question, my_department=my_department)
    if not parsed or parsed.get("needDepartment"):
        return None
    return parsed.get("department") or None


def roster_need_department_reply(question=""):
    """Ask the user to name a department when we cannot infer theirs."""
    from app.routing.language import detect_reply_language, pick_locale_text

    return pick_locale_text(
        detect_reply_language(question),
        english=(
            "I can show your department team — tell me which one: "
            "**BI**, **CS**, **Marketing**, **Sales**, or **HR**. "
            "Example: who is in BI?"
        ),
        roman=(
            "Main aapki department team dikha sakta hoon — kaunsi? "
            "**BI**, **CS**, **Marketing**, **Sales**, ya **HR**. "
            "Example: who is in BI?"
        ),
        urdu=(
            "میں آپ کی ڈیپارٹمنٹ ٹیم دکھا سکتا ہوں — کون سی؟ "
            "**BI**، **CS**، **Marketing**، **Sales**، یا **HR**۔ "
            "مثال: who is in BI?"
        ),
        mix=(
            "Main aapki department team dikha sakta hoon — BI, CS, Marketing, Sales, ya HR? "
            "Example: who is in BI?"
        ),
    )


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

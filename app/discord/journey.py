"""The employee's journey, from the entry channel to a closed ticket.

Everything an employee reads lives here, so the voice stays consistent and the
boundary of the service is stated the same way every time: this is HR support.

The assistant replies in whatever language the employee writes in, but the
cards never say so. Advertising it invites language-testing instead of HR
questions, so the capability stays quiet and simply works.

Cards name the employer, not the Discord server, which is often called
something else entirely.
"""

import discord

from app.routing.language import pick_locale_text
from app.routing.scope import capability_lines

BRAND = "Human Resources"
PANEL_COLOR = 0x4F46E5
WELCOME_COLOR = 0x0F766E
HELP_COLOR = 0x1E293B
CLOSED_COLOR = 0x64748B


def panel_embed():
    """The single card in the entry channel."""
    embed = discord.Embed(
        title="HR Support",
        description="Open a private ticket to talk to the HR assistant.",
        color=PANEL_COLOR,
    )
    embed.set_author(name=BRAND)
    embed.add_field(
        name="What you can ask about",
        value=(
            "• Company policy and workplace rules\n"
            "• Your leave balance, and applying for leave\n"
            "• Speaking to someone from the HR team"
        ),
        inline=False,
    )
    embed.add_field(
        name="Good to know",
        value=(
            "🔒 Only you and the HR team can see your ticket\n"
            "💼 HR and workplace topics only"
        ),
        inline=False,
    )
    embed.set_footer(text="Tap Open ticket to start")
    return embed


def welcome_embed(member_name="", company_name=""):
    """First thing an employee sees inside their new ticket."""
    greeting = f"Hello {member_name}," if member_name else "Hello,"
    embed = discord.Embed(
        title=f"{greeting} how can I help?",
        description="This is your private HR ticket. Ask in your own words.",
        color=WELCOME_COLOR,
    )
    embed.set_author(name=company_name or BRAND)
    embed.add_field(
        name="I can help with",
        value="\n".join(f"• {line}" for line in capability_lines("english")),
        inline=False,
    )
    embed.add_field(
        name="For example",
        value=(
            '• "How many annual leaves do I get?"\n'
            '• "What is my leave balance?"\n'
            '• "Who is in BI / CS / Marketing / HR?"\n'
            '• "I want to apply for sick leave tomorrow"'
        ),
        inline=False,
    )
    embed.set_footer(text="HR and workplace topics only • /help anytime")
    return embed


def help_embed(locale="english"):
    """The same capability list, on demand."""
    embed = discord.Embed(
        title=pick_locale_text(
            locale,
            english="What I can help with",
            roman="Main kis cheez mein madad kar sakta hoon",
            urdu="میں کس چیز میں مدد کر سکتا ہوں",
            mix="What I can help with",
        ),
        description=pick_locale_text(
            locale,
            english="I am the HR assistant for this workplace. Ask in your own words.",
            roman="Main is workplace ka HR assistant hoon. Apne alfaaz mein poochhein.",
            urdu="میں اس ورک پلیس کا HR اسسٹنٹ ہوں۔ اپنے الفاظ میں پوچھیں۔",
            mix="Main is workplace ka HR assistant hoon. Ask in your own words.",
        ),
        color=HELP_COLOR,
    )
    embed.set_author(name=BRAND)
    embed.add_field(
        name=pick_locale_text(
            locale, english="Topics", roman="Topics", urdu="موضوعات", mix="Topics"
        ),
        value="\n".join(f"• {line}" for line in capability_lines(locale)),
        inline=False,
    )
    embed.add_field(
        name=pick_locale_text(
            locale, english="Commands", roman="Commands", urdu="کمانڈز", mix="Commands"
        ),
        value=(
            "`/myleave` — your upcoming leave\n"
            "`/close` — close this ticket"
        ),
        inline=False,
    )
    embed.set_footer(
        text=pick_locale_text(
            locale,
            english="HR and workplace topics only",
            roman="Sirf HR aur workplace ke topics",
            urdu="صرف HR اور ورک پلیس کے موضوعات",
            mix="Sirf HR aur workplace topics",
        )
    )
    return embed


def ticket_intro_text(user_mention):
    """Ping the member; privacy is already on the welcome card."""
    return str(user_mention or "").strip()


def staff_note_text():
    """Kept separate from the welcome so employees are not shown staff mechanics."""
    return "Admin / HR: `/leave` hands the chat to a person, `/close` closes the ticket."


def discord_handle(member):
    """Public Discord username, shown as @handle. Never a snowflake id."""
    if member is None:
        return ""
    if isinstance(member, str):
        text = member.strip()
        if text.startswith("<@") or text.isdigit():
            return ""
        return text if text.startswith("@") else (f"@{text}" if text else "")
    username = str(getattr(member, "name", None) or "").strip()
    if username:
        return f"@{username}"
    nick = str(
        getattr(member, "display_name", None)
        or getattr(member, "global_name", None)
        or ""
    ).strip()
    if nick.startswith("<@") or nick.isdigit():
        return ""
    return f"@{nick}" if nick else ""


def workplace_role_label(member, config=None):
    """Admin, HR, or department HOD — never a personal display name."""
    if member is None:
        return ""
    if isinstance(member, str):
        return member.strip()
    from app.hr.departments import hod_display_name, member_hod_department
    from app.hr.permissions import is_hr_admin, is_hr_member

    config = config or {}
    hr_cfg = config.get("hr") or {}
    tickets = (config.get("discord") or {}).get("tickets") or {}
    admin_id = hr_cfg.get("adminRoleId") or tickets.get("adminRoleId")
    hr_id = hr_cfg.get("hrRoleId")
    staff_id = str(tickets.get("staffRoleId") or "").strip()
    if is_hr_admin(member, admin_id):
        return "Admin"
    if is_hr_member(member, hr_id):
        return "HR"
    dept = member_hod_department(member, config)
    if dept:
        return hod_display_name(dept)
    if staff_id and any(str(getattr(role, "id", "")) == staff_id for role in getattr(member, "roles", []) or []):
        return "Staff"
    return ""


def closer_caption(member, config=None):
    """Name and workplace role for the closed-ticket card. Embed footers cannot ping."""
    if member is None:
        return ""
    if isinstance(member, str):
        return member.strip()
    name = (
        getattr(member, "display_name", None)
        or getattr(member, "global_name", None)
        or getattr(member, "name", None)
        or "Someone"
    )
    role = workplace_role_label(member, config)
    return f"{name} · {role}" if role else str(name)


def closed_embed(closer_id=None, locale="english"):
    embed = discord.Embed(
        title=pick_locale_text(
            locale,
            english="Ticket closed",
            roman="Ticket band ho gaya",
            urdu="ٹکٹ بند ہو گیا",
            mix="Ticket closed",
        ),
        description=pick_locale_text(
            locale,
            english=(
                "Thank you for reaching out. Your messages stay here for reference.\n"
                "Open a new ticket from the HR Support channel whenever you need us again."
            ),
            roman=(
                "Rabta karne ka shukriya. Aapke messages yahin mehfooz rahenge.\n"
                "Jab dobara zarurat ho, HR Support channel se naya ticket khol lein."
            ),
            urdu=(
                "رابطہ کرنے کا شکریہ۔ آپ کے پیغامات یہیں محفوظ رہیں گے۔\n"
                "جب دوبارہ ضرورت ہو، HR سپورٹ چینل سے نیا ٹکٹ کھولیں۔"
            ),
            mix=(
                "Shukriya. Aapke messages yahin rahenge.\n"
                "Jab zarurat ho, HR Support channel se naya ticket khol lein."
            ),
        ),
        color=CLOSED_COLOR,
    )
    embed.set_author(name=BRAND)
    if closer_id:
        embed.add_field(name="Closed by", value=str(closer_id), inline=False)
    return embed

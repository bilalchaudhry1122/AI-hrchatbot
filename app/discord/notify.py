"""Direct messages for leave decisions.

A decision posted only in the ticket is easy to miss, and the ticket may be
closed by then. Every outcome is also sent to the employee directly. A DM can
always fail (closed DMs, left the server), so nothing depends on it.
"""

import discord

from app.hr.dates import format_display_date
from app.hr.leave_status import display_status
from app.routing.language import pick_locale_text

COLORS = {
    "approved": 0x15803D,
    "rejected": 0xB91C1C,
    "withdrawn": 0x64748B,
    "cancelled": 0x92400E,
    "moved": 0x1D4ED8,
}


def _span(request):
    start = format_display_date(request.get("startDate"))
    end = format_display_date(request.get("endDate")) or start
    if start and end and start != end:
        return f"{start} – {end}"
    return start or end or "—"


def _qty(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "—")
    return str(int(number)) if number.is_integer() else str(number)


def decision_embed(request, *, outcome, actor="", locale=None, guild_name=""):
    """One embed describing what happened to a leave request."""
    leave_type = request.get("leaveType") or "Leave"
    if str(leave_type).startswith("rec") and " " not in str(leave_type):
        leave_type = "Leave"
    titles = {
        "approved": pick_locale_text(
            locale,
            english="Your leave was approved",
            roman="Aapki leave approve ho gayi",
            urdu="آپ کی لیو منظور ہو گئی",
            mix="Your leave was approved",
        ),
        "rejected": pick_locale_text(
            locale,
            english="Your leave was not approved",
            roman="Aapki leave approve nahi hui",
            urdu="آپ کی لیو منظور نہیں ہوئی",
            mix="Your leave was not approved",
        ),
        "withdrawn": pick_locale_text(
            locale,
            english="Your leave request was withdrawn",
            roman="Aapki leave request withdraw ho gayi",
            urdu="آپ کی لیو درخواست واپس لے لی گئی",
            mix="Your leave request was withdrawn",
        ),
        "cancelled": pick_locale_text(
            locale,
            english="Your approved leave was cancelled",
            roman="Aapki approved leave cancel ho gayi",
            urdu="آپ کی منظور شدہ لیو منسوخ ہو گئی",
            mix="Your approved leave was cancelled",
        ),
        "moved": pick_locale_text(
            locale,
            english="Your HOD approved your leave",
            roman="HOD ne aapki leave approve kar di",
            urdu="HOD نے آپ کی لیو منظور کر دی",
            mix="Your HOD approved your leave",
        ),
    }
    embed = discord.Embed(
        title=titles.get(outcome, "Leave update"),
        color=COLORS.get(outcome, 0x1E293B),
    )
    embed.set_author(name=guild_name or "Human Resources")
    embed.add_field(name="Leave type", value=f"**{leave_type}**", inline=True)
    embed.add_field(name="Dates", value=_span(request), inline=True)
    embed.add_field(name="Days", value=f"**{_qty(request.get('daysRequested'))}**", inline=True)

    if outcome == "moved":
        embed.add_field(
            name="Next step",
            value=display_status(request.get("status"), locale),
            inline=False,
        )
    if outcome in {"rejected", "cancelled"}:
        from app.discord.attachments import add_attachment_preview, parse_reason_and_files

        note = str(request.get("rejectionReason") or "").strip()
        body, files = parse_reason_and_files(note)
        if body:
            embed.add_field(
                name=pick_locale_text(
                    locale,
                    english="Reason given",
                    roman="Wajah",
                    urdu="وجہ",
                    mix="Reason given",
                ),
                value=body[:1000],
                inline=False,
            )
            add_attachment_preview(embed, files)
        elif files:
            add_attachment_preview(embed, files)
        else:
            # A reason is optional for HR, but silence leaves the employee with
            # nowhere to go. Point them back at the ticket instead.
            embed.add_field(
                name=pick_locale_text(
                    locale,
                    english="No reason was recorded",
                    roman="Koi wajah darj nahi hui",
                    urdu="کوئی وجہ درج نہیں ہوئی",
                    mix="No reason was recorded",
                ),
                value=pick_locale_text(
                    locale,
                    english="You can ask HR about it in your ticket.",
                    roman="Aap apne ticket mein HR se poochh sakte hain.",
                    urdu="آپ اپنے ٹکٹ میں HR سے پوچھ سکتے ہیں۔",
                    mix="Aap apne ticket mein HR se poochh sakte hain.",
                ),
                inline=False,
            )
    if outcome == "approved":
        remaining = request.get("remaining")
        if remaining is not None:
            embed.add_field(name="Remaining balance", value=f"**{_qty(remaining)}**", inline=False)
    if actor:
        embed.set_footer(text=actor)
    return embed


async def _resolve_member(bot, discord_user_id, guild=None):
    try:
        user_id = int(str(discord_user_id).strip())
    except (TypeError, ValueError):
        return None
    if guild is not None:
        member = getattr(guild, "get_member", lambda _id: None)(user_id)
        if member is not None:
            return member
        fetch_member = getattr(guild, "fetch_member", None)
        if callable(fetch_member):
            try:
                return await fetch_member(user_id)
            except discord.HTTPException:
                pass
    user = bot.get_user(user_id)
    if user is not None:
        return user
    try:
        return await bot.fetch_user(user_id)
    except discord.HTTPException:
        return None


async def dm_member(bot, discord_user_id, *, embed=None, content=None, guild=None, files=None):
    """Try to DM someone. Returns True only if it actually sent."""
    user = await _resolve_member(bot, discord_user_id, guild)
    if user is None:
        return False
    try:
        kwargs = {}
        if files:
            kwargs["files"] = files
        await user.send(content=content, embed=embed, **kwargs)
        return True
    except discord.HTTPException:
        # Closed DMs or blocked bot. The ticket mention still carries the news.
        bot.logger.info("Could not DM a leave decision", {"user": str(discord_user_id)})
        return False


def employee_locale(request, locale=None):
    """The language to write to the employee in.

    Nobody records the employee's language, and the person triggering the
    decision is HR, so their message is no guide. The employee's own reason on
    the request is text they wrote themselves, which makes it the best signal
    available without adding a field.
    """
    if locale:
        return locale
    from app.routing.language import detect_reply_language

    written = str(request.get("reason") or "").strip()
    return detect_reply_language(written) if written else "english"


def inbox_line(outcome, locale=None):
    """Short line so the Discord inbox preview is readable, not just an embed."""
    if outcome == "approved":
        return pick_locale_text(
            locale,
            english="Your leave was approved.",
            roman="Aapki leave approve ho gayi.",
            urdu="آپ کی لیو منظور ہو گئی۔",
            mix="Your leave was approved.",
        )
    if outcome == "rejected":
        return pick_locale_text(
            locale,
            english="Your leave was not approved.",
            roman="Aapki leave approve nahi hui.",
            urdu="آپ کی لیو منظور نہیں ہوئی۔",
            mix="Your leave was not approved.",
        )
    if outcome == "cancelled":
        return pick_locale_text(
            locale,
            english="Your approved leave was cancelled.",
            roman="Aapki approved leave cancel ho gayi.",
            urdu="آپ کی منظور شدہ لیو منسوخ ہو گئی۔",
            mix="Your approved leave was cancelled.",
        )
    if outcome == "withdrawn":
        return pick_locale_text(
            locale,
            english="Your leave request was withdrawn.",
            roman="Aapki leave request withdraw ho gayi.",
            urdu="آپ کی لیو درخواست واپس لے لی گئی۔",
            mix="Your leave request was withdrawn.",
        )
    return ""


async def notify_decision(bot, request, *, outcome, actor="", locale=None, guild=None, ticket_channel=None, files=None):
    """Inbox the employee about the decision. Mention them in the ticket if DMs fail."""
    locale = employee_locale(request, locale)
    embed = decision_embed(
        request,
        outcome=outcome,
        actor=actor,
        locale=locale,
        guild_name=getattr(guild, "name", "") or "",
    )
    user_id = str(request.get("discordUserId") or "").strip()
    line = inbox_line(outcome, locale)
    payload = list(files or [])
    sent = await dm_member(bot, user_id, content=line or None, embed=embed, guild=guild, files=payload or None)
    if sent:
        bot.logger.info("Leave decision DM sent", {"user": user_id, "outcome": outcome})
        return True
    channel = ticket_channel
    if channel is not None and user_id:
        mention = f"<@{user_id}>"
        try:
            kwargs = {"content": f"{mention} {line}".strip(), "embed": embed}
            if payload:
                kwargs["files"] = payload
            await channel.send(**kwargs)
            bot.logger.info("Leave decision posted in ticket after DM failed", {
                "user": user_id,
                "outcome": outcome,
            })
            return False
        except discord.HTTPException:
            pass
    return False

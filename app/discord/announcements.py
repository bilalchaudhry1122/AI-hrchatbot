"""Public #announcements channel: birthday greetings + HR broadcasts.

Everyone can read. Only HR, Admin, and the bot can post. A daily task at
11:00 AM Pakistan time posts public birthday greetings here, and the day
before each birthday posts a private cake reminder (address + contact) in
the HR #leave-requests inbox. Completing #onboarding also posts a welcome here.
"""

import datetime

import discord
from discord.ext import tasks

from app.discord.leave_inbox import leave_review_channel_id
from app.records.employees import list_birthdays_today
from app.tickets.helpers import find_admin_role_id, find_hr_role_id

ANNOUNCEMENT_CHANNEL_NAME = "announcements"
# Pakistan Standard Time is UTC+5 year-round (no DST).
PAKISTAN_TZ = datetime.timezone(datetime.timedelta(hours=5), name="PKT")
BIRTHDAY_POST_TIME = datetime.time(hour=11, minute=0, tzinfo=PAKISTAN_TZ)


def _config_channel_id(config):
    tickets = (config.get("discord") or {}).get("tickets") or {}
    return str(tickets.get("announcementChannelId") or "").strip()


def _announcement_overwrites(guild, config):
    roles = [{"id": str(role.id), "name": role.name} for role in guild.roles]
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    hr_cfg = (config or {}).get("hr") or {}
    admin_id = find_admin_role_id(roles, tickets.get("adminRoleId")) or hr_cfg.get("adminRoleId")
    hr_id = hr_cfg.get("hrRoleId") or find_hr_role_id(roles, "")
    read_only = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
    can_post = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    overwrites = {guild.default_role: read_only}
    if guild.me:
        overwrites[guild.me] = can_post
    if admin_id:
        role = guild.get_role(int(admin_id)) if str(admin_id).isdigit() else None
        if role:
            overwrites[role] = can_post
    if hr_id:
        role = guild.get_role(int(hr_id)) if str(hr_id).isdigit() else None
        if role:
            overwrites[role] = can_post
    return overwrites


def _remember_announcement_channel(bot, channel):
    """Keep the channel id in memory and channels.json so welcomes always find it."""
    if bot is None or channel is None:
        return
    channel_id = str(getattr(channel, "id", "") or "").strip()
    if not channel_id.isdigit():
        return
    tickets = ((getattr(bot, "config", None) or {}).get("discord") or {}).get("tickets")
    if isinstance(tickets, dict):
        tickets["announcementChannelId"] = channel_id
    root = (getattr(bot, "config", None) or {}).get("rootDir")
    if not root:
        return
    from pathlib import Path
    import json

    path = Path(root) / "channels.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(data, dict):
            data = {}
        ticket_block = data.get("tickets")
        if not isinstance(ticket_block, dict):
            ticket_block = {}
            data["tickets"] = ticket_block
        if str(ticket_block.get("announcementChannelId") or "") == channel_id:
            return
        ticket_block["announcementChannelId"] = channel_id
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        logger = getattr(bot, "logger", None)
        if logger:
            logger.warn("Could not persist announcement channel id", {"message": str(error)[:200]})


async def ensure_announcement_channel(bot, guild):
    """Find or create #announcements. Everyone reads; HR/Admin/bot can post."""
    configured = _config_channel_id(bot.config)
    channel = None
    if configured.isdigit():
        channel = guild.get_channel(int(configured))
        if channel is None:
            try:
                channel = await guild.fetch_channel(int(configured))
            except discord.HTTPException:
                channel = None
    if channel is None:
        for item in guild.text_channels:
            if str(item.name or "").strip().lower() == ANNOUNCEMENT_CHANNEL_NAME:
                channel = item
                break
    overwrites = _announcement_overwrites(guild, bot.config)
    topic = "Company announcements and birthday greetings. HR can post here."
    try:
        if channel is None:
            channel = await guild.create_text_channel(
                ANNOUNCEMENT_CHANNEL_NAME,
                overwrites=overwrites,
                topic=topic,
                reason="Public announcements and birthday greetings",
            )
            bot.logger.info("Created announcements channel", {"channel": str(channel.id)})
        else:
            await channel.edit(overwrites=overwrites, topic=topic)
    except discord.HTTPException as error:
        bot.logger.warn("Could not prepare announcements channel", {"message": str(error)})
    # Always remember a found/created channel, even when overwrite edit fails.
    if channel is not None:
        _remember_announcement_channel(bot, channel)
    return channel


def welcome_onboard_embed(profile, *, discord_user_id, role_name):
    """Public welcome after a joiner finishes #onboarding."""
    name = (profile or {}).get("full_name") or "a teammate"
    mention = f"<@{discord_user_id}>" if discord_user_id else name
    role_label = str(role_name or "").strip() or "the team"
    designation = str((profile or {}).get("designation") or "").strip()
    title_line = f" as **{designation}**" if designation else ""
    return discord.Embed(
        title="Welcome to the team",
        description=(
            f"Please welcome {mention} (**{name}**), who just joined as **{role_label}**"
            f"{title_line}.\n\n"
            "Say hello in Discord and help them get settled."
        ),
        color=0x22C55E,
    )


async def post_onboard_welcome(bot, guild, *, profile, discord_user_id, role_name):
    """Post a welcome in #announcements. Never raise — onboarding already succeeded."""
    if bot is None or guild is None:
        return
    logger = getattr(bot, "logger", None)
    try:
        channel = await ensure_announcement_channel(bot, guild)
    except Exception as error:
        if logger:
            logger.warn("Could not resolve announcements channel for welcome", {"message": str(error)[:200]})
        return
    if channel is None:
        if logger:
            logger.warn("Onboarding welcome skipped — no #announcements channel")
        return
    try:
        await channel.send(
            embed=welcome_onboard_embed(
                profile,
                discord_user_id=discord_user_id,
                role_name=role_name,
            )
        )
    except discord.HTTPException as error:
        if logger:
            logger.warn("Could not post onboarding welcome", {"message": str(error)})


def birthday_embed(employee):
    name = employee.get("name") or "a teammate"
    discord_id = employee.get("discordUserId") or ""
    mention = f"<@{discord_id}>" if discord_id else name
    return discord.Embed(
        title="🎉🎂 Happy Birthday!!! 🎂🎉",
        description=(
            f"Hey {mention}!\n\n"
            f"The whole WebAiry family is celebrating **you** today. "
            f"Thank you for being such an amazing teammate — your energy, kindness, "
            f"and hard work make this place brighter every day.\n\n"
            f"May this year bring you joy, success, good health, and plenty of reasons to smile. "
            f"Enjoy your special day to the fullest — you deserve every bit of it!\n\n"
            f"🎈 With lots of love from all of us at **WebAiry** 🎈"
        ),
        color=0xF59E0B,
    )


def hr_birthday_cake_embed(employee, *, birthday_date=None):
    """HR-only reminder: cake delivery the day before a birthday. Includes PII."""
    name = employee.get("name") or "this teammate"
    discord_id = employee.get("discordUserId") or ""
    mention = f"<@{discord_id}>" if discord_id else name
    when = birthday_date.isoformat() if birthday_date is not None else "tomorrow"
    contact = str(employee.get("contactNumber") or "").strip() or "not on file — update in #hr-profiles"
    address = str(employee.get("address") or "").strip() or "not on file — update in #hr-profiles"
    department = str(employee.get("department") or "").strip() or "—"
    designation = str(employee.get("designation") or "").strip()
    title_line = f"{department} · {designation}" if designation else department
    return discord.Embed(
        title="Cake reminder — birthday tomorrow",
        description=(
            f"Kal **{name}** ({mention}) ka birthday hai (**{when}**).\n\n"
            f"Please **send a cake** to this person tomorrow.\n\n"
            f"**Department:** {title_line}\n"
            f"**Contact number:** {contact}\n"
            f"**Address:** {address}"
        ),
        color=0xEC4899,
    )


def _hr_role_mention(guild, config):
    roles = [{"id": str(role.id), "name": role.name} for role in getattr(guild, "roles", []) or []]
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    hr_cfg = (config or {}).get("hr") or {}
    hr_id = hr_cfg.get("hrRoleId") or find_hr_role_id(roles, "")
    if not hr_id and tickets.get("adminRoleId"):
        hr_id = tickets.get("adminRoleId")
    if str(hr_id or "").strip().isdigit():
        return f"<@&{hr_id}>"
    return ""


def _pakistan_today():
    return datetime.datetime.now(PAKISTAN_TZ).date()


async def post_todays_birthdays(bot, guild):
    if bot.hr is None or bot.hr.client is None:
        return
    channel_id = _config_channel_id(bot.config)
    if not channel_id.isdigit():
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return
    import asyncio

    today = _pakistan_today()
    people = await asyncio.to_thread(
        list_birthdays_today, bot.hr.client, today=today, logger=bot.logger
    )
    for person in people:
        try:
            await channel.send(embed=birthday_embed(person))
        except discord.HTTPException as error:
            bot.logger.warn("Could not post birthday greeting", {"message": str(error)})


async def post_hr_birthday_eve_reminders(bot, guild):
    """Day-before cake notice in #leave-requests (HR inbox only)."""
    if bot.hr is None or bot.hr.client is None or guild is None:
        return
    channel_id = str(leave_review_channel_id(bot.config) or "").strip()
    if not channel_id.isdigit():
        return
    channel = guild.get_channel(int(channel_id)) if hasattr(guild, "get_channel") else None
    if channel is None:
        return
    import asyncio

    today = _pakistan_today()
    tomorrow = today + datetime.timedelta(days=1)
    people = await asyncio.to_thread(
        list_birthdays_today, bot.hr.client, today=tomorrow, logger=bot.logger
    )
    ping = _hr_role_mention(guild, bot.config)
    content = f"{ping} Birthday tomorrow — please send a cake." if ping else None
    for person in people:
        try:
            await channel.send(
                content=content,
                embed=hr_birthday_cake_embed(person, birthday_date=tomorrow),
            )
        except discord.HTTPException as error:
            bot.logger.warn("Could not post HR birthday cake reminder", {"message": str(error)})


def start_birthday_task(bot):
    if getattr(bot, "_birthday_task_started", False):
        return
    bot._birthday_task_started = True

    @tasks.loop(time=BIRTHDAY_POST_TIME)
    async def _birthday_loop():
        for guild in bot.guilds:
            try:
                await post_hr_birthday_eve_reminders(bot, guild)
            except Exception as error:
                bot.logger.error("HR birthday cake reminder failed", {"message": str(error)[:300]})
            try:
                await post_todays_birthdays(bot, guild)
            except Exception as error:  # never let one guild's failure kill the loop
                bot.logger.error("Birthday announcement failed", {"message": str(error)[:300]})

    bot._birthday_loop = _birthday_loop
    _birthday_loop.start()

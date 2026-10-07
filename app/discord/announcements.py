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


def _find_announcements_channel(guild):
    """Match #announcements whether it is a text or Discord Announcement channel."""
    if guild is None:
        return None
    wanted = ANNOUNCEMENT_CHANNEL_NAME
    for item in list(getattr(guild, "text_channels", None) or []):
        if str(item.name or "").strip().lower() == wanted:
            return item
    for item in list(getattr(guild, "channels", None) or []):
        name = str(getattr(item, "name", "") or "").strip().lower()
        if name != wanted:
            continue
        if isinstance(item, discord.TextChannel):
            return item
    return None


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
        channel = _find_announcements_channel(guild)
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
            try:
                await channel.edit(overwrites=overwrites, topic=topic)
            except discord.HTTPException as error:
                # Still usable for posting even if permission sync failed.
                bot.logger.warn("Could not refresh announcements channel overwrites", {"message": str(error)})
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
        return False
    logger = getattr(bot, "logger", None)
    try:
        channel = await ensure_announcement_channel(bot, guild)
    except Exception as error:
        if logger:
            logger.warn("Could not resolve announcements channel for welcome", {"message": str(error)[:200]})
        return False
    if channel is None:
        if logger:
            logger.warn("Onboarding welcome skipped — no #announcements channel")
        return False
    mention = f"<@{discord_user_id}>" if str(discord_user_id or "").isdigit() else ""
    name = (profile or {}).get("full_name") or "a teammate"
    content = f"👋 New teammate: {mention or name}"
    try:
        await channel.send(
            content=content,
            embed=welcome_onboard_embed(
                profile,
                discord_user_id=discord_user_id,
                role_name=role_name,
            ),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        if logger:
            logger.info("Posted onboarding welcome", {
                "channel": str(channel.id),
                "user": str(discord_user_id or ""),
                "name": name,
            })
        return True
    except discord.HTTPException as error:
        if logger:
            logger.warn("Could not post onboarding welcome", {
                "channel": str(getattr(channel, "id", "")),
                "message": str(error),
            })
        return False


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


def _hr_member_ids(guild, config):
    """Discord user ids for everyone holding the HR (or Admin fallback) role."""
    roles = [{"id": str(role.id), "name": role.name} for role in getattr(guild, "roles", []) or []]
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    hr_cfg = (config or {}).get("hr") or {}
    hr_id = str(hr_cfg.get("hrRoleId") or find_hr_role_id(roles, "") or "").strip()
    if not hr_id.isdigit() and tickets.get("adminRoleId"):
        hr_id = str(tickets.get("adminRoleId") or "").strip()
    if not hr_id.isdigit():
        return []
    role = guild.get_role(int(hr_id)) if hasattr(guild, "get_role") else None
    if role is None:
        return []
    out = []
    for member in list(getattr(role, "members", None) or []):
        if getattr(member, "bot", False):
            continue
        mid = str(getattr(member, "id", "") or "").strip()
        if mid.isdigit():
            out.append(mid)
    return out


async def post_todays_birthdays(bot, guild):
    """Public Happy Birthday posts in #announcements (Pakistan calendar day)."""
    if bot.hr is None or bot.hr.client is None or guild is None:
        return
    channel = await ensure_announcement_channel(bot, guild)
    if channel is None:
        bot.logger.warn("Birthday greetings skipped — no #announcements channel")
        return
    import asyncio

    today = _pakistan_today()
    people = await asyncio.to_thread(
        list_birthdays_today, bot.hr.client, today=today, logger=bot.logger
    )
    for person in people:
        try:
            await channel.send(embed=birthday_embed(person))
            bot.logger.info("Posted birthday greeting", {
                "channel": str(channel.id),
                "user": str(person.get("discordUserId") or ""),
                "name": str(person.get("name") or ""),
            })
        except discord.HTTPException as error:
            bot.logger.warn("Could not post birthday greeting", {"message": str(error)})


async def post_hr_birthday_eve_reminders(bot, guild):
    """Day-before cake notice: #leave-requests plus a DM to each HR member."""
    if bot.hr is None or bot.hr.client is None or guild is None:
        return
    import asyncio

    today = _pakistan_today()
    tomorrow = today + datetime.timedelta(days=1)
    people = await asyncio.to_thread(
        list_birthdays_today, bot.hr.client, today=tomorrow, logger=bot.logger
    )
    if not people:
        return

    channel_id = str(leave_review_channel_id(bot.config) or "").strip()
    channel = guild.get_channel(int(channel_id)) if channel_id.isdigit() and hasattr(guild, "get_channel") else None
    ping = _hr_role_mention(guild, bot.config)
    content = f"{ping} Birthday tomorrow — please send a cake." if ping else "Birthday tomorrow — please send a cake."
    hr_ids = _hr_member_ids(guild, bot.config)

    from app.discord.notify import dm_member

    for person in people:
        embed = hr_birthday_cake_embed(person, birthday_date=tomorrow)
        if channel is not None:
            try:
                await channel.send(content=content, embed=embed)
            except discord.HTTPException as error:
                bot.logger.warn("Could not post HR birthday cake reminder", {"message": str(error)})
        dm_ok = 0
        for hr_id in hr_ids:
            sent = await dm_member(
                bot,
                hr_id,
                content="Birthday tomorrow — please send a cake.",
                embed=embed,
                guild=guild,
            )
            if sent:
                dm_ok += 1
        bot.logger.info("HR birthday eve reminder", {
            "name": str(person.get("name") or ""),
            "birthday": tomorrow.isoformat(),
            "inbox": bool(channel is not None),
            "hrDms": dm_ok,
            "hrCandidates": len(hr_ids),
        })


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

"""HR-only #hr-announcements channel: type a trigger phrase -> fill a form ->
the announcement is stored in MySQL and auto-posted into #announcements at
the scheduled Pakistan-time moment. A "cancel" trigger shows a picker so HR
can pull one back before it posts.

Modeled directly on the birthday-wish mechanism in app/discord/announcements.py
(SQL-backed, Pakistan time, discord.ext.tasks.loop) and the "Cancel approved
leave" picker in app/discord/leave_ui.py.
"""

import re
from datetime import datetime

import discord
from discord.ext import tasks

from app.discord.announcements import PAKISTAN_TZ
from app.records.hr_announcements import (
    cancel_announcement,
    create_announcement,
    list_due_announcements,
    list_scheduled_announcements,
    mark_announcement_posted,
)
from app.tickets.helpers import find_admin_role_id, find_hr_role_id

HR_ANNOUNCEMENT_CHANNEL_NAME = "hr-announcements"

NEW_ANNOUNCEMENT_HINT = re.compile(r"announc", re.I)
CANCEL_ANNOUNCEMENT_HINT = re.compile(r"cancel", re.I)

NEW_ANNOUNCEMENT_BUTTON_ID = "hrannounce:new"
CANCEL_PICK_ID = "hrannounce:cancel:pick"
CANCEL_CONFIRM_ID = "hrannounce:cancel:confirm"
CANCEL_CLOSE_ID = "hrannounce:cancel:close"


# ---------------------------------------------------------------------------
# Channel setup


def _config_channel_id(config):
    tickets = (config.get("discord") or {}).get("tickets") or {}
    return str(tickets.get("hrAnnouncementChannelId") or "").strip()


def _public_announcement_channel_id(config):
    """Where the finished announcement gets posted -- the existing #announcements channel."""
    tickets = (config.get("discord") or {}).get("tickets") or {}
    return str(tickets.get("announcementChannelId") or "").strip()


def is_hr_announcement_channel(bot, channel_id):
    configured = _config_channel_id(bot.config)
    if configured:
        return str(channel_id) == configured
    return False


def _hr_announcement_input_overwrites(guild, config):
    """@everyone hidden. Bot, HR, and Admin can view AND type here."""
    roles = [{"id": str(role.id), "name": role.name} for role in guild.roles]
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    hr_cfg = (config or {}).get("hr") or {}
    admin_id = find_admin_role_id(roles, tickets.get("adminRoleId")) or hr_cfg.get("adminRoleId")
    hr_id = hr_cfg.get("hrRoleId") or find_hr_role_id(roles, "")
    hide = discord.PermissionOverwrite(view_channel=False)
    can_post = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
    )
    overwrites = {guild.default_role: hide}
    bot_member = guild.me
    if isinstance(bot_member, discord.Member):
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            embed_links=True,
        )
    if admin_id:
        role = guild.get_role(int(admin_id)) if str(admin_id).isdigit() else None
        if role:
            overwrites[role] = can_post
    if hr_id:
        role = guild.get_role(int(hr_id)) if str(hr_id).isdigit() else None
        if role:
            overwrites[role] = can_post
    return overwrites


async def ensure_hr_announcement_channel(bot, guild):
    """Find or create #hr-announcements. Only HR/Admin (and the bot) can see or type here."""
    from app.discord.leave_inbox import ensure_hr_category

    tickets = bot.config["discord"]["tickets"]
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
            if str(item.name or "").strip().lower() == HR_ANNOUNCEMENT_CHANNEL_NAME:
                channel = item
                break
    overwrites = _hr_announcement_input_overwrites(guild, bot.config)
    parent = await ensure_hr_category(bot, guild)
    topic = (
        "HR only. Type \"I have an announcement\" (or \"mujhe announcement karni hai\") to schedule one, "
        "or \"cancel the announcement\" to pull one back before it posts."
    )
    try:
        if channel is None:
            channel = await guild.create_text_channel(
                HR_ANNOUNCEMENT_CHANNEL_NAME,
                category=parent,
                overwrites=overwrites,
                topic=topic,
                reason="Dedicated HR announcement scheduling channel",
            )
            bot.logger.info("Created hr-announcements channel", {"channel": str(channel.id)})
        else:
            await channel.edit(overwrites=overwrites, topic=topic, category=parent)
    except discord.HTTPException as error:
        bot.logger.warn("Could not prepare hr-announcements channel", {"message": str(error)})
        return channel
    tickets["hrAnnouncementChannelId"] = str(channel.id)
    return channel


# ---------------------------------------------------------------------------
# Drafts (keep entered values on validation error, same pattern as onboarding)


def _drafts(bot):
    store = getattr(bot, "_hr_announcement_drafts", None)
    if store is None:
        store = {}
        bot._hr_announcement_drafts = store
    return store


def _save_draft(bot, user_id, draft):
    if bot is None or not user_id:
        return
    _drafts(bot)[str(user_id)] = dict(draft or {})


def _load_draft(bot, user_id):
    if bot is None or not user_id:
        return {}
    return dict(_drafts(bot).get(str(user_id)) or {})


def _clear_draft(bot, user_id):
    if bot is None or not user_id:
        return
    _drafts(bot).pop(str(user_id), None)


def _clip(value, limit):
    return str(value if value is not None else "")[:limit]


# ---------------------------------------------------------------------------
# Trigger detection


def looks_like_new_announcement_request(text):
    return bool(NEW_ANNOUNCEMENT_HINT.search(str(text or "")))


def looks_like_cancel_announcement_request(text):
    blob = str(text or "")
    return bool(CANCEL_ANNOUNCEMENT_HINT.search(blob) and NEW_ANNOUNCEMENT_HINT.search(blob))


async def maybe_handle_hr_announcement_message(bot, message):
    """True if this message was handled here and should not reach the normal pipeline."""
    if not is_hr_announcement_channel(bot, message.channel.id):
        return False
    if message.author.bot:
        return False
    text = str(message.content or "")
    if looks_like_cancel_announcement_request(text):
        await _send_cancel_picker(bot, message.channel)
        return True
    if looks_like_new_announcement_request(text):
        await message.channel.send(
            embed=discord.Embed(
                title="Schedule an announcement",
                description="Click below to fill in the title, date, time, and description.",
                color=0x2563EB,
            ),
            view=NewAnnouncementPromptView(bot),
        )
        return True
    return False


# ---------------------------------------------------------------------------
# Create flow


class NewAnnouncementPromptView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=600)
        self.bot = bot
        button = discord.ui.Button(
            label="Create announcement",
            style=discord.ButtonStyle.primary,
            custom_id=NEW_ANNOUNCEMENT_BUTTON_ID,
        )

        async def open_cb(interaction: discord.Interaction):
            draft = _load_draft(self.bot, interaction.user.id)
            # Remember the "Schedule an announcement" prompt itself so it can
            # close on its own once the form is actually submitted.
            await interaction.response.send_modal(
                CreateAnnouncementModal(self.bot, draft, prompt_message=interaction.message)
            )

        button.callback = open_cb
        self.add_item(button)


def _parse_time_text(time_text):
    """Accepts 12-hour clock text like '6:20 PM', '6:20pm', '06:20 am'."""
    text = str(time_text or "").strip().upper()
    # Normalize "6:20PM" -> "6:20 PM" so strptime's %p always has a space to match.
    text = re.sub(r"(?<=\d)\s*(AM|PM)$", r" \1", text)
    for fmt in ("%I:%M %p", "%I %p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _validate_announcement(title, date_text, time_text, description, *, now=None):
    """Returns (errors, scheduled_at_datetime_or_none)."""
    errors = []
    title_clean = str(title or "").strip()
    if not title_clean:
        errors.append("Title is required.")
    description_clean = str(description or "").strip()
    if not description_clean:
        errors.append("Description is required.")
    date_clean = str(date_text or "").strip()
    time_clean = str(time_text or "").strip()
    parsed_date = None
    try:
        parsed_date = datetime.strptime(date_clean, "%Y-%m-%d").date()
    except ValueError:
        errors.append("Date must look like YYYY-MM-DD.")
    parsed_time = _parse_time_text(time_clean)
    if parsed_time is None:
        errors.append("Time must look like H:MM AM/PM in Pakistan time (e.g. 6:20 PM).")
    scheduled_at = None
    if parsed_date is not None and parsed_time is not None:
        candidate = datetime.combine(parsed_date, parsed_time, tzinfo=PAKISTAN_TZ)
        now_pkt = now or datetime.now(PAKISTAN_TZ)
        if candidate <= now_pkt:
            errors.append("Date and time must be in the future.")
        else:
            scheduled_at = candidate
    if errors:
        scheduled_at = None
    return errors, scheduled_at


class CreateAnnouncementModal(discord.ui.Modal, title="New announcement"):
    def __init__(self, bot, draft=None, *, prompt_message=None):
        super().__init__()
        self.bot = bot
        self.prompt_message = prompt_message
        draft = draft or {}
        self.title_input = discord.ui.TextInput(
            label="Title",
            placeholder="e.g. Office closed on Friday",
            default=_clip(draft.get("title"), 150) or None,
            max_length=150,
            required=True,
        )
        today_text = datetime.now(PAKISTAN_TZ).date().isoformat()
        self.date_input = discord.ui.TextInput(
            label="Date (YYYY-MM-DD, Pakistan time)",
            placeholder=today_text,
            default=_clip(draft.get("date"), 10) or None,
            max_length=10,
            required=True,
        )
        self.time_input = discord.ui.TextInput(
            label="Time (H:MM AM/PM, Pakistan time)",
            placeholder="6:20 PM",
            default=_clip(draft.get("time"), 10) or None,
            max_length=10,
            required=True,
        )
        self.description_input = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            placeholder="What should everyone know?",
            default=_clip(draft.get("description"), 1000) or None,
            max_length=1000,
            required=True,
        )
        self.add_item(self.title_input)
        self.add_item(self.date_input)
        self.add_item(self.time_input)
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction):
        title = str(self.title_input.value or "")
        date_text = str(self.date_input.value or "")
        time_text = str(self.time_input.value or "")
        description = str(self.description_input.value or "")
        draft = {"title": title, "date": date_text, "time": time_text, "description": description}
        errors, scheduled_at = _validate_announcement(title, date_text, time_text, description)
        if errors:
            _save_draft(self.bot, interaction.user.id, draft)
            await interaction.response.send_message(
                "Could not schedule this announcement:\n- " + "\n- ".join(errors),
                view=_retry_view(self.bot, self.prompt_message),
                ephemeral=True,
            )
            return
        if self.bot.hr is None or self.bot.hr.client is None:
            await interaction.response.send_message("HR data is not connected yet.", ephemeral=True)
            return
        import asyncio

        record = await asyncio.to_thread(
            create_announcement,
            self.bot.hr.client,
            title=title.strip(),
            description=description.strip(),
            announce_date=scheduled_at.date().isoformat(),
            announce_time=time_text.strip(),
            scheduled_at=scheduled_at.strftime("%Y-%m-%d %H:%M"),
            created_by_id=str(interaction.user.id),
            created_by_name=str(interaction.user.display_name or interaction.user.name),
            logger=self.bot.logger,
        )
        _clear_draft(self.bot, interaction.user.id)
        await interaction.response.send_message(embed=_scheduled_confirmation_embed(record), ephemeral=True)
        await _close_prompt_message(self.prompt_message, text=f"✅ Announcement scheduled: {record.get('title')}")


def _retry_view(bot, prompt_message=None):
    view = discord.ui.View(timeout=600)
    button = discord.ui.Button(label="Try again", style=discord.ButtonStyle.secondary)

    async def retry_cb(interaction: discord.Interaction):
        draft = _load_draft(bot, interaction.user.id)
        await interaction.response.send_modal(
            CreateAnnouncementModal(bot, draft, prompt_message=prompt_message)
        )

    button.callback = retry_cb
    view.add_item(button)
    return view


async def _close_prompt_message(message, *, text):
    """Once the form is actually submitted, the "Create announcement" prompt
    closes itself instead of sitting there re-clickable."""
    if message is None:
        return
    try:
        await message.edit(content=text, embed=None, view=None)
    except discord.HTTPException:
        pass


def _scheduled_confirmation_embed(record):
    record = record or {}
    embed = discord.Embed(
        title="Announcement scheduled",
        description=record.get("title") or "",
        color=0x22C55E,
    )
    embed.add_field(name="Date", value=record.get("announceDate") or "—", inline=True)
    embed.add_field(name="Time (PKT)", value=record.get("announceTime") or "—", inline=True)
    embed.add_field(name="Description", value=(record.get("description") or "—")[:1024], inline=False)
    embed.set_footer(text="It will be posted to #announcements automatically at that time.")
    return embed


# ---------------------------------------------------------------------------
# Cancel flow


def _cancel_choice_label(item):
    kind = str(item.get("title") or "Announcement")[:60]
    when = f"{item.get('announceDate') or '?'} {item.get('announceTime') or ''}".strip()
    return f"{kind} · {when}"[:100]


class CancelAnnouncementView(discord.ui.View):
    def __init__(self, bot, items=None, selected=""):
        super().__init__(timeout=600)
        self.bot = bot
        items = items or []
        options = []
        for item in items[:25]:
            record_id = str(item.get("id") or "")
            if not record_id:
                continue
            options.append(
                discord.SelectOption(
                    label=_cancel_choice_label(item),
                    value=record_id,
                    default=(record_id == selected),
                )
            )
        if not options:
            options = [discord.SelectOption(label="No scheduled announcements", value="none")]
        select = discord.ui.Select(
            placeholder="Choose a scheduled announcement",
            custom_id=CANCEL_PICK_ID,
            options=options,
            min_values=1,
            max_values=1,
            disabled=not items,
        )
        cancel_btn = discord.ui.Button(
            label="Cancel selected",
            style=discord.ButtonStyle.danger,
            custom_id=CANCEL_CONFIRM_ID,
            disabled=not items,
        )
        close_btn = discord.ui.Button(
            label="Close",
            style=discord.ButtonStyle.secondary,
            custom_id=CANCEL_CLOSE_ID,
        )

        async def pick_cb(interaction: discord.Interaction):
            values = getattr(select, "values", None) or []
            picked = values[0] if values else ""
            await interaction.response.edit_message(
                embed=_cancel_picker_embed(items),
                view=CancelAnnouncementView(self.bot, items, selected=picked),
            )

        async def cancel_cb(interaction: discord.Interaction):
            values = getattr(select, "values", None) or []
            picked = values[0] if values else selected
            target = next((row for row in items if str(row.get("id")) == picked), None)
            if not target:
                await interaction.response.send_message("Pick an announcement first.", ephemeral=True)
                return
            import asyncio

            await asyncio.to_thread(
                cancel_announcement,
                self.bot.hr.client,
                target,
                cancelled_by=str(interaction.user.display_name or interaction.user.name),
                logger=self.bot.logger,
            )
            # The picker closes itself; a plain confirmation replaces it.
            await interaction.response.edit_message(
                content=f"❌ Announcement cancelled: {target.get('title')}",
                embed=None,
                view=None,
            )

        async def close_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(content="Closed.", embed=None, view=None)

        select.callback = pick_cb
        cancel_btn.callback = cancel_cb
        close_btn.callback = close_cb
        self.add_item(select)
        self.add_item(cancel_btn)
        self.add_item(close_btn)


def _cancel_picker_embed(items, *, note=""):
    embed = discord.Embed(title="Cancel a scheduled announcement", color=0xF97316)
    if note:
        embed.description = note
    if items:
        lines = [f"**{item.get('title')}** — {item.get('announceDate')} {item.get('announceTime')} PKT" for item in items]
        embed.add_field(name="Scheduled", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="Scheduled", value="None upcoming", inline=False)
    return embed


async def _send_cancel_picker(bot, channel):
    if bot.hr is None or bot.hr.client is None:
        await channel.send("HR data is not connected yet.")
        return
    import asyncio

    items = await asyncio.to_thread(list_scheduled_announcements, bot.hr.client, logger=bot.logger)
    await channel.send(embed=_cancel_picker_embed(items), view=CancelAnnouncementView(bot, items))


# ---------------------------------------------------------------------------
# Scheduled posting task


def hr_announcement_embed(record):
    record = record or {}
    embed = discord.Embed(
        title=f"📢 {record.get('title') or 'Announcement'}",
        description=record.get("description") or "",
        color=0x2563EB,
    )
    embed.set_footer(text="HR Announcement")
    return embed


async def post_due_announcements(bot, guild):
    if bot.hr is None or bot.hr.client is None:
        return
    channel_id = _public_announcement_channel_id(bot.config)
    if not channel_id.isdigit():
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return
    import asyncio

    due = await asyncio.to_thread(list_due_announcements, bot.hr.client, logger=bot.logger)
    for record in due:
        try:
            await channel.send(embed=hr_announcement_embed(record))
            await asyncio.to_thread(mark_announcement_posted, bot.hr.client, record, logger=bot.logger)
        except discord.HTTPException as error:
            bot.logger.warn("Could not post HR announcement", {"message": str(error)})


def start_hr_announcement_task(bot):
    if getattr(bot, "_hr_announcement_task_started", False):
        return
    bot._hr_announcement_task_started = True

    @tasks.loop(seconds=60)
    async def _hr_announcement_loop():
        for guild in bot.guilds:
            try:
                await post_due_announcements(bot, guild)
            except Exception as error:  # never let one guild's failure kill the loop
                bot.logger.error("HR announcement posting failed", {"message": str(error)[:300]})

    bot._hr_announcement_loop = _hr_announcement_loop
    _hr_announcement_loop.start()

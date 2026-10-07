import asyncio
from datetime import date, datetime, timedelta, timezone

import discord

from app.discord.attachments import add_attachment_preview, parse_reason_and_files
from app.hr.dates import format_display_date, resolve_date_phrase, resolve_date_range
from app.routing.language import pick_locale_text

LEAVE_SUBMIT_ID = "leave:submit"
LEAVE_CANCEL_ID = "leave:cancel"
LEAVE_FILL_ID = "leave:fill"
LEAVE_TYPE_SELECT = "leave:type"
LEAVE_WITHDRAW_ID = "leave:withdraw"
LEAVE_CANCEL_FILL_ID = "leave:cancel:fill"
LEAVE_CANCEL_SUBMIT_ID = "leave:cancel:submit"
LEAVE_CANCEL_DISMISS_ID = "leave:cancel:dismiss"
LEAVE_CANCEL_PICK_ID = "leave:cancel:pick"
LEAVE_TYPES = ("Annual Leave", "Sick Leave", "Casual Leave")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


EMPTY = "Not set"
REASON_LIMIT = 320


async def fetch_guild_member(guild, user_id, fallback=None):
    """Load the member from cache, then the API, so Discord roles are available."""
    if guild is None or not user_id:
        return fallback
    try:
        uid = int(str(user_id).strip())
    except (TypeError, ValueError):
        return fallback
    member = guild.get_member(uid)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(uid)
    except (discord.HTTPException, discord.NotFound):
        return fallback

COLORS = {
    "form": 0x1E293B,
    "confirm": 0x4F46E5,
    "pending": 0x0F766E,
    "withdrawn": 0x64748B,
}


def _pretty_date(value):
    raw = str(value or "")[:10]
    try:
        year, month, day = [int(part) for part in raw.split("-")]
        parsed = date(year, month, day)
    except (TypeError, ValueError):
        return EMPTY
    return f"{parsed.strftime('%d %b %Y')}\n{WEEKDAYS[parsed.weekday()]}"


def _blank(value, fallback=EMPTY):
    text = str(value or "").strip()
    return text if text else fallback


def _looks_like_record_id(value):
    text = str(value or "").strip()
    return text.startswith("rec") and " " not in text and len(text) >= 10


def _leave_type_label(value, fallback=""):
    text = str(value or "").strip()
    if not text or _looks_like_record_id(text):
        return fallback or EMPTY
    return text


def _qty(value):
    if value is None or value == "":
        return EMPTY
    try:
        number = float(value)
        if number.is_integer():
            return str(int(number))
        return str(number)
    except (TypeError, ValueError):
        return str(value)


def _reason_display(value):
    text = " ".join(str(value or "").split())
    if not text:
        return f"*{EMPTY}*"
    if len(text) > REASON_LIMIT:
        text = text[: REASON_LIMIT - 1].rstrip() + "…"
    return text


def _field(embed, name, value, *, inline=True):
    embed.add_field(name=name, value=value or f"*{EMPTY}*", inline=inline)


def _spacer(embed):
    embed.add_field(name="\u200b", value="\u200b", inline=True)


def leave_template_embed(card):
    card = card or {}
    locale = card.get("locale") or "english"
    stage = card.get("stage") or "form"
    leave_type = _leave_type_label(card.get("leave_type"))
    start = _pretty_date(card.get("start_date")) if card.get("start_date") else EMPTY
    end = _pretty_date(card.get("end_date")) if card.get("end_date") else EMPTY
    days = _qty(card.get("days")) if card.get("days") else EMPTY
    half = _leave_type_label(card.get("half_day"), "")
    if half and half != EMPTY:
        days = f"{days} ({half.lower()})"
    reason_body, files = parse_reason_and_files(card.get("reason"))
    reason = _reason_display(reason_body)
    if not files:
        files = card.get("attachments") or []
    if stage == "confirm":
        status = "Ready"
        color = COLORS["confirm"]
        desc = pick_locale_text(
            locale,
            english="Review the details. HR is not notified until you submit.",
            roman="Details check karein. Submit se pehle HR ko notice nahi jayega.",
            urdu="تفصیلات چیک کریں۔ جمع کرنے سے پہلے HR کو اطلاع نہیں جائے گی۔",
            mix="Review the details. HR is not notified until you submit.",
        )
        footer = "Submit to HR  ·  or edit the form"
        if card.get("hint"):
            desc = card["hint"]
    else:
        status = "Draft"
        color = COLORS["form"]
        desc = None
        footer = "Fill form  ·  Cancel anytime"
    embed = discord.Embed(title="Leave request", description=desc, color=color)
    embed.set_author(name="Human Resources")
    _field(embed, "Leave type", f"**{leave_type}**")
    _field(embed, "Days", f"**{days}**")
    _field(embed, "Status", f"**{status}**")
    _field(embed, "From", start)
    _field(embed, "To", end)
    _spacer(embed)
    _field(embed, "Reason for leave", reason, inline=False)
    add_attachment_preview(embed, files)
    embed.set_footer(text=footer)
    return embed


def leave_confirm_embed(card):
    payload = dict(card or {})
    payload["stage"] = "confirm"
    return leave_template_embed(payload)


def leave_form_embed(card):
    payload = dict(card or {})
    payload["stage"] = payload.get("stage") or "form"
    return leave_template_embed(payload)


def leave_pending_embed(card):
    card = card or {}
    locale = card.get("locale") or "english"
    leave_type = _leave_type_label(card.get("leave_type"), "Leave")
    start = _pretty_date(card.get("start_date"))
    end = _pretty_date(card.get("end_date")) if card.get("end_date") else start
    days = _qty(card.get("days") or 1)
    name = card.get("name") or "Member"
    remaining = card.get("remaining")
    reason_body, files = parse_reason_and_files(card.get("reason"))
    reason = _reason_display(reason_body)
    if not files:
        files = card.get("attachments") or []
    title = pick_locale_text(
        locale,
        english="Leave request submitted",
        roman="Leave request HR ko chali gayi",
        urdu="لیو درخواست جمع ہو گئی",
        mix="Leave request HR ko chali gayi",
    )
    desc = pick_locale_text(
        locale,
        english=f"**{name}**  ·  {days} day(s)  ·  {leave_type}",
        roman=f"**{name}**  ·  {days} din  ·  {leave_type}",
        urdu=f"**{name}**  ·  {days} دن  ·  {leave_type}",
        mix=f"**{name}**  ·  {days} day(s)  ·  {leave_type}",
    )
    embed = discord.Embed(title=title, description=desc, color=COLORS["pending"])
    embed.set_author(name="Human Resources")
    _field(embed, "From", start)
    _field(embed, "To", end)
    _field(embed, "Status", "**Pending**")
    _field(embed, "Leave type", f"**{leave_type}**")
    _field(embed, "Days", f"**{days}**")
    if remaining is not None:
        _field(embed, "Available now", f"**{_qty(remaining)}**")
    else:
        _spacer(embed)
    _field(embed, "Reason for leave", reason, inline=False)
    add_attachment_preview(embed, files)
    from app.hr.leave_status import PENDING_MANAGER

    waiting = "waiting for HOD" if str((card or {}).get("status") or "") == PENDING_MANAGER else "waiting for HR"
    embed.set_footer(text=f"Withdraw anytime  ·  {waiting}")
    return embed


def leave_withdrawn_embed(card):
    card = card or {}
    locale = card.get("locale") or "english"
    leave_type = _leave_type_label(card.get("leave_type"), "Leave")
    start = _pretty_date(card.get("start_date"))
    end = _pretty_date(card.get("end_date")) if card.get("end_date") else start
    days = _qty(card.get("days") or 1)
    title = pick_locale_text(
        locale,
        english="Leave request withdrawn",
        roman="Leave request withdraw ho gayi",
        urdu="لیو درخواست واپس لے لی گئی",
        mix="Leave request withdraw ho gayi",
    )
    embed = discord.Embed(
        title=title,
        description=pick_locale_text(
            locale,
            english="This request is no longer with HR. You can apply again.",
            roman="Yeh request ab HR ke paas nahi. Dubara apply kar sakte ho.",
            urdu="یہ درخواست اب HR کے پاس نہیں۔ دوبارہ درخواست دے سکتے ہیں۔",
            mix="Yeh request ab HR ke paas nahi. You can apply again.",
        ),
        color=COLORS["withdrawn"],
    )
    embed.set_author(name="Human Resources")
    _field(embed, "From", start)
    _field(embed, "To", end)
    _field(embed, "Status", "**Withdrawn**")
    _field(embed, "Leave type", f"**{leave_type}**")
    _field(embed, "Days", f"**{days}**")
    _spacer(embed)
    embed.set_footer(text="Withdrawn by you")
    return embed


def leave_balance_embed(text, *, name=""):
    body = str(text or "").strip()
    lines = body.splitlines()
    if lines and "live leave balance" in lines[0].lower():
        lines = lines[1:]
    description = "\n".join(lines).strip()[:3900]
    person = str(name or "").strip()
    title = f"{person}'s live leave balance" if person else "Your live leave balance"
    embed = discord.Embed(
        title=title,
        description=description or "No leave balance is available.",
        color=0x1E293B,
    )
    embed.set_footer(text="Balances update after Admin approval")
    return embed


def _date_default(value):
    """ISO date string for form fields (YYYY-MM-DD)."""
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    raw = str(value or "")[:10]
    try:
        year, month, day = [int(part) for part in raw.split("-")]
        return date(year, month, day).isoformat()
    except (TypeError, ValueError):
        return ""


def split_from_to_columns(text):
    raw = str(text or "").strip()
    if not raw:
        return "", ""
    for sep in (" | ", "|", " – ", " — ", " - ", " to ", " say ", " se "):
        token = sep.lower()
        index = raw.lower().find(token)
        if index > 0:
            left = raw[:index].strip()
            right = raw[index + len(sep):].strip()
            right = right.replace(" tak", "").replace(" Tak", "").strip()
            if left and right:
                return left, right
    return raw, raw


class LeaveDetailsModal(discord.ui.Modal, title="Leave request"):
    def __init__(self, bot, draft):
        super().__init__()
        self.bot = bot
        draft = draft or {}
        # Default From/To to today so the user can edit comfortably instead of
        # typing a blank date. Chat never pre-fills these — only this modal does.
        # Standard ISO dates (YYYY-MM-DD) are easier to edit than "DD Mon YYYY".
        today_text = date.today().isoformat()
        from_default = _date_default(draft.get("start_date")) or today_text
        to_default = (
            _date_default(draft.get("end_date"))
            or _date_default(draft.get("start_date"))
            or today_text
        )
        self.from_input = discord.ui.TextInput(
            label="From (YYYY-MM-DD)",
            placeholder=today_text,
            required=True,
            max_length=40,
            default=from_default,
        )
        self.to_input = discord.ui.TextInput(
            label="To (YYYY-MM-DD)",
            placeholder=today_text,
            required=True,
            max_length=40,
            default=to_default,
        )
        from app.discord.attachments import parse_reason_and_files

        reason_text, _ = parse_reason_and_files(draft.get("reason"))
        self.reason_input = discord.ui.TextInput(
            label="Reason for leave",
            placeholder="Reason for leave",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=400,
            default=reason_text[:400],
        )
        # Optional, and only meaningful when From and To are the same day.
        self.half_input = discord.ui.TextInput(
            label="Half day? (first / second)",
            placeholder="Leave blank for a full day",
            required=False,
            max_length=20,
            default=str(draft.get("half_day") or ""),
        )
        self.add_item(self.from_input)
        self.add_item(self.to_input)
        self.add_item(self.half_input)
        self.add_item(self.reason_input)
        from app.discord.attachments import reason_file_upload

        label, self.reason_files = reason_file_upload(custom_id="leave:reason:files")
        self.add_item(label)

    async def on_submit(self, interaction: discord.Interaction):
        from app.agent.router import apply_leave_form
        from app.discord.attachments import meta_from_upload

        result = apply_leave_form(
            self.bot.agent,
            str(interaction.channel_id),
            from_text=str(self.from_input.value or ""),
            to_text=str(self.to_input.value or ""),
            reason=str(self.reason_input.value or ""),
            half_day=str(self.half_input.value or ""),
            attachments=meta_from_upload(self.reason_files),
        )
        if result.get("error"):
            await interaction.response.send_message(result["error"], ephemeral=True)
            return
        card = result.get("leaveCard") or {}
        try:
            await interaction.response.edit_message(
                embed=leave_template_embed(card),
                view=leave_action_view(self.bot, card),
            )
            _save_form_message_id(self.bot, interaction.channel_id, interaction.message.id)
        except Exception:
            await publish_leave_form(self.bot, interaction.channel, card, send=interaction.response.send_message)


class LeaveActionView(discord.ui.View):
    def __init__(self, bot, *, leave_type=None):
        super().__init__(timeout=None)
        self.bot = bot
        selected = str(leave_type or "").strip()
        select = discord.ui.Select(
            placeholder="Leave type",
            custom_id=LEAVE_TYPE_SELECT,
            options=[
                discord.SelectOption(label=name, value=name, default=(name == selected))
                for name in LEAVE_TYPES
            ],
            min_values=1,
            max_values=1,
        )
        fill = discord.ui.Button(
            label="Fill form",
            style=discord.ButtonStyle.primary,
            custom_id=LEAVE_FILL_ID,
        )
        submit = discord.ui.Button(
            label="Submit to HR",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=LEAVE_SUBMIT_ID,
        )
        cancel = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            emoji="✖️",
            custom_id=LEAVE_CANCEL_ID,
        )

        async def select_cb(interaction: discord.Interaction):
            await handle_leave_type(interaction, self.bot)

        async def fill_cb(interaction: discord.Interaction):
            await handle_leave_fill(interaction, self.bot)

        async def submit_cb(interaction: discord.Interaction):
            await handle_leave_action(interaction, self.bot, "yes")

        async def cancel_cb(interaction: discord.Interaction):
            await handle_leave_action(interaction, self.bot, "cancel")

        select.callback = select_cb
        fill.callback = fill_cb
        submit.callback = submit_cb
        cancel.callback = cancel_cb
        self.add_item(select)
        self.add_item(fill)
        self.add_item(submit)
        self.add_item(cancel)


def leave_action_view(bot, card=None):
    return LeaveActionView(bot, leave_type=(card or {}).get("leave_type"))


def _approved_leave_span(item):
    from_day = format_display_date(item.get("start_date")) or item.get("start_date") or "—"
    to_day = format_display_date(item.get("end_date")) or from_day
    return from_day if from_day == to_day else f"{from_day} to {to_day}"


def _cancel_choice_id(item):
    return str((item or {}).get("id") or (item or {}).get("requestId") or "").strip()[:100]


def cancel_leave_embed(card):
    card = card or {}
    locale = card.get("locale") or "english"
    rows = list(card.get("approved") or [])
    start = _pretty_date(card.get("start_date")) if card.get("start_date") else EMPTY
    end = _pretty_date(card.get("end_date")) if card.get("end_date") else EMPTY
    reason = _reason_display(card.get("reason"))
    desc = card.get("hint") or pick_locale_text(
        locale,
        english="Your approved leave is listed below. Choose one, add a reason, then submit.",
        roman="Neeche aapki approved leave hai. Ek choose karein, reason likhein, phir submit karein.",
        urdu="نیچے آپ کی منظور شدہ لیو ہے۔ ایک منتخب کریں، وجہ لکھیں، پھر جمع کریں۔",
        mix="Neeche aapki approved leave hai. Choose one, add a reason, then submit.",
    )
    embed = discord.Embed(title="Cancel approved leave", description=desc, color=COLORS["form"])
    embed.set_author(name="Human Resources")
    if rows:
        lines = []
        for item in rows:
            kind = _leave_type_label(item.get("leave_type"), "Leave")
            lines.append(f"**{kind}** — {_approved_leave_span(item)}")
        embed.add_field(name="Approved leave", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(name="Approved leave", value="None upcoming", inline=False)
    _field(embed, "From", start)
    _field(embed, "To", end)
    _field(embed, "Reason", reason, inline=False)
    embed.set_footer(text="Choose leave  ·  Fill form  ·  Submit")
    return embed


class CancelLeaveDetailsModal(discord.ui.Modal, title="Cancel leave"):
    def __init__(self, bot, draft):
        super().__init__()
        self.bot = bot
        draft = draft or {}
        has_dates = bool(draft.get("start_date") and (draft.get("end_date") or draft.get("start_date")))
        self.from_input = None
        self.to_input = None
        if not has_dates:
            today_text = date.today().isoformat()
            self.from_input = discord.ui.TextInput(
                label="From (YYYY-MM-DD)",
                placeholder=today_text,
                required=True,
                max_length=40,
                default=today_text,
            )
            self.to_input = discord.ui.TextInput(
                label="To (YYYY-MM-DD)",
                placeholder=today_text,
                required=True,
                max_length=40,
                default=today_text,
            )
            self.add_item(self.from_input)
            self.add_item(self.to_input)
        self.reason_input = discord.ui.TextInput(
            label="Reason for cancelling",
            placeholder="Why this leave should be cancelled",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=400,
            default=str(draft.get("reason") or "")[:400],
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        from app.agent.router import apply_cancel_leave_form

        result = apply_cancel_leave_form(
            self.bot.agent,
            str(interaction.channel_id),
            from_text=str(self.from_input.value or "") if self.from_input else "",
            to_text=str(self.to_input.value or "") if self.to_input else "",
            reason=str(self.reason_input.value or ""),
        )
        if result.get("error"):
            await interaction.response.send_message(result["error"], ephemeral=True)
            return
        card = result.get("leaveCard") or {}
        try:
            await interaction.response.edit_message(
                embed=cancel_leave_embed(card),
                view=cancel_leave_view(self.bot, card),
            )
            _save_cancel_form_message_id(self.bot, interaction.channel_id, interaction.message.id)
        except Exception:
            await publish_cancel_leave_form(
                self.bot, interaction.channel, card, send=interaction.response.send_message
            )


class CancelLeaveView(discord.ui.View):
    def __init__(self, bot, card=None):
        super().__init__(timeout=None)
        self.bot = bot
        card = card or {}
        rows = list(card.get("approved") or [])
        selected = str(card.get("request_id") or "").strip()
        options = []
        for item in rows[:25]:
            choice = _cancel_choice_id(item)
            if not choice:
                continue
            kind = _leave_type_label(item.get("leave_type"), "Leave")
            label = f"{kind} · {_approved_leave_span(item)}"[:100]
            options.append(discord.SelectOption(label=label, value=choice, default=(choice == selected)))
        if not options:
            options = [discord.SelectOption(label="No approved leave", value="none")]
        select = discord.ui.Select(
            placeholder="Choose approved leave",
            custom_id=LEAVE_CANCEL_PICK_ID,
            options=options,
            min_values=1,
            max_values=1,
        )
        fill = discord.ui.Button(
            label="Fill form",
            style=discord.ButtonStyle.primary,
            custom_id=LEAVE_CANCEL_FILL_ID,
        )
        submit = discord.ui.Button(
            label="Submit",
            style=discord.ButtonStyle.danger,
            custom_id=LEAVE_CANCEL_SUBMIT_ID,
        )
        dismiss = discord.ui.Button(
            label="Close",
            style=discord.ButtonStyle.secondary,
            custom_id=LEAVE_CANCEL_DISMISS_ID,
        )

        async def pick_cb(interaction: discord.Interaction):
            await handle_cancel_leave_pick(interaction, self.bot)

        async def fill_cb(interaction: discord.Interaction):
            await handle_cancel_leave_fill(interaction, self.bot)

        async def submit_cb(interaction: discord.Interaction):
            await handle_cancel_leave_submit(interaction, self.bot)

        async def dismiss_cb(interaction: discord.Interaction):
            await handle_cancel_leave_dismiss(interaction, self.bot)

        select.callback = pick_cb
        fill.callback = fill_cb
        submit.callback = submit_cb
        dismiss.callback = dismiss_cb
        self.add_item(select)
        self.add_item(fill)
        self.add_item(submit)
        self.add_item(dismiss)


def cancel_leave_view(bot, card=None):
    return CancelLeaveView(bot, card)


class LeavePendingView(discord.ui.View):
    """The card shown while a request is open. Staff only see Withdraw."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        withdraw = discord.ui.Button(
            label="Withdraw",
            style=discord.ButtonStyle.danger,
            custom_id=LEAVE_WITHDRAW_ID,
        )

        async def withdraw_cb(interaction: discord.Interaction):
            await handle_leave_withdraw(interaction, self.bot)

        withdraw.callback = withdraw_cb
        self.add_item(withdraw)


def leave_pending_view(bot):
    return LeavePendingView(bot)


async def _delete_message(channel, message_id):
    if not message_id:
        return
    try:
        old = await channel.fetch_message(int(message_id))
        await old.delete()
    except Exception:
        return


def is_leave_form_message(message):
    for embed in getattr(message, "embeds", []) or []:
        title = str(getattr(embed, "title", "") or "")
        footer = str(getattr(getattr(embed, "footer", None), "text", "") or "")
        if title == "Leave request" and ("Fill form" in footer or "Submit to HR" in footer):
            return True
    return False


async def _purge_extra_leave_forms(channel, keep_id):
    keep = str(keep_id or "")
    try:
        async for message in channel.history(limit=40):
            if str(message.id) == keep:
                continue
            if not is_leave_form_message(message):
                continue
            try:
                await message.delete()
            except Exception:
                pass
    except Exception:
        pass


def _save_form_message_id(bot, channel_id, message_id):
    ticket = bot.store.get_by_channel(channel_id)
    if not ticket:
        return
    bot.store.upsert({**ticket, "leaveFormMessageId": str(message_id) if message_id else ""})


def _save_cancel_form_message_id(bot, channel_id, message_id):
    ticket = bot.store.get_by_channel(channel_id)
    if not ticket:
        return
    bot.store.upsert({**ticket, "cancelFormMessageId": str(message_id) if message_id else ""})


async def clear_cancel_leave_form(bot, channel):
    ticket = bot.store.get_by_channel(channel.id)
    old_id = (ticket or {}).get("cancelFormMessageId")
    await _delete_message(channel, old_id)
    if ticket:
        bot.store.upsert({**ticket, "cancelFormMessageId": ""})


async def publish_cancel_leave_form(bot, channel, card, *, send=None):
    ticket = bot.store.get_by_channel(channel.id)
    old_id = (ticket or {}).get("cancelFormMessageId")
    embed = cancel_leave_embed(card)
    view = cancel_leave_view(bot, card)
    if old_id:
        try:
            old = await channel.fetch_message(int(old_id))
            await old.edit(embed=embed, view=view)
            _save_cancel_form_message_id(bot, channel.id, old.id)
            return old
        except Exception:
            pass
    poster = send or channel.send
    sent = await poster(embed=embed, view=view)
    _save_cancel_form_message_id(bot, channel.id, sent.id)
    return sent


async def handle_cancel_leave_pick(interaction, bot):
    from app.agent.router import apply_cancel_leave_pick

    ticket = bot.store.get_by_channel(interaction.channel_id)
    if not ticket or str(interaction.user.id) != str(ticket.get("userId") or ""):
        await interaction.response.send_message("Only the ticket owner can cancel this leave.", ephemeral=True)
        return
    draft = bot.agent.drafts.get(str(interaction.channel_id)) or {}
    if not draft.get("awaiting_cancel"):
        await interaction.response.send_message("This cancel form is no longer active.", ephemeral=True)
        return
    values = (interaction.data or {}).get("values") or []
    result = apply_cancel_leave_pick(bot.agent, str(interaction.channel_id), values[0] if values else "")
    if result.get("error"):
        await interaction.response.send_message(result["error"], ephemeral=True)
        return
    card = result.get("leaveCard") or {}
    await interaction.response.edit_message(
        embed=cancel_leave_embed(card),
        view=cancel_leave_view(bot, card),
    )
    _save_cancel_form_message_id(bot, interaction.channel_id, interaction.message.id)


async def handle_cancel_leave_fill(interaction, bot):
    ticket = bot.store.get_by_channel(interaction.channel_id)
    if not ticket or str(interaction.user.id) != str(ticket.get("userId") or ""):
        await interaction.response.send_message("Only the ticket owner can cancel this leave.", ephemeral=True)
        return
    draft = bot.agent.drafts.get(str(interaction.channel_id)) or {}
    if not draft.get("awaiting_cancel"):
        await interaction.response.send_message("This cancel form is no longer active.", ephemeral=True)
        return
    if not draft.get("start_date") and len(draft.get("approved") or []) > 1:
        await interaction.response.send_message("Choose which approved leave to cancel first.", ephemeral=True)
        return
    await interaction.response.send_modal(CancelLeaveDetailsModal(bot, draft))


async def handle_cancel_leave_submit(interaction, bot):
    from app.agent.router import user_error_text
    from app.errors import AppError

    ticket = bot.store.get_by_channel(interaction.channel_id)
    if not ticket or str(interaction.user.id) != str(ticket.get("userId") or ""):
        await interaction.response.send_message("Only the ticket owner can cancel this leave.", ephemeral=True)
        return
    owner_id = str(ticket.get("userId") or "")
    await interaction.response.defer()
    identity = {
        "memberName": getattr(interaction.user, "display_name", None) or interaction.user.name,
    }
    try:
        result = await asyncio.to_thread(
            bot.agent._submit_cancel_leave,
            str(interaction.channel_id),
            owner_id,
            identity,
        )
    except AppError as error:
        await interaction.followup.send(user_error_text(error, bot.config["messages"]["userError"]), ephemeral=True)
        return
    if result.get("error"):
        await interaction.followup.send(result["error"], ephemeral=True)
        return
    await clear_cancel_leave_form(bot, interaction.channel)
    await interaction.followup.send(result.get("answer") or "Cancelled.")
    if result.get("saved"):
        from app.discord.notify import notify_decision
        from app.mail.notify import notify_leave_cancelled_mail

        await notify_decision(
            bot,
            result["saved"],
            outcome="cancelled",
            actor="Cancelled by employee",
            guild=interaction.guild,
            ticket_channel=interaction.channel,
        )
        await notify_leave_cancelled_mail(
            bot,
            result["saved"],
            ticket_name=getattr(interaction.channel, "name", "") or "",
        )


async def handle_cancel_leave_dismiss(interaction, bot):
    ticket = bot.store.get_by_channel(interaction.channel_id)
    if not ticket or str(interaction.user.id) != str(ticket.get("userId") or ""):
        await interaction.response.send_message("Only the ticket owner can close this form.", ephemeral=True)
        return
    bot.agent.drafts.pop(str(interaction.channel_id), None)
    await interaction.response.defer()
    await clear_cancel_leave_form(bot, interaction.channel)
    await interaction.followup.send("Okay. No approved leave was cancelled.")


async def clear_leave_form_card(bot, channel):
    ticket = bot.store.get_by_channel(channel.id)
    old_id = (ticket or {}).get("leaveFormMessageId")
    await _delete_message(channel, old_id)
    if ticket:
        bot.store.upsert({**ticket, "leaveFormMessageId": ""})


async def publish_leave_form(bot, channel, card, *, send=None):
    ticket = bot.store.get_by_channel(channel.id)
    old_id = (ticket or {}).get("leaveFormMessageId")
    embed = leave_template_embed(card)
    view = leave_action_view(bot, card)
    if old_id:
        try:
            old = await channel.fetch_message(int(old_id))
            await old.edit(embed=embed, view=view)
            _save_form_message_id(bot, channel.id, old.id)
            await _purge_extra_leave_forms(channel, old.id)
            return old
        except Exception:
            pass
    poster = send or channel.send
    sent = await poster(embed=embed, view=view)
    _save_form_message_id(bot, channel.id, sent.id)
    await _purge_extra_leave_forms(channel, sent.id)
    return sent


def _save_pending_message_id(bot, channel_id, message_id):
    ticket = bot.store.get_by_channel(channel_id)
    if not ticket:
        return
    bot.store.upsert({**ticket, "pendingLeaveMessageId": str(message_id) if message_id else ""})


async def clear_pending_leave_card(bot, channel, *, embed=None):
    ticket = bot.store.get_by_channel(channel.id)
    old_id = (ticket or {}).get("pendingLeaveMessageId")
    if old_id:
        try:
            old = await channel.fetch_message(int(old_id))
            if embed is not None:
                await old.edit(embed=embed, view=None)
            else:
                await old.delete()
        except Exception:
            pass
    if ticket:
        bot.store.upsert({**ticket, "pendingLeaveMessageId": ""})


async def publish_pending_leave(bot, channel, discord_user_id, *, card=None, locale="english", name=None, send=None):
    leave = getattr(getattr(bot, "hr", None), "leave", None)
    if leave is None:
        return None
    if card is None:
        builder = getattr(leave, "pending_card_for_member", None)
        if not callable(builder):
            return None
        card = await asyncio.to_thread(builder, discord_user_id, locale, name)
    if not card:
        await clear_pending_leave_card(bot, channel)
        return None
    ticket = bot.store.get_by_channel(channel.id)
    old_id = (ticket or {}).get("pendingLeaveMessageId")
    embed = leave_pending_embed(card)
    view = leave_pending_view(bot)
    if old_id:
        try:
            old = await channel.fetch_message(int(old_id))
            await old.edit(embed=embed, view=view)
            _save_pending_message_id(bot, channel.id, old.id)
            return old
        except Exception:
            pass
    poster = send or channel.send
    sent = await poster(embed=embed, view=view)
    _save_pending_message_id(bot, channel.id, sent.id)
    if old_id and str(getattr(sent, "id", "")) != str(old_id):
        await _delete_message(channel, old_id)
    return sent


async def ensure_pending_leave_visible(bot, channel, discord_user_id, *, locale="english", name=None):
    leave = getattr(getattr(bot, "hr", None), "leave", None)
    builder = getattr(leave, "pending_card_for_member", None)
    if not callable(builder):
        return
    card = await asyncio.to_thread(builder, discord_user_id, locale, name)
    if not card:
        return
    await publish_pending_leave(bot, channel, discord_user_id, card=card, locale=locale, name=name)


def _owner_draft(interaction, bot):
    ticket = bot.store.get_by_channel(interaction.channel_id)
    if not ticket or ticket.get("status") == "closed":
        return None, "This ticket is closed."
    owner_id = str(ticket.get("userId") or "")
    if str(interaction.user.id) != owner_id:
        return None, "Only the ticket owner can use this form."
    draft = bot.agent.drafts.get(str(interaction.channel_id)) or {}
    if not (draft.get("awaiting_confirm") or draft.get("awaiting_details")):
        return None, "This leave form is no longer active."
    return draft, None


def _pending_leave_message(bot, discord_user_id, locale):
    leave = getattr(getattr(bot, "hr", None), "leave", None)
    checker = getattr(leave, "pending_already_open_error", None)
    if not callable(checker):
        return None
    error = checker(discord_user_id, locale)
    if error is None:
        return None
    return str(error)


async def handle_leave_fill(interaction, bot):
    draft, error = _owner_draft(interaction, bot)
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return
    pending = await asyncio.to_thread(
        _pending_leave_message, bot, str(interaction.user.id), draft.get("locale")
    )
    if pending:
        bot.agent.drafts.pop(str(interaction.channel_id), None)
        await interaction.response.send_message(pending, ephemeral=True)
        return
    await interaction.response.send_modal(LeaveDetailsModal(bot, draft))


async def handle_leave_type(interaction, bot):
    from app.agent.router import apply_leave_type

    draft, error = _owner_draft(interaction, bot)
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return
    pending = await asyncio.to_thread(
        _pending_leave_message, bot, str(interaction.user.id), draft.get("locale")
    )
    if pending:
        bot.agent.drafts.pop(str(interaction.channel_id), None)
        await interaction.response.send_message(pending, ephemeral=True)
        return
    values = (interaction.data or {}).get("values") or []
    leave_type = values[0] if values else ""
    result = apply_leave_type(bot.agent, str(interaction.channel_id), leave_type)
    await interaction.response.edit_message(
        embed=leave_template_embed(result.get("leaveCard") or {}),
        view=leave_action_view(bot, result.get("leaveCard") or {}),
    )
    _save_form_message_id(bot, interaction.channel_id, interaction.message.id)


async def handle_leave_action(interaction, bot, decision):
    from app.agent.router import format_agent_reply, user_error_text
    from app.discord.messages import split_discord_content
    from app.errors import AppError
    from app.routing.channels import namespace_for_channel

    ticket = bot.store.get_by_channel(interaction.channel_id)
    if not ticket or ticket.get("status") == "closed":
        await interaction.response.send_message("This ticket is closed.", ephemeral=True)
        return
    owner_id = str(ticket.get("userId") or "")
    if str(interaction.user.id) != owner_id:
        await interaction.response.send_message("Only the ticket owner can use these buttons.", ephemeral=True)
        return
    draft = bot.agent.drafts.get(str(interaction.channel_id)) or {}
    if not (draft.get("awaiting_confirm") or draft.get("awaiting_details")):
        await interaction.response.send_message("This leave card is no longer active.", ephemeral=True)
        return
    if decision == "yes" and not draft.get("awaiting_confirm"):
        await interaction.response.send_message("Complete the form first, then tap Submit to HR.", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        await interaction.message.edit(view=None)
    except Exception:
        pass
    namespace = ticket.get("namespace") or namespace_for_channel(
        bot.config["discord"]["channels"],
        ticket.get("parentChannelId"),
    )
    owner_member = await fetch_guild_member(interaction.guild, owner_id, interaction.user if str(interaction.user.id) == str(owner_id) else None)
    identity = {
        "botName": bot.config.get("assistantName") or "HR Assistant",
        "companyName": bot.config.get("companyName") or "WebAiry",
        "memberName": getattr(interaction.user, "display_name", None) or interaction.user.name,
        "replyLanguage": draft.get("locale") or "english",
        "memberRoleNames": [
            role.name for role in getattr(owner_member, "roles", []) or [] if getattr(role, "name", None)
        ],
    }
    result = None
    try:
        result = await asyncio.to_thread(
            bot.agent.handle,
            question=decision,
            namespace=namespace,
            channel_id=str(interaction.channel_id),
            discord_user_id=owner_id,
            identity=identity,
            conversation_history=[],
        )
        text = format_agent_reply(result)
    except AppError as error:
        text = user_error_text(error, bot.config["messages"]["userError"])
    if result and result.get("ui") == "leave_pending" and result.get("leaveCard"):
        await clear_leave_form_card(bot, interaction.channel)
        await publish_pending_leave(
            bot,
            interaction.channel,
            owner_id,
            card=result["leaveCard"],
            locale=(result["leaveCard"] or {}).get("locale") or "english",
            send=interaction.followup.send,
        )
        from app.discord.leave_inbox import publish_leave_inbox

        await publish_leave_inbox(
            bot,
            ticket_channel=interaction.channel,
            card=result["leaveCard"],
            employee_id=owner_id,
        )
        if result.get("balanceText"):
            await interaction.channel.send(
                embed=leave_balance_embed(
                    result["balanceText"],
                    name=result.get("employeeName") or "",
                )
            )
        mention = (result.get("answer") or "").strip()
        if mention and "<@&" in mention and not result.get("stickyPending"):
            await interaction.channel.send(mention)
        return
    if result and result.get("ui") in {"leave_form", "leave_confirm"} and result.get("leaveCard"):
        await publish_leave_form(
            bot,
            interaction.channel,
            result["leaveCard"],
            send=interaction.followup.send,
        )
        return
    if result and result.get("ui") == "leave_cancelled":
        await clear_leave_form_card(bot, interaction.channel)
    parts = split_discord_content(text)
    if parts:
        await interaction.followup.send(parts[0])
        for part in parts[1:]:
            await interaction.channel.send(part)


async def _recent_owner_question(channel, owner_id):
    """Latest ticket message from the employee, if it was just sent."""
    try:
        owner = int(str(owner_id or "").strip())
    except (TypeError, ValueError):
        return ""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
    try:
        async for item in channel.history(limit=12):
            if getattr(item.author, "bot", False):
                continue
            if int(getattr(item.author, "id", 0) or 0) != owner:
                continue
            created = getattr(item, "created_at", None)
            if created is not None:
                when = created if getattr(created, "tzinfo", None) else created.replace(tzinfo=timezone.utc)
                if when < cutoff:
                    return ""
            return str(item.content or "").strip()
    except Exception:
        return ""
    return ""


async def handle_leave_withdraw(interaction, bot):
    from app.agent.router import user_error_text
    from app.agent.verification import recent_question_should_not_withdraw
    from app.errors import AppError

    ticket = bot.store.get_by_channel(interaction.channel_id)
    if not ticket or ticket.get("status") == "closed":
        await interaction.response.send_message("This ticket is closed.", ephemeral=True)
        return
    owner_id = str(ticket.get("userId") or "")
    if str(interaction.user.id) != owner_id:
        await interaction.response.send_message("Only the ticket owner can withdraw this leave request.", ephemeral=True)
        return
    recent = await _recent_owner_question(interaction.channel, owner_id)
    if recent_question_should_not_withdraw(recent):
        await interaction.response.send_message(
            "Your leave request is still with HR. That last message looked like a question, not a withdraw. "
            "Type **withdraw** if you want to cancel it.",
            ephemeral=True,
        )
        return
    leave = getattr(getattr(bot, "hr", None), "leave", None)
    if leave is None:
        await interaction.response.send_message("HR data is not connected yet.", ephemeral=True)
        return
    await interaction.response.defer()
    name = getattr(interaction.user, "display_name", None) or interaction.user.name
    try:
        saved = await asyncio.to_thread(
            leave.withdraw_pending_for_member,
            owner_id,
            withdrawn_by=f"{name} ({owner_id})",
        )
    except AppError as error:
        await interaction.followup.send(user_error_text(error, "Could not withdraw that leave request."))
        return
    card = {
        "locale": "english",
        "leave_type": saved.get("leaveType") or "Leave",
        "start_date": saved.get("startDate"),
        "end_date": saved.get("endDate"),
        "days": saved.get("daysRequested") or 1,
        "name": saved.get("employeeName") or name,
        "reason": saved.get("reason") or "",
    }
    try:
        await interaction.message.edit(embed=leave_withdrawn_embed(card), view=None)
    except Exception:
        await interaction.followup.send(embed=leave_withdrawn_embed(card))
    else:
        await interaction.followup.send("Your leave request was withdrawn. You can apply again when you are ready.")
    _save_pending_message_id(bot, interaction.channel_id, "")
    from app.discord.leave_inbox import finalize_leave_inbox

    await finalize_leave_inbox(bot, str(interaction.channel_id), remove=True)
    from app.discord.notify import notify_decision

    await notify_decision(
        bot,
        {**saved, "discordUserId": owner_id},
        outcome="withdrawn",
        actor=f"Withdrawn by {name}",
        guild=interaction.guild,
        ticket_channel=interaction.channel,
    )

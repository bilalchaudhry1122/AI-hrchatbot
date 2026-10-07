"""Approving leave from inside Discord.

Approve and Decline are Admin or HR only. Staff see Withdraw on the ticket card.
Who may act is decided in Python from Discord Admin/HR roles, never by the model.
HOD/HR use the Approve and Reject buttons on the leave-channel card.
"""

import asyncio

import discord

from app.discord.notify import notify_decision
from app.errors import AppError
from app.hr.dates import format_display_date
from app.hr.leave_status import ADMIN, EMPLOYEE, HR, MANAGER, display_status, stage_for
from app.hr.permissions import is_hr_admin, is_hr_member, tier_for

LEAVE_APPROVE_ID = "leave:review:approve"
LEAVE_REJECT_ID = "leave:review:reject"

QUEUE_COLOR = 0x1D4ED8
DECISION_COLOR = {"approve": 0x15803D, "reject": 0xB91C1C}


def _qty(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "—")
    return str(int(number)) if number.is_integer() else str(number)


def _span(request):
    start = format_display_date(request.get("startDate"))
    end = format_display_date(request.get("endDate")) or start
    if start and end and start != end:
        return f"{start} – {end}"
    return start or end or "—"


def ticket_channel_from(channel):
    """The ticket GuildText channel, even when the click happened in an HR thread."""
    parent = getattr(channel, "parent", None)
    if parent is not None:
        return parent
    return channel


def ticket_channel_id_from(interaction, bot=None):
    from app.discord.leave_inbox import ticket_channel_id_from_message

    message = getattr(interaction, "message", None)
    ticket_id = ticket_channel_id_from_message(message, bot)
    if ticket_id:
        return ticket_id
    channel = getattr(interaction, "channel", None)
    parent = getattr(channel, "parent", None)
    if parent is not None:
        return str(getattr(parent, "id", "") or "")
    return str(getattr(interaction, "channel_id", "") or "")


def _leave_name(request, client=None, logger=None):
    from app.records.leave_types import public_leave_type_name_for_client

    return public_leave_type_name_for_client(
        client,
        (request or {}).get("leaveType") or (request or {}).get("leave_type"),
        logger=logger,
    )


async def resolve_tier(bot, interaction, employee_discord_id=None):
    """Work out the actor's tier, checking the line-manager link if needed."""
    member = interaction.user
    is_line_manager = False
    leave = getattr(getattr(bot, "hr", None), "leave", None)
    if employee_discord_id and leave is not None:
        checker = getattr(leave, "is_line_manager_of", None)
        if callable(checker):
            try:
                is_line_manager = await asyncio.to_thread(
                    checker, str(member.id), str(employee_discord_id)
                )
            except AppError:
                is_line_manager = False
    tier = tier_for(member, bot.config, is_line_manager=is_line_manager)
    return tier, is_line_manager


class RejectReasonModal(discord.ui.Modal, title="Decline this leave"):
    """A reason is optional, but it is shown to the employee when given."""

    def __init__(self, bot, *, tier, is_line_manager):
        super().__init__()
        self.bot = bot
        self.tier = tier
        self.is_line_manager = is_line_manager
        self.reason_input = discord.ui.TextInput(
            label="Reason for declining (optional)",
            placeholder="Optional. The employee sees this if you fill it in.",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=400,
        )
        self.add_item(self.reason_input)
        from app.discord.attachments import reason_file_upload

        label, self.reason_files = reason_file_upload(custom_id="leave:reject:files")
        self.add_item(label)

    async def on_submit(self, interaction: discord.Interaction):
        from app.discord.attachments import format_reason_with_files, meta_from_upload

        reason = format_reason_with_files(
            str(self.reason_input.value or "").strip(),
            meta_from_upload(self.reason_files),
        )
        await apply_decision(
            interaction,
            self.bot,
            decision="reject",
            reason=reason,
            tier=self.tier,
            is_line_manager=self.is_line_manager,
            files=list(self.reason_files.values or []),
        )


class LeaveReviewView(discord.ui.View):
    """Approve / Reject on the Admin/HR #leave-requests inbox."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        approve = discord.ui.Button(
            label="Approve",
            style=discord.ButtonStyle.success,
            custom_id=LEAVE_APPROVE_ID,
        )
        reject = discord.ui.Button(
            label="Reject",
            style=discord.ButtonStyle.danger,
            custom_id=LEAVE_REJECT_ID,
        )

        async def approve_cb(interaction: discord.Interaction):
            await handle_review_click(interaction, self.bot, "approve")

        async def reject_cb(interaction: discord.Interaction):
            await handle_review_click(interaction, self.bot, "reject")

        approve.callback = approve_cb
        reject.callback = reject_cb
        self.add_item(approve)
        self.add_item(reject)


async def _open_request_in(bot, channel_id):
    leave = getattr(getattr(bot, "hr", None), "leave", None)
    if leave is None:
        return None
    from app.records.leave_requests import get_open_request_by_ticket_channel

    try:
        return await asyncio.to_thread(
            get_open_request_by_ticket_channel, bot.hr.client, str(channel_id), logger=bot.logger
        )
    except AppError:
        return None


async def _review_reply(interaction, text):
    """Ack or follow up; never leave Discord showing a failed interaction."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        pass


async def _may_review(interaction, bot, tier):
    from app.discord.leave_inbox import is_hod_inbox_channel, is_leave_review_channel

    channel = getattr(interaction, "channel", None)
    if is_hod_inbox_channel(channel, bot.config):
        # The HOD inbox is notification-only. HOD (and everyone else except
        # Admin) can look but never decide from there.
        if tier == ADMIN:
            return True, ""
        return False, "This is a notification-only channel. Only HR (in #leave-requests) can approve or decline."
    if is_leave_review_channel(channel, bot.config):
        if tier in {HR, ADMIN}:
            return True, ""
        return False, "Only Admin or HR can approve or decline leave requests."
    return tier in {HR, ADMIN}, "Only Admin or HR can approve or decline this leave request."


async def handle_review_click(interaction, bot, decision):
    try:
        # Acknowledge Discord first so the buttons never fail the 3-second window.
        if decision == "reject" and not interaction.response.is_done():
            tier, is_line_manager = await resolve_tier(bot, interaction, None)
            allowed, message = await _may_review(interaction, bot, tier)
            if not allowed:
                await _review_reply(interaction, message)
                return
            await interaction.response.send_modal(
                RejectReasonModal(bot, tier=tier, is_line_manager=is_line_manager)
            )
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)
        if getattr(bot, "hr", None) is None:
            await _review_reply(interaction, "HR data is not connected yet.")
            return
        tier, is_line_manager = await resolve_tier(bot, interaction, None)
        allowed, message = await _may_review(interaction, bot, tier)
        if not allowed:
            await _review_reply(interaction, message)
            return
        ticket_id = ticket_channel_id_from(interaction, bot)
        request = await _open_request_in(bot, ticket_id)
        if not request:
            await _review_reply(
                interaction,
                "There is no leave request waiting for a decision.",
            )
            return
        if str(interaction.user.id) == str(request.get("discordUserId")):
            await _review_reply(interaction, "You cannot approve your own leave request.")
            return
        await apply_decision(
            interaction,
            bot,
            decision="approve",
            reason="",
            tier=tier,
            is_line_manager=is_line_manager,
            deferred=True,
        )
    except Exception as error:
        bot.logger.error("leave review click failed", {"message": str(error)})
        await _review_reply(
            interaction,
            "Could not complete that decision. Try the Approve or Reject button again.",
        )


async def apply_decision(interaction, bot, *, decision, reason, tier, is_line_manager, deferred=False, files=None):
    """Run the decision and report it in the ticket and by DM."""
    if not deferred:
        await interaction.response.defer(ephemeral=True, thinking=False)
    actor_name = getattr(interaction.user, "display_name", None) or str(interaction.user)
    from app.discord.journey import discord_handle, workplace_role_label

    actor_handle = discord_handle(interaction.user) or actor_name
    actor_role = workplace_role_label(interaction.user, bot.config) or "HR"
    ticket_channel_id = ticket_channel_id_from(interaction, bot)
    from app.discord.leave_inbox import is_hod_inbox_channel

    try:
        saved = await asyncio.to_thread(
            bot.hr.leave.decide_in_ticket,
            ticket_channel_id=str(ticket_channel_id or interaction.channel_id),
            actor_id=str(interaction.user.id),
            actor_name=actor_name,
            tier=tier,
            decision=decision,
            reason=reason,
            is_line_manager=is_line_manager,
            hod_first=is_hod_inbox_channel(interaction.channel, bot.config),
        )
    except AppError as error:
        from app.agent.router import user_error_text

        bot.logger.info("leave decision", {"ok": False, "code": error.code, "tier": tier})
        await _review_reply(
            interaction,
            user_error_text(error, bot.config["messages"]["userError"]),
        )
        return None

    finalised = saved.get("finalised", True)
    if decision == "approve" and not finalised:
        outcome = "moved"
    elif decision == "approve":
        outcome = "approved"
    else:
        outcome = "rejected"

    from app.discord.leave_inbox import is_leave_inbox_channel

    in_inbox = is_leave_inbox_channel(interaction.channel, bot.config)
    ticket_channel = None
    if ticket_channel_id and interaction.guild:
        try:
            ticket_channel = interaction.guild.get_channel(int(ticket_channel_id))
        except (TypeError, ValueError):
            ticket_channel = None
    if ticket_channel is None and not in_inbox:
        ticket_channel = ticket_channel_from(interaction.channel)
    stored = bot.store.get_by_channel(ticket_channel_id) if ticket_channel_id else None
    ticket_name = str(
        getattr(ticket_channel, "name", "")
        or (stored or {}).get("channelName")
        or ""
    )
    from app.discord.leave_inbox import polish_reviewer_card

    saved = polish_reviewer_card(
        saved,
        client=bot.hr.client if bot.hr else None,
        logger=bot.logger,
        ticket_name=ticket_name,
    )
    summary = decision_summary_embed(
        saved,
        outcome=outcome,
        actor=actor_handle,
        ticket_channel_id=ticket_channel_id,
        ticket_name=ticket_name,
    )
    try:
        await interaction.message.edit(embed=summary, view=None)
    except discord.HTTPException as error:
        bot.logger.warn("Could not update leave inbox card", {"message": str(error)})
    try:
        if in_inbox:
            await interaction.followup.send("Leave updated.", ephemeral=True)
        else:
            await interaction.followup.send(embed=summary, ephemeral=True)
    except discord.HTTPException as error:
        bot.logger.warn("Could not send leave decision followup", {"message": str(error)})
    from app.discord.attachments import files_from_upload

    upload = type("Upload", (), {"values": list(files or [])})()
    ticket_files = await files_from_upload(upload)
    dm_files = await files_from_upload(upload)
    if ticket_channel is not None and str(getattr(ticket_channel, "id", "")) != str(interaction.channel_id):
        try:
            kwargs = {"embed": summary}
            if ticket_files:
                kwargs["files"] = ticket_files
            await ticket_channel.send(**kwargs)
        except discord.HTTPException:
            pass
    try:
        await notify_decision(
            bot,
            saved,
            outcome=outcome,
            actor=f"{'Approved' if decision == 'approve' else 'Declined'} by {actor_handle}",
            guild=interaction.guild,
            ticket_channel=ticket_channel or (None if in_inbox else interaction.channel),
            files=dm_files or None,
        )
    except Exception as error:
        bot.logger.warn("Leave decision notify failed", {"message": str(error)})
    from app.discord.leave_inbox import finalize_leave_inbox
    from app.discord.leave_ui import clear_pending_leave_card, ensure_pending_leave_visible, leave_balance_embed

    try:
        await finalize_leave_inbox(bot, ticket_channel_id, embed=summary)
    except Exception as error:
        bot.logger.warn("Could not update leave-requests card", {"message": str(error)})
    if outcome == "moved":
        from app.discord.leave_inbox import publish_leave_inbox

        card = {
            "leave_type": saved.get("leaveType"),
            "start_date": saved.get("startDate"),
            "end_date": saved.get("endDate"),
            "days": saved.get("daysRequested"),
            "name": saved.get("employeeName"),
            "reason": saved.get("reason"),
            "status": saved.get("status"),
            "department": saved.get("department"),
            "needsHod": False,
        }
        if ticket_channel is not None:
            try:
                await publish_leave_inbox(
                    bot,
                    ticket_channel=ticket_channel,
                    card=card,
                    employee_id=str(saved.get("discordUserId") or ""),
                )
            except Exception as error:
                bot.logger.warn("Could not post leave to HR inbox", {"message": str(error)})
        await ensure_pending_leave_visible(bot, ticket_channel or interaction.channel, str(saved.get("discordUserId") or ""))
        stored = bot.store.get_by_channel(ticket_channel_id) if ticket_channel_id else None
        if stored:
            bot.store.upsert({
                **stored,
                "hodApprovedBy": saved.get("managerApprovedBy") or actor_handle,
                "hodApprovedName": actor_handle,
                "hodApprovedId": str(interaction.user.id),
            })
        return saved
    if ticket_channel is not None:
        await clear_pending_leave_card(bot, ticket_channel)
    if outcome == "approved" and ticket_channel is not None:
        try:
            live = await asyncio.to_thread(
                bot.hr.leave.get_my_leave_snapshot, saved.get("discordUserId")
            )
            await ticket_channel.send(
                embed=leave_balance_embed(
                    live["text"],
                    name=((live.get("employee") or {}).get("name") or saved.get("employeeName") or ""),
                )
            )
        except (AppError, discord.HTTPException):
            pass
    if outcome == "approved":
        try:
            from app.mail.notify import notify_leave_approved_mail

            await notify_leave_approved_mail(bot, saved, ticket_name=ticket_name)
        except Exception as error:
            bot.logger.warn("Leave approved mail failed", {"message": str(error)[:200]})
    return saved


def decision_summary_embed(request, *, outcome, actor="", ticket_channel_id="", ticket_name=""):
    titles = {
        "approved": "Leave approved",
        "rejected": "Leave declined",
        "moved": "Approved by HOD, sent to HR",
    }
    embed = discord.Embed(
        title=titles.get(outcome, "Leave updated"),
        color=DECISION_COLOR.get("approve" if outcome != "rejected" else "reject", 0x1E293B),
    )
    embed.set_author(name="Human Resources")
    status_labels = {
        "approved": "**Approved**",
        "rejected": "**Rejected**",
        "moved": "**Waiting for HR**",
    }
    embed.add_field(name="Status", value=status_labels.get(outcome, "Updated"), inline=True)
    embed.add_field(name="Employee", value=request.get("employeeName") or "—", inline=True)
    embed.add_field(name="Leave type", value=_leave_name(request, None), inline=True)
    embed.add_field(name="Days", value=_qty(request.get("daysRequested")), inline=True)
    embed.add_field(name="Dates", value=_span(request), inline=False)
    if outcome == "rejected":
        # Always shown, so the reviewer can see what the employee was told.
        from app.discord.attachments import add_attachment_preview, parse_reason_and_files

        note = str(request.get("rejectionReason") or "").strip()
        body, files = parse_reason_and_files(note)
        embed.add_field(
            name="Reason given",
            value=body[:1000] if body else "None recorded — the employee was asked to raise it in the ticket.",
            inline=False,
        )
        add_attachment_preview(embed, files)
    if outcome == "approved" and request.get("remaining") is not None:
        embed.add_field(name="Remaining", value=_qty(request.get("remaining")), inline=True)
    if outcome == "moved":
        embed.add_field(name="Now with", value=display_status(request.get("status")), inline=True)
    from app.discord.leave_inbox import ticket_field_text

    embed.add_field(
        name="Ticket",
        value=ticket_field_text(
            display_name=request.get("employeeName"),
            channel_name=ticket_name,
            channel_id="",
        ),
        inline=False,
    )
    footer = []
    if actor:
        verb = {
            "approved": "Approved by",
            "rejected": "Rejected by",
            "moved": "Approved by",
        }.get(outcome, "Decided by")
        footer.append(f"{verb} {actor}")
    if footer:
        embed.set_footer(text=" · ".join(footer))
    return embed


def queue_embed(rows, *, tier, viewer_name=""):
    """What is waiting for this person to decide."""
    label = {ADMIN: "Admin", HR: "HR", MANAGER: "HOD"}.get(tier, "You")
    embed = discord.Embed(
        title=f"Leave waiting for {label}",
        color=QUEUE_COLOR,
        description=(
            "Nothing is waiting for you right now."
            if not rows
            else f"{len(rows)} request(s) need a decision. Open a ticket to approve or decline."
        ),
    )
    embed.set_author(name="Human Resources")
    for request in rows[:20]:
        channel_id = request.get("ticketChannelId")
        where = f"<#{channel_id}>" if channel_id else "ticket unknown"
        embed.add_field(
            name=f"{request.get('employeeName') or 'Employee'} · {_leave_name(request)}",
            value=(
                f"{_span(request)} · {_qty(request.get('daysRequested'))} day(s)\n"
                f"{display_status(request.get('status'))} · {where}"
            ),
            inline=False,
        )
    if len(rows) > 20:
        embed.set_footer(text=f"Showing 20 of {len(rows)}")
    elif rows:
        embed.set_footer(text="Oldest first")
    return embed


def calendar_embed(calendar, *, member_name=""):
    """The employee's own upcoming leave."""
    approved = calendar.get("approved") or []
    waiting = calendar.get("waiting") or []
    embed = discord.Embed(
        title="Your leave calendar",
        color=0x0F766E,
        description=(
            "You have no upcoming leave booked."
            if not approved and not waiting
            else "Everything coming up, newest dates first."
        ),
    )
    embed.set_author(name="Human Resources")
    if approved:
        embed.add_field(
            name="Approved",
            value="\n".join(
                f"• **{_leave_name(item)}** — {_span(item)} · {_qty(item.get('daysRequested'))} day(s)"
                for item in approved[:10]
            ),
            inline=False,
        )
    if waiting:
        embed.add_field(
            name="Waiting for a decision",
            value="\n".join(
                f"• **{_leave_name(item)}** — {_span(item)} · {display_status(item.get('status'))}"
                for item in waiting[:10]
            ),
            inline=False,
        )
    if member_name:
        embed.set_footer(text=member_name)
    return embed

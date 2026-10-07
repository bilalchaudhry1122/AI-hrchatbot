import asyncio
import re

import discord
from discord import app_commands

from app.agent.draft_store import create_draft_store
from app.agent.router import AgentRouter, format_agent_reply, user_error_text
from app.discord.leave_ui import (
    CancelLeaveView,
    LeaveActionView,
    LeavePendingView,
    clear_leave_form_card,
    clear_pending_leave_card,
    ensure_pending_leave_visible,
    fetch_guild_member,
    leave_balance_embed,
    leave_withdrawn_embed,
    publish_leave_form,
    publish_pending_leave,
    publish_cancel_leave_form,
    clear_cancel_leave_form,
)
from app.discord.leave_review import LeaveReviewView, calendar_embed, queue_embed
from app.discord.messages import split_discord_content
from app.discord.notify import notify_decision
from app.discord.onboarding import OnboardingStartView, ensure_onboarding_channel, ensure_onboarding_panel
from app.discord.profile_lookup import (
    ensure_hr_profile_channel,
    run_profile_delete,
    run_profile_lookup,
)
from app.discord.announcements import ensure_announcement_channel, start_birthday_task
from app.discord.hr_announcements import (
    ensure_hr_announcement_channel,
    maybe_handle_hr_announcement_message,
    start_hr_announcement_task,
)
from app.discord.tickets import (
    CLOSE_TICKET_ID,
    OPEN_TICKET_ID,
    already_open_ticket_notice,
    create_ticket_manager,
    open_ticket_panel,
)
from app.errors import AppError, ErrorCodes
from app.routing.channels import namespace_for_channel, should_handle_message, strip_bot_mention
from app.routing.intent import classify_social, social_fallback_reply
from app.hr.leave_status import ADMIN, EMPLOYEE, HR, MANAGER
from app.hr.permissions import is_hr_admin, is_hr_member, tier_for
from app.records.discord_roles import delete_discord_role, sync_guild_roles, upsert_discord_role
from app.hr.staff_onboard import hod_for_guild_member, hr_role_for_guild_member, kind_for_guild_member, member_sync_key, upsert_staff_employee
from app.tickets.helpers import (
    can_close_ticket,
    find_admin_role_id,
    find_staff_role_id,
    is_admin_member,
)
from app.sessions.store import create_session_store
from app.sessions.followup import is_session_followup
from app.tickets.store import create_ticket_store


async def ensure_leave_inboxes(bot, guild):
    from app.discord.leave_inbox import ensure_hod_channels, ensure_leave_review_channel

    await ensure_leave_review_channel(bot, guild)
    await ensure_hod_channels(bot, guild)


async def apply_bot_display_name(bot):
    """Discord shows this name in the member list. Keep it as HR Assistant."""
    wanted = str(bot.config.get("assistantName") or "HR Assistant").strip() or "HR Assistant"
    user = bot.user
    if user is not None and str(getattr(user, "name", "") or "") != wanted:
        try:
            await user.edit(username=wanted)
            bot.logger.info("Discord bot renamed", {"name": wanted})
        except discord.HTTPException as error:
            bot.logger.warn("Could not rename Discord bot", {"message": str(error)})
    for guild in bot.guilds:
        me = guild.me
        if me is None:
            continue
        shown = str(me.nick or me.name or "")
        if shown == wanted:
            continue
        try:
            await me.edit(nick=wanted)
        except discord.HTTPException as error:
            bot.logger.warn("Could not set bot nickname", {"guild": str(guild.id), "message": str(error)})


async def send_discord_text(message, text, *, mention_author=False):
    """Post text in 2000-character chunks. Discord rejects anything longer.

    Always uses channel.send, not reply. Replying to a leave card and then
    replacing that card leaves a broken “Message could not be loaded” quote.
    """
    del mention_author
    parts = split_discord_content(text)
    if not parts:
        return
    channel = message.channel
    for part in parts:
        await channel.send(part)


class SupportBot(discord.Client):
    def __init__(self, *, config, logger, rag, hr=None):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(intents=intents)
        self.config = config
        self.logger = logger
        self.rag = rag
        self.hr = hr
        self.sessions = create_session_store(config["rootDir"] / "sessions.json")
        self.agent = AgentRouter(
            config=config,
            logger=logger,
            rag=rag,
            hr=hr,
            drafts=create_draft_store(config["rootDir"] / "leave_drafts.json", logger=logger),
            sessions=self.sessions,
        )
        self.tree = app_commands.CommandTree(self)
        self.store = create_ticket_store(config["rootDir"] / "tickets.json", logger=logger)
        self.tickets = create_ticket_manager(
            config,
            logger,
            self.store,
            close_view=lambda: CloseTicketView(self),
            sessions=self.sessions,
        )
        self.tickets.bot = self
        self.handling = set()
        self._staff_syncing = set()
        # The backfill runs once per process, not on every gateway reconnect.
        self._members_synced = False

    async def setup_hook(self):
        self.add_view(OpenTicketView(self))
        self.add_view(CloseTicketView(self))
        self.add_view(LeaveActionView(self))
        self.add_view(LeavePendingView(self))
        self.add_view(CancelLeaveView(self))
        self.add_view(LeaveReviewView(self))
        self.add_view(OnboardingStartView(self))
        self.tree.add_command(leave_command)
        self.tree.add_command(close_command)
        self.tree.add_command(help_command)
        self.tree.add_command(pending_command)
        self.tree.add_command(myleave_command)
        self.tree.add_command(profile_command)
        self.tree.add_command(deleteprofile_command)
        if self.config["hr"].get("whoamiEnabled", True):
            self.tree.add_command(whoami_command)

    async def on_ready(self):
        self.logger.info("Discord bot online", {
            "user": str(self.user),
            "guilds": len(self.guilds),
            "mappedChannels": len(self.config["discord"]["channels"]),
            "echoMode": self.config["echoMode"],
            "tickets": self.config["discord"]["tickets"]["enabled"],
            "ticketCategory": self.config["discord"]["tickets"]["categoryId"] or None,
        })
        await apply_bot_display_name(self)
        await ensure_open_ticket_panels(self)
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                self.logger.info("Registered slash commands")
            except discord.HTTPException as error:
                self.logger.warn("Could not register /leave", {"message": str(error)})
            await self.tickets.remove_old_thread_tickets(guild)
            await self.tickets.move_tickets_into_category(guild)
            await self.tickets.grant_admin_access(guild)
            await ensure_leave_inboxes(self, guild)
            onboarding_channel = await ensure_onboarding_channel(self, guild)
            if onboarding_channel is not None:
                await ensure_onboarding_panel(self, onboarding_channel)
            await ensure_hr_profile_channel(self, guild)
            await ensure_announcement_channel(self, guild)
            await ensure_hr_announcement_channel(self, guild)
            if not guild.chunked:
                try:
                    await guild.chunk()
                except discord.HTTPException as error:
                    self.logger.warn("Could not load member list", {"message": str(error)})
            await sync_guild_role_catalog(self, guild)
            await sync_existing_members(self, guild)
        await disable_welcome_in_ticket_channels(self)
        start_birthday_task(self)
        start_hr_announcement_task(self)

    async def on_member_join(self, member):
        await sync_staff_member(self, member, reason="join")
        asyncio.create_task(_sync_member_after_delay(self, member, reason="join-delayed"))

    async def on_guild_role_create(self, role):
        await sync_one_guild_role(self, role, reason="create")
        await resync_members_with_role(self, role)

    async def on_guild_role_update(self, before, after):
        await sync_one_guild_role(self, after, reason="update")
        if getattr(before, "name", None) != getattr(after, "name", None):
            await resync_members_with_role(self, after)
        if getattr(before, "permissions", None) != getattr(after, "permissions", None) or getattr(
            before, "name", None
        ) != getattr(after, "name", None):
            await ensure_leave_inboxes(self, after.guild)

    async def on_guild_role_delete(self, role):
        await drop_guild_role(self, getattr(role, "id", None))

    async def on_member_update(self, before, after):
        if _member_roles_changed(before, after, self.config):
            await sync_staff_member(self, after, reason="role")

    async def on_raw_member_update(self, payload):
        guild = self.get_guild(payload.guild_id)
        if guild is None:
            return
        before = getattr(payload, "cached_member", None)
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.HTTPException:
                return
        if _member_roles_changed(before, member, self.config):
            await sync_staff_member(self, member, reason="role-raw")

    async def on_guild_channel_delete(self, channel):
        if self.store.get_by_channel(channel.id):
            self.store.remove(channel.id)
            self.logger.info("Ticket channel deleted; conversation context cleared", {"channel": str(channel.id)})

    async def on_message(self, message):
        if is_welcome_noise(message, self.config):
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return
        if message.id in self.handling:
            return
        self.handling.add(message.id)
        replied = False
        try:
            if await maybe_handle_hr_announcement_message(self, message):
                return
            replied = await handle_message(self, message)
        except Exception as error:
            self.logger.error("Message handling failed", {
                "code": getattr(error, "code", type(error).__name__),
                "message": str(error),
            })
            ticket = self.store.get_by_channel(message.channel.id)
            if not replied and ticket and ticket.get("botActive") is not False:
                try:
                    await message.channel.send(self.config["messages"]["userError"])
                except discord.HTTPException as reply_error:
                    self.logger.error("Discord reply failed", {"message": str(reply_error)})
        finally:
            await asyncio.sleep(0)
            self.loop.call_later(60, lambda: self.handling.discard(message.id))


class OpenTicketView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        open_btn = discord.ui.Button(
            label="Open ticket",
            style=discord.ButtonStyle.success,
            emoji="🎫",
            custom_id=OPEN_TICKET_ID,
        )

        async def open_cb(interaction: discord.Interaction):
            await handle_open_ticket_button(interaction, self.bot)

        open_btn.callback = open_cb
        self.add_item(open_btn)


class CloseTicketView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        close_btn = discord.ui.Button(
            label="Close ticket",
            style=discord.ButtonStyle.secondary,
            custom_id=CLOSE_TICKET_ID,
        )

        async def close_cb(interaction: discord.Interaction):
            await on_ticket_button(interaction, self.bot)

        close_btn.callback = close_cb
        self.add_item(close_btn)


async def close_ticket_from_interaction(interaction: discord.Interaction, bot: SupportBot):
    ticket = bot.store.get_by_channel(interaction.channel_id)
    if not ticket:
        await interaction.response.send_message("Use `/close` inside a ticket.", ephemeral=True)
        return False
    if ticket.get("status") == "closed":
        await interaction.response.send_message("This ticket is already closed.", ephemeral=True)
        return False
    roles = [{"id": str(role.id), "name": role.name} for role in interaction.guild.roles] if interaction.guild else []
    if not can_close_ticket(
        interaction.user.id,
        interaction.user,
        ticket,
        {
            "staffRoleId": find_staff_role_id(roles, bot.config["discord"]["tickets"]["staffRoleId"]),
            "adminRoleId": find_admin_role_id(roles, bot.config["discord"]["tickets"]["adminRoleId"]),
        },
    ):
        await interaction.response.send_message(
            "Only the ticket owner, Staff, or Admin can close this ticket.",
            ephemeral=True,
        )
        return False
    await bot.tickets.close_ticket(
        interaction.channel,
        ticket,
        interaction.user,
        respond=interaction.response.send_message,
    )
    return True


async def on_ticket_button(interaction: discord.Interaction, bot: SupportBot):
    custom_id = interaction.data.get("custom_id") if interaction.data else None
    if custom_id == OPEN_TICKET_ID:
        await handle_open_ticket_button(interaction, bot)
        return
    if custom_id != CLOSE_TICKET_ID:
        return
    await close_ticket_from_interaction(interaction, bot)


@app_commands.command(name="close", description="Close this support ticket. Staff and Admin can use this.")
async def close_command(interaction: discord.Interaction):
    bot: SupportBot = interaction.client
    await close_ticket_from_interaction(interaction, bot)


@app_commands.command(name="leave", description="Admin or HR: bot leaves this ticket so people can talk.")
async def leave_command(interaction: discord.Interaction):
    bot: SupportBot = interaction.client
    ticket = bot.store.get_by_channel(interaction.channel_id)
    if not ticket:
        await interaction.response.send_message("Use `/leave` inside a ticket.", ephemeral=True)
        return
    if not can_ask_bot_to_leave(interaction.user, bot.config, interaction.guild):
        await interaction.response.send_message(
            "Only Admin or HR can ask the bot to leave this ticket.", ephemeral=True
        )
        return
    if ticket.get("botActive") is False:
        await interaction.response.send_message("The bot has already left this chat.", ephemeral=True)
        return
    await interaction.response.send_message("Leaving this ticket chat.", ephemeral=True)
    await leave_ticket_chat(interaction.channel, bot.store, bot.logger)


@app_commands.command(name="whoami", description="Show your linked employee record (temporary).")
async def whoami_command(interaction: discord.Interaction):
    bot: SupportBot = interaction.client
    if not bot.config["hr"].get("whoamiEnabled", True):
        await interaction.response.send_message("This command is disabled.", ephemeral=True)
        return
    if bot.hr is None:
        await interaction.response.send_message("HR data is not connected yet. Please contact HR.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        text = await asyncio.to_thread(bot.hr.employees.whoami_text, str(interaction.user.id))
    except AppError as error:
        bot.logger.info("employee lookup", {"ok": False})
        text = user_error_text(error, "Your Discord account is not linked to an employee record. Please contact HR.")
    await interaction.followup.send(text, ephemeral=True)


async def _actor_tier(bot, interaction, employee_discord_id=None):
    from app.discord.leave_review import resolve_tier

    return await resolve_tier(bot, interaction, employee_discord_id)


@app_commands.command(name="pending", description="Show the leave requests waiting for your decision.")
async def pending_command(interaction: discord.Interaction):
    bot: SupportBot = interaction.client
    if bot.hr is None:
        await interaction.response.send_message("HR data is not connected yet.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    tier, _ = await _actor_tier(bot, interaction)
    if tier not in {ADMIN, HR, MANAGER}:
        await interaction.followup.send(
            "Only Admin, HR, or a department HOD has a leave approval queue. "
            "Use `/myleave` to see your own leave.",
            ephemeral=True,
        )
        return
    try:
        rows = await asyncio.to_thread(
            bot.hr.leave.queue_for_actor,
            discord_user_id=str(interaction.user.id),
            tier=tier,
        )
    except AppError as error:
        await interaction.followup.send(
            user_error_text(error, bot.config["messages"]["userError"]), ephemeral=True
        )
        return
    bot.logger.info("leave queue viewed", {"tier": tier, "count": len(rows)})
    await interaction.followup.send(embed=queue_embed(rows, tier=tier), ephemeral=True)


@app_commands.command(name="help", description="What the HR assistant can help you with.")
async def help_command(interaction: discord.Interaction):
    from app.discord.journey import help_embed

    await interaction.response.send_message(embed=help_embed("english"), ephemeral=True)


@app_commands.command(name="profile", description="HR only: look up an employee profile by Discord ID or name.")
@app_commands.describe(query="Discord user ID, @mention, or name")
async def profile_command(interaction: discord.Interaction, query: str):
    bot: SupportBot = interaction.client
    await run_profile_lookup(interaction, bot, query)


@app_commands.command(
    name="deleteprofile",
    description="HR only: delete an employee profile from the DB and kick them from the server.",
)
@app_commands.describe(query="Discord user ID, @mention, or name")
async def deleteprofile_command(interaction: discord.Interaction, query: str):
    bot: SupportBot = interaction.client
    await run_profile_delete(interaction, bot, query)


@app_commands.command(name="myleave", description="Show your own upcoming leave.")
async def myleave_command(interaction: discord.Interaction):
    bot: SupportBot = interaction.client
    if bot.hr is None:
        await interaction.response.send_message("HR data is not connected yet.", ephemeral=True)
        return
    from app.hr.leave_access import leave_disabled_for_roles, leave_disabled_message

    role_names = [role.name for role in getattr(interaction.user, "roles", []) or [] if getattr(role, "name", None)]
    if leave_disabled_for_roles(role_names):
        await interaction.response.send_message(leave_disabled_message("english"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        calendar = await asyncio.to_thread(
            bot.hr.leave.leave_calendar,
            str(interaction.user.id),
            role_names=role_names,
        )
    except AppError as error:
        await interaction.followup.send(
            user_error_text(error, "I could not read your leave. Please contact HR."),
            ephemeral=True,
        )
        return
    name = getattr(interaction.user, "display_name", None) or str(interaction.user)
    await interaction.followup.send(embed=calendar_embed(calendar, member_name=name), ephemeral=True)


async def _onboarded_employee(bot, discord_user_id):
    """None unless this Discord user actually completed the onboarding form.

    A bare row created by the role-driven auto-sync (join, role change,
    startup backfill) does not count — those never set CNIC/DOB, only the
    onboarding form does (see app/discord/onboarding.py). Tickets stay
    gated on the form, not merely on holding a workplace role.
    """
    if bot.hr is None or bot.hr.client is None:
        return None
    from app.records.employees import lookup_employee_by_discord_id

    try:
        employee = await asyncio.to_thread(
            lookup_employee_by_discord_id, bot.hr.client, str(discord_user_id), logger=bot.logger
        )
    except Exception:
        employee = None
    if not employee or not employee.get("active"):
        return None
    if str(employee.get("cnic") or "").strip() or str(employee.get("dob") or "").strip():
        return employee
    return None


def _onboarding_channel_mention(bot):
    tickets = (bot.config.get("discord") or {}).get("tickets") or {}
    channel_id = str(tickets.get("onboardingChannelId") or "").strip()
    return f"<#{channel_id}>" if channel_id.isdigit() else "#onboarding"


async def handle_open_ticket_button(interaction, bot):
    if not bot.config["discord"]["tickets"]["enabled"]:
        await interaction.response.send_message("Tickets are not enabled.", ephemeral=True)
        return
    if not await _onboarded_employee(bot, interaction.user.id):
        await interaction.response.send_message(
            f"Please finish onboarding in {_onboarding_channel_mention(bot)} first — "
            "you need a profile on file before you can open a ticket.",
            ephemeral=True,
        )
        return
    namespace = namespace_for_channel(bot.config["discord"]["channels"], interaction.channel_id)
    if not namespace:
        await interaction.response.send_message("Use this button in the open-ticket channel.", ephemeral=True)
        return
    existing = bot.store.find_open(interaction.user.id)
    if existing and existing.get("status") != "closed":
        channel_id = existing.get("channelId")
        live = None
        if interaction.guild and channel_id:
            live = interaction.guild.get_channel(int(channel_id))
            if live is None:
                try:
                    live = await interaction.guild.fetch_channel(int(channel_id))
                except (discord.HTTPException, TypeError, ValueError):
                    live = None
        if live is not None:
            await interaction.response.send_message(
                already_open_ticket_notice(channel_id),
                ephemeral=True,
            )
            return
        bot.store.remove(channel_id)
    await interaction.response.defer(ephemeral=True)
    try:
        member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
        if member is None and interaction.guild:
            try:
                member = await interaction.guild.fetch_member(interaction.user.id)
            except discord.HTTPException:
                member = interaction.user if isinstance(interaction.user, discord.Member) else None
        opened = await bot.tickets.open_for_member(
            guild=interaction.guild,
            user=member or interaction.user,
            member=member or interaction.user,
            parent_channel=interaction.channel,
            namespace=namespace,
        )
        channel = (opened or {}).get("channel")
        if opened and not opened.get("created") and channel is not None:
            await interaction.followup.send(already_open_ticket_notice(channel.id), ephemeral=True)
    except Exception as error:
        bot.logger.error("Open ticket button failed", {"message": str(error)})
        try:
            await interaction.followup.send(f"I could not open a ticket ({error}).", ephemeral=True)
        except discord.HTTPException:
            pass


async def handle_message(bot, message):
    from app.discord.leave_inbox import is_leave_inbox_channel

    if is_leave_inbox_channel(message.channel, bot.config):
        return False
    open_ticket = bot.store.get_by_channel(message.channel.id)
    if not open_ticket or open_ticket.get("status") == "closed":
        return False
    if re.match(r"^/leave\b", str(message.content or "").strip(), re.I):
        await handle_leave_from_message(bot, message)
        return True
    if open_ticket.get("botActive") is False:
        return False

    namespace = open_ticket.get("namespace") or namespace_for_channel(
        bot.config["discord"]["channels"],
        open_ticket.get("parentChannelId"),
    )
    if not should_handle_message(
        message,
        client_user=bot.user,
        respond_mode="all",
        namespace=namespace,
    ):
        return False
    question = strip_bot_mention(message.content, bot.user)
    if not question:
        return False
    if len(question) > 4000:
        await message.channel.send("That message is too long. Please ask a shorter question.")
        return True

    bot.logger.debug("Eligible Discord ticket message", {
        "channel": str(message.channel.id),
        "namespace": namespace,
        "user": str(message.author.id),
        "question": question[:300],
    })

    result = None
    ticket_owner_id = str(open_ticket.get("userId") or message.author.id)
    owner_member = await fetch_guild_member(message.guild, ticket_owner_id, message.author)
    role_source = owner_member or message.author
    async with message.channel.typing():
        if bot.config["echoMode"]:
            social_kind = classify_social(question)
            reply_text = social_fallback_reply(social_kind, question) if social_kind else f"Received: {question}"
        else:
            history = await collect_ticket_history(message.channel, message.id, bot.user.id)
            identity = {
                "botName": bot.config.get("assistantName") or "HR Assistant",
                "guildName": message.guild.name if message.guild else "",
                "companyName": bot.config.get("companyName") or "WebAiry",
                "channelName": message.channel.name if message.channel else "",
                "respondMode": "slash",
                "conversationHistory": history,
                "memberName": getattr(message.author, "display_name", None) or getattr(message.author, "global_name", None) or getattr(message.author, "name", None) or "Unknown",
                "memberUsername": getattr(message.author, "name", None) or "",
                "memberId": str(message.author.id),
                "memberRoleNames": [
                    role.name for role in getattr(role_source, "roles", []) or [] if getattr(role, "name", None)
                ],
            }
            try:
                result = await asyncio.to_thread(
                    bot.agent.handle,
                    question=question,
                    namespace=namespace,
                    channel_id=str(message.channel.id),
                    discord_user_id=ticket_owner_id,
                    identity=identity,
                    conversation_history=history,
                )
                reply_text = format_agent_reply(result)
            except AppError as error:
                bot.logger.error("Ticket answer failed", {"code": error.code})
                reply_text = user_error_text(error, bot.config["messages"]["userError"])
            else:
                _remember_ticket_turn(bot, str(message.channel.id), question, reply_text, result)

    if result and result.get("ui") in {"leave_form", "leave_confirm"} and result.get("leaveCard"):
        extra = (result.get("answer") or "").strip() if result.get("speakAnswer") else ""
        if extra:
            await send_discord_text(message, extra, mention_author=False)
        await publish_leave_form(bot, message.channel, result["leaveCard"])
        return True
    if result and result.get("ui") == "leave_cancel_none":
        await send_discord_text(message, result.get("answer") or "You have no leave to be cancelled.", mention_author=False)
        return True
    if result and result.get("ui") == "leave_cancel_form" and result.get("leaveCard"):
        await publish_cancel_leave_form(bot, message.channel, result["leaveCard"])
        return True
    if result and result.get("ui") == "leave_approved_cancelled":
        await clear_cancel_leave_form(bot, message.channel)
        await send_discord_text(message, result.get("answer") or "Cancelled.", mention_author=False)
        if result.get("saved"):
            from app.mail.notify import notify_leave_cancelled_mail

            await notify_decision(
                bot,
                result["saved"],
                outcome="cancelled",
                actor="Cancelled by employee",
                guild=message.guild,
                ticket_channel=message.channel,
            )
            await notify_leave_cancelled_mail(
                bot,
                result["saved"],
                ticket_name=getattr(message.channel, "name", "") or "",
            )
        return True
    if result and result.get("ui") == "leave_cancelled":
        await clear_leave_form_card(bot, message.channel)
        await send_discord_text(message, result.get("answer") or "Cancelled.", mention_author=False)
        return True
    if result and result.get("ui") == "leave_withdrawn":
        await clear_pending_leave_card(bot, message.channel)
        from app.discord.leave_inbox import finalize_leave_inbox

        await finalize_leave_inbox(bot, str(message.channel.id), remove=True)
        await message.channel.send(embed=leave_withdrawn_embed(result.get("leaveCard") or {}))
        if result.get("answer"):
            await send_discord_text(message, result["answer"], mention_author=False)
        return True
    if result and result.get("ui") == "leave_pending" and result.get("leaveCard"):
        if result.get("stickyPending") and result.get("answer"):
            await send_discord_text(message, result["answer"], mention_author=False)
        await publish_pending_leave(
            bot,
            message.channel,
            ticket_owner_id,
            card=result["leaveCard"],
            locale=(result.get("leaveCard") or {}).get("locale") or "english",
        )
        if not result.get("stickyPending"):
            from app.discord.leave_inbox import publish_leave_inbox

            await publish_leave_inbox(
                bot,
                ticket_channel=message.channel,
                card=result["leaveCard"],
                employee_id=ticket_owner_id,
            )
        if result.get("balanceText"):
            await message.channel.send(
                embed=leave_balance_embed(
                    result["balanceText"],
                    name=result.get("employeeName") or "",
                )
            )
        mention = (result.get("answer") or "")
        if "<@&" in mention and not result.get("stickyPending"):
            await message.channel.send(mention[mention.find("<@&"):].split()[0])
        return True
    if result and result.get("ui") == "leave_balance":
        await message.channel.send(
            embed=leave_balance_embed(
                result.get("answer") or "",
                name=result.get("employeeName") or "",
            )
        )
        await ensure_pending_leave_visible(bot, message.channel, ticket_owner_id)
        return True
    if result and result.get("ui") == "team_directory":
        from app.discord.team_directory import post_team_directory

        await post_team_directory(
            bot,
            message.channel,
            department=result.get("directoryDepartment") or "",
        )
        return True

    if not str(reply_text or "").strip():
        raise AppError(ErrorCodes.DISCORD_REPLY, "Generated an empty Discord reply.")
    await send_discord_text(message, reply_text, mention_author=False)
    return True


def _remember_ticket_turn(bot, channel_id, question, reply_text, result):
    sessions = getattr(bot, "sessions", None)
    if sessions is None or not result:
        return
    ui = result.get("ui") or ""
    followup = is_session_followup(question)
    grounded = (
        not result.get("fallback")
        and ui not in {"clarify", "leave_form", "leave_confirm", "leave_cancelled", "session_prompt"}
    )
    sessions.remember(
        channel_id,
        question=question,
        answer=str(reply_text or result.get("answer") or ""),
        intent=ui or "",
        grounded=grounded,
        followup=followup,
    )


async def collect_ticket_history(channel, current_message_id, bot_id):
    from app.generation.context_window import INTENT_MSG_CHARS, INTENT_TURNS

    messages = [item async for item in channel.history(limit=INTENT_TURNS * 2)]
    messages = [item for item in messages if item.id != current_message_id and item.content]
    messages.sort(key=lambda item: item.created_at)
    history = []
    for item in messages[-INTENT_TURNS:]:
        history.append({
            "role": "assistant" if item.author.id == bot_id else "user",
            "content": str(item.content)[:INTENT_MSG_CHARS],
        })
    return history


def can_ask_bot_to_leave(member, config, guild):
    """Staff cannot mute the bot. Admin or HR can."""
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    hr_cfg = (config or {}).get("hr") or {}
    roles = [{"id": str(role.id), "name": role.name} for role in getattr(guild, "roles", [])]
    if is_admin_member(member, roles, tickets.get("adminRoleId")):
        return True
    if is_hr_admin(member, hr_cfg.get("adminRoleId") or tickets.get("adminRoleId")):
        return True
    if is_hr_member(member, hr_cfg.get("hrRoleId")):
        return True
    return False


async def leave_ticket_chat(channel, store, logger):
    ticket = store.set_bot_active(channel.id, False)
    if not ticket:
        return False
    try:
        await channel.send("I am leaving this chat. Admin and the member can talk here now.")
    except discord.HTTPException as error:
        logger.warn("Could not post leave notice", {"message": str(error)})
    logger.info("Bot left a ticket chat", {"channel": str(channel.id)})
    return True


async def handle_leave_from_message(bot, message):
    ticket = bot.store.get_by_channel(message.channel.id)
    if not ticket:
        return
    if not can_ask_bot_to_leave(message.author, bot.config, message.guild):
        await message.channel.send("Only Admin or HR can ask the bot to leave this ticket.")
        return
    if ticket.get("botActive") is False:
        return
    try:
        await message.delete()
    except discord.HTTPException:
        pass
    await leave_ticket_chat(message.channel, bot.store, bot.logger)


def is_welcome_noise(message, config):
    if str(message.channel.id) not in config["discord"]["channels"]:
        return False
    return message.type in {discord.MessageType.new_member, discord.MessageType.premium_guild_subscription}


async def disable_welcome_in_ticket_channels(bot):
    ticket_entry_ids = set(bot.config["discord"]["channels"].keys())
    for guild in bot.guilds:
        try:
            await asyncio.wait_for(
                guild.edit(system_channel_flags=discord.SystemChannelFlags(
                    join_notifications=True,
                    join_notification_replies=True,
                )),
                timeout=10,
            )
        except (discord.HTTPException, asyncio.TimeoutError) as error:
            bot.logger.warn("Could not suppress Discord welcome messages", {"message": str(error)})
        if guild.system_channel and str(guild.system_channel.id) in ticket_entry_ids:
            try:
                await asyncio.wait_for(guild.edit(system_channel=None), timeout=10)
            except (discord.HTTPException, asyncio.TimeoutError) as error:
                bot.logger.warn("Could not unset welcome channel on open-ticket", {"message": str(error)})


async def ensure_open_ticket_panels(bot):
    if not bot.config["discord"]["tickets"]["enabled"]:
        return
    for channel_id in bot.config["discord"]["channels"]:
        try:
            channel = bot.get_channel(int(channel_id))
            if channel is None:
                channel = await bot.fetch_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                continue
            await bot.tickets.prepare_open_ticket_channel(channel)
            async for message in channel.history(limit=100):
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
            embed, _view = open_ticket_panel()
            await channel.send(embed=embed, view=OpenTicketView(bot))
            bot.logger.info("Posted Open ticket panel", {"channel": channel_id})
        except Exception as error:
            bot.logger.warn("Could not post Open ticket panel", {
                "channel": channel_id,
                "message": str(error),
            })


def _role_ids(member):
    return {str(getattr(role, "id", role)) for role in getattr(member, "roles", []) or []}


def _member_roles_changed(before, after, config):
    if after is None:
        return False
    if before is None:
        return True
    if _role_ids(before) != _role_ids(after):
        return True
    return member_sync_key(before, config) != member_sync_key(after, config)


async def resync_members_with_role(bot, role):
    guild = getattr(role, "guild", None)
    if guild is None:
        return
    role_id = str(getattr(role, "id", "") or "")
    for member in getattr(guild, "members", []) or []:
        ids = {str(getattr(item, "id", "")) for item in getattr(member, "roles", []) or []}
        if role_id in ids:
            await sync_staff_member(bot, member, reason="role-renamed")


async def sync_guild_role_catalog(bot, guild):
    if bot.hr is None or bot.hr.client is None:
        return
    try:
        await asyncio.to_thread(
            sync_guild_roles,
            bot.hr.client,
            getattr(guild, "roles", []) or [],
            logger=bot.logger,
        )
    except Exception as error:
        bot.logger.error("MySQL Discord roles sync failed", {"message": str(error)})


async def sync_one_guild_role(bot, role, *, reason):
    if bot.hr is None or bot.hr.client is None or role is None:
        return
    try:
        await asyncio.to_thread(upsert_discord_role, bot.hr.client, role, logger=bot.logger)
        bot.logger.info("MySQL Discord role saved", {
            "role": str(getattr(role, "name", "")),
            "id": str(getattr(role, "id", "")),
            "reason": reason,
        })
    except Exception as error:
        bot.logger.error("MySQL Discord role sync failed", {
            "reason": reason,
            "message": str(error),
        })


async def drop_guild_role(bot, role_id):
    if bot.hr is None or bot.hr.client is None:
        return
    try:
        await asyncio.to_thread(delete_discord_role, bot.hr.client, role_id, logger=bot.logger)
    except Exception as error:
        bot.logger.error("MySQL Discord role delete failed", {"message": str(error)})


async def _sync_member_after_delay(bot, member, *, reason, delay=4):
    await asyncio.sleep(delay)
    guild = getattr(member, "guild", None)
    if guild is None:
        return
    fresh = guild.get_member(member.id)
    if fresh is None:
        try:
            fresh = await guild.fetch_member(member.id)
        except discord.HTTPException:
            return
    await sync_staff_member(bot, fresh, reason=reason)


async def sync_existing_members(bot, guild):
    """Put everyone who already holds a workplace role into MySQL.

    Join and role-assign keep new people current. This pass catches anyone
    already in the server when the bot starts.
    """
    if bot._members_synced or bot.hr is None or bot.hr.client is None:
        return
    bot._members_synced = True

    from app.records.employees import list_employee_discord_ids

    try:
        known = await asyncio.to_thread(
            list_employee_discord_ids, bot.hr.client, logger=bot.logger
        )
    except Exception as error:
        bot.logger.error("Could not read existing employees; skipping backfill", {
            "message": str(error),
        })
        return

    candidates = []
    for member in getattr(guild, "members", []) or []:
        if getattr(member, "bot", False):
            continue
        if kind_for_guild_member(member, bot.config) or str(member.id) in known:
            candidates.append(member)

    for member in candidates:
        await sync_staff_member(bot, member, reason="startup")

    bot.logger.info("Employee backfill complete", {
        "guild": str(getattr(guild, "id", "")),
        "alreadyMapped": len(known),
        "added": len(candidates),
    })


async def sync_staff_member(bot, member, *, reason):
    if member is None or getattr(member, "bot", False):
        return
    if bot.hr is None or bot.hr.client is None:
        bot.logger.warn("Skipped Staff DB sync; HR is not connected", {
            "user": str(getattr(member, "id", "")),
            "reason": reason,
        })
        return
    role_names = [role.name for role in getattr(member, "roles", []) or [] if getattr(role, "name", None)]
    await sync_member_roles_catalog(bot, member)
    kind = kind_for_guild_member(member, bot.config)
    user_id = str(member.id)
    existing = None
    if not kind:
        try:
            from app.records.employees import lookup_employee_by_discord_id

            existing = await asyncio.to_thread(
                lookup_employee_by_discord_id, bot.hr.client, user_id, logger=bot.logger
            )
        except Exception:
            existing = None
        if existing:
            kind = existing.get("department") or "Staff"
        else:
            bot.logger.debug("Skipped Staff DB sync; no workplace role", {
                "user": user_id,
                "reason": reason,
            })
            return
    if user_id in bot._staff_syncing:
        return
    bot._staff_syncing.add(user_id)
    try:
        joined = getattr(member, "joined_at", None)
        await asyncio.to_thread(
            upsert_staff_employee,
            bot.hr.client,
            discord_id=user_id,
            name=getattr(member, "display_name", None) or getattr(member, "name", None) or "Staff",
            username=getattr(member, "name", "") or "",
            joined_at=joined.date().isoformat() if joined is not None and hasattr(joined, "date") else None,
            kind=kind,
            hod=hod_for_guild_member(member, bot.config),
            hr_role=hr_role_for_guild_member(member, bot.config),
            role_names=role_names,
            # Joining or gaining a role is not onboarding. Leave quota is
            # only granted once the person actually submits the onboarding
            # form (see app/discord/onboarding.py).
            grant_leave=False,
            logger=bot.logger,
        )
    except Exception as error:
        bot.logger.error("Staff DB sync failed", {
            "user": user_id,
            "reason": reason,
            "message": str(error),
        })
    finally:
        bot._staff_syncing.discard(user_id)


async def sync_member_roles_catalog(bot, member):
    if bot.hr is None or bot.hr.client is None:
        return
    for role in getattr(member, "roles", []) or []:
        if str(getattr(role, "name", "") or "") in {"", "@everyone"}:
            continue
        try:
            await asyncio.to_thread(upsert_discord_role, bot.hr.client, role, logger=bot.logger)
        except Exception as error:
            bot.logger.warn("MySQL Discord role sync failed", {
                "role": str(getattr(role, "name", "")),
                "message": str(error)[:200],
            })


def create_discord_bot(*, config, logger, rag, hr=None):
    """Build the bot.

    Buttons and selects are handled by the persistent views registered in
    setup_hook, and slash commands by the command tree. discord.py routes both
    on its own, so this module must not also listen for `on_interaction`:
    that event fires *in addition to* view dispatch, which would run every
    button callback twice.
    """
    return SupportBot(config=config, logger=logger, rag=rag, hr=hr)

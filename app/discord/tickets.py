import discord

from app.tickets.helpers import (
    find_admin_role_id,
    find_staff_role_id,
    pick_ticket_category_id,
    ticket_channel_name,
    ticket_topic,
)

CLOSE_TICKET_ID = "ticket:close"
OPEN_TICKET_ID = "ticket:open"
CATEGORY_TYPE = discord.ChannelType.category


async def resolve_guild_member(guild, user_or_id):
    user_id = getattr(user_or_id, "id", user_or_id)
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    member = guild.get_member(user_id)
    if isinstance(member, discord.Member):
        return member
    try:
        member = await guild.fetch_member(user_id)
    except discord.HTTPException:
        return None
    return member if isinstance(member, discord.Member) else None


def open_ticket_panel():
    from app.discord.journey import panel_embed

    embed = panel_embed()
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Open ticket",
            style=discord.ButtonStyle.success,
            emoji="🎫",
            custom_id=OPEN_TICKET_ID,
        )
    )
    return embed, view


def already_open_ticket_notice(channel_id):
    return f"You already have an open ticket: <#{channel_id}>"


def close_row():
    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Close ticket",
            style=discord.ButtonStyle.secondary,
            custom_id=CLOSE_TICKET_ID,
        )
    )
    return view


class TicketManager:
    def __init__(self, config, logger, store, close_view=None, sessions=None):
        self.config = config
        self.logger = logger
        self.store = store
        # Factory for the Close ticket view. The bot passes one whose button
        # carries a real callback; close_row() is only a shape fallback.
        self.close_view = close_view or close_row
        self.sessions = sessions

    async def resolve_ticket(self, *, guild, user, member, parent_channel, namespace):
        reused = await self.reuse_user_ticket(guild, user.id, namespace, parent_channel.id)
        if reused:
            return reused
        return await self.create_ticket(guild, user, member, parent_channel, namespace)

    async def open_for_member(self, *, guild, user, member, parent_channel, namespace):
        return await self.resolve_ticket(
            guild=guild,
            user=user,
            member=member,
            parent_channel=parent_channel,
            namespace=namespace,
        )

    async def reuse_user_ticket(self, guild, user_id, namespace, parent_channel_id):
        for record in self.store.find_all_by_user(user_id):
            channel = guild.get_channel(int(record["channelId"]))
            if channel is None:
                try:
                    channel = await guild.fetch_channel(int(record["channelId"]))
                except discord.HTTPException:
                    channel = None
            if channel is None:
                self.store.remove(record["channelId"])
                continue
            if isinstance(channel, discord.Thread):
                await channel.delete(reason="Tickets now open as separate channels")
                self.store.remove(record["channelId"])
                continue
            return await self.reopen_ticket(channel, record, namespace, parent_channel_id)
        return None

    async def reopen_ticket(self, channel, record, namespace, parent_channel_id):
        ticket = self.store.upsert({
            **record,
            "namespace": namespace or record.get("namespace"),
            "parentChannelId": parent_channel_id or record.get("parentChannelId"),
            "status": "open",
            "channelName": str(channel.name or record.get("channelName") or ""),
            "closedAt": None,
            "botActive": True if record.get("status") == "closed" else record.get("botActive", True) is not False,
        })
        original_name = (channel.name or "").removeprefix("closed-")[:100] or ticket_channel_name("member", record["userId"])
        if channel.name != original_name:
            try:
                await channel.edit(name=original_name)
            except discord.HTTPException:
                pass
        member = await resolve_guild_member(channel.guild, record["userId"])
        try:
            if member:
                await channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
            await apply_support_role_access(channel, channel.guild, self.config, owner=member)
        except discord.HTTPException as error:
            self.logger.warn("Could not unlock the existing ticket channel", {"message": str(error)})
        if record.get("status") == "closed":
            await channel.send("Ticket reopened. Previous messages in this chat are still here.")
            await self.publish_close_row(channel)
        self.logger.info("Reused the same ticket channel for this member", {
            "channel": str(channel.id),
            "user": record["userId"],
        })
        return {"ticket": ticket, "channel": channel, "created": False}

    async def create_ticket(self, guild, user, member, parent_channel, namespace):
        member = member if isinstance(member, discord.Member) else await resolve_guild_member(guild, user)
        if member is None:
            member = await resolve_guild_member(guild, user)
        overwrite_target = member or (user if isinstance(user, discord.Member) else None)
        name = ticket_channel_name(getattr(user, "name", None) or "member", user.id)
        role_list = [{"id": str(role.id), "name": role.name} for role in guild.roles]
        staff_role_id = find_staff_role_id(role_list, self.config["discord"]["tickets"]["staffRoleId"])
        admin_role_id = find_admin_role_id(role_list, self.config["discord"]["tickets"]["adminRoleId"])
        parent = await self.resolve_category_parent(guild)
        if not parent:
            raise RuntimeError(
                "Tickets must open as separate channels next to #ticket. "
                "Create a #ticket channel or a Tickets folder, and give the bot Manage Channels."
            )
        bot_member = guild.me if isinstance(guild.me, discord.Member) else await resolve_guild_member(guild, getattr(guild.me, "id", None))
        overwrites = ticket_overwrites(
            guild=guild,
            user=overwrite_target,
            bot=bot_member,
            staff_role_id=staff_role_id,
            admin_role_id=admin_role_id,
            hod_role_ids=_all_hod_role_ids(guild, self.config),
        )
        topic = ticket_topic(user_id=user.id, namespace=namespace, parent_channel_id=parent_channel.id)
        try:
            channel = await guild.create_text_channel(
                name=name,
                category=parent,
                topic=topic,
                overwrites=overwrites,
                reason=f"Support ticket for {user}",
            )
        except discord.HTTPException as first_error:
            self.logger.warn("Creating ticket with custom permissions failed, retrying with folder permissions", {
                "message": str(first_error),
            })
            try:
                channel = await guild.create_text_channel(
                    name=name,
                    category=parent,
                    topic=topic,
                    reason=f"Support ticket for {user}",
                )
                if overwrite_target:
                    await channel.set_permissions(overwrite_target, view_channel=True, send_messages=True, read_message_history=True)
            except discord.HTTPException as second_error:
                raise RuntimeError(
                    f"Could not create a ticket channel in the Tickets folder ({second_error}). "
                    "Give the HR Assistant role Manage Channels, move it above Staff/Admin, "
                    "and add the bot to the Tickets folder with View Channel on."
                ) from second_error
        if channel.category_id != parent.id:
            try:
                await channel.edit(category=parent, sync_permissions=False)
            except discord.HTTPException as error:
                self.logger.warn("Ticket was created outside the Tickets folder", {"message": str(error)})
        return await self.finish_ticket(channel, user, member, parent_channel, namespace)

    async def finish_ticket(self, channel, user, member, parent_channel, namespace):
        from datetime import datetime, timezone

        ticket = self.store.upsert({
            "channelId": str(channel.id),
            "userId": str(user.id),
            "namespace": namespace,
            "parentChannelId": str(parent_channel.id),
            "guildId": str(channel.guild.id),
            "channelName": str(channel.name or ""),
            "status": "open",
            "botActive": True,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        })
        from app.discord.journey import ticket_intro_text, welcome_embed

        display_name = (
            getattr(member, "display_name", None)
            or getattr(user, "global_name", None)
            or getattr(user, "name", "")
        )
        # The employee is greeted first, in their own terms. The card names the
        # employer, falling back to the Discord server only if none is set.
        company = self.config.get("companyName") or "WebAiry"
        await channel.send(
            content=ticket_intro_text(user.mention),
            embed=welcome_embed(display_name, company),
            allowed_mentions=discord.AllowedMentions(users=[user], roles=False, everyone=False),
        )
        await self.publish_close_row(channel)
        self.logger.info("Opened a private support ticket", {
            "channel": str(channel.id),
            "user": str(user.id),
            "parent": str(parent_channel.id),
        })
        return {"ticket": ticket, "channel": channel, "created": True}

    async def publish_close_row(self, channel):
        ticket = self.store.get_by_channel(channel.id)
        if not ticket or ticket.get("status") == "closed":
            return None
        if ticket.get("closeMessageId"):
            return None
        sent = await channel.send(
            "Close this ticket when you are done. Staff can also use `/close`.",
            view=self.close_view(),
        )
        self.store.upsert({**ticket, "closeMessageId": str(sent.id)})
        return sent

    async def close_ticket(self, channel, ticket, closer, *, respond=None):
        old_id = ticket.get("closeMessageId")
        self.store.close(channel.id)
        if self.sessions:
            self.sessions.clear(channel.id)
        if old_id:
            try:
                old = await channel.fetch_message(int(old_id))
                await old.delete()
            except Exception:
                pass
        from app.discord.journey import closed_embed, closer_caption

        caption = closer_caption(closer, self.config)
        embed = closed_embed(caption or None)
        if respond:
            await respond(embed=embed)
        else:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        member = await resolve_guild_member(channel.guild, ticket["userId"])
        if member:
            try:
                await channel.set_permissions(
                    member,
                    send_messages=False,
                    view_channel=True,
                    read_message_history=True,
                )
            except discord.HTTPException as error:
                self.logger.warn("Could not lock ticket channel", {"message": str(error)})

    async def remove_old_thread_tickets(self, guild):
        for ticket in list(self.store.all().values()):
            try:
                channel = guild.get_channel(int(ticket["channelId"])) or await guild.fetch_channel(int(ticket["channelId"]))
            except discord.HTTPException:
                continue
            if not isinstance(channel, discord.Thread):
                continue
            await channel.delete(reason="Tickets now open as separate channels, not threads under general.")
            self.store.remove(ticket["channelId"])
            self.logger.info("Deleted old ticket thread under a public channel", {"channel": ticket["channelId"]})

    async def move_tickets_into_category(self, guild):
        parent = await self.resolve_category_parent(guild)
        if not parent:
            return
        for channel in guild.channels:
            if not isinstance(channel, discord.TextChannel):
                continue
            if not (channel.name.startswith("ticket-") or channel.name.startswith("closed-ticket-")):
                continue
            if channel.category_id == parent.id:
                continue
            try:
                await channel.edit(category=parent, sync_permissions=False)
            except discord.HTTPException as error:
                self.logger.warn("Could not move an existing ticket into the Tickets folder", {
                    "channel": str(channel.id),
                    "message": str(error),
                })

    async def grant_admin_access(self, guild):
        for ticket in list(self.store.all().values()):
            try:
                channel = guild.get_channel(int(ticket["channelId"])) or await guild.fetch_channel(int(ticket["channelId"]))
            except discord.HTTPException:
                continue
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                owner = None
                try:
                    owner = guild.get_member(int(ticket.get("userId") or 0))
                except (TypeError, ValueError):
                    owner = None
                await apply_support_role_access(channel, guild, self.config, owner=owner)
            except discord.HTTPException as error:
                self.logger.warn("Could not give Admin access to a ticket", {
                    "channel": ticket["channelId"],
                    "message": str(error),
                })

    async def resolve_category_parent(self, guild):
        channels = [
            {
                "id": str(channel.id),
                "name": channel.name,
                "type": channel.type.value if hasattr(channel.type, "value") else channel.type,
                "parentId": str(channel.category_id) if getattr(channel, "category_id", None) else None,
            }
            for channel in guild.channels
        ]
        parent_id = pick_ticket_category_id(channels, self.config["discord"]["tickets"]["categoryId"])
        if not parent_id:
            self.logger.warn("Could not find a Tickets category folder. Create a category named Tickets.")
            return None
        parent = guild.get_channel(int(parent_id))
        if parent and parent.type != CATEGORY_TYPE:
            self.logger.warn("Ticket parent is not a category folder", {"categoryId": parent_id})
            return None
        self.logger.info("New tickets will be created inside this folder", {
            "categoryId": parent_id,
            "name": getattr(parent, "name", None),
        })
        return parent

    async def prepare_open_ticket_channel(self, channel):
        if channel.name != "open-ticket":
            try:
                await channel.edit(name="open-ticket")
            except discord.HTTPException as error:
                self.logger.warn("Could not rename channel to open-ticket", {"message": str(error)})
        try:
            await channel.edit(topic="Open a private support ticket. No chat in this channel.")
        except discord.HTTPException:
            pass
        try:
            await channel.set_permissions(
                channel.guild.default_role,
                send_messages=False,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False,
                add_reactions=False,
                view_channel=True,
                read_message_history=True,
            )
            if channel.guild.me:
                await channel.set_permissions(
                    channel.guild.me,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                    embed_links=True,
                )
            self.logger.info("Locked chat in open-ticket channel; button only", {"channel": str(channel.id)})
        except discord.HTTPException as error:
            self.logger.warn("Could not lock chat in open-ticket channel", {"message": str(error)})


def ticket_overwrites(*, guild, user, bot, staff_role_id, admin_role_id, hod_role_id=None, other_hod_role_ids=None, hod_role_ids=None):
    allow = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    hide = discord.PermissionOverwrite(view_channel=False)
    overwrites = {
        guild.default_role: hide,
    }
    if isinstance(user, (discord.Member, discord.Role)):
        overwrites[user] = allow
    if isinstance(bot, (discord.Member, discord.Role)):
        overwrites[bot] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
        )
    if admin_role_id:
        role = guild.get_role(int(admin_role_id))
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                manage_channels=True,
            )
    if staff_role_id and staff_role_id != admin_role_id:
        role = guild.get_role(int(staff_role_id))
        if role:
            overwrites[role] = hide
    hide_ids = list(hod_role_ids or [])
    if hod_role_id:
        hide_ids.append(hod_role_id)
    hide_ids.extend(other_hod_role_ids or [])
    seen = set()
    for raw in hide_ids:
        try:
            rid = int(raw)
        except (TypeError, ValueError):
            continue
        if rid in seen:
            continue
        seen.add(rid)
        hod = guild.get_role(rid)
        if hod:
            overwrites[hod] = hide
    return overwrites


def _all_hod_role_ids(guild, config):
    from app.hr.departments import DEPARTMENTS, find_hod_role_id, hod_role_ids_from_config

    roles = [{"id": str(role.id), "name": role.name} for role in getattr(guild, "roles", []) or []]
    configured = hod_role_ids_from_config(config)
    ids = []
    for dept in DEPARTMENTS:
        found = find_hod_role_id(roles, dept, configured.get(dept, ""))
        if found and found not in ids:
            ids.append(found)
    return ids


async def apply_support_role_access(channel, guild, config, owner=None):
    role_list = [{"id": str(role.id), "name": role.name} for role in guild.roles]
    admin_role_id = find_admin_role_id(role_list, config["discord"]["tickets"]["adminRoleId"])
    staff_role_id = find_staff_role_id(role_list, config["discord"]["tickets"]["staffRoleId"])
    if admin_role_id:
        role = guild.get_role(int(admin_role_id))
        if role:
            await channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                manage_channels=True,
            )
    if staff_role_id and staff_role_id != admin_role_id:
        role = guild.get_role(int(staff_role_id))
        if role:
            await channel.set_permissions(role, view_channel=False)
    for hod_id in _all_hod_role_ids(guild, config):
        hod = guild.get_role(int(hod_id))
        if hod:
            await channel.set_permissions(hod, view_channel=False)


def create_ticket_manager(config, logger, store, close_view=None, sessions=None):
    return TicketManager(config, logger, store, close_view=close_view, sessions=sessions)

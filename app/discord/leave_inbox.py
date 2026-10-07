"""Private leave inboxes: #leave-requests for HR, HOD channels for notify-only.

HOD channels are visible to that department's HOD, Admin, and HR.
Every leave request is posted to BOTH #leave-requests (Admin/HR, with
Approve/Reject buttons) and the department's HOD channel (view-only, no
buttons) at the same time. Only HR/Admin can ever decide.
"""

import re

import discord

from app.discord.leave_review import LeaveReviewView, _leave_name, _qty, _span
from app.hr.departments import (
    DEPARTMENTS,
    CHANNEL_NAMES,
    find_hod_role_id,
    hod_channel_ids_from_config,
    hod_channel_name,
    hod_display_name,
    hod_role_ids_from_config,
    normalize_department,
)
from app.tickets.helpers import find_admin_role_id, find_hr_role_id, find_staff_role_id

REVIEW_CHANNEL_NAME = "leave-requests"
HR_CATEGORY_NAME = "hr"
HOD_CATEGORY_NAME = "hod"
TICKET_FOOTER_PREFIX = "ticket:"
CHANNEL_MENTION = re.compile(r"<#(\d+)>")
TICKET_ID_IN_TEXT = re.compile(r"ticket:(\d+)")


def hod_inbox_department(card):
    """Department to notify (view-only), or empty when there is none for this card.

    HOD notification is no longer tied to approval stage: it fires for every
    leave request in BI/CS/Marketing, alongside — never instead of — HR.
    """
    if not card:
        return ""
    department = normalize_department(card.get("department"))
    return department if department in DEPARTMENTS else ""


def leave_review_channel_id(config):
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    return str(tickets.get("leaveReviewChannelId") or "")


def is_leave_review_channel(channel, config):
    if channel is None:
        return False
    wanted = str(leave_review_channel_id(config) or "").strip()
    if wanted and str(getattr(channel, "id", "")) == wanted:
        return True
    return str(getattr(channel, "name", "") or "").strip().lower() == REVIEW_CHANNEL_NAME


def ticket_id_from_footer(text):
    found = TICKET_ID_IN_TEXT.search(str(text or ""))
    return found.group(1) if found else ""


def ticket_field_text(*, display_name="", channel_name="", channel_id=""):
    """Plain ticket label. Channel mentions show as #unknown in HOD/HR inboxes."""
    person = str(display_name or "").strip()
    channel = str(channel_name or "").strip().lstrip("#")
    parts = []
    if person:
        parts.append(person)
    if channel:
        parts.append(f"#{channel}")
    if parts:
        return "\n".join(parts)
    return "—"


def polish_reviewer_card(card, *, client=None, employee=None, logger=None, ticket_name="", display_name=""):
    """Names and reasons HOD/HR can read: no Airtable ids, no Discord file URLs."""
    from app.records.leave_types import looks_like_record_id, public_leave_type_name_for_client
    from app.discord.attachments import parse_reason_and_files, public_reason_text

    out = dict(card or {})
    raw_type = out.get("leave_type") or out.get("leaveType")
    label = public_leave_type_name_for_client(client, raw_type, logger=logger)
    out["leave_type"] = label
    out["leaveType"] = label
    name = str(out.get("name") or out.get("employeeName") or "").strip()
    emp_name = str((employee or {}).get("name") or "").strip()
    nick = str(display_name or "").strip()
    if not name or name.lower() in {"employee", "member", "staff", "—"} or looks_like_record_id(name):
        name = emp_name or nick or name
        if not name or looks_like_record_id(name) or name.lower() in {"employee", "member", "staff", "—"}:
            name = emp_name or nick or "Staff"
    out["name"] = name
    out["employeeName"] = name
    body, files = parse_reason_and_files(out.get("reason"))
    if files and not out.get("attachments"):
        out["attachments"] = files
    out["reason"] = public_reason_text(out.get("reason"))
    if ticket_name:
        out["ticketName"] = ticket_name
        out["channelName"] = ticket_name
    request_id = str(out.get("requestId") or "").strip()
    if looks_like_record_id(request_id):
        out["requestId"] = "—"
    return out


def inbox_embed(card, *, ticket_channel_id, employee_mention="", ticket_name=""):
    leave_type = _leave_name({"leaveType": (card or {}).get("leave_type") or (card or {}).get("leaveType")})
    start = (card or {}).get("start_date")
    end = (card or {}).get("end_date") or start
    request = {
        "leaveType": leave_type,
        "startDate": start,
        "endDate": end,
        "daysRequested": (card or {}).get("days") or 1,
    }
    name = (card or {}).get("name") or "Employee"
    embed = discord.Embed(
        title="Leave request",
        description=f"{name} applied for **{leave_type}**.",
        color=0x1D4ED8,
    )
    embed.set_author(name="Human Resources")
    embed.add_field(name="Leave type", value=f"**{leave_type}**", inline=True)
    embed.add_field(name="Days", value=f"**{_qty(request['daysRequested'])}**", inline=True)
    embed.add_field(name="Dates", value=_span(request), inline=False)
    reason = str((card or {}).get("reason") or "").strip() or "—"
    from app.discord.attachments import add_attachment_preview, parse_reason_and_files

    body, files = parse_reason_and_files(reason)
    if not files:
        files = (card or {}).get("attachments") or []
    embed.add_field(name="Reason", value=(body or "—")[:1000], inline=False)
    add_attachment_preview(embed, files)
    department = normalize_department((card or {}).get("department"))
    if department:
        embed.add_field(name="Department", value=department, inline=True)
    embed.add_field(
        name="Ticket",
        value=ticket_field_text(
            display_name=name,
            channel_name=ticket_name,
            channel_id="",
        ),
        inline=False,
    )
    embed.set_footer(text="Waiting for a decision")
    return embed


def _role(guild, role_id):
    try:
        rid = int(str(role_id or "").strip())
    except (TypeError, ValueError):
        return None
    if rid <= 0:
        return None
    return guild.get_role(rid)


def _is_hr_role_name(name):
    lowered = str(name or "").strip().lower()
    if not lowered:
        return False
    if lowered in {"hr", "human resources", "hr team", "hr staff"}:
        return True
    return lowered == "hr" or lowered.startswith("hr ") or lowered.endswith(" hr")


def _hr_role_ids(guild, config):
    roles = [{"id": str(role.id), "name": role.name} for role in getattr(guild, "roles", []) or []]
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    hr_cfg = (config or {}).get("hr") or {}
    ids = []
    for value in (
        hr_cfg.get("hrRoleId"),
        find_hr_role_id(roles, ""),
        tickets.get("adminRoleId") if _is_hr_role_name(_role_name(guild, tickets.get("adminRoleId"))) else "",
        hr_cfg.get("adminRoleId") if _is_hr_role_name(_role_name(guild, hr_cfg.get("adminRoleId"))) else "",
        tickets.get("adminRoleId") if str(tickets.get("adminRoleId") or "") == str(hr_cfg.get("hrRoleId") or "") else "",
    ):
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    for role in getattr(guild, "roles", []) or []:
        if _is_hr_role_name(getattr(role, "name", "")):
            text = str(getattr(role, "id", "") or "")
            if text and text not in ids:
                ids.append(text)
    return ids


def _role_name(guild, role_id):
    role = _role(guild, role_id)
    return str(getattr(role, "name", "") or "")


def _admin_role_id_for_hod_inbox(guild, config):
    """Admin may see HOD inboxes (alongside HR)."""
    roles = [{"id": str(role.id), "name": role.name} for role in getattr(guild, "roles", []) or []]
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    hr_cfg = (config or {}).get("hr") or {}
    return find_admin_role_id(roles, tickets.get("adminRoleId")) or hr_cfg.get("adminRoleId") or ""


def _review_overwrites(guild, config):
    roles = [{"id": str(role.id), "name": role.name} for role in guild.roles]
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    hr_cfg = (config or {}).get("hr") or {}
    admin_id = find_admin_role_id(roles, tickets.get("adminRoleId")) or hr_cfg.get("adminRoleId")
    hr_id = hr_cfg.get("hrRoleId") or find_hr_role_id(roles, "")
    staff_id = find_staff_role_id(roles, tickets.get("staffRoleId"))
    see = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=False,
        read_message_history=True,
        add_reactions=False,
    )
    hide = discord.PermissionOverwrite(view_channel=False)
    overwrites = {guild.default_role: hide}
    bot_member = guild.me
    if isinstance(bot_member, discord.Member):
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            manage_channels=True,
            embed_links=True,
        )
    admin_role = _role(guild, admin_id)
    hr_role = _role(guild, hr_id)
    if admin_role:
        overwrites[admin_role] = see
    if hr_role and hr_role != admin_role:
        overwrites[hr_role] = see
    staff_role = _role(guild, staff_id)
    if staff_role and staff_role not in {admin_role, hr_role}:
        overwrites[staff_role] = hide
    role_list = [{"id": str(role.id), "name": role.name} for role in guild.roles]
    configured_hod = hod_role_ids_from_config(config)
    for dept in DEPARTMENTS:
        hod_id = find_hod_role_id(role_list, dept, configured_hod.get(dept, ""))
        hod_role = _role(guild, hod_id)
        if hod_role and hod_role not in {admin_role, hr_role}:
            overwrites[hod_role] = hide
    return overwrites


def _hod_overwrites(guild, config, department):
    roles = [{"id": str(role.id), "name": role.name} for role in guild.roles]
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    staff_id = find_staff_role_id(roles, tickets.get("staffRoleId"))
    configured_hod = hod_role_ids_from_config(config)
    see = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=False,
        read_message_history=True,
        add_reactions=False,
    )
    hide = discord.PermissionOverwrite(view_channel=False)
    overwrites = {guild.default_role: hide}
    bot_member = guild.me
    if isinstance(bot_member, discord.Member):
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            manage_channels=True,
            embed_links=True,
        )
    admin_role = _role(guild, _admin_role_id_for_hod_inbox(guild, config))
    if admin_role:
        overwrites[admin_role] = see
    # HR can view every channel, including HOD notify inboxes.
    for hr_id in _hr_role_ids(guild, config):
        hr_role = _role(guild, hr_id)
        if hr_role:
            overwrites[hr_role] = see
    staff_role = _role(guild, staff_id)
    if staff_role and staff_role is not admin_role:
        overwrites[staff_role] = hide
    this_hod = _role(guild, find_hod_role_id(roles, department, configured_hod.get(department, "")))
    if this_hod:
        overwrites[this_hod] = see
    for dept in DEPARTMENTS:
        if dept == department:
            continue
        other = _role(guild, find_hod_role_id(roles, dept, configured_hod.get(dept, "")))
        if other and other not in {admin_role, this_hod}:
            overwrites[other] = hide
    return overwrites


def _hod_category_overwrites(guild, config):
    """HODs and HR/Admin can see the HOD folder. Each channel still hides other HODs."""
    overwrites = _hod_overwrites(guild, config, DEPARTMENTS[0])
    configured_hod = hod_role_ids_from_config(config)
    roles = [{"id": str(role.id), "name": role.name} for role in guild.roles]
    see = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=False,
        read_message_history=True,
        add_reactions=False,
    )
    for dept in DEPARTMENTS:
        hod_role = _role(guild, find_hod_role_id(roles, dept, configured_hod.get(dept, "")))
        if hod_role:
            overwrites[hod_role] = see
    for hr_id in _hr_role_ids(guild, config):
        hr_role = _role(guild, hr_id)
        if hr_role:
            overwrites[hr_role] = see
    return overwrites


async def _load_category(guild, category_id):
    if not str(category_id or "").strip().isdigit():
        return None
    parent = guild.get_channel(int(category_id))
    if parent is None:
        try:
            parent = await guild.fetch_channel(int(category_id))
        except discord.HTTPException:
            return None
    if getattr(parent, "type", None) != discord.ChannelType.category:
        return None
    return parent


async def _ensure_named_category(bot, guild, *, name, config_key, names, overwrites):
    tickets = bot.config["discord"]["tickets"]
    configured = str(tickets.get(config_key) or "").strip()
    parent = await _load_category(guild, configured)
    if parent is None:
        wanted = {str(item or "").strip().lower() for item in names if str(item or "").strip()}
        for item in guild.categories:
            if str(item.name or "").strip().lower() in wanted:
                parent = item
                break
    try:
        if parent is None:
            parent = await guild.create_category(
                name,
                overwrites=overwrites,
                reason="Separate HR and HOD leave inboxes",
            )
            bot.logger.info("Created leave category", {"name": name, "category": str(parent.id)})
        else:
            await parent.edit(overwrites=overwrites, reason="Separate HR and HOD leave inboxes")
    except discord.HTTPException as error:
        bot.logger.warn("Could not prepare leave category", {"name": name, "message": str(error)})
        return parent
    tickets[config_key] = str(parent.id)
    return parent


async def ensure_hr_category(bot, guild):
    """#leave-requests lives in HR, not Tickets and not HOD."""
    return await _ensure_named_category(
        bot,
        guild,
        name="HR",
        config_key="hrCategoryId",
        names=(HR_CATEGORY_NAME,),
        overwrites=_review_overwrites(guild, bot.config),
    )


async def ensure_hod_category(bot, guild):
    """HOD inboxes live in HOD. HR and Admin can see the folder."""
    return await _ensure_named_category(
        bot,
        guild,
        name="HOD",
        config_key="hodCategoryId",
        names=(HOD_CATEGORY_NAME,),
        overwrites=_hod_category_overwrites(guild, bot.config),
    )


async def ensure_leave_category(bot, guild):
    """Back-compat: HR category (not the old shared Leave folder)."""
    return await ensure_hr_category(bot, guild)


async def ensure_leave_review_channel(bot, guild):
    """Find or create #leave-requests. Only Admin and HR can see it."""
    tickets = bot.config["discord"]["tickets"]
    configured = str(tickets.get("leaveReviewChannelId") or "").strip()
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
            if str(item.name or "").strip().lower() == REVIEW_CHANNEL_NAME:
                channel = item
                break
    overwrites = _review_overwrites(guild, bot.config)
    parent = await ensure_hr_category(bot, guild)
    topic = "Leave requests for Admin and HR only after HOD approval."
    try:
        if channel is None:
            channel = await guild.create_text_channel(
                REVIEW_CHANNEL_NAME,
                category=parent,
                overwrites=overwrites,
                topic=topic,
                reason="Private leave approval inbox for Admin and HR",
            )
            bot.logger.info("Created leave-requests channel", {"channel": str(channel.id)})
        else:
            await channel.edit(overwrites=overwrites, topic=topic, category=parent)
    except discord.HTTPException as error:
        bot.logger.warn("Could not prepare leave-requests channel", {"message": str(error)})
        return channel
    tickets["leaveReviewChannelId"] = str(channel.id)
    return channel


async def ensure_hod_channel(bot, guild, department):
    dept = normalize_department(department)
    if not dept:
        return None
    tickets = bot.config["discord"]["tickets"]
    tickets.setdefault("hodChannels", {})
    configured = str((tickets.get("hodChannels") or {}).get(dept) or "").strip()
    name = hod_channel_name(dept)
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
            if str(item.name or "").strip().lower() == name:
                channel = item
                break
    overwrites = _hod_overwrites(guild, bot.config, dept)
    parent = await ensure_hod_category(bot, guild)
    topic = f"{hod_display_name(dept)} leave inbox. Not a ticket. View-only for this HOD (HR/Admin can also see)."
    try:
        if channel is None:
            channel = await guild.create_text_channel(
                name,
                category=parent,
                overwrites=overwrites,
                topic=topic,
                reason=f"Private leave inbox for {hod_display_name(dept)}",
            )
            bot.logger.info("Created HOD leave channel", {"channel": str(channel.id), "department": dept})
        else:
            await channel.edit(overwrites=overwrites, topic=topic, category=parent)
    except discord.HTTPException as error:
        bot.logger.warn("Could not prepare HOD leave channel", {"department": dept, "message": str(error)})
        return channel
    tickets["hodChannels"][dept] = str(channel.id)
    return channel


async def ensure_hod_channels(bot, guild):
    for dept in DEPARTMENTS:
        await ensure_hod_channel(bot, guild, dept)


def is_hod_inbox_channel(channel, config):
    if channel is None:
        return False
    cid = str(getattr(channel, "id", "") or "")
    names = set(CHANNEL_NAMES.values())
    if str(getattr(channel, "name", "") or "").strip().lower() in names:
        return True
    return cid in set(hod_channel_ids_from_config(config).values())


def hod_department_for_channel(channel, config):
    if channel is None:
        return ""
    cid = str(getattr(channel, "id", "") or "")
    for dept, stored in hod_channel_ids_from_config(config).items():
        if stored == cid:
            return dept
    name = str(getattr(channel, "name", "") or "").strip().lower()
    for dept, expected in CHANNEL_NAMES.items():
        if name == expected:
            return dept
    return ""


def is_leave_inbox_channel(channel, config):
    return is_leave_review_channel(channel, config) or is_hod_inbox_channel(channel, config)


def _inbox_mentions(guild, config, *, department=""):
    roles = []
    hr_cfg = (config or {}).get("hr") or {}
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    ids = []
    if department:
        role_list = [{"id": str(role.id), "name": role.name} for role in guild.roles]
        hod_id = find_hod_role_id(
            role_list, department, hod_role_ids_from_config(config).get(department, "")
        )
        ids.append(hod_id)
        ids.append(_admin_role_id_for_hod_inbox(guild, config))
    else:
        ids.extend((
            hr_cfg.get("hrRoleId"),
            hr_cfg.get("adminRoleId"),
            tickets.get("adminRoleId"),
        ))
    for role_id in ids:
        role = _role(guild, role_id)
        if role and f"<@&{role.id}>" not in roles:
            roles.append(f"<@&{role.id}>")
    return " ".join(roles).strip() or None


async def _publish_to_channel(bot, *, channel, embed, mention_roles, view, ticket, ticket_channel_id, message_key, channel_key, ticket_name):
    old_id = (ticket or {}).get(message_key)
    try:
        sent = await channel.send(content=mention_roles, embed=embed, view=view)
    except discord.HTTPException as error:
        bot.logger.warn("Could not post leave request to inbox", {"message": str(error)})
        return None
    stored = bot.store.get_by_channel(ticket_channel_id) or ticket
    if stored:
        bot.store.upsert({
            **stored,
            message_key: str(sent.id),
            channel_key: str(channel.id),
            "channelName": ticket_name or stored.get("channelName") or "",
        })
    if old_id and str(old_id) != str(sent.id):
        try:
            old = await channel.fetch_message(int(old_id))
            await old.delete()
        except Exception:
            pass
    return sent


async def publish_leave_inbox(bot, *, ticket_channel, card, employee_id=""):
    """Post the request to #leave-requests (HR, with buttons) AND, when the
    employee's department has an HOD, to that HOD's channel simultaneously
    (view-only, no buttons). HR is always notified; HOD notification is
    additional, never a substitute."""
    guild = getattr(ticket_channel, "guild", None)
    if guild is None:
        return None
    department = hod_inbox_department(card)
    mention = f"<@{employee_id}>" if employee_id else ""
    ticket_name = str(getattr(ticket_channel, "name", "") or "")
    employee = None
    if bot.hr is not None and employee_id:
        try:
            from app.records.employees import get_employee_by_discord_id

            employee = get_employee_by_discord_id(bot.hr.client, employee_id, logger=bot.logger)
        except Exception:
            employee = None
    client = bot.hr.client if bot.hr is not None else None
    display_name = ""
    if employee_id and guild is not None:
        try:
            member = guild.get_member(int(employee_id))
            display_name = str(
                getattr(member, "display_name", None) or getattr(member, "name", "") or ""
            )
        except (TypeError, ValueError):
            display_name = ""
    card = polish_reviewer_card(
        card,
        client=client,
        employee=employee,
        logger=getattr(bot, "logger", None),
        ticket_name=ticket_name,
        display_name=display_name,
    )
    embed = inbox_embed(
        card,
        ticket_channel_id=str(ticket_channel.id),
        employee_mention=mention,
        ticket_name=ticket_name,
    )
    ticket = bot.store.get_by_channel(ticket_channel.id)

    hr_channel = await ensure_leave_review_channel(bot, guild)
    hr_sent = None
    if hr_channel is not None:
        hr_sent = await _publish_to_channel(
            bot,
            channel=hr_channel,
            embed=embed,
            mention_roles=_inbox_mentions(guild, bot.config),
            view=LeaveReviewView(bot),
            ticket=ticket,
            ticket_channel_id=ticket_channel.id,
            message_key="leaveInboxMessageId",
            channel_key="leaveInboxChannelId",
            ticket_name=ticket_name,
        )

    hod_sent = None
    if department:
        hod_channel = await ensure_hod_channel(bot, guild, department)
        if hod_channel is not None:
            hod_sent = await _publish_to_channel(
                bot,
                channel=hod_channel,
                embed=embed,
                mention_roles=_inbox_mentions(guild, bot.config, department=department),
                view=None,
                ticket=ticket,
                ticket_channel_id=ticket_channel.id,
                message_key="hodInboxMessageId",
                channel_key="hodInboxChannelId",
                ticket_name=ticket_name,
            )

    try:
        await _dm_inbox_reviewers(bot, guild, embed, waiting_hod=False, department="", employee_id=employee_id)
        if department:
            await _dm_inbox_reviewers(
                bot, guild, embed, waiting_hod=True, department=department, employee_id=employee_id
            )
    except Exception as error:
        bot.logger.warn("Leave inbox DM failed", {"message": str(error)[:200]})
    return hr_sent or hod_sent


async def _dm_inbox_reviewers(bot, guild, embed, *, waiting_hod, department, employee_id):
    """DM only the HOD for that channel, or HR for #leave-requests."""
    from app.discord.notify import dm_member

    if guild is None:
        return
    roles = [{"id": str(role.id), "name": role.name} for role in guild.roles]
    tickets = (bot.config.get("discord") or {}).get("tickets") or {}
    hr_cfg = (bot.config or {}).get("hr") or {}
    role_id = ""
    if waiting_hod and department:
        role_id = find_hod_role_id(
            roles, department, hod_role_ids_from_config(bot.config).get(department, "")
        )
        line = "A leave request is waiting in your HOD inbox."
    else:
        role_id = str(hr_cfg.get("hrRoleId") or tickets.get("adminRoleId") or "").strip()
        line = "A leave request is waiting in #leave-requests."
    role = _role(guild, role_id)
    if role is None:
        return
    skip = str(employee_id or "")
    for member in getattr(role, "members", []) or []:
        if getattr(member, "bot", False) or str(member.id) == skip:
            continue
        sent = await dm_member(bot, member.id, content=line, embed=embed, guild=guild)
        if sent:
            bot.logger.info("Leave inbox DM sent", {
                "user": str(member.id),
                "waitingHod": waiting_hod,
                "department": department or "",
            })


async def _edit_inbox_message(bot, channel_id, message_id, embed, *, buttons=False):
    if not channel_id or not message_id:
        return
    try:
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            return
        message = await channel.fetch_message(int(message_id))
        view = LeaveReviewView(bot) if buttons else None
        if embed is not None:
            await message.edit(embed=embed, view=view)
        else:
            await message.edit(view=view)
    except Exception:
        pass


async def finalize_leave_inbox(bot, ticket_channel_id, *, embed=None, remove=False):
    """Update HOD and HR inbox cards. Final cards have no Approve/Reject."""
    del remove
    ticket = bot.store.get_by_channel(ticket_channel_id)
    if not ticket:
        return
    await _edit_inbox_message(
        bot, ticket.get("hodInboxChannelId"), ticket.get("hodInboxMessageId"), embed, buttons=False
    )
    hr_channel = ticket.get("leaveInboxChannelId") or leave_review_channel_id(bot.config)
    await _edit_inbox_message(bot, hr_channel, ticket.get("leaveInboxMessageId"), embed, buttons=False)


def ticket_channel_id_from_message(message, bot=None):
    for embed in getattr(message, "embeds", None) or []:
        footer = getattr(getattr(embed, "footer", None), "text", "") or ""
        ticket_id = ticket_id_from_footer(footer)
        if ticket_id:
            return ticket_id
        for field in getattr(embed, "fields", None) or []:
            if str(getattr(field, "name", "") or "").strip().lower() != "ticket":
                continue
            found = CHANNEL_MENTION.search(str(getattr(field, "value", "") or ""))
            if found:
                return found.group(1)
    if bot is not None and getattr(message, "id", None):
        for item in (bot.store.all() or {}).values():
            if str(item.get("leaveInboxMessageId") or "") == str(message.id):
                return str(item.get("channelId") or "")
            if str(item.get("hodInboxMessageId") or "") == str(message.id):
                return str(item.get("channelId") or "")
    return ""

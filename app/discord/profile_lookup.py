"""HR-only profile lookup + edit/delete: /profile and /deleteprofile in #hr-profiles.

Looks a person up by Discord user ID or name and prints their full
onboarding profile. HR/Admin can edit contact fields or delete the profile
(DB wipe + Discord kick). Nothing else runs in this channel.
"""

import asyncio
import re
from datetime import datetime

import discord

from app.hr.leave_status import ADMIN, HR
from app.hr.permissions import tier_for
from app.mail.leave import is_email
from app.records.employees import (
    delete_employee_profile,
    find_employees_by_name,
    lookup_employee_by_discord_id,
    update_employee_profile,
)

PROFILE_EDIT_ID = "profile:edit"
CNIC_RE = re.compile(r"^\d{5}-?\d{7}-?\d{1}$")
CONTACT_RE = re.compile(r"^[0-9+\-\s]{7,20}$")


def _config_channel_id(config):
    tickets = (config.get("discord") or {}).get("tickets") or {}
    return str(tickets.get("hrProfileChannelId") or "").strip()


def is_hr_profile_channel(bot, channel_id):
    configured = _config_channel_id(bot.config)
    return bool(configured) and str(channel_id) == configured


async def ensure_hr_profile_channel(bot, guild):
    """Find or create #hr-profiles. HR and Admin only; profile lookups only."""
    from app.discord.leave_inbox import ensure_hr_category, _review_overwrites

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
            if str(item.name or "").strip().lower() == "hr-profiles":
                channel = item
                break
    overwrites = _review_overwrites(guild, bot.config)
    parent = await ensure_hr_category(bot, guild)
    topic = (
        "HR only. /profile <user id or name> to look up or edit. "
        "/deleteprofile <user id or name> to wipe DB and kick from the server."
    )
    try:
        if channel is None:
            channel = await guild.create_text_channel(
                "hr-profiles",
                category=parent,
                overwrites=overwrites,
                topic=topic,
                reason="Dedicated HR profile lookup channel",
            )
            bot.logger.info("Created hr-profiles channel", {"channel": str(channel.id)})
        else:
            await channel.edit(overwrites=overwrites, topic=topic, category=parent)
    except discord.HTTPException as error:
        bot.logger.warn("Could not prepare hr-profiles channel", {"message": str(error)})
        return channel
    tickets["hrProfileChannelId"] = str(channel.id)
    return channel


def profile_embed(employee):
    name = employee.get("name") or "Unknown"
    embed = discord.Embed(title=f"Profile — {name}", color=0x2563EB)
    discord_id = employee.get("discordUserId") or ""
    embed.add_field(name="Discord", value=f"<@{discord_id}>" if discord_id else "—", inline=True)
    embed.add_field(name="Employee ID", value=employee.get("employeeId") or "—", inline=True)
    embed.add_field(name="Status", value=employee.get("status") or "—", inline=True)
    embed.add_field(name="Department", value=employee.get("department") or "—", inline=True)
    embed.add_field(name="HR Role", value=employee.get("hrRole") or "Member", inline=True)
    embed.add_field(name="Designation", value=employee.get("designation") or "—", inline=True)
    embed.add_field(name="Join Date", value=employee.get("joinDate") or "—", inline=True)
    embed.add_field(name="Email", value=employee.get("email") or "—", inline=True)
    embed.add_field(name="Contact Number", value=employee.get("contactNumber") or "—", inline=True)
    embed.add_field(name="CNIC", value=employee.get("cnic") or "—", inline=True)
    embed.add_field(name="Date of Birth", value=employee.get("dob") or "—", inline=True)
    embed.add_field(name="Address", value=employee.get("address") or "—", inline=False)
    if employee.get("photoPath"):
        embed.add_field(name="Photo", value="Attached", inline=True)
    embed.set_footer(text="HR / Admin: Edit profile — step 1 name/contact/CNIC, step 2 email/DOB/address/designation")
    return embed


def _profile_photo_file(bot, employee):
    from app.records.employee_photos import resolve_photo_path

    root = (getattr(bot, "config", None) or {}).get("rootDir")
    path = resolve_photo_path(root, (employee or {}).get("photoPath"))
    if path is None:
        return None
    return discord.File(str(path), filename=path.name)


async def _send_profile_card(interaction, bot, employee, *, view, followup=False):
    embed = profile_embed(employee)
    photo = _profile_photo_file(bot, employee)
    kwargs = {"embed": embed, "view": view, "ephemeral": True}
    if photo is not None:
        embed.set_image(url=f"attachment://{photo.filename}")
        kwargs["file"] = photo
    if followup:
        await interaction.followup.send(**kwargs)
        return
    await interaction.response.send_message(**kwargs)


def _actor_may_manage(interaction, bot, *, action="edit"):
    if not is_hr_profile_channel(bot, interaction.channel_id):
        return False, f"{action.capitalize()} profiles only in the HR profiles channel."
    tier = tier_for(interaction.user, bot.config)
    if tier not in {HR, ADMIN}:
        return False, f"Only HR or Admin can {action} profiles."
    if bot.hr is None or bot.hr.client is None:
        return False, "HR data is not connected right now."
    return True, None


def _actor_may_edit(interaction, bot):
    return _actor_may_manage(interaction, bot, action="edit")


def _actor_may_delete(interaction, bot):
    return _actor_may_manage(interaction, bot, action="delete")


async def _resolve_employee(bot, query):
    """Resolve one employee by Discord id/mention or unique name. Returns (employee, matches)."""
    query = str(query or "").strip()
    digits = query.lstrip("<@!").rstrip(">")
    employee = None
    if digits.isdigit():
        employee = await asyncio.to_thread(
            lookup_employee_by_discord_id, bot.hr.client, digits, logger=bot.logger
        )
    matches = []
    if employee is None:
        matches = await asyncio.to_thread(
            find_employees_by_name, bot.hr.client, query, logger=bot.logger
        )
    if employee is None and len(matches) == 1:
        employee = matches[0]
    return employee, matches


def _validate_profile_step_one(*, full_name, contact_number, cnic):
    errors = []
    if not str(full_name or "").strip():
        errors.append("Full Name is required.")
    if not CONTACT_RE.match(str(contact_number or "").strip()):
        errors.append("Contact Number must be 7-20 digits (may include + or -).")
    cnic_clean = str(cnic or "").strip()
    if cnic_clean and not CNIC_RE.match(cnic_clean):
        errors.append("CNIC must look like 12345-1234567-1 (13 digits, dashes optional).")
    return errors


def _validate_profile_step_two(*, email, dob, address):
    errors = []
    if not is_email(str(email or "").strip()):
        errors.append("Email is not a valid email address.")
    dob_clean = str(dob or "").strip()
    if dob_clean:
        try:
            datetime.strptime(dob_clean[:10], "%Y-%m-%d")
        except ValueError:
            errors.append("Date of Birth must be YYYY-MM-DD.")
    if not str(address or "").strip():
        errors.append("Address is required.")
    return errors


class ProfileEditView(discord.ui.View):
    """Edit button shown under a looked-up profile (ephemeral, HR/Admin only)."""

    def __init__(self, bot, employee):
        super().__init__(timeout=600)
        self.bot = bot
        self.employee = dict(employee or {})

    @discord.ui.button(label="Edit profile", style=discord.ButtonStyle.primary, custom_id=PROFILE_EDIT_ID)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        ok, error = _actor_may_edit(interaction, self.bot)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_modal(ProfileEditModalOne(self.bot, self.employee))


def _continue_profile_step_two_view(bot, employee):
    view = discord.ui.View(timeout=600)

    async def _continue(interaction: discord.Interaction):
        ok, error = _actor_may_edit(interaction, bot)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_modal(ProfileEditModalTwo(bot, employee))

    button = discord.ui.Button(label="Continue to email / DOB / address", style=discord.ButtonStyle.primary)
    button.callback = _continue
    view.add_item(button)
    return view


class ProfileEditModalOne(discord.ui.Modal, title="Edit profile — Step 1 of 2"):
    """Name, Contact Number, CNIC — same layout as onboarding step 1."""

    def __init__(self, bot, employee):
        super().__init__()
        self.bot = bot
        self.employee = dict(employee or {})
        self.full_name = discord.ui.TextInput(
            label="Full Name",
            max_length=100,
            required=True,
            default=str(employee.get("name") or "")[:100],
        )
        self.contact_number = discord.ui.TextInput(
            label="Contact Number",
            max_length=20,
            required=True,
            default=str(employee.get("contactNumber") or "")[:20],
        )
        self.cnic = discord.ui.TextInput(
            label="CNIC",
            placeholder="12345-1234567-1",
            max_length=15,
            required=False,
            default=str(employee.get("cnic") or "")[:15],
        )
        self.add_item(self.full_name)
        self.add_item(self.contact_number)
        self.add_item(self.cnic)

    async def on_submit(self, interaction: discord.Interaction):
        ok, error = _actor_may_edit(interaction, self.bot)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        errors = _validate_profile_step_one(
            full_name=str(self.full_name),
            contact_number=str(self.contact_number),
            cnic=str(self.cnic),
        )
        if errors:
            await interaction.response.send_message(
                "Please fix the following:\n- " + "\n- ".join(errors),
                ephemeral=True,
            )
            return
        record_id = str(self.employee.get("id") or "").strip()
        if not record_id:
            await interaction.response.send_message("Could not find that employee row.", ephemeral=True)
            return
        fields = {
            "Employee Name": str(self.full_name).strip(),
            "Contact Number": str(self.contact_number).strip(),
            "CNIC": str(self.cnic).strip(),
        }
        try:
            updated = await asyncio.to_thread(
                update_employee_profile,
                self.bot.hr.client,
                record_id,
                fields=fields,
                logger=self.bot.logger,
            )
        except Exception as error:
            self.bot.logger.error("Profile edit step 1 failed", {"message": str(error)[:300]})
            await interaction.response.send_message(
                "Could not save the profile. Please try again.", ephemeral=True
            )
            return
        if not updated:
            await interaction.response.send_message("Employee record was not found.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Step 1 saved (name, contact, CNIC). Click **Continue** for email, date of birth, address, and designation.",
            view=_continue_profile_step_two_view(self.bot, updated),
            ephemeral=True,
        )


class ProfileEditModalTwo(discord.ui.Modal, title="Edit profile — Step 2 of 2"):
    """Email, DOB, Address, Designation — same layout as onboarding step 2 plus title."""

    def __init__(self, bot, employee):
        super().__init__()
        self.bot = bot
        self.employee = dict(employee or {})
        self.email = discord.ui.TextInput(
            label="Email",
            max_length=255,
            required=True,
            default=str(employee.get("email") or "")[:255],
        )
        self.dob = discord.ui.TextInput(
            label="Date of Birth (YYYY-MM-DD)",
            placeholder="1998-05-20",
            max_length=10,
            required=False,
            default=str(employee.get("dob") or "")[:10],
        )
        self.address = discord.ui.TextInput(
            label="Address",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True,
            default=str(employee.get("address") or "")[:500],
        )
        self.designation = discord.ui.TextInput(
            label="Designation",
            placeholder="e.g. Software Engineer",
            max_length=80,
            required=False,
            default=str(employee.get("designation") or "")[:80],
        )
        self.add_item(self.email)
        self.add_item(self.dob)
        self.add_item(self.address)
        self.add_item(self.designation)

    async def on_submit(self, interaction: discord.Interaction):
        ok, error = _actor_may_edit(interaction, self.bot)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        errors = _validate_profile_step_two(
            email=str(self.email),
            dob=str(self.dob),
            address=str(self.address),
        )
        if errors:
            await interaction.response.send_message(
                "Please fix the following:\n- " + "\n- ".join(errors),
                ephemeral=True,
            )
            return
        record_id = str(self.employee.get("id") or "").strip()
        if not record_id:
            await interaction.response.send_message("Could not find that employee row.", ephemeral=True)
            return
        fields = {
            "Email": str(self.email).strip(),
            "DOB": str(self.dob).strip()[:10],
            "Address": str(self.address).strip(),
            "Designation": str(self.designation).strip(),
        }
        try:
            updated = await asyncio.to_thread(
                update_employee_profile,
                self.bot.hr.client,
                record_id,
                fields=fields,
                logger=self.bot.logger,
            )
        except Exception as error:
            self.bot.logger.error("Profile edit step 2 failed", {"message": str(error)[:300]})
            await interaction.response.send_message(
                "Could not save the profile. Please try again.", ephemeral=True
            )
            return
        if not updated:
            await interaction.response.send_message("Employee record was not found.", ephemeral=True)
            return
        await _send_profile_card(
            interaction, self.bot, updated, view=ProfileEditFollowupView(self.bot, updated)
        )


# Back-compat alias used by older tests / imports.
ProfileEditModal = ProfileEditModalOne


class ProfileEditFollowupView(discord.ui.View):
    def __init__(self, bot, employee):
        super().__init__(timeout=600)
        self.bot = bot
        self.employee = dict(employee or {})

    @discord.ui.button(label="Edit step 1 (name / contact / CNIC)", style=discord.ButtonStyle.primary)
    async def edit_step_one(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        ok, error = _actor_may_edit(interaction, self.bot)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_modal(ProfileEditModalOne(self.bot, self.employee))

    @discord.ui.button(label="Edit step 2 (email / DOB / address / title)", style=discord.ButtonStyle.secondary)
    async def edit_step_two(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        ok, error = _actor_may_edit(interaction, self.bot)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_modal(ProfileEditModalTwo(self.bot, self.employee))


class ProfileDeleteConfirmView(discord.ui.View):
    """Confirm / cancel before wiping DB and kicking the member."""

    def __init__(self, bot, employee, actor_id):
        super().__init__(timeout=120)
        self.bot = bot
        self.employee = dict(employee or {})
        self.actor_id = str(actor_id)

    async def interaction_check(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.actor_id:
            await interaction.response.send_message(
                "Only the HR member who started this delete can confirm it.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm delete + kick", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        ok, error = _actor_may_delete(interaction, self.bot)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="Deleting profile and kicking member…",
            embed=None,
            view=self,
        )
        result = await _execute_profile_delete(interaction, self.bot, self.employee)
        try:
            await interaction.edit_original_response(content=result, view=None)
        except discord.HTTPException:
            await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="Delete cancelled. Profile was not changed.",
            embed=None,
            view=self,
        )


async def _execute_profile_delete(interaction, bot, employee):
    """Wipe MySQL rows, restore onboarding access, then kick. Returns a status message."""
    from app.discord.onboarding import (
        _clear_draft,
        restore_onboarding_access,
        strip_roles_after_profile_delete,
    )
    from app.records.employee_photos import resolve_photo_path

    name = employee.get("name") or "Unknown"
    discord_id = str(employee.get("discordUserId") or "").strip()
    if discord_id and discord_id == str(interaction.user.id):
        return "You cannot delete your own profile."

    try:
        summary = await asyncio.to_thread(
            delete_employee_profile,
            bot.hr.client,
            employee,
            logger=bot.logger,
        )
    except Exception as error:
        bot.logger.error("Profile delete failed", {"message": str(error)[:300]})
        return f"Could not delete **{name}** from the database. Please try again."

    if not summary:
        return f"Could not delete **{name}** — record missing."

    # Drop the onboarding photo file (MySQL only stored the path).
    root = (getattr(bot, "config", None) or {}).get("rootDir")
    photo = resolve_photo_path(root, employee.get("photoPath"))
    if photo is not None:
        try:
            photo.unlink()
        except OSError as error:
            bot.logger.warn("Could not delete employee photo file", {"message": str(error)[:200]})

    if discord_id:
        _clear_draft(bot, discord_id)

    kick_note = "Member was not in this server (DB still cleared)."
    onboard_note = "Onboarding will be required if they join again."
    guild = interaction.guild
    if guild is not None and discord_id.isdigit():
        member = guild.get_member(int(discord_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(discord_id))
            except discord.NotFound:
                member = None
            except discord.HTTPException as error:
                bot.logger.warn("Could not fetch member to kick", {"message": str(error)[:200]})
                member = None
        if member is not None:
            removed = await strip_roles_after_profile_delete(
                member,
                reason=f"HR deleted profile ({interaction.user})",
            )
            await restore_onboarding_access(
                bot,
                member,
                reason=f"HR deleted profile ({interaction.user})",
            )
            if removed:
                onboard_note = (
                    "Workplace roles removed and #onboarding restored — "
                    "they must onboard again (also if they rejoin)."
                )
            try:
                await member.kick(reason=f"HR deleted profile ({interaction.user})")
                kick_note = f"Kicked <@{discord_id}> from the server."
            except discord.Forbidden:
                kick_note = (
                    f"DB cleared, but I could not kick <@{discord_id}> "
                    "(missing Kick Members permission or role hierarchy). "
                    "They must complete onboarding again in #onboarding."
                )
            except discord.HTTPException as error:
                bot.logger.warn("Kick failed after profile delete", {"message": str(error)[:200]})
                kick_note = (
                    f"DB cleared, but kick failed for <@{discord_id}>. "
                    "They must complete onboarding again in #onboarding."
                )

    return (
        f"Deleted **{name}** from the database "
        f"(requests={summary['leaveRequests']}, balances={summary['leaveBalances']}, "
        f"utilization={summary['leaveUtilization']}).\n{kick_note}\n{onboard_note}"
    )


async def run_profile_lookup(interaction: discord.Interaction, bot, query):
    if not is_hr_profile_channel(bot, interaction.channel_id):
        await interaction.response.send_message(
            "Use `/profile` in the HR profiles channel only.", ephemeral=True
        )
        return
    tier = tier_for(interaction.user, bot.config)
    if tier not in {HR, ADMIN}:
        await interaction.response.send_message("Only HR or Admin can look up profiles.", ephemeral=True)
        return
    if bot.hr is None or bot.hr.client is None:
        await interaction.response.send_message("HR data is not connected right now.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    employee, matches = await _resolve_employee(bot, query)
    if employee is not None:
        await _send_profile_card(
            interaction, bot, employee, view=ProfileEditView(bot, employee), followup=True
        )
        return
    if len(matches) > 1:
        names = "\n".join(f"- {item.get('name')} (<@{item.get('discordUserId')}>)" for item in matches[:10])
        await interaction.followup.send(
            f"Multiple matches for **{query}**. Try a Discord user ID instead:\n{names}",
            ephemeral=True,
        )
        return
    await interaction.followup.send(f"No profile found for **{query}**.", ephemeral=True)


async def run_profile_delete(interaction: discord.Interaction, bot, query):
    """HR/Admin: confirm, then wipe employee from DB and kick from the server."""
    ok, error = _actor_may_delete(interaction, bot)
    if not ok:
        await interaction.response.send_message(error, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    employee, matches = await _resolve_employee(bot, query)
    if employee is None and len(matches) > 1:
        names = "\n".join(f"- {item.get('name')} (<@{item.get('discordUserId')}>)" for item in matches[:10])
        await interaction.followup.send(
            f"Multiple matches for **{query}**. Try a Discord user ID instead:\n{names}",
            ephemeral=True,
        )
        return
    if employee is None:
        await interaction.followup.send(f"No profile found for **{query}**.", ephemeral=True)
        return
    discord_id = str(employee.get("discordUserId") or "").strip()
    if discord_id and discord_id == str(interaction.user.id):
        await interaction.followup.send("You cannot delete your own profile.", ephemeral=True)
        return
    name = employee.get("name") or "Unknown"
    mention = f"<@{discord_id}>" if discord_id else "—"
    embed = discord.Embed(
        title="Delete profile?",
        description=(
            f"This will **permanently delete** **{name}** ({mention}) from the database "
            "(leave requests, balances, utilization) and **kick them from this server**."
        ),
        color=0xDC2626,
    )
    embed.set_footer(text="This cannot be undone.")
    await interaction.followup.send(
        embed=embed,
        view=ProfileDeleteConfirmView(bot, employee, interaction.user.id),
        ephemeral=True,
    )

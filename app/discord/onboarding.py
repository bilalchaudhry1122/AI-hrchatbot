"""Self-service onboarding: form -> role assignment -> employee row.

Flow: #onboarding channel -> "Start Onboarding" button ->
Modal 1 (name, contact, CNIC) -> Modal 2 (email, DOB, address) ->
Department -> designation -> optional photo -> {Dept} Member (or HR) + employee row.
HOD Discord roles are assigned later by HR/Admin, not by this form.
"""

import asyncio
import re
from datetime import date, datetime

import discord

from app.discord.announcements import post_onboard_welcome
from app.hr.leave_access import leave_disabled_for_department_level
from app.hr.staff_onboard import upsert_staff_employee
from app.mail.leave import is_email
from app.records.employee_photos import MAX_BYTES, store_employee_photo
from app.records.employees import completed_onboarding, lookup_employee_by_discord_id
from app.tickets.helpers import find_admin_role_id, find_hr_role_id

ONBOARDING_CHANNEL_NAME = "onboarding"
ONBOARDING_START_ID = "onboarding:start"
ONBOARDING_RETRY_ONE_ID = "onboarding:retry:1"
ONBOARDING_PHOTO_ADD_ID = "onboarding:photo:add"
ONBOARDING_PHOTO_SKIP_ID = "onboarding:photo:skip"

CNIC_RE = re.compile(r"^\d{5}-?\d{7}-?\d{1}$")
CONTACT_RE = re.compile(r"^[0-9+\-\s]{7,20}$")

DEPARTMENT_OPTIONS = ("BI", "CS", "Sales", "Marketing", "HR")
DESIGNATION_MAX = 80

# Roles that mean "already onboarded" — they must not see #onboarding again.
# HR/Admin keep access so they can help new joiners.
_ONBOARDING_HIDE_EXACT = {
    "bi member",
    "cs member",
    "sales member",
    "marketing member",
    "bi hod",
    "cs hod",
    "marketing hod",
    "staff",
}


def _drafts(bot):
    """Per-user onboarding drafts so validation errors can reopen with values filled."""
    store = getattr(bot, "_onboarding_drafts", None)
    if store is None:
        store = {}
        bot._onboarding_drafts = store
    return store


def _save_draft(bot, user_id, profile):
    if bot is None or not user_id:
        return
    _drafts(bot)[str(user_id)] = dict(profile or {})


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


def _config_channel_id(config):
    tickets = (config.get("discord") or {}).get("tickets") or {}
    return str(tickets.get("onboardingChannelId") or "").strip()


def _is_onboarded_workplace_role(name):
    lowered = str(name or "").strip().lower()
    if not lowered or lowered in {"@everyone", "hr", "admin", "administrator", "admins"}:
        return False
    if lowered in _ONBOARDING_HIDE_EXACT:
        return True
    if lowered.endswith(" member"):
        return True
    if " hod" in lowered or lowered.endswith(" hod") or lowered.startswith("hod "):
        return True
    return False


def _onboarding_overwrites(guild, config):
    """New joiners (@everyone) can see #onboarding; onboarded workplace roles cannot.

    HR and Admin keep access. Bot can post.
    """
    roles = [{"id": str(role.id), "name": role.name} for role in getattr(guild, "roles", []) or []]
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    hr_cfg = (config or {}).get("hr") or {}
    admin_id = find_admin_role_id(roles, tickets.get("adminRoleId")) or hr_cfg.get("adminRoleId")
    hr_id = hr_cfg.get("hrRoleId") or find_hr_role_id(roles, "")
    read = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
    hide = discord.PermissionOverwrite(view_channel=False)
    post = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    overwrites = {guild.default_role: read}
    bot_member = getattr(guild, "me", None)
    if isinstance(bot_member, discord.Member):
        overwrites[bot_member] = post
    for role in getattr(guild, "roles", []) or []:
        if _is_onboarded_workplace_role(getattr(role, "name", "")):
            overwrites[role] = hide
    for role_id in (admin_id, hr_id):
        if not str(role_id or "").strip().isdigit():
            continue
        role = guild.get_role(int(role_id))
        if role:
            overwrites[role] = read
    return overwrites


async def hide_onboarding_for_member(bot, member):
    """After onboarding, hide #onboarding from that person (member overwrite)."""
    if member is None or getattr(member, "bot", False):
        return
    config = getattr(bot, "config", None) or {}
    channel_id = _config_channel_id(config)
    if not channel_id.isdigit():
        return
    guild = getattr(member, "guild", None)
    if guild is None:
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return
    try:
        await channel.set_permissions(
            member,
            view_channel=False,
            reason="Onboarded — onboarding channel no longer needed",
        )
    except discord.HTTPException as error:
        logger = getattr(bot, "logger", None)
        if logger:
            logger.warn("Could not hide onboarding channel for member", {
                "user": str(getattr(member, "id", "")),
                "message": str(error)[:200],
            })


async def ensure_onboarding_channel(bot, guild):
    """Find or create #onboarding. Visible to new joiners; hidden from onboarded roles."""
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
            if str(item.name or "").strip().lower() == ONBOARDING_CHANNEL_NAME:
                channel = item
                break
    overwrites = _onboarding_overwrites(guild, bot.config)
    try:
        if channel is None:
            channel = await guild.create_text_channel(
                ONBOARDING_CHANNEL_NAME,
                overwrites=overwrites,
                topic="New here? Click Start Onboarding to fill your profile and get your role.",
                reason="Self-service onboarding entry point",
            )
            bot.logger.info("Created onboarding channel", {"channel": str(channel.id)})
        else:
            await channel.edit(overwrites=overwrites)
    except discord.HTTPException as error:
        bot.logger.warn("Could not prepare onboarding channel", {"message": str(error)})
    if channel is not None:
        tickets["onboardingChannelId"] = str(channel.id)
    return channel


async def ensure_onboarding_panel(bot, channel):
    """Post the Start Onboarding button once; skip if already posted."""
    try:
        async for message in channel.history(limit=20):
            if message.author.id == bot.user.id and message.components:
                return
    except discord.HTTPException:
        pass
    embed = discord.Embed(
        title="Welcome to WebAiry",
        description=(
            "Click **Start Onboarding** to fill in your profile.\n"
            "• Step 1: name, contact number, CNIC\n"
            "• Step 2: email, date of birth, address\n"
            "Then pick your department, type your designation, and optionally add a photo. "
            "Your department role is assigned automatically. HR/Admin assign HOD separately."
        ),
        color=0x4F46E5,
    )
    try:
        await channel.send(embed=embed, view=OnboardingStartView(bot))
    except discord.HTTPException as error:
        bot.logger.warn("Could not post onboarding panel", {"message": str(error)})


class OnboardingStartView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Start Onboarding", style=discord.ButtonStyle.success, custom_id=ONBOARDING_START_ID)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        bot = self.bot
        if bot.hr is None or bot.hr.client is None:
            await interaction.response.send_message(
                "HR data is not connected right now. Try again shortly or contact HR.",
                ephemeral=True,
            )
            return
        existing = await asyncio.to_thread(
            lookup_employee_by_discord_id, bot.hr.client, str(interaction.user.id), logger=bot.logger
        )
        # A bare row from role sync (e.g. HR given their role first) must not
        # block the form; only a completed form counts as onboarded.
        if completed_onboarding(existing):
            await interaction.response.send_message(
                "You're already onboarded. Contact HR if something needs updating.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            OnboardingModalOne(bot, draft=_load_draft(bot, interaction.user.id))
        )


def _retry_one_view(bot, draft):
    view = discord.ui.View(timeout=600)

    async def _retry(interaction: discord.Interaction):
        saved = _load_draft(bot, interaction.user.id) or draft
        await interaction.response.send_modal(OnboardingModalOne(bot, draft=saved))

    button = discord.ui.Button(label="Edit & try again", style=discord.ButtonStyle.primary)
    button.callback = _retry
    view.add_item(button)
    return view


def _retry_two_view(bot, profile):
    view = discord.ui.View(timeout=600)

    async def _retry(interaction: discord.Interaction):
        saved = _load_draft(bot, interaction.user.id) or profile
        await interaction.response.send_modal(OnboardingModalTwo(bot, saved))

    button = discord.ui.Button(label="Edit & try again", style=discord.ButtonStyle.primary)
    button.callback = _retry
    view.add_item(button)
    return view


def _resume_after_finalize_error_view(bot, profile):
    """Keep the filled profile after a late failure (role/DB) so they can edit or retry."""
    view = discord.ui.View(timeout=600)

    async def _edit(interaction: discord.Interaction):
        saved = _load_draft(bot, interaction.user.id) or profile
        await interaction.response.send_modal(OnboardingModalOne(bot, draft=saved))

    async def _retry_dept(interaction: discord.Interaction):
        saved = _load_draft(bot, interaction.user.id) or profile
        await interaction.response.edit_message(
            content="Pick your department again:",
            view=DepartmentSelectView(bot, saved),
        )

    edit_btn = discord.ui.Button(label="Edit details", style=discord.ButtonStyle.secondary)
    edit_btn.callback = _edit
    retry_btn = discord.ui.Button(label="Retry department", style=discord.ButtonStyle.primary)
    retry_btn.callback = _retry_dept
    view.add_item(edit_btn)
    view.add_item(retry_btn)
    return view


def _continue_to_step_two_view(bot, profile):
    """Modal submit cannot open another modal — Continue button opens step 2."""
    view = discord.ui.View(timeout=600)

    async def _continue(interaction: discord.Interaction):
        saved = _load_draft(bot, interaction.user.id) or profile
        await interaction.response.send_modal(OnboardingModalTwo(bot, saved))

    button = discord.ui.Button(label="Continue", style=discord.ButtonStyle.primary)
    button.callback = _continue
    view.add_item(button)
    return view


def _validate_step_one(full_name, contact_number, cnic):
    """Step 1: name, contact, CNIC."""
    errors = []
    if not str(full_name or "").strip():
        errors.append("Full Name is required.")
    if not CONTACT_RE.match(str(contact_number or "").strip()):
        errors.append("Contact Number must be 7-20 digits (may include + or -).")
    cnic_clean = str(cnic or "").strip()
    if not CNIC_RE.match(cnic_clean):
        errors.append("CNIC must look like 12345-1234567-1 (13 digits, dashes optional).")
    return errors


def _validate_step_two(email, dob, address):
    """Step 2: email, DOB, address."""
    errors = []
    if not is_email(str(email or "").strip()):
        errors.append("Email is not a valid email address.")
    dob_clean = str(dob or "").strip()
    parsed_dob = None
    try:
        parsed_dob = datetime.strptime(dob_clean, "%Y-%m-%d").date()
    except ValueError:
        errors.append("Date of Birth must be in YYYY-MM-DD format.")
    if parsed_dob is not None:
        today = date.today()
        oldest = today.replace(year=today.year - 90)
        youngest = today.replace(year=today.year - 14)
        if parsed_dob > youngest or parsed_dob < oldest:
            errors.append("Date of Birth looks incorrect. Use YYYY-MM-DD.")
    if not str(address or "").strip():
        errors.append("Address is required.")
    return errors


class OnboardingModalOne(discord.ui.Modal, title="Onboarding — Step 1 of 2"):
    """Name, Contact Number, CNIC."""

    def __init__(self, bot, draft=None):
        super().__init__()
        self.bot = bot
        draft = draft or {}
        self.full_name = discord.ui.TextInput(
            label="Full Name",
            max_length=100,
            required=True,
            default=_clip(draft.get("full_name"), 100) or None,
        )
        self.contact_number = discord.ui.TextInput(
            label="Contact Number",
            max_length=20,
            required=True,
            default=_clip(draft.get("contact_number"), 20) or None,
        )
        self.cnic = discord.ui.TextInput(
            label="CNIC",
            placeholder="12345-1234567-1",
            max_length=15,
            required=True,
            default=_clip(draft.get("cnic"), 15) or None,
        )
        self.add_item(self.full_name)
        self.add_item(self.contact_number)
        self.add_item(self.cnic)

    async def on_submit(self, interaction: discord.Interaction):
        prior = _load_draft(self.bot, interaction.user.id)
        profile = dict(prior)
        profile.update({
            "full_name": str(self.full_name).strip(),
            "contact_number": str(self.contact_number).strip(),
            "cnic": str(self.cnic).strip(),
        })
        _save_draft(self.bot, interaction.user.id, profile)
        errors = _validate_step_one(
            profile["full_name"], profile["contact_number"], profile["cnic"]
        )
        if errors:
            await interaction.response.send_message(
                "Please fix the following and try again. Your answers are kept — "
                "tap **Edit & try again** to update them:\n- " + "\n- ".join(errors),
                view=_retry_one_view(self.bot, profile),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Step 1 saved (name, contact, CNIC). Click **Continue** for email, date of birth, and address.",
            view=_continue_to_step_two_view(self.bot, profile),
            ephemeral=True,
        )


class OnboardingModalTwo(discord.ui.Modal, title="Onboarding — Step 2 of 2"):
    """Email, Date of Birth, Address."""

    def __init__(self, bot, profile):
        super().__init__()
        self.bot = bot
        self.profile = dict(profile or {})
        self.email = discord.ui.TextInput(
            label="Email",
            max_length=255,
            required=True,
            default=_clip(self.profile.get("email"), 255) or None,
        )
        self.dob = discord.ui.TextInput(
            label="Date of Birth (YYYY-MM-DD)",
            placeholder="1998-05-20",
            max_length=10,
            required=True,
            default=_clip(self.profile.get("dob"), 10) or None,
        )
        self.address = discord.ui.TextInput(
            label="Address",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True,
            default=_clip(self.profile.get("address"), 500) or None,
        )
        self.add_item(self.email)
        self.add_item(self.dob)
        self.add_item(self.address)

    async def on_submit(self, interaction: discord.Interaction):
        profile = dict(self.profile)
        profile["email"] = str(self.email).strip()
        profile["dob"] = str(self.dob).strip()[:10]
        profile["address"] = str(self.address).strip()
        _save_draft(self.bot, interaction.user.id, profile)
        errors = _validate_step_two(profile["email"], profile["dob"], profile["address"])
        if errors:
            await interaction.response.send_message(
                "Please fix the following. Your answers are kept — "
                "tap **Edit & try again**:\n- " + "\n- ".join(errors),
                view=_retry_two_view(self.bot, profile),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Almost done — pick your department, then type your designation:",
            view=DepartmentSelectView(self.bot, profile),
            ephemeral=True,
        )


class DepartmentSelectView(discord.ui.View):
    def __init__(self, bot, profile):
        super().__init__(timeout=300)
        self.bot = bot
        self.profile = profile
        self.add_item(DepartmentSelect(bot, profile))


class DepartmentSelect(discord.ui.Select):
    def __init__(self, bot, profile):
        self.bot = bot
        self.profile = profile
        options = [discord.SelectOption(label=dept, value=dept) for dept in DEPARTMENT_OPTIONS]
        super().__init__(placeholder="Choose your department", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        department = self.values[0]
        await interaction.response.send_modal(
            DesignationModal(self.bot, self.profile, department)
        )


class DesignationModal(discord.ui.Modal, title="Your designation"):
    """Everyone types a job title. This is not Member vs HOD."""

    def __init__(self, bot, profile, department):
        super().__init__()
        self.bot = bot
        self.profile = dict(profile or {})
        self.department = department
        self.designation = discord.ui.TextInput(
            label="Designation",
            placeholder="e.g. Software Engineer",
            max_length=DESIGNATION_MAX,
            required=True,
            default=_clip(self.profile.get("designation"), DESIGNATION_MAX) or None,
        )
        self.add_item(self.designation)

    async def on_submit(self, interaction: discord.Interaction):
        profile = dict(self.profile)
        profile["designation"] = str(self.designation).strip()
        _save_draft(self.bot, interaction.user.id, profile)
        if not profile["designation"]:
            await interaction.response.send_message(
                "Designation is required. Pick your department again and type it.",
                view=DepartmentSelectView(self.bot, profile),
                ephemeral=True,
            )
            return
        _save_draft(self.bot, interaction.user.id, {**profile, "department": self.department})
        await interaction.response.send_message(
            "Last step — add a profile photo (JPG, PNG, or WebP), or skip.",
            view=PhotoStepView(self.bot, profile, self.department),
            ephemeral=True,
        )


class PhotoStepView(discord.ui.View):
    def __init__(self, bot, profile, department):
        super().__init__(timeout=600)
        self.bot = bot
        self.profile = dict(profile or {})
        self.department = department

    @discord.ui.button(
        label="Add photo",
        style=discord.ButtonStyle.primary,
        custom_id=ONBOARDING_PHOTO_ADD_ID,
    )
    async def add_photo(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        await interaction.response.send_modal(
            PhotoModal(self.bot, self.profile, self.department)
        )

    @discord.ui.button(
        label="Skip photo",
        style=discord.ButtonStyle.secondary,
        custom_id=ONBOARDING_PHOTO_SKIP_ID,
    )
    async def skip_photo(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await _finalize_onboarding(interaction, self.bot, self.profile, department=self.department)


class PhotoModal(discord.ui.Modal, title="Profile photo"):
    def __init__(self, bot, profile, department):
        super().__init__()
        self.bot = bot
        self.profile = dict(profile or {})
        self.department = department
        upload = discord.ui.FileUpload(
            custom_id="onboarding:photo:file",
            required=True,
            min_values=1,
            max_values=1,
        )
        self.photo = upload
        self.add_item(discord.ui.Label(
            text="Photo",
            description="JPG, PNG, or WebP. Max 8 MB.",
            component=upload,
        ))

    async def _photo_retry(self, interaction, content):
        await _onboard_reply(
            interaction,
            content=content,
            view=PhotoStepView(self.bot, self.profile, self.department),
        )

    async def on_submit(self, interaction: discord.Interaction):
        # Defer immediately — downloading/saving the file often exceeds Discord's 3s limit.
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        items = list(getattr(self.photo, "values", None) or [])
        if not items:
            await self._photo_retry(interaction, "Please attach one photo, or tap **Skip photo**.")
            return
        item = items[0]
        filename = str(getattr(item, "filename", None) or "photo.jpg")
        size = int(getattr(item, "size", 0) or 0)
        if size > MAX_BYTES:
            await self._photo_retry(interaction, "Photo must be 8 MB or smaller. Try again or skip.")
            return
        try:
            data = await item.read()
        except Exception:
            await self._photo_retry(
                interaction,
                "Could not read that photo. Use JPG/PNG/WebP, or tap **Skip photo**.",
            )
            return
        root = (getattr(self.bot, "config", None) or {}).get("rootDir")
        try:
            stored = store_employee_photo(
                root, interaction.user.id, filename=filename, data=data
            )
        except Exception as error:
            await self._photo_retry(
                interaction,
                f"{error} Try a JPG/PNG/WebP under 8 MB, or tap **Skip photo**.",
            )
            return
        profile = dict(self.profile)
        profile["photo_path"] = stored
        _save_draft(self.bot, interaction.user.id, profile)
        await _finalize_onboarding(interaction, self.bot, profile, department=self.department)


def workplace_role_name(department):
    if str(department or "").strip() == "HR":
        return "HR"
    return f"{department} Member"


def designation_role_name(department, designation):
    title = str(designation or "").strip()
    dept = str(department or "").strip() or "Staff"
    name = f"{dept} · {title}" if title else dept
    return name[:100]


async def _ensure_role(guild, role_name, *, logger=None):
    if guild is None or not role_name:
        return None
    role = discord.utils.find(lambda r: r.name == role_name, guild.roles)
    if role is not None:
        return role
    try:
        return await guild.create_role(name=role_name, reason="Onboarding designation")
    except discord.HTTPException as error:
        if logger:
            logger.error("Could not create Discord role", {
                "role": role_name,
                "message": str(error)[:200],
            })
        return None


async def _onboard_reply(interaction, *, content, view=None):
    if interaction.response.is_done():
        await interaction.followup.send(content=content, view=view, ephemeral=True)
        return
    await interaction.response.send_message(content=content, view=view, ephemeral=True)


async def _finalize_onboarding(interaction, bot, profile, *, department):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    member = interaction.user
    designation = str((profile or {}).get("designation") or "").strip()
    level = "HR" if department == "HR" else "Member"
    role_name = workplace_role_name(department)
    title_role_name = designation_role_name(department, designation) if designation else ""
    role = discord.utils.find(lambda r: r.name == role_name, guild.roles) if guild else None
    if role is None:
        bot.logger.error("Onboarding role missing on server", {
            "discordUserId": str(member.id),
            "roleName": role_name,
        })
        _save_draft(bot, member.id, profile)
        await _onboard_reply(
            interaction,
            content=(
                f"Setup is incomplete: the **{role_name}** role does not exist on this server yet. "
                "Your details are saved — tell HR, then use **Edit details** or **Retry department**."
            ),
            view=_resume_after_finalize_error_view(bot, profile),
        )
        return
    title_role = None
    if title_role_name and title_role_name != role_name:
        title_role = await _ensure_role(guild, title_role_name, logger=getattr(bot, "logger", None))
    to_add = [role]
    if title_role is not None and getattr(title_role, "name", "") != getattr(role, "name", ""):
        to_add.append(title_role)
    try:
        await member.add_roles(*to_add, reason="Onboarding form submitted")
    except discord.HTTPException as error:
        bot.logger.error("Could not assign onboarding role", {"message": str(error), "role": role_name})
        _save_draft(bot, member.id, profile)
        await _onboard_reply(
            interaction,
            content=(
                "Could not assign your Discord role. Your details are saved — "
                "tell HR, then use **Edit details** or **Retry department**."
            ),
            view=_resume_after_finalize_error_view(bot, profile),
        )
        return
    role_names = [r.name for r in getattr(member, "roles", []) or []]
    for extra in (role_name, title_role_name):
        if extra and extra not in role_names:
            role_names.append(extra)
    try:
        await asyncio.to_thread(
            upsert_staff_employee,
            bot.hr.client,
            discord_id=str(member.id),
            name=profile["full_name"],
            username=getattr(member, "name", "") or "",
            joined_at=(getattr(member, "joined_at", None) or datetime.utcnow()).date().isoformat(),
            kind=department,
            hod=False,
            hr_role="HR" if level == "HR" else "",
            role_names=role_names,
            cnic=profile["cnic"],
            dob=profile["dob"],
            contact_number=profile["contact_number"],
            address=profile["address"],
            email=profile["email"],
            designation=designation,
            photo_path=str((profile or {}).get("photo_path") or ""),
            grant_leave=not leave_disabled_for_department_level(department, level),
            logger=bot.logger,
        )
    except Exception as error:
        bot.logger.error("Onboarding employee record failed", {"message": str(error)[:300]})
        _save_draft(bot, member.id, profile)
        await _onboard_reply(
            interaction,
            content=(
                "Your role was assigned but your profile could not be saved. "
                "Your details are kept — tell HR, or tap **Edit details** / **Retry department**."
            ),
            view=_resume_after_finalize_error_view(bot, profile),
        )
        return
    _clear_draft(bot, member.id)
    if level != "HR":
        await hide_onboarding_for_member(bot, member)
    title_bit = f" — **{designation}**" if designation else ""
    await _onboard_reply(
        interaction,
        content=f"Welcome, {profile['full_name']}! You're onboarded as **{role_name}**{title_bit}.",
        view=None,
    )
    await post_onboard_welcome(
        bot,
        guild,
        profile=profile,
        discord_user_id=str(member.id),
        role_name=role_name,
    )

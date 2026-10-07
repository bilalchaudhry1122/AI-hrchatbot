"""Optional files on leave and decline reasons."""

import discord

from app.discord.attachments import (
    format_reason_with_files,
    parse_reason_and_files,
    reason_file_upload,
)
from app.discord.leave_review import RejectReasonModal
from app.discord.leave_ui import LeaveDetailsModal
from app.hr.leave_status import HR


def test_public_reason_hides_discord_urls():
    from app.discord.attachments import public_reason_text

    stored = format_reason_with_files(
        "Medical appointment",
        [{"filename": "note.png", "url": "https://cdn.discordapp.com/note.png"}],
    )
    shown = public_reason_text(stored)
    assert "Medical appointment" in shown
    assert "note.png" in shown
    assert "cdn.discordapp.com" not in shown
    stored = format_reason_with_files(
        "Medical appointment",
        [{"filename": "note.png", "url": "https://cdn.discordapp.com/note.png"}],
    )
    body, files = parse_reason_and_files(stored)
    assert body == "Medical appointment"
    assert files[0]["filename"] == "note.png"
    assert files[0]["url"].startswith("https://")


def test_decline_modal_has_optional_file_upload():
    modal = RejectReasonModal(object(), tier=HR, is_line_manager=False)
    labels = [item for item in modal.children if isinstance(item, discord.ui.Label)]
    assert labels, "decline reason must offer attachments"
    assert modal.reason_files.required is False
    assert modal.reason_files.max_values == 5


def test_leave_form_reason_has_optional_file_upload():
    modal = LeaveDetailsModal(object(), {})
    labels = [item for item in modal.children if isinstance(item, discord.ui.Label)]
    assert labels, "leave reason must offer attachments"
    assert modal.reason_files.required is False


def test_leave_form_keeps_files_on_card_preview():
    from app.discord.leave_ui import leave_template_embed

    embed = leave_template_embed(
        {
            "stage": "confirm",
            "leave_type": "Casual Leave",
            "reason": "Doctor visit",
            "attachments": [{"filename": "note.png", "url": "https://cdn.discordapp.com/note.png"}],
        }
    )
    names = [field.name for field in embed.fields]
    assert "Attachments" in names
    assert embed.image.url == "https://cdn.discordapp.com/note.png"


def test_reason_file_upload_is_optional():
    label, upload = reason_file_upload(custom_id="leave:reason:files")
    assert isinstance(label, discord.ui.Label)
    assert upload.required is False
    assert upload.min_values == 0

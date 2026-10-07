"""Optional files on leave and decline reasons (images, PDFs, etc.)."""

import discord

ATTACH_HEADER = "Attachments:"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def meta_from_upload(upload):
    files = []
    for item in getattr(upload, "values", None) or []:
        url = str(getattr(item, "url", None) or getattr(item, "proxy_url", "") or "").strip()
        name = str(getattr(item, "filename", None) or "file").strip() or "file"
        if url:
            files.append({"filename": name, "url": url})
    return files


def public_reason_text(reason, *, empty="—"):
    """Plain reason for HOD/HR: names of files, never raw Discord URLs."""
    body, files = parse_reason_and_files(reason)
    names = [str((item or {}).get("filename") or "file").strip() or "file" for item in files or []]
    names = [name for name in names if name]
    if names:
        label = "Attached file" if len(names) == 1 else "Attached files"
        extra = f"{label}: {', '.join(names)}"
        return f"{body}\n{extra}".strip() if body else extra
    return body.strip() if body else empty


def parse_reason_and_files(reason):
    text = str(reason or "")
    if ATTACH_HEADER not in text:
        return text.strip(), []
    body, rest = text.split(ATTACH_HEADER, 1)
    files = []
    for line in rest.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if ": http" in line:
            name, url = line.split(": ", 1)
            files.append({"filename": name.strip() or "file", "url": url.strip()})
        elif line.startswith("http"):
            files.append({"filename": "file", "url": line})
    return body.strip(), files


def format_reason_with_files(reason, files):
    body, existing = parse_reason_and_files(reason)
    items = list(files or existing)
    if not items:
        return body
    lines = [body] if body else []
    lines.append(ATTACH_HEADER)
    for item in items:
        name = str((item or {}).get("filename") or "file")
        url = str((item or {}).get("url") or "").strip()
        if url:
            lines.append(f"{name}: {url}")
    return "\n".join(lines)


def attachment_links(files):
    lines = []
    for item in files or []:
        name = str((item or {}).get("filename") or "file")
        url = str((item or {}).get("url") or "").strip()
        if url:
            lines.append(f"[{name}]({url})")
    return "\n".join(lines)[:1000]


def add_attachment_preview(embed, files):
    files = files or []
    if not files:
        return embed
    links = attachment_links(files)
    if links:
        embed.add_field(name="Attachments", value=links, inline=False)
    first = files[0]
    name = str(first.get("filename") or "").lower()
    url = str(first.get("url") or "")
    if url and name.endswith(IMAGE_SUFFIXES):
        embed.set_image(url=url)
    return embed


def reason_file_upload(*, custom_id):
    upload = discord.ui.FileUpload(
        custom_id=custom_id,
        required=False,
        min_values=0,
        max_values=5,
    )
    return discord.ui.Label(
        text="Attachments",
        description="Optional. Images, PDFs, or other files for this reason.",
        component=upload,
    ), upload


async def files_from_upload(upload):
    out = []
    for item in getattr(upload, "values", None) or []:
        to_file = getattr(item, "to_file", None)
        if not callable(to_file):
            continue
        try:
            out.append(await to_file())
        except Exception:
            pass
    return out

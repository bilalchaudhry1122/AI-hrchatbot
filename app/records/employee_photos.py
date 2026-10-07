"""Save onboarding photos on disk; MySQL only stores the relative path.

Discord CDN URLs expire. BLOBs in MySQL bloat backups. Files + path is the
durable approach for this bot.
"""

from pathlib import Path

PHOTO_SUBDIR = Path("data") / "employee-photos"
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_BYTES = 8 * 1024 * 1024


def photo_root(root_dir):
    path = Path(root_dir) / PHOTO_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_photo_ext(filename):
    ext = Path(str(filename or "")).suffix.lower()
    if ext == ".jpeg":
        return ".jpg"
    return ext if ext in ALLOWED_EXT else ""


def resolve_photo_path(root_dir, stored):
    text = str(stored or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = Path(root_dir) / path
    return path if path.is_file() else None


def store_employee_photo(root_dir, discord_id, *, filename, data):
    """Write bytes to data/employee-photos/{id}.ext. Returns relative path."""
    user_id = str(discord_id or "").strip()
    blob = bytes(data or b"")
    if not user_id:
        raise ValueError("Discord user id is required to save a photo.")
    if not blob:
        raise ValueError("Photo file is empty.")
    if len(blob) > MAX_BYTES:
        raise ValueError("Photo must be 8 MB or smaller.")
    ext = normalize_photo_ext(filename)
    if not ext:
        raise ValueError("Photo must be a JPG, PNG, or WebP image.")
    folder = photo_root(root_dir)
    dest = folder / f"{user_id}{ext}"
    for old in folder.glob(f"{user_id}.*"):
        if old != dest:
            try:
                old.unlink()
            except OSError:
                pass
    dest.write_bytes(blob)
    return str(PHOTO_SUBDIR.as_posix() + f"/{user_id}{ext}")

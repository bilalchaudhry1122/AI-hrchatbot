"""Split a ticket message that asks several things at once."""

import re

from app.agent.verification import looks_like_leave_form_reply

_BLANK = re.compile(r"(?:\r?\n\s*){2,}")


def split_user_questions(text):
    """Break a pasted list of questions into separate asks.

    One leave-form reply (a date, a type, yes/no) stays whole.
    """
    raw = str(text or "").strip()
    if not raw:
        return []
    if looks_like_leave_form_reply(raw) and raw.count("?") <= 1 and len(raw) < 240:
        return [raw]
    blocks = [part.strip() for part in _BLANK.split(raw) if part.strip()]
    if len(blocks) >= 2:
        return blocks
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) >= 3 and sum(1 for line in lines if "?" in line) >= 2:
        return lines
    return [raw]

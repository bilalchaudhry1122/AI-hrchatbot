"""Keep console output safe on Windows.

A default Windows console uses cp1252, which cannot encode an arrow, a bullet,
or any Urdu character. Printing one raises UnicodeEncodeError and, at startup,
takes the whole process down. Since this bot logs questions and answers in
Urdu and Roman Urdu, stdout is switched to UTF-8 with replacement so a stray
character can never kill the run.
"""

import sys


def ensure_utf8_console():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Already detached or redirected somewhere that cannot change.
            pass

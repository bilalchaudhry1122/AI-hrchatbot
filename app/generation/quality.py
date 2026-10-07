"""Reject model answers that looped or collapsed into noise."""

import re


def is_degenerate_answer(text):
    raw = str(text or "").strip()
    if not raw:
        return True
    compact = re.sub(r"\s+", "", raw)
    if len(compact) >= 40 and len(set(compact.lower())) <= 4:
        return True
    if re.search(r"(.)\1{19,}", compact):
        return True
    words = re.findall(r"\w+", raw.lower())
    if len(words) >= 20:
        top = max(words.count(word) for word in set(words))
        if top / len(words) >= 0.6:
            return True
    return False

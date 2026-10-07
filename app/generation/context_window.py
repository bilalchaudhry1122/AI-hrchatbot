"""Keep the model desk small: recent chat + draft notes, not the whole ticket."""


INTENT_TURNS = 12
LLM_TURNS = 10
INTENT_MSG_CHARS = 800
LLM_MSG_CHARS = 700
LLM_HISTORY_CHARS = 5000


def _clip(item, max_chars):
    content = str((item or {}).get("content") or "")[:max_chars]
    return {"role": (item or {}).get("role") or "user", "content": content}


def trim_history(history, *, max_turns, max_chars_each):
    items = [item for item in (history or []) if (item or {}).get("content")]
    clipped = [_clip(item, max_chars_each) for item in items[-max_turns:]]
    return [item for item in clipped if item["content"].strip()]


def history_for_intent(history):
    return trim_history(history, max_turns=INTENT_TURNS, max_chars_each=INTENT_MSG_CHARS)


def history_for_llm(history):
    items = trim_history(history, max_turns=LLM_TURNS, max_chars_each=LLM_MSG_CHARS)
    total = 0
    kept = []
    for item in reversed(items):
        size = len(item["content"])
        if kept and total + size > LLM_HISTORY_CHARS:
            continue
        kept.append(item)
        total += size
    kept.reverse()
    return kept


def ticket_notes(draft):
    draft = draft or {}
    parts = []
    if draft.get("awaiting_details"):
        parts.append("Collecting a leave request (type, days, or dates).")
    if draft.get("awaiting_confirm"):
        parts.append("Waiting for the member to confirm the leave request.")
    leave_type = draft.get("leave_type")
    if leave_type:
        parts.append(f"Draft leave type: {leave_type}.")
    start = draft.get("start_date")
    end = draft.get("end_date")
    if start and end:
        parts.append(f"Draft dates: {start} to {end}.")
    elif start:
        parts.append(f"Draft start date: {start}.")
    return " ".join(parts)

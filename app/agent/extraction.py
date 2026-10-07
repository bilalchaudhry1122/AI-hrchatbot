import json
import re
from datetime import timedelta

from app.agent.schemas import LEAVE_EXTRACT_INSTRUCTION
from app.hr.dates import DATE_TOKEN, RANGE_WORD, parse_day_count, resolve_date_phrase, resolve_date_range
from app.errors import AppError, ErrorCodes
from app.routing.roman_urdu import normalize_leave_text


def parse_json_object(text):
    raw = str(text or "").strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def infer_leave_type(text):
    raw = normalize_leave_text(text).lower()
    mapping = {
        "annual": "Annual Leave",
        "anual": "Annual Leave",
        "salana": "Annual Leave",
        "saalana": "Annual Leave",
        "sick": "Sick Leave",
        "bimar": "Sick Leave",
        "bimari": "Sick Leave",
        "casual": "Casual Leave",
    }
    rec = re.search(r"\b(rec[a-zA-Z0-9]{10,})\b", raw)
    if rec:
        return rec.group(1)
    for key, name in mapping.items():
        if key in raw:
            return name
    return None


_REASON_MARKERS = (
    r"because\s+(.+)$",
    r"due to\s+(.+)$",
    r"coz\s+(.+)$",
    r"as i(?:'m| am)\s+(.+)$",
    r"since i(?:'m| am)\s+(.+)$",
    r"reason(?:\s+for leave)?(?:\s+is|:)\s*(.+)$",
    r"kyun(?:ke|ki|k)\s+(.+)$",
    r"waja(?:h)?(?:\s+se)?\s+(.+)$",
    r"is liye\s+(.+)$",
    r"for (?:a |an |my |the )?(?!one day|two days|\d+\s*days?|leave\b|sick\b|annual\b|casual\b)(.+)$",
)
_ILLNESS_REASON = re.compile(
    r"(?i)\b(?:as |because |since )?(i(?:'m| am) (?:ill|sick|unwell|not well))\b"
)
_APPLY_TAIL = re.compile(r"(?i)\s+and i (?:want|need|wanna)\b")
_APPLY_NOISE = re.compile(
    r"(?i)\b("
    r"please |kindly |i (?:want to |wanna |need to |would like to )?(?:apply(?: for)?|request|take|book)|"
    r"i want|i need|apply karo|apply karna|mujhe|mujhy|chahiye|chahye|"
    r"leave request|open the form|fill (?:the )?form|next monday|next week"
    r")\b"
)
_TYPE_NOISE = re.compile(
    r"(?i)\b("
    r"annual leave|sick leave|casual leave|"
    r"annual|sick|casual|salana|saalana|bimar|bimari|"
    r"half day|first half|second half|leave|chutti|chuttian"
    r")\b"
)
_DATE_NOISE = re.compile(
    rf"(?i)\b({DATE_TOKEN}|{RANGE_WORD}|from|and|on|for one day|for \d+\s*days?|"
    r"\d+\s*days?|one day|two days|do din|ek din|din ki|din ka)\b"
)


def _leave_prompt_focus(text):
    raw = str(text or "").strip()
    raw = re.split(r"(?i)\s+also[,:]?\s+", raw, maxsplit=1)[0]
    raw = re.split(r"\s+[—–]\s+", raw, maxsplit=1)[0]
    parts = re.split(r"(?<=[.!?])\s+", raw)
    kept = [part for part in parts if not re.search(r"(?i)\b(open the form|fill (?:the )?form)\b", part)]
    return " ".join(kept or parts).strip(" .,-")


def _clean_reason(text):
    value = str(text or "").strip(" .,-")
    value = re.sub(r"(?i)\b(open the form|fill (?:the )?form)\b", "", value).strip(" .,-")
    value = re.sub(r"(?i)^(one|a|an|the)\s+", "", value).strip(" .,-")
    if len(value) < 2:
        return ""
    lowered = value.lower()
    if re.fullmatch(
        r"(i want( to apply)?( for)?( the)? leave|apply( for)?( leave)?|chutti( chahiye)?|leave)",
        lowered,
    ):
        return ""
    return value[:400]


def infer_leave_reason(text):
    """Pull a leave reason out of the same message that has type/dates."""
    raw = _leave_prompt_focus(text)
    raw = _APPLY_TAIL.split(raw, maxsplit=1)[0].strip()
    if not raw:
        return ""
    illness = _ILLNESS_REASON.search(raw)
    if illness:
        cleaned = _clean_reason(illness.group(1))
        if cleaned:
            return cleaned
    waja = re.search(r"(?i)(.+)\s+ki\s+waja(?:h)?(?:\s+se)?$", raw)
    if waja:
        tail = " ".join(waja.group(1).split()[-5:])
        cleaned = _clean_reason(tail)
        if cleaned:
            return cleaned
    for pattern in _REASON_MARKERS:
        match = re.search(pattern, raw, re.I | re.S)
        if match:
            cleaned = _clean_reason(match.group(1))
            if cleaned:
                if re.fullmatch(r"(?i)(ill|sick|unwell|not well)", cleaned):
                    return f"I am {cleaned.lower()}"
                return cleaned
    leftover = _DATE_NOISE.sub(" ", raw)
    leftover = _TYPE_NOISE.sub(" ", leftover)
    leftover = _APPLY_NOISE.sub(" ", leftover)
    leftover = re.sub(r"\s+", " ", leftover).strip(" .,-")
    leftover = re.sub(r"(?i)^(one|a|an|the)\s+", "", leftover).strip(" .,-")
    words = leftover.split()
    if len(words) < 2:
        return ""
    return _clean_reason(leftover)


def extract_leave_fields(question, *, llm=None, conversation_history=None, today=None):
    current = str(question or "")
    range_start, range_end = resolve_date_range(current, today=today)
    explicit_range = bool(range_start and range_end)
    start = range_start or resolve_date_phrase(current, today=today)
    end = range_end
    days = parse_day_count(current)
    if re.search(r"monday and tuesday", current, re.I):
        start = resolve_date_phrase("monday", today=today) or start
        if start:
            end = start + timedelta(days=1)
            explicit_range = True
    leave_type = infer_leave_type(current)
    reason = infer_leave_reason(current)
    if llm and (not leave_type or not start or not reason):
        try:
            blob = llm.generate_answer(
                question=f"Today is {(today.isoformat() if today else '')}. {question}",
                context_blocks=[],
                mode="json",
                identity={"instruction": LEAVE_EXTRACT_INSTRUCTION, "conversationHistory": conversation_history or []},
            )
            data = parse_json_object(blob)
            leave_type = leave_type or data.get("leave_type")
            reason = reason or str(data.get("reason") or "").strip()
            if data.get("start_date"):
                start = resolve_date_phrase(str(data.get("start_date")), today=today) or start
            if data.get("end_date"):
                parsed_end = resolve_date_phrase(str(data.get("end_date")), today=today)
                if parsed_end:
                    end = parsed_end
                    explicit_range = True
            if data.get("days_requested") and days is None:
                try:
                    days = int(data.get("days_requested"))
                except (TypeError, ValueError):
                    pass
        except AppError:
            pass
        except Exception:
            pass

    if start and days and not explicit_range:
        end = start + timedelta(days=max(days, 1) - 1)
    if explicit_range and start and end:
        days = (end - start).days + 1
    if start and not days and not explicit_range:
        days = 1
        end = end or start
    if start and not end:
        end = start
    if start and end and end < start:
        raise AppError(ErrorCodes.INVALID_DATES, "The end date cannot be before the start date.", expose=True)

    computed_days = (end - start).days + 1 if start and end else days
    span_complete = bool(start and end)
    complete = bool(leave_type and start and end and span_complete)
    return {
        "leave_type": leave_type,
        "start_date": start,
        "end_date": end,
        "days_requested": computed_days,
        "reason": reason,
        "explicit_range": explicit_range,
        "days_count": days,
        "span_complete": span_complete,
        "complete": complete,
    }

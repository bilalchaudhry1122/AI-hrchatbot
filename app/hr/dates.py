from calendar import monthrange
from datetime import date, timedelta
import re


MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def inclusive_days(start, end):
    return (end - start).days + 1


def format_display_date(value):
    raw = str(value or "").strip()[:10]
    if not raw:
        return ""
    try:
        return date.fromisoformat(raw).strftime("%d %b %Y")
    except ValueError:
        return str(value or "").strip()


def each_date(start, end):
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _this_or_next(today, weekday, prefer_next):
    delta = (weekday - today.weekday()) % 7
    if prefer_next:
        if delta == 0:
            delta = 7
        return today + timedelta(days=delta)
    return today + timedelta(days=delta)


DATE_TOKEN = (
    r"today|tomorrow|yesterday|aaj|kal|parson|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"20\d{2}-\d{2}-\d{2}|"
    rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTH_ALT})(?:\s+\d{{4}})?|"
    rf"(?:{MONTH_ALT})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:\s+\d{{4}})?|"
    r"\d{1,2}[/\-.]\d{1,2}(?:[/\-.]\d{2,4})?"
)
RANGE_WORD = r"to|till|until|through|upto|up to|se|say|sey|sae|tak"
RANGE_SPLIT = re.compile(
    rf"(?:from\s+)?(?P<left>(?:{DATE_TOKEN}))\s+(?:{RANGE_WORD})\s+(?P<right>(?:{DATE_TOKEN}))",
    re.I,
)
SAME_MONTH_RANGE = re.compile(
    rf"\b(?:from\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:{RANGE_WORD}|-|–|—)\s*"
    rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_ALT})(?:[,\s]+(\d{{4}}))?\b",
    re.I,
)
MONTH_FIRST_RANGE = re.compile(
    rf"\b({MONTH_ALT})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:{RANGE_WORD}|-|–|—)\s*"
    rf"(\d{{1,2}})(?:st|nd|rd|th)?(?:[,\s]+(\d{{4}}))?\b",
    re.I,
)
DAY_MONTH_TO_DAY = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_ALT})\s+(?:{RANGE_WORD}|-|–|—)\s+"
    rf"(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+(?:tak|to|till))?(?:\s+({MONTH_ALT}))?(?:[,\s]+(\d{{4}}))?\b",
    re.I,
)
DAY_COUNT = re.compile(
    r"\b(\d+)\s*(?:days?|din)\b|"
    r"\b(one|ek)\s+(?:day|din)\b|"
    r"\b(two|do)\s+(?:days?|din)\b|"
    r"\b(three|teen)\s+(?:days?|din)\b",
    re.I,
)


def parse_day_count(text):
    raw = str(text or "").strip()
    match = DAY_COUNT.search(raw)
    if not match:
        return None
    if match.group(1):
        return int(match.group(1))
    token = (match.group(2) or match.group(3) or match.group(4) or "").lower()
    if token in {"one", "ek"}:
        return 1
    if token in {"two", "do"}:
        return 2
    if token in {"three", "teen"}:
        return 3
    return None


def resolve_date_range(text, *, today=None, prefer_future=True):
    today = today or date.today()
    raw = str(text or "").strip()
    if re.search(r"\b\d{1,2}\s*(?:to|till|until|se|-)\s*\d{1,2}\s*(?:days?|din)\b", raw, re.I):
        return None, None

    same = SAME_MONTH_RANGE.search(raw)
    if same:
        start = _build_date(int(same.group(1)), MONTHS[same.group(3).lower()], same.group(4), today, prefer_future)
        end = _build_date(int(same.group(2)), MONTHS[same.group(3).lower()], same.group(4), today, prefer_future)
        if start and end and end < start:
            end = _shift_month(end, 1)
        if start and end:
            return start, end

    month_first = MONTH_FIRST_RANGE.search(raw)
    if month_first:
        start = _build_date(int(month_first.group(2)), MONTHS[month_first.group(1).lower()], month_first.group(4), today, prefer_future)
        end = _build_date(int(month_first.group(3)), MONTHS[month_first.group(1).lower()], month_first.group(4), today, prefer_future)
        if start and end and end < start:
            end = _shift_month(end, 1)
        if start and end:
            return start, end

    day_month = DAY_MONTH_TO_DAY.search(raw)
    if day_month:
        month_end = day_month.group(4) or day_month.group(2)
        start = _build_date(int(day_month.group(1)), MONTHS[day_month.group(2).lower()], day_month.group(5), today, prefer_future)
        end = _build_date(int(day_month.group(3)), MONTHS[month_end.lower()], day_month.group(5), today, prefer_future)
        if start and end and end < start:
            end = _shift_month(end, 1)
        if start and end:
            return start, end

    match = RANGE_SPLIT.search(raw)
    if not match:
        return None, None
    left = match.group("left")
    right = match.group("right")
    start = resolve_date_phrase(left, today=today, prefer_future=prefer_future)
    end = resolve_date_phrase(right, today=today, prefer_future=prefer_future)
    if start and end and end < start:
        end = end + timedelta(days=7)
    if start and end:
        return start, end
    return None, None


def _shift_month(value, months):
    month = value.month + months
    year = value.year
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def resolve_date_phrase(text, *, today=None, prefer_future=True):
    """Turn a date phrase into a date.

    prefer_future=True (leave requests) reads a bare day/month that has already
    passed as next year. prefer_future=False (attendance and other lookups)
    keeps it in the past, where the record actually is.
    """
    today = today or date.today()
    raw = str(text or "").strip().lower()
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", raw)
    if iso:
        return date.fromisoformat(iso.group(1))
    if re.search(r"\b(today|aaj)\b", raw):
        return today
    if re.search(r"\b(tomorrow|kal)\b", raw):
        return today + timedelta(days=1)
    if re.search(r"\b(parson|day after tomorrow)\b", raw):
        return today + timedelta(days=2)
    if re.search(r"\byesterday\b", raw):
        return today - timedelta(days=1)
    next_week = bool(re.search(r"\bnext week\b", raw))
    if next_week and not re.search(r"monday|tuesday|wednesday|thursday|friday|saturday|sunday", raw):
        days_ahead = (7 - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return today + timedelta(days=days_ahead)
    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", raw):
            prefer_next = bool(re.search(r"\bnext\b", raw))
            return _this_or_next(today, weekday, prefer_next)
    return parse_calendar_date(raw, today=today, prefer_future=prefer_future)


def parse_calendar_date(text, *, today=None, prefer_future=True):
    today = today or date.today()
    raw = str(text or "").strip().lower()
    named = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_ALT})(?:[,\s]+(\d{{4}}))?\b",
        raw,
    )
    if named:
        return _build_date(int(named.group(1)), MONTHS[named.group(2)], named.group(3), today, prefer_future)
    named_rev = re.search(
        rf"\b({MONTH_ALT})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:[,\s]+(\d{{4}}))?\b",
        raw,
    )
    if named_rev:
        return _build_date(int(named_rev.group(2)), MONTHS[named_rev.group(1)], named_rev.group(3), today, prefer_future)
    numeric = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?\b", raw)
    if numeric:
        first, second = int(numeric.group(1)), int(numeric.group(2))
        year_raw = numeric.group(3)
        day, month = first, second
        if month > 12 and day <= 12:
            day, month = second, first
        if month > 12 or day > 31:
            return None
        year = None
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        return _build_date(day, month, year, today, prefer_future)
    return None


def _build_date(day, month, year, today, prefer_future=True):
    try:
        year = int(year) if year not in (None, "") else today.year
        parsed = date(year, int(month), int(day))
    except ValueError:
        return None
    if prefer_future and year == today.year and parsed < today:
        try:
            parsed = date(today.year + 1, int(month), int(day))
        except ValueError:
            return parsed
    return parsed


def month_range(today=None, *, offset=0):
    today = today or date.today()
    month = today.month + offset
    year = today.year
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return start, end


def last_week_range(today=None):
    today = today or date.today()
    start = today - timedelta(days=today.weekday() + 7)
    end = start + timedelta(days=6)
    return start, end


def this_week_range(today=None):
    today = today or date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


def resolve_attendance_range(text, *, today=None):
    today = today or date.today()
    raw = str(text or "").lower()
    if re.search(r"\byesterday\b", raw):
        day = today - timedelta(days=1)
        return day, day
    if re.search(r"\b(today|aaj)\b", raw):
        return today, today
    if re.search(r"\bkal\b", raw):
        # "kal" is both yesterday and tomorrow in Urdu. Attendance only exists
        # for days that have already happened, so here it means yesterday.
        day = today - timedelta(days=1)
        return day, day
    if re.search(r"\btomorrow\b", raw):
        day = today + timedelta(days=1)
        return day, day
    if re.search(r"\bparson\b", raw):
        day = today - timedelta(days=2)
        return day, day
    # "was I present on 3 Sep" — an explicit date means the one that has passed.
    explicit_start, explicit_end = resolve_date_range(raw, today=today, prefer_future=False)
    if explicit_start and explicit_end:
        return explicit_start, explicit_end
    explicit_day = resolve_date_phrase(raw, today=today, prefer_future=False)
    if explicit_day and explicit_day <= today:
        return explicit_day, explicit_day
    if re.search(r"last month", raw):
        return month_range(today, offset=-1)
    if re.search(r"last week", raw):
        return last_week_range(today)
    if re.search(r"this week", raw):
        return this_week_range(today)
    return month_range(today)

"""Which days actually cost leave.

Saturday and Sunday are off, and so is anything in the company holiday list,
so a Friday-to-Monday booking costs two days, not four. Half days cost 0.5 and
only make sense on a single day.
"""

from datetime import date
import re

from app.hr.dates import each_date

SATURDAY = 5
SUNDAY = 6
WEEKEND = (SATURDAY, SUNDAY)

FIRST_HALF = "First half"
SECOND_HALF = "Second half"
HALF_DAY_OPTIONS = (FIRST_HALF, SECOND_HALF)


def _as_day(value):
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def normalize_half_day(value):
    """Accept a half-day label in any casing, or nothing at all."""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw in {"first", "first half", "morning", "am", "1"}:
        return FIRST_HALF
    if raw in {"second", "second half", "afternoon", "pm", "2"}:
        return SECOND_HALF
    return ""


def is_weekend(day, weekend=WEEKEND):
    return day.weekday() in tuple(weekend)


def holiday_dates(holidays):
    """Accept dates, ISO strings, or holiday dicts and return a set of dates."""
    days = set()
    for item in holidays or []:
        raw = item.get("date") if isinstance(item, dict) else item
        parsed = _as_day(raw)
        if parsed:
            days.add(parsed)
    return days


def is_working_day(day, *, holidays=None, weekend=WEEKEND):
    if is_weekend(day, weekend):
        return False
    return day not in holiday_dates(holidays)


def working_days(start, end, *, holidays=None, weekend=WEEKEND):
    """The days between start and end inclusive that actually cost leave."""
    off = holiday_dates(holidays)
    weekend = tuple(weekend)
    return [
        day
        for day in each_date(start, end)
        if day.weekday() not in weekend and day not in off
    ]


def count_leave_days(start, end, *, half_day="", holidays=None, weekend=WEEKEND):
    """How much balance this range costs.

    A half day is only meaningful on a single working day; a range keeps whole
    days. Returns a float so 0.5 survives, and an int-valued float stays clean
    when displayed.
    """
    days = working_days(start, end, holidays=holidays, weekend=weekend)
    if not days:
        return 0.0
    if normalize_half_day(half_day) and len(days) == 1:
        return 0.5
    return float(len(days))


def describe_skipped(start, end, *, holidays=None, weekend=WEEKEND):
    """Weekend/holiday days inside the range, for explaining the day count."""
    off = holiday_dates(holidays)
    weekend = tuple(weekend)
    skipped = []
    for day in each_date(start, end):
        if day.weekday() in weekend:
            skipped.append({"date": day, "reason": "weekend"})
        elif day in off:
            skipped.append({"date": day, "reason": "holiday"})
    return skipped


def next_working_day(day, *, holidays=None, weekend=WEEKEND):
    from datetime import timedelta

    current = day
    for _ in range(30):
        if is_working_day(current, holidays=holidays, weekend=weekend):
            return current
        current = current + timedelta(days=1)
    return day


_NAMED_WEEKDAY = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_ASK_DAY_KIND = re.compile(
    r"\bis\s+(today|tomorrow|(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\s+"
    r"a\s+(company\s+)?(working\s+day|work\s+day|holiday)\b",
    re.I,
)


def weekend_day_answer(question, locale="english"):
    """Saturday/Sunday working-day questions, without a handbook lookup."""
    from app.routing.language import pick_locale_text

    match = _ASK_DAY_KIND.search(str(question or ""))
    if not match:
        return ""
    token = (match.group(2) or match.group(1) or "").lower()
    weekday = _NAMED_WEEKDAY.get(token)
    if weekday is None:
        return ""
    name = token.title()
    asking_holiday = "holiday" in (match.group(4) or "").lower()
    off = weekday in WEEKEND
    if off and asking_holiday:
        return pick_locale_text(
            locale,
            english=f"{name} is already a weekly off, not a working day.",
            roman=f"{name} weekly off hai, working day nahi.",
            urdu=f"{name} ہفتہ وار چھٹی ہے، ورکنگ ڈے نہیں۔",
            mix=f"{name} weekly off hai, working day nahi.",
        )
    if off:
        return pick_locale_text(
            locale,
            english=f"No. {name} is not a working day. Saturday and Sunday are off.",
            roman=f"Nahi. {name} working day nahi hai. Saturday aur Sunday off hain.",
            urdu=f"نہیں۔ {name} ورکنگ ڈے نہیں ہے۔ ہفتہ اور اتوار چھٹی ہیں۔",
            mix=f"Nahi. {name} working day nahi hai. Saturday and Sunday are off.",
        )
    return pick_locale_text(
        locale,
        english=f"Yes. {name} is a working day, unless it is a company holiday.",
        roman=f"Haan. {name} working day hai, jab tak company holiday na ho.",
        urdu=f"ہاں۔ {name} ورکنگ ڈے ہے، جب تک کمپنی کی چھٹی نہ ہو۔",
        mix=f"Haan. {name} working day hai, unless it is a company holiday.",
    )

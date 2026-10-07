"""Leave entitlement gates.

CS Member and Sales Member do not get leave quota, balance lookup, or apply.
"""

from app.hr.departments import normalize_department
from app.routing.language import pick_locale_text

# Exact Discord role names (case-insensitive).
LEAVE_DISABLED_ROLES = frozenset({"cs member", "sales member"})
LEAVE_DISABLED_DEPARTMENTS = frozenset({"CS", "Sales"})


def is_leave_disabled_role_name(name):
    return str(name or "").strip().lower() in LEAVE_DISABLED_ROLES


def leave_disabled_for_roles(role_names):
    return any(is_leave_disabled_role_name(name) for name in (role_names or []))


def leave_disabled_for_employee(employee=None, role_names=None):
    """True when this person must not use leave apply / balance."""
    if leave_disabled_for_roles(role_names):
        return True
    if not employee:
        return False
    # Also match stored Discord Roles text and department + Member title.
    roles_blob = str(employee.get("discordRoles") or "")
    if roles_blob:
        parts = [part.strip() for part in roles_blob.replace(",", "\n").splitlines() if part.strip()]
        if leave_disabled_for_roles(parts):
            return True
    dept = normalize_department(employee.get("department"))
    title = str(employee.get("hrRole") or "").strip().lower()
    if dept in LEAVE_DISABLED_DEPARTMENTS and title in {"", "member"}:
        return True
    return False


def leave_disabled_for_department_level(department, level):
    """Onboarding: CS/Sales Member (not HOD/HR) get no leave quota."""
    dept = normalize_department(department) or str(department or "").strip()
    lvl = str(level or "").strip().lower()
    return dept in LEAVE_DISABLED_DEPARTMENTS and lvl == "member"


def leave_disabled_message(locale=None):
    return pick_locale_text(
        locale,
        english=(
            "Leave apply and leave balance are not available for CS Member or Sales Member. "
            "Please contact HR if you need help."
        ),
        roman=(
            "CS Member aur Sales Member ke liye leave apply aur leave balance available nahi hai. "
            "Zarurat ho to HR se rabta karein."
        ),
        urdu=(
            "CS Member یا Sales Member کے لیے لیو اپلائی اور لیو بیلنس دستیاب نہیں۔ "
            "مدد کے لیے HR سے رابطہ کریں۔"
        ),
        mix=(
            "CS Member / Sales Member ke liye leave apply aur balance available nahi hai. "
            "Please contact HR."
        ),
    )

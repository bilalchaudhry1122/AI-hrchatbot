"""Who is allowed to act on leave.

Tiers: employee < manager (HOD) < hr < admin. HR or Admin approves leave;
the HOD is notified only. Roles come from Discord.
"""

from app.hr.departments import is_hod_member
from app.hr.leave_status import ADMIN, EMPLOYEE, HR, MANAGER


def _has_role(member, role_id):
    wanted = str(role_id or "").strip()
    if not wanted or "PASTE_" in wanted:
        return False
    roles = getattr(member, "roles", []) or []
    cache = getattr(roles, "cache", None)
    if cache is not None and hasattr(cache, "has"):
        return bool(cache.has(wanted))
    for role in roles:
        if str(getattr(role, "id", role)) == wanted:
            return True
    return False


def is_hr_member(member, hr_role_id):
    return _has_role(member, hr_role_id)


def is_hr_admin(member, admin_role_id):
    """Admin above HR. Falls back to the Discord Administrator permission."""
    if _has_role(member, admin_role_id):
        return True
    permissions = getattr(member, "guild_permissions", None)
    return bool(getattr(permissions, "administrator", False))


def is_manager_role(member, manager_role_id):
    return _has_role(member, manager_role_id)


def tier_for(member, config, *, is_line_manager=False):
    """Highest tier this member holds. Line managers count even without a role."""
    hr_cfg = (config or {}).get("hr") or {}
    if is_hr_admin(member, hr_cfg.get("adminRoleId")):
        return ADMIN
    if is_hr_member(member, hr_cfg.get("hrRoleId")):
        return HR
    if is_hod_member(member, config) or is_line_manager or is_manager_role(member, hr_cfg.get("managerRoleId")):
        return MANAGER
    return EMPLOYEE


def describe_tier(tier):
    return {
        ADMIN: "Admin",
        HR: "HR",
        MANAGER: "HOD",
        EMPLOYEE: "Employee",
    }.get(tier, "Employee")

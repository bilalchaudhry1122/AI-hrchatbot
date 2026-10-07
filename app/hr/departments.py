"""Company departments that have an HOD leave step.

Staff sit in BI, CS, or Marketing. Each has one HOD. Leave from a member
goes to that HOD first; HR only sees it after the HOD approves.
"""

DEPARTMENTS = ("BI", "CS", "Marketing")
DEPARTMENT_CHOICES = ("BI", "CS", "Marketing", "Sales", "HR", "Staff")
AIRTABLE_DEPARTMENTS = DEPARTMENT_CHOICES  # legacy alias

_ALIASES = {
    "bi": "BI",
    "business intelligence": "BI",
    "cs": "CS",
    "customer success": "CS",
    "customer-success": "CS",
    "marketing": "Marketing",
    "sales": "Sales",
    "hr": "HR",
    "human resource": "HR",
    "human resources": "HR",
}

CHANNEL_NAMES = {
    "BI": "bi-hod",
    "CS": "cs-hod",
    "Marketing": "marketing-hod",
}

DISPLAY_NAMES = {
    "BI": "BI HOD",
    "CS": "CS HOD",
    "Marketing": "Marketing HOD",
}


def normalize_department(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower().replace("_", " ").replace("-", " ")
    lowered = " ".join(lowered.split())
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    for alias, key in _ALIASES.items():
        if lowered == alias or lowered.startswith(alias + " ") or lowered.endswith(" " + alias):
            return key
    for key in DEPARTMENTS + ("Sales", "HR"):
        if lowered == key.lower() or lowered.startswith(key.lower() + " "):
            return key
    return ""


def is_department_member_role(name):
    lowered = str(name or "").strip().lower()
    if not lowered or "hod" in lowered or "head of" in lowered:
        return False
    if "member" not in lowered:
        return False
    return normalize_department(name) in DEPARTMENTS


def should_skip_hod_step(hr_role="", role_names=None):
    """HOD, HR, and Admin apply into #leave-requests unless they hold a department Member role."""
    names = [str(item or "").strip() for item in (role_names or []) if str(item or "").strip()]
    if hod_department_from_role_names(names):
        return True
    if any(is_department_member_role(name) for name in names):
        return False
    for name in names:
        lowered = name.lower()
        if lowered in {"admin", "hr", "administrator"}:
            return True
        if lowered.startswith("admin ") or lowered.endswith(" admin"):
            return True
    if names:
        return False
    title = str(hr_role or "").strip().lower()
    return title in {"hr", "admin", "administrator"} or is_hod_title(title)


def is_hod_title(value):
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text in {"hod", "h.o.d", "head of department", "head"}:
        return True
    return "hod" in text or text.startswith("head of")


def _role_names(role_names):
    return [str(item or "").strip() for item in (role_names or []) if str(item or "").strip()]


def department_from_role_names(role_names):
    found = []
    for name in _role_names(role_names):
        dept = normalize_department(name)
        if dept and dept not in found:
            found.append(dept)
    for dept in DEPARTMENTS:
        if dept in found:
            return dept
    return found[0] if found else ""


def hod_queue_department(role_names=None, airtable_department=""):
    """Department used for HOD routing. BI/CS/Marketing beat Sales and Airtable."""
    names = _role_names(role_names)
    hod = hod_department_from_role_names(names)
    member = department_from_role_names(names)
    stored = normalize_department(airtable_department)
    for candidate in (hod, member, stored):
        if candidate in DEPARTMENTS:
            return candidate
    return member or stored


def hod_department_from_role_names(role_names):
    for name in _role_names(role_names):
        lowered = name.lower()
        if "hod" not in lowered and "head of" not in lowered:
            continue
        dept = normalize_department(name)
        if dept:
            return dept
    return ""


def hod_channel_name(department):
    return CHANNEL_NAMES.get(normalize_department(department) or department, "")


def hod_display_name(department):
    key = normalize_department(department) or department
    return DISPLAY_NAMES.get(key, "HOD")


def hod_role_ids_from_config(config):
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    raw = tickets.get("hodRoleIds") or {}
    out = {}
    for key in DEPARTMENTS:
        value = str((raw.get(key) or raw.get(key.lower()) or "")).strip()
        if value and "PASTE_" not in value:
            out[key] = value
    return out


def hod_channel_ids_from_config(config):
    tickets = ((config or {}).get("discord") or {}).get("tickets") or {}
    raw = tickets.get("hodChannels") or {}
    out = {}
    for key in DEPARTMENTS:
        value = str((raw.get(key) or raw.get(key.lower()) or "")).strip()
        if value.isdigit():
            out[key] = value
    return out


def find_hod_role_id(roles, department, configured_id=""):
    wanted = normalize_department(department)
    if not wanted:
        return ""
    configured = str(configured_id or "").strip()
    if configured.isdigit():
        return configured
    needle = wanted.lower()
    for role in roles or []:
        name = str(role.get("name") or "").strip().lower()
        rid = str(role.get("id") or "").strip()
        if not rid:
            continue
        if needle in name and ("hod" in name or "head of" in name):
            return rid
    return ""


def member_hod_department(member, config=None):
    if member is None:
        return ""
    names = [getattr(role, "name", "") for role in getattr(member, "roles", []) or []]
    from_names = hod_department_from_role_names(names)
    if from_names:
        return from_names
    configured = hod_role_ids_from_config(config)
    ids = {str(getattr(role, "id", role)) for role in getattr(member, "roles", []) or []}
    for dept, role_id in configured.items():
        if role_id in ids:
            return dept
    return ""


def member_department(member, config=None):
    hod = member_hod_department(member, config)
    if hod:
        return hod
    names = [getattr(role, "name", "") for role in getattr(member, "roles", []) or []]
    return department_from_role_names(names)


def is_hod_member(member, config=None):
    return bool(member_hod_department(member, config))

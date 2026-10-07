import re
from datetime import datetime, timezone

CATEGORY_TYPE = 4


def ticket_channel_name(username, user_id):
    safe = re.sub(r"[^a-z0-9]+", "-", str(username or "member").lower()).strip("-")[:16] or "member"
    suffix = str(user_id or "")[-4:] or "0000"
    return f"ticket-{safe}-{suffix}"[:100]


def ticket_topic(*, user_id, namespace, parent_channel_id):
    return f"ticket:{user_id}:{namespace}:{parent_channel_id}"


def parse_ticket_topic(topic):
    match = re.match(r"^ticket:(\d+):([^:]+):(\d+)$", str(topic or ""))
    if not match:
        return None
    return {"userId": match.group(1), "namespace": match.group(2), "parentChannelId": match.group(3)}


def format_member_lines(member, user):
    display = (
        getattr(member, "display_name", None)
        or getattr(user, "global_name", None)
        or getattr(user, "username", None)
        or "Unknown member"
    )
    username = f"@{user.username}" if getattr(user, "username", None) else "unknown"
    user_id = str(getattr(user, "id", "unknown"))
    joined = "unknown"
    if getattr(member, "joined_at", None):
        joined = member.joined_at.date().isoformat() if hasattr(member.joined_at, "date") else str(member.joined_at)[:10]
    created = "unknown"
    created_at = getattr(user, "created_at", None)
    if created_at:
        created = created_at.date().isoformat() if hasattr(created_at, "date") else str(created_at)[:10]
    roles = "unknown"
    role_cache = getattr(getattr(member, "roles", None), "cache", None)
    if member is not None:
        names = []
        roles_iter = role_cache.values() if role_cache is not None else getattr(member, "roles", []) or []
        try:
            for role in roles_iter:
                name = getattr(role, "name", None) or (role.get("name") if isinstance(role, dict) else None)
                if name and name != "@everyone":
                    names.append(name)
            roles = ", ".join(names[:8]) or "none"
        except TypeError:
            roles = "unknown"
    return {
        "mention": f"<@{user.id}>" if getattr(user, "id", None) else display,
        "display": display,
        "username": username,
        "id": user_id,
        "joined": joined,
        "created": created,
        "roles": roles,
    }


def _role_ids(member):
    cache = getattr(getattr(member, "roles", None), "cache", None)
    if cache is not None and hasattr(cache, "has"):
        return cache
    ids = set()
    for role in getattr(member, "roles", []) or []:
        ids.add(str(getattr(role, "id", role)))
    return ids


def _has_role(member, role_id):
    cache = getattr(getattr(member, "roles", None), "cache", None)
    if cache is not None and hasattr(cache, "has"):
        return cache.has(str(role_id))
    return str(role_id) in _role_ids(member)


def _has_permission(member, name):
    gp = getattr(member, "guild_permissions", None)
    mapping = {
        "Administrator": "administrator",
        "ManageChannels": "manage_channels",
    }
    attr = mapping.get(name, name.lower())
    if gp is not None and bool(getattr(gp, attr, False)):
        return True
    perms = getattr(member, "permissions", None)
    if perms is None:
        return False
    has = getattr(perms, "has", None)
    if callable(has):
        try:
            return bool(has(name))
        except Exception:
            return False
    return bool(getattr(perms, attr, False))


def can_close_ticket(user_id, member, ticket, access=None):
    if not ticket:
        return False
    if str(user_id) == str(ticket.get("userId")):
        return True
    if isinstance(access, str):
        staff_role_id, admin_role_id = access, ""
    else:
        access = access or {}
        admin_role_id = access.get("adminRoleId") or ""
        staff_role_id = access.get("staffRoleId") or ""
    if admin_role_id and _has_role(member, admin_role_id):
        return True
    if staff_role_id and _has_role(member, staff_role_id):
        return True
    if _has_permission(member, "Administrator"):
        return True
    if _has_permission(member, "ManageChannels"):
        return True
    return False


def category_id_from_channel(channel):
    if not channel:
        return None
    channel_type = channel.get("type") if isinstance(channel, dict) else getattr(channel, "type", None)
    channel_id = channel.get("id") if isinstance(channel, dict) else getattr(channel, "id", None)
    parent_id = channel.get("parentId") if isinstance(channel, dict) else getattr(channel, "parent_id", None)
    type_value = channel_type.value if hasattr(channel_type, "value") else channel_type
    if type_value == CATEGORY_TYPE:
        return str(channel_id)
    if parent_id:
        return str(parent_id)
    return None


def find_role_id_by_names(roles, configured_id, names):
    if configured_id:
        return str(configured_id)
    wanted = [name.strip().lower() for name in names]
    for role in roles or []:
        role_name = (role.get("name") if isinstance(role, dict) else getattr(role, "name", "")) or ""
        if role_name.strip().lower() in wanted:
            role_id = role.get("id") if isinstance(role, dict) else getattr(role, "id", None)
            return str(role_id) if role_id else None
    return None


def find_staff_role_id(roles, configured_id):
    return find_role_id_by_names(roles, configured_id, ["staff"])


def find_admin_role_id(roles, configured_id):
    return find_role_id_by_names(roles, configured_id, ["admin", "administrator", "admins"])


def find_hr_role_id(roles, configured_id):
    return find_role_id_by_names(roles, configured_id, ["hr"])


def is_admin_member(member, roles, configured_admin_role_id):
    if not member:
        return False
    if _has_permission(member, "Administrator"):
        return True
    admin_role_id = find_admin_role_id(roles, configured_admin_role_id)
    return bool(admin_role_id and _has_role(member, admin_role_id))


def is_ticket_folder_name(name):
    return str(name or "").strip().lower() in {"ticket", "tickets"}


def pick_ticket_category_id(channels, configured_id):
    items = list(channels or [])

    def channel_type(channel):
        value = channel.get("type") if isinstance(channel, dict) else getattr(channel, "type", None)
        return value.value if hasattr(value, "value") else value

    def channel_name(channel):
        return channel.get("name") if isinstance(channel, dict) else getattr(channel, "name", "")

    def channel_id(channel):
        return str(channel.get("id") if isinstance(channel, dict) else getattr(channel, "id", ""))

    def parent_id(channel):
        value = channel.get("parentId") if isinstance(channel, dict) else getattr(channel, "parent_id", None)
        return str(value) if value else None

    named_folder = next(
        (channel for channel in items if channel_type(channel) == CATEGORY_TYPE and is_ticket_folder_name(channel_name(channel))),
        None,
    )
    if named_folder:
        return channel_id(named_folder)
    if configured_id:
        configured = next((channel for channel in items if channel_id(channel) == str(configured_id)), None)
        if configured and channel_type(configured) == CATEGORY_TYPE:
            return channel_id(configured)
        if configured and parent_id(configured):
            return parent_id(configured)
        if not configured:
            return str(configured_id)
    named = next((channel for channel in items if is_ticket_folder_name(channel_name(channel))), None)
    if named and channel_type(named) == CATEGORY_TYPE:
        return channel_id(named)
    if named and parent_id(named):
        return parent_id(named)
    return str(configured_id) if configured_id else None

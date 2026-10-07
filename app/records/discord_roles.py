"""Guild Discord roles mirrored into MySQL."""

from app.records.fields import db_call, escape_formula_value, is_unknown_field_name


def role_payload(role):
    name = str(getattr(role, "name", None) or (role.get("name") if isinstance(role, dict) else "") or "").strip()
    role_id = str(getattr(role, "id", None) or (role.get("id") if isinstance(role, dict) else "") or "").strip()
    managed = bool(getattr(role, "managed", None) if not isinstance(role, dict) else role.get("managed"))
    mentionable = bool(getattr(role, "mentionable", None) if not isinstance(role, dict) else role.get("mentionable"))
    position = getattr(role, "position", None)
    if position is None and isinstance(role, dict):
        position = role.get("position")
    try:
        position = int(position)
    except (TypeError, ValueError):
        position = 0
    color = getattr(role, "colour", None)
    color_value = getattr(color, "value", None) if color is not None else None
    if color_value is None and isinstance(role, dict):
        color_value = role.get("color") or role.get("colour")
    return {
        "Role Name": name,
        "Discord Role ID": role_id,
        "Position": position,
        "Managed": managed,
        "Mentionable": mentionable,
        "Color": int(color_value or 0),
    }


def skip_role(role):
    name = str(getattr(role, "name", None) or (role.get("name") if isinstance(role, dict) else "") or "")
    return name.strip() in {"", "@everyone"}


def upsert_discord_role(client, role, *, logger=None):
    if client is None or skip_role(role):
        return None
    fields = role_payload(role)
    role_id = fields["Discord Role ID"]
    if not role_id:
        return None
    formula = f"{{Discord Role ID}}='{escape_formula_value(role_id)}'"
    try:
        existing = db_call(
            lambda: client.table("discordRoles").all(formula=formula),
            op="discord_role_lookup",
            logger=logger,
        )
    except Exception as error:
        if logger:
            logger.warn("Discord Roles table is missing; run scripts/setup_mysql.py", {
                "message": str(error)[:200],
            })
        return None
    payload = dict(fields)
    try:
        if existing:
            return db_call(
                lambda: client.table("discordRoles").update(existing[0]["id"], payload),
                op="discord_role_update",
                logger=logger,
            )
        return db_call(
            lambda: client.table("discordRoles").create(payload),
            op="discord_role_create",
            logger=logger,
        )
    except Exception as error:
        if is_unknown_field_name(error):
            slim = {"Role Name": fields["Role Name"], "Discord Role ID": role_id}
            if existing:
                return db_call(
                    lambda: client.table("discordRoles").update(existing[0]["id"], slim),
                    op="discord_role_update",
                    logger=logger,
                )
            return db_call(
                lambda: client.table("discordRoles").create(slim),
                op="discord_role_create",
                logger=logger,
            )
        raise


def delete_discord_role(client, role_id, *, logger=None):
    role_id = str(role_id or "").strip()
    if client is None or not role_id:
        return False
    formula = f"{{Discord Role ID}}='{escape_formula_value(role_id)}'"
    try:
        existing = db_call(
            lambda: client.table("discordRoles").all(formula=formula),
            op="discord_role_lookup",
            logger=logger,
        )
    except Exception as error:
        if logger:
            logger.warn("Could not delete Discord role in MySQL", {"message": str(error)[:200]})
        return False
    for item in existing or []:
        db_call(
            lambda record_id=item["id"]: client.table("discordRoles").delete(record_id),
            op="discord_role_delete",
            logger=logger,
        )
    return bool(existing)


def sync_guild_roles(client, roles, *, logger=None):
    live_ids = set()
    synced = 0
    for role in roles or []:
        if skip_role(role):
            continue
        record = upsert_discord_role(client, role, logger=logger)
        role_id = role_payload(role).get("Discord Role ID")
        if role_id:
            live_ids.add(role_id)
        if record:
            synced += 1
    removed = 0
    try:
        existing = db_call(
            lambda: client.table("discordRoles").all(),
            op="discord_role_list",
            logger=logger,
        )
    except Exception as error:
        if logger:
            logger.warn("Could not prune Discord Roles table", {"message": str(error)[:200]})
        existing = []
    for item in existing or []:
        stored = str(((item.get("fields") or {}).get("Discord Role ID")) or "").strip()
        if stored and stored not in live_ids:
            db_call(
                lambda record_id=item["id"]: client.table("discordRoles").delete(record_id),
                op="discord_role_delete",
                logger=logger,
            )
            removed += 1
    if logger:
        logger.info("MySQL Discord roles sync", {"roles": synced, "removed": removed})
    return synced

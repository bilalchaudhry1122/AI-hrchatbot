"""Sync Discord members into MySQL Employees + leave quota.

Needs DISCORD_TOKEN and DATABASE_URL (or MYSQL_*) in .env.

Usage:
  python scripts/sync_discord_staff.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.config import load_channel_map, optional  # noqa: E402
from app.db.client import create_mysql_client  # noqa: E402
from app.records.discord_roles import sync_guild_roles  # noqa: E402
from app.records.employees import list_employees  # noqa: E402
from app.hr.staff_onboard import LEAVE_GRANTS, staff_kind_from_roles, upsert_staff_employee  # noqa: E402
from app.logger import create_logger  # noqa: E402
from app.config import load_config  # noqa: E402

API = "https://discord.com/api/v10"


def dget(path, token, params=None):
    response = requests.get(
        f"{API}{path}",
        headers={"Authorization": f"Bot {token}"},
        params=params or {},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def pick_roles(roles):
    by_name = {str(role.get("name") or "").strip().lower(): role for role in roles}
    admin = by_name.get("admin")
    staff = by_name.get("staff")
    hr = by_name.get("hr")
    return admin, staff, hr


def is_bot(member):
    return bool((member.get("user") or {}).get("bot"))


def classify(member, admin_id, staff_id, role_names=None):
    role_ids = {str(rid) for rid in (member.get("roles") or [])}
    names = list(role_names or [])
    kind = staff_kind_from_roles(
        names,
        admin_role_id=admin_id,
        hr_role_id="",
        member_role_ids=role_ids,
    )
    if not kind:
        return None
    user = member.get("user") or {}
    return {
        "discord_id": str(user.get("id") or ""),
        "name": member.get("nick") or user.get("global_name") or user.get("username") or "Member",
        "kind": kind,
        "role_names": names,
    }


def deactivate_missing(client, live, logger=None):
    deactivated = []
    for person in list_employees(client, logger=logger):
        discord_id = str(person.get("discordUserId") or "").strip()
        if not discord_id or discord_id in live:
            continue
        if not person.get("active"):
            continue
        record_id = person.get("id")
        if not record_id:
            continue
        client.table("employees").update(record_id, {"Status": "Inactive"})
        deactivated.append(person.get("name") or discord_id)
        if logger:
            logger.info("Staff marked inactive", {"discordUserId": discord_id, "name": person.get("name")})
    return deactivated


def write_env_value(key, value):
    set_key(ROOT / ".env", key, value, quote_mode="never")


def update_channels_json(admin_id, staff_id):
    import json

    path = ROOT / "channels.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    tickets = data.setdefault("tickets", {})
    if admin_id:
        tickets["adminRoleId"] = admin_id
    if staff_id:
        tickets["staffRoleId"] = staff_id
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main():
    discord_token = optional("DISCORD_TOKEN")
    config = load_config()
    if not discord_token or not (config.get("db") or {}).get("enabled"):
        print("Need DISCORD_TOKEN and DATABASE_URL (or MYSQL_*) in .env")
        sys.exit(1)

    mapped = load_channel_map()
    channel_id = next(iter(mapped.get("channels") or {}), None)
    if not channel_id:
        print("No mapped Discord channel in channels.json")
        sys.exit(1)

    channel = dget(f"/channels/{channel_id}", discord_token)
    guild_id = channel.get("guild_id")
    roles = dget(f"/guilds/{guild_id}/roles", discord_token)
    roles_by_id = {str(role["id"]): role for role in roles}
    admin_role, staff_role, hr_role = pick_roles(roles)
    if not admin_role and not hr_role:
        print("No Admin or HR role found on the Discord server.")
        sys.exit(1)
    admin_id = str(admin_role["id"]) if admin_role else ""
    staff_id = str(staff_role["id"]) if staff_role else ""
    hr_id = str(hr_role["id"]) if hr_role else admin_id
    print(f"Admin role: {(admin_role or {}).get('name') or '(none)'}")
    print(f"HR role: {(hr_role or {}).get('name') or '(none)'}")
    print(f"Staff role: {(staff_role or {}).get('name') or '(none)'}")

    members = dget(f"/guilds/{guild_id}/members", discord_token, params={"limit": 1000})
    logger = create_logger("info")
    client = create_mysql_client(config, logger)
    if client is None:
        print("MySQL client failed to start.")
        sys.exit(1)
    print("Using MySQL")
    role_count = sync_guild_roles(client, roles, logger=logger)
    print(f"Discord roles synced: {role_count}")
    synced = []
    live = set()
    for member in members:
        if is_bot(member):
            continue
        names = [str((roles_by_id.get(str(rid)) or {}).get("name") or "") for rid in member.get("roles") or []]
        profile = classify(member, admin_id, staff_id, role_names=names)
        if not profile:
            continue
        user = member.get("user") or {}
        live.add(str(user.get("id") or ""))
        record = upsert_staff_employee(
            client,
            discord_id=profile["discord_id"],
            name=profile["name"],
            kind=profile["kind"],
            role_names=profile["role_names"],
            logger=logger,
        )
        synced.append(record.get("name") or profile["name"])

    deactivated = deactivate_missing(client, live, logger=logger)
    if hr_id:
        write_env_value("HR_ROLE_ID", hr_id)
    update_channels_json(admin_id, staff_id)
    print(f"Synced {len(synced)} staff: {', '.join(synced) or '(none)'}")
    if deactivated:
        print(f"Deactivated {len(deactivated)}: {', '.join(deactivated)}")
    print(f"Leave grants: {LEAVE_GRANTS}")


if __name__ == "__main__":
    main()

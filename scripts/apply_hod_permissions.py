"""One-shot: lock HOD and HR leave channels using the bot token.

Discord MCP cannot set channel overwrites. This uses the same bot the MCP
logged in as, after MCP listed the guild channels.
"""

import json
import time
import urllib.error
import urllib.request

from app.config import ROOT_DIR, load_config
from app.hr.departments import (
    DEPARTMENTS,
    find_hod_role_id,
)

GUILD_ID = "1544669715702751314"
API = "https://discord.com/api/v10"

VIEW = 1 << 10
SEND = 1 << 11
HISTORY = 1 << 16
REACT = 1 << 6
MANAGE_MSG = 1 << 13
MANAGE_CH = 1 << 4
EMBED = 1 << 14


def _api(token, method, path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "WebAiryHR-Permissions/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as error:
        payload = error.read().decode("utf-8", errors="replace")
        if error.code == 429:
            retry = 1.5
            try:
                retry = float(json.loads(payload).get("retry_after") or retry)
            except ValueError:
                pass
            time.sleep(retry + 0.2)
            return _api(token, method, path, body)
        raise SystemExit(f"Discord {method} {path} -> {error.code}: {payload[:400]}")


def ow(role_id, *, allow=0, deny=0, kind=0):
    return {
        "id": str(role_id),
        "type": kind,
        "allow": str(int(allow)),
        "deny": str(int(deny)),
    }


def main():
    config = load_config()
    token = config["discord"]["token"]
    tickets = config["discord"]["tickets"]
    airtable = config.get("hr") or {}
    me = _api(token, "GET", "/users/@me")
    bot_id = str(me["id"])
    print(f"bot={me.get('username')} id={bot_id}")

    roles = _api(token, "GET", f"/guilds/{GUILD_ID}/roles")
    role_list = [{"id": str(r["id"]), "name": r["name"]} for r in roles]
    print("roles:")
    for item in role_list:
        print(f"  {item['name']} {item['id']}")

    admin_id = tickets.get("adminRoleId") or airtable.get("adminRoleId")
    named_hr = next((str(item["id"]) for item in role_list if str(item.get("name") or "").strip().lower() == "hr"), "")
    named_admin = next(
        (
            str(item["id"])
            for item in role_list
            if str(item.get("name") or "").strip().lower() in {"admin", "administrator", "admins"}
        ),
        "",
    )
    hr_id = str(airtable.get("hrRoleId") or named_hr or "")
    if hr_id and str(admin_id) == hr_id:
        admin_for_hod = named_admin
    else:
        admin_for_hod = named_admin or admin_id
    staff_id = tickets.get("staffRoleId")
    hod_ids = {}
    for dept in DEPARTMENTS:
        found = find_hod_role_id(role_list, dept, "")
        if found:
            hod_ids[dept] = found
    print("hod roles:", hod_ids)
    if len(hod_ids) < 3:
        raise SystemExit("Need Discord roles named BI HOD, CS HOD, and Marketing HOD.")

    see = VIEW | HISTORY
    hide = VIEW
    hod_see = VIEW | HISTORY
    hod_deny = SEND | REACT
    bot_allow = VIEW | SEND | HISTORY | MANAGE_MSG | MANAGE_CH | EMBED

    hod_channels = tickets.get("hodChannels") or {}
    hr_channel = tickets.get("leaveReviewChannelId")
    hr_parent = tickets.get("hrCategoryId") or None
    hod_parent = tickets.get("hodCategoryId") or None

    def hod_overwrites(department):
        rows = [
            ow(GUILD_ID, deny=hide),
            ow(bot_id, allow=bot_allow, kind=1),
        ]
        if admin_for_hod and str(admin_for_hod) != str(hr_id or ""):
            rows.append(ow(admin_for_hod, allow=see, deny=SEND | REACT))
        if hr_id:
            rows.append(ow(hr_id, deny=hide))
        if admin_id and str(admin_id) == str(hr_id or "") and admin_id != admin_for_hod:
            rows.append(ow(admin_id, deny=hide))
        if staff_id and staff_id not in {admin_id, hr_id}:
            rows.append(ow(staff_id, deny=hide))
        this = hod_ids[department]
        rows.append(ow(this, allow=hod_see, deny=hod_deny))
        for dept, rid in hod_ids.items():
            if dept != department:
                rows.append(ow(rid, deny=hide))
        return rows

    def hr_overwrites():
        rows = [
            ow(GUILD_ID, deny=hide),
            ow(bot_id, allow=bot_allow, kind=1),
        ]
        if admin_id:
            rows.append(ow(admin_id, allow=see, deny=SEND | REACT))
        if hr_id and hr_id != admin_id:
            rows.append(ow(hr_id, allow=see, deny=SEND | REACT))
        if staff_id and staff_id not in {admin_id, hr_id}:
            rows.append(ow(staff_id, deny=hide))
        for rid in hod_ids.values():
            if rid not in {admin_id, hr_id}:
                rows.append(ow(rid, deny=hide))
        return rows

    for dept, channel_id in hod_channels.items():
        body = {
            "permission_overwrites": hod_overwrites(dept),
            "topic": f"{dept} HOD leave inbox. HR cannot see this channel.",
        }
        if hod_parent:
            body["parent_id"] = hod_parent
        _api(token, "PATCH", f"/channels/{channel_id}", body)
        print(f"locked #{dept} {channel_id}")

    if hr_channel:
        body = {
            "permission_overwrites": hr_overwrites(),
            "topic": "Leave requests for Admin and HR only after HOD approval.",
        }
        if hr_parent:
            body["parent_id"] = hr_parent
        _api(token, "PATCH", f"/channels/{hr_channel}", body)
        print(f"locked #leave-requests {hr_channel}")

    ticket_hide = VIEW
    guild_channels = _api(token, "GET", f"/guilds/{GUILD_ID}/channels")
    for channel in guild_channels or []:
        topic = str(channel.get("topic") or "")
        if not topic.startswith("ticket:"):
            continue
        existing = list(channel.get("permission_overwrites") or [])
        by_id = {str(item.get("id")): item for item in existing}
        for rid in hod_ids.values():
            by_id[rid] = ow(rid, deny=ticket_hide)
        if staff_id:
            by_id[staff_id] = ow(staff_id, deny=hide)
        _api(
            token,
            "PATCH",
            f"/channels/{channel['id']}",
            {"permission_overwrites": list(by_id.values())},
        )
        print(f"ticket {channel['name']} hods hidden")

    channels_path = ROOT_DIR / "channels.json"
    parsed = json.loads(channels_path.read_text(encoding="utf-8"))
    parsed.setdefault("tickets", {})["hodRoleIds"] = hod_ids
    parsed["tickets"]["hodChannels"] = hod_channels
    channels_path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
    print("saved hodRoleIds to channels.json")


if __name__ == "__main__":
    main()

"""Move #leave-requests into HR and HOD inboxes into HOD."""

import json
import urllib.request

from app.config import load_config

GUILD = "1544669715702751314"
API = "https://discord.com/api/v10"


def main():
    config = load_config()
    token = config["discord"]["token"]
    tickets = config["discord"]["tickets"]
    hr_parent = tickets.get("hrCategoryId") or ""
    hod_parent = tickets.get("hodCategoryId") or ""
    moves = []
    if hr_parent:
        moves.append((tickets.get("leaveReviewChannelId"), hr_parent))
    if hod_parent:
        for channel_id in (tickets.get("hodChannels") or {}).values():
            moves.append((channel_id, hod_parent))
    for channel_id, parent in moves:
        if not channel_id or not parent:
            continue
        req = urllib.request.Request(
            f"{API}/channels/{channel_id}",
            data=json.dumps({"parent_id": parent}).encode(),
            method="PATCH",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "WebAiryHR-Permissions/1.0",
            },
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        print(data.get("name"), "->", data.get("parent_id"))


if __name__ == "__main__":
    main()

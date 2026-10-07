import threading
from pathlib import Path

from app.json_store import read_json, write_json_atomic


class TicketStore:
    def __init__(self, file_path, logger=None):
        self.file_path = Path(file_path)
        self.logger = logger
        # Writes come from the gateway loop, reads from worker threads.
        self.lock = threading.RLock()
        self.data = self._load()

    def all(self):
        return self.data["tickets"]

    def get_by_channel(self, channel_id):
        return self.data["tickets"].get(str(channel_id))

    def tickets_for_user(self, user_id):
        uid = str(user_id)
        tickets = [ticket for ticket in self.data["tickets"].values() if ticket.get("userId") == uid]
        tickets.sort(key=lambda ticket: str(ticket.get("createdAt") or ""), reverse=True)
        return tickets

    def find_open(self, user_id, parent_channel_id=None):
        tickets = [ticket for ticket in self.tickets_for_user(user_id) if ticket.get("status") != "closed"]
        if parent_channel_id:
            match = next((ticket for ticket in tickets if ticket.get("parentChannelId") == str(parent_channel_id)), None)
            if match:
                return match
        return tickets[0] if tickets else None

    def find_by_user(self, user_id):
        tickets = self.tickets_for_user(user_id)
        return tickets[0] if tickets else None

    def find_all_by_user(self, user_id):
        return self.tickets_for_user(user_id)

    def upsert(self, ticket):
        bot_active = ticket.get("botActive")
        record = {
            **ticket,
            "channelId": str(ticket["channelId"]),
            "userId": str(ticket["userId"]),
            "parentChannelId": str(ticket.get("parentChannelId") or ""),
            "status": ticket.get("status") or "open",
            "botActive": True if bot_active is None else bool(bot_active),
        }
        with self.lock:
            self.data["tickets"][str(ticket["channelId"])] = record
            self._save()
        return record

    def close(self, channel_id):
        from datetime import datetime, timezone

        with self.lock:
            ticket = self.data["tickets"].get(str(channel_id))
            if not ticket:
                return None
            ticket["status"] = "closed"
            ticket["closedAt"] = datetime.now(timezone.utc).isoformat()
            self._save()
            return ticket

    def set_bot_active(self, channel_id, active):
        with self.lock:
            ticket = self.data["tickets"].get(str(channel_id))
            if not ticket:
                return None
            ticket["botActive"] = bool(active)
            self._save()
            return ticket

    def remove(self, channel_id):
        with self.lock:
            self.data["tickets"].pop(str(channel_id), None)
            self._save()

    def _load(self):
        parsed = read_json(self.file_path, default=None, logger=self.logger)
        if not isinstance(parsed, dict):
            return {"tickets": {}}
        tickets = parsed.get("tickets")
        return {"tickets": tickets if isinstance(tickets, dict) else {}}

    def _save(self):
        write_json_atomic(self.file_path, {"tickets": self.data["tickets"]})


def create_ticket_store(file_path, logger=None):
    return TicketStore(file_path, logger=logger)

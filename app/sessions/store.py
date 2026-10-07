"""Per-ticket chat memory. Survives bot restart. Not Pinecone."""

from datetime import datetime, timezone
import json
from pathlib import Path

MAX_TURNS = 40
MAX_ANSWER_CHARS = 4000
MAX_TURN_CHARS = 800


class SessionStore:
    def __init__(self, file_path):
        self.file_path = Path(file_path)
        self.data = self._load()

    def get(self, channel_id):
        record = self.data["sessions"].get(str(channel_id)) or {}
        return {
            "turns": list(record.get("turns") or []),
            "lastTopic": str(record.get("lastTopic") or ""),
            "lastAnswer": str(record.get("lastAnswer") or ""),
            "lastIntent": str(record.get("lastIntent") or ""),
        }

    def remember(self, channel_id, *, question, answer, intent="", grounded=False, followup=False):
        key = str(channel_id)
        record = self.get(key)
        turns = list(record["turns"])
        q = str(question or "").strip()[:MAX_TURN_CHARS]
        a = str(answer or "").strip()[:MAX_ANSWER_CHARS]
        if q:
            turns.append({"role": "user", "content": q})
        if a:
            turns.append({"role": "assistant", "content": a[:MAX_TURN_CHARS]})
        record["turns"] = turns[-MAX_TURNS:]
        if grounded and q and not followup:
            record["lastTopic"] = str(question or "").strip()[:500]
        if grounded and a:
            record["lastAnswer"] = a
        elif followup and a and record.get("lastAnswer"):
            record["lastAnswer"] = a
        if intent:
            record["lastIntent"] = str(intent)
        record["updatedAt"] = datetime.now(timezone.utc).isoformat()
        self.data["sessions"][key] = record
        self._save()
        return record

    def clear(self, channel_id):
        self.data["sessions"].pop(str(channel_id), None)
        self._save()

    def _load(self):
        try:
            parsed = json.loads(self.file_path.read_text(encoding="utf-8"))
            sessions = parsed.get("sessions") if isinstance(parsed.get("sessions"), dict) else {}
            return {"sessions": sessions}
        except OSError:
            return {"sessions": {}}

    def _save(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(json.dumps({"sessions": self.data["sessions"]}, indent=2), encoding="utf-8")


def merge_histories(*histories):
    merged = []
    for history in histories:
        for item in history or []:
            role = (item or {}).get("role") or "user"
            content = str((item or {}).get("content") or "").strip()
            if not content:
                continue
            if merged and merged[-1]["role"] == role and merged[-1]["content"] == content:
                continue
            merged.append({"role": role, "content": content})
    return merged


def create_session_store(file_path):
    return SessionStore(file_path)

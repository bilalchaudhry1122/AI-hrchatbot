import re

PLACEHOLDER_IDS = ["PASTE_DISCORD_CHANNEL_ID", "ANOTHER_CHANNEL_ID"]


def normalize_namespace(value):
    return str(value or "").strip().lower()


def namespace_for_channel(channel_map, channel_id):
    if not channel_id:
        return None
    return channel_map.get(str(channel_id))


def is_placeholder_channel_id(channel_id):
    return str(channel_id) in PLACEHOLDER_IDS


def bot_was_mentioned(message, client_user):
    if not client_user:
        return False
    mentions = getattr(message, "mentions", None)
    if mentions is not None:
        has = getattr(mentions, "has", None)
        if callable(has) and has(client_user):
            return True
        users = getattr(mentions, "users", mentions)
        try:
            ids = [getattr(user, "id", user) for user in users]
            if client_user in users or getattr(client_user, "id", None) in ids:
                return True
        except TypeError:
            pass
    pattern = re.compile(rf"<@!?{getattr(client_user, 'id', '')}>")
    return bool(pattern.search(getattr(message, "content", "") or ""))


def should_handle_message(message, *, client_user, respond_mode, namespace):
    if not message or getattr(getattr(message, "author", None), "bot", False):
        return False
    if client_user and getattr(message.author, "id", None) == getattr(client_user, "id", None):
        return False
    if not getattr(message, "guild", None):
        return False
    if not namespace:
        return False
    content = str(getattr(message, "content", "") or "").strip()
    if not content:
        return False
    if respond_mode in {"slash", "command"}:
        return False
    if respond_mode == "mention":
        return bot_was_mentioned(message, client_user)
    return True


def strip_bot_mention(content, client_user):
    text = str(content or "")
    if not client_user:
        return text.strip()
    return re.sub(rf"<@!?{getattr(client_user, 'id', '')}>", "", text).strip()

DISCORD_LIMIT = 2000


def format_support_reply(answer, chunks=None, fallback=False):
    """The reply text as the employee sees it.

    Deliberately no source line. Naming the file an answer came from tells the
    employee there is a document store behind the assistant, which is exactly
    what the HR voice avoids. Sources are still logged for diagnostics.
    """
    return str(answer or "").strip()


def split_discord_content(text, limit=DISCORD_LIMIT):
    value = str(text or "").strip()
    if not value:
        return []
    if len(value) <= limit:
        return [value]
    chunks = []
    remaining = value
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit * 0.5:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit * 0.5:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks

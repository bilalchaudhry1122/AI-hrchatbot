"""Short replies that continue the last ticket topic, not a new search."""

import re

from app.agent.verification import POLICY_FOLLOW_SHORT, is_workplace_clarification

REPEAT = re.compile(
    r"^("
    r"give me again|give it again|say (it|that) again|repeat( that| it| this)?"
    r"|once more|again please|again"
    r"|dobara( se)?( batao| btao)?"
    r"|phir se( batao| btao)?"
    r"|wahi (do|batao|btao)|same (thing|again|one)"
    r"|show (it |that |me )?(again|once more)"
    r")[.!? ]*$",
    re.I,
)
FORMAT = re.compile(
    r"\b("
    r"precise form|precis form|in short|in brief|briefly|"
    r"bullet points|in bullets|as bullets|"
    r"summarize|summarise|more detail|in detail|concise|shorter|longer"
    r")\b",
    re.I,
)
FORMAT_ONLY = re.compile(
    r"^("
    r"in precise form|in precis form|precise form|precis form|"
    r"in short|in brief|briefly|in bullets|as bullets|bullet points|"
    r"summarize|summarise|more detail|in detail|concise"
    r")[.!? ]*$",
    re.I,
)
KNOWLEDGEISH = re.compile(
    r"\b("
    r"policy|policies|handbook|leave|chutti|opd|medical|wfh|holiday|"
    r"working hours|attendance|salary info|appraisal|laptop|confidential|"
    r"rule|rules|entitled|allowance"
    r")\b",
    re.I,
)


def is_repeat_followup(text):
    raw = str(text or "").strip()
    if not raw or len(raw) > 80:
        return False
    return bool(REPEAT.match(raw))


def is_format_followup(text):
    raw = str(text or "").strip()
    if not raw or len(raw) > 120:
        return False
    return bool(FORMAT.search(raw))


EXPAND = re.compile(
    r"^("
    r"in detail|more detail|more details|in more detail|"
    r"longer|full(er)?( detail| version)?|explain (more|in detail)|"
    r"batao (detail|poora)|detail mein|zyada detail"
    r")[.!? ]*$",
    re.I,
)


def is_expand_followup(text):
    """Ask for more handbook detail on the prior topic — needs a fresh retrieve."""
    raw = str(text or "").strip()
    if not raw or len(raw) > 80:
        return False
    return bool(EXPAND.match(raw))


def is_session_followup(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    if is_workplace_clarification(raw):
        return True
    if len(raw) <= 80 and POLICY_FOLLOW_SHORT.match(raw):
        return True
    return is_repeat_followup(raw) or bool(FORMAT_ONLY.match(raw)) or is_expand_followup(raw) or (
        is_format_followup(raw) and len(raw) <= 80 and not KNOWLEDGEISH.search(raw)
    )


def last_knowledge_question(history, last_topic=""):
    topic = str(last_topic or "").strip()
    for item in reversed(list(history or [])):
        if str(item.get("role") or "") != "user":
            continue
        text = str(item.get("content") or "").strip()
        if not text or is_session_followup(text):
            continue
        if KNOWLEDGEISH.search(text) or len(text) > 24:
            return text
    return topic

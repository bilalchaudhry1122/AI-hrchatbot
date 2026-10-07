"""Reply language is locked to the current user message."""

import re

from app.routing.roman_urdu import is_roman_urdu

URDU_SCRIPT = re.compile(r"[\u0600-\u06FF]")
ENGLISH_PHRASE = re.compile(
    r"\b("
    r"how many|what is|what are|who am|who is|can you|could you|please|"
    r"i have|do i|tell me about|apply for|i want to|i need to|"
    r"remaining|available|thank you|thanks|hello|good morning|good evening"
    r")\b",
    re.I,
)
ENGLISH_WORDS = re.compile(
    r"\b(the|and|how|what|when|where|why|which|who|please|could|would|"
    r"have|has|remaining|available|apply|request|tomorrow|today|"
    r"hello|thanks|need|want)\b",
    re.I,
)

MODES = ("english", "roman", "urdu", "mix")


def has_urdu_script(text):
    return bool(URDU_SCRIPT.search(str(text or "")))


def has_roman_urdu(text):
    return is_roman_urdu(text)


def has_english(text):
    raw = str(text or "")
    if ENGLISH_PHRASE.search(raw):
        return True
    if has_urdu_script(raw) or has_roman_urdu(raw):
        return False
    return bool(ENGLISH_WORDS.search(raw))


def detect_reply_language(text):
    raw = str(text or "").strip()
    if not raw:
        return "english"
    flags = []
    if has_urdu_script(raw):
        flags.append("urdu")
    if has_roman_urdu(raw):
        flags.append("roman")
    if has_english(raw):
        flags.append("english")
    if len(flags) >= 2:
        return "mix"
    if flags == ["urdu"]:
        return "urdu"
    if flags == ["roman"]:
        return "roman"
    return "english"


def language_lock_rules(question=""):
    mode = detect_reply_language(question)
    header = (
        f"Reply language parameter: {mode}. "
        "Match the user message exactly. Do not mention that you are translating."
    )
    if mode == "english":
        return header + "\n- Reply in English only. No Roman Urdu. No Urdu script."
    if mode == "roman":
        return (
            header
            + "\n- Reply in Roman Urdu (Latin letters, words like kya, kitna, baqi, chutti). "
            "Do not use Urdu script. Do not switch to full formal English."
        )
    if mode == "urdu":
        return header + "\n- Reply in Urdu script only. Do not reply in English or Roman Urdu."
    return (
        header
        + "\n- The user mixed languages. Reply in the same mix and the same scripts. "
        "Keep HR terms like Annual Leave readable."
    )


def policy_language_rules(question=""):
    """Policy answers follow the question language; keep terms and numbers exact.

    English / Roman Urdu / Urdu script / mix — same lock as other replies.
    Translation is allowed; inventing or softening policy is not.
    """
    lock = language_lock_rules(question)
    return (
        f"{lock}\n"
        "- This is an official company-policy answer from the reference text.\n"
        "- Give a useful answer: the main points that match the question "
        "(typically 3 to 6 short sentences covering the key rules, limits, and conditions).\n"
        "- Keep the exact terms, numbers, and conditions from the reference text. Do not soften, "
        "add to, or change them.\n"
        "- You may translate the wording into the reply language above so the employee can read it "
        "easily; translate the facts faithfully. Do not invent policy.\n"
        "- Keep official leave-type names readable (e.g. Annual Leave, Sick Leave, Casual Leave) "
        "even when the rest of the reply is Urdu or Roman Urdu.\n"
        "- Do not paste every minor clause of a long section, and do not answer with only a one-line "
        "headline plus a menu of topics to ask about.\n"
        "- Do not tell the employee that you are following a language rule."
    )


def pick_locale_text(locale, *, english, roman, urdu, mix=None):
    mode = locale if locale in MODES else detect_reply_language(locale or "")
    if mode == "urdu":
        return urdu
    if mode == "roman":
        return roman
    if mode == "mix":
        return mix if mix is not None else f"{english} / {roman}"
    return english

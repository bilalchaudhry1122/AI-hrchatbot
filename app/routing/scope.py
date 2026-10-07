"""What this assistant will and will not answer.

It is an HR support assistant. Company policy, the employee's own leave,
attendance, and this ticket are in scope. Maths homework, general trivia,
coding, news and entertainment are not.

Off-topic messages are caught here, before any knowledge lookup, so the bot
never spends a retrieval on "what is 2x2" and never risks answering it from a
loosely matching handbook chunk. The reply stays warm and professional: name
what is out of scope once, then point at something useful.

Order matters. Anything carrying workplace vocabulary is treated as in scope,
so "calculate my remaining leave" is HR even though it says calculate.
"""

import re

from app.routing.language import detect_reply_language, pick_locale_text

# Private employee profile fields. These are only for HR in #hr-profiles —
# never answered in tickets or general chat.
PROFILE_PII = re.compile(
    r"\b("
    r"cnic|nic|national id|identity card|"
    r"date of birth|d\.?o\.?b\.?|"
    r"home address|residential address|my address|kisi ki address|"
    r"contact number|phone number|mobile number|personal (?:email|number|phone)|"
    r"employee profile|staff profile|someone'?s profile|kisi ka profile|"
    r"personal (?:info|information|data|details)|private (?:info|information|data|details)|"
    r"show (?:me )?(?:my |their |his |her )?(?:cnic|dob|address|contact)|"
    r"what(?:'s| is) (?:my |their |his |her )?(?:cnic|dob|address|phone|contact number)"
    r")\b",
    re.I,
)

# Workplace vocabulary. If any of this is present the message is treated as
# HR-related and never redirected, even if it also looks like something else.
HR_VOCABULARY = re.compile(
    r"\b("
    r"leave|leaves|chutti|chuttiyan|vacation|holiday|holidays|off day|day off|"
    r"attendance|present|absent|late|check[- ]?in|check[- ]?out|timesheet|shift|roster|"
    r"salary|pay|payroll|payslip|wage|bonus|increment|raise|allowance|reimburse|expense|"
    r"policy|policies|handbook|rule|rules|code of conduct|guideline|"
    r"hr|human resource|manager|supervisor|team lead|boss|"
    r"employee|employment|staff|colleague|coworker|"
    r"contract|probation|notice period|resign|resignation|termination|fired|"
    r"appraisal|performance|review|promotion|"
    r"benefit|benefits|insurance|medical|health cover|provident|pension|gratuity|"
    r"office|workplace|work from home|wfh|remote work|hybrid|"
    r"onboarding|joining|induction|training|"
    r"complaint|grievance|harassment|dispute|investigation|"
    r"maternity|paternity|bereavement|sick|bimar|bimari|"
    r"annual|casual|salana|"
    r"working hours?|timing|overtime|"
    r"ticket|balance|quota|entitlement|entitled|apply|approval|approve|request|"
    r"document|certificate|letter|experience letter|noc|"
    r"opd|dental|intern|freelance|freelancing|company laptop|personal (pc|laptop)|"
    r"confidential|carry[- ]forward|substitute holiday|labour day|labor day"
    r")\b",
    re.I,
)

# Roman Urdu workplace words that the English list would miss.
HR_VOCABULARY_ROMAN = re.compile(
    r"\b(tankhwah|tankhah|naukri|nokri|kaam|daftar|chutti|darkhwast|manzoori|"
    r"hazri|hazri lagana|mulazim|mulazmat|izafa|bonus|maazrat)\b",
    re.I,
)

# --- out of scope signals ---------------------------------------------------

MATH_WORDS = re.compile(
    r"\b(calculate|solve|multiply|divide|add|subtract|sum of|square root|percentage of|"
    r"equation|algebra|derivative|integral|factorial)\b",
    re.I,
)
# "2x2", "5 + 5", "12*7=?" - an expression with no words around it.
BARE_ARITHMETIC = re.compile(
    r"^\s*(?:what(?:'s| is)\s+|kitna\s+|batao\s+)?"
    r"\d+(?:\s*[-+*/x×÷^]\s*\d+)+\s*(?:=\s*\??)?\s*[?.]?\s*$",
    re.I,
)
# "15% of 200", "20 percent of 500" - only without workplace words, which are
# checked first, so "20% of my salary" stays in scope.
PERCENT_OF = re.compile(r"\b\d+\s*(?:%|percent|percentage)\s*(?:of|ka)\s*\d+", re.I)

CODE = re.compile(
    r"\b(python|javascript|java|c\+\+|sql query|html|css|react|node\.?js|"
    r"write (?:me )?(?:a |some )?code|debug|stack ?trace|compile|api endpoint|"
    r"regex|algorithm|function that|script that)\b",
    re.I,
)

TRIVIA = re.compile(
    r"\b(capital of|population of|who (?:is|was) (?:the )?(?:president|prime minister|king|queen|"
    r"einstein|newton|shakespeare)|tallest|largest country|highest mountain|"
    r"how far is|distance between|when was .* (?:invented|discovered|born)|"
    r"history of|meaning of life)\b",
    re.I,
)

ENTERTAINMENT = re.compile(
    r"\b(movie|film|song|lyrics|music|netflix|youtube|anime|drama serial|"
    r"tell me a joke|joke sunao|funny story|game|gaming|pubg|fortnite|cricket score|"
    r"football|match score|ipl|psl)\b",
    re.I,
)

WORLD = re.compile(
    r"\b(weather|mausam|temperature outside|forecast|"
    r"news|headlines|politics|election|prime minister|stock market|share price|"
    r"bitcoin|crypto|dollar rate|exchange rate|gold rate)\b",
    re.I,
)

AI_TALK = re.compile(
    r"\b(chatgpt|gpt-?\d|openai|gemini|claude|llama|which model are you|"
    r"what model|are you gpt|language model|prompt engineering)\b",
    re.I,
)

PERSONAL_ADVICE = re.compile(
    r"\b(recipe|how to cook|diet plan|workout|gym routine|"
    r"girlfriend|boyfriend|relationship advice|marriage proposal|"
    r"which phone should i buy|best laptop|shopping)\b",
    re.I,
)

# Medical and legal advice: adjacent to HR, but not something to answer.
OUTSIDE_EXPERTISE = re.compile(
    r"\b(diagnose|prescribe|what medicine|which medicine|dawai|"
    r"sue (?:my|the) (?:company|employer)|legal advice|lawyer|court case)\b",
    re.I,
)

KINDS = (
    ("math", MATH_WORDS),
    ("code", CODE),
    ("trivia", TRIVIA),
    ("entertainment", ENTERTAINMENT),
    ("world", WORLD),
    ("ai", AI_TALK),
    ("advice", PERSONAL_ADVICE),
    ("expertise", OUTSIDE_EXPERTISE),
)


def mentions_hr_topic(text):
    """Does the message carry workplace vocabulary?"""
    raw = str(text or "")
    return bool(HR_VOCABULARY.search(raw) or HR_VOCABULARY_ROMAN.search(raw))


def off_topic_kind(text):
    """Name the off-topic category, or None when the message may be HR.

    Workplace vocabulary always wins, so an HR question that happens to use a
    word like "calculate" or "medical" is never redirected.
    """
    raw = str(text or "").strip()
    if not raw or len(raw) > 400:
        return None
    if mentions_hr_topic(raw):
        return None
    if BARE_ARITHMETIC.match(raw) or PERCENT_OF.search(raw):
        return "math"
    for kind, pattern in KINDS:
        if pattern.search(raw):
            return kind
    return None


def is_off_topic(text):
    return off_topic_kind(text) is not None


# --- the redirect ------------------------------------------------------------

_WHAT_I_DO = {
    "english": (
        "I can help with company policy, your leave balance, applying for leave, "
        "or putting you in touch with HR."
    ),
    "roman": (
        "Main company policy, aapki leave balance, leave apply karne, "
        "ya HR se baat karwane mein madad kar sakta hoon."
    ),
    "urdu": (
        "میں کمپنی پالیسی، آپ کی چھٹیوں کا بیلنس، چھٹی کی درخواست، حاضری، "
        "یا HR سے رابطے میں مدد کر سکتا ہوں۔"
    ),
    "mix": (
        "Main company policy, your leave balance, leave apply, "
        "ya HR se baat karwane mein madad kar sakta hoon."
    ),
}

_OPENERS = {
    "math": {
        "english": "That one is outside what I handle here.",
        "roman": "Yeh cheez mere kaam se bahar hai.",
        "urdu": "یہ میرے کام کے دائرے سے باہر ہے۔",
        "mix": "Yeh mere scope se bahar hai.",
    },
    "code": {
        "english": "I am not the right assistant for technical or coding questions.",
        "roman": "Coding ya technical sawal ke liye main sahi assistant nahi hoon.",
        "urdu": "کوڈنگ یا تکنیکی سوالات کے لیے میں مناسب نہیں ہوں۔",
        "mix": "Coding ya technical questions ke liye main sahi assistant nahi hoon.",
    },
    "expertise": {
        "english": "I am not able to give medical or legal advice.",
        "roman": "Main medical ya legal mashwara nahi de sakta.",
        "urdu": "میں طبی یا قانونی مشورہ نہیں دے سکتا۔",
        "mix": "Main medical ya legal advice nahi de sakta.",
    },
}

_DEFAULT_OPENER = {
    "english": "That is outside what I can help with here.",
    "roman": "Yeh mere kaam ke daire se bahar hai.",
    "urdu": "یہ میری مدد کے دائرے سے باہر ہے۔",
    "mix": "Yeh mere scope se bahar hai.",
}

_INVITE = {
    "english": "Is there anything about your work or HR I can look into for you?",
    "roman": "Kya aapke kaam ya HR se juda koi sawal hai jo main dekh doon?",
    "urdu": "کیا آپ کے کام یا HR سے متعلق کوئی سوال ہے جو میں دیکھ سکوں؟",
    "mix": "Koi HR ya kaam se juda sawal ho to bataiye, main dekh leta hoon.",
}


def _pick(table, locale):
    return table.get(locale, table["english"])


def redirect_reply(text="", kind=None, locale=None):
    """A short, professional redirect: what I am, what I can do, an invitation.

    Deliberately not apologetic and never preachy. It states the boundary once
    and moves the conversation back to work.
    """
    mode = locale if locale in {"english", "roman", "urdu", "mix"} else detect_reply_language(text)
    kind = kind or off_topic_kind(text) or "other"
    opener = _pick(_OPENERS.get(kind, _DEFAULT_OPENER), mode)
    return f"{opener} {_pick(_WHAT_I_DO, mode)}\n\n{_pick(_INVITE, mode)}"


def is_profile_pii_request(text):
    """True when the user is asking for private profile fields (CNIC, DOB, etc.)."""
    return bool(PROFILE_PII.search(str(text or "")))


def profile_privacy_reply(text="", locale=None):
    """Refuse profile PII outside #hr-profiles. Never invent or look up the data."""
    mode = locale if locale in {"english", "roman", "urdu", "mix"} else detect_reply_language(text)
    return pick_locale_text(
        mode,
        english=(
            "Employee profile details (CNIC, date of birth, contact, address, and similar) "
            "are private. Only HR can look them up in the HR profiles channel. "
            "I cannot share that information here."
        ),
        roman=(
            "Employee profile details (CNIC, date of birth, contact, address, waghera) private hain. "
            "Sirf HR unhein HR profiles channel mein dekh sakta hai. "
            "Main yahan woh information share nahi kar sakta."
        ),
        urdu=(
            "ملازم کی پروفائل تفصیلات (CNIC، تاریخ پیدائش، رابطہ، پتہ وغیرہ) نجی ہیں۔ "
            "صرف HR انہیں HR profiles چینل میں دیکھ سکتا ہے۔ "
            "میں یہاں یہ معلومات شیئر نہیں کر سکتا۔"
        ),
        mix=(
            "Employee profile details private hain. Only HR can look them up in the HR profiles channel. "
            "Main yahan woh information share nahi kar sakta."
        ),
    )


def no_answer_reply(text="", locale=None, hr_mention=""):
    """When there is no grounded answer to give.

    This must never suggest that a search happened and came back empty, or
    that any records were consulted. The employee is simply pointed at what
    the assistant handles, and offered a person if they need one. From their
    side it reads as a scope reply, not as a failed lookup.
    """
    mode = locale if locale in {"english", "roman", "urdu", "mix"} else detect_reply_language(text)
    body = pick_locale_text(
        mode,
        english=(
            "I look after HR matters here: company policy, your leave, "
            "and anything you need from the HR team. "
            "Could you ask me about one of those?"
        ),
        roman=(
            "Main yahan HR ke maamlat dekhta hoon: company policy, aapki leave, "
            "aur HR team se juri koi bhi zarurat. "
            "In mein se koi sawal poochh lein?"
        ),
        urdu=(
            "میں یہاں HR کے معاملات دیکھتا ہوں: کمپنی پالیسی، آپ کی چھٹیاں، آپ کی حاضری، "
            "اور HR ٹیم سے متعلق ہر ضرورت۔ "
            "کیا آپ ان میں سے کوئی سوال پوچھنا چاہیں گے؟"
        ),
        mix=(
            "Main yahan HR matters dekhta hoon: company policy, aapki leave, "
            "aur HR team se juri koi bhi zarurat. In mein se koi sawal poochh lein?"
        ),
    )
    hint = pick_locale_text(
        mode,
        english='If you would rather speak to a person, say "talk to HR" and I will bring them in.',
        roman='Agar kisi insaan se baat karni ho to "HR se baat" likhein, main unhein bula deta hoon.',
        urdu='اگر کسی فرد سے بات کرنی ہو تو "HR سے بات" لکھیں، میں انہیں بلا دیتا ہوں۔',
        mix='Kisi insaan se baat karni ho to "talk to HR" likhein, main unhein bula deta hoon.',
    )
    return f"{body}\n\n{hint}"


def public_policy_title(source):
    name = str(source or "").strip()
    name = re.sub(r"\.[a-z0-9]{2,5}$", "", name, flags=re.I)
    name = re.sub(r"^WebAiry(?:'s)?\s+", "", name, flags=re.I)
    name = re.sub(r"^Technologies\s+", "", name, flags=re.I)
    name = re.sub(r"\s+Criteria$", "", name, flags=re.I)
    return name.strip() or "Workplace policy"


def policy_catalog_reply(chunks=None, locale=None):
    """Short list of policy topics. Never dump the full text."""
    titles = []
    seen = set()
    for chunk in chunks or []:
        title = public_policy_title((chunk or {}).get("source"))
        key = title.lower()
        if title and key not in seen:
            seen.add(key)
            titles.append(title)
    if not titles:
        titles = [
            "Leave",
            "Attendance",
            "Work from home",
            "Working hours and holidays",
            "Confidentiality",
        ]
    bullets = "\n".join(f"- {title}" for title in titles[:8])
    mode = locale if locale in {"english", "roman", "urdu", "mix"} else "english"
    return pick_locale_text(
        mode,
        english=(
            f"I can walk you through these workplace policies:\n{bullets}\n\n"
            "Which one do you want to know about?"
        ),
        roman=(
            f"Main in workplace policies par madad kar sakta hoon:\n{bullets}\n\n"
            "Kaunsi wali dekhni hai?"
        ),
        urdu=(
            f"میں ان ورک پلیس پالیسیز میں مدد کر سکتا ہوں:\n{bullets}\n\n"
            "کون سی دیکھنی ہے؟"
        ),
        mix=(
            f"Main in workplace policies par madad kar sakta hoon:\n{bullets}\n\n"
            "Kaunsi wali dekhni hai?"
        ),
    )


def capability_lines(locale=None):
    """The short 'what I can do' list, for welcome and help messages."""
    mode = locale if locale in {"english", "roman", "urdu", "mix"} else "english"
    return pick_locale_text(
        mode,
        english=[
            "Company policy and workplace rules",
            "Your leave balance and history",
            "Applying for leave, withdrawing a request, or cancelling approved leave",
            "Reaching a human from the HR team",
        ],
        roman=[
            "Company policy aur workplace ke rules",
            "Aapki leave balance aur history",
            "Leave apply karna, request wapas lena, ya approved leave cancel karna",
            "HR team ke kisi insaan se baat",
        ],
        urdu=[
            "کمپنی پالیسی اور ورک پلیس کے قواعد",
            "آپ کی چھٹیوں کا بیلنس اور تاریخ",
            "چھٹی کی درخواست، درخواست واپس لینا، یا منظور شدہ لیو منسوخ کرنا",
            "HR ٹیم کے کسی فرد سے رابطہ",
        ],
        mix=[
            "Company policy aur workplace rules",
            "Aapki leave balance aur history",
            "Leave apply, withdraw, ya approved leave cancel karna",
            "HR team se baat",
        ],
    )

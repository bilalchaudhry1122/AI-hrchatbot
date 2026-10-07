import re

from app.routing.roman_urdu import normalize_leave_text

QUOTA_ONLY = re.compile(
    r"\b(quota|check|available|balance|remaining|how many|left|enough|pending|status|"
    r"kitna|kitni|kitne|baqi|baqaya|bachi|mojood|available hai|"
    r"batao|btao|bataiye|bataen|btado|btaye|dikhao|dikhaen|tell me|show me)\b",
    re.I,
)

LEAVE_INFO = re.compile(
    r"\b("
    r"apni (leave|chutti)|meri (leave|chutti|leaves)|my (leave|leaves|chutti)|"
    r"mere (paas|pass|pas) |meray (paas|pass) |"
    r"(leave|chutti) (ka |ki )?(batao|bataiye|bataen|btado|status|detail)|"
    r"tell me about (my )?(leave|chutti)|show (me )?(my )?(leave|balance)|"
    r"leave ka (pata|status|hisab)"
    r")\b",
    re.I,
)

APPLY_OVERRIDE = re.compile(
    r"\b(chahiye|apply|book|request|darkhwast|lena|leni|karni|take leave|want to apply)\b",
    re.I,
)

EXPLICIT_APPLY = re.compile(
    r"\b("
    r"apply(ing)? for|apply for leave|request(ing)? leave|leave request|"
    r"book(ing)? leave|submit(ting)? (a |the )?leave|"
    r"i (?:want|need|wanna)(?:\s+to)?(?:\s+(?:apply\s+for|take|request|book))?(?:\s+(?:a|the|some))?(?:\s+(?:sick|annual|anual|casual))?\s+leave|"
    r"need (a |the )?(sick |annual |casual )?leave|"
    r"take (a |the )?(sick |annual |casual )?leave|"
    r"please (apply|request|book|submit)|please approve|"
    r"chutti chahiye|leave chahiye|chutti karni|leave lena|leave leni|"
    r"mujhe (ek |aik )?(chutti|leave)|"
    r"apply kar(o|na|do)|darkhwast|"
    r"(bimar|salana|casual) chutti chahiye"
    r")\b",
    re.I,
)
CONFIRM_SUBMIT = re.compile(
    r"^(yes|yep|yeah|y|ok|okay|sure|confirm|confirmed|submit|please submit|"
    r"go ahead|do it|han|haan|ji|theek hai|theek|krdo|kar do|karo)$",
    re.I,
)
DENY_SUBMIT = re.compile(
    r"^(no|nope|nah|cancel|don't|dont|not now|no thanks|no thank you|"
    r"nahi|nahin|nahee|mat karo|cancel karo)$",
    re.I,
)
CONFIRM_CLAUSE = re.compile(
    r"\b("
    r"please submit|submit (it|this|to hr)|confirm (it|this|the )?(leave|request)?"
    r"|go ahead|send it to hr|hr ko bhej|bhej do|"
    r"(yes|haan|han)[, ]+(submit|confirm|bhej|kar do|krdo)"
    r")\b",
    re.I,
)
THANKS_TAIL = re.compile(r"\b(thanks|thank you|thx|ty|shukriya|shukria)\b", re.I)
NEGATION_WORD = re.compile(r"\b(nahi|nahin|not|don't|dont|do not|mat|never)\b", re.I)
DISCOURSE_YES = re.compile(
    r"^(yes|yep|yeah|y|ok|okay|sure|han|haan|ji|theek hai)[,!.\s]+",
    re.I,
)
DISCOURSE_NO = re.compile(r"^(no|nope|nah|nahi|nahin)[,!.\s]+", re.I)
BARE_DENY = re.compile(r"^(no|nope|nah|nahi|nahin|nahee)$", re.I)
BARE_AFFIRM = re.compile(
    r"^(yes|yep|yeah|y|ok|okay|sure|han|haan|ji|theek hai|theek)$",
    re.I,
)
CONFIRM_HINT = re.compile(
    r"submit to HR|verify this|nothing is sent to HR|haan likhein|"
    r"awaiting confirm|please verify|HR ko bhej|submit kar",
    re.I,
)
CORRECTION_PREFIX = re.compile(
    r"^(no[,.]?\s+)*(i mean[t]?|matlab|mera matlab|actually)[,:]?\s+",
    re.I,
)
PERSONAL_LEAVE = re.compile(
    r"\b("
    r"my|meri|apni|mera|mere|meray|merey|paas|do i have|i have|remaining|baqi|"
    r"my (quota|balance)|check my|live balance"
    r")\b",
    re.I,
)
COMPANY_LEAVE_POLICY = re.compile(
    r"\b("
    r"allowed|allowance|entitled|entitlement|policy|handbook|"
    r"company|organisation|organization|office|workplace|"
    r"types of leave|leave types|"
    r"how many (?:types of )?leaves? (?:are )?(?:there|allowed|given|provided)(?: in total)?|"
    r"kitn[iae] (?:leaves?|chutti) (?:allowed|milti)|"
    r"chutti (?:kitni |kitne )?(?:allowed|milti)|"
    r"milti hain|company mein|office mein"
    r")\b",
    re.I,
)
WORKPLACE_CLARIFY = re.compile(
    r"\b("
    r"this workplace|this company|this office|our (company|office|workplace)|"
    r"i am talking about|i['’]?m talking about|talking about (this|here)|"
    r"i mean (here|this)|in (the |this )?(company|office|workplace)"
    r")\b",
    re.I,
)
POLICY_FOLLOW_SHORT = re.compile(
    r"^(in total|total|allowed|in (the |this )?(company|office|workplace|policy)|"
    r"for (everyone|all|staff)|company|handbook|entitlement|"
    r"kitni (allowed|milti).+|milti hain.*|yeh workplace.*)$",
    re.I,
)
POLICY_HINT_LOCAL = re.compile(
    r"\b(policy|policies|handbook|entitled|notice period|working hours?|remote work)\b",
    re.I,
)
HANDBOOK_ASK = re.compile(
    r"\b("
    r"polic\w*|handbook|"
    r"company (rule|rules|guideline|guidelines)|"
    r"workplace (rule|rules|policy|policies)|"
    r"know about .{0,40}(company|handbook|polic\w*)|"
    r"what (are|is) (the )?(company )?(polic\w*|handbook|rules)"
    r")\b",
    re.I,
)


DESIRE = re.compile(
    r"\b("
    r"chahiye|want|wanna|need|apply|request|book|take|lena|leni|leni hai|karni|karo|do|"
    r"please|darkhwast|mujhe"
    r")\b",
    re.I,
)
LEAVE_TOPIC = re.compile(
    r"\b("
    r"leave|chutti|vacation|holiday|annual|sick|casual|salana|bimar|"
    r"day off|days off|time off|off day|off days|"
    r"take off|taking off|"
    r"(today|tomorrow|kal|monday|tuesday|wednesday|thursday|friday|saturday|sunday) off|"
    r"off (hai|chahiye|laga)"
    r")\b",
    re.I,
)
ASSET_CONDUCT_POLICY = re.compile(
    r"\b("
    r"freelance|freelancing|"
    r"company (laptop|asset|pc|computer)|"
    r"personal (pc|laptop|computer)|"
    r"warning letter|"
    r"external work|"
    r"asset usage"
    r")\b",
    re.I,
)
LEAVE_REJECT = re.compile(
    r"\b("
    r"nahi chahiye|nahin chahiye|nahi chaiye|"
    r"don't want|dont want|do not want|don't need|dont need|do not need|"
    r"no (need|want|leave|thanks)|not (need|want)(ed)?|"
    r"leave nahi|chutti nahi|nahi (leave|chutti)|"
    r"mat (do|karo)|nahi chahiye (leave|chutti)|"
    r"i don'?t (need|want)"
    r")\b",
    re.I,
)


def strip_correction_prefix(text):
    return CORRECTION_PREFIX.sub("", normalize_leave_text(text).strip()).strip()


def is_asset_conduct_policy_question(text):
    """Freelance, laptop, warning letter: handbook, not a leave form."""
    return bool(ASSET_CONDUCT_POLICY.search(strip_correction_prefix(text)))


def is_company_leave_policy_question(text):
    raw = strip_correction_prefix(text)
    if is_asset_conduct_policy_question(raw):
        return False
    if not raw or not LEAVE_TOPIC.search(raw):
        return False
    personal = bool(PERSONAL_LEAVE.search(raw))
    policy_words = bool(COMPANY_LEAVE_POLICY.search(raw) or POLICY_HINT_LOCAL.search(raw))
    in_org = bool(re.search(r"\bin\s+[a-z]{3,}\b", raw, re.I) and LEAVE_TOPIC.search(raw))
    how_many_company = bool(
        re.search(r"\b(how many|kitna|kitni|kitne)\b", raw, re.I)
        and LEAVE_TOPIC.search(raw)
        and not personal
        and re.search(
            r"\b(allowed|there|total|company|office|workplace|policy|handbook|milti|given|provided)\b",
            raw,
            re.I,
        )
    )
    if personal and not policy_words:
        return False
    if personal and policy_words and re.search(
        r"\b(do i have|remaining|baqi|my |mere |meri |apni |paas)\b",
        raw,
        re.I,
    ):
        return False
    return bool(policy_words or in_org or how_many_company)


def is_company_handbook_question(text):
    """Any company/handbook policy ask — not only leave entitlement wording."""
    raw = strip_correction_prefix(text)
    if not raw:
        return False
    if is_company_leave_policy_question(raw):
        return True
    if is_asset_conduct_policy_question(raw):
        return True
    if PERSONAL_LEAVE.search(raw) and not HANDBOOK_ASK.search(raw):
        return False
    return bool(HANDBOOK_ASK.search(raw))


BROAD_POLICY_CATALOG = re.compile(
    r"^("
    r"(what|which|list|tell me|show( me)?|know).{0,48}(company )?(polic\w*|handbook|rules)|"
    r"(i want to |want to )?(know|learn) about (the )?(company )?(polic\w*|handbook)|"
    r"(company )?(polic\w*|handbook)s?|"
    r"(polic\w*|handbook) (kya|kia|batao|btao|btaye)"
    r")[.!?]*$",
    re.I,
)
SPECIFIC_POLICY_TOPIC = re.compile(
    r"\b("
    r"annual|sick|casual|wfh|work from home|attendance|holiday|holidays|"
    r"confidential|salary|opd|laptop|freelance|working hours|gazetted|appraisal|"
    r"notice period|probation|leave policy|chutti"
    r")\b",
    re.I,
)


def is_broad_policy_catalog_question(text):
    """'What are the policies' — list topics, do not dump every policy."""
    raw = strip_correction_prefix(text)
    if not raw:
        return False
    if is_company_leave_policy_question(raw) or is_asset_conduct_policy_question(raw):
        return False
    if SPECIFIC_POLICY_TOPIC.search(raw):
        return False
    return bool(BROAD_POLICY_CATALOG.match(raw) or (HANDBOOK_ASK.search(raw) and len(raw.split()) <= 8))


POLICY_WORDING = re.compile(
    r"\b(policy|policies|handbook|rules?|procedure|process|wording)\b",
    re.I,
)
ALLOWANCE_ASK = re.compile(
    r"\b(how many|kitna|kitni|kitne|entitled|entitlement|allowance|allowed|milti|in total|quota)\b",
    re.I,
)


def is_company_leave_allowance_question(text):
    """Company 'how many days are allowed' — not 'what is the leave policy'."""
    raw = strip_correction_prefix(text)
    if not is_company_leave_policy_question(raw):
        return False
    if re.search(r"\btypes? of leave\b", raw, re.I):
        return False
    if POLICY_WORDING.search(raw) and not ALLOWANCE_ASK.search(raw):
        return False
    return bool(ALLOWANCE_ASK.search(raw))


def is_workplace_clarification(text):
    raw = str(text or "").strip()
    if not raw or len(raw) > 180:
        return False
    return bool(WORKPLACE_CLARIFY.search(raw))


def last_company_policy_question(history):
    for item in reversed(list(history or [])):
        if str(item.get("role") or "") != "user":
            continue
        text = str(item.get("content") or "").strip()
        if not text or is_workplace_clarification(text):
            continue
        if is_company_leave_policy_question(text):
            return text
    return ""


def is_policy_conversation_followup(text, history=None):
    raw = str(text or "").strip()
    if not raw:
        return False
    if not last_company_policy_question(history):
        return False
    if is_workplace_clarification(raw):
        return True
    if is_company_leave_policy_question(raw):
        return True
    if len(raw) <= 80 and POLICY_FOLLOW_SHORT.match(raw):
        return True
    return False


def is_leave_info_question(text):
    raw = normalize_leave_text(text)
    if not LEAVE_TOPIC.search(raw):
        return False
    if APPLY_OVERRIDE.search(raw):
        return False
    if is_cancel_approved_leave(raw):
        return False
    if LEAVE_INFO.search(raw):
        return True
    if QUOTA_ONLY.search(raw) and re.search(r"\b(apni|meri|mera|mere|my)\b", raw, re.I):
        return True
    return False


def is_quota_or_status_question(text):
    raw = normalize_leave_text(text)
    if is_company_leave_policy_question(raw):
        return False
    if is_leave_info_question(raw):
        return True
    if not LEAVE_TOPIC.search(raw):
        return False
    if not QUOTA_ONLY.search(raw):
        return False
    if re.search(r"\b(quota|check|remaining|balance|how many|kitna|kitni|kitne|baqi|batao|tell me|show me)\b", raw, re.I):
        return True
    if DESIRE.search(raw):
        return False
    return True


def is_reject_leave(text):
    raw = normalize_leave_text(text)
    return bool(LEAVE_REJECT.search(raw))


def is_leave_desire(text):
    raw = normalize_leave_text(text).strip()
    if not raw or is_reject_leave(raw) or is_quota_or_status_question(raw):
        return False
    if re.search(r"\brec[a-zA-Z0-9]{10,}\b", raw) and re.search(r"\bthis leave\b", raw, re.I):
        return False
    if not LEAVE_TOPIC.search(raw):
        return False
    if is_leave_info_question(raw):
        return False
    if DESIRE.search(raw) or EXPLICIT_APPLY.search(raw):
        return True
    return False


def is_explicit_leave_apply(text):
    raw = normalize_leave_text(text).strip()
    if not raw or is_quota_or_status_question(raw) or is_reject_leave(raw) or is_cancel_submit(raw):
        return False
    if is_cancel_approved_leave(raw):
        return False
    return bool(EXPLICIT_APPLY.search(raw) or is_leave_desire(raw))


def _bare_utterance(text):
    return re.sub(r"[.!?]+$", "", normalize_leave_text(text).strip()).strip()


def is_confirm_submit(text):
    raw = _bare_utterance(text)
    if not raw:
        return False
    if is_refuse_withdraw(raw) or is_reject_leave(raw):
        return False
    if THANKS_TAIL.search(raw) and not CONFIRM_CLAUSE.search(raw):
        return False
    if CONFIRM_SUBMIT.match(raw):
        return True
    if CONFIRM_CLAUSE.search(raw) and not NEGATION_WORD.search(raw):
        return True
    if DISCOURSE_YES.match(raw):
        return False
    return False


def is_bare_deny(text):
    return bool(BARE_DENY.match(_bare_utterance(text)))


def is_bare_affirm(text):
    return bool(BARE_AFFIRM.match(_bare_utterance(text)))


def is_explicit_form_cancel(text):
    raw = normalize_leave_text(text).strip()
    bare = _bare_utterance(raw)
    if is_reject_leave(raw):
        return True
    if re.fullmatch(r"(cancel|mat karo|cancel karo|not now)", bare, re.I):
        return True
    return bool(re.search(
        r"\b(cancel (the |this |my )?(leave|request|form|application)|cancel karo)\b",
        raw,
        re.I,
    ))


def last_bot_asked_leave_confirm(history):
    for item in reversed(list(history or [])):
        if str(item.get("role") or "") != "assistant":
            continue
        return bool(CONFIRM_HINT.search(str(item.get("content") or "")))
    return False


def should_cancel_leave_form(text, draft=None, history=None):
    draft = draft or {}
    form_open = bool(draft.get("awaiting_details") or draft.get("awaiting_confirm"))
    if not form_open:
        return False
    if is_explicit_form_cancel(text):
        return True
    if is_bare_deny(text):
        return bool(draft.get("awaiting_confirm") or last_bot_asked_leave_confirm(history))
    return False


def should_confirm_leave_form(text, draft=None, history=None):
    draft = draft or {}
    if not is_confirm_submit(text):
        return False
    if draft.get("awaiting_confirm") or last_bot_asked_leave_confirm(history):
        return True
    return False


def is_cancel_submit(text):
    raw = normalize_leave_text(text).strip()
    bare = _bare_utterance(raw)
    if not bare:
        return False
    if is_refuse_withdraw(bare):
        return False
    if is_company_leave_policy_question(raw) or is_quota_or_status_question(raw):
        return False
    if CORRECTION_PREFIX.search(raw) and len(raw.split()) > 3:
        return False
    if DISCOURSE_NO.match(bare) and not is_reject_leave(bare) and not DENY_SUBMIT.match(bare):
        rest = DISCOURSE_NO.sub("", bare).strip()
        if rest and not re.search(r"\b(cancel|mat karo|don't want|dont want|nahi chahiye)\b", rest, re.I):
            return False
    if is_reject_leave(raw):
        return True
    if DENY_SUBMIT.match(bare):
        return True
    return bool(re.search(
        r"\b(cancel (the |this |my )?(leave|request|form|application)|cancel karo)\b",
        raw,
        re.I,
    ))


def is_refuse_withdraw(text):
    raw = normalize_leave_text(text).strip()
    if not raw or len(raw) > 160:
        return False
    if not re.search(r"\b(withdraw|withdrawn|wapis|wapas)\b", raw, re.I):
        return False
    return bool(re.search(
        r"\b("
        r"don'?t withdraw|do not withdraw|not withdrawing|"
        r"i don'?t want to withdraw|dont want to withdraw|"
        r"withdraw (mat|nahi)|nahi withdraw|"
        r"(nahi|mat) .{0,50}withdraw|"
        r"withdraw .{0,24}(nahi|mat) (karna|karo|karni|karne|do)?"
        r"|mujhe withdraw nahi|withdraw nahi karna|"
        r"wapis (nahi|mat)|wapas (nahi|mat)"
        r")\b",
        raw,
        re.I,
    ))


def is_cancel_approved_leave(text):
    """Booked/approved leave, not withdrawing a pending card or closing the apply form."""
    raw = normalize_leave_text(text).strip()
    if not raw or is_refuse_withdraw(raw) or is_company_leave_policy_question(raw):
        return False
    if raw.endswith("?") and re.search(r"\b(how|what|what's|whats|which|policy)\b", raw, re.I):
        return False
    return bool(re.search(
        r"\b("
        r"i want to cancel( my leave)?|"
        r"want to cancel my leave|"
        r"please cancel my leave|"
        r"cancel my leave|cancel the leave|"
        r"leave cancel( karo| kardo| krdo| krni| karna| karni)?|"
        r"chutti cancel|"
        r"cancel krdo|cancel kardo|cancel krni hai|"
        r"(mujhe|mujhai|mujhy) .{0,40}(leave|chutti) cancel|"
        r"(leave|chutti) .{0,20}cancel (krdo|kardo|karo|krni|karna)"
        r")\b",
        raw,
        re.I,
    ))


def recent_question_should_not_withdraw(text):
    """A policy or info question is not a withdraw, even if Withdraw was tapped."""
    raw = normalize_leave_text(text).strip()
    if not raw or is_withdraw_leave(raw):
        return False
    if is_company_leave_policy_question(raw) or is_company_leave_allowance_question(raw):
        return True
    if is_quota_or_status_question(raw):
        return True
    if raw.endswith("?") or re.search(
        r"\b(what|what's|whats|why|how|which|policy|handbook|entitlement)\b",
        raw,
        re.I,
    ):
        return True
    return False


def is_withdraw_leave(text):
    raw = normalize_leave_text(text).strip()
    if not raw or len(raw) > 120:
        return False
    if is_refuse_withdraw(raw):
        return False
    if is_company_leave_policy_question(raw) or is_company_leave_allowance_question(raw):
        return False
    if is_quota_or_status_question(raw) and not re.search(
        r"\b(withdraw|withdrawn|wapas|wapis|cancel)\b", raw, re.I
    ):
        return False
    asking = bool(re.search(
        r"\b(what|what's|whats|why|how|which|who|where|when|policy|handbook|entitlement)\b",
        raw,
        re.I,
    )) or raw.endswith("?")
    if asking and not re.search(
        r"\b(withdraw|withdrawn|wapas|wapis)\b",
        raw,
        re.I,
    ):
        return False
    return bool(re.search(
        r"\b(withdraw|withdrawn|take it back|take back)\b|"
        r"\b(leave (request |application )?wapis|leave (request |application )?wapas)\b|"
        r"\b(wapis le|wapas le|wapis kar|wapas kar|darkhwast wapas)\b|"
        r"^(wapis|wapas|withdraw)\b",
        raw,
        re.I,
    ))


INTAKE_ASK = re.compile(
    r"which leave|kaunsi leave|how many days|kitne din|which date|date kya hai|"
    r"from which date|kab se kab tak|until which|haan likhein|"
    r"verify this|HR ko bhejne|I will not send this to HR|"
    r"select a leave type|fill form|add the reason|"
    r"complete the form|reason for leave",
    re.I,
)


INTAKE_CLOSED = re.compile(
    r"cancel(led)?|cancel ho gaya|no leave request was sent|koi leave request nahi|"
    r"leave request submitted|your live leave balance|here is your live leave balance|"
    r"awaiting hr approval|hr approval required|withdrawn|was withdrawn",
    re.I,
)

LEAVE_FORM_QUESTION = re.compile(
    r"\b("
    r"what is|what's|whats|why|how|who|where|when|which|"
    r"kya hai|kyun|kaise|remember|last message|policy|handbook|"
    r"namespace|knowledge"
    r")\b|\?",
    re.I,
)


def in_leave_intake(conversation_history):
    open_intake = False
    for item in list(conversation_history or [])[-12:]:
        content = str(item.get("content") or "")
        role = item.get("role")
        if role == "assistant" and INTAKE_ASK.search(content):
            open_intake = True
        if role == "assistant" and INTAKE_CLOSED.search(content):
            open_intake = False
        if role == "user" and is_cancel_submit(content):
            open_intake = False
        if role == "user" and is_explicit_leave_apply(content):
            open_intake = True
    return open_intake


def looks_like_leave_form_reply(text, draft=None):
    raw = str(text or "").strip()
    if not raw:
        return False
    if is_explicit_leave_apply(raw):
        return True
    if should_cancel_leave_form(raw, draft) or should_confirm_leave_form(raw, draft):
        return True
    if is_explicit_form_cancel(raw):
        return True
    if is_bare_deny(raw) or is_bare_affirm(raw):
        return False
    if is_confirm_submit(raw) or is_cancel_submit(raw):
        return True
    if is_company_leave_policy_question(raw) or is_workplace_clarification(raw):
        return False
    if LEAVE_FORM_QUESTION.search(raw) and not is_explicit_leave_apply(raw):
        return False
    from app.agent.extraction import infer_leave_type
    from app.hr.dates import parse_day_count, resolve_date_phrase, resolve_date_range

    if infer_leave_type(raw) and len(raw.split()) <= 8:
        return True
    if parse_day_count(raw):
        return True
    start, end = resolve_date_range(raw)
    if start and end:
        return True
    if resolve_date_phrase(raw) and len(raw) <= 40:
        return True
    draft = draft or {}
    if draft.get("awaiting_confirm"):
        return False
    if draft.get("awaiting_details") and (draft.get("start_date") or draft.get("leave_type")):
        if len(raw) <= 400 and not is_quota_or_status_question(raw):
            return True
    return False


def is_new_leave_start(text):
    if is_confirm_submit(text) or is_cancel_submit(text) or is_quota_or_status_question(text):
        return False
    return is_explicit_leave_apply(text)

"""WebAiry intent router (training pack). Classifier only — does not answer or write."""

import re

from app.agent.verification import (
    in_leave_intake,
    is_asset_conduct_policy_question,
    is_company_leave_policy_question,
    is_confirm_submit,
    is_explicit_leave_apply,
    is_leave_info_question,
    is_policy_conversation_followup,
    is_quota_or_status_question,
    is_reject_leave,
    is_withdraw_leave,
    looks_like_leave_form_reply,
)
from app.routing.roman_urdu import normalize_leave_text
from app.sessions.followup import is_session_followup, last_knowledge_question

CLARIFY_QUESTION = (
    "Do you want to check the leave policy, check your leave record, or apply/change a leave?"
)
CLARIFY_QUESTION_ROMAN = (
    "Aap leave policy dekhna chahte hain, apni leave record, ya leave apply/change karna chahte hain?"
)

SMALL_TALK = re.compile(
    r"^(hey bot|ok thanks bro|thanks bro|hello|hi+|hey+|salam|salaam|shukriya|shukria|"
    r"thanks|thank you|thx|ty|who are you|who r u)\b",
    re.I,
)
IDENTITY = re.compile(r"\b(who are you|who r u|tum kaun ho|aap kaun ho)\b", re.I)

NEGATE_WRITE = re.compile(
    r"\b("
    r"don'?t apply|do not apply|not asking to apply|apply mat|mat krna|mat karna|"
    r"chutti mat lagana|leave mat lagana|apply mat krna|sirf policy|just tell me the|"
    r"not my balance|personal record ki nahi|general leave rules|"
    r"i don'?t want to apply|don't want to apply|don'?t want to apply anything|"
    r"meri chutti mat lagana"
    r")\b",
    re.I,
)
HYPOTHETICAL = re.compile(
    r"\b("
    r"if i (need|take|want)|as per policy|what should i do|"
    r"agar .{0,40}(leave|chutti) (loon|lun|len)|"
    r"can employees|what is the process|how does .{0,40} work|"
    r"eligible for|during probation as per|"
    r"if hr rejects|if electricity|half-day wfh"
    r")\b",
    re.I,
)
ATTENDANCE_WRITE = re.compile(
    r"\b(change my attendance|attendance to present|approve (my )?wfh|wfh approve|"
    r"wfh karwa|wfh kar do mera)\b",
    re.I,
)
LIVE_ATTENDANCE = re.compile(
    r"\b("
    r"my attendance|meri attendance|attendance dikhao|attendance record|"
    r"show .{0,24}attendance|attendance (this|for) (month|week|today|yesterday)|"
    r"check[- ]?in|punches?|was i present"
    r")\b",
    re.I,
)
LIVE_PAY = re.compile(
    r"\b("
    r"(my |meri |mera )?(current )?salary|"
    r"meri salary|mera appraisal|appraisal (rating|score)|"
    r"what appraisal"
    r")\b",
    re.I,
)
PAY_POLICY = re.compile(
    r"\b("
    r"share|shared|allowed|confidential|coworkers?|hota hai|policy|information be|"
    r"tell|disclose|discuss|anyone|anybody|other employee|kisi ko|kisi se"
    r")\b",
    re.I,
)
SALARY_DISCLOSE = re.compile(
    r"\b("
    r"(tell|share|disclose|discuss).{0,80}(salary|personal data|confidential)|"
    r"(salary|personal data).{0,80}(tell|share|disclose|anyone|anybody|coworker|employee|kisi)|"
    r"can i tell (my |the )?(salary|personal)|"
    r"salary (kisi ko|bata|batao|btana)"
    r")\b",
    re.I,
)
WFH_POLICY = re.compile(
    r"\b("
    r"wfh (ka )?(rule|policy|procedure|process)|work from home|"
    r"barish ho to wfh|can we work from home|wfh mil sakta|"
    r"wfh lene ka|\bwfh\b.{0,40}(rule|process|instead|rain|eligible)"
    r")\b",
    re.I,
)
WRITE_CREATE = re.compile(
    r"\b("
    r"apply(ing)? (for )?(leave|annual|sick|casual|it)|apply kar ?do|apply karo|"
    r"laga do|laga dena|lga do|daal do|book(ing)? (my )?(annual |sick |casual )?leave|put me on leave|"
    r"put in a leave|submit( it)? as annual|submit annual|request sick leave|"
    r"leave request bana|chutti laga|leave laga|off laga|"
    r"i need leave|i need annual leave|i want you to apply|please put me on leave|"
    r"won'?t be available.{0,20}leave|emergency.{0,30}(apply|laga)|"
    r"nahi aa paunga|office nahi aa sakta.{0,40}leave|"
    r"please apply it|apply it for|leave chahiye|chutti chahiye|apply leave|"
    r"i (want|need) (a |the |some )?(sick |annual |casual )?leave|"
    r"open (the |a )?form|fill (the |a )?form"
    r")\b",
    re.I,
)
WRITE_CANCEL = re.compile(
    r"\b("
    r"cancel (my )?(leave|request|chutti)|withdraw (my )?(pending )?leave|"
    r"leave cancel|chutti cancel|hata do|wapis le lo|remove my leave|chutti hata"
    r")\b",
    re.I,
)
WRITE_MODIFY = re.compile(
    r"\b("
    r"change my leave|move my leave|move my .{0,40}request|extend my leave|barha do|"
    r"friday se monday|jagah .{0,20} (ki )?leave|shift kar|"
    r"ki jagah .{0,20}leave"
    r")\b",
    re.I,
)
READ_BALANCE = re.compile(
    r"\b("
    r"do i have (left|enough|remaining)|how many .{0,24}(do i have|have i|i have left|\bi have\b)|"
    r"my (leave )?balance|remaining leave|leaves? (do i|have i) |"
    r"meri (kitni |annual )?.*(bachi|baki|baqi|balance)|"
    r"mera leave balance|maine kitni chutti use|how many sick leaves have i|"
    r"enough leave remaining|3 din ki leave ke liye balance|"
    r"apni leave|my remaining leaves|meri apni leave|"
    r"left in my account|how many do i have left|"
    r"kitni (leave|chutti) (hain|hai)|"
    r"(mere|meri) paas kitni|"
    r"what('?s| is) my leave"
    r")\b",
    re.I,
)
READ_STATUS = re.compile(
    r"\b("
    r"is my (leave|friday).{0,20}approved|leave (for friday )?approved|"
    r"pending leave|leave request kahan|request dali thi|"
    r"already have leave booked|leave lagi hui|approve hui|"
    r"under my name|pending pari|reject hui ya approve|"
    r"what happened to my leave request|"
    r"did hr reject the leave|leave i requested|"
    r"friday leave is approved|wali leave approve|leave approve\??$"
    r")\b",
    re.I,
)
READ_HISTORY = re.compile(
    r"\b("
    r"leave history|purani leaves|last (approved )?leave|"
    r"when was my last approved|approved chuttiyan kitni|"
    r"how many days did i take off as approved|"
    r"approved leave this year"
    r")\b",
    re.I,
)
PERSONAL = re.compile(r"\b(my|meri|mera|mere|meray|apni|paas|i have left|do i have)\b", re.I)
HOLIDAY_Q = re.compile(
    r"\b("
    r"is (tomorrow|today|kal|monday|tuesday|wednesday|thursday|friday|saturday|sunday|eid) a (company )?(holiday|working day|work day)|"
    r"(kal|tomorrow|tmrw) (chutti|holiday) hai|"
    r"kal chutti hai|office band hai|gazetted|public holiday|"
    r"kal public holiday|sunday ko holiday|replacement holiday|"
    r"taking a public holiday|is friday a holiday|"
    r"holiday hai|working day"
    r")\b",
    re.I,
)
POLICY_Q = re.compile(
    r"\b("
    r"polic\w*|handbook|rule|rules|procedure|process|entitled|allowance|"
    r"company (allow|provide|give)|does the company|"
    r"kitni milti|leave kitni milti|ka rule|ka scene|"
    r"working hours|office timing|opd|confidential|"
    r"company laptop|freelance|carry[- ]forward|gazetted|"
    r"planned leave|unapproved absence|probation|"
    r"absent without|informing hr|how often are performance|"
    r"leave lene se pehle|general leave|general rule|"
    r"same as a gazetted|reduce my leave balance|"
    r"working day|work day|office (open|closed|band)"
    r")\b",
    re.I,
)
AMBIGUOUS = re.compile(
    r"^("
    r"leave tomorrow\??|can i have leave tomorrow\??|can i take tomorrow off\??|"
    r"i was thinking about leave.{0,40}|what about my leave\??|"
    r"kal leave\??|kal chutti chahiye kya scene hai|"
    r"friday off\??|meri leave ka kya\??|chutti|leave please|"
    r"monday ka dekh lo|can you do something about friday\??|"
    r"could you sort out my leave.{0,40}|i may need friday off|"
    r"mere friday ka kuch karna hai.{0,30}|kal off ka kya karen\??"
    r")[.!?]*$",
    re.I,
)
MIXED_POLICY_BALANCE = re.compile(
    r"\b(policy|rule|allowed generally|how many .{0,40}allowed).{0,100}\b(i have|meri |do i have|bachi|left in my|are left|have left|personally have)\b|"
    r"\b(meri kitni|how many .{0,20}i have).{0,80}\b(policy|rule)\b",
    re.I,
)

TYPOS = (
    (re.compile(r"\blv\b", re.I), "leave"),
    (re.compile(r"\bappy\b", re.I), "apply"),
    (re.compile(r"\btmrw\b", re.I), "tomorrow"),
    (re.compile(r"\bmri\b", re.I), "meri"),
    (re.compile(r"\bkl\b", re.I), "kal"),
    (re.compile(r"\bfri\b", re.I), "friday"),
    (re.compile(r"\bchuti\b", re.I), "chutti"),
    (re.compile(r"\bchhutti\b", re.I), "chutti"),
    (re.compile(r"\bbchi\b", re.I), "bachi"),
    (re.compile(r"\bkrdo\b", re.I), "kar do"),
    (re.compile(r"\blga\b", re.I), "laga"),
    (re.compile(r"\baj\b", re.I), "aaj"),
)


def _norm(text):
    raw = normalize_leave_text(text).strip()
    for pattern, repl in TYPOS:
        raw = pattern.sub(repl, raw)
    return raw


def _prior_blob(history):
    return " ".join(str(item.get("content") or "") for item in (history or [])[-8:])


def _last_user(history):
    for item in reversed(list(history or [])):
        if str(item.get("role") or "") == "user":
            return str(item.get("content") or "")
    return ""


def _route(intent, sub_intent=None, confidence=0.9, clarify=None):
    needs = intent == "CLARIFY"
    return {
        "intent": intent,
        "sub_intent": sub_intent,
        "confidence": confidence,
        "needs_clarification": needs,
        "clarification_question": clarify if needs else None,
    }


def _holiday_knowledge(raw):
    return bool(
        HOLIDAY_Q.search(raw)
        or re.search(r"\b(public holiday|gazetted|replacement holiday|office band)\b", raw, re.I)
        or re.search(r"taking a public holiday|holiday reduce", raw, re.I)
    )


def classify_webairy(text, conversation_history=None):
    history = conversation_history or []
    raw = _norm(text)
    if not raw:
        return _route("SMALL_TALK", "empty", 0.5)
    prior = _prior_blob(history)

    if SMALL_TALK.match(raw) or IDENTITY.search(raw):
        sub = "identity" if IDENTITY.search(raw) else ("thanks" if re.search(r"thank|shukri", raw, re.I) else "greeting")
        return _route("SMALL_TALK", sub, 0.95)

    applying = (WRITE_CREATE.search(raw) or is_explicit_leave_apply(raw)) and not NEGATE_WRITE.search(raw)
    if applying and is_quota_or_status_question(raw):
        applying = False

    if not applying and is_session_followup(raw) and last_knowledge_question(history):
        return _route("RAG_KNOWLEDGE", "session_followup", 0.86)

    if ATTENDANCE_WRITE.search(raw):
        return _route("HUMAN_HR", "unsupported_non_leave_action", 0.9)
    if SALARY_DISCLOSE.search(raw) and not re.search(
        r"\b(what is my|current salary|kitni hai|kitna hai)\b", raw, re.I
    ):
        return _route("RAG_KNOWLEDGE", "confidentiality_policy", 0.93)
    if LIVE_PAY.search(raw) and not PAY_POLICY.search(raw) and not re.search(r"\b(leave|chutti|handbook)\b", raw, re.I):
        return _route("HUMAN_HR", "live_non_leave_data", 0.9)
    if LIVE_ATTENDANCE.search(raw) and re.search(r"\b(polic\w*|handbook|rule|rules)\b", raw, re.I):
        return _route("RAG_KNOWLEDGE", "attendance_policy", 0.93)
    if LIVE_ATTENDANCE.search(raw) and not re.search(r"\b(leave|chutti|polic\w*|handbook)\b", raw, re.I):
        return _route("HUMAN_HR", "live_non_leave_data", 0.9)

    if (
        NEGATE_WRITE.search(raw)
        and not WRITE_CREATE.search(raw)
        and re.search(r"\b(leave|chutti|rule|allowed|policy|emergency)\b", raw, re.I)
    ):
        return _route("RAG_KNOWLEDGE", "leave_policy", 0.93)

    if is_asset_conduct_policy_question(raw):
        return _route("RAG_KNOWLEDGE", "asset_policy", 0.94)

    if in_leave_intake(history) and looks_like_leave_form_reply(raw) and not is_company_leave_policy_question(raw) and not is_asset_conduct_policy_question(raw):
        return _route("LEAVE_WRITE", "create", 0.85)
    if is_confirm_submit(raw) and in_leave_intake(history):
        return _route("LEAVE_WRITE", "create", 0.85)

    if AMBIGUOUS.match(raw):
        sub = "read_or_write" if re.search(r"\b(my leave|meri leave)\b", raw, re.I) else "policy_or_request"
        if re.search(r"dekh lo|something about friday", raw, re.I):
            sub = "insufficient_context"
        return _route("CLARIFY", sub, 0.7, CLARIFY_QUESTION)

    reject_policy_talk = bool(re.search(
        r"\b("
        r"not asking about policy|i know the policy|policy nahi chahiye|"
        r"policy mat batao|just want my|i just want my"
        r")\b",
        raw,
        re.I,
    ))
    if reject_policy_talk and WRITE_CREATE.search(raw):
        return _route("LEAVE_WRITE", "create", 0.92)
    if reject_policy_talk and (READ_BALANCE.search(raw) or is_leave_info_question(raw) or PERSONAL.search(raw)):
        return _route("LEAVE_READ", "balance", 0.92)

    if _holiday_knowledge(raw) and re.search(r"\b(reduce|count as|same as)\b", raw, re.I) and not WRITE_CREATE.search(raw):
        return _route("RAG_KNOWLEDGE", "holiday_policy", 0.9)

    if WRITE_CREATE.search(raw) and re.search(
        r"\b(quota|leave balance|remaining leave|how many|kitni baqi|check my|avalaible|is it available)\b",
        raw,
        re.I,
    ) and not reject_policy_talk:
        return _route("LEAVE_READ", "balance", 0.9)

    mixed_create = bool(
        (
            _holiday_knowledge(raw)
            or WFH_POLICY.search(raw)
            or POLICY_Q.search(raw)
            or re.search(r"\bhow does .{0,40} leave\b", raw, re.I)
            or re.search(r"\b(working day|work day|office (open|closed|band))\b", raw, re.I)
        )
        and WRITE_CREATE.search(raw)
    )
    mixed_balance = bool(
        MIXED_POLICY_BALANCE.search(raw)
        or (
            (POLICY_Q.search(raw) or is_company_leave_policy_question(raw))
            and (READ_BALANCE.search(raw) or is_leave_info_question(raw) or re.search(r"\b(do i have|meri kitni|left in my|are left)\b", raw, re.I))
        )
    )
    mixed_status = bool(
        (POLICY_Q.search(raw) or re.search(r"\bgeneral rule\b", raw, re.I) or _holiday_knowledge(raw))
        and READ_STATUS.search(raw)
    )
    if mixed_create:
        sub = "holiday_plus_create" if _holiday_knowledge(raw) else ("wfh_plus_create" if WFH_POLICY.search(raw) else "policy_plus_create")
        return _route("MIXED", sub, 0.88)
    if mixed_status:
        sub = "holiday_plus_status" if _holiday_knowledge(raw) else "policy_plus_status"
        return _route("MIXED", sub, 0.88)
    if mixed_balance:
        return _route("MIXED", "policy_plus_balance", 0.9)

    ctx_write = False
    if re.search(r"\b(laga do|leave laga|cancel kar do|hata do)\b", raw, re.I):
        if re.search(r"holiday|chutti hai|pending|which leave type|provide a reason", prior, re.I):
            ctx_write = True
    if re.fullmatch(r"annual|sick|casual", raw, re.I) and re.search(r"which leave|leave type", prior, re.I):
        ctx_write = True
    if len(raw.split()) <= 4 and re.search(r"reason for leave|provide a reason", prior, re.I):
        ctx_write = True

    if WRITE_CANCEL.search(raw) or (re.fullmatch(r"cancel kar do", raw, re.I) and re.search(r"leave|pending|chutti", prior, re.I)):
        if not is_company_leave_policy_question(raw) and not POLICY_Q.search(raw):
            return _route("LEAVE_WRITE", "cancel", 0.94)
    if WRITE_MODIFY.search(raw):
        return _route("LEAVE_WRITE", "modify", 0.9)
    if WRITE_CREATE.search(raw) or ctx_write:
        if not NEGATE_WRITE.search(raw):
            return _route("LEAVE_WRITE", "create", 0.92)

    if HYPOTHETICAL.search(raw) and not WRITE_CREATE.search(raw):
        sub = "wfh_policy" if WFH_POLICY.search(raw) or re.search(r"\bwfh\b", raw, re.I) else "leave_policy"
        return _route("RAG_KNOWLEDGE", sub, 0.9)

    if READ_HISTORY.search(raw):
        return _route("LEAVE_READ", "history", 0.9)
    if READ_STATUS.search(raw):
        return _route("LEAVE_READ", "status", 0.9)
    if READ_BALANCE.search(raw) or is_leave_info_question(raw):
        return _route("LEAVE_READ", "balance", 0.92)
    if PERSONAL.search(raw) and is_quota_or_status_question(raw):
        return _route("LEAVE_READ", "balance", 0.9)
    if re.search(r"\bhow many do i have left\b", raw, re.I):
        return _route("LEAVE_READ", "balance", 0.9)
    if is_quota_or_status_question(raw) and not is_company_leave_policy_question(raw) and PERSONAL.search(raw):
        return _route("LEAVE_READ", "balance", 0.88)
    if is_quota_or_status_question(raw) and not is_company_leave_policy_question(raw) and re.search(
        r"\b((chutti|leave) kitni|kitni (chutti|leave))\b", raw, re.I
    ):
        return _route("LEAVE_READ", "balance", 0.8)

    if not applying and is_policy_conversation_followup(raw, history):
        return _route("RAG_KNOWLEDGE", "leave_policy", 0.86)
    if _holiday_knowledge(raw) or (
        re.search(r"\bwhat about friday\b", raw, re.I) and re.search(r"holiday", prior, re.I)
    ):
        return _route("RAG_KNOWLEDGE", "holiday_policy", 0.9)
    if WFH_POLICY.search(raw) or re.search(r"\bhalf-day wfh|electricity is down\b", raw, re.I):
        return _route("RAG_KNOWLEDGE", "wfh_policy", 0.9)
    if is_company_leave_policy_question(raw) or POLICY_Q.search(raw):
        sub = "leave_policy"
        if re.search(r"\b(opd|dental|glasses)\b", raw, re.I):
            sub = "opd_policy"
        elif re.search(r"\b(timing|working hours|ghantay)\b", raw, re.I):
            sub = "working_hours"
        elif re.search(r"\b(laptop|freelance|asset)\b", raw, re.I):
            sub = "asset_policy"
        elif re.search(r"\b(salary info|confidential)\b", raw, re.I):
            sub = "confidentiality_policy"
        elif re.search(r"\bappraisal\b", raw, re.I) and not PERSONAL.search(raw):
            sub = "appraisal_policy"
        elif re.search(r"\b(holiday|gazetted|eid|office band|absent without)\b", raw, re.I):
            sub = "holiday_policy" if re.search(r"holiday|gazetted|eid", raw, re.I) else "attendance_policy"
        elif re.search(r"\babsent\b", raw, re.I):
            sub = "attendance_policy"
        return _route("RAG_KNOWLEDGE", sub, 0.9)
    if re.search(r"\b(carry[- ]forward|company rule for carrying)\b", raw, re.I):
        return _route("RAG_KNOWLEDGE", "leave_policy", 0.88)
    if re.search(r"\bgeneral rule bhi batao|leave ka general rule\b", raw, re.I):
        return _route("RAG_KNOWLEDGE", "leave_policy", 0.88)

    if is_withdraw_leave(raw):
        return _route("LEAVE_WRITE", "cancel", 0.9)
    if is_reject_leave(raw):
        return _route("CLARIFY", "policy_or_request", 0.6, CLARIFY_QUESTION)

    return _route("RAG_KNOWLEDGE", None, 0.55)


LEGACY = {
    "RAG_KNOWLEDGE": "POLICY",
    "LEAVE_READ": "LEAVE_BALANCE",
    "LEAVE_WRITE": "LEAVE_REQUEST",
    "MIXED": "MIXED",
    "HUMAN_HR": "HUMAN_HR",
    "CLARIFY": "CLARIFY",
    "SMALL_TALK": "SMALL_TALK",
}


def to_legacy_intent(route):
    intent = (route or {}).get("intent")
    return LEGACY.get(intent, "GENERAL")

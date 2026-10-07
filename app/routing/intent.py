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
    looks_like_leave_form_reply,
)
from app.routing.language import detect_reply_language, pick_locale_text
from app.routing.webairy import classify_webairy, to_legacy_intent
from app.routing.roman_urdu import normalize_leave_text, prefer_roman

ABOUT_BOT_PHRASES = re.compile(
    r"tell me about (yourself|you)|introduce yourself|are you (a |an )?(bot|ai|assistant|robot)|"
    r"do you speak|can you speak|answer in |what languages|which languages|"
    r"who (?:made|built|created) you|tum kaun ho|tu kaun ho|aap kaun|ap kaun ho|tum kya ho|"
    r"kahan ho|kahan hai|kyun ho|kia kam|kya kam|qui[eé]n eres|que puedes hacer|qui es[- ]tu|"
    r"qui [eê]tes-vous|من أنت|من انت|أين أنت|اين انت|عرف نفسك",
    re.I,
)
W_QUESTION = re.compile(r"\b(who|what|where|when|why|which|whom|whose|how)\b", re.I)
PLACE_HINT = re.compile(
    r"\b("
    r"this server|this channel|this ticket|the server|yeh? server|yeh? channel|"
    r"channel'?s knowledge|this channel'?s knowledge|knowledge (here|base)|"
    r"what (do you|can you) (do|help|answer)|what are you (for|here for)|"
    r"aap kya (karte|kar sakt)|ye server kya|server kya hai"
    r")\b",
    re.I,
)
ASKER_HINT = re.compile(
    r"\b("
    r"what('?s| is) my name|who am i|what('?s| is) my username|"
    r"mera naam|mera name|main kaun hoon|main kon hoon"
    r")\b",
    re.I,
)
ABOUT_YOU = re.compile(
    r"\b(you|your|yourself|u\b|ur\b|this bot|the bot|this assistant|support assistant)\b",
    re.I,
)
KNOWLEDGE_TOPIC = re.compile(
    r"\b(policy|policies|refund|handbook|salary|leave|hr|invoice|price|pricing|password|"
    r"account|document|file|rule|rules|conduct|employee|investigation|panel|login|benefit|"
    r"vacation|holiday|office hours?)\b",
    re.I,
)

POLICY_HINT = re.compile(r"\b(policy|policies|handbook|entitled|notice period|working hours?|remote work)\b", re.I)
BALANCE_HINT = re.compile(
    r"\b(how many|remaining|balance|left|do i have enough|available|pending|leave status|my leaves?|"
    r"apni (leave|chutti)|meri (leave|chutti)|kitna|kitni|kitne|baqi|baqaya|"
    r"batao|bataiye|tell me about)\b",
    re.I,
)
QUOTA_HINT = re.compile(
    r"\b(quota|check|available|balance|remaining|how many|left|enough|kitna|kitni|kitne|baqi)\b",
    re.I,
)
LEAVE_TYPE_HINT = re.compile(r"\b(annual|sick|casual|salana|saalana|bimar|bimari)\b", re.I)
ATTENDANCE_HINT = re.compile(r"\b(attendance|present|late|absent|check[- ]?in|was i)\b", re.I)
LEAVE_REQUEST_HINT = re.compile(
    r"\b(i need|i want|apply for|request|take|book)\b.*\b(leave|off|vacation|holiday)\b|"
    r"\b(leave|vacation|holiday)\b.*\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next)\b|"
    r"\b(chutti|leave) chahiye\b|"
    r"\bapply kar(o|na|do)\b|"
    r"\bdarkhwast\b",
    re.I,
)
LEAVE_DETAIL_HINT = re.compile(
    r"\b(annual|sick|casual|salana|saalana|bimar|bimari|"
    r"today|tomorrow|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"aaj|kal|parson|din|days?|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|november|december|"
    r"20\d{2}-\d{2}-\d{2})\b|"
    r"\b\d{1,2}(?:st|nd|rd|th)?\b|"
    r"\b(to|till|until|se)\b",
    re.I,
)
HUMAN_HR_HINT = re.compile(r"\b(speak to hr|talk to hr|human hr|contact hr|need hr|hr se baat)\b", re.I)


def classify_hr_route(content, conversation_history=None):
    text = normalize_leave_text(content).strip()
    if not text:
        return {
            "intent": "SMALL_TALK",
            "sub_intent": "empty",
            "confidence": 0.5,
            "needs_clarification": False,
            "clarification_question": None,
        }
    if HUMAN_HR_HINT.search(text):
        return {
            "intent": "HUMAN_HR",
            "sub_intent": "human_escalation",
            "confidence": 0.95,
            "needs_clarification": False,
            "clarification_question": None,
        }
    if is_asset_conduct_policy_question(text):
        return classify_webairy(text, conversation_history)
    if in_leave_intake(conversation_history) and looks_like_leave_form_reply(text) and not is_company_leave_policy_question(text):
        return {
            "intent": "LEAVE_WRITE",
            "sub_intent": "create",
            "confidence": 0.9,
            "needs_clarification": False,
            "clarification_question": None,
        }
    if is_confirm_submit(text) and in_leave_intake(conversation_history):
        return {
            "intent": "LEAVE_WRITE",
            "sub_intent": "create",
            "confidence": 0.9,
            "needs_clarification": False,
            "clarification_question": None,
        }
    return classify_webairy(text, conversation_history)


def classify_hr_intent(content, conversation_history=None):
    route = classify_hr_route(content, conversation_history)
    legacy = to_legacy_intent(route)
    if legacy == "SMALL_TALK":
        return "GENERAL"
    return legacy


def _prior_was_leave_request(conversation_history):
    prior = " ".join(str(item.get("content") or "") for item in (conversation_history or [])[-8:])
    return bool(re.search(
        r"\b("
        r"submit to HR|leave type|which date|apply for|haan likhein|HR ko bhej|"
        r"from when|to when|from which|until which|how many days|start date|"
        r"Annual, Sick|kab se|kitne din|kis din|kis tareekh|verify this|"
        r"Which leave|How many days|Which date|kitne din|kaunsi leave|"
        r"To apply, send|reason for leave|fill form|Fill form|"
        r"Nothing is sent to HR|I will not send this to HR"
        r")\b",
        prior,
        re.I,
    ))


def _prior_showed_live_balance(conversation_history):
    prior = " ".join(str(item.get("content") or "") for item in (conversation_history or [])[-12:])
    return bool(re.search(
        r"live leave balance|Available now:|Ab available:|Pending approval|Recently approved",
        prior,
        re.I,
    ))


def _is_leave_followup(text, conversation_history):
    if not conversation_history or len(text) > 160:
        return False
    if is_company_leave_policy_question(text) or is_policy_conversation_followup(text, conversation_history):
        return False
    prior = " ".join(str(item.get("content") or "") for item in conversation_history[-12:])
    if not re.search(r"\b(leave|balance|pending|annual|sick|casual|remaining|airtable|chutti|baqi)\b", prior, re.I):
        return False
    if is_explicit_leave_apply(text) and not is_quota_or_status_question(text):
        return False
    if _prior_showed_live_balance(conversation_history) and re.search(
        r"\b(leave|chutti|balance|baqi|batao|tell|show|apni|meri|my|phir|dobara|again|status)\b",
        text,
        re.I,
    ):
        return True
    return bool(re.search(
        r"\b(and|what about|those|them|pending|remaining|available|sick|annual|casual|again|status|"
        r"chutti|baqi|kal|aur|batao|apni|meri)\b",
        text,
        re.I,
    ))
GREETING = re.compile(
    r"^(hy+|hi+|hii+|hello|helo|hallo|hey+|yo|sup|greetings|hi there|hey there|good morning|"
    r"good afternoon|good evening|good night|morning|evening|how are you|how r u|how are ya|"
    r"how(?:'s| is) it going|whats? up|wassup|hola|bonjour|salut|ciao|namaste|merhaba|ol[aá]|"
    r"salam|ass?alamu ?alaikum|kia haal( hai)?|kya haal( hai)?|"
    r"(aap? )?(kaise|kaisi|kaisay|kaisy|kesay|kese|kesi|kayse) (ho|hain|hai)|"
    r"as-?salamu ?alaykum|سلام|مرحبا|أهلا)[.!? ]*$",
    re.I,
)
APPRECIATION = re.compile(
    r"^(thanks|thank you|thx|ty|tysm|thank you so much|thanks a lot|much appreciated|"
    r"appreciate it|shukriya|shukria|jazakallah|jazak)[.!, ]*$",
    re.I,
)
COMPLIMENT = re.compile(
    r"\b(good bot|great bot|nice bot|best bot|love you|i like you|"
    r"you(?:'re| are) (?:a )?(?:great|good|awesome|amazing|the best|helpful|smart|nice)|"
    r"well done|good job|nice work|mashallah|masha allah|zabardast|bohat acha)\b",
    re.I,
)
CHITCHAT = re.compile(
    r"^(ok|okay|k|lol|lmao|haha|nice|cool|great|awesome|np|no problem|alright|got it|"
    r"(or |aur |and )?(batao|btao|btado|btaye|kya|kia|what else|aur kya|or kya|phir|"
    r"tell me more|go on|continue|matlab|kaise|kese|acha|sahi|hmm)\??)[.!, ]*$",
    re.I,
)
CONVO_CONTINUE = re.compile(
    r"^(or |aur |and |to )?(batao|btao|btado|btaye|kya|kia|phir|aur|what else|"
    r"tell me more|go on|continue|why|kaise|kese|matlab|and then|acha|sahi|hmm|"
    r"or kya|aur kya|kya horaha|kya scene)\??[.! ]*$",
    re.I,
)


def is_greeting(content):
    return bool(GREETING.match(str(content or "").strip()))


def is_appreciation(content):
    return bool(APPRECIATION.match(str(content or "").strip()))


def is_compliment(content):
    text = str(content or "").strip()
    if not text or len(text) > 160:
        return False
    return bool(COMPLIMENT.search(text))


def is_chitchat(content):
    return bool(CHITCHAT.match(str(content or "").strip()))


def is_conversation_continue(content):
    text = str(content or "").strip()
    if not text or len(text) > 80:
        return False
    return bool(CONVO_CONTINUE.match(text) or is_chitchat(text))


def classify_social(content):
    text = str(content or "").strip()
    if not text or len(text) > 160:
        return None
    if is_greeting(text):
        return "greeting"
    if KNOWLEDGE_TOPIC.search(text):
        return None
    if is_appreciation(text):
        return "appreciation"
    if is_compliment(text):
        return "compliment"
    if is_chitchat(text):
        return "chitchat"
    return None


def social_fallback_reply(kind, content):
    text = re.sub(r"[.!?]+$", "", str(content or "").strip().lower()).strip()
    roman = prefer_roman(content)
    if kind == "appreciation":
        if roman or re.search(r"shukriya|shukria|jazak", text):
            return "Shukriya. Koi aur sawal ho to poochhein."
        return "You are welcome. If anything else about HR or your leave comes up, just ask."
    if kind == "compliment":
        if roman:
            return "Shukriya. Koi sawal ho to bataiye."
        return "Thank you. I am here whenever you have an HR question."
    if kind == "chitchat":
        if roman:
            return "Theek hai. Sawal ho to poochhein."
        return "Alright. Let me know if you need anything about policy or leave."
    if text.startswith("good morning"):
        return "Good morning. How can I help you today?"
    if text.startswith("good afternoon"):
        return "Good afternoon. How can I help you today?"
    if text.startswith("good evening"):
        return "Good evening. How can I help you today?"
    if text.startswith("good night"):
        return "Good night. Ask if you need anything tomorrow."
    if re.match(r"^(hola)", text):
        return "Hola. ¿En qué puedo ayudarte?"
    if re.match(r"^(bonjour|salut)", text):
        return "Bonjour. Comment puis-je vous aider ?"
    if re.match(r"^(ciao)", text):
        return "Ciao. Come posso aiutarti?"
    if re.match(r"^(namaste)", text):
        return "Namaste. How can I help you?"
    if re.match(r"^(merhaba)", text):
        return "Merhaba. Size nasıl yardımcı olabilirim?"
    if re.match(r"^(olá|ola)", text):
        return "Olá. Como posso ajudar?"
    if re.match(r"^(سلام|مرحبا|أهلا)", text):
        return "سلام. میں کیسے مدد کر سکتا ہوں؟"
    if re.match(r"^(salam|assalam|as-salamu)", text):
        return "Walaikum salam. Bataiye, main kaise madad kar sakta hoon?"
    if re.match(
        r"^(kia haal|kya haal|kaise |kaisi |kaisay |kaisy |kesay |kese |kesi |kayse )",
        text,
    ):
        return "Theek hoon, shukriya. Bataiye, main kaise madad kar sakta hoon?"
    if re.match(r"^(how are you|how r u|how are ya|how(?:'s| is) it going)", text):
        return "I am well, thank you. How can I help you with HR today?"
    if re.match(r"^(hello|helo|hallo|greetings|hi there|hey there)", text):
        return "Hello. How can I help you with HR today?"
    if text.startswith("hey"):
        return "Hello. How can I help you with HR today?"
    return "Hello. How can I help you with HR today?"


def scope_fallback_reply(question=""):
    """Kept for callers that still import it; the wording lives in routing.scope."""
    from app.routing.scope import redirect_reply

    return redirect_reply(question)


def situational_fallback_reply(question, identity=None):
    identity = identity or {}
    name = identity.get("memberName") or identity.get("memberUsername")
    # The employer's name, not the Discord server's, which is often different.
    company = identity.get("companyName") or "WebAiry"
    server = identity.get("companyName") or identity.get("guildName") or company
    bot = identity.get("botName") or "HR Assistant"
    locale = detect_reply_language(question)
    if is_about_asker(question):
        if name:
            return pick_locale_text(
                locale,
                english=f"You are {name}.",
                roman=f"Aap {name} hain.",
                urdu=f"آپ {name} ہیں۔",
                mix=f"Aap {name} hain.",
            )
        return pick_locale_text(
            locale,
            english="I can see you in this ticket, but I do not have a name on this message.",
            roman="Main aapko is ticket mein dekh sakta hoon, lekin is message par naam nahi hai.",
            urdu="میں آپ کو اس ٹکٹ میں دیکھ سکتا ہوں، لیکن اس پیغام پر نام نہیں ہے۔",
            mix="Main aapko dekh sakta hoon, lekin is message par naam nahi hai.",
        )
    if is_about_place(question) and re.search(r"knowledge", str(question or ""), re.I):
        return pick_locale_text(
            locale,
            english=(
                f"This is a private HR ticket for {server}. I help with company policy and "
                "workplace rules, and with your own leave."
            ),
            roman=(
                f"Yeh {server} ka private HR ticket hai. Main company policy, workplace rules, "
                "aur aapki leave mein madad karta hoon."
            ),
            urdu=(
                f"یہ {server} کا پرائیویٹ HR ٹکٹ ہے۔ میں کمپنی پالیسی، ورک پلیس رولز، "
                "اور آپ کی لیو میں مدد کرتا ہوں۔"
            ),
            mix=(
                f"Yeh {server} ka private HR ticket hai. Main company policy, workplace rules, "
                "aur aapki leave mein madad karta hoon."
            ),
        )
    if is_about_place(question):
        return pick_locale_text(
            locale,
            english=(
                f"This is the HR support desk for {server}. In this private ticket I help with "
                "company policy, and with your own leave."
            ),
            roman=(
                f"Yeh {server} ka HR support desk hai. Is private ticket mein main company "
                "policy, aur aapki leave mein madad karta hoon."
            ),
            urdu=(
                f"یہ {server} کا HR سپورٹ ڈیسک ہے۔ اس پرائیویٹ ٹکٹ میں میں کمپنی پالیسی، "
                "اور آپ کی لیو میں مدد کرتا ہوں۔"
            ),
            mix=(
                f"Yeh {server} ka HR support desk hai. Main company policy, aur aapki leave "
                "mein madad karta hoon."
            ),
        )
    return pick_locale_text(
        locale,
        english=f"I am {bot} for {company}. Ask about policy, or your own leave.",
        roman=f"Main {company} ka {bot} hoon. Policy, ya apni leave poochhein.",
        urdu=f"میں {company} کا {bot} ہوں۔ پالیسی یا اپنی لیو پوچھیں۔",
        mix=f"Main {company} ka {bot} hoon. Policy, ya apni leave poochhein.",
    )


def is_about_place(content):
    text = str(content or "").strip()
    if not text:
        return False
    if re.search(r"\b(policy|handbook|leave|salary|refund|invoice)\b", text, re.I) and not PLACE_HINT.search(text):
        return False
    if re.search(r"\b(policy|handbook|salary|refund|invoice)\b", text, re.I):
        return False
    return bool(PLACE_HINT.search(text))


def is_about_asker(content):
    return bool(ASKER_HINT.search(str(content or "")))


def is_about_bot(content):
    text = str(content or "").strip()
    if not text or len(text) > 240:
        return False
    if classify_social(text):
        return False
    if is_policy_conversation_followup(text):
        return False
    if is_about_asker(text) or is_about_place(text):
        return True
    if KNOWLEDGE_TOPIC.search(text):
        return False
    if ABOUT_BOT_PHRASES.search(text):
        return True
    normalized = re.sub(r"\s+", " ", re.sub(r"[?'\"!.,]+", " ", text)).strip()
    return bool(W_QUESTION.search(normalized) and ABOUT_YOU.search(normalized))

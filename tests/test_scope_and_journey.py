"""The bot answers HR questions and nothing else, in the employee's language.

The risk runs both ways: letting "what is 2x2" through makes it look like a
general chatbot, and redirecting "calculate my remaining leave" makes it
useless. Both directions are covered here.
"""

import pytest

from app.agent.router import AgentRouter
from app.logger import create_logger
from app.routing.scope import (
    capability_lines,
    is_off_topic,
    mentions_hr_topic,
    no_answer_reply,
    off_topic_kind,
    redirect_reply,
)

# Things an HR bot must not answer.
OFF_TOPIC = [
    ("what is 2x2", "math"),
    ("2x2", "math"),
    ("5 + 5", "math"),
    ("12*7=?", "math"),
    ("what is 15% of 200", "math"),
    ("solve this equation for me", "math"),
    ("write me a python function", "code"),
    ("help me debug this stack trace", "code"),
    ("what is the capital of France", "trivia"),
    ("who was Einstein", "trivia"),
    ("tell me a joke", "entertainment"),
    ("any netflix suggestions", "entertainment"),
    ("what is the weather today", "world"),
    ("mausam kaisa hai", "world"),
    ("bitcoin price today", "world"),
    ("are you chatgpt", "ai"),
    ("which model are you", "ai"),
    ("give me a recipe for biryani", "advice"),
    ("what medicine should I take", "expertise"),
]

# Things it must answer, several of which look off-topic on the surface.
IN_SCOPE = [
    "how many leaves do I have",
    "what is my leave balance",
    "calculate my remaining leave",
    "apni chutti ka batao",
    "I want to apply for sick leave tomorrow",
    "mujhe kal chutti chahiye",
    "what is the notice period",
    "kya company remote work allow karti hai",
    "I am sick today, can I take leave",
    "when do I get my salary slip",
    "tankhwah kab milti hai",
    "what does the medical insurance cover",
    "who is my manager",
    "attendance kaise lagti hai",
    "maternity leave policy",
    "how many days off do I get",
    "I need to talk to HR",
    "can I get 20% of my salary in advance",
    "what is the policy on overtime",
    "harassment complaint process",
    "OPD kitna yearly intern ko milta hai",
    "Can I freelance on my personal PC if the company laptop stays off",
]


def test_shopping_for_a_laptop_is_still_off_topic():
    assert off_topic_kind("which is the best laptop to buy") == "advice"


@pytest.mark.parametrize("text,expected", OFF_TOPIC)
def test_off_topic_messages_are_recognised(text, expected):
    assert off_topic_kind(text) == expected, text


@pytest.mark.parametrize("text", IN_SCOPE)
def test_hr_questions_are_never_redirected(text):
    assert off_topic_kind(text) is None, text
    assert mentions_hr_topic(text) or not is_off_topic(text)


def test_short_replies_inside_a_conversation_are_not_off_topic():
    # These arrive constantly during a leave form and must pass straight through.
    for text in ["yes", "no", "haan", "2 days", "Monday", "annual leave", "ok", "thanks"]:
        assert off_topic_kind(text) is None, text


def test_empty_and_very_long_input_is_ignored():
    assert off_topic_kind("") is None
    assert off_topic_kind("   ") is None
    assert off_topic_kind("weather " * 200) is None


# --- the redirect reads professionally --------------------------------------


def test_redirect_states_the_boundary_and_offers_help():
    reply = redirect_reply("what is 2x2")
    assert "policy" in reply.lower()
    assert "leave" in reply.lower()
    # Names the boundary once, without repeating the off-topic subject.
    assert reply.count("outside") <= 1
    assert "2x2" not in reply


def test_redirect_has_no_apology_or_lecture():
    for text, _kind in OFF_TOPIC:
        reply = redirect_reply(text).lower()
        assert "sorry" not in reply
        assert "i am just" not in reply
        assert "unfortunately" not in reply


def test_redirect_follows_the_employee_language():
    assert "madad" in redirect_reply("mausam kaisa hai").lower()
    assert "help" in redirect_reply("what is the weather").lower()
    urdu = redirect_reply("tell me a joke", None, "urdu")
    assert any("؀" <= ch <= "ۿ" for ch in urdu)


def test_coding_and_medical_get_their_own_wording():
    assert "coding" in redirect_reply("write me a python function").lower()
    assert "medical" in redirect_reply("what medicine should I take").lower()


# --- a fair HR question the handbook cannot answer --------------------------


def test_broad_policy_catalog_lists_topics_not_files():
    from app.agent.verification import is_broad_policy_catalog_question
    from app.generation.quality import is_degenerate_answer
    from app.routing.scope import policy_catalog_reply, public_policy_title

    for ask in ("what are the policies", "what are the company policies", "company policy"):
        assert is_broad_policy_catalog_question(ask), ask
    assert is_broad_policy_catalog_question("what is the annual leave policy") is False
    assert is_broad_policy_catalog_question("what is the WFH policy") is False
    assert public_policy_title("WebAiry Technologies Attendance Policy.docx") == "Attendance Policy"
    reply = policy_catalog_reply([
        {"source": "WebAiry Technologies Attendance Policy.docx"},
        {"source": "WebAiry's WFH Policy Criteria.docx"},
    ])
    assert "Attendance Policy" in reply
    assert "docx" not in reply.lower()
    assert "which one" in reply.lower()
    assert is_degenerate_answer("o" * 80) is True
    assert is_degenerate_answer("Sick leave needs a doctor's note after two days.") is False


def test_no_answer_never_admits_an_empty_lookup():
    """The employee must never learn that a search happened, or came up empty."""
    reply = no_answer_reply("what is the policy on sabbatical leave").lower()
    for leak in (
        "could not find",
        "couldn't find",
        "not find",
        "knowledge",
        "handbook",
        "document",
        "record",
        "data",
        "search",
        "pinecone",
        "airtable",
        "index",
    ):
        assert leak not in reply, leak
    # Instead it says what it does handle and invites an HR question.
    assert "hr" in reply
    assert "policy" in reply and "leave" in reply
    assert "?" in reply


def test_no_answer_speaks_the_employee_language():
    roman = no_answer_reply("sabbatical ka kya policy hai", "roman").lower()
    assert "madad" in roman or "poochh" in roman
    assert "could not find" not in roman
    urdu = no_answer_reply("kuch aur", "urdu")
    assert any("\u0600" <= ch <= "\u06ff" for ch in urdu)


# --- capability list --------------------------------------------------------


def test_capability_list_covers_the_service():
    lines = " ".join(capability_lines("english")).lower()
    for topic in ["policy", "leave", "hr"]:
        assert topic in lines
    assert "attendance" not in lines
    assert len(capability_lines("roman")) == len(capability_lines("english"))
    assert len(capability_lines("urdu")) == len(capability_lines("english"))


# --- the router redirects without touching retrieval ------------------------


class ExplodingRag:
    """Any retrieval attempt is a failure: off-topic must never reach here."""

    def answer_question(self, **kwargs):
        raise AssertionError("off-topic message reached the knowledge base")


def make_router(hr=None):
    return AgentRouter(
        config={"hr": {}},
        logger=create_logger("error"),
        rag=ExplodingRag(),
        hr=hr,
    )


@pytest.mark.parametrize("text,_kind", OFF_TOPIC)
def test_router_answers_off_topic_without_a_lookup(text, _kind):
    result = make_router().handle(
        question=text,
        namespace="hr",
        channel_id="scope-1",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert result["offTopic"] == _kind
    assert result["chunks"] == []
    assert "policy" in result["answer"].lower()


def test_router_still_sends_hr_questions_to_the_knowledge_base():
    router = make_router()
    with pytest.raises(AssertionError, match="reached the knowledge base"):
        router.handle(
            question="what is the notice period",
            namespace="hr",
            channel_id="scope-2",
            discord_user_id="111",
            identity={},
            conversation_history=[],
        )


def test_a_greeting_is_not_treated_as_off_topic():
    router = make_router()
    with pytest.raises(AssertionError, match="reached the knowledge base"):
        # Greetings go through the normal social path, not the redirect.
        router.handle(
            question="hello",
            namespace="hr",
            channel_id="scope-3",
            discord_user_id="111",
            identity={},
            conversation_history=[],
        )


def test_off_topic_does_not_hijack_an_open_leave_form():
    """Mid-form answers are never redirected, even if they look like trivia."""
    router = make_router(hr=object())
    router.drafts["scope-4"] = {
        "leave_type": "Annual Leave",
        "awaiting_details": True,
        "locale": "english",
    }
    result = router.handle(
        question="tell me a joke",
        namespace="hr",
        channel_id="scope-4",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert result.get("offTopic") is None
    assert result.get("ui") in {"leave_form", "leave_confirm"}


# --- journey copy -----------------------------------------------------------


def test_journey_embeds_explain_the_service():
    from app.discord.journey import closed_embed, help_embed, panel_embed, welcome_embed

    panel = panel_embed()
    assert "HR" in panel.title
    panel_text = " ".join(field.value for field in panel.fields).lower()
    assert "leave" in panel_text
    assert "attendance" not in panel_text
    # The entry card sets the boundary before anyone opens a ticket.
    assert "hr and workplace topics only" in panel_text

    welcome = welcome_embed("Abdullah", "Web Airy")
    assert "Abdullah" in welcome.title
    # The card is signed with the employer, not the Discord server.
    assert welcome.author.name == "Web Airy"
    welcome_text = " ".join(field.value for field in welcome.fields).lower()
    assert "leave balance" in welcome_text
    assert "talk to hr" in welcome_text


def test_cards_never_advertise_the_languages_they_support():
    """The assistant follows the employee's language without announcing it.

    Saying so invites people to test the languages instead of asking HR
    questions, so no card mentions Urdu, Roman Urdu or "any language".
    """
    from app.discord.journey import closed_embed, help_embed, panel_embed, welcome_embed

    surfaces = []
    for embed in (panel_embed(), welcome_embed("Abdullah", "Web Airy"), closed_embed("<@1>")):
        surfaces.extend([embed.title or "", embed.description or ""])
        surfaces.extend(field.value for field in embed.fields)
        if embed.footer:
            surfaces.append(embed.footer.text or "")

    blob = " ".join(surfaces).lower()
    for banned in ("roman urdu", "اردو", "urdu", "language", "zaban", "any language"):
        assert banned not in blob, f"cards must not advertise languages: {banned!r}"
    # And no Roman Urdu sample text in the examples either.
    for sample in ("chutti", "poochh", "kholein", "marzi"):
        assert sample not in blob, f"card still shows Roman Urdu: {sample!r}"

    for locale in ("english", "roman", "urdu", "mix"):
        assert help_embed(locale).fields

    assert closed_embed("<@1>").title
    assert closed_embed("Mohib Hasan · Staff").fields[0].value == "Mohib Hasan · Staff"


def test_closer_caption_uses_name_and_role():
    from types import SimpleNamespace
    from app.discord.journey import closer_caption

    config = {
        "discord": {"tickets": {"staffRoleId": "10", "adminRoleId": "8"}},
        "hr": {"hrRoleId": "9", "adminRoleId": "8"},
    }
    staff = SimpleNamespace(
        display_name="Mohib Hasan",
        roles=[SimpleNamespace(id=10)],
        guild_permissions=SimpleNamespace(administrator=False),
    )
    assert closer_caption(staff, config) == "Mohib Hasan · Staff"

    admin = SimpleNamespace(
        display_name="Mohib Hasan",
        roles=[SimpleNamespace(id=8)],
        guild_permissions=SimpleNamespace(administrator=False),
    )
    assert closer_caption(admin, config) == "Mohib Hasan · Admin"


def test_leave_decision_actor_is_discord_handle():
    from types import SimpleNamespace
    from app.discord.journey import discord_handle

    hod = SimpleNamespace(
        display_name="Mohib Hasan",
        name="mohib",
        roles=[SimpleNamespace(id=11, name="Marketing HOD")],
        guild_permissions=SimpleNamespace(administrator=False),
    )
    assert discord_handle(hod) == "@mohib"
    from app.discord.leave_review import decision_summary_embed

    embed = decision_summary_embed(
        {"employeeName": "Alex", "leaveType": "Annual Leave", "daysRequested": 1},
        outcome="approved",
        actor="@mohib",
        ticket_channel_id="1551526308528267314",
        ticket_name="ticket-alex-0001",
    )
    assert "Approved by @mohib" in (embed.footer.text or "")
    assert "ticket:" not in (embed.footer.text or "")
    assert "1551526308528267314" not in (embed.footer.text or "")
    ticket_field = next(field.value for field in embed.fields if field.name == "Ticket")
    assert "1551526308528267314" not in ticket_field


# --- nothing employee-facing may reveal how answers are produced ------------

# Words that would tell an employee there is a searchable store behind the
# assistant, or that a lookup came back empty.
BANNED_IN_EMPLOYEE_COPY = (
    "could not find",
    "couldn't find",
    "did not find",
    "no match",
    "knowledge base",
    "knowledge",
    "handbook",
    "excerpt",
    "document",
    "pinecone",
    "airtable",
    "vector",
    "embedding",
    "namespace",
    "index",
    "database",
    "retriev",
)


def _every_employee_facing_string():
    """Collect the copy an employee can actually be shown."""
    from app.config import FALLBACK_ANSWER, USER_ERROR
    from app.discord.journey import (
        closed_embed,
        help_embed,
        panel_embed,
        staff_note_text,
        ticket_intro_text,
        welcome_embed,
    )
    from app.routing.intent import (
        scope_fallback_reply,
        situational_fallback_reply,
        social_fallback_reply,
    )

    out = [FALLBACK_ANSWER, USER_ERROR, ticket_intro_text("<@1>"), staff_note_text()]

    for locale in ("english", "roman", "urdu", "mix"):
        out.append(no_answer_reply("something", locale))
        out.extend(capability_lines(locale))
        for kind, _pattern in [(k, None) for k in ("math", "code", "trivia", "world", "ai", "expertise", "other")]:
            out.append(redirect_reply("something", kind, locale))

    for text, _kind in OFF_TOPIC:
        out.append(redirect_reply(text))
        out.append(scope_fallback_reply(text))

    for kind in ("greeting", "appreciation", "compliment", "chitchat"):
        for text in ("hello", "thanks", "good bot", "ok", "salam", "kesay ho?"):
            out.append(social_fallback_reply(kind, text))

    for question in (
        "who are you",
        "what is my name",
        "what is this channel's knowledge?",
        "what can you do",
    ):
        out.append(
            situational_fallback_reply(question, {"memberName": "Abdullah", "guildName": "Web Airy"})
        )

    embeds = [
        panel_embed(),
        welcome_embed("Abdullah", "Web Airy"),
        closed_embed("<@1>"),
    ] + [help_embed(locale) for locale in ("english", "roman", "urdu", "mix")]
    for embed in embeds:
        out.extend([embed.title or "", embed.description or ""])
        out.extend(f"{field.name} {field.value}" for field in embed.fields)
        if embed.footer:
            out.append(embed.footer.text or "")
    return [str(item) for item in out if item]


def test_no_employee_facing_copy_reveals_the_retrieval_layer():
    leaks = []
    for text in _every_employee_facing_string():
        lowered = text.lower()
        for banned in BANNED_IN_EMPLOYEE_COPY:
            if banned in lowered:
                leaks.append((banned, text[:120]))
    assert not leaks, f"employee-facing copy leaks how answers are produced: {leaks}"


def test_answers_do_not_carry_a_source_file_name():
    from app.discord.messages import format_support_reply

    reply = format_support_reply(
        "Annual leave is 16 days.",
        [{"source": "WebAiry HR Handbook.docx", "text": "..."}],
        False,
    )
    assert reply == "Annual leave is 16 days."
    assert "docx" not in reply.lower()


def test_prompts_forbid_mentioning_the_retrieval_layer():
    """Even when a message reaches the model, the model is told to stay quiet."""
    from app.generation.prompt import answer_system_message, build_answer_prompt

    for mode in ("knowledge", "fallback", "mixed", "social", "self"):
        message = answer_system_message(mode)
        prompt = build_answer_prompt("what is the sabbatical policy", [], mode, {"memberName": "A"})
        combined = f"{message} {prompt}".lower()
        assert "never" in combined
    knowledge = build_answer_prompt("q", [{"source": "a.docx", "text": "t"}], "knowledge", {})
    assert "Never say that you searched" in knowledge
    fallback = build_answer_prompt("q", [], "fallback", {})
    assert "never say that you searched" in fallback.lower()


# --- the employer's name, not the Discord server's --------------------------


def test_identity_replies_name_the_company_not_the_server():
    """A server called "Mohib HR" must not be reported as the company name."""
    from app.routing.intent import situational_fallback_reply

    identity = {
        "memberName": "Mohib Hasan",
        "guildName": "Mohib HR",
        "companyName": "WebAiry",
        "botName": "HR support bot",
    }
    reply = situational_fallback_reply("what is this server of", identity)
    assert "WebAiry" in reply
    assert "Mohib HR" not in reply

    # With no company configured it falls back to the server name.
    fallback = situational_fallback_reply(
        "what is this server of", {**identity, "companyName": ""}
    )
    assert "Mohib HR" in fallback


def test_self_description_prompt_uses_the_company():
    from app.generation.prompt import build_answer_prompt

    prompt = build_answer_prompt("who are you", [], "self", {
        "guildName": "Mohib HR",
        "companyName": "WebAiry",
        "memberName": "Mohib Hasan",
    })
    assert "HR Assistant" in prompt
    assert "WebAiry" in prompt
    assert "Mohib HR" not in prompt


def test_who_are_you_fallback_does_not_use_the_discord_server_name():
    from app.routing.intent import situational_fallback_reply

    reply = situational_fallback_reply(
        "who are you",
        {"guildName": "Support Bot", "memberName": "Mohib Hasan"},
    )
    assert "HR Assistant" in reply
    assert "Support Bot" not in reply


# --- Roman Urdu must be recognised, English must not be mistaken for it -----


ROMAN_PHRASES = [
    "main kaun hoon",
    "ghar se kaam kar sakta hoon?",
    "kitni chuttiyan milti hain",
    "tankhwah kab milti hai",
    "attendance kaise lagti hai",
    "kitne din baqi hain",
    "abhi kya karna hai",
    "mujhe kal chutti chahiye",
]

ENGLISH_PHRASES = [
    "who are you",
    "what are the working hours",
    "how many leaves are allowed",
    "the main office is closed",
    "what is the main policy",
    "please approve my request",
    "was I marked late yesterday",
    "my manager approved it",
]


@pytest.mark.parametrize("text", ROMAN_PHRASES)
def test_roman_urdu_is_detected(text):
    from app.routing.language import detect_reply_language

    assert detect_reply_language(text) in {"roman", "mix"}, text


@pytest.mark.parametrize("text", ENGLISH_PHRASES)
def test_english_is_not_mistaken_for_roman_urdu(text):
    """"main" and "policy" are English words too, so the vocabulary must not
    be so eager that an English sentence gets answered in Roman Urdu."""
    from app.routing.language import detect_reply_language

    assert detect_reply_language(text) == "english", text


def test_identity_reply_follows_roman_urdu():
    from app.routing.intent import situational_fallback_reply

    reply = situational_fallback_reply("main kaun hoon", {"memberName": "Mohib Hasan"})
    assert "Mohib Hasan" in reply
    assert "hain" in reply.lower()
    assert "you are" not in reply.lower()

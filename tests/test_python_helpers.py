from types import SimpleNamespace

from app.discord.messages import format_support_reply, split_discord_content
from app.generation import is_rate_limited
from app.generation.prompt import answer_system_message, build_answer_prompt
from app.pinecone.metadata import detect_text_field, extract_chunk_text, extract_source_name, is_namespace_marker
from app.process_lock import acquire_instance_lock, release_instance_lock
from app.rag.retrieve import higher_score_is_better, is_relevant, to_context_chunks
from app.routing.channels import namespace_for_channel, should_handle_message, strip_bot_mention
from app.routing.intent import classify_social, is_about_bot, is_greeting, social_fallback_reply, situational_fallback_reply
from app.tickets.helpers import (
    can_close_ticket,
    category_id_from_channel,
    find_admin_role_id,
    find_staff_role_id,
    is_admin_member,
    parse_ticket_topic,
    pick_ticket_category_id,
    ticket_channel_name,
)
from app.tickets.store import TicketStore


class FakeCache:
    def __init__(self, ids):
        self._ids = {str(item) for item in ids}

    def has(self, role_id):
        return str(role_id) in self._ids


def test_extracts_chunk_text():
    assert extract_chunk_text({"text": "Invoice is due in 14 days"}) == "Invoice is due in 14 days"
    assert extract_chunk_text({"pageContent": "Hello"}) == "Hello"
    assert extract_chunk_text({"record_type": "document"}) == ""


def test_extracts_source_name():
    assert extract_source_name({"file_name": "guide.pdf", "fileName": "guide.pdf"}) == "guide.pdf"
    assert extract_source_name({"fileName": "manual.docx"}) == "manual.docx"


def test_skips_namespace_markers():
    assert is_namespace_marker({"id": "__namespace_marker__", "metadata": {}}) is True
    assert is_namespace_marker({"id": "abc", "metadata": {"record_type": "namespace_marker"}}) is True
    assert is_namespace_marker({"id": "chunk-1", "metadata": {"record_type": "document"}}) is False


def test_detects_text_field():
    assert detect_text_field([{"metadata": {"text": "body", "file_name": "a.pdf"}}]) == "text"


def test_cosine_relevance_threshold():
    assert higher_score_is_better("cosine") is True
    assert higher_score_is_better("euclidean") is False
    assert is_relevant([{"score": 0.72}], 0.45, "cosine") is True
    assert is_relevant([{"score": 0.12}], 0.45, "cosine") is False
    assert is_relevant([], 0.45, "cosine") is False


def test_namespace_routing():
    mapping = {"111": "bilal", "222": "abdullah"}
    assert namespace_for_channel(mapping, "111") == "bilal"
    assert namespace_for_channel(mapping, "999") is None


def test_ignores_bots_and_unmapped_channels():
    bot_user = SimpleNamespace(id="bot-1")
    assert should_handle_message(
        SimpleNamespace(author=SimpleNamespace(bot=True, id="other-bot"), guild=SimpleNamespace(id="g"), content="hello"),
        client_user=bot_user,
        respond_mode="all",
        namespace="bilal",
    ) is False
    assert should_handle_message(
        SimpleNamespace(author=SimpleNamespace(bot=False, id="user-1"), guild=SimpleNamespace(id="g"), content="hello"),
        client_user=bot_user,
        respond_mode="all",
        namespace=None,
    ) is False
    assert should_handle_message(
        SimpleNamespace(author=SimpleNamespace(bot=False, id="user-1"), guild=SimpleNamespace(id="g"), content="hello"),
        client_user=bot_user,
        respond_mode="all",
        namespace="bilal",
    ) is True


def test_slash_mode_ignores_mentions():
    bot_user = SimpleNamespace(id="bot-1")
    assert should_handle_message(
        SimpleNamespace(
            author=SimpleNamespace(bot=False, id="user-1"),
            guild=SimpleNamespace(id="g"),
            content="<@bot-1> what is the price?",
            mentions=SimpleNamespace(has=lambda user: user.id == "bot-1"),
        ),
        client_user=bot_user,
        respond_mode="slash",
        namespace="web airy",
    ) is False


def test_mention_mode():
    bot_user = SimpleNamespace(id="bot-1")
    mentioned = SimpleNamespace(
        author=SimpleNamespace(bot=False, id="user-1"),
        guild=SimpleNamespace(id="g"),
        content="<@bot-1> what is the price?",
        mentions=SimpleNamespace(has=lambda user: user.id == "bot-1"),
    )
    assert should_handle_message(mentioned, client_user=bot_user, respond_mode="mention", namespace="bilal") is True
    unmentioned = SimpleNamespace(
        author=SimpleNamespace(bot=False, id="user-1"),
        guild=SimpleNamespace(id="g"),
        content="what is the price?",
        mentions=SimpleNamespace(has=lambda user: False),
    )
    assert should_handle_message(unmentioned, client_user=bot_user, respond_mode="mention", namespace="bilal") is False


def test_strips_bot_mention():
    assert strip_bot_mention("<@bot-1> How do I reset the panel?", SimpleNamespace(id="bot-1")) == "How do I reset the panel?"


def test_greetings_thanks_compliments():
    assert is_greeting("hi") is True
    assert is_greeting("hy") is True
    assert classify_social("hello") == "greeting"
    assert classify_social("kesay ho?") == "greeting"
    assert classify_social("kia haal hai") == "greeting"
    assert "weather" not in social_fallback_reply("greeting", "kesay ho?").lower()
    assert classify_social("thanks") == "appreciation"
    assert classify_social("you are amazing") == "compliment"
    assert classify_social("ok") == "chitchat"
    assert classify_social("What is the refund window?") is None
    assert "How can I help" in social_fallback_reply("greeting", "hello")
    assert "welcome" in social_fallback_reply("appreciation", "thanks").lower()


def test_questions_about_the_bot():
    assert is_about_bot("who are you") is True
    assert is_about_bot("what are you") is True
    assert is_about_bot("how are you") is False
    assert is_about_bot("What is the refund window?") is False
    assert is_about_bot("what is this server?") is True
    assert is_about_bot("what is this channel's knowledge?") is True
    assert is_about_bot("what is my name?") is True
    assert is_about_bot("What is our annual leave policy?") is False
    name_reply = situational_fallback_reply("what is my name?", {"memberName": "Mohib Hasan"})
    assert "Mohib Hasan" in name_reply
    knowledge_reply = situational_fallback_reply(
        "what is this channel's knowledge?", {"guildName": "WebAiry"}
    ).lower()
    assert "policy" in knowledge_reply
    assert "leave" in knowledge_reply
    assert "attendance" not in knowledge_reply
    # Describes what it helps with, never a document store.
    for leak in ("handbook", "document", "knowledge base", "records"):
        assert leak not in knowledge_reply


def test_source_line_and_split():
    with_source = format_support_reply("Investigations must be impartial.", [{"source": "WebAiry Rules Policies.docx"}])
    # No source line: naming the file would tell the employee a document
    # store exists behind the assistant.
    assert with_source == "Investigations must be impartial."
    assert "WebAiry Rules Policies.docx" not in with_source
    assert "Source:" not in with_source
    assert format_support_reply("I could not find that.", [], True) == "I could not find that."
    parts = split_discord_content("a" * 2500, 2000)
    assert len(parts) == 2
    assert all(len(part) <= 2000 for part in parts)


def test_prompts_grounded():
    prompt = build_answer_prompt("What is the refund window?", [{"source": "policy.pdf", "text": "Refunds are available within 14 days."}])
    assert "ONLY the reference text" in prompt
    # The employee must never be told there is a document store behind this,
    # so the prompt carries that instruction explicitly.
    assert "Never mention documents" in prompt
    assert "Never say that you searched" in prompt
    assert "knowledge excerpts" not in prompt
    assert "Refunds are available within 14 days" in prompt
    social = build_answer_prompt("thanks", [], "social", {"socialKind": "appreciation", "memberName": "Bilal"})
    assert "Bilal" in social
    chat = build_answer_prompt("What is the capital of France?", [], "fallback", {"memberName": "Bilal"})
    assert "off-topic" in chat.lower() or "weather" in chat.lower()
    assert "general knowledge" in chat.lower() or "stay in scope" in chat.lower()
    from app.routing.intent import scope_fallback_reply
    scoped = scope_fallback_reply("whats the weather today")
    # Names what it can do rather than repeating the off-topic subject back.
    assert "policy" in scoped.lower()
    assert "leave" in scoped.lower()
    assert "weather" not in scoped.lower()
    self_prompt = build_answer_prompt("where are you", [], "self", {
        "botName": "HR Assistant",
        "guildName": "Support Bot",
        "companyName": "WebAiry",
        "channelName": "support",
        "respondMode": "mention",
        "memberName": "Mohib Hasan",
        "memberUsername": "mohib",
    })
    assert "HR Assistant" in self_prompt
    assert "Mohib Hasan" in self_prompt
    assert "WebAiry" in self_prompt
    assert "Support Bot" not in self_prompt
    assert "Support RAG Bot" not in self_prompt
    from app.generation.context_window import history_for_intent, history_for_llm, ticket_notes

    long_history = [{"role": "user", "content": f"old {i} " + ("x" * 200)} for i in range(20)]
    long_history.append({"role": "assistant", "content": "Which leave do you want?"})
    assert len(history_for_intent(long_history)) == 12
    assert len(history_for_llm(long_history)) <= 10
    assert "remaining" not in ticket_notes({"awaiting_confirm": True, "leave_type": "Casual Leave"})
    assert "Casual Leave" in ticket_notes({"awaiting_confirm": True, "leave_type": "Casual Leave"})
    urdu_policy = build_answer_prompt(
        "leave policy kya hai",
        [{"source": "policy.pdf", "text": "Annual leave is sixteen working days."}],
    )
    assert "Reply language parameter: roman" in urdu_policy
    assert "translate the facts faithfully" in urdu_policy.lower()
    assert "English only" not in urdu_policy
    assert "Do not translate policy" not in urdu_policy
    english_policy = build_answer_prompt(
        "what is the leave policy",
        [{"source": "policy.pdf", "text": "Annual leave is sixteen working days."}],
    )
    assert "Reply language parameter: english" in english_policy
    script_policy = build_answer_prompt(
        "چھٹی کی پالیسی کیا ہے",
        [{"source": "policy.pdf", "text": "Annual leave is sixteen working days."}],
    )
    assert "Reply language parameter: urdu" in script_policy
    social_urdu = build_answer_prompt("shukriya", [], "social", {"socialKind": "appreciation"})
    assert "Roman Urdu" in social_urdu
    noted = build_answer_prompt("policy?", [{"source": "h.docx", "text": "16 days"}], "knowledge", {
        "ticketNotes": "Collecting a leave request.",
        "conversationHistory": [{"role": "user", "content": "hi"}],
    })
    assert "working notes" in noted
    assert "Recent messages" in noted


def test_policy_answers_include_main_document_points():
    """A named policy ask should get the main points from the document, not a topic menu."""
    prompt = build_answer_prompt(
        "tell me opd policy",
        [{"source": "handbook.docx", "text": "OPD covers outpatient care. Annual limit PKR 48000."}],
    )
    assert "3 to 6 short sentences" in prompt.lower()
    assert "do not answer with a one-line" in prompt.lower() or "one-line summary" in prompt.lower()
    assert "keep exact terms, numbers" in prompt.lower()
    assert "knowledgeable hr" in prompt.lower() or "understand what they are asking" in prompt.lower()
    assert "combine points" in prompt.lower() or "more than one block" in prompt.lower()
    system = answer_system_message("knowledge")
    assert "strict wording" not in system.lower()
    assert "english only" not in system.lower()
    assert "knowledgeable hr" in system.lower() or "helpfully" in system.lower()


def test_instance_lock(tmp_path):
    import os

    acquire_instance_lock(tmp_path, os.getpid())
    try:
        acquire_instance_lock(tmp_path, os.getpid() + 1)
        raised = False
    except RuntimeError as error:
        raised = "already running" in str(error)
    assert raised
    release_instance_lock(tmp_path, os.getpid())


def test_rate_limit_detection():
    assert is_rate_limited(SimpleNamespace(status=429, message="Rate limit")) is True
    assert is_rate_limited(SimpleNamespace(message="OpenRouter HTTP 429")) is True
    assert is_rate_limited(SimpleNamespace(message="Failed to generate an answer.")) is False


def test_context_chunks():
    chunks = to_context_chunks([{
        "id": "1",
        "score": 0.9,
        "metadata": {"text": "Panel login uses email.", "file_name": "panel.pdf"},
    }])
    assert chunks[0]["source"] == "panel.pdf"
    assert chunks[0]["text"] == "Panel login uses email."


def test_ticket_helpers_and_store(tmp_path):
    assert find_staff_role_id([{"id": "9", "name": "Staff"}], "") == "9"
    assert find_admin_role_id([{"id": "1", "name": "Admin"}], "") == "1"
    assert pick_ticket_category_id(
        [
            {"id": "t1", "name": "ticket", "type": 0, "parentId": "cat1"},
            {"id": "cat1", "name": "Text Channels", "type": 4, "parentId": None},
            {"id": "cat2", "name": "Tickets", "type": 4, "parentId": None},
        ],
        "cat1",
    ) == "cat2"
    assert category_id_from_channel({"type": 0, "id": "222", "parentId": "111"}) == "111"
    assert parse_ticket_topic("ticket:98:web airy:1544")["namespace"] == "web airy"
    assert ticket_channel_name("Bilal Chaudhry", "12345616").startswith("ticket-")
    ticket = {"userId": "user-1"}
    member = SimpleNamespace(
        permissions=SimpleNamespace(has=lambda flag: False),
        roles=SimpleNamespace(cache=FakeCache([])),
    )
    assert can_close_ticket("user-1", member, ticket, "") is True
    admin_member = SimpleNamespace(
        permissions=SimpleNamespace(has=lambda flag: False),
        roles=SimpleNamespace(cache=FakeCache(["admin"])),
    )
    assert can_close_ticket("other", admin_member, ticket, {"adminRoleId": "admin", "staffRoleId": "staff"}) is True
    staff_member = SimpleNamespace(
        permissions=SimpleNamespace(has=lambda flag: False),
        roles=SimpleNamespace(cache=FakeCache(["staff"])),
    )
    assert can_close_ticket("other", staff_member, ticket, {"adminRoleId": "admin", "staffRoleId": "staff"}) is True
    assert can_close_ticket("user-1", staff_member, ticket, {"adminRoleId": "admin", "staffRoleId": "staff"}) is True
    assert is_admin_member(
        SimpleNamespace(permissions=SimpleNamespace(has=lambda flag: flag == "Administrator"), roles=SimpleNamespace(cache=FakeCache([]))),
        [],
        "",
    ) is True

    store = TicketStore(tmp_path / "tickets.json")
    store.upsert({
        "channelId": "c1",
        "userId": "u1",
        "parentChannelId": "p1",
        "namespace": "web airy",
        "status": "open",
    })
    assert store.find_by_user("u1")["channelId"] == "c1"
    store.close("c1")
    assert store.get_by_channel("c1")["status"] == "closed"
    store.upsert({**store.get_by_channel("c1"), "status": "open", "botActive": True})
    assert store.get_by_channel("c1")["status"] == "open"
    store.set_bot_active("c1", False)
    assert store.get_by_channel("c1")["botActive"] is False
    store.remove("c1")
    assert store.get_by_channel("c1") is None


def test_open_ticket_panel_has_no_close_button():
    from app.discord.tickets import OPEN_TICKET_ID, already_open_ticket_notice, open_ticket_panel

    embed, view = open_ticket_panel()
    ids = [item.custom_id for item in view.children]
    assert ids == [OPEN_TICKET_ID]
    notice = already_open_ticket_notice("123")
    assert "<#123>" in notice
    assert "already" in notice.lower()


def test_close_row_is_close_only():
    from app.discord.tickets import CLOSE_TICKET_ID, close_row

    view = close_row()
    ids = [item.custom_id for item in view.children]
    assert ids == [CLOSE_TICKET_ID]


def test_answer_model_falls_through_provider_chain():
    from app.errors import AppError, ErrorCodes
    from app.generation import AnswerModel

    class Failing:
        def __init__(self, status):
            self.status = status
            self.calls = 0

        def generate_answer(self, **_):
            self.calls += 1
            raise AppError(ErrorCodes.GENERATION_FAILED, f"OpenRouter HTTP {self.status}", status=self.status)

    class Working:
        def generate_answer(self, **_):
            return "ok"

    logger = SimpleNamespace(warn=lambda *a, **k: None)
    bad_key = Failing(401)
    limited = Failing(429)
    model = AnswerModel([("openrouter#1", bad_key), ("openrouter#2", limited), ("gemini", Working())], logger, 60_000)

    assert model.generate_answer(question="q") == "ok"
    # The 429 provider is cooling down; the bad key is retried every time.
    assert model.generate_answer(question="q") == "ok"
    assert bad_key.calls == 2
    assert limited.calls == 1


def test_answer_model_raises_last_error_when_all_fail():
    import pytest
    from app.errors import AppError, ErrorCodes
    from app.generation import AnswerModel

    class Failing:
        def generate_answer(self, **_):
            raise AppError(ErrorCodes.GENERATION_FAILED, "down")

    logger = SimpleNamespace(warn=lambda *a, **k: None)
    model = AnswerModel([("a", Failing()), ("b", Failing())], logger, 60_000)
    with pytest.raises(AppError):
        model.generate_answer(question="q")

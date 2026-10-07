from app.agent.router import AgentRouter
from app.logger import create_logger
from app.rag.query import expand_retrieval_query
from app.sessions.followup import (
    is_expand_followup,
    is_format_followup,
    is_repeat_followup,
    is_session_followup,
    last_knowledge_question,
)
from app.sessions.store import SessionStore, merge_histories


def test_followup_phrases():
    assert is_repeat_followup("give me again") is True
    assert is_format_followup("in precise form") is True
    assert is_session_followup("in precis form") is True
    assert is_session_followup("give me the medical policy in precis form") is False
    assert is_expand_followup("in detail") is True
    assert is_expand_followup("more detail") is True
    assert is_session_followup("in detail") is True
    history = [{"role": "user", "content": "give me the medical policy in precis form"}]
    assert "medical" in last_knowledge_question(history).lower()
    assert expand_retrieval_query("give me again", history).lower().find("medical") >= 0
    assert "opd" in expand_retrieval_query("in detail", [
        {"role": "user", "content": "tell me opd policy"},
        {"role": "assistant", "content": "OPD covers outpatient care."},
    ]).lower()


def test_in_detail_retrieves_prior_topic_not_thin_rewrite(tmp_path):
    """Asking for more detail must hit the handbook again, not rewrite a one-liner."""
    store = SessionStore(tmp_path / "sessions.json")
    store.remember(
        "55",
        question="tell me opd policy",
        answer="The OPD Policy ensures basic outpatient support. Ask about scope if you want more.",
        grounded=True,
    )
    seen = {}

    class FakeRag:
        def answer_question(self, **kwargs):
            seen["question"] = kwargs.get("question")
            seen["history"] = kwargs.get("conversation_history")
            return {
                "answer": "OPD covers outpatient care with an annual limit of PKR 48,000.",
                "fallback": False,
                "chunks": [{"text": "OPD covers outpatient care."}],
            }

    router = AgentRouter(
        config={"hr": {}},
        logger=create_logger("error"),
        rag=FakeRag(),
        hr=None,
        sessions=store,
    )
    result = router.handle(
        question="in detail",
        namespace="hr",
        channel_id="55",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert "48,000" in (result.get("answer") or "") or "48000" in (result.get("answer") or "")
    assert result.get("ui") != "session_repeat"
    assert seen.get("question") == "in detail"


def test_session_store_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    store.remember("111", question="OPD policy?", answer="Annual limit PKR 48000", grounded=True)
    store.remember("111", question="give me again", answer="Annual limit PKR 48000", grounded=True, followup=True)
    saved = store.get("111")
    assert saved["lastTopic"] == "OPD policy?"
    assert "48000" in saved["lastAnswer"]
    assert len(saved["turns"]) >= 4
    store.clear("111")
    assert store.get("111")["lastTopic"] == ""


def test_merge_and_repeat_answer(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    store.remember("99", question="give me the medical policy", answer="OPD covers glasses.", grounded=True)
    merged = merge_histories(store.get("99")["turns"], [{"role": "user", "content": "give me again"}])
    assert last_knowledge_question(merged, store.get("99")["lastTopic"])

    class FakeRag:
        def answer_question(self, **kwargs):
            return {"answer": "should not retrieve", "fallback": False, "chunks": []}

    router = AgentRouter(
        config={"hr": {}},
        logger=create_logger("error"),
        rag=FakeRag(),
        hr=None,
        sessions=store,
    )
    result = router.handle(
        question="give me again",
        namespace="hr",
        channel_id="99",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert "glasses" in (result.get("answer") or "").lower()
    assert result.get("ui") == "session_repeat"


def test_format_without_topic_asks_which_policy():
    router = AgentRouter(
        config={"hr": {}},
        logger=create_logger("error"),
        rag=None,
        hr=None,
    )
    result = router.handle(
        question="in precise form",
        namespace="hr",
        channel_id="1",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert "which policy" in (result.get("answer") or "").lower()

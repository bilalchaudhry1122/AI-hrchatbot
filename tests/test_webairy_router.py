import json
from pathlib import Path

from app.routing.intent import classify_hr_intent
from app.routing.webairy import classify_webairy, to_legacy_intent

PACK = Path(__file__).resolve().parents[1] / "webairy_intent_router_complete_training_pack.md"


def _jsonl_block(title):
    text = PACK.read_text(encoding="utf-8")
    marker = f"# {title}"
    start = text.find(marker)
    assert start != -1, title
    chunk = text[start:]
    fence = chunk.find("```jsonl")
    assert fence != -1
    body = chunk[fence + len("```jsonl"):]
    end = body.find("```")
    lines = []
    for line in body[:end].splitlines():
        line = line.strip()
        if not line:
            continue
        lines.append(json.loads(line))
    return lines


def _examples(kind):
    if kind == "train":
        return _jsonl_block("PART 2 — TRAINING DATASET")
    return _jsonl_block("PART 3 — HOLDOUT / EVALUATION TESTS")


def test_pack_training_intents():
    misses = []
    for row in _examples("train"):
        route = classify_webairy(row["text"], row.get("context") or [])
        expected = row["expected"]["intent"]
        if route["intent"] != expected:
            misses.append((row["text"], expected, route["intent"], route.get("sub_intent")))
    assert misses == [], misses


def test_pack_holdout_intents():
    misses = []
    for row in _examples("holdout"):
        route = classify_webairy(row["text"], row.get("context") or [])
        expected = row["expected"]["intent"]
        if route["intent"] != expected:
            misses.append((row["text"], expected, route["intent"], route.get("sub_intent")))
    assert misses == [], misses


def test_legacy_keeps_live_attendance_and_clarify():
    assert classify_hr_intent("Show my attendance this month.") == "HUMAN_HR"
    assert classify_hr_intent("what is the attendance policy") == "POLICY"
    assert classify_hr_intent("What is my current salary?") == "HUMAN_HR"
    assert classify_hr_intent("can i tell my salary to anyone?") == "POLICY"
    assert classify_hr_intent("Can salary information be shared with coworkers?") == "POLICY"
    assert classify_hr_intent("Please approve my WFH for tomorrow.") == "HUMAN_HR"
    assert classify_hr_intent("Can I have leave tomorrow?") == "CLARIFY"
    assert classify_hr_intent("leave please") == "CLARIFY"
    assert classify_hr_intent("Apply annual leave for tomorrow.") == "LEAVE_REQUEST"
    assert classify_hr_intent("How many annual leaves do I have?") == "LEAVE_BALANCE"
    assert classify_hr_intent("What is the annual leave policy?") == "POLICY"
    assert to_legacy_intent(classify_webairy("Show me my attendance for this month.")) == "HUMAN_HR"
    assert classify_webairy("what is the attendance policy")["intent"] == "RAG_KNOWLEDGE"


FREELANCE_SUNDAY = (
    "Can I freelance on Sunday on my personal PC if the company laptop stays off "
    "— and do I need a warning letter first if I’m caught?"
)


def test_friday_off_still_applies():
    from app.agent.verification import is_explicit_leave_apply

    assert is_explicit_leave_apply("I want Friday off") is True
    assert is_explicit_leave_apply(FREELANCE_SUNDAY) is False
    history = [
        {"role": "assistant", "content": "Select a leave type, then fill From, To, and Reason."},
    ]
    route = classify_webairy(FREELANCE_SUNDAY, history)
    assert route["intent"] == "RAG_KNOWLEDGE"
    assert route["sub_intent"] == "asset_policy"
    assert classify_hr_intent(FREELANCE_SUNDAY, history) == "POLICY"
    assert classify_hr_intent(FREELANCE_SUNDAY) == "POLICY"


APPLY_AND_SUNDAY = (
    "I want leave next Monday for a cricket match — open the form. Also, is Sunday a working day?"
)


def test_split_pasted_questions_opens_form_on_last_ask():
    from app.agent.router import AgentRouter
    from app.logger import create_logger
    from app.routing.questions import split_user_questions
    from tests.test_leave_workflow import make_hr

    blob = (
        "Can I freelance on Sunday on my personal PC if the company laptop stays off "
        "— and do I need a warning letter first if I’m caught?\n\n"
        + APPLY_AND_SUNDAY
    )
    parts = split_user_questions(blob)
    assert len(parts) == 2
    assert classify_hr_intent(parts[0]) == "POLICY"
    assert classify_hr_intent(parts[1]) == "MIXED"

    class FakeRag:
        def answer_question(self, **kwargs):
            return {"answer": "Policy answer.", "fallback": False, "chunks": []}

    router = AgentRouter(
        config={"hr": {}},
        logger=create_logger("error"),
        rag=FakeRag(),
        hr=make_hr(),
    )
    result = router.handle(
        question=blob,
        namespace="hr",
        channel_id="88",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert result.get("ui") == "leave_form"
    assert result.get("speakAnswer") is True
    assert result.get("leaveCard")
    assert "not a working day" in (result.get("answer") or "").lower() or "sunday" in (result.get("answer") or "").lower()


def test_apply_plus_working_day_question_is_mixed():
    from app.hr.workdays import weekend_day_answer
    from app.logger import create_logger
    from app.agent.router import AgentRouter
    from tests.test_leave_workflow import make_hr

    route = classify_webairy(APPLY_AND_SUNDAY)
    assert route["intent"] == "MIXED"
    assert route["sub_intent"] == "holiday_plus_create"
    assert classify_hr_intent(APPLY_AND_SUNDAY) == "MIXED"
    assert "not a working day" in weekend_day_answer(APPLY_AND_SUNDAY, "english").lower()

    class FakeRag:
        def answer_question(self, **kwargs):
            return {"answer": "Weekends are weekly offs.", "fallback": False, "chunks": []}

    router = AgentRouter(
        config={"hr": {}},
        logger=create_logger("error"),
        rag=FakeRag(),
        hr=make_hr(),
    )
    result = router.handle(
        question=APPLY_AND_SUNDAY,
        namespace="hr",
        channel_id="77",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert result.get("ui") == "leave_form"
    assert result.get("speakAnswer") is True
    assert "sunday" in (result.get("answer") or "").lower()
    assert result.get("leaveCard")


def test_want_sick_leave_tomorrow_opens_form_with_policy_line():
    from app.agent.router import AgentRouter
    from app.logger import create_logger
    from tests.test_leave_workflow import make_hr

    assert classify_hr_intent("i want sick leave tomorrow") == "LEAVE_REQUEST"

    class FakeRag:
        def answer_question(self, **kwargs):
            return {
                "answer": "Planned leave must be applied for and approved through the HR in advance.",
                "fallback": False,
                "chunks": [],
            }

    router = AgentRouter(
        config={"hr": {}},
        logger=create_logger("error"),
        rag=FakeRag(),
        hr=make_hr(),
    )
    result = router.handle(
        question="i want sick leave tomorrow",
        namespace="hr",
        channel_id="90",
        discord_user_id="111",
        identity={"memberName": "Abdullah"},
        conversation_history=[],
    )
    assert result.get("ui") == "leave_form"
    assert result.get("leaveCard")
    assert result.get("speakAnswer") is not True
    assert "handle HR topics" not in (result.get("answer") or "")
    assert "planned leave" not in (result.get("answer") or "").lower()

from app.agent.router import AgentRouter
from app.agent.verification import (
    is_cancel_submit,
    is_confirm_submit,
    is_refuse_withdraw,
    is_withdraw_leave,
    should_cancel_leave_form,
    should_confirm_leave_form,
)
from app.logger import create_logger


def test_short_yes_no_only_when_whole_message():
    for text in ("yes", "haan", "han", "ok", "okay", "sure", "ji", "theek hai", "submit", "kar do"):
        assert is_confirm_submit(text) is True, text
    for text in ("no", "nahi", "cancel", "nope"):
        assert is_cancel_submit(text) is True, text


def test_leading_yes_no_does_not_override_sentence():
    assert is_confirm_submit("ok thanks") is False
    assert is_confirm_submit("yes thanks") is False
    assert is_confirm_submit("haan meray pass kitni leaves hain") is False
    assert is_confirm_submit("yes how many leaves do I have") is False
    assert is_confirm_submit("ok tell me the leave policy") is False
    assert is_confirm_submit("haan nahi withdraw krna") is False
    assert is_confirm_submit("yes please submit") is True
    assert is_confirm_submit("haan submit kar do") is True
    assert is_cancel_submit("no i mean how many leaves are allowed") is False
    assert is_cancel_submit("nahi mujhai withdraw nhi krna") is False
    assert is_refuse_withdraw("nahi mujhai withdraw nhi krna") is True
    assert is_withdraw_leave("nahi mujhai withdraw nhi krna") is False
    assert is_cancel_submit("nhi chahiye leave") is True
    assert is_confirm_submit("karo leave laga kal ki") is False


def test_bare_nhi_needs_confirm_context():
    filling = {"awaiting_details": True, "awaiting_confirm": False}
    confirming = {"awaiting_details": False, "awaiting_confirm": True}
    assert should_cancel_leave_form("nhi", filling) is False
    assert should_cancel_leave_form("no", filling) is False
    assert should_cancel_leave_form("nhi", confirming) is True
    assert should_cancel_leave_form("cancel", filling) is True
    assert should_cancel_leave_form("nahi chahiye leave", filling) is True
    asked = [{"role": "assistant", "content": "Nothing is sent to HR until you tap Submit to HR."}]
    assert should_cancel_leave_form("nhi", filling, asked) is True
    assert should_confirm_leave_form("haan", filling) is False
    assert should_confirm_leave_form("haan", confirming) is True

    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=None, hr=None)
    router.drafts["1"] = {"awaiting_details": True, "leave_type": "Sick Leave", "locale": "roman"}
    result = router.handle(
        question="nhi",
        namespace="hr",
        channel_id="1",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert result.get("ui") != "leave_cancelled"
    assert result.get("ui") == "polarity_ack"
    assert "1" in router.drafts
    assert is_confirm_submit("yes nahi") is False
    assert is_confirm_submit("haan nahi") is False
    assert is_withdraw_leave("don't withdraw") is False
    assert is_confirm_submit("yes I don't want to withdraw") is False

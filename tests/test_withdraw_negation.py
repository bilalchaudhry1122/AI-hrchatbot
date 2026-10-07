from datetime import date

from app.agent.router import AgentRouter
from app.agent.verification import is_refuse_withdraw, is_withdraw_leave
from app.logger import create_logger
from tests.test_hr import make_hr

REFUSE = [
    "nhi mujhai withdraw nhi krna",
    "nahi mujhe withdraw nahi karna",
    "mujhe withdraw nahi karna",
    "don't withdraw",
    "do not withdraw",
    "I don't want to withdraw",
    "withdraw mat karo",
    "withdraw nahi krna",
    "no don't withdraw",
    "nahi withdraw karna",
]

CONFIRM = [
    "withdraw",
    "withdraw my leave",
    "please withdraw",
    "wapas le lo",
    "pending chutti wapis le lo",
]

POLICY_AFTER_APPLY = [
    "what is the leave entitlement policy for goplay?",
    "what is the leave policy",
    "leave policy btao",
    "how many leaves are allowed",
]


def test_refuse_withdraw_phrases():
    for text in REFUSE:
        assert is_refuse_withdraw(text) is True, text
        assert is_withdraw_leave(text) is False, text
    for text in CONFIRM:
        assert is_refuse_withdraw(text) is False, text
        assert is_withdraw_leave(text) is True, text


def test_router_keeps_pending_when_user_refuses_withdraw():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="770",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 14),
        end_date=date(2026, 9, 14),
        reason="family",
    )
    router = AgentRouter(config={"hr": {}}, logger=create_logger("error"), rag=None, hr=hr)
    result = router.handle(
        question="nhi mujhai withdraw nhi krna",
        namespace="hr",
        channel_id="770",
        discord_user_id="111",
        identity={},
        conversation_history=[],
    )
    assert result.get("ui") == "leave_kept"
    assert result.get("ui") != "leave_withdrawn"
    assert hr.leave.get_pending_for_member("111") is not None
    withdrawn = router.handle(
        question="withdraw",
        namespace="hr",
        channel_id="770",
        discord_user_id="111",
        identity={"memberName": "Bilal"},
        conversation_history=[],
    )
    assert withdrawn.get("ui") == "leave_withdrawn"
    assert hr.leave.get_pending_for_member("111") is None


def test_policy_question_is_not_a_withdraw():
    from app.agent.verification import recent_question_should_not_withdraw

    for text in POLICY_AFTER_APPLY:
        assert is_withdraw_leave(text) is False, text
        assert recent_question_should_not_withdraw(text) is True, text
    assert is_withdraw_leave("withdraw my leave") is True
    assert recent_question_should_not_withdraw("withdraw my leave") is False
    assert is_withdraw_leave("how do I withdraw my leave") is True


class _FakeRag:
    def answer_question(self, **_kwargs):
        return {
            "answer": "Annual leave is covered in the company leave policy.",
            "fallback": False,
            "chunks": [{"text": "Annual leave entitlement and leave policy."}],
        }


def test_policy_question_after_apply_keeps_pending_leave():
    hr = make_hr()
    hr.leave.create_pending_request(
        discord_user_id="111",
        ticket_channel_id="771",
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 18),
        end_date=date(2026, 9, 24),
        reason="travel",
    )
    router = AgentRouter(
        config={"hr": {}},
        logger=create_logger("error"),
        rag=_FakeRag(),
        hr=hr,
    )
    history = [
        {"role": "user", "content": "I want annual leave from 18 sep to 24 sep"},
        {"role": "assistant", "content": "HR approval required."},
    ]
    result = router.handle(
        question="what is the leave entitlement policy for goplay?",
        namespace="hr",
        channel_id="771",
        discord_user_id="111",
        identity={},
        conversation_history=history,
    )
    assert result.get("ui") != "leave_withdrawn"
    assert "withdraw" not in (result.get("answer") or "").lower()
    assert hr.leave.get_pending_for_member("111") is not None
    withdrawn = router.handle(
        question="withdraw",
        namespace="hr",
        channel_id="771",
        discord_user_id="111",
        identity={"memberName": "Bilal"},
        conversation_history=history,
    )
    assert withdrawn.get("ui") == "leave_withdrawn"

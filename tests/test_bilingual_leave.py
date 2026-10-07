from app.agent.verification import (
    is_company_leave_allowance_question,
    is_company_leave_policy_question,
)
from app.routing.intent import classify_hr_intent
from app.routing.roman_urdu import normalize_leave_text


BALANCE = [
    "meray pass kitni leaves hain?",
    "mere pass kitni leaves hain",
    "mere paas kitni chutti hain",
    "meri leaves kitni hain",
    "meri chutti kitni hai",
    "kitni leaves hain meray pass",
    "mujhe kitni leave bachi hain",
    "apni leave kitni hai",
    "my leave balance",
    "what's my leave balance",
    "what is my leave",
    "how many leaves do I have?",
    "How many annual leaves do I have?",
    "how many leaves I have",
    "tell me about my leave",
    "bhai mughe apni leave ka batao",
]

POLICY = [
    "leave policy btao",
    "leave policy batao",
    "what is the leave policy",
    "what the leave policy",
    "whats the leave policy",
    "what's the leave policy",
    "How many annual leaves does the company allow?",
    "how many leaves are allowed",
    "kitni leaves milti hain company mein",
]


def test_personal_balance_roman_and_english():
    assert "mere paas" in normalize_leave_text("meray pass kitni leaves hain")
    for text in BALANCE:
        assert classify_hr_intent(text) == "LEAVE_BALANCE", text


def test_policy_stays_handbook():
    for text in POLICY:
        assert classify_hr_intent(text) == "POLICY", text


def test_policy_wording_is_not_a_personal_allowance_question():
    for text in (
        "what the leave policy",
        "what is the leave policy",
        "leave policy btao",
    ):
        assert is_company_leave_policy_question(text), text
        assert not is_company_leave_allowance_question(text), text


def test_how_many_allowed_can_use_recorded_entitlement():
    assert is_company_leave_allowance_question("how many leaves are allowed")
    assert is_company_leave_allowance_question("How many annual leaves does the company allow?")


def test_policy_after_balance_card_stays_handbook():
    history = [
        {"role": "user", "content": "Remaining"},
        {"role": "assistant", "content": "Your leave balance\nAvailable now:\n• Sick Leave — 8 of 10"},
    ]
    assert classify_hr_intent("what the leave policy", history) == "POLICY"

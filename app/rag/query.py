from app.agent.verification import (
    is_company_handbook_question,
    is_company_leave_policy_question,
    is_policy_conversation_followup,
    is_workplace_clarification,
    last_company_policy_question,
)

POLICY_RETRIEVE_HINT = (
    "company HR leave policy handbook yearly entitlement "
    "annual casual sick leave days allowed in total"
)
HANDBOOK_RETRIEVE_HINT = (
    "WebAiry company HR handbook workplace policy rules "
    "leave attendance working hours code of conduct work from home"
)


def expand_retrieval_query(question, conversation_history=None, last_topic=""):
    from app.sessions.followup import is_session_followup, last_knowledge_question

    current = str(question or "").strip()
    prior = last_knowledge_question(conversation_history, last_topic) or last_company_policy_question(conversation_history)
    source = current
    if (is_policy_conversation_followup(current, conversation_history) or is_session_followup(current)) and prior:
        source = prior
    if is_workplace_clarification(current) and prior:
        source = prior
    if is_company_leave_policy_question(source):
        return f"{source} {POLICY_RETRIEVE_HINT}"
    if is_company_handbook_question(source):
        return f"{source} {HANDBOOK_RETRIEVE_HINT}"
    return source


def should_retry_policy_retrieve(question, conversation_history=None, last_topic=""):
    from app.sessions.followup import is_session_followup, last_knowledge_question

    current = str(question or "").strip()
    if is_company_leave_policy_question(current) or is_company_handbook_question(current):
        return True
    prior = last_knowledge_question(conversation_history, last_topic) or last_company_policy_question(conversation_history)
    if is_session_followup(current) and prior:
        return True
    return bool(
        is_policy_conversation_followup(current, conversation_history)
        and last_company_policy_question(conversation_history)
    )

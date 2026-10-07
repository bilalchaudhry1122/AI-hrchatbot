from app.errors import AppError, ErrorCodes
from app.hr.dates import resolve_attendance_range


def search_hr_policy(rag, *, question, namespace, channel_id, identity, conversation_history):
    if rag is None:
        raise AppError(ErrorCodes.PINECONE_UNAVAILABLE, "Policy search is unavailable.", expose=True)
    return rag.answer_question(
        question=question,
        namespace=namespace,
        channel_id=channel_id,
        identity=identity,
        conversation_history=conversation_history,
    )


def get_my_leave_balance(hr, discord_user_id, leave_type=None, locale=None, role_names=None):
    return hr.leave.get_my_leave_balance(
        discord_user_id, leave_type, locale=locale, role_names=role_names
    )


def get_my_attendance(hr, discord_user_id, question):
    start, end = resolve_attendance_range(question)
    return hr.attendance.get_my_attendance(discord_user_id, start, end)


def prepare_leave_request(hr, **kwargs):
    return hr.leave.create_pending_request(**kwargs)

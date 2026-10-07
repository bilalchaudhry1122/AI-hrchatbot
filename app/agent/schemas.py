INTENTS = ("POLICY", "LEAVE_BALANCE", "ATTENDANCE", "LEAVE_REQUEST", "GENERAL", "HUMAN_HR", "MIXED", "CLARIFY")

LEAVE_EXTRACT_INSTRUCTION = """You extract structured leave data. You do NOT approve leave and you do NOT invent a request.

Read the user message carefully.

Set is_leave_request to true ONLY if the user is clearly applying for / requesting / booking leave.
Set is_leave_request to false if they are:
- asking quota, balance, remaining, pending, or availability
- asking policy
- chatting, confirming they understood, or sending random text
- mentioning a leave type without asking to apply

Never invent a leave type or date that the user did not state.
If unsure, use nulls and is_leave_request=false.

JSON keys:
is_leave_request (boolean),
leave_type (Annual Leave|Sick Leave|Casual Leave or null),
start_date (YYYY-MM-DD or null),
end_date (YYYY-MM-DD or null),
days_requested (number or null),
reason (string or null)
"""


# Patterns

- Factories: `create_logger`, `create_pinecone`, `create_gemini`, `create_answer_model`, `create_rag_pipeline`, `create_discord_bot`
- Config dicts with camelCase keys (ported from Node)
- User-facing errors never leak keys, scores, namespaces, model names
- Diagnostic scripts in `scripts/` are query-only except `scripts/add_leave_status_options.py`, which seeds then deletes two Leave Requests rows so Airtable Status gains `PENDING_MANAGER` / `PENDING_HR`, and `scripts/sync_discord_staff.py`, which upserts Employees from live Discord roles (HR is enough when Admin is gone) and marks leftover rows Inactive
- Tests: `tests/test_python_helpers.py` (helpers, routing, intent — no live network); `tests/test_hr.py` for Airtable/leave; `tests/test_leave_mail.py` for approved-leave To/Cc and human-readable copy
- Leave mail setup: `scripts/setup_leave_mail.py` writes SMTP + reviewer Emails; do not commit `.env`
- Leave apply: one form card per ticket (reused, not duplicated); modal **Fill form**; leave types are Annual / Sick / Casual only (Unpaid removed); typed dates still work; reason is taken from the same apply message when present (`because` / `for a …` / `waja se`); reason still required before submit; Roman ranges `20 sep say 25 tak`; keep draft so follow-ups are not sent to RAG; one open request per Discord user until HOD/HR decides or the staff member withdraws; BI/CS/Marketing members go to their HOD channel first (those Discord roles beat Sales/Airtable), then `#leave-requests` after HOD approve
- Cancel vs answer: “no i mean …” / company leave allowance → policy (Pinecone), never the cancel line; personal “how many do I have” → Airtable; stray **yes** after a balance card does not re-print balances or “I did not create an HR approval”
- Split Discord messages if over length in `discord/messages.py`
- Preserve ticket history in prompt until channel deleted

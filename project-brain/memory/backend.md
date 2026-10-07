# Backend

## Discord bot

`app/discord/bot.py` handles ready, messages in ticket channels, button interactions, `/leave`. Uses Discord recent messages plus **persisted ticket session** (`sessions.json`, last 40 turns, last topic, last grounded answer). Follow-ups like “give me again” / “in precise form” reuse that session. Closing a ticket clears the session.

## Tickets

`app/discord/tickets.py` + `app/tickets/helpers.py`: one ticket per member; close locks send; reopen same channel; new channel only if deleted. Admin roles named Admin / Administrator / Admins; Staff if present.

## RAG pipeline

`app/rag/pipeline.py`: social/greeting → no retrieve; about-bot → self mode; else embed + retrieve. Company leave-allowance questions embed with a handbook hint; a bare “what are the policies” ask lists policy topics (no model dump). Degenerate model loops are rejected. Follow-ups (“this workplace”, “in total”) reuse the last policy question; if still no match, retry a handbook entitlement query. “how many leaves in policy” is POLICY (handbook only), not MIXED personal+policy, unless they also ask what *they* have. Below `RELEVANCE_THRESHOLD` → scoped refusal. Weather/AI examples only if the user asked about those. Roman “kesay ho” is a greeting. No general-knowledge chat.

## Generation

`app/generation/prompt.py` builds grounded prompts. Policy mode understands the question, combines matching points from retrieved chunks, and answers like knowledgeable HR (exact terms/numbers kept; language follows the question). OpenRouter primary (`openrouter.py` via httpx); Gemini fallback (`generation/gemini.py`). `AnswerModel` in `generation/__init__.py` switches on 429 cooldown.

`app/agent/router.py` — leave form continues only when the new message looks like a leave reply (type/date/yes/reason). History after submit/balance does not reopen intake. Other ticket questions go to RAG/HR as normal. A staff member cannot start or submit another leave while any request for their Discord User ID is PENDING (quota questions still work).

Strict source split: **Airtable** only for *this person’s* remaining/quota (“my/meri/apni/mere paas/meray pass”, “do I have”, “kitni leaves hain” with a personal marker). **Pinecone** for company allowance (“how many leaves are allowed/there”, “leave policy btao”, handbook). “meray pass kitni leaves hain?” is live balance, not handbook. Cancel applies only with context: bare `no`/`nhi` cancel only while waiting for Submit (or the last bot line asked to confirm). Filling the form, `nhi` is not cancel. Explicit `cancel` / `nahi chahiye leave` still cancel. “No I mean …” is a correction. **yes / haan / ok** submit only in that same confirm context.

Approved-leave cancel lists upcoming rows from `list_cancellable_approved`. The person chooses a leave on the form (request id + dates) and `LeaveService.cancel_approved_for_member` cancels that row. Detected by `is_cancel_approved_leave` (not pending withdraw).

Airtable leave: BI / Marketing members (and HODs/HR/Admin) get Annual 16 / Sick 8 / Casual 8. **CS Member and Sales Member have no leave apply, balance, or quota.** Department **members** in **BI / Marketing** go to HOD first (`PENDING_MANAGER`), then HR (`PENDING_HR`). HOD, HR, and Admin applying for themselves go straight to `#leave-requests`. Discord Member/HOD role names are the routing source of truth when present. Leave request writes use `typecast=True` so Status can store `PENDING_MANAGER` / `PENDING_HR`. HOD may act only on their department’s HOD-stage leave; HR only after that. Admin may act at either step. `LeaveService.create_pending_request` rejects a second PENDING row (`LEAVE_REQUEST_OPEN`). Inbox routing uses `needsHod`, not only the stored Airtable status. One bot instance is enforced with an exclusive file lock.

## Routing

`app/routing/language.py` — greetings, leave cards, personal answers, and **policy RAG** follow the current question (english / roman / urdu / mix). Policy may be translated into that language; exact terms/numbers stay faithful (about 3–6 main sentences for a named policy). Expand follow-ups like “in detail” re-retrieve that prior handbook topic.

`app/routing/channels.py` — namespace map, respond modes. `app/routing/intent.py` + `app/routing/webairy.py` + `app/routing/data_source.py` — WebAiry classifier first (`RAG_KNOWLEDGE`, `LEAVE_READ`, `LEAVE_WRITE`, `MIXED`, `HUMAN_HR`, `CLARIFY`, `SMALL_TALK`), then mapped to POLICY / LEAVE_BALANCE / LEAVE_REQUEST / MIXED / HUMAN_HR / CLARIFY. **Airtable reads are leave balance only.** Leave apply writes Airtable. Attendance policy and other handbook questions go to Pinecone. Live punch/attendance records escalate to HUMAN_HR (no Attendance table). MIXED if policy+balance or holiday/policy+apply. Salary *amount* escalates to HUMAN_HR; “can I tell/share my salary” is confidentiality policy. `CLARIFY` asks one question and does not write Airtable. Ambiguous “Can I have leave tomorrow?” / “leave please” is CLARIFY, not apply. Greetings offer policy and leave, not attendance. A leave apply does not run RAG first. Staff is not a ticket viewer. Situational questions use Discord identity + self-mode. Self-mode names **WebAiry HR assistant**.


## Infra

Leave mail: HTML + plain text. HTML uses the WebAiry logo header and a purple footer (security note + copyright only; no social or client-area buttons). Header/footer use solid purple `bgcolor`. From is the SMTP login (display name WebAiry HR); Reply-To stays no-reply. To is `LEAVE_MAIL_HR` from `.env` (then Airtable HR Role, then SMTP login). Cc is the department HOD Email from Employees. Port 465 uses SSL.

`process_lock.py`, `logger.py`, `errors.py`, `main.py`.

`app/generation/__init__.py` lazy-imports `create_gemini` so `embeddings.gemini` can import `generation.prompt` without a circular import. `app/embeddings/__init__.py` does not re-export `create_gemini`.

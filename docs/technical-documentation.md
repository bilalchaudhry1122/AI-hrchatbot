# HR Assistant — Technical Documentation

Technical reference for the Discord HR Assistant bot (WebAiry).  
Companion docs: `docs/user-guide-members-hod.md`, `docs/user-guide-hr.md`, `docs/sow-updates-current-flow.md`, `README.md`.

---

## 1. Purpose

A Python Discord bot that:

1. Answers **company policy / handbook** questions from a **query-only** Pinecone index (filled externally by n8n + Google Drive).
2. Manages **HR operations** in Discord: onboarding, private tickets, leave apply/approve, profiles, announcements.
3. Uses **MySQL** for live employee and leave data (not the vector index).

The Discord app **never writes to Pinecone** and **never calls n8n** during chat.

---

## 2. Tech stack

| Layer | Choice |
|-------|--------|
| Language | Python ≥ 3.12 |
| Discord | discord.py ≥ 2.4 |
| Config | python-dotenv, `.env` + `channels.json` |
| Embeddings | Google GenAI — `gemini-embedding-2` |
| Answers | OpenRouter — `google/gemma-4-31b-it` (Gemini `gemini-3.5-flash` fallback) |
| Vector DB | Pinecone index `document`, dim `3072`, cosine — **query only** |
| HR DB | MySQL via PyMySQL (`DATABASE_URL` or `MYSQL_*`) |
| HTTP | httpx (OpenRouter, SendGrid) |
| Mail | SendGrid API (`SENDGRID_API_KEY`) |
| Tests | pytest ≥ 8 |

Run entrypoint:

```powershell
python -m app.main
```

Only one process may run (`.bot.instance.lock`).

---

## 3. High-level architecture

```
                    Discord Gateway (discord.py)
                              │
                    app/discord/bot.py
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   Tickets / UI          Agent router            Channel ensure
   onboarding            app/agent/router.py     leave inboxes
   leave forms           │                       announcements
   profiles              ▼
                    Intent + scope
                    app/routing/*
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
     RAG pipeline                      HR services
     embed → Pinecone query            app/hr/* + app/records/*
     → OpenRouter/Gemini               MySQL (app/db/client.py)
```

### Design principles

- **Factory-style wiring** — `create_*` helpers return clients/services (`main.py` composes them).
- **Strict source split** — handbook → Pinecone; personal leave balance/apply → MySQL.
- **Ticket-first UX** — members chat in a private ticket, not in public channels.
- **Single instance** — exclusive file lock under the project root.
- **Query-only vectors** — ingestion is out of band (n8n).

---

## 4. Repository layout

```
app/
  main.py                 # Bootstrap: config, lock, Pinecone, MySQL, Discord
  config.py               # .env + channels.json → config dict
  process_lock.py         # Single-instance lock
  logger.py / errors.py / console.py / json_store.py
  discord/                # Gateway bot, tickets, leave UI/inbox, onboarding, announcements
  agent/                  # Ticket message router, extraction, verification, drafts
  routing/                # Channel namespaces, intent, WebAiry classifier, language, scope
  rag/                    # Retrieve + answer pipeline
  embeddings/             # Gemini embeddings
  generation/             # Prompts, OpenRouter, Gemini fallback, quality
  pinecone/               # Query client + metadata text extraction
  hr/                     # Leave, employees, departments, permissions, staff sync hooks
  records/                # MySQL domain helpers (employees, leave_*, holidays, announcements)
  db/                     # MySQL client + schema metadata
  mail/                   # Leave email (SendGrid) + notify helpers
  tickets/                # tickets.json store + helpers
  sessions/               # sessions.json ticket conversation memory
scripts/                  # Setup, sync, diagnostics (mostly query-only)
tests/                    # pytest suite
docs/                     # User guides + SOW + this document
channels.example.json     # Template for Discord IDs / namespaces
.env.example              # Environment template
```

Runtime JSON (local state, do not treat as source of truth for HR):

| File | Purpose |
|------|---------|
| `tickets.json` | Open/closed ticket channels per member |
| `sessions.json` | Last turns / topic / grounded answer per ticket |
| `leave_drafts.json` | In-progress leave form drafts |
| `.bot.instance.lock` | Process lock |

---

## 5. Bootstrap sequence (`app/main.py`)

1. `load_config()` — fail fast on missing required env.
2. `create_logger(logLevel)`.
3. `acquire_instance_lock(rootDir)`.
4. Unless `ECHO_MODE`: create Pinecone + Gemini embeddings + answer model; `describe_index` / stats; build RAG pipeline.
5. If MySQL configured: `create_mysql_client` → `create_hr_services`.
6. `create_discord_bot(config, logger, rag, hr)` → `bot.start(token)`.
7. On shutdown: `bot.close()`, `release_instance_lock`.

`ECHO_MODE=true` skips Pinecone/LLM and replies without retrieval (dev/smoke).

---

## 6. Configuration

### 6.1 Environment (`.env`)

See `.env.example`. Important groups:

| Group | Keys (representative) |
|-------|------------------------|
| Discord | `DISCORD_TOKEN`, optional `DISCORD_CLIENT_ID` |
| Pinecone | `PINECONE_API_KEY`, `PINECONE_INDEX_NAME=document` |
| Embeddings | `GEMINI_API_KEY`, `GEMINI_EMBEDDING_MODEL`, `GEMINI_EMBEDDING_TASK_TYPE` |
| Answers | `ANSWER_PROVIDER`, `OPENROUTER_API_KEY`, `OPENROUTER_ANSWER_MODEL` |
| RAG | `PINECONE_TOP_K`, `RELEVANCE_THRESHOLD` |
| MySQL | `DATABASE_URL` or `MYSQL_HOST` / `PORT` / `USER` / `PASSWORD` / `DATABASE` |
| HR roles | `HR_ROLE_ID`, `HR_ADMIN_ROLE_ID`, leave grant amounts |
| Branding | `COMPANY_NAME`, `ASSISTANT_NAME` |
| Mail | `SENDGRID_API_KEY`, `EMAIL_FROM_*`, `HR_LEAVE_TO` / `LEAVE_MAIL_HR`, `DRY_RUN` |

**Do not commit** `.env`, `channels.json`, `tickets.json`, or lockfiles with secrets.

### 6.2 Channels (`channels.json`)

Copy from `channels.example.json`. Structure:

```json
{
  "respondMode": "all",
  "tickets": {
    "categoryId": "...",
    "adminRoleId": "...",
    "staffRoleId": "...",
    "leaveReviewChannelId": "...",
    "hrCategoryId": "...",
    "hodCategoryId": "...",
    "hodChannels": { "BI": "...", "CS": "...", "Marketing": "..." },
    "hodRoleIds": { "BI": "...", "CS": "...", "Marketing": "..." },
    "onboardingChannelId": "...",
    "announcementChannelId": "...",
    "hrProfileChannelId": "...",
    "hrAnnouncementChannelId": "..."
  },
  "channels": {
    "<discord-channel-id>": "<pinecone-namespace>"
  }
}
```

- `channels` maps a Discord channel ID → Pinecone namespace (lowercased).
- Ticket category / leave / HOD / onboarding IDs can also be supplied via env fallbacks in `app/config.py`.
- On startup the bot can **ensure** (find/create) several channels if IDs are missing.

### 6.3 Discord intents & permissions

- **Message Content Intent:** on  
- **Guild Members Intent:** off (per product constraint)  
- Bot needs: View Channel, Send Messages, Read Message History, Manage Messages, Manage Channels (and role assignment for onboarding).

---

## 7. Discord surfaces

### 7.1 Categories

| Category | Contents |
|----------|----------|
| **Tickets** | Private `#ticket-…` channels |
| **HR** | `#leave-requests`, `#hr-profiles`, `#hr-announcements` (HR/Admin) |
| **HOD** | `#bi-hod`, `#cs-hod`, `#marketing-hod` (notify-only leave cards) |

### 7.2 Channel responsibilities

| Channel | Module(s) | Behavior |
|---------|-----------|----------|
| `#onboarding` | `discord/onboarding.py` | Start Onboarding → 2 forms → dept/level → role + employee row |
| `#open-ticket` | `discord/tickets.py` | Persistent **Open ticket** panel |
| Ticket channel | `discord/bot.py`, `agent/router.py` | RAG + leave + cancel/withdraw |
| `#leave-requests` | `discord/leave_inbox.py`, `leave_review.py` | HR/Admin Approve / Reject |
| `#bi-hod` / `#cs-hod` / `#marketing-hod` | `leave_inbox.py` | Same leave card, **no buttons** |
| `#hr-profiles` | `discord/profile_lookup.py` | `/profile`, edit, `/deleteprofile` |
| `#hr-announcements` | `discord/hr_announcements.py` | Schedule / cancel announcements |
| `#announcements` | `discord/announcements.py` | Public posts + birthday loop |

### 7.3 Persistent UI custom IDs (representative)

`ticket:open`, `ticket:close`, `leave:submit`, `leave:cancel`, `leave:fill`, `leave:type`, `leave:withdraw`, `leave:cancel:*`, `leave:review:approve`, `leave:review:reject`, onboarding button IDs.

Views are registered as persistent where needed so they survive restarts.

---

## 8. Product flows (technical)

### 8.1 Onboarding

1. Ensure `#onboarding` overwrites: `@everyone` can see; workplace roles hidden; HR/Admin visible.
2. Modal step 1: name, contact, CNIC.  
3. Modal step 2: email, DOB, address.  
4. Department select → level (Member/HOD for BI/CS/Marketing).  
5. Assign Discord role; upsert employee + leave quota (except CS/Sales Member — no leave quota).  
6. Hide onboarding for that member.

**Roles:** `BI Member`, `BI HOD`, `CS Member`, `CS HOD`, `Marketing Member`, `Marketing HOD`, `Sales Member`, `HR`.

Corrections after onboarding: HR in `#hr-profiles` (no employee self-service department change).

### 8.2 Tickets

1. Member clicks **Open ticket** in `#open-ticket`.  
2. Bot creates or reopens a private channel under **Tickets** (owner + bot + Admin).  
3. Greeting embed + **Close ticket**.  
4. Messages go through the agent router.  
5. Close locks send; reopen reuses the same channel.  
6. `/leave` (Admin/HR) sets `botActive=false` so humans can talk without bot replies.  
7. Closing clears the ticket session in `sessions.json`.

HODs/Staff do not see other members’ tickets. A HOD may open their **own** ticket.

### 8.3 Leave apply → notify → decide

```
Ticket (employee)
  → agent detects leave apply
  → leave form UI (Annual / Sick / Casual)
  → LeaveService.create_pending_request → MySQL (status PENDING_HR)
  → publish_leave_inbox:
        #leave-requests  + LeaveReviewView (Approve/Reject)
        #*-hod           + embed only (if department has HOD inbox)
  → optional DMs to reviewers
  → on decision: update MySQL, DM employee, SendGrid mail (approve/cancel)
```

**Authoritative rules (current code):**

- Every new request is created as **`PENDING_HR`**.  
- HOD channels are **view-only notifications** posted in parallel; they are not a decision queue.  
- Only HR/Admin Approve/Reject in `#leave-requests`.  
- One open (pending) request per Discord user.  
- **CS Member** and **Sales Member**: leave apply and balance blocked (`app/hr/leave_access.py`).  
- Withdraw while pending; cancel approved via ticket form (`list_cancellable_approved`).

Legacy status constants (`PENDING_MANAGER`, two-step helpers in `leave_status.py`) may still exist for older rows; new creates follow HR-only decision + HOD notify.

### 8.4 Announcements

- HR types a trigger in `#hr-announcements` → Create announcement modal (title, date, time PKT, description) → row in `hr_announcements`.  
- Background task posts to `#announcements` at schedule; cancel flow removes upcoming items.  
- Separate birthday task posts greetings to `#announcements` from employee DOBs.

---

## 9. Agent & routing

### 9.1 Ticket router (`app/agent/router.py`)

Central orchestrator for ticket text:

- Leave form continuation vs new question.  
- Balance / apply / withdraw / cancel-approved detection.  
- Human-HR escalation phrases.  
- Otherwise RAG / policy pipeline.  
- Blocks second leave while one is PENDING.  
- Uses ticket **owner** Discord ID for HR lookups (even if Admin typed).

Supporting pieces:

| Module | Role |
|--------|------|
| `agent/extraction.py` | Dates, leave type, reason snippets |
| `agent/verification.py` | Guardrails before submit |
| `agent/schemas.py` | Structured leave/draft shapes |
| `agent/draft_store.py` | Persist drafts (`leave_drafts.json`) |
| `agent/tools.py` | Tool-style helpers for the router |

### 9.2 Intent stack (`app/routing/`)

| Module | Role |
|--------|------|
| `webairy.py` | First-pass labels: `RAG_KNOWLEDGE`, `LEAVE_READ`, `LEAVE_WRITE`, `MIXED`, `HUMAN_HR`, `CLARIFY`, `SMALL_TALK` |
| `intent.py` | Maps to POLICY / LEAVE_BALANCE / LEAVE_REQUEST / etc. |
| `data_source.py` | Handbook vs live leave vs escalate |
| `channels.py` | Namespace + respond mode |
| `language.py` | english / roman / urdu / mix reply language |
| `scope.py` | What the bot will/won’t answer |
| `questions.py` / `roman_urdu.py` | Phrase helpers |

**Source split (must stay true):**

| Question type | Source |
|---------------|--------|
| Company leave policy / handbook | Pinecone RAG |
| “How many leaves do *I* have?” | MySQL leave balances |
| Leave apply / cancel / withdraw | MySQL leave_requests |
| Salary amount / live attendance punches | Escalate to human HR |
| Small talk / greetings | No retrieve (scoped reply) |

### 9.3 Sessions (`app/sessions/`)

Per-ticket memory in `sessions.json` (recent turns, last topic, last grounded answer) so follow-ups like “in detail” / “give me again” reuse context. Cleared on ticket close.

---

## 10. RAG pipeline

**Path:** `app/rag/pipeline.py` → embed (`embeddings/gemini.py`) → query (`pinecone/client.py`) → generate (`generation/*`).

Behavior highlights:

- Social / about-bot paths skip or use self-mode (identity: **HR Assistant** / `COMPANY_NAME`).  
- Below `RELEVANCE_THRESHOLD` → scoped refusal (no general-knowledge dump).  
- Policy prompts synthesize matching handbook points; keep exact terms/numbers; match user language.  
- OpenRouter primary; Gemini fallback on provider cooldown/errors (`generation/__init__.py`).  
- Namespace comes from the channel map associated with the ticket’s entry context.  
- Ignore Pinecone `record_type=namespace_marker`; chunk text from metadata `text`.

**Hard constraints (do not change unless explicitly requested):**

| Setting | Value |
|---------|-------|
| Index | `document` |
| Dimension | `3072` |
| Metric | cosine |
| Embedding model | `gemini-embedding-2` |
| Answer model | `google/gemma-4-31b-it` |

---

## 11. HR data layer (MySQL)

### 11.1 Client

- `app/db/client.py` — PyMySQL wrapper shaped like the former Airtable client (list/get/create/update).  
- `app/db/schema.py` — table names, columns, link/bool/date field metadata.  
- `app/records/*` — domain functions (`employees`, `leave_types`, `leave_balances`, `leave_requests`, `leave_utilization`, `holidays`, `discord_roles`, `hr_announcements`).

### 11.2 Tables (logical → physical)

| Logical key | Table |
|-------------|-------|
| employees | `employees` |
| leaveTypes | `leave_types` |
| leaveBalances | `leave_balances` |
| leaveRequests | `leave_requests` |
| leaveUtilization | `leave_utilization` |
| holidays | `holidays` |
| discordRoles | `discord_roles` |
| hrAnnouncements | `hr_announcements` |

Attendance punch table is **not** used; attendance **policy** still comes from the handbook via RAG.

### 11.3 HR services (`app/hr/`)

| Module | Responsibility |
|--------|----------------|
| `leave_service.py` | Create pending, approve/reject, cancel, balances, day counting |
| `leave_access.py` | CS/Sales Member gates |
| `leave_status.py` | Status constants / legacy stage helpers |
| `departments.py` | BI/CS/Marketing aliases, HOD matching |
| `employee_service.py` | Employee lookups / updates |
| `staff_onboard.py` | Role → employee upsert / quota grants |
| `permissions.py` | HR/Admin/manager tier checks |
| `workdays.py` / `dates.py` | Working-day math, holidays |
| `attendance_service.py` | Residual/helpers (no live punch feed) |

Default leave grants for new eligible employees (env): Annual 16, Sick 8, Casual 8.

---

## 12. Mail

- `app/mail/sendgrid.py` — HTTP send.  
- `app/mail/leave.py` — branded HTML + plain text for approved / cancelled leave.  
- `app/mail/notify.py` — orchestration (To / Cc).  

Typical addressing:

- **To:** `HR_LEAVE_TO` / `LEAVE_MAIL_HR` (and/or active HR emails as implemented).  
- **Cc:** department HOD email from employee records when available.  
- `DRY_RUN=true` logs instead of sending.

Discord DMs for leave decisions: `app/discord/notify.py`.

---

## 13. Key Discord modules (quick index)

| File | Role |
|------|------|
| `bot.py` | Events, slash commands, message dispatch, startup ensure-* |
| `tickets.py` | Open/close/reopen, permissions, panel |
| `messages.py` | Split long replies, formatting |
| `leave_ui.py` | Apply/cancel forms, pending cards, withdraw |
| `leave_inbox.py` | Ensure HR/HOD channels; publish notify + HR review |
| `leave_review.py` | Approve/Reject view |
| `onboarding.py` | Self-service join flow |
| `profile_lookup.py` | HR profile tools |
| `announcements.py` | Public channel + birthdays |
| `hr_announcements.py` | HR schedule/cancel |
| `attachments.py` | Leave/reason file handling |
| `journey.py` | Guided copy / journey helpers |

---

## 14. Scripts

| Script | Use |
|--------|-----|
| `scripts/setup_mysql.py` | Create/seed MySQL schema |
| `scripts/reset_database.py` | Reset DB (destructive — ops only) |
| `scripts/sync_discord_staff.py` | Upsert employees from Discord roles |
| `scripts/strip_cs_sales_leave.py` | Wipe leave rows for blocked roles |
| `scripts/apply_hod_permissions.py` | Align HOD channel overwrites |
| `scripts/move_leave_inboxes.py` | Move leave channels into HR/HOD categories |
| `scripts/setup_leave_mail.py` / `sync_reviewer_emails.py` | Mail-related setup |
| `scripts/inspect_pinecone.py` | Index diagnostics |
| `scripts/test_embed.py` / `test_retrieve.py` / `test_answer.py` / `test_suite.py` | Query-only RAG diagnostics |

Prefer query-only diagnostics against production indexes; do not recreate the Pinecone index from this app.

---

## 15. Tests

Run:

```powershell
pytest
```

Notable suites under `tests/`:

- Helpers / intent / routing (`test_python_helpers.py`, `test_webairy_router.py`)  
- Leave workflow, inbox, HOD notify, access gates, cancel form, mail, SendGrid  
- Onboarding, announcements, MySQL client, sessions, reliability  

Tests are intended to avoid live Discord/Pinecone network where possible; HR tests use fakes or local DB fixtures as written.

---

## 16. Security & privacy notes

- Never expose API keys, Pinecone scores, namespaces, or model names in user-facing Discord text.  
- Ticket channels are private; leave inbox cards avoid leaking internal Airtable-style IDs / raw file URLs where polished.  
- `/deleteprofile` wipes MySQL employee + leave data and may kick the Discord member — HR/Admin only, with confirmation; self-delete blocked.  
- Secrets stay in `.env` (SendGrid, Discord, Gemini, OpenRouter, Pinecone, MySQL).

---

## 17. Operational runbook

### 17.1 Local setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# Copy .env.example → .env and channels.example.json → channels.json; fill IDs/secrets
python scripts/setup_mysql.py   # if schema needed
python -m app.main
```

### 17.2 Health checks

- Logs show Pinecone connect (index, dimension, namespaces) and MySQL ready.  
- Second process should fail on instance lock.  
- `#open-ticket` panel reappears on `on_ready`.  
- Leave submit appears in `#leave-requests` and matching `#*-hod` when applicable.

### 17.3 Common failure modes

| Symptom | Likely cause |
|---------|----------------|
| No RAG answers | `ECHO_MODE`, missing Pinecone/Gemini/OpenRouter keys, bad namespace map |
| Leave disabled unexpectedly | CS/Sales Member role or missing employee link |
| No HOD card | Department not BI/CS/Marketing, or HOD channel ensure failed |
| No email | `SENDGRID_API_KEY` / `DRY_RUN` / missing `HR_LEAVE_TO` |
| Empty `#open-ticket` | Startup race; panel posts at start of `on_ready` |

---

## 18. Non-goals / out of scope

- Writing to Pinecone or calling n8n from this runtime  
- HOD as leave approver in Discord (notify-only)  
- Unpaid leave on the employee form  
- Live attendance punch integration  
- Public-channel Q&A as the primary UX (ticket-only answers)  
- Changing embedding/answer models or index dimensions without an explicit product decision  

---

## 19. Related documentation

| Doc | Audience |
|-----|----------|
| `README.md` | Quick start |
| `docs/technical-documentation.md` | Engineers (this file) |
| `docs/user-guide-members-hod.md` | Members & HODs |
| `docs/user-guide-hr.md` | HR operators |
| `docs/sow-updates-current-flow.md` | SOW / contract alignment |
| `project-brain/memory/*` | Agent engineering memory (internal) |

---

*Reflects the current codebase: MySQL HR store, Pinecone query-only RAG, HOD leave notify-only, SendGrid leave mail, Discord ticket UX.*

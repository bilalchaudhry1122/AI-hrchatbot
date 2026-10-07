# Frontend (Discord UX)

There is no web UI. “Frontend” means Discord surfaces.

## Surfaces

- `#open-ticket`: view + history only for @everyone; one **Open ticket** panel (no Close). If a ticket is already open, Open ticket shows an ephemeral notice with the channel. Delete+repost panel at the **start** of `on_ready` (before Airtable backfill) so Discord does not show the empty-channel Getting Started page. Suppress/delete join welcomes.
- Ticket GuildText channels under **Tickets** category: bot + ticket owner + Admin. HODs and the Staff role cannot see anyone else’s ticket. A HOD may open their own ticket for leave or questions; that leave goes to `#leave-requests` for HR. Opening a ticket posts the greeting embed plus Close ticket (no employee directory in the greeting). Asking **who is in BI / CS / Marketing / HR** (or similar) posts that department’s roster with name, designation, and photo when on disk. The ping is the member mention only; the card already says the ticket is private. **Close ticket** is posted once when the ticket opens (or is reopened from closed). It is not moved after later messages. Staff/Admin/owner close later with `/close`. Close replies immediately with **Closed by {name} · {role}** (no public “thinking…” placeholder). Embed footers cannot ping, so the closer is a name, not `<@id>`.
- Buttons: persistent view custom_ids `ticket:open`, `ticket:close`, `leave:submit`, `leave:cancel`, `leave:fill`, `leave:type`, `leave:withdraw`, `leave:cancel:fill`, `leave:cancel:submit`, `leave:cancel:dismiss`, `leave:review:approve`, `leave:review:reject`.
- Cancel approved leave is a ticket form (not `/cancelleave`). Phrases like “cancel my leave” open it only when there is upcoming approved leave; otherwise the bot says there is no leave to cancel (no empty form). The submit button is **Submit**. Ticket owner only.
- Ticket answers are posted as new messages, not Discord replies, so replacing a leave card does not leave “Message could not be loaded”. Pending leave cards are edited in place instead of delete-and-repost. Applying for leave also posts the matching policy line (if any) and the leave form together. Only **one form** is kept in the ticket. Leave-balance embeds use the **ticket owner’s name** (the person whose balance was asked), e.g. “Abdullah's live leave balance”.
- Decline reason modal also has optional attachments. Those files are shown on the card and sent to the employee.
- `#leave-requests` lives in an **HR** category (Admin/HR only). One day before an employee's birthday (11:00 AM Pakistan time), the bot posts a **cake reminder** here with their name, Discord mention, address, and contact number. Public `#announcements` still get the greeting on the birthday itself (no address/contact). `#bi-hod`, `#cs-hod`, `#marketing-hod` live in a separate **HOD** category. Inbox cards do not show ticket or user ids. **Approved by** is the Discord handle (`@username`). Ticket field is the employee name plus `#ticket-…` text.
- `/leave` is **Admin or HR only** — sets `botActive=false`. Leave is decided with **Approve / Reject** on the `#leave-requests` and HOD channel cards (not `/granted` / `/rejected`). After a decision the employee is DMed. `/close` for ticket owner, Staff, or Admin.
- `#onboarding`: Start Onboarding → step 1 (name, contact, CNIC) → Continue → step 2 (email, DOB, address) → department → **designation** → optional **photo**. Photo is saved under `data/employee-photos/` and the relative path is stored on the employee row (`Photo Path`). Discord CDN URLs are not used (they expire). Image bytes are not stored in MySQL. Discord role is always `{Dept} Member` or **HR**; a second role `{Dept} · {designation}` is created/assigned under that department. **HOD is not on the form**. After success, welcome in `#announcements`. HR `/profile` shows the photo when the file is on disk.
- `#hr-profiles`: HR/Admin only. `/profile` look up + edit (step 1 name/contact/CNIC, step 2 email/DOB/address/designation). `/deleteprofile` wipes DB and kicks. Day-to-day HR steps: `docs/user-guide-hr.md`.
- Identity: the assistant is **HR Assistant** (Discord username and nickname too). `COMPANY_NAME` defaults to WebAiry. “Who are you?” must not use the Discord server name.
- Assigning **BI Member / CS Member / Marketing Member / Sales Member**, **BI HOD / CS HOD / Marketing HOD**, **Admin/HR**, Staff, or any role whose name contains **Member** upserts that person into Employees (leave quota on first create). Any later role add/remove/rename updates **Discord Roles** on that employee. A new Discord role is written to the Airtable **Discord Roles** table as soon as it is created, and again whenever someone is given that role. Startup resyncs workplace-role holders and anyone already in Employees.
- Mentions in `#open-ticket` ignored when `respondMode` is `slash`. `/ask` unused.

HR answers in a ticket use the **ticket owner** Discord User ID (Airtable), not whoever typed if Admin is helping.

## Files

- `app/discord/onboarding.py` — self-service form, role, employee row, then `#announcements` welcome
- `app/discord/announcements.py` — `#announcements` (birthdays + onboard welcome)
- `app/discord/bot.py` — events, commands, RAG replies in tickets
- `app/discord/profile_lookup.py` — `/profile` + `/deleteprofile` in `#hr-profiles`
- `app/discord/notify.py` — DM the employee on leave approve/reject/cancel/withdraw
- `app/mail/` — one email after leave is fully approved, and again if cancelled. **To** is every active employee with HR Role (or Discord HR) and an Email. **Cc** is that department’s HOD Email, or the HOD’s own Email if their Discord User ID is on the card. SMTP env is only for sending, not for To/Cc.
- `app/discord/leave_inbox.py` — `#leave-requests` plus `#bi-hod` / `#cs-hod` / `#marketing-hod`
- `app/hr/departments.py` — BI / CS / Marketing aliases and HOD role matching
- `app/discord/leave_review.py` — Approve/Reject view on leave inbox cards
- `app/discord/leave_ui.py` — leave confirm/pending embeds and buttons. If dates overlap approved leave, the same card is re-posted with a hint; Fill form / Submit remain so the staff member can change From/To.
- `app/discord/tickets.py` — create/reopen/close, permissions, panel
- `app/discord/messages.py` — split long replies, format answers

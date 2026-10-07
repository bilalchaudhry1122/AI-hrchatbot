# Completed

---
Task: Fix onboarding welcome + photo
Date: 2026-10-07
Type: bugfix
Files Changed: app/discord/announcements.py, app/discord/onboarding.py, channels.json, tests/test_onboarding_overhaul.py
Modules Changed: discord_announcements, discord_onboarding
Summary: Welcome no longer no-ops when announcement channel id missing after overwrite edit; photo/finalize defer so Discord interactions do not time out.
---
Task: Department roster on ask (not in greeting)
Date: 2026-10-07
Type: feature
Files Changed: app/discord/team_directory.py, app/discord/tickets.py, app/discord/bot.py, app/agent/router.py, app/hr/departments.py, app/discord/journey.py, tests/test_team_directory.py, docs/user-guide-hr.md
Modules Changed: discord_tickets, agent_router, hr_departments
Summary: Removed Meet your teammates from ticket open. Roster (name, designation, photo) posts only when the user asks who is in BI/CS/Marketing/HR/Sales.
---
Task: Revert push commit
Date: 2026-10-07
Type: config
Files Changed: none (git reset only)
Modules Changed: none
Summary: Mixed-reset removed `63963b2` from main; feature diffs remain uncommitted. Remote current-flow was already gone.
---
Task: Push latest changes to AI-hrchatbot
Date: 2026-10-07
Type: docs
Files Changed: (commit 63963b2 on main; remote branch current-flow)
Modules Changed: none
Summary: Committed designation/photo/team-directory/HR guide work; pushed clean snapshot to AI-hrchatbot/current-flow without .env. Did not force-update remote main.
---
Task: Start local Discord bot
Date: 2026-10-07
Type: config
Files Changed: none
Modules Changed: none
Summary: Cleared stale instance lock if present and started `python -u -m app.main`; bot reached ready.
---
Task: HR user guide markdown (current flow)
Date: 2026-10-06
Type: docs
Files Changed: docs/user-guide-hr.md
Modules Changed: none
Summary: Full HR/Admin guide covering new onboarding, HOD assignment, team directory, leave-balance name, and birthday cake reminders.
---
Task: First-ticket team directory greeting
Date: 2026-10-06
Type: feature
Files Changed: app/discord/team_directory.py, app/discord/tickets.py, app/discord/bot.py, tests/test_team_directory.py
Modules Changed: discord_tickets
Summary: New tickets get a Meet your teammates list (name, department, designation, photo) after the welcome card. Reopens do not repeat it.
---
Task: Onboarding profile photo (disk + Photo Path)
Date: 2026-10-06
Type: feature
Files Changed: app/discord/onboarding.py, app/records/employee_photos.py, app/records/employees.py, app/hr/staff_onboard.py, app/db/schema.py, app/db/client.py, app/discord/profile_lookup.py, scripts/schema_mysql.sql, scripts/setup_mysql.py, scripts/reset_database.py, .gitignore, tests/test_employee_photos.py, tests/test_onboarding_overhaul.py
Modules Changed: discord_onboarding, records, mysql_client
Summary: Joiners can attach a photo or skip. File saved under data/employee-photos/; employees.Photo Path holds the relative path. HR /profile attaches the file.
---
Task: Leave-balance embed shows asker name
Date: 2026-10-06
Type: feature
Files Changed: app/discord/leave_ui.py, app/discord/bot.py, app/discord/leave_review.py, app/agent/router.py, tests/test_hr.py
Modules Changed: discord_leave_ui, agent_router
Summary: Balance card title/author is the employee whose balance was requested (ticket owner).
---
Task: HR birthday-eve cake reminder in leave inbox
Date: 2026-10-06
Type: feature
Files Changed: app/discord/announcements.py, tests/test_onboarding_overhaul.py
Modules Changed: discord_announcements, discord_leave_inbox
Summary: Day before a birthday, #leave-requests gets a cake reminder with name, address, and contact. Public announcements stay PII-free.
---
Task: Onboarding designation instead of Member/HOD dropdown
Date: 2026-10-06
Type: feature
Files Changed: app/discord/onboarding.py, app/discord/announcements.py, app/discord/profile_lookup.py, app/hr/staff_onboard.py, app/records/employees.py, app/db/schema.py, app/db/client.py, scripts/schema_mysql.sql, scripts/setup_mysql.py, scripts/reset_database.py, tests/test_onboarding_overhaul.py
Modules Changed: discord_onboarding, discord_announcements, mysql_client, hr_services
Summary: Joiners type a designation after department. Discord role is always Member/HR; `{Dept} · {designation}` is assigned. HOD remains HR/Admin-only.
---
Task: Onboarding welcome in #announcements
Date: 2026-10-06
Type: feature
Files Changed: app/discord/announcements.py, app/discord/onboarding.py, tests/test_onboarding_overhaul.py
Modules Changed: discord_onboarding, discord_announcements
Summary: After a successful #onboarding finish, post a public welcome (mention, name, role) in #announcements. Post failure does not undo onboarding.
---
Task: Full project technical documentation
Date: 2026-10-05
Type: docs
Files Changed: docs/technical-documentation.md
Modules Changed: docs
Summary: End-to-end engineering doc — stack, architecture, config, Discord flows, agent/RAG, MySQL HR, leave/HOD notify-only, mail, scripts, tests, ops runbook.
---
Task: SOW updates MD for current flow
Date: 2026-10-05
Type: docs
Files Changed: docs/sow-updates-current-flow.md
Modules Changed: docs
Summary: Full SOW amendment guide — onboarding/change, HOD notify-only leave, all HR/HOD/public channels, leave eligibility, announcements, copy-paste SOW text and acceptance criteria.
---
Task: User guides for HR and Members/HODs
Date: 2026-09-24
Type: docs
Files Changed: docs/user-guide-members-hod.md, docs/user-guide-hr.md
Modules Changed: docs
Summary: Two non-technical Discord guides covering onboarding role selection, tickets, questions, leave apply/balance/withdraw/cancel, and HR tools.
---
Task: Remove Unpaid Leave completely
Date: 2026-09-24
Type: feature
Files Changed: app/discord/leave_ui.py, scripts/setup_mysql.py, app/records/leave_types.py, app/agent/*, app/routing/*, app/hr/staff_onboard.py, tests/*, MySQL leave_types
Modules Changed: discord_leave_ui, records, agent_router, routing_intent, hr_services
Summary: Dropdown/seed/NLP no longer offer Unpaid; deleted UNPAID from live leave_types; kept is_unpaid() for old rows.
---
Task: Disable leave for CS Member & Sales Member
Date: 2026-09-23
Type: feature
Files Changed: app/hr/leave_access.py, leave_service.py, staff_onboard.py, agent/router.py, discord/bot.py, onboarding.py, records/employees.py, scripts/strip_cs_sales_leave.py, tests/test_leave_access.py
Modules Changed: hr_services, agent_router, discord_bot
Summary: CS/Sales Member blocked from leave apply and balance; no quota on onboard; wipe script for leave rows.
---
Task: Onboarding draft on validation errors
Date: 2026-09-23
Type: feature
Files Changed: app/discord/onboarding.py, tests/test_onboarding_overhaul.py
Modules Changed: discord_bot
Summary: Format/submit errors keep filled values; Edit & try again (and Start) reopen modals prefilled.
---
Task: Birthday wishes at 4:20 PM PKT
Date: 2026-09-23
Type: config
Files Changed: app/discord/announcements.py, tests/test_onboarding_overhaul.py
Modules Changed: discord_bot
Summary: Daily birthday posts in #announcements moved from 11:00 to 16:20 Pakistan time.
---
Task: Smarter grounded policy answers
Date: 2026-09-23
Type: feature
Files Changed: app/generation/prompt.py, tests/test_python_helpers.py
Modules Changed: generation_prompt
Summary: Knowledge/mixed prompts understand the question, combine matching policy points, answer like HR — not paste or topic menus.
---
Task: Policy answers match question language
Date: 2026-09-23
Type: feature
Files Changed: app/routing/language.py, app/generation/prompt.py, tests/test_python_helpers.py
Modules Changed: routing_intent, generation_prompt
Summary: Policy RAG replies in English, Roman Urdu, or Urdu script matching the question; facts/numbers stay faithful.
---
Task: /deleteprofile in #hr-profiles
Date: 2026-09-23
Type: feature
Files Changed: app/records/employees.py, app/discord/profile_lookup.py, app/discord/bot.py, tests/test_onboarding_overhaul.py
Modules Changed: discord_bot, employees
Summary: HR/Admin can delete a profile (DB wipe of employee + leave data) and kick the member. Confirm UI; self-delete blocked.
---
Task: Remove Airtable; MySQL only
Date: 2026-09-23
Type: refactor
Files Changed: app/records/*, app/config.py, app/main.py, scripts/*, .env.example, requirements.txt; deleted app/airtable, setup/migrate Airtable scripts
Modules Changed: airtable_client→records+mysql, config, hr_services
Summary: Confirmed migration then removed Airtable dependency and dual backend. Live HR data is MySQL only.
---
Task: Migrate Airtable HR data to MySQL
Date: 2026-09-23
Type: feature
Files Changed: app/db/*, scripts/schema_mysql.sql, scripts/setup_mysql.py, scripts/migrate_airtable_to_mysql.py, app/config.py, app/main.py, requirements.txt, .env.example, tests/test_mysql_client.py
Modules Changed: airtable_client, config, hr_services
Summary: Drop-in MySQL client matching Airtable API shape. User sets MYSQL_* and DB_BACKEND=mysql, runs setup then migrate.
---
Task: Policy answers with balanced document detail
Date: 2026-09-22
Type: bugfix
Files Changed: app/routing/language.py, app/generation/prompt.py, app/sessions/followup.py, app/agent/router.py, tests/test_session.py, tests/test_python_helpers.py
Modules Changed: routing_intent, generation_prompt, session_store, agent_router
Summary: Named policy asks get 3–6 document sentences (not a topic menu). Expand follow-ups like "in detail" re-retrieve the prior handbook topic.
---
Task: Policy answers extract the relevant part only
Date: 2026-09-22
Type: feature
Files Changed: app/routing/language.py, app/generation/prompt.py, tests/test_python_helpers.py
Modules Changed: routing_intent, generation_prompt
Summary: policy_language_rules and the knowledge-mode prompt now tell the model to answer only the
part of the reference text the question is about (still verbatim numbers/terms for what is included)
and invite a follow-up for more detail, instead of pasting the entire policy chunk.
---
Task: Restore Open ticket panel on startup
Date: 2026-09-22
Type: bugfix
Files Changed: app/discord/bot.py
Modules Changed: discord_bot
Summary: Post the #open-ticket card before Airtable backfill. Timeout guild.edit so startup cannot leave the channel empty.
---
Task: Update Airtable from new Discord roles
Date: 2026-09-22
Type: config
Files Changed: scripts/sync_discord_staff.py, app/hr/staff_onboard.py, tests/test_staff_sync.py
Modules Changed: scripts, hr_services
Summary: Sync accepts HR without Admin. Live roster written. People with no staff role marked Inactive.
---
Task: Remove leave-mail footer buttons
Date: 2026-09-22
Type: feature
Files Changed: app/mail/leave.py, tests/test_leave_mail.py
Modules Changed: mail
Summary: Footer keeps security + copyright only.
---
Task: Round leave-mail header and footer
Date: 2026-09-22
Type: feature
Files Changed: app/mail/leave.py, tests/test_leave_mail.py
Modules Changed: mail
Summary: Purple header/footer use 22px corner radius.
---
Task: Solid purple leave-mail header for Outlook
Date: 2026-09-22
Type: bugfix
Files Changed: app/mail/leave.py, tests/test_leave_mail.py
Modules Changed: mail
Summary: Header/footer bgcolor so the logo is visible on a white inbox.
---
Task: Brand leave approve/cancel mail
Date: 2026-09-22
Type: feature
Files Changed: app/mail/leave.py, tests/test_leave_mail.py
Modules Changed: mail
Summary: Approved and cancelled HTML wrap in WebAiry header and footer.
---
Task: Attendance policy from handbook; Airtable only for leave
Date: 2026-09-22
Type: bugfix
Files Changed: app/routing/webairy.py, app/agent/router.py, greetings/copy, tests
Modules Changed: routing_webairy, agent_router
Summary: Attendance policy no longer hits Airtable. Leave apply skips RAG. Greeting is policy + leave.
---
Task: Stop degenerate policy dumps
Date: 2026-09-22
Type: bugfix
Files Changed: app/rag/pipeline.py, app/routing/scope.py, app/generation/quality.py, app/agent/verification.py, app/generation/prompt.py, tests
Modules Changed: rag_pipeline, generation, routing
Summary: Broad policy asks list topics; looped model text is replaced.
---
Task: Company policy questions retrieve the handbook
Date: 2026-09-22
Type: bugfix
Files Changed: app/agent/verification.py, app/rag/query.py, app/routing/webairy.py, tests/test_hr.py
Modules Changed: agent_router, rag_pipeline, routing_webairy
Summary: Bare “company policy” asks expand and retry Pinecone instead of no_answer greeting.
---
Task: Hard-code HR leave To in LEAVE_MAIL_HR
Date: 2026-09-22
Type: config
Files Changed: app/config.py, app/mail/leave.py, .env, .env.example, tests/test_leave_mail.py
Modules Changed: config, mail
Summary: Approved/cancel To is env LEAVE_MAIL_HR; HOD Cc still Airtable.
---
Task: Clean Employees to current Discord roles
Date: 2026-09-22
Type: config
Files Changed: Airtable Employees (Khadija, Shahzaib, Faizan)
Modules Changed: none
Summary: HR Role / Status now match Discord. No code change.
---
Task: Leave mail recipients from Airtable, not LEAVE_MAIL_* env
Date: 2026-09-21
Type: feature
Files Changed: app/mail/leave.py, app/config.py, .env, .env.example, tests/test_leave_mail.py, scripts/sync_reviewer_emails.py
Modules Changed: mail, config
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Remove duplicate privacy ping; salary disclose from policy; fix sick reasons
Date: 2026-09-21
Type: bugfix
Files Changed: app/discord/journey.py, app/routing/webairy.py, app/agent/extraction.py, tests
Modules Changed: discord_tickets, routing_webairy, agent_router
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Cancel Submit, policy+form, no embed ids, no empty cancel card
Date: 2026-09-21
Type: bugfix
Files Changed: app/discord/leave_ui.py, app/discord/leave_inbox.py, app/discord/leave_review.py, app/discord/journey.py, app/discord/bot.py, app/agent/router.py, app/routing/webairy.py, tests
Modules Changed: discord_leave_ui, discord_leave_inbox, discord_bot, agent_router, routing_webairy
Review Score: 93
Memory Updated: yes
Graph Updated: no
---
Task: Set Bilal Chaudhry as HR in Airtable and confirm HOD emails
Date: 2026-09-21
Type: config
Files Changed: .env, Airtable Employees
Modules Changed: airtable_client, mail
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Send approved and cancelled leave mail when HR inbox env is empty
Date: 2026-09-21
Type: bugfix
Files Changed: app/mail/leave.py, app/mail/notify.py, app/mail/smtp.py, tests/test_leave_mail.py
Modules Changed: mail
Review Score: 93
Memory Updated: yes
Graph Updated: no
---
Task: Do not Discord-reply to embeds; edit pending leave cards in place
Date: 2026-09-21
Type: bugfix
Files Changed: app/discord/bot.py, app/discord/leave_ui.py
Modules Changed: discord_bot, discord_leave_ui
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Remove /granted and /rejected slash commands
Date: 2026-09-21
Type: feature
Files Changed: app/discord/bot.py, app/discord/leave_review.py
Modules Changed: discord_bot, discord_leave_review
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Ticket opens with only the greeting embed
Date: 2026-09-21
Type: bugfix
Files Changed: app/discord/tickets.py
Modules Changed: discord_tickets
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Cc department HOD on cancel-leave mail
Date: 2026-09-21
Type: bugfix
Files Changed: app/mail/leave.py, app/mail/notify.py, tests/test_leave_mail.py
Modules Changed: mail
Review Score: 93
Memory Updated: yes
Graph Updated: no
---
Task: Email HR (Cc approving HOD) when approved leave is cancelled
Date: 2026-09-21
Type: feature
Files Changed: app/mail/leave.py, app/mail/notify.py, app/hr/leave_service.py, app/discord/leave_ui.py, app/discord/bot.py, tests/test_leave_mail.py
Modules Changed: mail, hr_services, discord_leave_ui
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Cancel form shows approved leaves to pick, no copy-paste
Date: 2026-09-21
Type: feature
Files Changed: app/discord/leave_ui.py, app/agent/router.py, app/hr/leave_service.py, tests/test_cancel_leave_form.py
Modules Changed: discord_leave_ui, agent_router
Review Score: 93
Memory Updated: yes
Graph Updated: no
---
Task: Replace /cancelleave with an approved-leave cancel form
Date: 2026-09-21
Type: feature
Files Changed: app/discord/bot.py, app/discord/leave_ui.py, app/discord/journey.py, app/agent/router.py, app/agent/verification.py, app/hr/leave_service.py, app/routing/scope.py, tests
Modules Changed: discord_bot, discord_leave_ui, agent_router, hr_services
Review Score: 93
Memory Updated: yes
Graph Updated: no
---
Task: Rename Discord bot to HR Assistant
Date: 2026-09-21
Type: feature
Files Changed: app/discord/bot.py, app/config.py, app/generation/prompt.py, app/routing/intent.py, app/discord/tickets.py, .env.example, tests
Modules Changed: discord_bot, generation, config
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Separate Discord categories for HR and HOD leave inboxes
Date: 2026-09-17
Type: feature
Files Changed: app/discord/leave_inbox.py, app/config.py, channels.example.json, scripts/move_leave_inboxes.py, scripts/apply_hod_permissions.py, tests/test_hod_flow.py
Modules Changed: discord_leave_inbox, config
Review Score: 93
Memory Updated: yes
Graph Updated: no
---
Task: Auto-fill leave reason from the user prompt
Date: 2026-09-17
Type: bugfix
Files Changed: app/agent/extraction.py, app/agent/router.py, tests/test_hr.py
Modules Changed: agent_router
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Keep leave form files on the card only
Date: 2026-09-17
Type: bugfix
Files Changed: app/discord/leave_ui.py, tests/test_reason_attachments.py
Modules Changed: discord_leave_ui
Review Score: 95
Memory Updated: yes
Graph Updated: no
---
Task: Reapply HOD hides after HR lost Administrator
Date: 2026-09-17
Type: bugfix
Files Changed: app/discord/bot.py
Modules Changed: discord_bot
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Hide HOD leave channels from HR
Date: 2026-09-17
Type: bugfix
Files Changed: app/discord/leave_inbox.py, tests/test_hod_flow.py
Modules Changed: discord_leave_inbox
Review Score: 94
Memory Updated: yes
Graph Updated: no
---
Task: Sync new Discord roles and member role changes into Airtable
Date: 2026-09-17
Type: feature
Files Changed: app/hr/staff_onboard.py, app/airtable/employees.py, app/discord/bot.py, tests/test_staff_sync.py
Modules Changed: discord_bot, hr_services, airtable_client
Review Score: 93
Memory Updated: yes
Graph Updated: no
---
Task: Sync BI HOD Email in Airtable from env
Date: 2026-09-17
Type: config
Files Changed: scripts/sync_reviewer_emails.py
Modules Changed: mail, airtable_client
Review Score: 96
Memory Updated: yes
Graph Updated: no
---
Task: Cc BI HOD from env and sync Airtable Emails
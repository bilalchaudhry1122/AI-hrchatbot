# SOW Updates — Discord HR Assistant (Current Product Flow)

Use this document to revise the Statement of Work so it matches what the bot does today.  
There is no SOW file in the repo; treat each section as **what to change / add / remove** in your existing SOW.

**Product name:** HR Assistant (Discord)  
**Company default:** WebAiry  
**Related guides:** `docs/user-guide-members-hod.md`, `docs/user-guide-hr.md`

---

## 1. Summary of SOW changes (checklist)

| # | Area | Action in SOW |
|---|------|----------------|
| 1 | Onboarding | **Replace** any “HR creates accounts manually” / single-step signup with self-service `#onboarding` flow + role assignment |
| 2 | Role / profile change | **Add** HR correction path via `#hr-profiles` (edit / delete); wrong onboarding role must be fixed by HR |
| 3 | Leave approval authority | **Replace** “HOD approves leave” with **HR/Admin only** approve/reject in `#leave-requests` |
| 4 | HOD leave role | **Replace** HOD as approver with **HOD notify-only** (department HOD channels + optional DM); no Approve/Reject for HOD |
| 5 | Channel map | **Replace** old channel list with the full map in §3 |
| 6 | Announcements | **Split** public `#announcements` vs HR-only `#hr-announcements` scheduling |
| 7 | Tickets | **Keep/clarify** private ticket UX from `#open-ticket`; RAG policy Q&A + leave inside ticket |
| 8 | Leave eligibility | **Add** CS Member & Sales Member cannot apply leave or see balance |
| 9 | Leave types | **Remove** Unpaid (if SOW listed it); only Annual / Sick / Casual |
| 10 | Email | **Clarify** leave approved/cancel mail: To = HR inbox; Cc = department HOD when available |
| 11 | Scope out | **Remove** any HOD multi-stage approval gate before HR can act |

---

## 2. Onboarding & change flow (rewrite for SOW)

### 2.1 Current onboarding flow (authoritative)

**Channel:** `#onboarding`  
**Who sees it:** New joiners (`@everyone`). After a workplace role is assigned, the channel is hidden for that member. HR/Admin can still see it.

**Steps:**

1. Member clicks **Start Onboarding**.
2. **Step 1 form:** Full Name, Contact Number, CNIC → Continue.
3. **Step 2 form:** Email, Date of Birth (`YYYY-MM-DD`), Address.
4. **Department select:** BI | CS | Sales | Marketing | HR.
5. **Level select** (only for BI, CS, Marketing): **Member** or **HOD**.  
   - Sales → always **Sales Member** (no HOD level in this flow).  
   - HR → role **HR**.
6. Bot creates/updates the employee record and assigns the matching Discord role.
7. Onboarding channel hides for that user; they can use tickets / leave (subject to eligibility).

**Discord roles produced by onboarding:**

| Selection | Discord role |
|-----------|--------------|
| BI + Member | BI Member |
| BI + HOD | BI HOD |
| CS + Member | CS Member |
| CS + HOD | CS HOD |
| Marketing + Member | Marketing Member |
| Marketing + HOD | Marketing HOD |
| Sales | Sales Member |
| HR | HR |

**SOW wording to use:**

> New employees complete self-service onboarding in `#onboarding`. The bot collects profile fields in two steps, then department (and Member/HOD level where applicable), assigns the Discord role, and creates the employee record. Incorrect role selection is corrected by HR (not by re-running a public self-change of department/level in product scope unless later agreed).

### 2.2 Change / correction flow (authoritative)

There is **no** employee self-service “change my department/HOD level” wizard after onboarding.

| Situation | Current process |
|-----------|-----------------|
| Wrong name / contact / email / DOB / address | HR uses `#hr-profiles` → look up (`/profile`) → **Edit profile** (same field split as onboarding) |
| Wrong department or Member/HOD role | HR fixes Discord role + employee record via `#hr-profiles` / Admin process; employee should not rely on re-onboarding alone |
| Employee leaves company / remove access | HR uses `/deleteprofile` in `#hr-profiles` (confirmation; may remove from server) |
| Role added/removed later on Discord | Bot syncs workplace roles into the employee **Discord Roles** field |

**SOW wording to use:**

> Post-onboarding profile and role corrections are HR-owned in `#hr-profiles`. Employees do not self-approve role changes. Deletion of an employee profile is an HR/Admin action with confirmation.

### 2.3 What to remove from SOW (if present)

- Manual HR spreadsheet onboarding as the only path (unless kept as fallback outside the bot).
- Multi-step HOD sign-off before the employee can finish onboarding.
- Employee self-service department/HOD toggle without HR.
- Any claim that onboarding stays visible forever for all members.

---

## 3. Complete channel map (put this in the SOW)

### 3.1 Categories

| Category | Purpose |
|----------|---------|
| **Tickets** | Private per-employee ticket channels |
| **HR** | HR/Admin-only operational channels (leave approval, profiles, HR announcement drafting) |
| **HOD** | Department HOD notify inboxes (view-only leave cards) |

### 3.2 Public / member-facing channels

| Channel | Audience | Purpose |
|---------|----------|---------|
| `#onboarding` | New joiners; hidden after workplace role | Self-service profile + role |
| `#open-ticket` | Members with access | Panel: **Open ticket** → private ticket |
| `#announcements` | Everyone (read); HR/Admin/bot (post) | Scheduled HR announcements + automated birthday greetings |

### 3.3 HR category / HR-only channels

| Channel | Audience | Purpose |
|---------|----------|---------|
| `#leave-requests` | Admin + HR only | **Final** leave Approve / Reject (buttons). Source of truth for leave decision. |
| `#hr-profiles` | Admin + HR only | `/profile`, Edit profile, `/deleteprofile` |
| `#hr-announcements` | Admin + HR only | Type trigger → **Create announcement** form → schedule post to `#announcements`; cancel upcoming announcements |

### 3.4 HOD category channels (notify only)

| Channel | Audience | Purpose |
|---------|----------|---------|
| `#bi-hod` | BI HOD (+ Admin/HR can see) | View leave requests for BI team — **no Approve/Reject** |
| `#cs-hod` | CS HOD (+ Admin/HR can see) | View leave requests for CS team — **no Approve/Reject** |
| `#marketing-hod` | Marketing HOD (+ Admin/HR can see) | View leave requests for Marketing team — **no Approve/Reject** |

**Important SOW rule:**

> When a leave request is submitted, the bot posts it to `#leave-requests` (HR, with Approve/Reject) **and**, if the employee’s department has a HOD inbox, to that HOD channel **at the same time** as a **notification only** (card without approval buttons). HOD notification is additional, never a substitute for HR. HODs do not approve or reject leave in Discord.

### 3.5 Ticket channels

| Surface | Audience | Purpose |
|---------|----------|---------|
| `#ticket-…` (private) | Ticket owner + bot + Admin (HR joins as needed) | Policy Q&A (RAG), leave apply/balance/withdraw/cancel, Close ticket |

**SOW clarifications:**

- One open ticket per member (reopen same channel).
- HODs and Staff do **not** see other people’s tickets.
- A HOD may open **their own** ticket for questions/leave; their leave still goes to `#leave-requests` for HR.
- `/leave` (pause bot in ticket) is **Admin/HR only**.

---

## 4. Leave & approval flow (rewrite for SOW)

### 4.1 Who can use leave

| Role | Apply leave / balance |
|------|------------------------|
| BI Member, BI HOD | Yes |
| Marketing Member, Marketing HOD | Yes |
| CS HOD | Yes |
| CS Member | **No** — contact HR |
| Sales Member | **No** — contact HR |
| HR | Per product rules (HR tools; leave decision authority in `#leave-requests`) |

Leave types on the form: **Annual Leave**, **Sick Leave**, **Casual Leave** only (no Unpaid).

### 4.2 Apply → notify → decide

```
Employee (ticket)
  → asks for leave / form (type, dates, half-day optional, reason, optional file)
  → Submit to HR
       ├─→ #leave-requests   (HR/Admin: Approve | Reject)   ← decision
       └─→ #bi-hod / #cs-hod / #marketing-hod (if applicable)
              (HOD: notify / view only; optional DM)        ← information only
  → Employee notified on decision (DM)
  → Email on approve / cancel when mail is configured
       To: HR inbox; Cc: department HOD when available
```

**Rules to state in SOW:**

1. Only **one pending leave** at a time per employee.
2. Employee can **Withdraw** while pending.
3. Employee can **Cancel** an approved upcoming leave via ticket form; days return to balance.
4. **Final decision = HR/Admin** in `#leave-requests` only.
5. **HOD = notification only** (department HOD channel + DM where used). No HOD approval stage before HR.

### 4.3 What to delete from SOW (common old wording)

| Old SOW idea | Replace with |
|--------------|--------------|
| HOD must approve before HR sees the request | HR and HOD notified together; only HR decides |
| HOD Approve/Reject buttons | No buttons for HOD; view-only card |
| Leave decided in ticket by HOD | Decision only in `#leave-requests` |
| Multi-level workflow: Member → HOD → HR | Single decision level: HR; HOD informed in parallel |
| Unpaid leave in the employee form | Remove; Annual / Sick / Casual only |
| All departments get leave quota | CS Member & Sales Member excluded |

---

## 5. Announcements flow (for SOW)

| Step | Channel | Actor |
|------|---------|--------|
| Draft / schedule / cancel | `#hr-announcements` | HR/Admin |
| Public post at scheduled time | `#announcements` | Bot |
| Birthday greetings (automated) | `#announcements` | Bot (Pakistan time schedule) |

**SOW wording:**

> HR schedules company announcements from the private `#hr-announcements` channel. The bot posts them to the public `#announcements` channel at the chosen date/time (Pakistan time). Birthday greetings are also posted to `#announcements`. HODs do not manage the announcement schedule unless they are also HR/Admin.

---

## 6. Tickets & knowledge (RAG) — keep / tighten

Keep or add these SOW points to match the build:

- Answers come from the existing Pinecone index (n8n + Google Drive ingest). **This Discord app does not write to Pinecone and does not call n8n during chat.**
- Policy / handbook questions are answered inside the private ticket.
- Live leave balance / apply uses HR records (structured DB / Airtable sync as implemented), not vector search for leave transactions.
- Identity of the bot: **HR Assistant** (not the Discord server name).

---

## 7. Suggested SOW section text (copy-paste)

You can paste or adapt the block below into the SOW body.

### A. Discord channel architecture

The solution uses dedicated Discord channels:

- `#onboarding` — employee self-onboarding and role assignment  
- `#open-ticket` — entry to private support tickets  
- Private ticket channels under **Tickets**  
- `#leave-requests` (HR category) — HR/Admin leave Approve/Reject  
- `#hr-profiles` (HR) — employee profile lookup, edit, delete  
- `#hr-announcements` (HR) — schedule/cancel company announcements  
- `#announcements` — public posts (scheduled announcements + birthdays)  
- `#bi-hod`, `#cs-hod`, `#marketing-hod` (HOD category) — **leave notifications only** for the matching HOD  

### B. Onboarding & change management

Employees complete a two-step profile form and select department (and Member/HOD where applicable). The bot assigns Discord roles and creates the employee record. Subsequent profile or role corrections are performed by HR in `#hr-profiles`. Profile deletion is an HR/Admin confirmed action.

### C. Leave workflow

Eligible employees apply for leave from their private ticket. On submit, HR receives the request in `#leave-requests` with Approve/Reject controls. The department HOD (BI / CS / Marketing) receives a parallel **notification** in their HOD channel without approval controls. Final authority rests with HR/Admin. CS Member and Sales Member cannot use leave apply or balance features and must contact HR. Supported leave types: Annual, Sick, Casual.

### D. Out of scope / non-goals (align SOW)

- HOD as leave approver in Discord  
- Employee self-service department/HOD change after onboarding  
- Unpaid leave on the standard leave form  
- Pinecone writes or n8n calls from the Discord bot runtime  

---

## 8. Acceptance criteria to add/update in SOW

1. New joiner can complete `#onboarding` and receive the correct Discord role from department + level.  
2. After onboarding, `#onboarding` is not visible to that workplace role.  
3. HR can edit and delete profiles from `#hr-profiles`.  
4. Eligible employee can open a ticket, apply leave, and see the request in `#leave-requests` with Approve/Reject.  
5. Matching HOD channel receives the same leave card **without** Approve/Reject.  
6. HOD cannot approve/reject leave from the HOD channel.  
7. After HR Approve/Reject, employee is notified (DM); email sent when configured.  
8. CS Member and Sales Member receive a clear denial for leave apply/balance.  
9. HR can schedule and cancel announcements from `#hr-announcements`; posts appear in `#announcements`.  
10. Birthday automation posts to `#announcements`.  

---

## 9. Mapping: typical old SOW → required update

| If your SOW currently says… | Change it to… |
|-----------------------------|----------------|
| “HOD approves leave; HR is informed” | “HR approves/rejects in `#leave-requests`; HOD is notified in `#*-hod` only” |
| “Leave inbox is one shared channel” | “HR `#leave-requests` + separate HOD category channels” |
| “Announcements posted by HOD” | “HR schedules in `#hr-announcements`; public feed is `#announcements`” |
| “HR creates every employee profile” | “Employee self-onboards; HR corrects via `#hr-profiles`” |
| “All staff can apply leave” | “Leave disabled for CS Member and Sales Member” |
| “HOD must sign off before HR sees request” | “Parallel notify; no HOD gate” |
| “Unpaid leave available in bot” | “Annual / Sick / Casual only” |

---

## 10. Deliverables / docs cross-reference

When you update the SOW, keep these aligned:

| Audience | File |
|----------|------|
| Members & HODs | `docs/user-guide-members-hod.md` |
| HR | `docs/user-guide-hr.md` |
| This SOW amendment list | `docs/sow-updates-current-flow.md` |

---

*Generated from the current Discord HR Assistant implementation (onboarding, tickets, leave inbox, HOD notify-only, HR profiles, announcements).*

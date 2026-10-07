# HR Assistant — Guide for HR

This guide is for **HR** and **Admin**. It covers day-to-day use of the HR Assistant bot in Discord.

Members and HODs have their own guide: `user-guide-members-hod.md`.

---

## 1. Your main channels

| Channel | What you use it for |
|---------|---------------------|
| **#leave-requests** | Approve or reject leave. Also: **cake reminder** the day before a birthday (name, contact, address). |
| **#hr-profiles** | Look up and edit employee profiles (including designation and photo). |
| **#hr-announcements** | Schedule or cancel company announcements. |
| **#onboarding** | Where new people create their profile. |
| **#open-ticket** | Where anyone opens a private ticket. |
| **#announcements** | Scheduled posts, **welcome after onboarding**, and **birthday greetings on the day** (no private address or phone). |

You can also join employee tickets when needed.

HOD channels (`#bi-hod`, `#cs-hod`, `#marketing-hod`) are for **viewing** leave only. HODs cannot approve or reject there.

---

## 2. How new people get onboarded

Employees start in **#onboarding**:

1. They click **Start Onboarding**.
2. They enter name, contact, CNIC, then email, date of birth, and address.
3. They choose **department** (BI, CS, Sales, Marketing, HR).
4. They type their **designation** (job title), for example Software Engineer.
5. They **add a photo** or **Skip photo**.

They do **not** pick Member or HOD on the form.

### What the bot assigns

- Department role: **BI Member**, **CS Member**, **Marketing Member**, **Sales Member**, or **HR**.
- Designation role under the department, for example **BI · Software Engineer**.

**HOD is assigned only by you.** Give the person the Discord role **BI HOD**, **CS HOD**, or **Marketing HOD** after they finish onboarding. Do not tell joiners to select HOD in the form.

### After they finish

- Their employee record is created (including designation and photo path if they uploaded a picture).
- A **welcome** is posted in **#announcements**.
- **#onboarding** usually hides for that person.

### If something is wrong

Fix it in **#hr-profiles** (look up with `/profile`, then **Edit profile**). Common fixes: wrong department, wrong designation, missing photo, missing address or contact.

If they chose the wrong department, they may not see the right channels, and leave may be blocked (CS Member and Sales Member cannot apply leave).

---

## 3. Tickets and questions

Employees open tickets from **#open-ticket** → **Open ticket**.

The greeting is a short welcome only (no employee list). Inside a ticket they can ask **who is in BI / CS / Marketing / HR** and the bot posts that department’s names, designations, and photos (when a photo is on file).

Inside a ticket they can also:

- Ask policy / handbook questions
- Apply for leave
- Check leave balance
- Withdraw or cancel leave

If you need to talk to them without the bot answering, use **`/leave`** in that ticket (the bot pauses so humans can chat).

---

## 4. Approve or reject leave

1. Open **#leave-requests**.
2. Find the leave card.
3. Click **Approve** or **Reject**.
4. If you reject, you may be asked for a reason.

Notes:

- Final decision is with **HR / Admin** in this channel.
- Department HOD channels (`#bi-hod`, `#cs-hod`, `#marketing-hod`) are **view only**.
- After approval, the employee is notified. Leave email may also go out if email is set up.
- You can use **`/pending`** to see what still needs a decision.

---

## 5. Employee leave types (what they can choose)

On the leave form employees only see:

- Annual Leave
- Sick Leave
- Casual Leave

Unpaid leave is not offered.

**Leave blocked for:** CS Member and Sales Member (they should contact HR).

---

## 6. What employees can do (so you can help them)

### Check balance

They ask in their ticket, for example “What is my leave balance?” or they use `/myleave`.

The card title shows **that employee’s name once**, for example *Muhammad Bilal's live leave balance*. If you type in their ticket, the name is still **the ticket owner**, not yours.

### Apply leave

They ask in the ticket → choose type → **Fill form** → **Submit to HR**.

### Withdraw (still pending)

They click **Withdraw** or type **withdraw**.

### Cancel (already approved)

They ask to cancel leave → pick the leave → give a reason → submit. Days return to balance.

---

## 7. Profiles (`#hr-profiles`)

Useful commands / actions:

- **`/profile`** with a name or ID — look someone up (photo shows when the file is stored)
- **Edit profile** — update name, contact, CNIC, email, date of birth, address, **designation**
- **`/deleteprofile`** — remove their employee record (confirmation required; they may also be removed from the server)

Use this when onboarding data is wrong, a photo or title needs updating, or someone leaves the company.

To make someone a **HOD**, assign the HOD Discord role yourself. Do not expect the onboarding form to do it.

---

## 8. Announcements (`#hr-announcements`)

### Create one

1. Type something that includes **announcement** (for example: “I have an announcement”).
2. Click **Create announcement**.
3. Enter title, date, time (Pakistan time, like `6:30 PM`), and description.
4. The bot saves it and posts to **#announcements** at that date and time.

### Cancel one

1. Type something with **cancel** and **announcement**.
2. Pick the upcoming announcement from the list.
3. Confirm cancel.

The public **#announcements** channel also gets automatic **onboarding welcomes** and **birthday greetings**. You do not schedule those by hand.

---

## 9. Birthdays

| When | Where | What you see |
|------|--------|----------------|
| **Day before**, 11:00 AM Pakistan time | **#leave-requests** | Cake reminder: name, Discord mention, **contact**, **address** |
| **On the day**, 11:00 AM Pakistan time | **#announcements** | Public greeting only (no address or phone) |

If contact or address is missing, update the profile in **#hr-profiles** so the cake reminder is useful.

---

## 10. Handy commands for HR

| Command | Use |
|---------|-----|
| `/whoami` | See your own linked employee record |
| `/pending` | See leave waiting for a decision |
| `/profile` | Look up an employee (in `#hr-profiles`) |
| `/deleteprofile` | Remove a profile (in `#hr-profiles`) |
| `/leave` | Pause the bot in a ticket so you can talk |

---

## 11. Quick HR checklist

| Task | Where / how |
|------|-------------|
| New joiner stuck | Check department and designation; fix via **#hr-profiles** |
| Assign HOD | Give **BI HOD / CS HOD / Marketing HOD** in Discord yourself |
| Missing photo or title | **#hr-profiles** → `/profile` → Edit profile |
| Cake for tomorrow’s birthday | **#leave-requests** reminder (day before, 11:00 AM) |
| Approve leave | **#leave-requests** → Approve / Reject |
| Schedule news | **#hr-announcements** → create announcement |
| Help with policy | Join their ticket, or ask them to open one from **#open-ticket** |
| Talk without bot replies | In the ticket, use `/leave` |

---

## Share with the team

Give Members and HODs: **`docs/user-guide-members-hod.md`**  
Keep this file for the HR team: **`docs/user-guide-hr.md`**

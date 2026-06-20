# Hackathon Planning App · User Guide

A simple, all-in-one planning workspace for running the **Let's Tech Club
hackathon (July 17–19)**. It keeps your whole team on the same page — what needs
doing, who's doing it, which sponsors and guests are confirmed, and where things
are stuck — all in one clean dashboard.

Think of it as your event's mission control: plan the work, track the progress,
manage the people outside your team, and store the important documents you keep
coming back to.

---

## What you can do with it

- **Plan your event in layers** — group big areas of work into *Epics*, break
  each Epic into *Sprints* (phases), and fill each Sprint with *Tasks*.
- **Track work on a board** — clear status lanes show every task moving from
  *Backlog → To Do → In Progress → Done*.
- **Assign work to people** — give each task an owner so nothing falls through
  the cracks. Owners get an email when work lands on their plate.
- **Flag blockers** — mark a task as "blocked", add a reason, and the right
  people are automatically alerted by email so it gets unstuck fast.
- **Manage stakeholders** — keep a tidy register of sponsors, judges, mentors,
  speakers and guests, including their status (Pending / Confirmed / Rejected)
  and contact details.
- **Connect work to stakeholders** — link a task to a sponsor or speaker so you
  can see exactly what's outstanding for each external partner.
- **Keep important Docs** — store run-of-show notes, checklists, contact lists
  and any other reference material as rich-text documents.
- **See the big picture** — switch to the Overview to get a summary of an Epic at
  a glance.

---

## Getting started

### Signing in

This app uses **passwordless login** — there's nothing to memorize.

1. Open the app and enter your email address.
2. You'll see *"A passcode is on its way to your email."*
3. Check your inbox for a one-time passcode and enter it.
4. You're in.

> If you enter an email that hasn't been added to the team yet, you'll be told
> *"There is no account for this email."* Ask an admin to invite you first.

### Finding your way around

- **Left sidebar** — your list of **Epics**, plus shortcuts to **Docs** and the
  **Team**. Your name and a sign-out button sit at the bottom.
- **Top bar** — the name of the Epic you're viewing, a **Board / Overview**
  switch, and buttons for **Stakeholders**, **Sprints** and **+ New Task**.
- **Main area** — the work board (or the Overview summary) for the selected Epic.

---

## Core concepts (in plain words)

| Term                  | What it means                                                                                      |
| --------------------- | -------------------------------------------------------------------------------------------------- |
| **Epic**        | A major area of your event, e.g.*Venue & Logistics* or *Marketing*. The top level of planning. |
| **Sprint**      | A phase or stage inside an Epic, e.g.*Week 1 Prep* or *Event Day*. Sprints are ordered.        |
| **Task**        | A single piece of work inside a Sprint, e.g.*Book the projector*.                                |
| **Stakeholder** | A person or organization outside your team — sponsors, judges, mentors, speakers, guests.         |
| **Doc**         | A standalone rich-text document for important reference information.                               |

A handy way to picture it:

> **Epic** → contains **Sprints** → contain **Tasks**.
> **Stakeholders** and **Docs** live alongside, available across your workspace.

---

## Working with Epics

Epics are the big buckets of work.

- **Create one** — in the left sidebar, under *Epics*, click **+ New**. Give it a
  name, an optional description, and choose an owner.
- **Open one** — click its name in the sidebar to load its board.
- **Edit or delete** — open the Epic and click the small gear icon next to its
  title. (Deleting an Epic also removes its Sprints, Tasks and Stakeholders, so
  you'll be asked to confirm.)

A small red dot next to an Epic means it has **blocked tasks** that need
attention.

---

## Working with Sprints

Sprints split an Epic into manageable phases.

- **Manage them** — click **Sprints** in the top bar to add, rename, edit or
  remove Sprints.
- **Reorder them** — drag a Sprint into a new position to change its order.
- **Switch between them** — use the Sprint tabs above the board to focus on one
  phase at a time.

---

## Working with Tasks

Tasks are the day-to-day to-dos.

- **Create a task** — click **+ New Task** in the top bar. Add a title, a rich
  description, a priority, and (optionally) an owner and a linked stakeholder.
- **Open a task** — click it on the board to see and edit the full details.
- **Move it along** — update a task's status to walk it through
  *Backlog → To Do → In Progress → Done*.
- **Assign it** — pick a team member as the owner. They'll receive an email
  letting them know.
- **Block it** — if a task is stuck, mark it blocked and add a reason. An
  escalation email is sent so it gets noticed. Unblock it once it's moving again.

> **Note:** a task can't move into *In Progress* while it has no owner — this
> keeps every active piece of work accountable to someone.

### The two views

- **Board** — the classic columns view, great for daily work and seeing what's in
  flight.
- **Overview** — a summarized view of the Epic, great for status check-ins.

You can also **filter the board by stakeholder** to see only the tasks tied to a
particular sponsor, speaker or partner.

---

## Working with Stakeholders

Stakeholders are everyone outside your core team who matters to the event.

- **Open the register** — click **Stakeholders** in the top bar.
- **Add someone** — record their name, organization, one or more roles
  (e.g. *Main Sponsor*, *Judge*, *Speaker*, *Guest*), their status, and contact
  details.
- **Update status** — move them between *Pending*, *Confirmed* and *Rejected* as
  conversations progress.
- **Link them to work** — connect a stakeholder to a task so you always know what
  still needs doing for each partner.

Stakeholder roles are grouped to make priorities clear — for example, essential
"must-have" sponsors are kept separate from optional supporting sponsors.

---

## Working with Docs

Docs are your team's lightweight knowledge base — a place for the important
information you keep coming back to.

- **Open Docs** — click **Docs** in the left sidebar.
- **Create a doc** — click **+ New doc**, give it a title, and write your content
  using the rich-text editor (headings, bold, lists, links and more).
- **Edit a doc** — click any doc to open and update it, then **Save**.
- **Delete a doc** — use the **Delete** button on the doc or in the list.

Docs are available across the whole workspace — they aren't tied to any single
Epic — so they're perfect for run sheets, contact lists, packing checklists and
event-day runbooks.

---

## Managing your team

Team members are the people inside your organizing crew who use the app.

- **Open the team panel** — click **Team** in the left sidebar.
- **Invite a member** *(admins only)* — add their email and choose a role. They
  can then sign in with a passcode.
- **Roles** — *Admins* can invite and remove members and manage access;
  *Members* can do the everyday planning work.
- **Scrum Master** — a member can be flagged as Scrum Master so they receive
  escalation alerts when tasks get blocked.

---

## Email notifications

The app keeps people informed automatically:

- **Assignment emails** — when a task is assigned to someone, they get a heads-up.
- **Escalation emails** — when a task is blocked, the relevant people are alerted
  so it can be resolved quickly.

By default, outbound mail uses Resend with `USE_SMTP=false`. If you want to
switch back to Gmail SMTP, set `USE_SMTP=true` and fill in the `MAIL_*`
settings.

You don't need to do anything to send these — they happen as you work.

---

## Quick reference

| I want to…              | Where to go                                     |
| ------------------------ | ----------------------------------------------- |
| Sign in                  | Enter your email, then the emailed passcode     |
| Add a big area of work   | Sidebar →*Epics* → **+ New**          |
| Add a phase              | Top bar →**Sprints**                     |
| Add a to-do              | Top bar →**+ New Task**                  |
| Assign a to-do           | Open the task → choose an owner                |
| Mark something stuck     | Open the task →**block** + reason        |
| Track a sponsor or guest | Top bar →**Stakeholders**                |
| Save reference info      | Sidebar →**Docs** → **+ New doc** |
| Invite a teammate        | Sidebar →**Team** (admins only)          |
| See a summary            | Top bar →**Overview**                    |

---

## For developers

This section is for people setting up or running the app.

**Run locally**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # edit secrets
$env:APP_ENV = "development"
flask --app wsgi seed            # optional demo data
python wsgi.py                   # http://localhost:5000
```

**Run with Docker (PostgreSQL + gunicorn)**

```powershell
Copy-Item .env.example .env      # set SECRET_KEY, RESEND_KEY, optional MAIL_* fallback
docker compose up --build
# App: http://localhost:8000  Health: http://localhost:8000/health
```

Built with Flask, SQLAlchemy, Flask-Migrate, Flask-Mail, PostgreSQL, gunicorn,
and a Tailwind single-page dashboard. Deployable to Render (Docker) or Vercel
(serverless with Vercel Postgres / Neon).

# Hackathon App User Guide

A practical workspace for running the Let's Tech Club hackathon end to end.
It combines planning, execution, external stakeholder management, participant
selection, team formation, and shared documentation in one system.

This guide is written for organizers, stakeholders, participants, and
developers.

---

## What changed recently

- Stakeholders are now shared across the full program, not isolated per epic.
- Deleting an epic removes that epic's sprints and tasks, but shared
  stakeholders are preserved.
- Partner account enablement is now program-wide and no longer depends on a
  specific epic id.

---

## Core model

Use this mental model when working in the app:

- Program
  - Epics
    - Sprints
      - Tasks
- Shared across all epics
  - Stakeholders
  - Docs

In short: tasks stay epic and sprint scoped, while stakeholder records are
program-wide and reusable everywhere.

---

## Roles and sign-in

There are three role families:

- Organizers: Admin and Member
- Stakeholders: Industry partners
- Participants: Applicants and selected competitors

Sign-in behavior:

- Organizers and participants: passwordless OTP by email
- Stakeholders: direct email login (no OTP)
- New participants: self-register from the Register page

Unknown emails are not auto-created (except participant self-registration).

---

## Organizer command center

Main organizer surfaces:

- Sidebar
  - Epics list
  - Program views: Milestones, Participants, Teams, Stakeholders
  - Docs and Team admin
- Header
  - Board or Overview mode
  - Sprints management
  - Stakeholder matrix access
  - New task

### Epics

- Create and edit epics for major workstreams.
- Delete epic removes only that epic's sprint and task tree.
- Shared stakeholders remain available after epic deletion.

### Sprints

- Add, edit, and delete sprints within an epic.
- Drag and drop in Sprint management to reorder sprint sequence.

### Tasks

- Create tasks under a sprint.
- Assign one or multiple users.
- Move through states: Backlog, To Do, In Progress, Done.
- Block or unblock with escalation reason.
- Link tasks to a shared stakeholder.

### Shared stakeholders

Stakeholders are global records:

- A stakeholder can be used by tasks from any epic.
- Status and profile updates are reflected everywhere.
- Partner portal login can be enabled once and reused program-wide.

### Docs

- Rich-text docs are shared workspace references.
- Use docs for runbooks, checklists, contact sheets, and schedules.

---

## Program views

Organizers get consolidated views:

- Milestones: cross-epic progress rollup
- Participants: funnel management and interview notes
- Teams: formed teams and chosen requirement focus
- Stakeholders: shared matrix and portal enablement

---

## Industry partner workflow

Partners can:

- Sign in with email-only access
- Maintain profile details
- Create and update requirement/problem statements
- Track teams interested in their requirements

Requirement statuses:

- Draft
- Open
- Addressed
- Closed

---

## Participant workflow

Participants can:

- Register publicly
- Sign in with OTP
- Track selection status
- Browse open requirements
- Form or join teams once selected

Selection statuses:

- Applied
- Interviewing
- Selected
- Waitlisted
- Rejected

---

## Notifications

The system sends transactional emails for:

- Task assignment
- Task escalation when blocked
- Stakeholder invites
- Participant decision updates

Mail provider is configured by environment variables.

---

## Local development

### Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
$env:APP_ENV = "development"
flask --app wsgi seed
python wsgi.py
```

### Run with Docker

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Default health endpoint:

- http://localhost:8000/health

---

## External API quick reference

Base path:

- /api/v1

Docs:

- GET /api/v1/docs
- GET /api/v1/openapi.json

Auth flow:

- POST /api/v1/auth/login
- POST /api/v1/auth/verify (OTP users)
- POST /api/v1/auth/register (participants)

Key domains:

- Epics, Sprints, Tasks
- Shared Stakeholders
- Documents
- Community (participants and teams)
- Portal (stakeholder and participant self-service)

For full endpoint workflows, see API_WORKFLOWS.md.

---

## Operational notes

- Shared stakeholder integrity is preserved when epics are deleted.
- If attempting to delete the last epic while shared stakeholders exist, create
  another epic first or remove stakeholders.
- For production, always run migrations before serving traffic.

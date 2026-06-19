# Let's Tech Project Planning App

Internal, production-grade Project Planning & Operations Management app for the
Let's Tech Club hackathon (July 17–19). Built with Flask, SQLAlchemy,
Flask-Migrate, Flask-Mail (async via native threading), PostgreSQL, gunicorn,
and a Tailwind single-page command center.

## Capabilities

- **Operational Milestone & Scrum Engine** — projects → sequential sprints →
  tasks moving through `Backlog → To Do → In Progress → In Review → Done`.
- **Strict Concurrency Guard** — activating a sprint transactionally
  deactivates any other active sprint in the same project.
- **Validation Gatekeepers** — a task cannot enter `In Progress` / `In Review`
  while unassigned or while its sprint is inactive (enforced at the ORM layer).
- **Stakeholder Matrix** — typed external entities (Main Sponsor, In-Kind
  Sponsor, Key Speaker, Venue Management, Media Partner) with task interlocking
  and filtering.
- **Roadblock Propagation** — blocked tasks surface up to the project view.
- **Async Communication Engine** — non-blocking Flask-Mail dispatch on
  `threading.Thread`, firing assignment notifications and escalation alerts.

## Project layout

```
config.py                     # Dev / Test / Prod configuration
wsgi.py                       # Gunicorn entrypoint (exposes `app`)
app/
  __init__.py                 # create_app() factory
  extensions.py               # db, migrate, mail singletons
  models.py                   # User, Project, Sprint, Task, Stakeholder + enums
  routes.py                   # RESTful JSON Blueprint + dashboard view
  seed.py                     # demo dataset
  services/
    mail_service.py           # async threaded SMTP dispatcher
    ops_service.py            # transactional business logic
  templates/
    dashboard.html            # SPA shell
    emails/                   # assignment + escalation HTML emails
  static/app.js               # SPA client
Dockerfile / docker-compose.yml / docker-entrypoint.sh
```

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # edit secrets
$env:APP_ENV = "development"
flask --app wsgi seed            # optional demo data
python wsgi.py                   # http://localhost:5000
```

## Run with Docker (PostgreSQL + gunicorn)

```powershell
Copy-Item .env.example .env      # set SECRET_KEY, MAIL_* etc.
docker compose up --build
# App: http://localhost:8000   Health: http://localhost:8000/health
```

The `web` container waits for `db` to report `service_healthy` before booting.

## Key API surface

| Method | Path                                | Purpose                            |
| ------ | ----------------------------------- | ---------------------------------- |
| GET    | `/api/bootstrap`                  | Full snapshot for the SPA          |
| POST   | `/api/projects`                   | Create project                     |
| POST   | `/api/projects/<id>/sprints`      | Create sprint                      |
| POST   | `/api/sprints/<id>/activate`      | Activate (single-active guard)     |
| POST   | `/api/projects/<id>/stakeholders` | Register stakeholder               |
| GET    | `/api/stakeholders/<id>/tasks`    | Tasks by dependency                |
| POST   | `/api/sprints/<id>/tasks`         | Create task                        |
| POST   | `/api/tasks/<id>/assign`          | Assign (async notify)              |
| POST   | `/api/tasks/<id>/transition`      | Move lane (guarded)                |
| POST   | `/api/tasks/<id>/block`           | Flag/unflag block (async escalate) |
| POST   | `/api/tasks/<id>/stakeholder`     | Link/unlink dependency             |

In the UI, **double-click a sprint tab** to toggle it active/inactive.

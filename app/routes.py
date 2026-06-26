"""
app/routes.py
=============
Operations Blueprint — RESTful JSON API plus the single-page Platform.
All `/api/*` paths require an authenticated session; team administration paths
additionally require the admin role. Write paths delegate to the transactional
service layer so business rules, gatekeepers, rollbacks, and async comms fire
in exactly one place.
"""

from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, jsonify, render_template, request

from .extensions import db
from .models import (
    User,
    Project,
    Sprint,
    Task,
    Stakeholder,
    Doc,
    TaskState,
    StakeholderRoleType,
    StakeholderStatus,
    UserRole,
    UserStatus,
    IndustryRequirement,
    ParticipantProfile,
    Team,
    SelectionStatus,
    ExperienceLevel,
    RequirementStatus,
    StakeholderHackathonStatus,
    SUGGESTED_INDUSTRIES,
    coerce_enum,
    coerce_stakeholder_status,
    stakeholder_role_groups_meta,
)
from .services import ops_service
from .services.ops_service import OperationError
from .services import auth_service
from .services.auth_service import AuthError
from .services import community_service
from .services.community_service import CommunityError
from .auth import login_required, admin_required, current_user

ops_bp = Blueprint("ops", __name__)


# ---------------------------------------------------------------------------
# Shared community metadata for templates + organizer APIs
# ---------------------------------------------------------------------------
def _enum_meta(enum_cls):
    return [{"key": m.name, "label": m.value} for m in enum_cls]


def _community_meta() -> dict:
    return {
        "industries": SUGGESTED_INDUSTRIES,
        "selection_statuses": _enum_meta(SelectionStatus),
        "experience_levels": _enum_meta(ExperienceLevel),
        "requirement_statuses": _enum_meta(RequirementStatus),
        "hackathon_statuses": _enum_meta(StakeholderHackathonStatus),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _payload() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        raise OperationError("Request body must be valid JSON.", status=400)
    if not isinstance(data, dict):
        raise OperationError("JSON body must be an object.", status=400)
    return data


def _require(data: dict, *keys: str):
    missing = [k for k in keys if data.get(k) in (None, "")]
    if missing:
        raise OperationError(f"Missing required field(s): {', '.join(missing)}", status=400)


def _get_or_404(model, ident, label: str):
    obj = db.session.get(model, ident)
    if obj is None:
        raise OperationError(f"{label} {ident} not found.", status=404)
    return obj


def _parse_due_date(value):
    """Coerce an incoming ``due_date`` into a ``date`` (or ``None`` to clear).

    Raises ``ValueError`` on a malformed value so the task create/update
    handlers surface it as a 400 via their existing ``ValueError`` guard.
    """
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValueError("due_date must be a calendar date (YYYY-MM-DD).")


def _anchor_project() -> Project:
    project = Project.query.order_by(Project.created_at, Project.id).first()
    if project is None:
        raise OperationError("Create at least one epic before adding stakeholders.", status=409)
    return project


def _rehome_project_stakeholders(project: Project) -> None:
    """Keep shared stakeholders alive when an epic is removed."""
    count = Stakeholder.query.filter(Stakeholder.project_id == project.id).count()
    if count == 0:
        return

    target = (
        Project.query
        .filter(Project.id != project.id)
        .order_by(Project.created_at, Project.id)
        .first()
    )
    if target is None:
        raise OperationError(
            "Cannot delete the last epic while shared stakeholders exist. "
            "Create another epic first or delete stakeholders.",
            status=409,
        )

    Stakeholder.query.filter(Stakeholder.project_id == project.id).update(
        {Stakeholder.project_id: target.id},
        synchronize_session=False,
    )


@ops_bp.errorhandler(OperationError)
def _handle_op_error(err: OperationError):
    return jsonify(ok=False, error="operation_error", message=err.message), err.status


@ops_bp.errorhandler(AuthError)
def _handle_auth_error(err: AuthError):
    return jsonify(ok=False, error="auth_error", message=err.message), err.status


@ops_bp.errorhandler(CommunityError)
def _handle_community_error(err: CommunityError):
    return jsonify(ok=False, error="community_error", message=err.message), err.status


# ---------------------------------------------------------------------------
# Access guard — every command-center API path is organizer-only.
# Participants and industry partners use the separate portal blueprint.
# ---------------------------------------------------------------------------
@ops_bp.before_request
def _guard_staff_api():
    if request.path.startswith("/api/"):
        user = current_user()
        if user is None:
            return jsonify(ok=False, error="unauthorized",
                           message="Authentication required."), 401
        if not user.is_staff:
            return jsonify(ok=False, error="forbidden",
                           message="Organizer access required."), 403


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
@ops_bp.route("/")
def dashboard():
    """Role-aware landing: login, Platform, or a self-service portal."""
    user = current_user()
    if user is None:
        return render_template("login.html")
    if user.is_staff:
        return render_template(
            "dashboard.html",
            current_user=user,
            task_states=[{"key": s.name, "label": s.value} for s in TaskState.ordered()],
            stakeholder_roles=[{"key": t.name, "label": t.value} for t in StakeholderRoleType],
            stakeholder_role_groups=stakeholder_role_groups_meta(),
            stakeholder_statuses=[{"key": s.name, "label": s.value} for s in StakeholderStatus],
            user_roles=[{"key": r.name, "label": r.value} for r in UserRole],
            community_meta=_community_meta(),
            selection_cap=community_service.selection_cap(),
        )
    if user.is_stakeholder:
        return render_template("stakeholder.html", current_user=user)
    if user.is_participant:
        return render_template("participant.html", current_user=user)
    return render_template("login.html")


@ops_bp.route("/register")
def register_page():
    """Public participant registration page."""
    if current_user() is not None:
        from flask import redirect
        return redirect("/")
    return render_template("register.html", industries=SUGGESTED_INDUSTRIES,
                           experience_levels=_enum_meta(ExperienceLevel))


@ops_bp.route("/health")
def health():
    """Liveness probe for container orchestration."""
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify(ok=True, status="healthy"), 200
    except Exception as exc:  # pragma: no cover
        return jsonify(ok=False, status="degraded", message=str(exc)), 503


# ---------------------------------------------------------------------------
# Bootstrap snapshot — everything the SPA needs in one call
# ---------------------------------------------------------------------------
@ops_bp.route("/api/bootstrap")
@login_required
def bootstrap():
    projects = Project.query.order_by(Project.created_at).all()
    users = User.query.order_by(User.created_at).all()
    docs = Doc.query.order_by(Doc.updated_at.desc()).all()
    return jsonify(
        ok=True,
        me=current_user().to_dict(),
        projects=[p.to_dict(include_children=True) for p in projects],
        users=[u.to_dict() for u in users],
        docs=[d.to_dict() for d in docs],
    )


# ---------------------------------------------------------------------------
# Docs (workspace-level rich-text knowledge base)
# ---------------------------------------------------------------------------
@ops_bp.route("/api/docs", methods=["GET"])
@login_required
def list_docs():
    docs = Doc.query.order_by(Doc.updated_at.desc()).all()
    return jsonify(ok=True, docs=[d.to_dict() for d in docs])


@ops_bp.route("/api/docs", methods=["POST"])
@login_required
def create_doc():
    data = _payload()
    _require(data, "title")
    try:
        doc = Doc(
            title=data["title"].strip(),
            content=data.get("content"),
            created_by=current_user().id,
        )
        db.session.add(doc)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not create doc: {exc}", status=422)
    return jsonify(ok=True, doc=doc.to_dict()), 201


@ops_bp.route("/api/docs/<int:doc_id>", methods=["GET"])
@login_required
def get_doc(doc_id):
    doc = _get_or_404(Doc, doc_id, "Doc")
    return jsonify(ok=True, doc=doc.to_dict())


@ops_bp.route("/api/docs/<int:doc_id>", methods=["PATCH", "PUT"])
@login_required
def update_doc(doc_id):
    doc = _get_or_404(Doc, doc_id, "Doc")
    data = _payload()
    try:
        if "title" in data and data["title"]:
            doc.title = data["title"].strip()
        if "content" in data:
            doc.content = data.get("content")
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not update doc: {exc}", status=422)
    return jsonify(ok=True, doc=doc.to_dict())


@ops_bp.route("/api/docs/<int:doc_id>", methods=["DELETE"])
@login_required
def delete_doc(doc_id):
    doc = _get_or_404(Doc, doc_id, "Doc")
    try:
        db.session.delete(doc)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not delete doc: {exc}", status=409)
    return jsonify(ok=True, deleted=doc_id)


# ---------------------------------------------------------------------------
# Team administration (admin only)
# ---------------------------------------------------------------------------
@ops_bp.route("/api/users", methods=["GET"])
@login_required
def list_users():
    users = User.query.order_by(User.created_at).all()
    return jsonify(ok=True, users=[u.to_dict() for u in users])


@ops_bp.route("/api/users", methods=["POST"])
@admin_required
def invite_user():
    data = _payload()
    _require(data, "email")
    user = auth_service.invite_member(
        email=data["email"],
        role=data.get("role", "member"),
        username=data.get("username"),
        is_scrum_master=bool(data.get("is_scrum_master", False)),
    )
    return jsonify(ok=True, user=user.to_dict()), 201


@ops_bp.route("/api/users/<int:user_id>", methods=["PATCH", "PUT"])
@admin_required
def update_user(user_id):
    user = _get_or_404(User, user_id, "User")
    data = _payload()
    status = None
    if "status" in data and data["status"]:
        try:
            status = UserStatus(data["status"]) if data["status"] in {s.value for s in UserStatus} \
                else UserStatus[data["status"].upper()]
        except (KeyError, ValueError):
            raise OperationError(f"Unknown status: {data['status']}", status=400)

    # Guard: do not allow demoting/disabling the last remaining admin.
    if (data.get("role") and data["role"] not in ("admin", "ADMIN")) or status == UserStatus.DISABLED:
        if user.is_admin:
            other_admins = User.query.filter(
                User.role == UserRole.ADMIN, User.id != user.id,
                User.status != UserStatus.DISABLED,
            ).count()
            if other_admins == 0:
                raise OperationError("Cannot demote or disable the last administrator.", status=409)

    auth_service.update_member(
        user,
        role=data.get("role"),
        status=status,
        username=data.get("username") if "username" in data else None,
        is_scrum_master=data.get("is_scrum_master") if "is_scrum_master" in data else None,
    )
    return jsonify(ok=True, user=user.to_dict())


@ops_bp.route("/api/users/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    user = _get_or_404(User, user_id, "User")
    if user.id == current_user().id:
        raise OperationError("You cannot remove your own account.", status=409)
    if user.is_admin:
        other_admins = User.query.filter(
            User.role == UserRole.ADMIN, User.id != user.id,
            User.status != UserStatus.DISABLED,
        ).count()
        if other_admins == 0:
            raise OperationError("Cannot remove the last administrator.", status=409)
    auth_service.remove_member(user)
    return jsonify(ok=True, deleted=user_id)


# ---------------------------------------------------------------------------
# Projects (Epics)
# ---------------------------------------------------------------------------
@ops_bp.route("/api/projects", methods=["GET"])
@login_required
def list_projects():
    projects = Project.query.order_by(Project.created_at).all()
    return jsonify(ok=True, projects=[p.to_dict(include_children=True) for p in projects])


@ops_bp.route("/api/projects", methods=["POST"])
@login_required
def create_project():
    data = _payload()
    _require(data, "name")
    owner_id = data.get("owner_id")
    if owner_id is not None:
        _get_or_404(User, owner_id, "User")
    try:
        project = Project(
            name=data["name"].strip(),
            description=data.get("description"),
            owner_id=owner_id,
        )
        db.session.add(project)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not create epic: {exc}", status=422)
    return jsonify(ok=True, project=project.to_dict(include_children=True)), 201


@ops_bp.route("/api/projects/<int:project_id>", methods=["GET"])
@login_required
def get_project(project_id):
    project = _get_or_404(Project, project_id, "Project")
    return jsonify(ok=True, project=project.to_dict(include_children=True))


@ops_bp.route("/api/projects/<int:project_id>", methods=["PATCH", "PUT"])
@login_required
def update_project(project_id):
    project = _get_or_404(Project, project_id, "Project")
    data = _payload()
    try:
        if "name" in data and data["name"]:
            project.name = data["name"].strip()
        if "description" in data:
            project.description = data.get("description")
        if "owner_id" in data:
            owner_id = data.get("owner_id")
            if owner_id is not None:
                _get_or_404(User, owner_id, "User")
            project.owner_id = owner_id
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not update epic: {exc}", status=422)
    return jsonify(ok=True, project=project.to_dict(include_children=True))


@ops_bp.route("/api/projects/<int:project_id>", methods=["DELETE"])
@login_required
def delete_project(project_id):
    project = _get_or_404(Project, project_id, "Project")
    try:
        _rehome_project_stakeholders(project)
        db.session.delete(project)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not delete epic: {exc}", status=409)
    return jsonify(ok=True, deleted=project_id)


# ---------------------------------------------------------------------------
# Sprints
# ---------------------------------------------------------------------------
@ops_bp.route("/api/projects/<int:project_id>/sprints", methods=["POST"])
@login_required
def create_sprint(project_id):
    project = _get_or_404(Project, project_id, "Project")
    data = _payload()
    _require(data, "name")
    try:
        sprint = Sprint(
            name=data["name"].strip(),
            sequence=int(data.get("sequence", len(project.sprints))),
            goal=data.get("goal"),
            start_date=_parse_date(data.get("start_date")),
            end_date=_parse_date(data.get("end_date")),
            project_id=project.id,
        )
        db.session.add(sprint)
        db.session.commit()
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        raise OperationError(f"Invalid sprint data: {exc}", status=400)
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not create sprint: {exc}", status=422)
    return jsonify(ok=True, sprint=sprint.to_dict(include_tasks=True)), 201


@ops_bp.route("/api/sprints/<int:sprint_id>", methods=["PATCH", "PUT"])
@login_required
def update_sprint(sprint_id):
    sprint = _get_or_404(Sprint, sprint_id, "Sprint")
    data = _payload()
    try:
        if "name" in data and data["name"]:
            sprint.name = data["name"].strip()
        if "goal" in data:
            sprint.goal = data.get("goal")
        if "sequence" in data and data["sequence"] is not None:
            sprint.sequence = int(data["sequence"])
        if "start_date" in data:
            sprint.start_date = _parse_date(data.get("start_date"))
        if "end_date" in data:
            sprint.end_date = _parse_date(data.get("end_date"))
        db.session.commit()
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        raise OperationError(f"Invalid sprint data: {exc}", status=400)
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not update sprint: {exc}", status=422)
    return jsonify(ok=True, sprint=sprint.to_dict(include_tasks=True))


@ops_bp.route("/api/sprints/<int:sprint_id>", methods=["DELETE"])
@login_required
def delete_sprint(sprint_id):
    sprint = _get_or_404(Sprint, sprint_id, "Sprint")
    try:
        db.session.delete(sprint)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not delete sprint: {exc}", status=409)
    return jsonify(ok=True, deleted=sprint_id)


# ---------------------------------------------------------------------------
# Stakeholders (multi-role + status workflow)
# ---------------------------------------------------------------------------
@ops_bp.route("/api/projects/<int:project_id>/stakeholders", methods=["POST"])
@login_required
def create_stakeholder(project_id):
    _get_or_404(Project, project_id, "Project")
    anchor = _anchor_project()
    data = _payload()
    _require(data, "name")
    roles = data.get("roles") or []
    if not isinstance(roles, list) or not roles:
        raise OperationError("Select at least one stakeholder role.", status=400)
    try:
        contact_email = (data.get("contact_email") or "").strip().lower() or None
        linked_user = auth_service.get_user_by_email(contact_email) if contact_email else None
        stakeholder = Stakeholder(
            name=data["name"].strip(),
            organization=data.get("organization"),
            industry=data.get("industry"),
            hackathon_status=coerce_enum(
                StakeholderHackathonStatus,
                data.get("hackathon_status", "EXPLORING"),
                field="hackathon status",
            ),
            about=data.get("about"),
            website=data.get("website"),
            status=coerce_stakeholder_status(data.get("status", "PENDING")),
            contact_email=contact_email,
            contact_phone=data.get("contact_phone"),
            notes=data.get("notes"),
            project_id=anchor.id,
        )
        if linked_user is not None and linked_user.is_stakeholder:
            stakeholder.user_id = linked_user.id
        stakeholder.set_roles(roles)
        db.session.add(stakeholder)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        raise OperationError(str(exc), status=400)
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not create stakeholder: {exc}", status=422)
    return jsonify(ok=True, stakeholder=stakeholder.to_dict()), 201


@ops_bp.route("/api/stakeholders/<int:stakeholder_id>", methods=["PATCH", "PUT"])
@login_required
def update_stakeholder(stakeholder_id):
    stakeholder = _get_or_404(Stakeholder, stakeholder_id, "Stakeholder")
    data = _payload()
    try:
        if "name" in data and data["name"]:
            stakeholder.name = data["name"].strip()
        if "organization" in data:
            stakeholder.organization = data.get("organization")
        if "industry" in data:
            stakeholder.industry = data.get("industry")
        if "hackathon_status" in data and data["hackathon_status"]:
            stakeholder.hackathon_status = coerce_enum(
                StakeholderHackathonStatus,
                data["hackathon_status"],
                field="hackathon status",
            )
        if "about" in data:
            stakeholder.about = data.get("about")
        if "website" in data:
            stakeholder.website = data.get("website")
        if "status" in data and data["status"]:
            stakeholder.status = coerce_stakeholder_status(data["status"])
        if "contact_email" in data:
            email = (data.get("contact_email") or "").strip().lower() or None
            stakeholder.contact_email = email
        if "contact_phone" in data:
            stakeholder.contact_phone = data.get("contact_phone")
        if "notes" in data:
            stakeholder.notes = data.get("notes")
        if "roles" in data:
            roles = data.get("roles") or []
            if not roles:
                raise OperationError("A stakeholder needs at least one role.", status=400)
            stakeholder.set_roles(roles)

        if stakeholder.contact_email:
            linked_user = auth_service.get_user_by_email(stakeholder.contact_email)
            if linked_user is not None and linked_user.is_stakeholder:
                stakeholder.user_id = linked_user.id
            elif "contact_email" in data:
                stakeholder.user_id = None
        elif "contact_email" in data:
            stakeholder.user_id = None
        db.session.commit()
    except OperationError:
        db.session.rollback()
        raise
    except ValueError as exc:
        db.session.rollback()
        raise OperationError(str(exc), status=400)
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not update stakeholder: {exc}", status=422)
    return jsonify(ok=True, stakeholder=stakeholder.to_dict())


@ops_bp.route("/api/stakeholders/<int:stakeholder_id>", methods=["DELETE"])
@login_required
def delete_stakeholder(stakeholder_id):
    stakeholder = _get_or_404(Stakeholder, stakeholder_id, "Stakeholder")
    try:
        db.session.delete(stakeholder)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not delete stakeholder: {exc}", status=409)
    return jsonify(ok=True, deleted=stakeholder_id)


@ops_bp.route("/api/stakeholders/<int:stakeholder_id>/tasks", methods=["GET"])
@login_required
def tasks_by_stakeholder(stakeholder_id):
    """Dependency interlocking: list every task bound to a stakeholder."""
    stakeholder = _get_or_404(Stakeholder, stakeholder_id, "Stakeholder")
    return jsonify(
        ok=True,
        stakeholder=stakeholder.to_dict(),
        tasks=[t.to_dict() for t in stakeholder.tasks],
    )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
@ops_bp.route("/api/sprints/<int:sprint_id>/tasks", methods=["POST"])
@login_required
def create_task(sprint_id):
    sprint = _get_or_404(Sprint, sprint_id, "Sprint")
    data = _payload()
    _require(data, "title")
    assigned_user_ids = _coerce_assignee_ids(data)
    try:
        task = Task(
            title=data["title"].strip(),
            description=data.get("description"),
            priority=int(data.get("priority", 2)),
            due_date=_parse_due_date(data.get("due_date")),
            sprint_id=sprint.id,
            assigned_to=assigned_user_ids[0] if assigned_user_ids else None,
            stakeholder_id=data.get("stakeholder_id"),
        )
        task.set_assignees(assigned_user_ids)
        db.session.add(task)
        db.session.commit()
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        raise OperationError(f"Invalid task data: {exc}", status=400)
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not create task: {exc}", status=422)

    if task.assigned_users:
        db.session.refresh(task)
        from .services import mail_service
        for assignee in task.assigned_users:
            mail_service.send_assignment_notification(task, assignee)

    return jsonify(ok=True, task=task.to_dict()), 201


@ops_bp.route("/api/tasks/<int:task_id>", methods=["GET"])
@login_required
def get_task(task_id):
    task = _get_or_404(Task, task_id, "Task")
    return jsonify(ok=True, task=task.to_dict())


@ops_bp.route("/api/tasks/<int:task_id>", methods=["PATCH", "PUT"])
@login_required
def update_task(task_id):
    """Edit task core fields (title, description, priority, due date, sprint, stakeholder)."""
    task = _get_or_404(Task, task_id, "Task")
    data = _payload()

    # Validate relational moves up-front so they surface as clean 404s instead
    # of being swallowed by the broad update guard below.
    new_sprint_id = None
    if "sprint_id" in data and data.get("sprint_id") not in (None, ""):
        try:
            new_sprint_id = int(data["sprint_id"])
        except (TypeError, ValueError):
            raise OperationError("sprint_id must be an integer.", status=400)
        _get_or_404(Sprint, new_sprint_id, "Sprint")

    change_stakeholder = "stakeholder_id" in data
    new_stakeholder_id = None
    if change_stakeholder and data.get("stakeholder_id") not in (None, ""):
        try:
            new_stakeholder_id = int(data["stakeholder_id"])
        except (TypeError, ValueError):
            raise OperationError("stakeholder_id must be an integer.", status=400)
        _get_or_404(Stakeholder, new_stakeholder_id, "Stakeholder")

    try:
        if "title" in data and data["title"]:
            task.title = data["title"].strip()
        if "description" in data:
            task.description = data.get("description")
        if "priority" in data and data["priority"] is not None:
            task.priority = int(data["priority"])
        if "due_date" in data:
            task.due_date = _parse_due_date(data.get("due_date"))
        if new_sprint_id is not None:
            task.sprint_id = new_sprint_id
        if change_stakeholder:
            task.stakeholder_id = new_stakeholder_id
        db.session.commit()
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        raise OperationError(f"Invalid task data: {exc}", status=400)
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not update task: {exc}", status=422)
    return jsonify(ok=True, task=task.to_dict())


@ops_bp.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id):
    task = _get_or_404(Task, task_id, "Task")
    try:
        db.session.delete(task)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not delete task: {exc}", status=409)
    return jsonify(ok=True, deleted=task_id)


@ops_bp.route("/api/tasks/<int:task_id>/assign", methods=["POST"])
@login_required
def assign_task(task_id):
    task = _get_or_404(Task, task_id, "Task")
    data = _payload()
    if "user_ids" in data or "assigned_user_ids" in data:
        user_ids = data.get("user_ids")
        if user_ids is None:
            user_ids = data.get("assigned_user_ids")
        if not isinstance(user_ids, list):
            raise OperationError("user_ids must be an array.", status=400)
        ops_service.assign_task_multiple(task, user_ids)
    else:
        user_id = data.get("user_id")  # null clears assignment
        ops_service.assign_task(task, user_id)
    return jsonify(ok=True, task=task.to_dict())


@ops_bp.route("/api/tasks/<int:task_id>/transition", methods=["POST"])
@login_required
def transition_task(task_id):
    task = _get_or_404(Task, task_id, "Task")
    data = _payload()
    _require(data, "state")
    ops_service.transition_task(task, data["state"])
    return jsonify(ok=True, task=task.to_dict())


@ops_bp.route("/api/tasks/<int:task_id>/block", methods=["POST"])
@login_required
def block_task(task_id):
    task = _get_or_404(Task, task_id, "Task")
    data = _payload()
    blocked = bool(data.get("blocked", True))
    reason = data.get("reason")
    ops_service.set_task_block(task, blocked, reason)
    return jsonify(ok=True, task=task.to_dict())


@ops_bp.route("/api/tasks/<int:task_id>/stakeholder", methods=["POST"])
@login_required
def link_stakeholder(task_id):
    task = _get_or_404(Task, task_id, "Task")
    data = _payload()
    ops_service.link_task_stakeholder(task, data.get("stakeholder_id"))
    return jsonify(ok=True, task=task.to_dict())


# ---------------------------------------------------------------------------
# Community oversight (organizer view of partners, participants & teams)
# ---------------------------------------------------------------------------
@ops_bp.route("/api/community", methods=["GET"])
@login_required
def community_overview():
    """One snapshot powering the Participants, Teams & Partners views."""
    partners = Stakeholder.query.order_by(Stakeholder.created_at).all()
    participants = (
        ParticipantProfile.query.order_by(ParticipantProfile.applied_at.desc()).all()
    )
    teams = Team.query.order_by(Team.created_at.desc()).all()
    requirements = (
        IndustryRequirement.query.order_by(IndustryRequirement.created_at.desc()).all()
    )
    return jsonify(
        ok=True,
        partners=[s.to_dict(include_requirements=True) for s in partners],
        participants=[p.to_dict(include_private=True) for p in participants],
        teams=[t.to_dict() for t in teams],
        requirements=[r.to_dict() for r in requirements],
        selection_cap=community_service.selection_cap(),
        selected_count=community_service.selected_count(),
        meta=_community_meta(),
    )


@ops_bp.route("/api/participants/<int:profile_id>", methods=["PATCH", "PUT"])
@login_required
def update_participant(profile_id):
    """Advance a participant through the selection funnel / save interview notes."""
    profile = _get_or_404(ParticipantProfile, profile_id, "Participant")
    data = _payload()
    if data.get("selection_status"):
        community_service.set_selection_status(
            profile, data["selection_status"], data.get("interview_notes")
        )
    elif "interview_notes" in data:
        try:
            profile.interview_notes = data.get("interview_notes")
            db.session.commit()
        except Exception as exc:  # pragma: no cover - defensive
            db.session.rollback()
            raise OperationError(f"Could not save notes: {exc}", status=422)
    return jsonify(
        ok=True,
        participant=profile.to_dict(include_private=True),
        selected_count=community_service.selected_count(),
    )


@ops_bp.route("/api/industry-partners/invite", methods=["POST"])
@login_required
def invite_partner():
    """Provision an industry-partner account (email-only sign-in)."""
    data = _payload()
    _require(data, "email")

    existing = auth_service.get_stakeholder_by_email(data["email"])
    if existing is not None and existing.user_id is not None:
        raise OperationError("Portal login is already enabled for this partner.", status=409)

    if existing is None:
        # New stakeholders are global to the whole program; keep them on a
        # stable anchor project so deleting an epic does not remove them.
        anchor = _anchor_project()
        roles = data.get("roles") or [StakeholderRoleType.IN_KIND_SPONSOR.name]
        if not isinstance(roles, list) or not roles:
            raise OperationError("roles must be a non-empty array.", status=400)
        try:
            stakeholder = Stakeholder(
                name=(data.get("name") or data["email"].split("@")[0]).strip(),
                organization=data.get("organization"),
                industry=data.get("industry"),
                status=coerce_stakeholder_status(data.get("status", "PENDING")),
                contact_email=data["email"].strip().lower(),
                contact_phone=data.get("contact_phone"),
                notes=data.get("notes"),
                project_id=anchor.id,
            )
            stakeholder.set_roles(roles)
            db.session.add(stakeholder)
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            raise OperationError(str(exc), status=400)
        except Exception as exc:
            db.session.rollback()
            raise OperationError(f"Could not create industry partner: {exc}", status=422)

    user = auth_service.invite_stakeholder(
        email=data["email"],
        name=data.get("name"),
        organization=data.get("organization"),
        industry=data.get("industry"),
    )
    return jsonify(ok=True, user=user.to_dict()), 201


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------
def _parse_date(value):
    if value in (None, ""):
        return None
    from datetime import date

    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _coerce_assignee_ids(data: dict) -> list[int]:
    raw_ids = []
    if "assigned_user_ids" in data:
        raw_ids = data.get("assigned_user_ids") or []
    elif "assignees" in data:
        raw_ids = data.get("assignees") or []
    elif data.get("assigned_to") not in (None, ""):
        raw_ids = [data.get("assigned_to")]

    if not isinstance(raw_ids, list):
        raise OperationError("assigned_user_ids must be an array.", status=400)

    normalized: list[int] = []
    for raw in raw_ids:
        if raw in (None, ""):
            continue
        try:
            user_id = int(raw)
        except (TypeError, ValueError):
            raise OperationError(f"Invalid assignee id: {raw!r}", status=400)
        if user_id not in normalized:
            normalized.append(user_id)
    return normalized

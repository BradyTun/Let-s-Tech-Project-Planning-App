"""
app/routes.py
=============
Operations Blueprint — RESTful JSON API plus the single-page command center.
All `/api/*` paths require an authenticated session; team administration paths
additionally require the admin role. Write paths delegate to the transactional
service layer so business rules, gatekeepers, rollbacks, and async comms fire
in exactly one place.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from .extensions import db
from .models import (
    User,
    Project,
    Sprint,
    Task,
    Stakeholder,
    TaskState,
    StakeholderRoleType,
    StakeholderStatus,
    UserRole,
    UserStatus,
    coerce_stakeholder_status,
    stakeholder_role_groups_meta,
)
from .services import ops_service
from .services.ops_service import OperationError
from .services import auth_service
from .services.auth_service import AuthError
from .auth import login_required, admin_required, current_user

ops_bp = Blueprint("ops", __name__)


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


@ops_bp.errorhandler(OperationError)
def _handle_op_error(err: OperationError):
    return jsonify(ok=False, error="operation_error", message=err.message), err.status


@ops_bp.errorhandler(AuthError)
def _handle_auth_error(err: AuthError):
    return jsonify(ok=False, error="auth_error", message=err.message), err.status


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
@ops_bp.route("/")
def dashboard():
    """Login screen for anonymous visitors; the app for authenticated users."""
    user = current_user()
    if user is None:
        return render_template("login.html")
    return render_template(
        "dashboard.html",
        current_user=user,
        task_states=[{"key": s.name, "label": s.value} for s in TaskState.ordered()],
        stakeholder_roles=[{"key": t.name, "label": t.value} for t in StakeholderRoleType],
        stakeholder_role_groups=stakeholder_role_groups_meta(),
        stakeholder_statuses=[{"key": s.name, "label": s.value} for s in StakeholderStatus],
        user_roles=[{"key": r.name, "label": r.value} for r in UserRole],
    )


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
    return jsonify(
        ok=True,
        me=current_user().to_dict(),
        projects=[p.to_dict(include_children=True) for p in projects],
        users=[u.to_dict() for u in users],
    )


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
    project = _get_or_404(Project, project_id, "Project")
    data = _payload()
    _require(data, "name")
    roles = data.get("roles") or []
    if not isinstance(roles, list) or not roles:
        raise OperationError("Select at least one stakeholder role.", status=400)
    try:
        stakeholder = Stakeholder(
            name=data["name"].strip(),
            organization=data.get("organization"),
            status=coerce_stakeholder_status(data.get("status", "PENDING")),
            contact_email=data.get("contact_email"),
            contact_phone=data.get("contact_phone"),
            notes=data.get("notes"),
            project_id=project.id,
        )
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
        if "status" in data and data["status"]:
            stakeholder.status = coerce_stakeholder_status(data["status"])
        if "contact_email" in data:
            stakeholder.contact_email = data.get("contact_email")
        if "contact_phone" in data:
            stakeholder.contact_phone = data.get("contact_phone")
        if "notes" in data:
            stakeholder.notes = data.get("notes")
        if "roles" in data:
            roles = data.get("roles") or []
            if not roles:
                raise OperationError("A stakeholder needs at least one role.", status=400)
            stakeholder.set_roles(roles)
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
    try:
        task = Task(
            title=data["title"].strip(),
            description=data.get("description"),
            priority=int(data.get("priority", 2)),
            sprint_id=sprint.id,
            assigned_to=data.get("assigned_to"),
            stakeholder_id=data.get("stakeholder_id"),
        )
        db.session.add(task)
        db.session.commit()
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        raise OperationError(f"Invalid task data: {exc}", status=400)
    except Exception as exc:
        db.session.rollback()
        raise OperationError(f"Could not create task: {exc}", status=422)

    if task.assigned_to is not None:
        db.session.refresh(task)
        from .services import mail_service
        mail_service.send_assignment_notification(task, task.assignee)

    return jsonify(ok=True, task=task.to_dict()), 201


@ops_bp.route("/api/tasks/<int:task_id>", methods=["GET"])
@login_required
def get_task(task_id):
    task = _get_or_404(Task, task_id, "Task")
    return jsonify(ok=True, task=task.to_dict())


@ops_bp.route("/api/tasks/<int:task_id>", methods=["PATCH", "PUT"])
@login_required
def update_task(task_id):
    """Edit task core fields (title, markdown description, priority)."""
    task = _get_or_404(Task, task_id, "Task")
    data = _payload()
    try:
        if "title" in data and data["title"]:
            task.title = data["title"].strip()
        if "description" in data:
            task.description = data.get("description")
        if "priority" in data and data["priority"] is not None:
            task.priority = int(data["priority"])
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
# Internal utilities
# ---------------------------------------------------------------------------
def _parse_date(value):
    if value in (None, ""):
        return None
    from datetime import date

    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))

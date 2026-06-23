"""
app/api/resources.py
====================
The full resource surface of the external REST API. Every first-party
capability is exposed here and delegates to the same models/services used by
the browser UI so behaviour never diverges.

Grouping (see OpenAPI tags):
    Meta / Workspace ......... reference data + one-shot snapshot
    Users .................... organizer team administration (admin)
    Epics / Sprints / Tasks .. the operations board (staff)
    Stakeholders ............. partner matrix + task linking (staff)
    Docs ..................... knowledge base (staff)
    Community ................ participants, teams, partners oversight (staff)
    Requirements ............. published industry problem catalog (any user)
    Portal ................... self-service for stakeholders & participants
"""

from __future__ import annotations

from datetime import date

from flask import current_app

from ..extensions import db
from ..models import (
    User, Project, Sprint, Task, Stakeholder, Doc,
    ParticipantProfile, Team, IndustryRequirement,
    TaskState, UserRole, UserStatus, StakeholderRoleType, StakeholderStatus,
    StakeholderHackathonStatus, RequirementStatus, ExperienceLevel,
    SelectionStatus, TeamStatus, SUGGESTED_INDUSTRIES,
    stakeholder_role_groups_meta, coerce_stakeholder_status, coerce_enum,
    _VISIBLE_REQUIREMENT_STATES,
)
from ..services import ops_service, community_service, auth_service, mail_service
from . import (
    api_v1_bp, ApiError, ok, body, get_or_404, current_api_user, public,
    api_login_required, api_admin_required, api_staff_required,
    api_stakeholder_required, api_participant_required,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
def _enum(enum_cls):
    return [{"key": m.name, "label": m.value} for m in enum_cls]


def _parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ApiError(f"Invalid date: {value!r} (expected YYYY-MM-DD).", 400)


def _assignee_ids(data: dict) -> list[int]:
    raw = []
    if "assigned_user_ids" in data:
        raw = data.get("assigned_user_ids") or []
    elif "assignees" in data:
        raw = data.get("assignees") or []
    elif data.get("assigned_to") not in (None, ""):
        raw = [data.get("assigned_to")]
    if not isinstance(raw, list):
        raise ApiError("assigned_user_ids must be an array.", 400)
    out: list[int] = []
    for item in raw:
        if item in (None, ""):
            continue
        try:
            uid = int(item)
        except (TypeError, ValueError):
            raise ApiError(f"Invalid assignee id: {item!r}", 400)
        if uid not in out:
            out.append(uid)
    return out


def _anchor_epic() -> Project:
    epic = Project.query.order_by(Project.created_at, Project.id).first()
    if epic is None:
        raise ApiError("Create at least one epic before adding stakeholders.", 409)
    return epic


def _rehome_epic_stakeholders(epic: Project) -> None:
    """Keep shared stakeholders alive when an epic is removed."""
    count = Stakeholder.query.filter(Stakeholder.project_id == epic.id).count()
    if count == 0:
        return

    target = (
        Project.query
        .filter(Project.id != epic.id)
        .order_by(Project.created_at, Project.id)
        .first()
    )
    if target is None:
        raise ApiError(
            "Cannot delete the last epic while shared stakeholders exist. "
            "Create another epic first or delete stakeholders.",
            409,
        )

    Stakeholder.query.filter(Stakeholder.project_id == epic.id).update(
        {Stakeholder.project_id: target.id},
        synchronize_session=False,
    )


# ---------------------------------------------------------------------------
# Health + reference data
# ---------------------------------------------------------------------------
@api_v1_bp.route("/health", methods=["GET"])
@public
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return ok({"status": "healthy"})
    except Exception as exc:  # pragma: no cover
        raise ApiError(f"Database unavailable: {exc}", 503, "degraded")


@api_v1_bp.route("/meta", methods=["GET"])
@api_login_required
def meta():
    return ok({"meta": {
        "task_states": [{"key": s.name, "label": s.value} for s in TaskState.ordered()],
        "user_roles": _enum(UserRole),
        "user_statuses": _enum(UserStatus),
        "stakeholder_roles": _enum(StakeholderRoleType),
        "stakeholder_role_groups": stakeholder_role_groups_meta(),
        "stakeholder_statuses": _enum(StakeholderStatus),
        "hackathon_statuses": _enum(StakeholderHackathonStatus),
        "requirement_statuses": _enum(RequirementStatus),
        "experience_levels": _enum(ExperienceLevel),
        "selection_statuses": _enum(SelectionStatus),
        "team_statuses": _enum(TeamStatus),
        "industries": SUGGESTED_INDUSTRIES,
        "selection_cap": community_service.selection_cap(),
        "max_team_size": int(current_app.config.get("MAX_TEAM_SIZE", 5)),
    }})


@api_v1_bp.route("/bootstrap", methods=["GET"])
@api_staff_required
def bootstrap():
    epics = Project.query.order_by(Project.created_at).all()
    users = User.query.order_by(User.created_at).all()
    docs = Doc.query.order_by(Doc.updated_at.desc()).all()
    return ok({
        "me": current_api_user().to_dict(),
        "epics": [p.to_dict(include_children=True) for p in epics],
        "users": [u.to_dict() for u in users],
        "docs": [d.to_dict() for d in docs],
    })


# ---------------------------------------------------------------------------
# Users (organizer team administration)
# ---------------------------------------------------------------------------
@api_v1_bp.route("/users", methods=["GET"])
@api_staff_required
def list_users():
    users = User.query.order_by(User.created_at).all()
    return ok({"users": [u.to_dict() for u in users]})


@api_v1_bp.route("/users", methods=["POST"])
@api_admin_required
def invite_user():
    data = body("email")
    user = auth_service.invite_member(
        email=data["email"],
        role=data.get("role", "member"),
        username=data.get("username"),
        is_scrum_master=bool(data.get("is_scrum_master", False)),
    )
    return ok({"user": user.to_dict()}, status=201)


@api_v1_bp.route("/users/<int:user_id>", methods=["PATCH", "PUT"])
@api_admin_required
def update_user(user_id):
    user = get_or_404(User, user_id, "User")
    data = body()
    status = None
    if data.get("status"):
        try:
            status = (UserStatus(data["status"]) if data["status"] in {s.value for s in UserStatus}
                      else UserStatus[data["status"].upper()])
        except (KeyError, ValueError):
            raise ApiError(f"Unknown status: {data['status']}", 400)

    demoting = bool(data.get("role")) and data["role"] not in ("admin", "ADMIN")
    if (demoting or status == UserStatus.DISABLED) and user.is_admin:
        other_admins = User.query.filter(
            User.role == UserRole.ADMIN, User.id != user.id,
            User.status != UserStatus.DISABLED,
        ).count()
        if other_admins == 0:
            raise ApiError("Cannot demote or disable the last administrator.", 409)

    auth_service.update_member(
        user,
        role=data.get("role"),
        status=status,
        username=data.get("username") if "username" in data else None,
        is_scrum_master=data.get("is_scrum_master") if "is_scrum_master" in data else None,
    )
    return ok({"user": user.to_dict()})


@api_v1_bp.route("/users/<int:user_id>", methods=["DELETE"])
@api_admin_required
def delete_user(user_id):
    user = get_or_404(User, user_id, "User")
    if user.id == current_api_user().id:
        raise ApiError("You cannot remove your own account.", 409)
    if user.is_admin:
        other_admins = User.query.filter(
            User.role == UserRole.ADMIN, User.id != user.id,
            User.status != UserStatus.DISABLED,
        ).count()
        if other_admins == 0:
            raise ApiError("Cannot remove the last administrator.", 409)
    auth_service.remove_member(user)
    return ok({"deleted": user_id})


# ---------------------------------------------------------------------------
# Epics
# ---------------------------------------------------------------------------
@api_v1_bp.route("/epics", methods=["GET"])
@api_staff_required
def list_epics():
    epics = Project.query.order_by(Project.created_at).all()
    return ok({"epics": [p.to_dict(include_children=True) for p in epics]})


@api_v1_bp.route("/epics", methods=["POST"])
@api_staff_required
def create_epic():
    data = body("name")
    owner_id = data.get("owner_id")
    if owner_id is not None:
        get_or_404(User, owner_id, "User")
    try:
        epic = Project(name=data["name"].strip(),
                       description=data.get("description"), owner_id=owner_id)
        db.session.add(epic)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not create epic: {exc}", 422)
    return ok({"epic": epic.to_dict(include_children=True)}, status=201)


@api_v1_bp.route("/epics/<int:epic_id>", methods=["GET"])
@api_staff_required
def get_epic(epic_id):
    epic = get_or_404(Project, epic_id, "Epic")
    return ok({"epic": epic.to_dict(include_children=True)})


@api_v1_bp.route("/epics/<int:epic_id>", methods=["PATCH", "PUT"])
@api_staff_required
def update_epic(epic_id):
    epic = get_or_404(Project, epic_id, "Epic")
    data = body()
    try:
        if "name" in data and data["name"]:
            epic.name = data["name"].strip()
        if "description" in data:
            epic.description = data.get("description")
        if "owner_id" in data:
            owner_id = data.get("owner_id")
            if owner_id is not None:
                get_or_404(User, owner_id, "User")
            epic.owner_id = owner_id
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not update epic: {exc}", 422)
    return ok({"epic": epic.to_dict(include_children=True)})


@api_v1_bp.route("/epics/<int:epic_id>", methods=["DELETE"])
@api_staff_required
def delete_epic(epic_id):
    epic = get_or_404(Project, epic_id, "Epic")
    try:
        _rehome_epic_stakeholders(epic)
        db.session.delete(epic)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not delete epic: {exc}", 409)
    return ok({"deleted": epic_id})


# ---------------------------------------------------------------------------
# Sprints
# ---------------------------------------------------------------------------
@api_v1_bp.route("/epics/<int:epic_id>/sprints", methods=["POST"])
@api_staff_required
def create_sprint(epic_id):
    epic = get_or_404(Project, epic_id, "Epic")
    data = body("name")
    try:
        sprint = Sprint(
            name=data["name"].strip(),
            sequence=int(data.get("sequence", len(epic.sprints))),
            goal=data.get("goal"),
            start_date=_parse_date(data.get("start_date")),
            end_date=_parse_date(data.get("end_date")),
            project_id=epic.id,
        )
        db.session.add(sprint)
        db.session.commit()
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        raise ApiError(f"Invalid sprint data: {exc}", 400)
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not create sprint: {exc}", 422)
    return ok({"sprint": sprint.to_dict(include_tasks=True)}, status=201)


@api_v1_bp.route("/sprints/<int:sprint_id>", methods=["PATCH", "PUT"])
@api_staff_required
def update_sprint(sprint_id):
    sprint = get_or_404(Sprint, sprint_id, "Sprint")
    data = body()
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
        raise ApiError(f"Invalid sprint data: {exc}", 400)
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not update sprint: {exc}", 422)
    return ok({"sprint": sprint.to_dict(include_tasks=True)})


@api_v1_bp.route("/sprints/<int:sprint_id>", methods=["DELETE"])
@api_staff_required
def delete_sprint(sprint_id):
    sprint = get_or_404(Sprint, sprint_id, "Sprint")
    try:
        db.session.delete(sprint)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not delete sprint: {exc}", 409)
    return ok({"deleted": sprint_id})


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
@api_v1_bp.route("/sprints/<int:sprint_id>/tasks", methods=["POST"])
@api_staff_required
def create_task(sprint_id):
    sprint = get_or_404(Sprint, sprint_id, "Sprint")
    data = body("title")
    assigned = _assignee_ids(data)
    try:
        task = Task(
            title=data["title"].strip(),
            description=data.get("description"),
            priority=int(data.get("priority", 2)),
            sprint_id=sprint.id,
            assigned_to=assigned[0] if assigned else None,
            stakeholder_id=data.get("stakeholder_id"),
        )
        task.set_assignees(assigned)
        db.session.add(task)
        db.session.commit()
    except (ValueError, TypeError) as exc:
        db.session.rollback()
        raise ApiError(f"Invalid task data: {exc}", 400)
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not create task: {exc}", 422)

    if task.assigned_users:
        db.session.refresh(task)
        for assignee in task.assigned_users:
            mail_service.send_assignment_notification(task, assignee)
    return ok({"task": task.to_dict()}, status=201)


@api_v1_bp.route("/tasks/<int:task_id>", methods=["GET"])
@api_staff_required
def get_task(task_id):
    return ok({"task": get_or_404(Task, task_id, "Task").to_dict()})


@api_v1_bp.route("/tasks/<int:task_id>", methods=["PATCH", "PUT"])
@api_staff_required
def update_task(task_id):
    task = get_or_404(Task, task_id, "Task")
    data = body()
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
        raise ApiError(f"Invalid task data: {exc}", 400)
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not update task: {exc}", 422)
    return ok({"task": task.to_dict()})


@api_v1_bp.route("/tasks/<int:task_id>", methods=["DELETE"])
@api_staff_required
def delete_task(task_id):
    task = get_or_404(Task, task_id, "Task")
    try:
        db.session.delete(task)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not delete task: {exc}", 409)
    return ok({"deleted": task_id})


@api_v1_bp.route("/tasks/<int:task_id>/assign", methods=["POST"])
@api_staff_required
def assign_task(task_id):
    task = get_or_404(Task, task_id, "Task")
    data = body()
    if "user_ids" in data or "assigned_user_ids" in data:
        user_ids = data.get("user_ids")
        if user_ids is None:
            user_ids = data.get("assigned_user_ids")
        if not isinstance(user_ids, list):
            raise ApiError("user_ids must be an array.", 400)
        ops_service.assign_task_multiple(task, user_ids)
    else:
        ops_service.assign_task(task, data.get("user_id"))
    return ok({"task": task.to_dict()})


@api_v1_bp.route("/tasks/<int:task_id>/transition", methods=["POST"])
@api_staff_required
def transition_task(task_id):
    task = get_or_404(Task, task_id, "Task")
    data = body("state")
    ops_service.transition_task(task, data["state"])
    return ok({"task": task.to_dict()})


@api_v1_bp.route("/tasks/<int:task_id>/block", methods=["POST"])
@api_staff_required
def block_task(task_id):
    task = get_or_404(Task, task_id, "Task")
    data = body()
    ops_service.set_task_block(task, bool(data.get("blocked", True)), data.get("reason"))
    return ok({"task": task.to_dict()})


@api_v1_bp.route("/tasks/<int:task_id>/stakeholder", methods=["POST"])
@api_staff_required
def link_task_stakeholder(task_id):
    task = get_or_404(Task, task_id, "Task")
    data = body()
    ops_service.link_task_stakeholder(task, data.get("stakeholder_id"))
    return ok({"task": task.to_dict()})


# ---------------------------------------------------------------------------
# Stakeholders (partner matrix)
# ---------------------------------------------------------------------------
@api_v1_bp.route("/epics/<int:epic_id>/stakeholders", methods=["POST"])
@api_staff_required
def create_stakeholder(epic_id):
    get_or_404(Project, epic_id, "Epic")
    anchor = _anchor_epic()
    data = body("name")
    roles = data.get("roles") or []
    if not isinstance(roles, list) or not roles:
        raise ApiError("Select at least one stakeholder role.", 400)
    try:
        contact_email = (data.get("contact_email") or "").strip().lower() or None
        linked = auth_service.get_user_by_email(contact_email) if contact_email else None
        stakeholder = Stakeholder(
            name=data["name"].strip(),
            organization=data.get("organization"),
            industry=data.get("industry"),
            hackathon_status=coerce_enum(
                StakeholderHackathonStatus, data.get("hackathon_status", "EXPLORING"),
                field="hackathon status"),
            about=data.get("about"),
            website=data.get("website"),
            status=coerce_stakeholder_status(data.get("status", "PENDING")),
            contact_email=contact_email,
            contact_phone=data.get("contact_phone"),
            notes=data.get("notes"),
            project_id=anchor.id,
        )
        if linked is not None and linked.is_stakeholder:
            stakeholder.user_id = linked.id
        stakeholder.set_roles(roles)
        db.session.add(stakeholder)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        raise ApiError(str(exc), 400)
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not create stakeholder: {exc}", 422)
    return ok({"stakeholder": stakeholder.to_dict(include_requirements=True)}, status=201)


@api_v1_bp.route("/stakeholders/<int:stakeholder_id>", methods=["PATCH", "PUT"])
@api_staff_required
def update_stakeholder(stakeholder_id):
    stakeholder = get_or_404(Stakeholder, stakeholder_id, "Stakeholder")
    data = body()
    try:
        if "name" in data and data["name"]:
            stakeholder.name = data["name"].strip()
        if "organization" in data:
            stakeholder.organization = data.get("organization")
        if "industry" in data:
            stakeholder.industry = data.get("industry")
        if "hackathon_status" in data and data["hackathon_status"]:
            stakeholder.hackathon_status = coerce_enum(
                StakeholderHackathonStatus, data["hackathon_status"], field="hackathon status")
        if "about" in data:
            stakeholder.about = data.get("about")
        if "website" in data:
            stakeholder.website = data.get("website")
        if "status" in data and data["status"]:
            stakeholder.status = coerce_stakeholder_status(data["status"])
        if "contact_email" in data:
            stakeholder.contact_email = (data.get("contact_email") or "").strip().lower() or None
        if "contact_phone" in data:
            stakeholder.contact_phone = data.get("contact_phone")
        if "notes" in data:
            stakeholder.notes = data.get("notes")
        if "roles" in data:
            roles = data.get("roles") or []
            if not roles:
                raise ApiError("A stakeholder needs at least one role.", 400)
            stakeholder.set_roles(roles)
        if stakeholder.contact_email:
            linked = auth_service.get_user_by_email(stakeholder.contact_email)
            if linked is not None and linked.is_stakeholder:
                stakeholder.user_id = linked.id
            elif "contact_email" in data:
                stakeholder.user_id = None
        elif "contact_email" in data:
            stakeholder.user_id = None
        db.session.commit()
    except ApiError:
        db.session.rollback()
        raise
    except ValueError as exc:
        db.session.rollback()
        raise ApiError(str(exc), 400)
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not update stakeholder: {exc}", 422)
    return ok({"stakeholder": stakeholder.to_dict(include_requirements=True)})


@api_v1_bp.route("/stakeholders/<int:stakeholder_id>", methods=["DELETE"])
@api_staff_required
def delete_stakeholder(stakeholder_id):
    stakeholder = get_or_404(Stakeholder, stakeholder_id, "Stakeholder")
    try:
        db.session.delete(stakeholder)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not delete stakeholder: {exc}", 409)
    return ok({"deleted": stakeholder_id})


@api_v1_bp.route("/stakeholders/<int:stakeholder_id>/tasks", methods=["GET"])
@api_staff_required
def tasks_by_stakeholder(stakeholder_id):
    stakeholder = get_or_404(Stakeholder, stakeholder_id, "Stakeholder")
    return ok({
        "stakeholder": stakeholder.to_dict(),
        "tasks": [t.to_dict() for t in stakeholder.tasks],
    })


# ---------------------------------------------------------------------------
# Docs (knowledge base)
# ---------------------------------------------------------------------------
@api_v1_bp.route("/documents", methods=["GET"])
@api_staff_required
def list_docs():
    docs = Doc.query.order_by(Doc.updated_at.desc()).all()
    return ok({"docs": [d.to_dict() for d in docs]})


@api_v1_bp.route("/documents", methods=["POST"])
@api_staff_required
def create_doc():
    data = body("title")
    try:
        doc = Doc(title=data["title"].strip(), content=data.get("content"),
                  created_by=current_api_user().id)
        db.session.add(doc)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not create doc: {exc}", 422)
    return ok({"doc": doc.to_dict()}, status=201)


@api_v1_bp.route("/documents/<int:doc_id>", methods=["GET"])
@api_staff_required
def get_doc(doc_id):
    return ok({"doc": get_or_404(Doc, doc_id, "Doc").to_dict()})


@api_v1_bp.route("/documents/<int:doc_id>", methods=["PATCH", "PUT"])
@api_staff_required
def update_doc(doc_id):
    doc = get_or_404(Doc, doc_id, "Doc")
    data = body()
    try:
        if "title" in data and data["title"]:
            doc.title = data["title"].strip()
        if "content" in data:
            doc.content = data.get("content")
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not update doc: {exc}", 422)
    return ok({"doc": doc.to_dict()})


@api_v1_bp.route("/documents/<int:doc_id>", methods=["DELETE"])
@api_staff_required
def delete_doc(doc_id):
    doc = get_or_404(Doc, doc_id, "Doc")
    try:
        db.session.delete(doc)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise ApiError(f"Could not delete doc: {exc}", 409)
    return ok({"deleted": doc_id})


# ---------------------------------------------------------------------------
# Community oversight (organizer)
# ---------------------------------------------------------------------------
@api_v1_bp.route("/community", methods=["GET"])
@api_staff_required
def community_overview():
    partners = Stakeholder.query.order_by(Stakeholder.created_at).all()
    participants = ParticipantProfile.query.order_by(ParticipantProfile.applied_at.desc()).all()
    teams = Team.query.order_by(Team.created_at.desc()).all()
    requirements = IndustryRequirement.query.order_by(IndustryRequirement.created_at.desc()).all()
    return ok({
        "partners": [s.to_dict(include_requirements=True) for s in partners],
        "participants": [p.to_dict(include_private=True) for p in participants],
        "teams": [t.to_dict() for t in teams],
        "requirements": [r.to_dict() for r in requirements],
        "selection_cap": community_service.selection_cap(),
        "selected_count": community_service.selected_count(),
    })


@api_v1_bp.route("/participants", methods=["GET"])
@api_staff_required
def list_participants():
    participants = ParticipantProfile.query.order_by(ParticipantProfile.applied_at.desc()).all()
    return ok({
        "participants": [p.to_dict(include_private=True) for p in participants],
        "selection_cap": community_service.selection_cap(),
        "selected_count": community_service.selected_count(),
    })


@api_v1_bp.route("/participants/<int:profile_id>", methods=["PATCH", "PUT"])
@api_staff_required
def update_participant(profile_id):
    profile = get_or_404(ParticipantProfile, profile_id, "Participant")
    data = body()
    if data.get("selection_status"):
        community_service.set_selection_status(
            profile, data["selection_status"], data.get("interview_notes"))
    elif "interview_notes" in data:
        try:
            profile.interview_notes = data.get("interview_notes")
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise ApiError(f"Could not save notes: {exc}", 422)
    return ok({
        "participant": profile.to_dict(include_private=True),
        "selected_count": community_service.selected_count(),
    })


@api_v1_bp.route("/teams", methods=["GET"])
@api_staff_required
def list_teams():
    teams = Team.query.order_by(Team.created_at.desc()).all()
    return ok({"teams": [t.to_dict() for t in teams]})


@api_v1_bp.route("/stakeholders/invite", methods=["POST"])
@api_staff_required
def invite_stakeholder_account():
    """Provision (or link) a stakeholder portal account — email-only sign-in."""
    data = body("email")
    existing = auth_service.get_stakeholder_by_email(data["email"])
    if existing is not None and existing.user_id is not None:
        raise ApiError("Portal login is already enabled for this stakeholder.", 409)

    if existing is None:
        # New stakeholders are shared across epics. Anchor once so they don't
        # get removed when a specific epic is deleted.
        anchor = _anchor_epic()
        roles = data.get("roles") or [StakeholderRoleType.IN_KIND_SPONSOR.name]
        if not isinstance(roles, list) or not roles:
            raise ApiError("roles must be a non-empty array.", 400)
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
            raise ApiError(str(exc), 400)
        except Exception as exc:
            db.session.rollback()
            raise ApiError(f"Could not create stakeholder: {exc}", 422)

    user = auth_service.invite_stakeholder(
        email=data["email"], name=data.get("name"),
        organization=data.get("organization"), industry=data.get("industry"))
    return ok({"user": user.to_dict()}, status=201)


# ---------------------------------------------------------------------------
# Published requirement catalog (any authenticated user)
# ---------------------------------------------------------------------------
@api_v1_bp.route("/requirements", methods=["GET"])
@api_login_required
def list_requirements():
    reqs = (IndustryRequirement.query
            .filter(IndustryRequirement.status.in_(_VISIBLE_REQUIREMENT_STATES))
            .order_by(IndustryRequirement.priority.asc(),
                      IndustryRequirement.created_at.desc())
            .all())
    return ok({"requirements": [r.to_dict() for r in reqs]})


# ---------------------------------------------------------------------------
# Portal — role-aware self-service snapshot
# ---------------------------------------------------------------------------
@api_v1_bp.route("/portal", methods=["GET"])
@api_login_required
def portal_bootstrap():
    user = current_api_user()
    if user.is_stakeholder:
        profile = community_service.ensure_stakeholder_profile(user)
        teams = community_service.teams_for_requirements([r.id for r in profile.requirements])
        return ok({
            "role": "stakeholder",
            "me": user.to_dict(),
            "profile": profile.to_dict(include_requirements=True),
            "interested_teams": [t.to_dict(include_members=False) for t in teams],
        })
    if user.is_participant:
        profile = community_service.ensure_participant_profile(user)
        team = user.team
        reqs = (IndustryRequirement.query
                .filter(IndustryRequirement.status.in_(_VISIBLE_REQUIREMENT_STATES))
                .order_by(IndustryRequirement.priority.asc(),
                          IndustryRequirement.created_at.desc()).all())
        return ok({
            "role": "participant",
            "me": user.to_dict(),
            "profile": profile.to_dict(),
            "team": team.to_dict() if team else None,
            "requirements": [r.to_dict() for r in reqs],
            "selection_cap": community_service.selection_cap(),
            "selected_count": community_service.selected_count(),
            "max_team_size": int(current_app.config.get("MAX_TEAM_SIZE", 5)),
        })
    raise ApiError("This portal is for stakeholders and participants.", 403, "forbidden")


# ----- Portal: stakeholder -------------------------------------------------
@api_v1_bp.route("/portal/stakeholder/profile", methods=["PATCH", "PUT"])
@api_stakeholder_required
def portal_update_stakeholder_profile():
    user = current_api_user()
    profile = community_service.ensure_stakeholder_profile(user)
    community_service.update_stakeholder_profile(profile, body())
    return ok({"profile": profile.to_dict(include_requirements=True)})


@api_v1_bp.route("/portal/stakeholder/requirements", methods=["POST"])
@api_stakeholder_required
def portal_create_requirement():
    user = current_api_user()
    profile = community_service.ensure_stakeholder_profile(user)
    req = community_service.create_requirement(profile, body())
    return ok({"requirement": req.to_dict()}, status=201)


def _owned_requirement(requirement_id: int) -> IndustryRequirement:
    user = current_api_user()
    req = db.session.get(IndustryRequirement, requirement_id)
    partner = req.stakeholder.stakeholder if req and req.stakeholder else None
    if req is None or partner is None or partner.user_id != user.id:
        raise ApiError("Problem statement not found.", 404, "not_found")
    return req


@api_v1_bp.route("/portal/stakeholder/requirements/<int:requirement_id>", methods=["PATCH", "PUT"])
@api_stakeholder_required
def portal_update_requirement(requirement_id):
    req = _owned_requirement(requirement_id)
    community_service.update_requirement(req, body())
    return ok({"requirement": req.to_dict()})


@api_v1_bp.route("/portal/stakeholder/requirements/<int:requirement_id>", methods=["DELETE"])
@api_stakeholder_required
def portal_delete_requirement(requirement_id):
    req = _owned_requirement(requirement_id)
    community_service.delete_requirement(req)
    return ok({"deleted": requirement_id})


# ----- Portal: participant -------------------------------------------------
@api_v1_bp.route("/portal/participant/profile", methods=["PATCH", "PUT"])
@api_participant_required
def portal_update_participant_profile():
    user = current_api_user()
    profile = community_service.ensure_participant_profile(user)
    community_service.update_participant_profile(profile, body())
    return ok({"profile": profile.to_dict()})


@api_v1_bp.route("/portal/participant/team", methods=["POST"])
@api_participant_required
def portal_create_team():
    team = community_service.create_team(current_api_user(), body())
    return ok({"team": team.to_dict()}, status=201)


@api_v1_bp.route("/portal/participant/team", methods=["PATCH", "PUT"])
@api_participant_required
def portal_update_team():
    user = current_api_user()
    team = user.team
    if team is None:
        raise ApiError("You're not in a team yet.", 400)
    community_service.update_team(user, team, body())
    return ok({"team": team.to_dict()})


@api_v1_bp.route("/portal/participant/team/join", methods=["POST"])
@api_participant_required
def portal_join_team():
    data = body("join_code")
    team = community_service.join_team(current_api_user(), data.get("join_code", ""))
    return ok({"team": team.to_dict()})


@api_v1_bp.route("/portal/participant/team/leave", methods=["POST"])
@api_participant_required
def portal_leave_team():
    community_service.leave_team(current_api_user())
    return ok({"message": "You left your team."})

"""
app/models.py
=============
Relational schema for the Hackathon Platform.

Tables
------
    User                -> Team members + auth identities (admin/member).
    OTPToken            -> Single-use, expiring email one-time passcodes.
    Project (Epic)      -> A top-level operational program.
    Sprint              -> Sequentially bounded milestone phases within an epic.
    Task                -> Atomic work items flowing through a linear state machine.
    Stakeholder         -> External parties (sponsors, judges, mentors, speakers…).
    StakeholderRoleLink -> Many-to-many tags so one party can hold many roles.
    Doc                 -> Workspace-level rich-text documents (knowledge base).

Enumerations drive task lanes, user roles/status, stakeholder roles, and the
stakeholder confirmation workflow.
"""

from __future__ import annotations

import enum
import secrets
from datetime import datetime, timezone

from sqlalchemy import Enum as SAEnum, UniqueConstraint
from sqlalchemy.orm import validates
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class TaskState(enum.Enum):
    """Linear kanban lanes. Order is meaningful for transition validation."""

    BACKLOG = "Backlog"
    TODO = "To Do"
    IN_PROGRESS = "In Progress"
    DONE = "Done"

    @classmethod
    def ordered(cls) -> list["TaskState"]:
        return [cls.BACKLOG, cls.TODO, cls.IN_PROGRESS, cls.DONE]


class UserRole(enum.Enum):
    ADMIN = "admin"            # organizer with full control
    MEMBER = "member"          # organizer staff
    STAKEHOLDER = "stakeholder"  # external industry partner (email-only login)
    PARTICIPANT = "participant"  # hackathon applicant / competitor


class UserStatus(enum.Enum):
    INVITED = "invited"    # added by an admin; has not completed onboarding
    ACTIVE = "active"      # completed onboarding (has a username)
    DISABLED = "disabled"  # access revoked but record retained


class StakeholderRoleType(enum.Enum):
    """A stakeholder may hold several of these simultaneously."""

    MAIN_SPONSOR = "Main Sponsor"
    VENUE_SPONSOR = "Venue Sponsor"
    IN_KIND_SPONSOR = "In-Kind Sponsor"
    JUDGE = "Judge"
    MENTOR = "Mentor"
    SPEAKER = "Speaker"
    GUEST = "Guest"


class StakeholderStatus(enum.Enum):
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    REJECTED = "Rejected"


class StakeholderHackathonStatus(enum.Enum):
    """An industry partner's relationship to the hackathon."""

    EXPLORING = "Exploring"
    PROVIDING_PROBLEMS = "Providing Problem Statements"
    SPONSORING = "Sponsoring"
    CONFIRMED_PARTNER = "Confirmed Partner"
    NOT_PARTICIPATING = "Not Participating"


class RequirementStatus(enum.Enum):
    """Lifecycle of an industry problem statement.

    DRAFT is private to the author; OPEN/ADDRESSED are visible to participants;
    CLOSED hides it from the participant-facing catalog.
    """

    DRAFT = "Draft"
    OPEN = "Open"
    ADDRESSED = "Addressed"
    CLOSED = "Closed"


class ExperienceLevel(enum.Enum):
    BEGINNER = "Beginner"
    INTERMEDIATE = "Intermediate"
    ADVANCED = "Advanced"


class SelectionStatus(enum.Enum):
    """Organizer-managed funnel for participant applications."""

    APPLIED = "Applied"
    INTERVIEWING = "Interviewing"
    SELECTED = "Selected"
    WAITLISTED = "Waitlisted"
    REJECTED = "Rejected"


class TeamStatus(enum.Enum):
    FORMING = "Forming"
    SUBMITTED = "Submitted"


# Stakeholder roles grouped for the organizer-facing views. Sponsors are split
# into a "must-have" tier (the event cannot run without them) and an optional
# "supporting" tier, using plain language instead of "mandatory/non-mandatory".
STAKEHOLDER_ROLE_GROUPS = [
    ("ESSENTIAL_SPONSORS", "Essential Sponsors (must-have)",
     [StakeholderRoleType.MAIN_SPONSOR, StakeholderRoleType.VENUE_SPONSOR]),
    ("SUPPORTING_SPONSORS", "Supporting Sponsors (optional)",
     [StakeholderRoleType.IN_KIND_SPONSOR]),
    ("JUDGES_MENTORS", "Judges & Mentors",
     [StakeholderRoleType.JUDGE, StakeholderRoleType.MENTOR]),
    ("SPEAKERS", "Speakers", [StakeholderRoleType.SPEAKER]),
    ("GUESTS", "Guests", [StakeholderRoleType.GUEST]),
]

# Sponsors the event genuinely depends on.
MANDATORY_SPONSOR_ROLES = {
    StakeholderRoleType.MAIN_SPONSOR,
    StakeholderRoleType.VENUE_SPONSOR,
}


def stakeholder_role_groups_meta() -> list[dict]:
    """Serialize the role grouping for the front-end."""
    return [
        {"key": key, "label": label,
         "roles": [{"key": r.name, "label": r.value} for r in roles]}
        for (key, label, roles) in STAKEHOLDER_ROLE_GROUPS
    ]


# Lanes forbidden while a task is unassigned.
_ASSIGNMENT_GATED_STATES = {TaskState.IN_PROGRESS}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(80), nullable=True)           # set at onboarding
    full_name = db.Column(db.String(120), nullable=True)         # legacy / optional
    role = db.Column(
        SAEnum(UserRole, name="user_role"),
        nullable=False, default=UserRole.MEMBER, index=True,
    )
    status = db.Column(
        SAEnum(UserStatus, name="user_status"),
        nullable=False, default=UserStatus.INVITED, index=True,
    )
    is_scrum_master = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    owned_projects = db.relationship("Project", back_populates="owner", lazy="selectin")
    assigned_tasks = db.relationship("Task", back_populates="assignee", lazy="selectin")
    task_assignment_links = db.relationship(
        "TaskAssigneeLink", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    otp_tokens = db.relationship(
        "OTPToken", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    stakeholder = db.relationship(
        "Stakeholder", back_populates="user",
        uselist=False, foreign_keys="Stakeholder.user_id",
    )
    stakeholder_profile = db.relationship(
        "StakeholderProfile", back_populates="user",
        uselist=False, cascade="all, delete-orphan",
    )
    participant_profile = db.relationship(
        "ParticipantProfile", back_populates="user",
        uselist=False, cascade="all, delete-orphan",
    )
    led_teams = db.relationship(
        "Team", back_populates="lead", foreign_keys="Team.lead_user_id",
        cascade="all, delete-orphan", lazy="selectin",
    )
    team_memberships = db.relationship(
        "TeamMember", back_populates="user",
        cascade="all, delete-orphan", lazy="selectin",
    )

    @validates("email")
    def _normalize_email(self, _key, value):
        if not value or "@" not in value:
            raise ValueError("A valid email address is required.")
        return value.strip().lower()

    @validates("username")
    def _check_username(self, _key, value):
        if value is None:
            return value
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Username must be at least 2 characters.")
        if len(cleaned) > 80:
            raise ValueError("Username is too long.")
        return cleaned

    @property
    def display_name(self) -> str:
        return self.username or self.full_name or self.email.split("@")[0]

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_staff(self) -> bool:
        """Organizer access (admin or member) — drives the Platform."""
        return self.role in (UserRole.ADMIN, UserRole.MEMBER)

    @property
    def is_stakeholder(self) -> bool:
        return self.role == UserRole.STAKEHOLDER

    @property
    def is_participant(self) -> bool:
        return self.role == UserRole.PARTICIPANT

    @property
    def team(self):
        """The single team this user belongs to (one-team-per-participant)."""
        for link in self.team_memberships:
            return link.team
        return None

    @property
    def needs_onboarding(self) -> bool:
        return not self.username

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "full_name": self.full_name,
            "display_name": self.display_name,
            "role": self.role.value,
            "status": self.status.value,
            "is_admin": self.is_admin,
            "is_staff": self.is_staff,
            "is_stakeholder": self.is_stakeholder,
            "is_participant": self.is_participant,
            "is_scrum_master": self.is_scrum_master,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.id} {self.email} {self.role.value}>"


# ---------------------------------------------------------------------------
# OTP token
# ---------------------------------------------------------------------------
class OTPToken(db.Model):
    __tablename__ = "otp_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    consumed = db.Column(db.Boolean, nullable=False, default=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    user = db.relationship("User", back_populates="otp_tokens")

    def set_code(self, code: str) -> None:
        self.code_hash = generate_password_hash(code)

    def verify_code(self, code: str) -> bool:
        return check_password_hash(self.code_hash, code)

    @property
    def is_expired(self) -> bool:
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return _utcnow() > exp

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OTPToken user={self.user_id} consumed={self.consumed}>"


# ---------------------------------------------------------------------------
# Project (Epic)
# ---------------------------------------------------------------------------
class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=True)

    owner_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    owner = db.relationship("User", back_populates="owned_projects")
    sprints = db.relationship(
        "Sprint", back_populates="project", cascade="all, delete-orphan",
        lazy="selectin", order_by="Sprint.sequence",
    )
    stakeholders = db.relationship(
        "Stakeholder", back_populates="project", lazy="selectin"
    )

    @property
    def active_sprint(self) -> "Sprint | None":
        for sprint in self.sprints:
            if sprint.is_active:
                return sprint
        return None

    @property
    def has_blocked_tasks(self) -> bool:
        return any(task.is_blocked for sprint in self.sprints for task in sprint.tasks)

    def to_dict(self, include_children: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "owner_id": self.owner_id,
            "owner": self.owner.to_dict() if self.owner else None,
            "active_sprint_id": self.active_sprint.id if self.active_sprint else None,
            "has_blocked_tasks": self.has_blocked_tasks,
        }
        if include_children:
            # Stakeholders are program-wide and shared by every epic.
            shared_stakeholders = (
                Stakeholder.query
                .order_by(Stakeholder.created_at, Stakeholder.id)
                .all()
            )
            data["sprints"] = [s.to_dict(include_tasks=True) for s in self.sprints]
            data["stakeholders"] = [s.to_dict() for s in shared_stakeholders]
        return data

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Project {self.id} {self.name}>"


# ---------------------------------------------------------------------------
# Sprint
# ---------------------------------------------------------------------------
class Sprint(db.Model):
    __tablename__ = "sprints"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    sequence = db.Column(db.Integer, nullable=False, default=0)
    goal = db.Column(db.Text, nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)

    project_id = db.Column(
        db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    project = db.relationship("Project", back_populates="sprints")
    tasks = db.relationship(
        "Task", back_populates="sprint", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self, include_tasks: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "sequence": self.sequence,
            "goal": self.goal,
            "is_active": self.is_active,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "project_id": self.project_id,
            "task_count": len(self.tasks),
        }
        if include_tasks:
            data["tasks"] = [t.to_dict() for t in self.tasks]
        return data

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Sprint {self.id} {self.name} active={self.is_active}>"


# ---------------------------------------------------------------------------
# Stakeholder + role links
# ---------------------------------------------------------------------------
class StakeholderRoleLink(db.Model):
    __tablename__ = "stakeholder_role_links"
    __table_args__ = (UniqueConstraint("stakeholder_id", "role", name="uq_stakeholder_role"),)

    id = db.Column(db.Integer, primary_key=True)
    stakeholder_id = db.Column(
        db.Integer, db.ForeignKey("stakeholders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role = db.Column(SAEnum(StakeholderRoleType, name="stakeholder_role"), nullable=False, index=True)

    stakeholder = db.relationship("Stakeholder", back_populates="role_links")


class Stakeholder(db.Model):
    __tablename__ = "stakeholders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"),
        unique=True, index=True, nullable=True,
    )
    name = db.Column(db.String(160), nullable=False)
    organization = db.Column(db.String(160), nullable=True)
    industry = db.Column(db.String(120), nullable=True, index=True)
    hackathon_status = db.Column(
        SAEnum(StakeholderHackathonStatus, name="stakeholder_hackathon_status"),
        nullable=False, default=StakeholderHackathonStatus.EXPLORING,
    )
    about = db.Column(db.Text, nullable=True)
    website = db.Column(db.String(255), nullable=True)
    status = db.Column(
        SAEnum(StakeholderStatus, name="stakeholder_status"),
        nullable=False, default=StakeholderStatus.PENDING, index=True,
    )
    contact_email = db.Column(db.String(255), nullable=True)
    contact_phone = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    project_id = db.Column(
        db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    project = db.relationship("Project", back_populates="stakeholders")
    user = db.relationship("User", back_populates="stakeholder", foreign_keys=[user_id])
    tasks = db.relationship("Task", back_populates="stakeholder", lazy="selectin")
    role_links = db.relationship(
        "StakeholderRoleLink", back_populates="stakeholder",
        cascade="all, delete-orphan", lazy="selectin",
    )
    partner_profile = db.relationship(
        "StakeholderProfile", back_populates="stakeholder",
        uselist=False, lazy="selectin",
    )

    @validates("contact_email")
    def _check_email(self, _key, value):
        if value and "@" not in value:
            raise ValueError("Stakeholder contact_email must be a valid address.")
        return value.strip().lower() if value else value

    @property
    def roles(self) -> list["StakeholderRoleType"]:
        return [link.role for link in self.role_links]

    def set_roles(self, roles: list) -> None:
        """Replace the stakeholder's role tags with a de-duplicated set.

        Diffs against the existing links (add missing / drop extra) so an
        update never tries to insert a duplicate (stakeholder_id, role) row
        during the same flush.
        """
        wanted: list[StakeholderRoleType] = []
        for r in roles or []:
            rt = coerce_stakeholder_role(r)
            if rt not in wanted:
                wanted.append(rt)
        wanted_set = set(wanted)
        existing = {link.role: link for link in self.role_links}
        for role, link in list(existing.items()):
            if role not in wanted_set:
                self.role_links.remove(link)
        for rt in wanted:
            if rt not in existing:
                self.role_links.append(StakeholderRoleLink(role=rt))

    @property
    def is_critical(self) -> bool:
        return any(r in MANDATORY_SPONSOR_ROLES for r in self.roles)

    @property
    def requirements(self) -> list["IndustryRequirement"]:
        profile = self.partner_profile
        return profile.requirements if profile else []

    @property
    def portal_enabled(self) -> bool:
        return bool(self.user_id)

    @property
    def is_complete(self) -> bool:
        return bool(self.organization and self.industry)

    @property
    def requirement_count(self) -> int:
        return len(self.requirements)

    @property
    def open_requirement_count(self) -> int:
        return sum(1 for r in self.requirements if r.status in _VISIBLE_REQUIREMENT_STATES)

    def to_dict(self, include_requirements: bool = False) -> dict:
        hackathon = self.hackathon_status or StakeholderHackathonStatus.EXPLORING
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "display_name": self.user.display_name if self.user else self.name,
            "email": self.user.email if self.user else self.contact_email,
            "organization": self.organization,
            "industry": self.industry,
            "hackathon_status": hackathon.value,
            "hackathon_status_key": hackathon.name,
            "about": self.about,
            "website": self.website,
            "status": self.status.value,
            "status_key": self.status.name,
            "roles": [{"key": r.name, "label": r.value} for r in self.roles],
            "role_keys": [r.name for r in self.roles],
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "notes": self.notes,
            "project_id": self.project_id,
            "is_critical": self.is_critical,
            "portal_enabled": self.portal_enabled,
            "is_complete": self.is_complete,
            "requirement_count": self.requirement_count,
            "open_requirement_count": self.open_requirement_count,
            "open_task_count": sum(1 for t in self.tasks if t.state != TaskState.DONE),
        }
        if include_requirements:
            data["requirements"] = [r.to_dict() for r in self.requirements]
        return data

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Stakeholder {self.id} {self.name}>"


# ---------------------------------------------------------------------------
# Task assignee links (multi-assignee persistence)
# ---------------------------------------------------------------------------
class TaskAssigneeLink(db.Model):
    __tablename__ = "task_assignee_links"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_assignee_link"),)

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer, db.ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    task = db.relationship("Task", back_populates="assignee_links")
    user = db.relationship("User", back_populates="task_assignment_links")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TaskAssigneeLink task={self.task_id} user={self.user_id}>"


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------
class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

    state = db.Column(
        SAEnum(TaskState, name="task_state"), nullable=False,
        default=TaskState.BACKLOG, index=True,
    )
    is_blocked = db.Column(db.Boolean, nullable=False, default=False, index=True)
    blocked_reason = db.Column(db.String(500), nullable=True)
    priority = db.Column(db.Integer, nullable=False, default=2)  # 1 high .. 3 low
    due_date = db.Column(db.Date, nullable=True, index=True)  # marketing-calendar deadline

    sprint_id = db.Column(
        db.Integer, db.ForeignKey("sprints.id", ondelete="CASCADE"), index=True, nullable=False
    )
    assigned_to = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    stakeholder_id = db.Column(
        db.Integer, db.ForeignKey("stakeholders.id", ondelete="SET NULL"), index=True, nullable=True
    )

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    sprint = db.relationship("Sprint", back_populates="tasks")
    assignee = db.relationship("User", back_populates="assigned_tasks", foreign_keys=[assigned_to])
    assignee_links = db.relationship(
        "TaskAssigneeLink", back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )
    stakeholder = db.relationship("Stakeholder", back_populates="tasks")

    @property
    def assigned_users(self) -> list["User"]:
        users = [link.user for link in self.assignee_links if link.user is not None]
        if not users and self.assignee is not None:
            users = [self.assignee]
        if self.assigned_to is not None and users:
            primary_index = next(
                (index for index, user in enumerate(users) if user.id == self.assigned_to),
                None,
            )
            if primary_index not in (None, 0):
                users.insert(0, users.pop(primary_index))
        return users

    @property
    def assigned_user_ids(self) -> list[int]:
        ids = [user.id for user in self.assigned_users if user and user.id is not None]
        if self.assigned_to is not None and self.assigned_to not in ids:
            ids.insert(0, self.assigned_to)
        return ids

    @property
    def has_assignees(self) -> bool:
        return bool(self.assigned_user_ids)

    def set_assignees(self, user_ids: list[int] | None) -> None:
        normalized: list[int] = []
        for raw in user_ids or []:
            if raw in (None, ""):
                continue
            try:
                user_id = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid user ID in assignees: {raw!r}")
            if user_id not in normalized:
                normalized.append(user_id)

        wanted = set(normalized)
        existing = {link.user_id: link for link in self.assignee_links}

        for user_id, link in list(existing.items()):
            if user_id not in wanted:
                self.assignee_links.remove(link)

        for user_id in normalized:
            if user_id not in existing:
                self.assignee_links.append(TaskAssigneeLink(user_id=user_id))

        self.assigned_to = normalized[0] if normalized else None

    @validates("state")
    def _guard_state_transition(self, _key, new_state):
        if isinstance(new_state, str):
            new_state = _coerce_task_state(new_state)
        if new_state in _ASSIGNMENT_GATED_STATES:
            if not self.has_assignees:
                raise ValueError(
                    f"Task cannot transition to '{new_state.value}' while unassigned."
                )
        return new_state

    def to_dict(self) -> dict:
        assignees = self.assigned_users
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "state": self.state.value,
            "state_key": self.state.name,
            "is_blocked": self.is_blocked,
            "blocked_reason": self.blocked_reason,
            "priority": self.priority,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "sprint_id": self.sprint_id,
            "assigned_to": self.assigned_to,
            "assignee": assignees[0].to_dict() if assignees else None,
            "assigned_user_ids": self.assigned_user_ids,
            "assignees": [user.to_dict() for user in assignees],
            "stakeholder_id": self.stakeholder_id,
            "stakeholder": (
                {"id": self.stakeholder.id, "name": self.stakeholder.name,
                 "roles": [r.value for r in self.stakeholder.roles],
                 "status": self.stakeholder.status.value}
                if self.stakeholder else None
            ),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Task {self.id} {self.title} [{self.state.value}]>"


# ---------------------------------------------------------------------------
# Doc (workspace-level rich-text document)
# ---------------------------------------------------------------------------
class Doc(db.Model):
    """A standalone rich-text document — the lightweight team knowledge base.

    Unlike epics/sprints/tasks, docs are workspace-global: they are not tied
    to any project. Content is sanitized rich HTML produced by the editor.
    """

    __tablename__ = "docs"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)  # sanitized rich HTML

    created_by = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    author = db.relationship("User")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "created_by": self.created_by,
            "author": self.author.to_dict() if self.author else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Doc {self.id} {self.title}>"


# ---------------------------------------------------------------------------
# Coercion helpers (shared by services & routes)
# ---------------------------------------------------------------------------
def _coerce_task_state(value) -> TaskState:
    if isinstance(value, TaskState):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        for state in TaskState:
            if candidate.upper() == state.name or candidate.lower() == state.value.lower():
                return state
    raise ValueError(f"Unknown task state: {value!r}")


def coerce_stakeholder_role(value) -> StakeholderRoleType:
    if isinstance(value, StakeholderRoleType):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        for rt in StakeholderRoleType:
            if candidate.upper() == rt.name or candidate.lower() == rt.value.lower():
                return rt
    raise ValueError(f"Unknown stakeholder role: {value!r}")


def coerce_stakeholder_status(value) -> StakeholderStatus:
    if isinstance(value, StakeholderStatus):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        for st in StakeholderStatus:
            if candidate.upper() == st.name or candidate.lower() == st.value.lower():
                return st
    raise ValueError(f"Unknown stakeholder status: {value!r}")


def coerce_user_role(value) -> UserRole:
    if isinstance(value, UserRole):
        return value
    if isinstance(value, str):
        candidate = value.strip().lower()
        for r in UserRole:
            if candidate == r.name.lower() or candidate == r.value.lower():
                return r
    raise ValueError(f"Unknown user role: {value!r}")


def coerce_enum(enum_cls, value, *, field: str = "value"):
    """Generic, case-insensitive enum coercion by member name or value."""
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        for member in enum_cls:
            if candidate.upper() == member.name or candidate.lower() == member.value.lower():
                return member
    raise ValueError(f"Unknown {field}: {value!r}")


# ---------------------------------------------------------------------------
# Community: industry partners (stakeholder accounts), participants & teams
# ---------------------------------------------------------------------------

# Curated industry suggestions surfaced in the UI (free-text field stays open).
SUGGESTED_INDUSTRIES = [
    "Agriculture", "Healthcare", "Education", "Finance & Banking",
    "Logistics & Supply Chain", "Retail & E-commerce", "Manufacturing",
    "Tourism & Hospitality", "Energy & Utilities", "Government & Public Sector",
    "Telecommunications", "Real Estate & Construction", "Media & Entertainment",
    "Transportation & Mobility", "Non-profit & Social Impact", "Other",
]

# Requirement states visible in the participant-facing problem catalog.
_VISIBLE_REQUIREMENT_STATES = {RequirementStatus.OPEN, RequirementStatus.ADDRESSED}


class StakeholderProfile(db.Model):
    """Self-service profile for an industry partner (stakeholder account)."""

    __tablename__ = "stakeholder_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, index=True, nullable=False,
    )
    stakeholder_id = db.Column(
        db.Integer, db.ForeignKey("stakeholders.id", ondelete="CASCADE"),
        unique=True, index=True, nullable=True,
    )
    organization = db.Column(db.String(160), nullable=True)
    industry = db.Column(db.String(120), nullable=True, index=True)
    hackathon_status = db.Column(
        SAEnum(StakeholderHackathonStatus, name="stakeholder_hackathon_status"),
        nullable=False, default=StakeholderHackathonStatus.EXPLORING,
    )
    about = db.Column(db.Text, nullable=True)
    website = db.Column(db.String(255), nullable=True)
    contact_phone = db.Column(db.String(40), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    user = db.relationship("User", back_populates="stakeholder_profile")
    stakeholder = db.relationship("Stakeholder", back_populates="partner_profile")
    requirements = db.relationship(
        "IndustryRequirement", back_populates="stakeholder",
        cascade="all, delete-orphan", lazy="selectin",
        order_by="IndustryRequirement.created_at.desc()",
    )

    @property
    def is_complete(self) -> bool:
        return bool(self.organization and self.industry)

    def to_dict(self, include_requirements: bool = False) -> dict:
        partner = self.stakeholder
        org = self.organization or (partner.organization if partner else None)
        industry = self.industry or (partner.industry if partner else None)
        hackathon = self.hackathon_status or (
            partner.hackathon_status if partner else StakeholderHackathonStatus.EXPLORING
        )
        about = self.about or (partner.about if partner else None)
        website = self.website or (partner.website if partner else None)
        phone = self.contact_phone or (partner.contact_phone if partner else None)
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "stakeholder_id": self.stakeholder_id,
            "display_name": self.user.display_name if self.user else None,
            "email": self.user.email if self.user else None,
            "organization": org,
            "industry": industry,
            "hackathon_status": hackathon.value,
            "hackathon_status_key": hackathon.name,
            "about": about,
            "website": website,
            "contact_phone": phone,
            "is_complete": bool(org and industry),
            "requirement_count": len(self.requirements),
            "open_requirement_count": sum(
                1 for r in self.requirements if r.status in _VISIBLE_REQUIREMENT_STATES
            ),
        }
        if include_requirements:
            data["requirements"] = [r.to_dict() for r in self.requirements]
        return data

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StakeholderProfile {self.id} {self.organization}>"


class IndustryRequirement(db.Model):
    """A problem statement / automation need posted by an industry partner."""

    __tablename__ = "industry_requirements"

    id = db.Column(db.Integer, primary_key=True)
    stakeholder_id = db.Column(
        db.Integer, db.ForeignKey("stakeholder_profiles.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    title = db.Column(db.String(200), nullable=False)
    industry = db.Column(db.String(120), nullable=True, index=True)
    problem = db.Column(db.Text, nullable=True)
    desired_outcome = db.Column(db.Text, nullable=True)
    priority = db.Column(db.Integer, nullable=False, default=2)  # 1 high .. 3 low
    status = db.Column(
        SAEnum(RequirementStatus, name="requirement_status"),
        nullable=False, default=RequirementStatus.OPEN, index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    stakeholder = db.relationship("StakeholderProfile", back_populates="requirements")
    teams = db.relationship("Team", back_populates="target_requirement", lazy="selectin")

    @property
    def is_public(self) -> bool:
        return self.status in _VISIBLE_REQUIREMENT_STATES

    def to_dict(self, include_stakeholder: bool = True) -> dict:
        data = {
            "id": self.id,
            "stakeholder_id": self.stakeholder_id,
            "title": self.title,
            "industry": self.industry,
            "problem": self.problem,
            "desired_outcome": self.desired_outcome,
            "priority": self.priority,
            "status": self.status.value,
            "status_key": self.status.name,
            "is_public": self.is_public,
            "team_count": len(self.teams),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_stakeholder and self.stakeholder:
            partner = self.stakeholder.stakeholder
            data["organization"] = (
                partner.organization if partner else self.stakeholder.organization
            )
            data["stakeholder_name"] = (
                partner.name if partner
                else (self.stakeholder.user.display_name if self.stakeholder.user else None)
            )
            data["stakeholder_entity_id"] = partner.id if partner else None
        return data

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IndustryRequirement {self.id} {self.title}>"


class ParticipantProfile(db.Model):
    """Application + profile for a hackathon participant."""

    __tablename__ = "participant_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, index=True, nullable=False,
    )
    full_name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    school_or_org = db.Column(db.String(160), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    skills = db.Column(db.Text, nullable=True)
    experience_level = db.Column(
        SAEnum(ExperienceLevel, name="experience_level"),
        nullable=False, default=ExperienceLevel.BEGINNER,
    )
    industry_interest = db.Column(db.String(120), nullable=True)
    selection_status = db.Column(
        SAEnum(SelectionStatus, name="selection_status"),
        nullable=False, default=SelectionStatus.APPLIED, index=True,
    )
    interview_notes = db.Column(db.Text, nullable=True)  # organizer-only
    applied_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    user = db.relationship("User", back_populates="participant_profile")

    @property
    def is_selected(self) -> bool:
        return self.selection_status == SelectionStatus.SELECTED

    def to_dict(self, include_private: bool = False) -> dict:
        user = self.user
        team = user.team if user else None
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "display_name": user.display_name if user else self.full_name,
            "email": user.email if user else None,
            "full_name": self.full_name,
            "phone": self.phone,
            "school_or_org": self.school_or_org,
            "bio": self.bio,
            "skills": self.skills,
            "experience_level": self.experience_level.value,
            "experience_level_key": self.experience_level.name,
            "industry_interest": self.industry_interest,
            "selection_status": self.selection_status.value,
            "selection_status_key": self.selection_status.name,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "team": (
                {"id": team.id, "name": team.name,
                 "is_lead": team.lead_user_id == self.user_id}
                if team else None
            ),
        }
        if include_private:
            data["interview_notes"] = self.interview_notes
        return data

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ParticipantProfile {self.id} {self.full_name} [{self.selection_status.value}]>"


class Team(db.Model):
    """A participant-formed team competing in the hackathon."""

    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    pitch = db.Column(db.Text, nullable=True)
    target_requirement_id = db.Column(
        db.Integer, db.ForeignKey("industry_requirements.id", ondelete="SET NULL"),
        index=True, nullable=True,
    )
    lead_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    join_code = db.Column(db.String(12), unique=True, index=True, nullable=False)
    status = db.Column(
        SAEnum(TeamStatus, name="team_status"),
        nullable=False, default=TeamStatus.FORMING, index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    lead = db.relationship("User", back_populates="led_teams", foreign_keys=[lead_user_id])
    target_requirement = db.relationship("IndustryRequirement", back_populates="teams")
    members = db.relationship(
        "TeamMember", back_populates="team",
        cascade="all, delete-orphan", lazy="selectin",
        order_by="TeamMember.joined_at",
    )

    @staticmethod
    def generate_join_code() -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous chars
        return "".join(secrets.choice(alphabet) for _ in range(6))

    @property
    def size(self) -> int:
        return len(self.members)

    def to_dict(self, include_members: bool = True) -> dict:
        target = self.target_requirement
        target_partner = target.stakeholder.stakeholder if target and target.stakeholder else None
        data = {
            "id": self.id,
            "name": self.name,
            "pitch": self.pitch,
            "status": self.status.value,
            "status_key": self.status.name,
            "join_code": self.join_code,
            "lead_user_id": self.lead_user_id,
            "lead_name": self.lead.display_name if self.lead else None,
            "size": self.size,
            "target_requirement_id": self.target_requirement_id,
            "target_requirement": (
                {"id": target.id, "title": target.title,
                 "industry": target.industry,
                 "organization": (
                     target_partner.organization if target_partner
                     else (target.stakeholder.organization if target.stakeholder else None)
                 )}
                if target else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_members:
            data["members"] = [m.to_dict() for m in self.members]
        return data

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Team {self.id} {self.name}>"


class TeamMember(db.Model):
    """Link row tying a participant to exactly one team."""

    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("user_id", name="uq_team_member_user"),)

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    is_lead = db.Column(db.Boolean, nullable=False, default=False)
    joined_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    team = db.relationship("Team", back_populates="members")
    user = db.relationship("User", back_populates="team_memberships")

    def to_dict(self) -> dict:
        user = self.user
        profile = user.participant_profile if user else None
        return {
            "id": self.id,
            "team_id": self.team_id,
            "user_id": self.user_id,
            "is_lead": self.is_lead,
            "display_name": user.display_name if user else None,
            "email": user.email if user else None,
            "experience_level": profile.experience_level.value if profile else None,
            "skills": profile.skills if profile else None,
            "joined_at": self.joined_at.isoformat() if self.joined_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TeamMember team={self.team_id} user={self.user_id}>"

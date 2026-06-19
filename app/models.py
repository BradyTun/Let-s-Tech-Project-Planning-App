"""
app/models.py
=============
Relational schema for the Hackathon Planning command center.

Tables
------
    User                -> Team members + auth identities (admin/member).
    OTPToken            -> Single-use, expiring email one-time passcodes.
    Project (Epic)      -> A top-level operational program.
    Sprint              -> Sequentially bounded milestone phases within an epic.
    Task                -> Atomic work items flowing through a linear state machine.
    Stakeholder         -> External parties (sponsors, judges, mentors, speakers…).
    StakeholderRoleLink -> Many-to-many tags so one party can hold many roles.

Enumerations drive task lanes, user roles/status, stakeholder roles, and the
stakeholder confirmation workflow.
"""

from __future__ import annotations

import enum
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
    ADMIN = "admin"
    MEMBER = "member"


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
    otp_tokens = db.relationship(
        "OTPToken", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
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
        "Stakeholder", back_populates="project", cascade="all, delete-orphan", lazy="selectin"
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
            data["sprints"] = [s.to_dict(include_tasks=True) for s in self.sprints]
            data["stakeholders"] = [s.to_dict() for s in self.stakeholders]
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
    name = db.Column(db.String(160), nullable=False)
    organization = db.Column(db.String(160), nullable=True)
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
    tasks = db.relationship("Task", back_populates="stakeholder", lazy="selectin")
    role_links = db.relationship(
        "StakeholderRoleLink", back_populates="stakeholder",
        cascade="all, delete-orphan", lazy="selectin",
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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "organization": self.organization,
            "status": self.status.value,
            "status_key": self.status.name,
            "roles": [{"key": r.name, "label": r.value} for r in self.roles],
            "role_keys": [r.name for r in self.roles],
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
            "notes": self.notes,
            "project_id": self.project_id,
            "is_critical": self.is_critical,
            "open_task_count": sum(1 for t in self.tasks if t.state != TaskState.DONE),
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Stakeholder {self.id} {self.name}>"


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
    assignee = db.relationship("User", back_populates="assigned_tasks")
    stakeholder = db.relationship("Stakeholder", back_populates="tasks")

    @validates("state")
    def _guard_state_transition(self, _key, new_state):
        if isinstance(new_state, str):
            new_state = _coerce_task_state(new_state)
        if new_state in _ASSIGNMENT_GATED_STATES:
            if self.assigned_to is None:
                raise ValueError(
                    f"Task cannot transition to '{new_state.value}' while unassigned."
                )
        return new_state

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "state": self.state.value,
            "state_key": self.state.name,
            "is_blocked": self.is_blocked,
            "blocked_reason": self.blocked_reason,
            "priority": self.priority,
            "sprint_id": self.sprint_id,
            "assigned_to": self.assigned_to,
            "assignee": self.assignee.to_dict() if self.assignee else None,
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

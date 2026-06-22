"""
app/services/ops_service.py
===========================
Transactional business-logic layer sitting between the HTTP routes and the
ORM. Every mutating operation is wrapped so that any write anomaly triggers a
clean `db.session.rollback()`, and every side-effecting communication trigger
is fired only *after* the database write has been validated.

Public surface
--------------
    assign_task(task, user_id)                    -> mutate primary assignee
    assign_task_multiple(task, user_ids)          -> mutate persisted assignee set
    transition_task(task, new_state)              -> guarded kanban lane change
    set_task_block(task, blocked, reason)         -> roadblock flag + escalation
    link_task_stakeholder(task, sid)              -> dependency interlocking
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import (
    Task,
    User,
    Stakeholder,
    _coerce_task_state,
)
from . import mail_service


class OperationError(Exception):
    """Raised when a business rule is violated. Carries an HTTP status hint."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Task assignment (Trigger 1)
# ---------------------------------------------------------------------------
def _normalize_user_ids(user_ids: list[int] | None) -> list[int]:
    normalized: list[int] = []
    for raw in user_ids or []:
        if raw in (None, ""):
            continue
        try:
            user_id = int(raw)
        except (TypeError, ValueError):
            raise OperationError(f"Invalid user ID: {raw!r}", status=400)
        if user_id not in normalized:
            normalized.append(user_id)
    return normalized


def _load_assignees(user_ids: list[int]) -> list[User]:
    assignees: list[User] = []
    for user_id in user_ids:
        user = db.session.get(User, user_id)
        if user is None:
            raise OperationError(f"User {user_id} does not exist.", status=404)
        assignees.append(user)
    return assignees


def _notify_new_assignees(task: Task, previous_user_ids: set[int]) -> None:
    current = {user.id: user for user in task.assigned_users}
    for user_id, user in current.items():
        if user_id not in previous_user_ids:
            mail_service.send_assignment_notification(task, user)


def assign_task(task: Task, user_id: int | None) -> Task:
    """
    Mutate `task.assigned_to`. When the value changes to a real user, dispatch
    the asynchronous assignment notification AFTER a successful commit.
    """
    return assign_task_multiple(task, [] if user_id is None else [user_id])


def assign_task_multiple(task: Task, user_ids: list[int] | None) -> Task:
    """
    Replace the task's persisted assignee set. The first ID becomes the
    backward-compatible `assigned_to` primary assignee.
    """
    normalized = _normalize_user_ids(user_ids)
    _load_assignees(normalized)

    previous_user_ids = set(task.assigned_user_ids)

    try:
        task.set_assignees(normalized)
        db.session.commit()
    except (SQLAlchemyError, ValueError) as exc:
        db.session.rollback()
        raise OperationError(f"Failed to assign task: {exc}", status=422)

    db.session.refresh(task)
    _notify_new_assignees(task, previous_user_ids)
    return task


# ---------------------------------------------------------------------------
# Task lane transition
# ---------------------------------------------------------------------------
def transition_task(task: Task, new_state) -> Task:
    """
    Move a task across the linear state machine. The ORM-level validator
    enforces the assignment/active-sprint gatekeepers; we translate any
    ValueError into a clean OperationError after rolling back.
    """
    try:
        target = _coerce_task_state(new_state)
    except ValueError as exc:
        raise OperationError(str(exc), status=400)

    try:
        task.state = target          # triggers @validates gatekeeper
        db.session.commit()
    except ValueError as exc:        # gatekeeper rejection
        db.session.rollback()
        raise OperationError(str(exc), status=409)
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise OperationError(f"Failed to transition task: {exc}", status=500)

    return task


# ---------------------------------------------------------------------------
# Roadblock flagging (Trigger 2 on Blocked)
# ---------------------------------------------------------------------------
def set_task_block(task: Task, blocked: bool, reason: str | None = None) -> Task:
    """
    Flag/unflag a task as blocked. When raising a block, escalate immediately
    to the project owner. Roadblock propagation to the project view is handled
    declaratively via `Project.has_blocked_tasks`.
    """
    try:
        task.is_blocked = bool(blocked)
        task.blocked_reason = reason if blocked else None
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise OperationError(f"Failed to update block state: {exc}", status=500)

    if blocked:
        db.session.refresh(task)
        detail = reason or "No reason supplied"
        mail_service.send_escalation_alert(
            task, reason=f"Task flagged BLOCKED — {detail}"
        )

    return task


# ---------------------------------------------------------------------------
# Stakeholder dependency interlocking
# ---------------------------------------------------------------------------
def link_task_stakeholder(task: Task, stakeholder_id: int | None) -> Task:
    """Map (or unmap) a task onto an external stakeholder dependency."""
    if stakeholder_id is not None:
        stakeholder = db.session.get(Stakeholder, stakeholder_id)
        if stakeholder is None:
            raise OperationError(
                f"Stakeholder {stakeholder_id} does not exist.", status=404
            )
        if stakeholder.project_id != task.sprint.project_id:
            raise OperationError(
                "Stakeholder belongs to a different project scope.", status=409
            )

    try:
        task.stakeholder_id = stakeholder_id
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise OperationError(f"Failed to link stakeholder: {exc}", status=500)

    return task

"""
app/services/ops_service.py
===========================
Transactional business-logic layer sitting between the HTTP routes and the
ORM. Every mutating operation is wrapped so that any write anomaly triggers a
clean `db.session.rollback()`, and every side-effecting communication trigger
is fired only *after* the database write has been validated.

Public surface
--------------
    activate_sprint(sprint)               -> strict single-active concurrency
    assign_task(task, user_id)            -> mutate assignee + async notify
    transition_task(task, new_state)      -> guarded kanban lane change
    set_task_block(task, blocked, reason) -> roadblock flag + escalation
    link_task_stakeholder(task, sid)      -> dependency interlocking
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import (
    Sprint,
    Task,
    User,
    Stakeholder,
    TaskState,
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
# Sprint concurrency engine
# ---------------------------------------------------------------------------
def activate_sprint(sprint: Sprint) -> Sprint:
    """
    Strict Concurrency Guard.

    Activates `sprint` and, within the SAME transaction, deactivates every
    other sprint in the parent project scope so that exactly one sprint is
    ever active. Rolls back atomically on any failure.
    """
    try:
        # Deactivate all sibling sprints in this project scope.
        Sprint.query.filter(
            Sprint.project_id == sprint.project_id,
            Sprint.id != sprint.id,
            Sprint.is_active.is_(True),
        ).update({Sprint.is_active: False}, synchronize_session="fetch")

        sprint.is_active = True
        db.session.commit()
        return sprint
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise OperationError(f"Failed to activate sprint: {exc}", status=500)


def deactivate_sprint(sprint: Sprint) -> Sprint:
    """Deactivate a single sprint transactionally."""
    try:
        sprint.is_active = False
        db.session.commit()
        return sprint
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise OperationError(f"Failed to deactivate sprint: {exc}", status=500)


# ---------------------------------------------------------------------------
# Task assignment (Trigger 1)
# ---------------------------------------------------------------------------
def assign_task(task: Task, user_id: int | None) -> Task:
    """
    Mutate `task.assigned_to`. When the value changes to a real user, dispatch
    the asynchronous assignment notification AFTER a successful commit.
    """
    previous = task.assigned_to
    assignee = None

    if user_id is not None:
        assignee = db.session.get(User, user_id)
        if assignee is None:
            raise OperationError(f"User {user_id} does not exist.", status=404)

    try:
        task.assigned_to = user_id
        db.session.commit()
    except (SQLAlchemyError, ValueError) as exc:
        db.session.rollback()
        raise OperationError(f"Failed to assign task: {exc}", status=422)

    # Side-effect only on a genuine new assignment.
    if user_id is not None and user_id != previous and assignee is not None:
        db.session.refresh(task)
        mail_service.send_assignment_notification(task, assignee)

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

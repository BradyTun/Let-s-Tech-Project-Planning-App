"""
app/services/mail_service.py
============================
Fully decoupled, non-blocking SMTP dispatcher.

The primary WSGI request thread must NEVER block on an SMTP handshake. Every
message is therefore serialized into a Flask-Mail `Message`, captured along
with the *real* application object (`current_app._get_current_object()`), and
handed to a freshly spawned `threading.Thread`. The worker thread pushes its
own application context so Flask-Mail can resolve configuration safely in
complete isolation from the request that triggered it.

Two operational triggers are exposed:

    * send_assignment_notification  -> routed to the newly-assigned member.
    * send_escalation_alert         -> blasted to the Project Owner / Scrum
                                       Master when a task is blocked or moves
                                       into 'In Review' for executive sign-off.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import threading
from typing import Iterable

from flask import current_app, render_template
from flask_mail import Message

from ..extensions import mail


# ---------------------------------------------------------------------------
# Low-level threaded transport
# ---------------------------------------------------------------------------
def _transport(app, message: Message) -> None:
    """Hand the message to the active transport (Resend by default)."""
    if app.config.get("USE_SMTP"):
        mail.send(message)
    else:
        _send_with_resend(app, message)


def _deliver(app, message: Message) -> None:
    """Worker body: executed inside an isolated application context."""
    with app.app_context():
        try:
            _transport(app, message)
        except Exception as exc:  # pragma: no cover - transport failures
            # Never raise from a daemon thread; surface through the app logger.
            app.logger.error("Asynchronous mail delivery failed: %s", exc)


def _send_with_resend(app, message: Message) -> None:
    api_key = app.config.get("RESEND_KEY")
    if not api_key:
        raise RuntimeError("RESEND_KEY is not configured.")

    payload = {
        "from": message.sender or app.config.get("MAIL_DEFAULT_SENDER"),
        "to": list(message.recipients),
        "subject": message.subject,
        "html": message.html or "",
    }
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "HackathonPlanning/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend request failed with HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Resend request failed: {exc.reason}") from exc


def send_async(message: Message) -> threading.Thread:
    """
    Dispatch `message` on a background thread bound to the live application
    object. Returns the thread handle (primarily for test synchronization).
    """
    # Capture the underlying application object — NOT the context-local proxy.
    app = current_app._get_current_object()

    # Honor the testing suppression flag without spinning up a thread.
    if app.config.get("MAIL_SUPPRESS_SEND"):
        return threading.Thread(target=lambda: None)

    worker = threading.Thread(
        target=_deliver, args=(app, message), daemon=True
    )
    worker.start()
    return worker


def send_sync(message: Message) -> bool:
    """Deliver a message inline within the current request lifecycle.

    Used for critical, login-path email (OTP) where a fire-and-forget daemon
    thread can be torn down before the transport call completes (e.g. on
    serverless platforms). Errors are logged and reported via the return value,
    never raised, so the auth flow keeps a uniform response.
    """
    app = current_app._get_current_object()
    if app.config.get("MAIL_SUPPRESS_SEND"):
        return True
    try:
        _transport(app, message)
        return True
    except Exception as exc:  # pragma: no cover - transport failures
        app.logger.error("Synchronous mail delivery failed: %s", exc)
        return False


def _build_message(subject: str, recipients: Iterable[str], html: str) -> Message:
    clean_recipients = [r for r in recipients if r]
    if not clean_recipients:
        raise ValueError("Cannot dispatch mail with no valid recipients.")
    return Message(
        subject=subject,
        recipients=clean_recipients,
        html=html,
        sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
    )


# ---------------------------------------------------------------------------
# Trigger 1 — Operational assignment notification
# ---------------------------------------------------------------------------
def send_assignment_notification(task, assignee) -> threading.Thread | None:
    """
    Notify a team member the moment they are routed to a task.

    `task` and `assignee` are ORM instances. The function reads only plain
    attributes so it is safe to call before/after the session commits.
    """
    if assignee is None or not getattr(assignee, "email", None):
        return None

    deadline = None
    if task.sprint is not None and task.sprint.end_date is not None:
        deadline = task.sprint.end_date.isoformat()

    html = render_template(
        "emails/assignment.html",
        assignee_name=getattr(assignee, "display_name", None) or assignee.full_name or assignee.email,
        task_title=task.title,
        task_description=task.description,
        sprint_name=task.sprint.name if task.sprint else "Unassigned Sprint",
        deadline=deadline or "To be scheduled",
        priority=task.priority,
    )
    subject = f"Operational Assignment: You have been routed to “{task.title}”"
    message = _build_message(subject, [assignee.email], html)
    return send_async(message)


# ---------------------------------------------------------------------------
# Trigger 2 — Critical escalation alert
# ---------------------------------------------------------------------------
def send_escalation_alert(task, reason: str) -> threading.Thread | None:
    """
    Blast an escalation to the Project Owner / Scrum Master.

    Fired when a task is flagged 'Blocked' or transitions into 'In Review'
    (logistics ready for executive sign-off). Recipients are de-duplicated
    across the project owner and any scrum-master accounts attached to the
    task's assignee chain.
    """
    project = None
    if task.sprint is not None:
        project = task.sprint.project

    recipients: set[str] = set()
    owner_name = "Operations Lead"
    if project is not None and project.owner is not None and project.owner.email:
        recipients.add(project.owner.email)
        owner_name = getattr(project.owner, "display_name", None) or project.owner.email

    if not recipients:
        # Nothing to escalate to; bail gracefully rather than raising.
        current_app.logger.warning(
            "Escalation requested for task %s but no owner email is configured.",
            task.id,
        )
        return None

    stakeholder_name = task.stakeholder.name if task.stakeholder else None

    html = render_template(
        "emails/escalation.html",
        owner_name=owner_name,
        task_title=task.title,
        task_state=task.state.value,
        reason=reason,
        sprint_name=task.sprint.name if task.sprint else "—",
        project_name=project.name if project else "—",
        stakeholder_name=stakeholder_name,
        assignee_name=(getattr(task.assignee, "display_name", None) if task.assignee else "Unassigned"),
    )
    subject = f"[ESCALATION] {reason} — Task “{task.title}”"
    message = _build_message(subject, list(recipients), html)
    return send_async(message)


# ---------------------------------------------------------------------------
# Auth — one-time passcode
# ---------------------------------------------------------------------------
def send_otp_email(user, code: str, ttl_minutes: int) -> threading.Thread | None:
    """Email a login passcode to a user."""
    if user is None or not getattr(user, "email", None):
        return None
    html = render_template(
        "emails/otp.html",
        name=getattr(user, "display_name", None) or user.email,
        code=code,
        ttl_minutes=ttl_minutes,
    )
    subject = f"Your Hackathon passcode: {code}"
    # OTP is on the unauthenticated login path; send inline so the transport
    # call always completes before the response returns.
    send_sync(_build_message(subject, [user.email], html))
    return None


# ---------------------------------------------------------------------------
# Auth — member invitation
# ---------------------------------------------------------------------------
def send_invitation_email(user, base_url: str) -> threading.Thread | None:
    """Email an invitation with a link to the login screen."""
    if user is None or not getattr(user, "email", None):
        return None
    login_url = (base_url or "").rstrip("/") + "/"
    html = render_template(
        "emails/invite.html",
        email=user.email,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        login_url=login_url,
    )
    subject = "You're invited to Hackathon"
    return send_async(_build_message(subject, [user.email], html))


# ---------------------------------------------------------------------------
# Community — industry partner invitation
# ---------------------------------------------------------------------------
def send_stakeholder_invite(user, base_url: str) -> threading.Thread | None:
    """Invite an industry partner; they sign in with just their email."""
    if user is None or not getattr(user, "email", None):
        return None
    login_url = (base_url or "").rstrip("/") + "/"
    html = render_template(
        "emails/stakeholder_invite.html",
        name=getattr(user, "display_name", None) or user.email,
        login_url=login_url,
    )
    subject = "You're invited as an Industry Partner"
    return send_async(_build_message(subject, [user.email], html))


# ---------------------------------------------------------------------------
# Community — participant application lifecycle
# ---------------------------------------------------------------------------
def send_participant_welcome(user, base_url: str) -> threading.Thread | None:
    """Confirm a participant application and point them at passcode sign-in."""
    if user is None or not getattr(user, "email", None):
        return None
    login_url = (base_url or "").rstrip("/") + "/"
    html = render_template(
        "emails/participant_welcome.html",
        name=getattr(user, "display_name", None) or user.email,
        login_url=login_url,
    )
    subject = "Application received — Hackathon"
    return send_async(_build_message(subject, [user.email], html))


def send_selection_update(profile) -> threading.Thread | None:
    """Notify a participant when their selection decision changes."""
    user = getattr(profile, "user", None)
    if user is None or not getattr(user, "email", None):
        return None
    status = profile.selection_status
    status_label = status.value if hasattr(status, "value") else str(status)
    html = render_template(
        "emails/selection_update.html",
        name=getattr(user, "display_name", None) or user.email,
        status_label=status_label,
        status_key=status.name if hasattr(status, "name") else str(status),
        base_url=current_app.config.get("APP_BASE_URL", ""),
    )
    subject = f"Hackathon application update: {status_label}"
    return send_async(_build_message(subject, [user.email], html))

"""
app/services/auth_service.py
============================
Email one-time-passcode (OTP) authentication and admin-driven member
provisioning. Pure business logic — HTTP concerns live in the auth blueprint.

Flow
----
    request_otp(email)  -> mint a 6-digit code, email it, return dev echo.
    verify_otp(email,c) -> validate code, mark login, report onboarding need.
    set_username(user)  -> complete onboarding for first-time members.
    invite_member(...)  -> admin creates an invited user + invitation email.
    ensure_root_admin() -> idempotently guarantee the seeded admin exists.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import (
    User,
    OTPToken,
    UserRole,
    UserStatus,
    coerce_user_role,
    _utcnow,
)
from . import mail_service


class AuthError(Exception):
    """Raised when an authentication rule is violated."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _generate_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def get_user_by_email(email: str) -> User | None:
    if not email:
        return None
    return User.query.filter(User.email == email.strip().lower()).first()


# ---------------------------------------------------------------------------
# OTP request
# ---------------------------------------------------------------------------
def request_otp(email: str) -> dict:
    """
    Mint and dispatch an OTP for an existing (invited or active) user.

    Returns a dict describing the outcome. To avoid leaking which addresses
    are registered, callers should present a uniform "code sent" message
    regardless of whether the user existed.
    """
    user = get_user_by_email(email)
    if user is None:
        return {"sent": False, "reason": "unknown_email"}
    if user.status == UserStatus.DISABLED:
        return {"sent": False, "reason": "disabled"}

    length = current_app.config.get("OTP_LENGTH", 6)
    ttl = current_app.config.get("OTP_TTL_MINUTES", 10)
    code = _generate_code(length)

    try:
        # Invalidate any prior unconsumed codes for this user.
        OTPToken.query.filter(
            OTPToken.user_id == user.id, OTPToken.consumed.is_(False)
        ).update({OTPToken.consumed: True}, synchronize_session="fetch")

        token = OTPToken(
            user_id=user.id,
            expires_at=_utcnow() + timedelta(minutes=ttl),
        )
        token.set_code(code)
        db.session.add(token)
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise AuthError(f"Could not issue a passcode: {exc}", status=500)

    # Dispatch asynchronously; failures are logged, never raised to the request.
    mail_service.send_otp_email(user, code, ttl)

    current_app.logger.info("OTP for %s: %s (expires in %s min)", user.email, code, ttl)

    result = {"sent": True}
    if current_app.config.get("OTP_DEV_ECHO"):
        result["dev_code"] = code  # convenience when no live SMTP is configured
    return result


# ---------------------------------------------------------------------------
# OTP verify
# ---------------------------------------------------------------------------
def verify_otp(email: str, code: str) -> User:
    """Validate a submitted OTP and return the authenticated user."""
    if not code or not str(code).strip():
        raise AuthError("Enter the passcode from your email.", status=400)
    code = str(code).strip()

    user = get_user_by_email(email)
    if user is None:
        raise AuthError("Invalid email or passcode.", status=401)
    if user.status == UserStatus.DISABLED:
        raise AuthError("This account has been disabled.", status=403)

    token = (
        OTPToken.query.filter(OTPToken.user_id == user.id, OTPToken.consumed.is_(False))
        .order_by(OTPToken.created_at.desc())
        .first()
    )
    if token is None:
        raise AuthError("No active passcode. Request a new one.", status=401)
    if token.is_expired:
        raise AuthError("Passcode expired. Request a new one.", status=401)

    max_attempts = current_app.config.get("OTP_MAX_ATTEMPTS", 5)
    if token.attempts >= max_attempts:
        token.consumed = True
        db.session.commit()
        raise AuthError("Too many attempts. Request a new passcode.", status=429)

    if not token.verify_code(code):
        token.attempts += 1
        db.session.commit()
        raise AuthError("Invalid passcode.", status=401)

    # Success — consume token, stamp login.
    try:
        token.consumed = True
        user.last_login_at = _utcnow()
        if user.status == UserStatus.INVITED and user.username:
            user.status = UserStatus.ACTIVE
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise AuthError(f"Login could not be completed: {exc}", status=500)

    return user


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------
def set_username(user: User, username: str) -> User:
    """Complete onboarding by assigning a username and activating the account."""
    if not username or not username.strip():
        raise AuthError("A username is required.", status=400)
    try:
        user.username = username.strip()
        user.status = UserStatus.ACTIVE
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        raise AuthError(str(exc), status=422)
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise AuthError(f"Could not save username: {exc}", status=500)
    return user


# ---------------------------------------------------------------------------
# Admin: member provisioning
# ---------------------------------------------------------------------------
def invite_member(email: str, role: str = "member", username: str | None = None,
                  is_scrum_master: bool = False) -> User:
    """Admin action: create an invited user and send the invitation email."""
    if not email or "@" not in email:
        raise AuthError("A valid email address is required.", status=400)
    if get_user_by_email(email) is not None:
        raise AuthError("A user with that email already exists.", status=409)

    role_enum = coerce_user_role(role) if role else UserRole.MEMBER

    try:
        user = User(
            email=email,
            username=(username.strip() if username else None),
            role=role_enum,
            status=UserStatus.INVITED,
            is_scrum_master=bool(is_scrum_master),
        )
        db.session.add(user)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        raise AuthError(str(exc), status=422)
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise AuthError(f"Could not invite member: {exc}", status=500)

    base_url = current_app.config.get("APP_BASE_URL", "")
    mail_service.send_invitation_email(user, base_url)
    return user


def update_member(user: User, *, role=None, status=None, username=None,
                  is_scrum_master=None) -> User:
    try:
        if role is not None:
            user.role = coerce_user_role(role)
        if status is not None and isinstance(status, UserStatus):
            user.status = status
        if username is not None:
            user.username = username
        if is_scrum_master is not None:
            user.is_scrum_master = bool(is_scrum_master)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        raise AuthError(str(exc), status=422)
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise AuthError(f"Could not update member: {exc}", status=500)
    return user


def remove_member(user: User) -> None:
    try:
        db.session.delete(user)
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        raise AuthError(f"Could not remove member: {exc}", status=500)


# ---------------------------------------------------------------------------
# Root admin guarantee
# ---------------------------------------------------------------------------
def ensure_root_admin() -> User:
    """Idempotently make sure the configured root admin exists and is admin."""
    email = current_app.config.get("ROOT_ADMIN_EMAIL")
    if not email:
        raise AuthError("ROOT_ADMIN_EMAIL is not configured.", status=500)

    user = get_user_by_email(email)
    if user is None:
        user = User(
            email=email,
            username="Admin",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
            is_scrum_master=True,
        )
        db.session.add(user)
    else:
        user.role = UserRole.ADMIN
        if user.status == UserStatus.DISABLED:
            user.status = UserStatus.ACTIVE
        if not user.username:
            user.username = "Admin"
    db.session.commit()
    return user

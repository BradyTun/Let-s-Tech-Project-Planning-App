"""
app/auth.py
===========
Authentication blueprint: email-OTP login, onboarding, logout, and the
session-backed current-user machinery (loader + route decorators).

Session model: a signed cookie stores `user_id`. `g.current_user` is populated
once per request. API decorators return JSON 401/403; the dashboard route uses
`current_user()` directly to decide between the login screen and the app.
"""

from __future__ import annotations

from functools import wraps

from flask import (
    Blueprint, jsonify, request, session, g, current_app,
)

from .extensions import db
from .models import User, UserStatus
from .services import auth_service
from .services.auth_service import AuthError

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ---------------------------------------------------------------------------
# Current-user plumbing
# ---------------------------------------------------------------------------
def current_user() -> User | None:
    if "current_user" in g:
        return g.current_user
    user = None
    uid = session.get("user_id")
    if uid is not None:
        user = db.session.get(User, uid)
        if user is None or user.status == UserStatus.DISABLED:
            session.pop("user_id", None)
            user = None
    g.current_user = user
    return user


@auth_bp.app_context_processor
def _inject_user():
    return {"current_user": current_user()}


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return jsonify(ok=False, error="unauthorized",
                           message="Authentication required."), 401
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify(ok=False, error="unauthorized",
                           message="Authentication required."), 401
        if not user.is_admin:
            return jsonify(ok=False, error="forbidden",
                           message="Administrator access required."), 403
        return fn(*args, **kwargs)
    return wrapper


def _role_guard(predicate, message):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                return jsonify(ok=False, error="unauthorized",
                               message="Authentication required."), 401
            if not predicate(user):
                return jsonify(ok=False, error="forbidden", message=message), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


staff_required = _role_guard(
    lambda u: u.is_staff, "Organizer access required."
)
stakeholder_required = _role_guard(
    lambda u: u.is_stakeholder, "Industry-partner access required."
)
participant_required = _role_guard(
    lambda u: u.is_participant, "Participant access required."
)


def _login(user: User) -> None:
    session.clear()
    session["user_id"] = user.id
    session.permanent = True
    g.current_user = user


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------
@auth_bp.errorhandler(AuthError)
def _handle_auth_error(err: AuthError):
    return jsonify(ok=False, error="auth_error", message=err.message), err.status


def _json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise AuthError("Request body must be a JSON object.", status=400)
    return data


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@auth_bp.route("/start", methods=["POST"])
def start():
    """Unified sign-in entry point.

    Resolves how an email authenticates: industry partners are logged in
    immediately (email-only), everyone else is sent a one-time passcode.
    """
    data = _json()
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise AuthError("Enter a valid email address.", status=400)

    method, user = auth_service.resolve_login_method(email)

    if method == "unknown":
        response = jsonify(
            ok=False,
            error="unknown_email",
            message="No account for this email. New participants can register.",
            can_register=True,
        )
        response.status_code = 404
        return response
    if method == "disabled":
        raise AuthError("This account has been disabled.", status=403)
    if method == "stakeholder":
        # Industry partners sign in with just their email (no passcode).
        from .services.auth_service import _utcnow  # local import to avoid cycle noise
        user.last_login_at = _utcnow()
        db.session.commit()
        _login(user)
        return jsonify(ok=True, method="stakeholder", authenticated=True,
                       user=user.to_dict())

    # Staff + participants: passcode flow.
    return _issue_otp(email)


def _issue_otp(email: str):
    result = auth_service.request_otp(email)
    if result.get("reason") == "unknown_email":
        raise AuthError("There is no account for this email.", status=404)
    if result.get("reason") == "rate_limited":
        retry_after = int(result.get("retry_after") or 60)
        response = jsonify(
            ok=False,
            error="rate_limited",
            message=f"Please wait {retry_after}s before requesting another passcode.",
            retry_after=retry_after,
        )
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
    payload = {"ok": True, "method": "otp",
               "message": "A passcode is on its way to your email."}
    if result.get("dev_code"):
        payload["dev_code"] = result["dev_code"]
    return jsonify(payload)


@auth_bp.route("/register-participant", methods=["POST"])
def register_participant():
    """Public participant signup. Creates an account; login is via passcode."""
    if current_user() is not None:
        raise AuthError("You're already signed in.", status=409)
    data = _json()
    user = auth_service.register_participant(data)
    return jsonify(
        ok=True,
        message="Application received. Sign in with a passcode to continue.",
        email=user.email,
    ), 201


@auth_bp.route("/request-otp", methods=["POST"])
def request_otp():
    data = _json()
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise AuthError("Enter a valid email address.", status=400)
    return _issue_otp(email)


@auth_bp.route("/verify-otp", methods=["POST"])
def verify_otp():
    data = _json()
    email = (data.get("email") or "").strip().lower()
    code = data.get("code")
    user = auth_service.verify_otp(email, code)
    _login(user)
    return jsonify(
        ok=True,
        needs_onboarding=user.needs_onboarding,
        user=user.to_dict(),
    )


@auth_bp.route("/set-username", methods=["POST"])
def set_username():
    user = current_user()
    if user is None:
        raise AuthError("Authentication required.", status=401)
    data = _json()
    auth_service.set_username(user, data.get("username", ""))
    return jsonify(ok=True, user=user.to_dict())


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    g.pop("current_user", None)
    return jsonify(ok=True)


@auth_bp.route("/me", methods=["GET"])
def me():
    user = current_user()
    if user is None:
        return jsonify(ok=True, authenticated=False)
    return jsonify(ok=True, authenticated=True,
                   needs_onboarding=user.needs_onboarding, user=user.to_dict())

"""
app/api/auth.py
===============
Token-based authentication endpoints for the external REST API.

Flow (mirrors the first-party app, but returns bearer tokens instead of
setting a cookie session):

    POST /api/v1/auth/login     -> stakeholder: token; others: passcode sent
    POST /api/v1/auth/verify    -> exchange email + passcode for a token
    POST /api/v1/auth/register  -> public participant signup
    POST /api/v1/auth/onboarding-> set username on first login
    GET  /api/v1/auth/me        -> current token holder
    POST /api/v1/auth/logout    -> stateless acknowledgement
"""

from __future__ import annotations

from ..services import auth_service
from ..services.auth_service import _utcnow
from ..extensions import db
from . import (
    api_v1_bp, ApiError, public, issue_token, ok, body, current_api_user,
    api_login_required,
)


@api_v1_bp.route("/auth/login", methods=["POST"])
@public
def auth_login():
    """Resolve sign-in: partners get a token directly; others a passcode."""
    data = body("email")
    email = (data.get("email") or "").strip().lower()
    if "@" not in email:
        raise ApiError("Enter a valid email address.", 400)

    method, user = auth_service.resolve_login_method(email)
    if method == "unknown":
        raise ApiError("No account for this email. New participants can register.",
                       404, "unknown_email")
    if method == "disabled":
        raise ApiError("This account has been disabled.", 403, "forbidden")
    if method == "stakeholder":
        user.last_login_at = _utcnow()
        db.session.commit()
        return ok({"method": "token", **issue_token(user), "user": user.to_dict()})

    # Staff + participants: dispatch a one-time passcode.
    result = auth_service.request_otp(email)
    if result.get("reason") == "rate_limited":
        retry = int(result.get("retry_after") or 60)
        raise ApiError(f"Please wait {retry}s before requesting another passcode.",
                       429, "rate_limited")
    payload = {"method": "otp", "message": "A passcode is on its way to your email."}
    if result.get("dev_code"):
        payload["dev_code"] = result["dev_code"]
    return ok(payload)


@api_v1_bp.route("/auth/request-otp", methods=["POST"])
@public
def auth_request_otp():
    """Re-send a passcode for staff/participant accounts."""
    data = body("email")
    email = (data.get("email") or "").strip().lower()
    if "@" not in email:
        raise ApiError("Enter a valid email address.", 400)
    result = auth_service.request_otp(email)
    if result.get("reason") == "unknown_email":
        raise ApiError("There is no account for this email.", 404, "unknown_email")
    if result.get("reason") == "rate_limited":
        retry = int(result.get("retry_after") or 60)
        raise ApiError(f"Please wait {retry}s before requesting another passcode.",
                       429, "rate_limited")
    payload = {"message": "A passcode is on its way to your email."}
    if result.get("dev_code"):
        payload["dev_code"] = result["dev_code"]
    return ok(payload)


@api_v1_bp.route("/auth/verify", methods=["POST"])
@public
def auth_verify():
    """Exchange an email + passcode for a bearer token."""
    data = body("email", "code")
    email = (data.get("email") or "").strip().lower()
    user = auth_service.verify_otp(email, data.get("code"))
    return ok({
        **issue_token(user),
        "user": user.to_dict(),
        "needs_onboarding": user.needs_onboarding,
    })


@api_v1_bp.route("/auth/register", methods=["POST"])
@public
def auth_register():
    """Public participant self-registration."""
    data = body("email", "full_name")
    user = auth_service.register_participant(data)
    return ok({
        "message": "Application received. Verify a passcode to sign in.",
        "email": user.email,
    }, status=201)


@api_v1_bp.route("/auth/onboarding", methods=["POST"])
@api_login_required
def auth_onboarding():
    """Complete first-login onboarding by choosing a username."""
    user = current_api_user()
    data = body("username")
    auth_service.set_username(user, data.get("username", ""))
    return ok({"user": user.to_dict()})


@api_v1_bp.route("/auth/me", methods=["GET"])
@api_login_required
def auth_me():
    return ok({"user": current_api_user().to_dict()})


@api_v1_bp.route("/auth/logout", methods=["POST"])
@api_login_required
def auth_logout():
    """Stateless logout: the client simply discards its token."""
    return ok({"message": "Token discarded client-side."})

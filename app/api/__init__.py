"""
app/api/__init__.py
===================
Versioned, token-authenticated REST API (``/api/v1``) intended for external,
front-facing applications.

Design
------
* **Stateless bearer tokens.** Clients authenticate once (passcode or partner
  email) and receive a signed token (``itsdangerous``) that carries the user id
  and an expiry. No server-side session/cookie is used, so the API works
  cleanly from any cross-origin SPA or mobile app.
* **Reuses the existing domain layer.** Every endpoint delegates to the same
  models and service functions that power the first-party UI, so behaviour and
  business rules stay identical and never drift.
* **Self-documenting.** An OpenAPI 3 document is generated at
  ``/api/v1/openapi.json`` and rendered with Swagger UI at ``/api/v1/docs``.

The blueprint owns its own authentication (`g.api_user`), CORS handling, and
JSON error envelopes; it does not depend on the cookie-session machinery used
by the browser UI.
"""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..extensions import db
from ..models import User, UserStatus
from ..services.auth_service import AuthError
from ..services.ops_service import OperationError
from ..services.community_service import CommunityError

api_v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

_TOKEN_SALT = "hackathon-api-v1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    """Uniform API failure carrying an HTTP status + machine code."""

    def __init__(self, message: str, status: int = 400, code: str = "api_error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_TOKEN_SALT)


def issue_token(user: User) -> dict:
    """Mint a signed bearer token for ``user`` and describe its lifetime."""
    ttl = int(current_app.config.get("API_TOKEN_TTL_SECONDS", 7 * 24 * 3600))
    token = _serializer().dumps({"uid": user.id})
    return {"access_token": token, "token_type": "Bearer", "expires_in": ttl}


def _user_from_token(token: str | None) -> User | None:
    if not token:
        return None
    ttl = int(current_app.config.get("API_TOKEN_TTL_SECONDS", 7 * 24 * 3600))
    try:
        data = _serializer().loads(token, max_age=ttl)
    except (BadSignature, SignatureExpired, Exception):  # noqa: BLE001 - any decode failure => anonymous
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    if uid is None:
        return None
    return db.session.get(User, uid)


def _bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header[:7].lower() == "bearer ":
        return header[7:].strip()
    # Convenience fallback header for tooling that cannot set Authorization.
    return request.headers.get("X-API-Token") or None


def current_api_user() -> User | None:
    return g.get("api_user")


# ---------------------------------------------------------------------------
# Public-route marker + auth/role guards
# ---------------------------------------------------------------------------
def public(fn):
    """Mark a view as unauthenticated (login, registration, docs, health)."""
    fn._api_public = True
    return fn


def _require_user() -> User:
    user = current_api_user()
    if user is None:
        raise ApiError("Authentication required. Provide a valid Bearer token.",
                       401, "unauthorized")
    return user


def api_login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        _require_user()
        return fn(*args, **kwargs)
    return wrapper


def _role_guard(predicate, message):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = _require_user()
            if not predicate(user):
                raise ApiError(message, 403, "forbidden")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


api_admin_required = _role_guard(lambda u: u.is_admin, "Administrator access required.")
api_staff_required = _role_guard(lambda u: u.is_staff, "Organizer access required.")
api_stakeholder_required = _role_guard(lambda u: u.is_stakeholder, "Stakeholder access required.")
api_participant_required = _role_guard(lambda u: u.is_participant, "Participant access required.")


# ---------------------------------------------------------------------------
# Request/response plumbing
# ---------------------------------------------------------------------------
def body(*required: str) -> dict:
    """Return the JSON object body, validating that required keys are present."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object.", 400)
    missing = [k for k in required if data.get(k) in (None, "")]
    if missing:
        raise ApiError(f"Missing required field(s): {', '.join(missing)}", 400)
    return data


def get_or_404(model, ident, label: str):
    obj = db.session.get(model, ident)
    if obj is None:
        raise ApiError(f"{label} {ident} not found.", 404, "not_found")
    return obj


def ok(payload: dict | None = None, status: int = 200):
    data = {"ok": True}
    if payload:
        data.update(payload)
    return jsonify(data), status


# ---------------------------------------------------------------------------
# Lifecycle: authenticate, CORS, error envelopes
# ---------------------------------------------------------------------------
@api_v1_bp.before_request
def _authenticate():
    if request.method == "OPTIONS":
        # CORS preflight — answered here; headers added in after_request.
        return ("", 204)

    g.api_user = None
    view = current_app.view_functions.get(request.endpoint)
    if getattr(view, "_api_public", False):
        return None

    user = _user_from_token(_bearer_token())
    if user is None:
        raise ApiError("Authentication required. Provide a valid Bearer token.",
                       401, "unauthorized")
    if user.status == UserStatus.DISABLED:
        raise ApiError("This account has been disabled.", 403, "forbidden")
    g.api_user = user
    return None


@api_v1_bp.after_request
def _cors(response):
    origin = current_app.config.get("API_CORS_ORIGINS", "*")
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


@api_v1_bp.errorhandler(ApiError)
def _handle_api_error(err: ApiError):
    return jsonify(ok=False, error=err.code, message=err.message), err.status


@api_v1_bp.errorhandler(AuthError)
def _handle_auth_error(err: AuthError):
    return jsonify(ok=False, error="auth_error", message=err.message), err.status


@api_v1_bp.errorhandler(OperationError)
def _handle_operation_error(err: OperationError):
    return jsonify(ok=False, error="operation_error", message=err.message), err.status


@api_v1_bp.errorhandler(CommunityError)
def _handle_community_error(err: CommunityError):
    return jsonify(ok=False, error="community_error", message=err.message), err.status


@api_v1_bp.errorhandler(404)
def _handle_404(_err):
    return jsonify(ok=False, error="not_found", message="Resource not found."), 404


@api_v1_bp.errorhandler(405)
def _handle_405(_err):
    return jsonify(ok=False, error="method_not_allowed", message="Method not allowed."), 405


# Attach routes (imported for their side effects).
from . import auth as _auth  # noqa: E402,F401
from . import resources as _resources  # noqa: E402,F401
from . import docs as _docs  # noqa: E402,F401

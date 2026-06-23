"""
app/api/openapi.py
==================
Generates the OpenAPI 3.0 document for the ``/api/v1`` surface.

Rather than hand-maintaining a parallel list of paths, the spec is built by
introspecting the Flask URL map for the ``api_v1`` blueprint. Every route is
therefore documented automatically — new endpoints appear in Swagger UI the
moment they are registered. Curated metadata (`_META`) layers human-friendly
summaries, tags, and request-body examples on top of the introspected routes.
"""

from __future__ import annotations

import re

from flask import current_app, request

# Routes that power the docs themselves are not part of the documented surface.
_INTERNAL_ENDPOINTS = {"api_v1.openapi_json", "api_v1.swagger_ui", "api_v1.api_index"}

_PATH_PARAM = re.compile(r"<(?:[^:<>]+:)?([^<>]+)>")


# ---------------------------------------------------------------------------
# Curated per-endpoint metadata: tag, summary, and optional request example.
# ---------------------------------------------------------------------------
def _b(example: dict, required: list[str] | None = None) -> dict:
    """Shorthand for a JSON request body described by an example object."""
    schema = {"type": "object", "example": example}
    if required:
        schema["required"] = required
    return schema


_META: dict[str, dict] = {
    # --- Authentication ----------------------------------------------------
    "auth_login": {
        "tag": "Authentication",
        "summary": "Start sign-in (returns a token for stakeholders, else sends a passcode)",
        "body": _b({"email": "partner@acme.com"}, ["email"]),
    },
    "auth_request_otp": {
        "tag": "Authentication",
        "summary": "Re-send a one-time passcode to staff/participant accounts",
        "body": _b({"email": "organizer@event.com"}, ["email"]),
    },
    "auth_verify": {
        "tag": "Authentication",
        "summary": "Exchange an email + passcode for a bearer token",
        "body": _b({"email": "organizer@event.com", "code": "123456"}, ["email", "code"]),
    },
    "auth_register": {
        "tag": "Authentication",
        "summary": "Public participant self-registration",
        "body": _b({
            "email": "hacker@school.edu", "full_name": "Ada Lovelace",
            "phone": "+1 555 0100", "school_or_org": "State University",
            "skills": "Python, ML", "experience_level": "INTERMEDIATE",
            "industry_interest": "Healthcare",
        }, ["email", "full_name"]),
    },
    "auth_onboarding": {
        "tag": "Authentication",
        "summary": "Set a username on first sign-in",
        "body": _b({"username": "ada"}, ["username"]),
    },
    "auth_me": {"tag": "Authentication", "summary": "Current token holder"},
    "auth_logout": {"tag": "Authentication", "summary": "Discard the token (stateless)"},

    # --- Workspace ---------------------------------------------------------
    "health": {"tag": "Workspace", "summary": "Service + database health probe"},
    "meta": {"tag": "Workspace", "summary": "Reference data: every enum, industry list, and caps"},
    "bootstrap": {"tag": "Workspace", "summary": "One-shot organizer snapshot (epics, users, docs)"},

    # --- Users -------------------------------------------------------------
    "list_users": {"tag": "Users", "summary": "List organizer team accounts"},
    "invite_user": {
        "tag": "Users", "summary": "Invite an organizer (admin/member)",
        "body": _b({"email": "new@event.com", "role": "member",
                    "username": "newmember", "is_scrum_master": False}, ["email"]),
    },
    "update_user": {
        "tag": "Users", "summary": "Update a user's role, status, or username",
        "body": _b({"role": "admin", "status": "ACTIVE", "is_scrum_master": True}),
    },
    "delete_user": {"tag": "Users", "summary": "Remove a user account"},

    # --- Epics -------------------------------------------------------------
    "list_projects": {"tag": "Epics", "summary": "List epics with sprints and tasks"},
    "create_project": {
        "tag": "Epics", "summary": "Create an epic",
        "body": _b({"name": "Spring Hackathon", "description": "Flagship event",
                    "owner_id": 1}, ["name"]),
    },
    "get_project": {"tag": "Epics", "summary": "Fetch a single epic with its children"},
    "update_project": {
        "tag": "Epics", "summary": "Update an epic",
        "body": _b({"name": "Renamed", "description": "...", "owner_id": 2}),
    },
    "delete_project": {"tag": "Epics", "summary": "Delete an epic"},

    # --- Sprints -----------------------------------------------------------
    "create_sprint": {
        "tag": "Sprints", "summary": "Add a sprint to an epic",
        "body": _b({"name": "Sprint 1", "goal": "Kickoff", "sequence": 0,
                    "start_date": "2025-03-01", "end_date": "2025-03-14"}, ["name"]),
    },
    "update_sprint": {
        "tag": "Sprints", "summary": "Update a sprint",
        "body": _b({"name": "Sprint 1", "goal": "Revised", "start_date": "2025-03-02"}),
    },
    "delete_sprint": {"tag": "Sprints", "summary": "Delete a sprint"},

    # --- Tasks -------------------------------------------------------------
    "create_task": {
        "tag": "Tasks", "summary": "Create a task in a sprint (supports multiple assignees)",
        "body": _b({"title": "Design landing page", "description": "Hero + CTA",
                    "priority": 1, "assigned_user_ids": [2, 3], "stakeholder_id": 5}, ["title"]),
    },
    "get_task": {"tag": "Tasks", "summary": "Fetch a single task"},
    "update_task": {
        "tag": "Tasks", "summary": "Update task title/description/priority",
        "body": _b({"title": "New title", "description": "...", "priority": 2}),
    },
    "delete_task": {"tag": "Tasks", "summary": "Delete a task"},
    "assign_task": {
        "tag": "Tasks", "summary": "Set task assignees (one or many)",
        "body": _b({"user_ids": [2, 3]}),
    },
    "transition_task": {
        "tag": "Tasks", "summary": "Move a task to a new workflow state",
        "body": _b({"state": "IN_PROGRESS"}, ["state"]),
    },
    "block_task": {
        "tag": "Tasks", "summary": "Block or unblock a task",
        "body": _b({"blocked": True, "reason": "Waiting on assets"}),
    },
    "link_task_stakeholder": {
        "tag": "Tasks", "summary": "Attach (or clear) the related stakeholder",
        "body": _b({"stakeholder_id": 5}),
    },

    # --- Stakeholders ------------------------------------------------------
    "create_stakeholder": {
        "tag": "Stakeholders", "summary": "Add a stakeholder to an epic",
        "body": _b({"name": "Acme Corp", "organization": "Acme",
                    "industry": "Fintech", "hackathon_status": "EXPLORING",
                    "about": "Payments leader", "website": "https://acme.com",
                    "status": "PENDING", "roles": ["IN_KIND_SPONSOR"],
                    "contact_email": "partner@acme.com", "contact_phone": "+1 555 0101",
                    "notes": "Intro via referral"}, ["name", "roles"]),
    },
    "update_stakeholder": {
        "tag": "Stakeholders", "summary": "Update a stakeholder",
        "body": _b({"organization": "Acme Inc", "status": "CONFIRMED",
                    "roles": ["CASH_SPONSOR", "MENTOR"]}),
    },
    "delete_stakeholder": {"tag": "Stakeholders", "summary": "Delete a stakeholder"},
    "tasks_by_stakeholder": {"tag": "Stakeholders", "summary": "List tasks linked to a stakeholder"},
    "invite_stakeholder_account": {
        "tag": "Stakeholders",
        "summary": "Enable portal login for a stakeholder (creates one if needed)",
        "body": _b({"email": "partner@acme.com", "project_id": 1,
                    "name": "Acme Corp", "organization": "Acme",
                    "industry": "Fintech", "roles": ["IN_KIND_SPONSOR"]}, ["email"]),
    },

    # --- Docs --------------------------------------------------------------
    "list_docs": {"tag": "Docs", "summary": "List knowledge-base docs"},
    "create_doc": {
        "tag": "Docs", "summary": "Create a doc",
        "body": _b({"title": "Run of show", "content": "# Agenda..."}, ["title"]),
    },
    "get_doc": {"tag": "Docs", "summary": "Fetch a doc"},
    "update_doc": {
        "tag": "Docs", "summary": "Update a doc",
        "body": _b({"title": "Run of show", "content": "Updated"}),
    },
    "delete_doc": {"tag": "Docs", "summary": "Delete a doc"},

    # --- Community ---------------------------------------------------------
    "community_overview": {
        "tag": "Community",
        "summary": "Full community snapshot (partners, participants, teams, requirements)",
    },
    "list_participants": {"tag": "Community", "summary": "List participant applications"},
    "update_participant": {
        "tag": "Community", "summary": "Advance a participant in the selection funnel",
        "body": _b({"selection_status": "SELECTED", "interview_notes": "Strong fit"}),
    },
    "list_teams": {"tag": "Community", "summary": "List participant teams"},

    # --- Requirements ------------------------------------------------------
    "list_requirements": {
        "tag": "Requirements", "summary": "Published industry problem statements (any user)",
    },

    # --- Portal: shared ----------------------------------------------------
    "portal_bootstrap": {
        "tag": "Portal", "summary": "Role-aware self-service snapshot (stakeholder or participant)",
    },
    # --- Portal: stakeholder ----------------------------------------------
    "portal_update_stakeholder_profile": {
        "tag": "Portal", "summary": "Stakeholder: update own profile",
        "body": _b({"organization": "Acme", "industry": "Fintech",
                    "about": "...", "website": "https://acme.com",
                    "contact_phone": "+1 555 0101", "hackathon_status": "COMMITTED"}),
    },
    "portal_create_requirement": {
        "tag": "Portal", "summary": "Stakeholder: publish a problem statement",
        "body": _b({"title": "Fraud detection", "industry": "Fintech",
                    "problem": "Reduce false positives", "desired_outcome": "Prototype",
                    "priority": 1, "status": "OPEN"}, ["title"]),
    },
    "portal_update_requirement": {
        "tag": "Portal", "summary": "Stakeholder: update a problem statement",
        "body": _b({"title": "Fraud detection v2", "status": "ADDRESSED"}),
    },
    "portal_delete_requirement": {"tag": "Portal", "summary": "Stakeholder: delete a problem statement"},
    # --- Portal: participant ----------------------------------------------
    "portal_update_participant_profile": {
        "tag": "Portal", "summary": "Participant: update own profile",
        "body": _b({"full_name": "Ada Lovelace", "phone": "+1 555 0100",
                    "school_or_org": "State University", "bio": "...",
                    "skills": "Python, ML", "experience_level": "INTERMEDIATE",
                    "industry_interest": "Healthcare"}),
    },
    "portal_create_team": {
        "tag": "Portal", "summary": "Participant: create a team (selected only)",
        "body": _b({"name": "Team Rocket", "pitch": "...", "target_requirement_id": 7}, ["name"]),
    },
    "portal_update_team": {
        "tag": "Portal", "summary": "Participant (lead): update the team",
        "body": _b({"name": "Team Rocket", "pitch": "Revised",
                    "target_requirement_id": 7, "status": "FORMING"}),
    },
    "portal_join_team": {
        "tag": "Portal", "summary": "Participant: join a team by code",
        "body": _b({"join_code": "AB12CD"}, ["join_code"]),
    },
    "portal_leave_team": {"tag": "Portal", "summary": "Participant: leave the current team"},
}

# Tag descriptions, in display order.
_TAGS = [
    {"name": "Authentication", "description": "Token issuance: passcode and partner sign-in."},
    {"name": "Workspace", "description": "Health, reference enums, and bootstrap snapshots."},
    {"name": "Users", "description": "Organizer team administration (admin only)."},
    {"name": "Epics", "description": "Top-level initiatives (a.k.a. projects)."},
    {"name": "Sprints", "description": "Time-boxed iterations inside an epic."},
    {"name": "Tasks", "description": "Work items, assignment, workflow, and blocking."},
    {"name": "Stakeholders", "description": "Partner matrix, roles, and task linking."},
    {"name": "Docs", "description": "Shared knowledge base."},
    {"name": "Community", "description": "Participants, teams, and the selection funnel."},
    {"name": "Requirements", "description": "Published industry problem statements."},
    {"name": "Portal", "description": "Self-service for stakeholders and participants."},
]


# ---------------------------------------------------------------------------
# Component schemas
# ---------------------------------------------------------------------------
def _schemas() -> dict:
    str_ = {"type": "string"}
    int_ = {"type": "integer"}
    bool_ = {"type": "boolean"}
    return {
        "Error": {
            "type": "object",
            "properties": {"ok": {"type": "boolean", "example": False},
                           "error": str_, "message": str_},
        },
        "AuthToken": {
            "type": "object",
            "properties": {
                "ok": bool_,
                "access_token": str_,
                "token_type": {"type": "string", "example": "Bearer"},
                "expires_in": {"type": "integer", "example": 604800},
                "user": {"$ref": "#/components/schemas/User"},
            },
        },
        "User": {
            "type": "object",
            "properties": {
                "id": int_, "email": str_, "username": str_, "display_name": str_,
                "role": str_, "status": str_, "is_scrum_master": bool_,
                "is_staff": bool_, "is_stakeholder": bool_, "is_participant": bool_,
            },
        },
        "Project": {
            "type": "object",
            "properties": {
                "id": int_, "name": str_, "description": str_, "owner_id": int_,
                "sprints": {"type": "array", "items": {"$ref": "#/components/schemas/Sprint"}},
                "stakeholders": {"type": "array",
                                 "items": {"$ref": "#/components/schemas/Stakeholder"}},
            },
        },
        "Sprint": {
            "type": "object",
            "properties": {
                "id": int_, "name": str_, "goal": str_, "sequence": int_,
                "start_date": str_, "end_date": str_, "project_id": int_,
                "tasks": {"type": "array", "items": {"$ref": "#/components/schemas/Task"}},
            },
        },
        "Task": {
            "type": "object",
            "properties": {
                "id": int_, "title": str_, "description": str_, "priority": int_,
                "state": str_, "blocked": bool_, "block_reason": str_,
                "sprint_id": int_, "assigned_to": int_,
                "assigned_user_ids": {"type": "array", "items": int_},
                "assignee": {"type": "object"},
                "assignees": {"type": "array", "items": {"type": "object"}},
                "stakeholder": {"type": "object"},
            },
        },
        "Stakeholder": {
            "type": "object",
            "properties": {
                "id": int_, "name": str_, "display_name": str_, "organization": str_,
                "industry": str_, "hackathon_status": str_, "hackathon_status_key": str_,
                "about": str_, "website": str_, "status": str_, "contact_email": str_,
                "contact_phone": str_, "notes": str_, "project_id": int_, "user_id": int_,
                "portal_enabled": bool_, "is_complete": bool_,
                "requirement_count": int_, "open_requirement_count": int_,
                "open_task_count": int_,
                "roles": {"type": "array", "items": str_},
                "role_keys": {"type": "array", "items": str_},
            },
        },
        "Doc": {
            "type": "object",
            "properties": {"id": int_, "title": str_, "content": str_,
                           "created_by": int_, "updated_at": str_},
        },
        "Requirement": {
            "type": "object",
            "properties": {
                "id": int_, "title": str_, "industry": str_, "problem": str_,
                "desired_outcome": str_, "priority": int_, "status": str_,
                "stakeholder_id": int_, "organization": str_, "stakeholder_name": str_,
            },
        },
        "ParticipantProfile": {
            "type": "object",
            "properties": {
                "id": int_, "user_id": int_, "full_name": str_, "phone": str_,
                "school_or_org": str_, "bio": str_, "skills": str_,
                "experience_level": str_, "industry_interest": str_,
                "selection_status": str_, "interview_notes": str_, "applied_at": str_,
            },
        },
        "Team": {
            "type": "object",
            "properties": {
                "id": int_, "name": str_, "pitch": str_, "status": str_,
                "join_code": str_, "lead_user_id": int_, "target_requirement_id": int_,
                "size": int_, "members": {"type": "array", "items": {"type": "object"}},
            },
        },
        "Ok": {
            "type": "object",
            "properties": {"ok": {"type": "boolean", "example": True}},
        },
    }


def _humanize(endpoint: str) -> str:
    return endpoint.replace("_", " ").capitalize()


def _error_responses() -> dict:
    err = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
    return {
        "400": {"description": "Validation error", **err},
        "401": {"description": "Authentication required", **err},
        "403": {"description": "Forbidden", **err},
        "404": {"description": "Not found", **err},
        "409": {"description": "Conflict", **err},
        "422": {"description": "Unprocessable", **err},
    }


def build_spec() -> dict:
    """Construct the OpenAPI 3.0.3 document from the live URL map."""
    paths: dict[str, dict] = {}
    common_errors = _error_responses()

    for rule in current_app.url_map.iter_rules():
        if not rule.endpoint.startswith("api_v1."):
            continue
        if rule.endpoint in _INTERNAL_ENDPOINTS:
            continue

        view = current_app.view_functions.get(rule.endpoint)
        is_public = bool(getattr(view, "_api_public", False))
        short = rule.endpoint.split(".", 1)[1]
        meta = _META.get(short, {})

        # Convert Flask path params to OpenAPI style and collect parameters.
        oas_path = _PATH_PARAM.sub(r"{\1}", rule.rule)
        parameters = []
        for arg in sorted(rule.arguments):
            is_int = f"<int:{arg}>" in rule.rule
            parameters.append({
                "name": arg, "in": "path", "required": True,
                "schema": {"type": "integer" if is_int else "string"},
            })

        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        for method in methods:
            operation = {
                "operationId": f"{short}_{method.lower()}",
                "tags": [meta.get("tag", "Workspace")],
                "summary": meta.get("summary", _humanize(short)),
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/Ok"}}},
                    },
                    **common_errors,
                },
            }
            if parameters:
                operation["parameters"] = parameters
            if is_public:
                operation["security"] = []  # override the global bearer requirement
            if method in ("POST", "PATCH", "PUT") and meta.get("body"):
                operation["requestBody"] = {
                    "required": True,
                    "content": {"application/json": {"schema": meta["body"]}},
                }
            paths.setdefault(oas_path, {})[method.lower()] = operation

    server_url = request.host_url.rstrip("/") + "/api/v1"
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Hackathon Management API",
            "version": "1.0.0",
            "description": (
                "External REST API exposing the full hackathon platform: epics, "
                "sprints, tasks, stakeholders, docs, the community funnel, and the "
                "stakeholder/participant portals.\n\n"
                "**Auth:** call `POST /auth/login`. Stakeholders receive a bearer "
                "token immediately; staff and participants receive a one-time "
                "passcode, then exchange it at `POST /auth/verify`. Send the token "
                "as `Authorization: Bearer <token>`."
            ),
        },
        "servers": [{"url": server_url}],
        "tags": _TAGS,
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT-like"},
            },
            "schemas": _schemas(),
        },
        "security": [{"bearerAuth": []}],
        "paths": paths,
    }

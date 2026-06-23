"""
app/portal.py
=============
Self-service portal API for the two external audiences:

    * Industry partners (stakeholders) — manage their profile and the problem
      statements they want participants to solve.
    * Participants — manage their application profile, browse industry
      problems, and form / join teams.

Every route is role-guarded. Organizer-only data never crosses into these
endpoints; the command-center API lives in ``routes.py`` behind a staff gate.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, current_app

from .extensions import db
from .models import (
    IndustryRequirement,
    ParticipantProfile,
    Team,
    SUGGESTED_INDUSTRIES,
    StakeholderHackathonStatus,
    RequirementStatus,
    ExperienceLevel,
    SelectionStatus,
    _VISIBLE_REQUIREMENT_STATES,
)
from .services import community_service
from .services.community_service import CommunityError
from .auth import (
    current_user, login_required, stakeholder_required, participant_required,
)

portal_bp = Blueprint("portal", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _payload() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise CommunityError("Request body must be a JSON object.", status=400)
    return data


@portal_bp.errorhandler(CommunityError)
def _handle_community_error(err: CommunityError):
    return jsonify(ok=False, error="community_error", message=err.message), err.status


def _enum_options(enum_cls) -> list[dict]:
    return [{"key": m.name, "label": m.value} for m in enum_cls]


def _meta() -> dict:
    return {
        "industries": SUGGESTED_INDUSTRIES,
        "hackathon_statuses": _enum_options(StakeholderHackathonStatus),
        "requirement_statuses": _enum_options(RequirementStatus),
        "experience_levels": _enum_options(ExperienceLevel),
        "selection_statuses": _enum_options(SelectionStatus),
    }


def _published_requirements() -> list[IndustryRequirement]:
    return (
        IndustryRequirement.query.filter(
            IndustryRequirement.status.in_(_VISIBLE_REQUIREMENT_STATES)
        )
        .order_by(IndustryRequirement.priority.asc(), IndustryRequirement.created_at.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# Bootstrap (role-aware snapshot for the portal SPA)
# ---------------------------------------------------------------------------
@portal_bp.route("/api/portal/bootstrap", methods=["GET"])
@login_required
def bootstrap():
    user = current_user()

    if user.is_stakeholder:
        profile = community_service.ensure_stakeholder_profile(user)
        req_ids = [r.id for r in profile.requirements]
        teams = community_service.teams_for_requirements(req_ids)
        return jsonify(
            ok=True,
            role="stakeholder",
            me=user.to_dict(),
            profile=profile.to_dict(include_requirements=True),
            interested_teams=[t.to_dict(include_members=False) for t in teams],
            meta=_meta(),
        )

    if user.is_participant:
        profile = community_service.ensure_participant_profile(user)
        team = user.team
        return jsonify(
            ok=True,
            role="participant",
            me=user.to_dict(),
            profile=profile.to_dict(),
            team=team.to_dict() if team else None,
            requirements=[r.to_dict() for r in _published_requirements()],
            selection_cap=community_service.selection_cap(),
            selected_count=community_service.selected_count(),
            max_team_size=int(current_app.config.get("MAX_TEAM_SIZE", 5)),
            meta=_meta(),
        )

    # Staff land in the Platform, not the portal.
    return jsonify(ok=False, error="forbidden",
                   message="This portal is for participants and partners."), 403


# ---------------------------------------------------------------------------
# Stakeholder — profile + problem statements
# ---------------------------------------------------------------------------
@portal_bp.route("/api/portal/stakeholder/profile", methods=["PATCH", "PUT"])
@stakeholder_required
def update_stakeholder_profile():
    user = current_user()
    profile = community_service.ensure_stakeholder_profile(user)
    community_service.update_stakeholder_profile(profile, _payload())
    return jsonify(ok=True, profile=profile.to_dict(include_requirements=True))


@portal_bp.route("/api/portal/stakeholder/requirements", methods=["POST"])
@stakeholder_required
def create_requirement():
    user = current_user()
    profile = community_service.ensure_stakeholder_profile(user)
    req = community_service.create_requirement(profile, _payload())
    return jsonify(ok=True, requirement=req.to_dict()), 201


def _owned_requirement(requirement_id: int) -> IndustryRequirement:
    user = current_user()
    req = db.session.get(IndustryRequirement, requirement_id)
    partner = req.stakeholder.stakeholder if req and req.stakeholder else None
    if req is None or req.stakeholder is None or partner is None or partner.user_id != user.id:
        raise CommunityError("Problem statement not found.", status=404)
    return req


@portal_bp.route("/api/portal/stakeholder/requirements/<int:requirement_id>",
                 methods=["PATCH", "PUT"])
@stakeholder_required
def update_requirement(requirement_id):
    req = _owned_requirement(requirement_id)
    community_service.update_requirement(req, _payload())
    return jsonify(ok=True, requirement=req.to_dict())


@portal_bp.route("/api/portal/stakeholder/requirements/<int:requirement_id>",
                 methods=["DELETE"])
@stakeholder_required
def delete_requirement(requirement_id):
    req = _owned_requirement(requirement_id)
    community_service.delete_requirement(req)
    return jsonify(ok=True, deleted=requirement_id)


# ---------------------------------------------------------------------------
# Participant — profile, problem catalog, teams
# ---------------------------------------------------------------------------
@portal_bp.route("/api/portal/participant/profile", methods=["PATCH", "PUT"])
@participant_required
def update_participant_profile():
    user = current_user()
    profile = community_service.ensure_participant_profile(user)
    community_service.update_participant_profile(profile, _payload())
    return jsonify(ok=True, profile=profile.to_dict())


@portal_bp.route("/api/portal/participant/team", methods=["POST"])
@participant_required
def create_team():
    team = community_service.create_team(current_user(), _payload())
    return jsonify(ok=True, team=team.to_dict()), 201


@portal_bp.route("/api/portal/participant/team", methods=["PATCH", "PUT"])
@participant_required
def update_team():
    user = current_user()
    team = user.team
    if team is None:
        raise CommunityError("You're not in a team yet.", status=400)
    community_service.update_team(user, team, _payload())
    return jsonify(ok=True, team=team.to_dict())


@portal_bp.route("/api/portal/participant/team/join", methods=["POST"])
@participant_required
def join_team():
    data = _payload()
    team = community_service.join_team(current_user(), data.get("join_code", ""))
    return jsonify(ok=True, team=team.to_dict())


@portal_bp.route("/api/portal/participant/team/leave", methods=["POST"])
@participant_required
def leave_team():
    community_service.leave_team(current_user())
    return jsonify(ok=True)

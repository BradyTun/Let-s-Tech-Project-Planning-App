"""
app/services/community_service.py
=================================
Business logic for the hackathon community layer: industry-partner profiles,
problem statements (requirements), participant applications + the organizer
selection funnel, and participant team formation.

All mutating helpers wrap their writes so any anomaly rolls back cleanly and
business rules (selection cap, single-team membership, team size) live in one
place rather than being scattered across the HTTP handlers.
"""

from __future__ import annotations

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import (
    User,
    Project,
    Stakeholder,
    StakeholderRoleType,
    StakeholderProfile,
    IndustryRequirement,
    ParticipantProfile,
    Team,
    TeamMember,
    RequirementStatus,
    SelectionStatus,
    StakeholderHackathonStatus,
    ExperienceLevel,
    TeamStatus,
    coerce_enum,
)
from . import mail_service


class CommunityError(Exception):
    """Raised when a community business rule is violated."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


def _commit(action: str) -> None:
    try:
        db.session.commit()
    except (SQLAlchemyError, ValueError) as exc:
        db.session.rollback()
        raise CommunityError(f"Could not {action}: {exc}", status=422)


def _partner_for_user(user: User) -> Stakeholder:
    stakeholder = user.stakeholder
    if stakeholder is None:
        profile = user.stakeholder_profile
        project = Project.query.order_by(Project.created_at).first()
        if project is None:
            raise CommunityError(
                "Your partner account is not linked to an epic yet. "
                "Ask an organizer to add you in Industry Partners.",
                status=409,
            )
        stakeholder = Stakeholder(
            user_id=user.id,
            name=user.display_name,
            organization=(profile.organization if profile else None),
            industry=(profile.industry if profile else None),
            hackathon_status=(
                profile.hackathon_status if profile else StakeholderHackathonStatus.EXPLORING
            ),
            about=(profile.about if profile else None),
            website=(profile.website if profile else None),
            contact_phone=(profile.contact_phone if profile else None),
            contact_email=user.email,
            project_id=project.id,
        )
        stakeholder.set_roles([StakeholderRoleType.IN_KIND_SPONSOR])
        db.session.add(stakeholder)
        db.session.flush()
        if profile is not None:
            profile.stakeholder_id = stakeholder.id
        _commit("link partner account")
    return stakeholder


def _ensure_partner_profile(partner: Stakeholder) -> StakeholderProfile:
    profile = partner.partner_profile
    if profile is None:
        profile = StakeholderProfile(
            user_id=partner.user_id,
            stakeholder_id=partner.id,
            organization=partner.organization,
            industry=partner.industry,
            hackathon_status=partner.hackathon_status,
            about=partner.about,
            website=partner.website,
            contact_phone=partner.contact_phone,
        )
        db.session.add(profile)
        _commit("create partner profile")
    return profile


# ---------------------------------------------------------------------------
# Profile bootstrap (lazily create the 1:1 profile row)
# ---------------------------------------------------------------------------
def ensure_stakeholder_profile(user: User) -> StakeholderProfile:
    partner = _partner_for_user(user)
    profile = _ensure_partner_profile(partner)
    if profile.user_id != user.id:
        profile.user_id = user.id
    if profile.stakeholder_id != partner.id:
        profile.stakeholder_id = partner.id
    changed = False
    if profile.organization != partner.organization:
        profile.organization = partner.organization
        changed = True
    if profile.industry != partner.industry:
        profile.industry = partner.industry
        changed = True
    if profile.hackathon_status != partner.hackathon_status:
        profile.hackathon_status = partner.hackathon_status
        changed = True
    if profile.about != partner.about:
        profile.about = partner.about
        changed = True
    if profile.website != partner.website:
        profile.website = partner.website
        changed = True
    if profile.contact_phone != partner.contact_phone:
        profile.contact_phone = partner.contact_phone
        changed = True
    if changed:
        _commit("sync partner profile")
    return profile


def ensure_participant_profile(user: User) -> ParticipantProfile:
    profile = user.participant_profile
    if profile is None:
        profile = ParticipantProfile(user_id=user.id, full_name=user.display_name)
        db.session.add(profile)
        _commit("create participant profile")
    return profile


# ---------------------------------------------------------------------------
# Stakeholder profile + requirements
# ---------------------------------------------------------------------------
def update_stakeholder_profile(profile: StakeholderProfile, data: dict) -> StakeholderProfile:
    partner = profile.stakeholder
    if partner is None:
        raise CommunityError("Partner record is missing.", status=404)

    if "organization" in data:
        value = (data.get("organization") or "").strip() or None
        profile.organization = value
        partner.organization = value
    if "industry" in data:
        value = (data.get("industry") or "").strip() or None
        profile.industry = value
        partner.industry = value
    if "about" in data:
        value = data.get("about")
        profile.about = value
        partner.about = value
    if "website" in data:
        value = (data.get("website") or "").strip() or None
        profile.website = value
        partner.website = value
    if "contact_phone" in data:
        value = (data.get("contact_phone") or "").strip() or None
        profile.contact_phone = value
        partner.contact_phone = value
    if "hackathon_status" in data and data["hackathon_status"]:
        try:
            status = coerce_enum(
                StakeholderHackathonStatus, data["hackathon_status"], field="hackathon status"
            )
            profile.hackathon_status = status
            partner.hackathon_status = status
        except ValueError as exc:
            raise CommunityError(str(exc), status=400)
    _commit("update profile")
    return profile


def create_requirement(profile: StakeholderProfile, data: dict) -> IndustryRequirement:
    title = (data.get("title") or "").strip()
    if not title:
        raise CommunityError("A problem title is required.", status=400)
    status = RequirementStatus.OPEN
    if data.get("status"):
        try:
            status = coerce_enum(RequirementStatus, data["status"], field="requirement status")
        except ValueError as exc:
            raise CommunityError(str(exc), status=400)
    req = IndustryRequirement(
        stakeholder_id=profile.id,
        title=title,
        industry=(data.get("industry") or profile.industry or "").strip() or None,
        problem=data.get("problem"),
        desired_outcome=data.get("desired_outcome"),
        priority=int(data.get("priority", 2) or 2),
        status=status,
    )
    db.session.add(req)
    _commit("create requirement")
    return req


def update_requirement(req: IndustryRequirement, data: dict) -> IndustryRequirement:
    if "title" in data and data["title"]:
        req.title = data["title"].strip()
    if "industry" in data:
        req.industry = (data.get("industry") or "").strip() or None
    if "problem" in data:
        req.problem = data.get("problem")
    if "desired_outcome" in data:
        req.desired_outcome = data.get("desired_outcome")
    if "priority" in data and data["priority"] is not None:
        req.priority = int(data["priority"])
    if "status" in data and data["status"]:
        try:
            req.status = coerce_enum(RequirementStatus, data["status"], field="requirement status")
        except ValueError as exc:
            raise CommunityError(str(exc), status=400)
    _commit("update requirement")
    return req


def delete_requirement(req: IndustryRequirement) -> None:
    db.session.delete(req)
    _commit("delete requirement")


# ---------------------------------------------------------------------------
# Participant profile + organizer selection funnel
# ---------------------------------------------------------------------------
def update_participant_profile(profile: ParticipantProfile, data: dict) -> ParticipantProfile:
    if "full_name" in data and data["full_name"]:
        profile.full_name = data["full_name"].strip()
    if "phone" in data:
        profile.phone = (data.get("phone") or "").strip() or None
    if "school_or_org" in data:
        profile.school_or_org = (data.get("school_or_org") or "").strip() or None
    if "bio" in data:
        profile.bio = data.get("bio")
    if "skills" in data:
        profile.skills = data.get("skills")
    if "industry_interest" in data:
        profile.industry_interest = (data.get("industry_interest") or "").strip() or None
    if "experience_level" in data and data["experience_level"]:
        try:
            profile.experience_level = coerce_enum(
                ExperienceLevel, data["experience_level"], field="experience level"
            )
        except ValueError as exc:
            raise CommunityError(str(exc), status=400)
    _commit("update profile")
    return profile


def selected_count() -> int:
    return ParticipantProfile.query.filter(
        ParticipantProfile.selection_status == SelectionStatus.SELECTED
    ).count()


def selection_cap() -> int:
    return int(current_app.config.get("PARTICIPANT_SELECTION_CAP", 80))


def set_selection_status(profile: ParticipantProfile, status_value,
                         interview_notes=None) -> ParticipantProfile:
    """Organizer action: advance a participant through the selection funnel.

    Enforces the configured selection cap when moving someone to SELECTED.
    Sends a notification email when the final decision changes.
    """
    try:
        new_status = coerce_enum(SelectionStatus, status_value, field="selection status")
    except ValueError as exc:
        raise CommunityError(str(exc), status=400)

    previous = profile.selection_status
    if new_status == SelectionStatus.SELECTED and previous != SelectionStatus.SELECTED:
        cap = selection_cap()
        if selected_count() >= cap:
            raise CommunityError(
                f"Selection cap reached ({cap} participants). "
                f"Move someone out of 'Selected' first.",
                status=409,
            )

    profile.selection_status = new_status
    if interview_notes is not None:
        profile.interview_notes = interview_notes
    _commit("update selection")

    # Notify the applicant on a meaningful decision change.
    if new_status != previous and new_status in (
        SelectionStatus.SELECTED, SelectionStatus.WAITLISTED, SelectionStatus.REJECTED
    ):
        db.session.refresh(profile)
        mail_service.send_selection_update(profile)

    return profile


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------
def _require_selected(user: User) -> ParticipantProfile:
    profile = user.participant_profile
    if profile is None:
        raise CommunityError("Complete your participant profile first.", status=400)
    if profile.selection_status != SelectionStatus.SELECTED:
        raise CommunityError(
            "Team formation unlocks once you've been selected for the hackathon.",
            status=403,
        )
    return profile


def _unique_join_code() -> str:
    for _ in range(12):
        code = Team.generate_join_code()
        if Team.query.filter(Team.join_code == code).first() is None:
            return code
    raise CommunityError("Could not allocate a team code. Try again.", status=500)


def create_team(user: User, data: dict) -> Team:
    _require_selected(user)
    if user.team is not None:
        raise CommunityError("You're already in a team. Leave it before creating another.", status=409)

    name = (data.get("name") or "").strip()
    if not name:
        raise CommunityError("A team name is required.", status=400)

    target_id = data.get("target_requirement_id")
    if target_id is not None:
        if db.session.get(IndustryRequirement, target_id) is None:
            raise CommunityError("That problem statement no longer exists.", status=404)

    team = Team(
        name=name,
        pitch=data.get("pitch"),
        target_requirement_id=target_id,
        lead_user_id=user.id,
        join_code=_unique_join_code(),
        status=TeamStatus.FORMING,
    )
    db.session.add(team)
    db.session.flush()
    db.session.add(TeamMember(team_id=team.id, user_id=user.id, is_lead=True))
    _commit("create team")
    return team


def update_team(user: User, team: Team, data: dict) -> Team:
    if team.lead_user_id != user.id:
        raise CommunityError("Only the team lead can edit the team.", status=403)
    if "name" in data and data["name"]:
        team.name = data["name"].strip()
    if "pitch" in data:
        team.pitch = data.get("pitch")
    if "target_requirement_id" in data:
        target_id = data.get("target_requirement_id")
        if target_id is not None and db.session.get(IndustryRequirement, target_id) is None:
            raise CommunityError("That problem statement no longer exists.", status=404)
        team.target_requirement_id = target_id
    if "status" in data and data["status"]:
        try:
            team.status = coerce_enum(TeamStatus, data["status"], field="team status")
        except ValueError as exc:
            raise CommunityError(str(exc), status=400)
    _commit("update team")
    return team


def join_team(user: User, join_code: str) -> Team:
    _require_selected(user)
    if user.team is not None:
        raise CommunityError("You're already in a team. Leave it before joining another.", status=409)

    code = (join_code or "").strip().upper()
    if not code:
        raise CommunityError("Enter a team code.", status=400)
    team = Team.query.filter(Team.join_code == code).first()
    if team is None:
        raise CommunityError("No team matches that code.", status=404)

    max_size = int(current_app.config.get("MAX_TEAM_SIZE", 12))
    if team.size >= max_size:
        raise CommunityError(f"That team is full ({max_size} members).", status=409)

    db.session.add(TeamMember(team_id=team.id, user_id=user.id, is_lead=False))
    _commit("join team")
    return team


def leave_team(user: User) -> None:
    link = user.team_memberships[0] if user.team_memberships else None
    if link is None:
        raise CommunityError("You're not in a team.", status=400)
    team = link.team
    is_lead = team.lead_user_id == user.id
    if is_lead and team.size > 1:
        raise CommunityError(
            "Transfer the lead role or remove members before leaving as the lead.",
            status=409,
        )
    # Lead leaving an otherwise-empty team disbands it.
    if is_lead:
        db.session.delete(team)
    else:
        db.session.delete(link)
    _commit("leave team")


def teams_for_requirements(requirement_ids: list[int]) -> list[Team]:
    if not requirement_ids:
        return []
    return (
        Team.query.filter(Team.target_requirement_id.in_(requirement_ids))
        .order_by(Team.created_at.desc())
        .all()
    )

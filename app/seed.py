"""
app/seed.py
===========
Idempotent demo dataset for "48 Hours to Survive in the AI Era".
Guarantees the root admin, then loads a realistic operations plan.

Run with:  flask --app wsgi seed
"""

from __future__ import annotations

from datetime import date

from .extensions import db
from .models import (
    User,
    Project,
    Sprint,
    Stakeholder,
    Task,
    StakeholderRoleType,
    StakeholderStatus,
    UserRole,
    UserStatus,
    TaskState,
    StakeholderProfile,
    IndustryRequirement,
    ParticipantProfile,
    Team,
    TeamMember,
    StakeholderHackathonStatus,
    RequirementStatus,
    ExperienceLevel,
    SelectionStatus,
    TeamStatus,
)
from .services.auth_service import ensure_root_admin


def run_seed() -> bool:
    """Idempotently load the initial dataset.

    Schema is owned by Alembic migrations, so this never creates tables.
    Returns True if demo data was inserted, False if it already existed.
    """
    admin = ensure_root_admin()
    existing_project = Project.query.order_by(Project.created_at).first()
    if existing_project is not None:
        _seed_community(existing_project)
        return False  # ops data already present — nothing more to do

    # --- Team (active members so demo tasks can be assigned) --------------
    su = User(email="su@letstechclub.org", username="Su Su", role=UserRole.MEMBER,
              status=UserStatus.ACTIVE)
    mint = User(email="min@letstechclub.org", username="Min Thant", role=UserRole.MEMBER,
                status=UserStatus.ACTIVE, is_scrum_master=True)
    hnin = User(email="hnin@letstechclub.org", username="Hnin Wai", role=UserRole.MEMBER,
                status=UserStatus.INVITED)  # invited but not yet onboarded
    db.session.add_all([su, mint, hnin])
    db.session.commit()

    # --- Epic --------------------------------------------------------------
    project = Project(
        name="48 Hours to Survive in the AI Era",
        description="Internal operations plan for the Let's Tech Club hackathon (Jul 17–19).",
        owner_id=admin.id,
    )
    db.session.add(project)
    db.session.commit()

    # --- Stakeholders (multi-role + status) -------------------------------
    aya = Stakeholder(name="AYA Bank", organization="AYA Financial Group",
                      status=StakeholderStatus.CONFIRMED,
                      contact_email="partnerships@ayabank.com", project_id=project.id)
    aya.set_roles([StakeholderRoleType.MAIN_SPONSOR])

    kfc = Stakeholder(name="KFC Myanmar", organization="Yum! Brands",
                      status=StakeholderStatus.PENDING,
                      contact_email="events@kfc.com.mm", project_id=project.id)
    kfc.set_roles([StakeholderRoleType.IN_KIND_SPONSOR])

    thiri = Stakeholder(name="Dr. Thiri", organization="AI Research Lab",
                        status=StakeholderStatus.CONFIRMED,
                        contact_email="thiri@ai.org", project_id=project.id)
    # One party, multiple roles: judge AND mentor AND speaker.
    thiri.set_roles([StakeholderRoleType.JUDGE, StakeholderRoleType.MENTOR,
                     StakeholderRoleType.SPEAKER])

    royald = Stakeholder(name="Royal D", organization="Beverage Partner",
                         status=StakeholderStatus.PENDING, project_id=project.id)
    royald.set_roles([StakeholderRoleType.IN_KIND_SPONSOR])

    novotel = Stakeholder(name="Novotel Grand Ballroom", organization="Novotel Yangon",
                          status=StakeholderStatus.CONFIRMED,
                          contact_email="events@novotel.com", project_id=project.id)
    novotel.set_roles([StakeholderRoleType.VENUE_SPONSOR])

    guest = Stakeholder(name="U Hla (Guest of Honour)", status=StakeholderStatus.PENDING,
                        project_id=project.id)
    guest.set_roles([StakeholderRoleType.GUEST, StakeholderRoleType.SPEAKER])

    db.session.add_all([aya, kfc, thiri, royald, novotel, guest])
    db.session.commit()

    # --- Sprints -----------------------------------------------------------
    s1 = Sprint(name="Phase 1: Venue Freeze", sequence=1,
                goal="Lock venue, power, and floor plan.",
                start_date=date(2026, 6, 20), end_date=date(2026, 6, 30), project_id=project.id)
    s2 = Sprint(name="Phase 2: Sponsor Lock", sequence=2,
                goal="Secure main + in-kind sponsor commitments.",
                start_date=date(2026, 7, 1), end_date=date(2026, 7, 10), project_id=project.id)
    s3 = Sprint(name="Phase 3: Show Day Ops", sequence=3,
                goal="On-site execution readiness.",
                start_date=date(2026, 7, 11), end_date=date(2026, 7, 19), project_id=project.id)
    db.session.add_all([s1, s2, s3])
    db.session.commit()

    # --- Tasks -------------------------------------------------------------
    t1 = Task(title="Confirm ballroom booking & deposit", priority=1,
              sprint_id=s1.id, assigned_to=su.id, due_date=date(2026, 6, 24))
    t2 = Task(title="Audit main-stage power supply", priority=1,
              sprint_id=s1.id, assigned_to=su.id, due_date=date(2026, 6, 29))
    t3 = Task(title="Draft AYA Bank sponsorship deck", priority=2,
              sprint_id=s2.id, assigned_to=mint.id, stakeholder_id=aya.id,
              due_date=date(2026, 7, 3))
    t4 = Task(title="Coordinate KFC catering for 48h", priority=2,
              sprint_id=s2.id, stakeholder_id=kfc.id, due_date=date(2026, 7, 8))
    t5 = Task(title="Confirm judge/mentor schedule (Dr. Thiri)", priority=2,
              sprint_id=s3.id, stakeholder_id=thiri.id, due_date=date(2026, 7, 15))
    db.session.add_all([t1, t2, t3, t4, t5])
    db.session.commit()

    t1.state = TaskState.IN_PROGRESS
    db.session.commit()

    _seed_community(project)

    return True


def _seed_community(project: Project | None = None) -> None:
    """Idempotently load demo industry partners, participants and a team."""
    project = project or Project.query.order_by(Project.created_at).first()
    if project is None:
        return

    if ParticipantProfile.query.first() is not None and IndustryRequirement.query.first() is not None:
        return

    def ensure_partner(email, name, organization, industry, hackathon_status, about):
        email = email.strip().lower()
        user = User.query.filter(User.email == email).first()
        if user is None:
            user = User(email=email, username=name,
                        role=UserRole.STAKEHOLDER, status=UserStatus.ACTIVE)
            db.session.add(user)
            db.session.flush()
        else:
            user.role = UserRole.STAKEHOLDER
            if user.status == UserStatus.DISABLED:
                user.status = UserStatus.ACTIVE
            if not user.username:
                user.username = name

        stakeholder = Stakeholder.query.filter(Stakeholder.contact_email == email).first()
        if stakeholder is None and user.id is not None:
            stakeholder = Stakeholder.query.filter(Stakeholder.user_id == user.id).first()

        if stakeholder is None:
            stakeholder = Stakeholder(
                user_id=user.id,
                name=name,
                organization=organization,
                industry=industry,
                hackathon_status=hackathon_status,
                about=about,
                status=StakeholderStatus.CONFIRMED,
                contact_email=email,
                project_id=project.id,
            )
            stakeholder.set_roles([StakeholderRoleType.IN_KIND_SPONSOR])
            db.session.add(stakeholder)
            db.session.flush()
        else:
            stakeholder.user_id = user.id
            stakeholder.name = stakeholder.name or name
            stakeholder.organization = stakeholder.organization or organization
            stakeholder.industry = stakeholder.industry or industry
            stakeholder.hackathon_status = stakeholder.hackathon_status or hackathon_status
            stakeholder.about = stakeholder.about or about
            stakeholder.contact_email = stakeholder.contact_email or email
            if not stakeholder.role_links:
                stakeholder.set_roles([StakeholderRoleType.IN_KIND_SPONSOR])

        profile = stakeholder.partner_profile
        if profile is None:
            profile = user.stakeholder_profile
        if profile is None:
            profile = StakeholderProfile(user_id=user.id)
            db.session.add(profile)
        profile.user_id = user.id
        profile.stakeholder_id = stakeholder.id
        profile.organization = stakeholder.organization
        profile.industry = stakeholder.industry
        profile.hackathon_status = stakeholder.hackathon_status
        profile.about = stakeholder.about
        profile.contact_phone = stakeholder.contact_phone
        profile.website = stakeholder.website
        return stakeholder, profile

    def ensure_requirement(profile: StakeholderProfile, title: str, **kwargs):
        req = IndustryRequirement.query.filter(
            IndustryRequirement.stakeholder_id == profile.id,
            IndustryRequirement.title == title,
        ).first()
        if req is None:
            req = IndustryRequirement(
                stakeholder_id=profile.id,
                title=title,
                industry=kwargs.get("industry"),
                priority=kwargs.get("priority", 2),
                status=kwargs.get("status", RequirementStatus.OPEN),
                problem=kwargs.get("problem"),
                desired_outcome=kwargs.get("desired_outcome"),
            )
            db.session.add(req)

    # --- Industry partners (email-only sign-in) --------------------------
    _agri_partner, agri_profile = ensure_partner(
        "agritech@demo.letstech",
        "AgriTech Myanmar",
        "AgriTech Myanmar",
        "Agriculture",
        StakeholderHackathonStatus.PROVIDING_PROBLEMS,
        "Bringing modern tooling to smallholder farms.",
    )
    _health_partner, health_profile = ensure_partner(
        "hospital@demo.letstech",
        "Yangon General Hospital",
        "Yangon General Hospital",
        "Healthcare",
        StakeholderHackathonStatus.SPONSORING,
        "Public hospital modernizing patient operations.",
    )

    ensure_requirement(
        agri_profile,
        "Predict crop disease from leaf photos",
        industry="Agriculture", priority=1, status=RequirementStatus.OPEN,
        problem="Farmers spot disease too late and lose much of their yield.",
        desired_outcome="A mobile tool that flags likely disease from a single leaf photo.",
    )
    ensure_requirement(
        agri_profile,
        "Fair produce pricing transparency",
        industry="Agriculture", priority=2, status=RequirementStatus.OPEN,
        problem="Middlemen obscure fair market prices from farmers.",
        desired_outcome="A simple price-reference service farmers can trust.",
    )
    ensure_requirement(
        health_profile,
        "Automate clinic appointment scheduling",
        industry="Healthcare", priority=1, status=RequirementStatus.OPEN,
        problem="Manual phone scheduling causes long queues and no-shows.",
        desired_outcome="Self-service scheduling with automatic reminders.",
    )
    db.session.commit()

    # --- Participants (varied selection states) ---------------------------
    def mk_part(email, name, level, status, skills, school, industry=None):
        u = User(email=email, username=name, role=UserRole.PARTICIPANT,
                 status=UserStatus.ACTIVE)
        db.session.add(u)
        db.session.flush()
        db.session.add(ParticipantProfile(
            user_id=u.id, full_name=name, experience_level=level,
            selection_status=status, skills=skills, school_or_org=school,
            industry_interest=industry,
        ))
        return u

    sel1 = mk_part("aung@demo.letstech", "Aung Ko", ExperienceLevel.ADVANCED,
                   SelectionStatus.SELECTED, "Python, ML, Computer Vision", "UIT", "Agriculture")
    sel2 = mk_part("may@demo.letstech", "May Thu", ExperienceLevel.INTERMEDIATE,
                   SelectionStatus.SELECTED, "React, UI/UX", "UCSY", "Healthcare")
    mk_part("kyaw@demo.letstech", "Kyaw Zin", ExperienceLevel.INTERMEDIATE,
            SelectionStatus.SELECTED, "Flutter, Firebase", "Freelancer")
    mk_part("nilar@demo.letstech", "Nilar Win", ExperienceLevel.BEGINNER,
            SelectionStatus.INTERVIEWING, "HTML, CSS, JavaScript", "UIT")
    mk_part("zaw@demo.letstech", "Zaw Min", ExperienceLevel.BEGINNER,
            SelectionStatus.APPLIED, "Eager to learn", "UCSY")
    mk_part("hsu@demo.letstech", "Hsu Hlaing", ExperienceLevel.ADVANCED,
            SelectionStatus.WAITLISTED, "Data engineering, SQL", "MIIT")
    db.session.commit()

    # --- A team formed by selected participants --------------------------
    target = IndustryRequirement.query.filter_by(
        title="Predict crop disease from leaf photos"
    ).first()
    team = Team(
        name="Automation Avengers",
        pitch="AI leaf-scanner for early crop-disease detection.",
        target_requirement_id=target.id if target else None,
        lead_user_id=sel1.id, join_code=Team.generate_join_code(),
        status=TeamStatus.FORMING,
    )
    db.session.add(team)
    db.session.flush()
    db.session.add_all([
        TeamMember(team_id=team.id, user_id=sel1.id, is_lead=True),
        TeamMember(team_id=team.id, user_id=sel2.id, is_lead=False),
    ])
    db.session.commit()

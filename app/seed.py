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
)
from .services.auth_service import ensure_root_admin


def run_seed() -> bool:
    """Idempotently load the initial dataset.

    Schema is owned by Alembic migrations, so this never creates tables.
    Returns True if demo data was inserted, False if it already existed.
    """
    admin = ensure_root_admin()

    if Project.query.first() is not None:
        return False  # data already present — nothing to do

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
              sprint_id=s1.id, assigned_to=su.id)
    t2 = Task(title="Audit main-stage power supply", priority=1,
              sprint_id=s1.id, assigned_to=su.id)
    t3 = Task(title="Draft AYA Bank sponsorship deck", priority=2,
              sprint_id=s2.id, assigned_to=mint.id, stakeholder_id=aya.id)
    t4 = Task(title="Coordinate KFC catering for 48h", priority=2,
              sprint_id=s2.id, stakeholder_id=kfc.id)
    t5 = Task(title="Confirm judge/mentor schedule (Dr. Thiri)", priority=2,
              sprint_id=s3.id, stakeholder_id=thiri.id)
    db.session.add_all([t1, t2, t3, t4, t5])
    db.session.commit()

    t1.state = TaskState.IN_PROGRESS
    db.session.commit()

    return True

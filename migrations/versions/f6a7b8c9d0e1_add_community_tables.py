"""add community tables (stakeholder accounts, requirements, participants, teams)

Adds the industry-partner / participant / team domain on top of the existing
operations schema, plus the new STAKEHOLDER and PARTICIPANT values on the
``user_role`` enum. Backward compatible: no existing table is altered.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-23 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


_STAKEHOLDER_HACKATHON_STATUS = sa.Enum(
    "EXPLORING", "PROVIDING_PROBLEMS", "SPONSORING", "CONFIRMED_PARTNER",
    "NOT_PARTICIPATING", name="stakeholder_hackathon_status",
)
_REQUIREMENT_STATUS = sa.Enum(
    "DRAFT", "OPEN", "ADDRESSED", "CLOSED", name="requirement_status",
)
_EXPERIENCE_LEVEL = sa.Enum(
    "BEGINNER", "INTERMEDIATE", "ADVANCED", name="experience_level",
)
_SELECTION_STATUS = sa.Enum(
    "APPLIED", "INTERVIEWING", "SELECTED", "WAITLISTED", "REJECTED",
    name="selection_status",
)
_TEAM_STATUS = sa.Enum("FORMING", "SUBMITTED", name="team_status")


def _extend_user_role_enum() -> None:
    """Add STAKEHOLDER/PARTICIPANT to the user_role enum (PostgreSQL only)."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite stores enums as plain strings; nothing to alter.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'STAKEHOLDER'")
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'PARTICIPANT'")


def upgrade():
    _extend_user_role_enum()

    op.create_table(
        "stakeholder_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("organization", sa.String(length=160), nullable=True),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("hackathon_status", _STAKEHOLDER_HACKATHON_STATUS, nullable=False),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_stakeholder_profile_user"),
    )
    op.create_index(
        op.f("ix_stakeholder_profiles_user_id"), "stakeholder_profiles", ["user_id"]
    )
    op.create_index(
        op.f("ix_stakeholder_profiles_industry"), "stakeholder_profiles", ["industry"]
    )

    op.create_table(
        "industry_requirements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stakeholder_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("problem", sa.Text(), nullable=True),
        sa.Column("desired_outcome", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", _REQUIREMENT_STATUS, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["stakeholder_id"], ["stakeholder_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_industry_requirements_stakeholder_id"),
        "industry_requirements", ["stakeholder_id"],
    )
    op.create_index(
        op.f("ix_industry_requirements_industry"), "industry_requirements", ["industry"]
    )
    op.create_index(
        op.f("ix_industry_requirements_status"), "industry_requirements", ["status"]
    )

    op.create_table(
        "participant_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("school_or_org", sa.String(length=160), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("skills", sa.Text(), nullable=True),
        sa.Column("experience_level", _EXPERIENCE_LEVEL, nullable=False),
        sa.Column("industry_interest", sa.String(length=120), nullable=True),
        sa.Column("selection_status", _SELECTION_STATUS, nullable=False),
        sa.Column("interview_notes", sa.Text(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_participant_profile_user"),
    )
    op.create_index(
        op.f("ix_participant_profiles_user_id"), "participant_profiles", ["user_id"]
    )
    op.create_index(
        op.f("ix_participant_profiles_selection_status"),
        "participant_profiles", ["selection_status"],
    )

    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("pitch", sa.Text(), nullable=True),
        sa.Column("target_requirement_id", sa.Integer(), nullable=True),
        sa.Column("lead_user_id", sa.Integer(), nullable=False),
        sa.Column("join_code", sa.String(length=12), nullable=False),
        sa.Column("status", _TEAM_STATUS, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["target_requirement_id"], ["industry_requirements.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["lead_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("join_code", name="uq_team_join_code"),
    )
    op.create_index(op.f("ix_teams_target_requirement_id"), "teams", ["target_requirement_id"])
    op.create_index(op.f("ix_teams_lead_user_id"), "teams", ["lead_user_id"])
    op.create_index(op.f("ix_teams_join_code"), "teams", ["join_code"])
    op.create_index(op.f("ix_teams_status"), "teams", ["status"])

    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_lead", sa.Boolean(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_team_member_user"),
    )
    op.create_index(op.f("ix_team_members_team_id"), "team_members", ["team_id"])
    op.create_index(op.f("ix_team_members_user_id"), "team_members", ["user_id"])


def downgrade():
    op.drop_index(op.f("ix_team_members_user_id"), table_name="team_members")
    op.drop_index(op.f("ix_team_members_team_id"), table_name="team_members")
    op.drop_table("team_members")

    op.drop_index(op.f("ix_teams_status"), table_name="teams")
    op.drop_index(op.f("ix_teams_join_code"), table_name="teams")
    op.drop_index(op.f("ix_teams_lead_user_id"), table_name="teams")
    op.drop_index(op.f("ix_teams_target_requirement_id"), table_name="teams")
    op.drop_table("teams")

    op.drop_index(op.f("ix_participant_profiles_selection_status"), table_name="participant_profiles")
    op.drop_index(op.f("ix_participant_profiles_user_id"), table_name="participant_profiles")
    op.drop_table("participant_profiles")

    op.drop_index(op.f("ix_industry_requirements_status"), table_name="industry_requirements")
    op.drop_index(op.f("ix_industry_requirements_industry"), table_name="industry_requirements")
    op.drop_index(op.f("ix_industry_requirements_stakeholder_id"), table_name="industry_requirements")
    op.drop_table("industry_requirements")

    op.drop_index(op.f("ix_stakeholder_profiles_industry"), table_name="stakeholder_profiles")
    op.drop_index(op.f("ix_stakeholder_profiles_user_id"), table_name="stakeholder_profiles")
    op.drop_table("stakeholder_profiles")

    # Enum types are left in place on PostgreSQL; dropping enum VALUES is not
    # supported and the bare types are harmless if the tables are gone.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for enum_type in (
            "team_status", "selection_status", "experience_level",
            "requirement_status", "stakeholder_hackathon_status",
        ):
            op.execute(sa.text(f"DROP TYPE IF EXISTS {enum_type}"))

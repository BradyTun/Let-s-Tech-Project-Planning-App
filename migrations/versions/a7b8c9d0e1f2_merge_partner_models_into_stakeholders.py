"""merge partner models into canonical stakeholders

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-24 10:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


_HACKATHON_ENUM = sa.Enum(
    "EXPLORING", "PROVIDING_PROBLEMS", "SPONSORING", "CONFIRMED_PARTNER",
    "NOT_PARTICIPATING", name="stakeholder_hackathon_status", create_type=False,
)


def _derive_display_name(username: str | None, email: str | None) -> str:
    """Prefer username; otherwise derive from email local-part."""
    if username and username.strip():
        return username.strip()
    if not email:
        return ""
    local, _sep, _domain = email.partition("@")
    return local or email


def _insert_missing_stakeholders(connection, default_project_id: int | None) -> None:
    if default_project_id is None:
        return

    rows = connection.execute(sa.text("""
        SELECT
            sp.id AS profile_id,
            sp.user_id AS user_id,
            sp.organization AS organization,
            sp.industry AS industry,
            sp.hackathon_status AS hackathon_status,
            sp.about AS about,
            sp.website AS website,
            sp.contact_phone AS contact_phone,
            u.username AS username,
            u.email AS email
        FROM stakeholder_profiles sp
        JOIN users u ON u.id = sp.user_id
        WHERE sp.stakeholder_id IS NULL
    """)).mappings().all()

    for row in rows:
        display_name = _derive_display_name(row["username"], row["email"])
        params = {
            "user_id": row["user_id"],
            "name": display_name or row["email"],
            "organization": row["organization"],
            "industry": row["industry"],
            "hackathon_status": row["hackathon_status"] or "EXPLORING",
            "about": row["about"],
            "website": row["website"],
            "contact_phone": row["contact_phone"],
            "contact_email": row["email"],
            "project_id": default_project_id,
        }

        if connection.dialect.name == "postgresql":
            stakeholder_id = connection.execute(sa.text("""
                INSERT INTO stakeholders (
                    user_id, name, organization, industry, hackathon_status,
                    about, website, status, contact_email, contact_phone,
                    notes, project_id, created_at
                ) VALUES (
                    :user_id, :name, :organization, :industry, :hackathon_status,
                    :about, :website, 'PENDING', :contact_email, :contact_phone,
                    NULL, :project_id, NOW()
                ) RETURNING id
            """), params).scalar_one()
            connection.execute(sa.text("""
                INSERT INTO stakeholder_role_links (stakeholder_id, role)
                VALUES (:stakeholder_id, 'IN_KIND_SPONSOR')
                ON CONFLICT DO NOTHING
            """), {"stakeholder_id": stakeholder_id})
        else:
            connection.execute(sa.text("""
                INSERT INTO stakeholders (
                    user_id, name, organization, industry, hackathon_status,
                    about, website, status, contact_email, contact_phone,
                    notes, project_id, created_at
                ) VALUES (
                    :user_id, :name, :organization, :industry, :hackathon_status,
                    :about, :website, 'PENDING', :contact_email, :contact_phone,
                    NULL, :project_id, CURRENT_TIMESTAMP
                )
            """), params)
            stakeholder_id = connection.execute(sa.text("SELECT last_insert_rowid()")).scalar()
            connection.execute(sa.text("""
                INSERT OR IGNORE INTO stakeholder_role_links (stakeholder_id, role)
                VALUES (:stakeholder_id, 'IN_KIND_SPONSOR')
            """), {"stakeholder_id": stakeholder_id})

        connection.execute(sa.text("""
            UPDATE stakeholder_profiles
            SET stakeholder_id = :stakeholder_id
            WHERE id = :profile_id
        """), {
            "stakeholder_id": stakeholder_id,
            "profile_id": row["profile_id"],
        })


def upgrade():
    with op.batch_alter_table("stakeholders") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("industry", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("hackathon_status", _HACKATHON_ENUM, nullable=True))
        batch_op.add_column(sa.Column("about", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("website", sa.String(length=255), nullable=True))
        batch_op.create_index(batch_op.f("ix_stakeholders_user_id"), ["user_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_stakeholders_industry"), ["industry"], unique=False)
        batch_op.create_foreign_key(
            "fk_stakeholders_user_id_users", "users", ["user_id"], ["id"], ondelete="SET NULL"
        )

    with op.batch_alter_table("stakeholder_profiles") as batch_op:
        batch_op.add_column(sa.Column("stakeholder_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_stakeholder_profiles_stakeholder_id"),
            ["stakeholder_id"], unique=True,
        )
        batch_op.create_foreign_key(
            "fk_stakeholder_profiles_stakeholder_id_stakeholders",
            "stakeholders", ["stakeholder_id"], ["id"], ondelete="CASCADE"
        )

    connection = op.get_bind()

    # Link existing stakeholders to stakeholder users via contact email.
    connection.execute(sa.text("""
        UPDATE stakeholders
        SET user_id = (
            SELECT u.id FROM users u
            WHERE lower(u.email) = lower(stakeholders.contact_email)
            LIMIT 1
        )
        WHERE user_id IS NULL AND contact_email IS NOT NULL
    """))

    # Fill newly-added partner fields from previously separate profile rows.
    connection.execute(sa.text("""
        UPDATE stakeholders
        SET
            organization = COALESCE(
                stakeholders.organization,
                (SELECT sp.organization FROM stakeholder_profiles sp WHERE sp.user_id = stakeholders.user_id LIMIT 1)
            ),
            industry = COALESCE(
                stakeholders.industry,
                (SELECT sp.industry FROM stakeholder_profiles sp WHERE sp.user_id = stakeholders.user_id LIMIT 1)
            ),
            hackathon_status = COALESCE(
                stakeholders.hackathon_status,
                (SELECT sp.hackathon_status FROM stakeholder_profiles sp WHERE sp.user_id = stakeholders.user_id LIMIT 1),
                'EXPLORING'
            ),
            about = COALESCE(
                stakeholders.about,
                (SELECT sp.about FROM stakeholder_profiles sp WHERE sp.user_id = stakeholders.user_id LIMIT 1)
            ),
            website = COALESCE(
                stakeholders.website,
                (SELECT sp.website FROM stakeholder_profiles sp WHERE sp.user_id = stakeholders.user_id LIMIT 1)
            ),
            contact_phone = COALESCE(
                stakeholders.contact_phone,
                (SELECT sp.contact_phone FROM stakeholder_profiles sp WHERE sp.user_id = stakeholders.user_id LIMIT 1)
            )
        WHERE user_id IS NOT NULL
    """))

    connection.execute(sa.text("""
        UPDATE stakeholders
        SET contact_email = (
            SELECT u.email FROM users u WHERE u.id = stakeholders.user_id LIMIT 1
        )
        WHERE user_id IS NOT NULL AND contact_email IS NULL
    """))

    # Link profile rows to canonical stakeholders.
    connection.execute(sa.text("""
        UPDATE stakeholder_profiles
        SET stakeholder_id = (
            SELECT s.id FROM stakeholders s
            WHERE s.user_id = stakeholder_profiles.user_id
            LIMIT 1
        )
        WHERE stakeholder_id IS NULL
    """))

    connection.execute(sa.text("""
        UPDATE stakeholder_profiles
        SET stakeholder_id = (
            SELECT s.id FROM stakeholders s
            WHERE lower(COALESCE(s.organization, '')) = lower(COALESCE(stakeholder_profiles.organization, ''))
              AND COALESCE(stakeholder_profiles.organization, '') <> ''
            LIMIT 1
        )
        WHERE stakeholder_id IS NULL
    """))

    default_project_id = connection.execute(sa.text(
        "SELECT id FROM projects ORDER BY created_at, id LIMIT 1"
    )).scalar()
    _insert_missing_stakeholders(connection, default_project_id)

    connection.execute(sa.text("""
        UPDATE stakeholders
        SET hackathon_status = COALESCE(hackathon_status, 'EXPLORING')
        WHERE hackathon_status IS NULL
    """))


def downgrade():
    with op.batch_alter_table("stakeholder_profiles") as batch_op:
        batch_op.drop_constraint(
            "fk_stakeholder_profiles_stakeholder_id_stakeholders", type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_stakeholder_profiles_stakeholder_id"))
        batch_op.drop_column("stakeholder_id")

    with op.batch_alter_table("stakeholders") as batch_op:
        batch_op.drop_constraint("fk_stakeholders_user_id_users", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_stakeholders_industry"))
        batch_op.drop_index(batch_op.f("ix_stakeholders_user_id"))
        batch_op.drop_column("website")
        batch_op.drop_column("about")
        batch_op.drop_column("hackathon_status")
        batch_op.drop_column("industry")
        batch_op.drop_column("user_id")

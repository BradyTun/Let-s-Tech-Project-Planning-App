"""all sprints active by default

Removes the activate/deactivate concept: every sprint is active. Backfills
existing rows so none remain inactive. New rows default to active via the ORM.

Revision ID: c2d3e4f5a6b7
Revises: b7145b1e85b6
Create Date: 2026-06-19 13:10:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


# revision identifiers, used by Alembic.
revision = "c2d3e4f5a6b7"
down_revision = "b7145b1e85b6"
branch_labels = None
depends_on = None


# Lightweight table reference so the UPDATE renders correctly on every dialect
# (Postgres `true`, SQLite `1`).
_sprints = table("sprints", column("is_active", sa.Boolean))


def upgrade():
    op.execute(_sprints.update().values(is_active=True))


def downgrade():
    # Non-destructive: nothing to undo (the column and rows remain).
    pass

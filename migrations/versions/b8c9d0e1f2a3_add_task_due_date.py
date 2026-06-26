"""add task due date

Adds an optional ``due_date`` (calendar date) to tasks so work items can be
plotted on the marketing-calendar month view. Nullable + indexed so the
calendar can range-query a month cheaply. Additive and dialect-portable:
SQLite and Postgres both support ``ADD COLUMN`` + ``CREATE INDEX`` natively,
so no table rebuild is required.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("due_date", sa.Date(), nullable=True))
    op.create_index(op.f("ix_tasks_due_date"), "tasks", ["due_date"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_tasks_due_date"), table_name="tasks")
    op.drop_column("tasks", "due_date")

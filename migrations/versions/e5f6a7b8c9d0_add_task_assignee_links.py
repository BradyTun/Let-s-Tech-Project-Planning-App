"""add task assignee links

Persist Trello-style multi-assignee membership without removing the existing
`tasks.assigned_to` single-assignee column. Existing assignments are backfilled
so current tasks retain their assignee in the new link table.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-22 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_assignee_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "user_id", name="uq_task_assignee_link"),
    )
    op.create_index(
        op.f("ix_task_assignee_links_task_id"),
        "task_assignee_links",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_assignee_links_user_id"),
        "task_assignee_links",
        ["user_id"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO task_assignee_links (task_id, user_id, created_at)
            SELECT tasks.id, tasks.assigned_to, tasks.created_at
            FROM tasks
            WHERE tasks.assigned_to IS NOT NULL
            """
        )
    )


def downgrade():
    op.drop_index(op.f("ix_task_assignee_links_user_id"), table_name="task_assignee_links")
    op.drop_index(op.f("ix_task_assignee_links_task_id"), table_name="task_assignee_links")
    op.drop_table("task_assignee_links")

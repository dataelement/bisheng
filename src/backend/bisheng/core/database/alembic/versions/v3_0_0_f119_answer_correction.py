"""Create the F119 answer correction workflow records."""

import sqlalchemy as sa
from alembic import context, op

revision = "f119_answer_correction"
down_revision = "f114_app_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode() and sa.inspect(op.get_bind()).has_table("answer_correction"):
        return
    op.create_table(
        "answer_correction",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("app_id", sa.String(64), nullable=False),
        sa.Column("answer_id", sa.Integer(), nullable=False),
        sa.Column("submitter_id", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("correction", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("knowledge_id", sa.Integer()),
        sa.Column("assignee_id", sa.Integer()),
        sa.Column("assigned_by", sa.Integer()),
        sa.Column("assigned_at", sa.DateTime()),
        sa.Column("result", sa.Text()),
        sa.Column("processed_by", sa.Integer()),
        sa.Column("processed_at", sa.DateTime()),
        sa.Column("reply", sa.Text()),
        sa.Column("replied_by", sa.Integer()),
        sa.Column("replied_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )
    for index, subject in (
        ("ix_ac_submitter", "submitter_id"),
        ("ix_ac_app", "app_id"),
        ("ix_ac_assignee", "assignee_id"),
    ):
        op.create_index(index, "answer_correction", ["tenant_id", subject, "created_at", "id"])


def downgrade() -> None:
    op.drop_table("answer_correction")

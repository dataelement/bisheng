"""持久化知识修复预算和积分、OpenFGA 执行租约。"""

import sqlalchemy as sa
from alembic import op

revision = "f108_background_budgets"
down_revision = "f107_migration_reconcile_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("knowledge_document_repair_state"):
        op.create_table(
            "knowledge_document_repair_state",
            sa.Column("document_id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rebuild_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("knowledge_document_repair_state")}
    if "ix_knowledge_document_repair_state_tenant_id" not in indexes:
        op.create_index(
            "ix_knowledge_document_repair_state_tenant_id", "knowledge_document_repair_state", ["tenant_id"]
        )
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("failed_tuple")}
    for column in (
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
    ):
        if column.name not in columns:
            op.add_column("failed_tuple", column)
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("point_sync_outbox")}
    for column in (
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
    ):
        if column.name not in columns:
            op.add_column("point_sync_outbox", column)


def downgrade() -> None:
    op.drop_table("knowledge_document_repair_state")
    for name in ("next_retry_at", "lease_until", "lease_owner"):
        op.drop_column("failed_tuple", name)
    for name in ("lease_until", "lease_owner"):
        op.drop_column("point_sync_outbox", name)

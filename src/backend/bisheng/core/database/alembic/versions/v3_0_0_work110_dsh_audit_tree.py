"""DDL only; historical relationship preparation is a separate operator command."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists

revision = "f062_work110_audit_tree"
down_revision = "f062_work110_audit_groups"
branch_labels = None
depends_on = None


def upgrade():
    request = "dsh_model_audit_request"
    if table_exists(request):
        if not column_exists(request, "hierarchy_indexed"):
            op.add_column(
                request, sa.Column("hierarchy_indexed", sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )
        if not index_exists(request, "ix_dma_request_tree_pending"):
            op.create_index("ix_dma_request_tree_pending", request, ["tenant_id", "hierarchy_indexed", "request_id"])
    group = "dsh_model_audit_conversation"
    if table_exists(group):
        for column in (
            sa.Column("origin_state", sa.String(16), nullable=False, server_default="UNKNOWN"),
            sa.Column("declared_parent_key", sa.String(64)),
            sa.Column("parent_declaration_missing", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("relation_conflict", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        ):
            if not column_exists(group, column.name):
                op.add_column(group, column)


def downgrade():
    # Retain additive columns and rebuildable directories on application rollback.
    pass

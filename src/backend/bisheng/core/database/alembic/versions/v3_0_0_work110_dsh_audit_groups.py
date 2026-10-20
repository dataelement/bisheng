"""DDL only: presentation status and independently rebuildable group projection."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists

revision = "f062_work110_audit_groups"
down_revision = "f062_work110_audit_sources"
branch_labels = None
depends_on = None
TABLE = "dsh_model_audit_request"


def upgrade():
    if not table_exists(TABLE):
        return
    for column in (
        sa.Column("audit_status", sa.String(16), nullable=True),
        sa.Column("group_index_pending", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("group_indexed_status", sa.String(16), nullable=True),
    ):
        if not column_exists(TABLE, column.name):
            op.add_column(TABLE, column)
    for name, columns in (
        ("ix_dma_request_status", ["tenant_id", "audit_status", "started_at", "request_id"]),
        ("ix_dma_request_association", ["tenant_id", "association_status", "started_at", "request_id"]),
        ("ix_dma_request_group_pending", ["tenant_id", "group_index_pending", "request_id"]),
    ):
        if not index_exists(TABLE, name):
            op.create_index(name, TABLE, columns)


def downgrade():
    # Application rollback retains audit facts and the rebuildable directory.
    pass

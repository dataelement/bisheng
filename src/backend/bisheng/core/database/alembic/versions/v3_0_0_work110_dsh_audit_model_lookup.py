"""Index audit model ID/exact-name lookup; historical digests use a separate ops job."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists

revision = "f062_work110_audit_lookup"
down_revision = "f065_dsh_install_policy_default_off"
branch_labels = None
depends_on = None

TABLE = "dsh_model_audit_request"
INDEXES = {
    "ix_dma_request_model": ["tenant_id", "model_id", "started_at", "request_id"],
    "ix_dma_request_name": ["tenant_id", "model_name_digest", "started_at", "request_id"],
}


def upgrade():
    if not table_exists(TABLE):
        return
    if not column_exists(TABLE, "model_name_digest"):
        op.add_column(TABLE, sa.Column("model_name_digest", sa.String(64), nullable=True))
    for name, columns in INDEXES.items():
        if not index_exists(TABLE, name):
            op.create_index(name, TABLE, columns)


def downgrade():
    if not table_exists(TABLE):
        return
    for name in INDEXES:
        if index_exists(TABLE, name):
            op.drop_index(name, table_name=TABLE)
    if column_exists(TABLE, "model_name_digest"):
        op.drop_column(TABLE, "model_name_digest")

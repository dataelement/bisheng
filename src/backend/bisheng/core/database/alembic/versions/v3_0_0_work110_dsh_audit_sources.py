"""Optional request provenance and independently encrypted message annotations."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists, table_exists
from bisheng.core.database.dialect_helpers import JsonType

revision = "f062_work110_audit_sources"
down_revision = "f062_work110_audit_lookup"
branch_labels = None
depends_on = None
TABLE = "dsh_model_audit_request"
INDEX = "ix_dma_request_sources"


def upgrade():
    if not table_exists(TABLE):
        return
    columns = [
        sa.Column("session_origin", sa.String(16), nullable=True),
        sa.Column("parent_conversation_id", sa.String(1024), nullable=True),
        sa.Column("message_sources_status", sa.String(16), nullable=False, server_default="NOT_PROVIDED"),
        sa.Column("message_sources_ref", JsonType, nullable=True),
    ]
    for column in columns:
        if not column_exists(TABLE, column.name):
            op.add_column(TABLE, column)
    if not index_exists(TABLE, INDEX):
        op.create_index(INDEX, TABLE, ["tenant_id", "message_sources_status", "started_at", "request_id"])


def downgrade():
    # Application rollback retains optional provenance and encrypted references.
    pass

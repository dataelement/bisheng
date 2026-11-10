"""Widen hosted artifact and transfer byte counters on existing installations."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import get_column_type

revision = "f130_cloud_workbenches"
down_revision = "dsh_idle_sessions"
branch_labels = None
depends_on = None


def widen_existing_byte_counters():
    """Preserve large artifacts when an environment already has runtime tables."""
    conn = op.get_bind()
    for table, column in (("runtime_artifact", "size_bytes"), ("runtime_transfer", "offset")):
        if not table_exists(table) or not column_exists(table, column):
            continue
        kind = (get_column_type(conn, table, column) or "").lower()
        if kind in {"bigint", "biginteger"}:
            continue
        if kind not in {"int", "integer"}:
            raise RuntimeError(f"Unexpected byte-counter column type: {table}.{column}")
        op.alter_column(table, column, type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=False)


def upgrade():
    widen_existing_byte_counters()


def downgrade():
    # Large released artifacts cannot safely be narrowed back to 32-bit counters.
    pass

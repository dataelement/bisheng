"""Widen byte counters for 2 GiB artifacts and 10 GiB SQLite snapshots.

Revision ID: f086_runtime_byte_counters
Revises: merge_vibe_f077_heads
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import get_column_type

revision = "f086_runtime_byte_counters"
down_revision = "merge_vibe_f077_heads"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    for table, column in (("runtime_artifact", "size_bytes"), ("runtime_transfer", "offset")):
        if not table_exists(table) or not column_exists(table, column):
            continue
        kind = (get_column_type(conn, table, column) or "").lower()
        if kind in {"bigint", "biginteger"}:
            continue
        if kind not in {"int", "integer"}:
            raise RuntimeError(f"Unexpected byte-counter column type: {table}.{column}")
        op.alter_column(
            table,
            column,
            type_=sa.BigInteger(),
            existing_type=sa.Integer(),
            existing_nullable=False,
        )


def downgrade():
    # Retain the wider storage type: narrowing could corrupt already stored
    # multi-GiB counters, and older ORM Integer fields can read BIGINT values.
    pass

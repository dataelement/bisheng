"""Enforce one shared-storage routing row per tenant.

Revision ID: f099_shared_storage_routing_unique
Revises: f098_repair_dangling_predecessor
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f099_shared_storage_routing_unique"
down_revision = "f098_repair_dangling_predecessor"
branch_labels = None
depends_on = None

_TABLE = "knowledge_space_shared_storage_routing"
_TENANT_INDEX = "ix_knowledge_space_shared_storage_routing_tenant"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return

    duplicate = bind.execute(
        sa.text(
            f"SELECT tenant_id, COUNT(*) AS row_count FROM {_TABLE} "
            "GROUP BY tenant_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "cannot enforce shared-storage routing uniqueness: "
            f"tenant {duplicate[0]} has {duplicate[1]} rows"
        )

    indexes = {item["name"]: item for item in inspector.get_indexes(_TABLE)}
    unique_columns = {
        tuple(item.get("column_names") or ())
        for item in indexes.values()
        if item.get("unique")
    }
    unique_columns.update(
        tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints(_TABLE)
    )
    if ("tenant_id",) in unique_columns:
        return
    if _TENANT_INDEX in indexes:
        op.drop_index(_TENANT_INDEX, table_name=_TABLE)
    op.create_index(_TENANT_INDEX, _TABLE, ["tenant_id"], unique=True)


def downgrade() -> None:
    """Keep the uniqueness invariant; older code is compatible with it."""

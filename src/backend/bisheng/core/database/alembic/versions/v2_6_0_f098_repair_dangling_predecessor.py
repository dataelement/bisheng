"""F098: repair dangling publish-chain predecessor pointers.

Retiring a knowledge space used to mark its publish entries for deletion
without relinking the chain first, so the projection worker eventually removed
rows that documents (and other entries) still pointed at. A document left
pointing at a missing row can no longer be deleted at all: walking the chain
raises "predecessor chain is incomplete" and the delete is refused forever.

The predecessor of a row that no longer exists is unknowable, so the pointer is
cleared rather than re-targeted. NULL is the honest answer — it means "the
chain ends here", which makes a later manager delete fall through to a final
delete instead of erroring out.

Revision ID: f098_repair_dangling_predecessor
Revises: f097_merge_shared_storage_points_heads
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f098_repair_dangling_predecessor"
down_revision = "f097_merge_shared_storage_points_heads"
branch_labels = None
depends_on = None

_BATCH_SIZE = 500


def _dangling_ids(bind, table: str) -> list[int]:
    """Rows whose predecessor pointer names a knowledgefile row that is gone."""
    result = bind.execute(
        sa.text(
            f"SELECT t.id FROM {table} t "
            "LEFT JOIN knowledgefile f ON f.id = t.predecessor_logic_file_id "
            "WHERE t.predecessor_logic_file_id IS NOT NULL AND f.id IS NULL"
        )
    )
    return [int(row[0]) for row in result.fetchall()]


def _clear_pointers(bind, table: str, ids: list[int]) -> None:
    for start in range(0, len(ids), _BATCH_SIZE):
        batch = ids[start : start + _BATCH_SIZE]
        statement = sa.text(
            f"UPDATE {table} SET predecessor_logic_file_id = NULL "
            "WHERE id IN :ids"
        ).bindparams(sa.bindparam("ids", expanding=True))
        bind.execute(statement, {"ids": batch})


def upgrade() -> None:
    bind = op.get_bind()
    for table in ("knowledge_document", "knowledgefile"):
        ids = _dangling_ids(bind, table)
        if ids:
            _clear_pointers(bind, table, ids)


def downgrade() -> None:
    """No-op: the removed pointers referenced rows that no longer exist."""

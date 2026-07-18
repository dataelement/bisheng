"""F035: relax linsight status columns from native ENUM to VARCHAR.

The ``status`` columns of ``linsight_session_version`` and
``linsight_execute_task`` were created (via SQLModel ``create_all``) as a native
MySQL ``ENUM(...)`` whose allowed set is frozen at table-creation time. The HITL
park-and-release feature added a new value ``WAITING_FOR_USER_INPUT`` later, so
on already-deployed DBs writing that value fails with::

    (1265, "Data truncated for column 'status' at row 1")

Convert both columns to a plain ``VARCHAR(50)`` (no ENUM / CHECK) so current and
future status names are accepted. Storage stays the enum NAME, so existing rows
remain valid — this is a widening, no data backfill needed.

Note (DM8): if a deployment created these columns as VARCHAR + CHECK constraint
(SQLAlchemy's non-native ENUM fallback), the CHECK may need dropping manually;
MySQL native ENUM is replaced wholesale by the MODIFY below.

Revision ID: f035_linsight_status_varchar
Revises: f035_linsight_knowledge_ids
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = "f035_linsight_status_varchar"
down_revision: Union[str, Sequence[str], None] = "f035_linsight_knowledge_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column) pairs whose enum status must accept WAITING_FOR_USER_INPUT.
_TARGETS = (
    ("linsight_session_version", "status"),
    ("linsight_execute_task", "status"),
)


def upgrade() -> None:
    conn = op.get_bind()
    for table, column in _TARGETS:
        if column_exists(conn, table, column):
            op.alter_column(
                table,
                column,
                type_=sa.String(length=50),
                existing_nullable=False,
            )


def downgrade() -> None:
    # No-op: re-freezing the column to a native ENUM would re-introduce the bug
    # and risks rejecting rows holding the newer status value. Leave as VARCHAR.
    pass

"""F017: add ``is_shared`` column to 5 shareable resources — tenant-shared-storage.

Revision ID: f017_is_shared
Revises: f014_sso_sync_fields
Create Date: 2026-04-20

Changes:
  - ALTER knowledge, flow, assistant, channel, t_gpts_tools:
    add ``is_shared TINYINT NOT NULL DEFAULT 0``.

    The column is the persistent flip-side of the FGA ``shared_with`` tuples
    written by ``ResourceShareService.enable_sharing`` (F017 T03): while FGA
    is the authority for *access* decisions, the DB column exists so the UI
    can render a "集团共享" Badge without issuing an FGA read per row, and
    so list/count queries can filter by share state cheaply.

Two layers — DB flag and FGA tuples — must stay in sync. The share-toggle
API (T07) writes both in the same transactional path.

Idempotent: checks for the column before adding, consistent with F011/F012
helper pattern.

Tool table physical name is ``t_gpts_tools`` (prefix per tool domain), not
``gpts_tools``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = 'f017_is_shared'
down_revision: Union[str, Sequence[str], None] = 'f014_sso_sync_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SHAREABLE_TABLES: list[str] = [
    'knowledge',
    'flow',
    'assistant',
    'channel',
    # FGA owner_tuple writes `tool:{gpts_tool_type.id}` (see
    # tool/domain/services/tool.py:add_gpts_tools_hook), so the is_shared
    # flag lives on the tool-type table, not the tool-instance table.
    't_gpts_tools_type',
]

def upgrade() -> None:
    conn = op.get_bind()
    for table in _SHAREABLE_TABLES:
        if not column_exists(conn, table, 'is_shared'):
            op.add_column(
                table,
                sa.Column(
                    'is_shared',
                    sa.Boolean,
                    nullable=False,
                    server_default=sa.text('0'),
                    comment='F017: Root resource shared to all children (DB flag mirroring FGA shared_with tuples)',
                ),
            )

def downgrade() -> None:
    conn = op.get_bind()
    for table in _SHAREABLE_TABLES:
        if column_exists(conn, table, 'is_shared'):
            op.drop_column(table, 'is_shared')

"""Allow duplicate user_name; person_id (external_id) remains unique per source.

Revision ID: f010_user_name_nonunique
Revises: f009_org_sync
Create Date: 2026-04-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f010_user_name_nonunique'
down_revision: Union[str, Sequence[str], None] = 'f009_org_sync'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            'SELECT COUNT(*) FROM information_schema.TABLES '
            'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t',
        ),
        {'t': table_name},
    )
    return result.scalar() > 0


def upgrade() -> None:
    """Drop UNIQUE on user.user_name; keep a non-unique index for lookup."""
    if not _table_exists('user'):
        return
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT DISTINCT INDEX_NAME, NON_UNIQUE
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'user'
              AND COLUMN_NAME = 'user_name'
              AND INDEX_NAME != 'PRIMARY'
            """,
        ),
    ).fetchall()
    for index_name, non_unique in rows:
        if int(non_unique) == 0:
            op.drop_index(index_name, table_name='user')
    # Recreate plain index if none remains on user_name
    has_any = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'user'
              AND COLUMN_NAME = 'user_name'
              AND INDEX_NAME != 'PRIMARY'
            """,
        ),
    ).scalar()
    if not has_any:
        op.create_index('ix_user_user_name', 'user', ['user_name'], unique=False)


def downgrade() -> None:
    """Cannot safely restore UNIQUE if duplicates exist; only ensure index exists."""
    if not _table_exists('user'):
        return
    conn = op.get_bind()
    has_any = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'user'
              AND COLUMN_NAME = 'user_name'
              AND INDEX_NAME != 'PRIMARY'
            """,
        ),
    ).scalar()
    if not has_any:
        op.create_index('ix_user_user_name', 'user', ['user_name'], unique=False)

"""Allow duplicate user_name; person_id (external_id) remains unique per source.

Revision ID: f010_user_name_nonunique
Revises: f009_org_sync
Create Date: 2026-04-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import table_exists, get_indexes_for_column

revision: str = 'f010_user_name_nonunique'
down_revision: Union[str, Sequence[str], None] = 'f009_org_sync'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop UNIQUE on user.user_name; keep a non-unique index for lookup."""
    conn = op.get_bind()
    if not table_exists(conn, 'user'):
        return

    for idx in get_indexes_for_column(conn, 'user', 'user_name'):
        if idx.get('unique'):
            op.drop_index(idx['name'], table_name='user')

    if not get_indexes_for_column(conn, 'user', 'user_name'):
        op.create_index('ix_user_user_name', 'user', ['user_name'], unique=False)


def downgrade() -> None:
    """Cannot safely restore UNIQUE if duplicates exist; only ensure index exists."""
    conn = op.get_bind()
    if not table_exists(conn, 'user'):
        return

    if not get_indexes_for_column(conn, 'user', 'user_name'):
        op.create_index('ix_user_user_name', 'user', ['user_name'], unique=False)

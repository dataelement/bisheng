"""F045: add guid field to user table for SG SSO account sync.

Revision ID: f045_user_guid
Revises: f044_developer_token
Create Date: 2026-06-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, index_exists

revision: str = 'f045_user_guid'
down_revision: Union[str, Sequence[str], None] = 'f044_developer_token'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'user', 'guid'):
        op.add_column(
            'user',
            sa.Column(
                'guid',
                sa.String(length=64),
                nullable=True,
                comment='SSO account GUID',
            ),
        )
    if not index_exists(conn, 'user', 'ix_user_guid'):
        op.create_index('ix_user_guid', 'user', ['guid'])


def downgrade() -> None:
    conn = op.get_bind()
    if index_exists(conn, 'user', 'ix_user_guid'):
        op.drop_index('ix_user_guid', table_name='user')
    if column_exists(conn, 'user', 'guid'):
        op.drop_column('user', 'guid')


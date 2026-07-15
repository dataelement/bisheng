"""F056: add wechat_user_id field to user table for Enterprise WeChat message push.

Revision ID: f056_user_wechat_user_id
Revises: f055_message_citation_relation
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, index_exists

revision: str = 'f056_user_wechat_user_id'
down_revision: Union[str, Sequence[str], None] = 'f055_message_citation_relation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'user', 'wechat_user_id'):
        op.add_column(
            'user',
            sa.Column(
                'wechat_user_id',
                sa.String(length=256),
                nullable=True,
                comment='Enterprise WeChat user ID for message push',
            ),
        )
    if not index_exists(conn, 'user', 'ix_user_wechat_user_id'):
        op.create_index('ix_user_wechat_user_id', 'user', ['wechat_user_id'])


def downgrade() -> None:
    conn = op.get_bind()
    if index_exists(conn, 'user', 'ix_user_wechat_user_id'):
        op.drop_index('ix_user_wechat_user_id', table_name='user')
    if column_exists(conn, 'user', 'wechat_user_id'):
        op.drop_column('user', 'wechat_user_id')

"""F012: User.token_version for JWT invalidation — v2.5.1 tenant-resolver.

Revision ID: f012_user_token_version
Revises: f011_tenant_tree
Create Date: 2026-04-19

Changes:
  - ALTER user: add token_version INT NOT NULL DEFAULT 0.
    The column is incremented whenever a user's leaf tenant changes
    (``UserTenantSyncService.sync_user``) so that issued JWTs carrying a
    stale version are rejected by the middleware with a 401.

Idempotent: checks for the column before adding, consistent with F011's
helper pattern.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f012_user_token_version'
down_revision: Union[str, Sequence[str], None] = 'f011_tenant_tree'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.COLUMNS '
        'WHERE TABLE_SCHEMA = DATABASE() '
        '  AND TABLE_NAME = :t AND COLUMN_NAME = :c'
    ), {'t': table, 'c': column})
    return result.scalar() > 0


def upgrade() -> None:
    if not _column_exists('user', 'token_version'):
        op.add_column(
            'user',
            sa.Column(
                'token_version',
                sa.Integer,
                nullable=False,
                server_default='0',
                comment='v2.5.1 F012: JWT invalidation counter; +1 on leaf tenant change',
            ),
        )


def downgrade() -> None:
    if _column_exists('user', 'token_version'):
        op.drop_column('user', 'token_version')

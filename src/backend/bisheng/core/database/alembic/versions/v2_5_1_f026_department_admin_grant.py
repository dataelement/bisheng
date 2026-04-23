"""F026: department_admin_grant — SSO vs manual department admin markers.

Revision ID: f026_department_admin_grant
Revises: f025_merge_f024_heads
Create Date: 2026-04-23

Lets ``LoginSyncService`` revoke OpenFGA ``department#admin`` only when the
grant was created by SSO (WeCom leader); management UI grants stay ``manual``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f026_department_admin_grant'
down_revision: Union[str, Sequence[str], None] = 'f025_merge_f024_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.TABLES '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t'
    ), {'t': name})
    return result.scalar() > 0


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        'SELECT COUNT(*) FROM information_schema.STATISTICS '
        'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND INDEX_NAME = :i'
    ), {'t': table_name, 'i': index_name})
    return result.scalar() > 0


def upgrade() -> None:
    if not _table_exists('department_admin_grant'):
        op.create_table(
            'department_admin_grant',
            sa.Column(
                'id', sa.BigInteger, primary_key=True, autoincrement=True,
            ),
            sa.Column(
                'user_id', sa.Integer,
                sa.ForeignKey('user.user_id', ondelete='CASCADE'),
                nullable=False,
            ),
            sa.Column(
                'department_id', sa.Integer,
                sa.ForeignKey('department.id', ondelete='CASCADE'),
                nullable=False,
            ),
            sa.Column(
                'grant_source', sa.String(16), nullable=False,
                comment='sso | manual',
            ),
            sa.UniqueConstraint(
                'user_id', 'department_id',
                name='uk_dept_admin_grant_user_dept',
            ),
        )
    if not _index_exists('department_admin_grant', 'idx_dag_user_id'):
        op.create_index(
            'idx_dag_user_id', 'department_admin_grant', ['user_id'],
        )
    if not _index_exists('department_admin_grant', 'idx_dag_department_id'):
        op.create_index(
            'idx_dag_department_id', 'department_admin_grant',
            ['department_id'],
        )


def downgrade() -> None:
    if _table_exists('department_admin_grant'):
        if _index_exists('department_admin_grant', 'idx_dag_user_id'):
            op.drop_index(
                'idx_dag_user_id', table_name='department_admin_grant',
            )
        if _index_exists('department_admin_grant', 'idx_dag_department_id'):
            op.drop_index(
                'idx_dag_department_id', table_name='department_admin_grant',
            )
        op.drop_table('department_admin_grant')

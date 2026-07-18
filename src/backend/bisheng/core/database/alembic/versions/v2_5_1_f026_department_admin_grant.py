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

from bisheng.core.database.dialect_helpers import index_exists, table_exists

revision: str = 'f026_department_admin_grant'
down_revision: Union[str, Sequence[str], None] = 'f025_merge_f024_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, 'department_admin_grant'):
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
    if not index_exists(conn, 'department_admin_grant', 'idx_dag_user_id'):
        op.create_index(
            'idx_dag_user_id', 'department_admin_grant', ['user_id'],
        )
    if not index_exists(conn, 'department_admin_grant', 'idx_dag_department_id'):
        op.create_index(
            'idx_dag_department_id', 'department_admin_grant',
            ['department_id'],
        )

def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, 'department_admin_grant'):
        if index_exists(conn, 'department_admin_grant', 'idx_dag_user_id'):
            op.drop_index(
                'idx_dag_user_id', table_name='department_admin_grant',
            )
        if index_exists(conn, 'department_admin_grant', 'idx_dag_department_id'):
            op.drop_index(
                'idx_dag_department_id', table_name='department_admin_grant',
            )
        op.drop_table('department_admin_grant')

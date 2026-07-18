"""F024: add ``role.create_user`` and backfill from role audit logs.

Revision ID: f024_role_creator
Revises: f023_department_admin_membership_overlay
Create Date: 2026-04-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = 'f024_role_creator'
down_revision: Union[str, Sequence[str], None] = 'f023_department_admin_membership_overlay'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def _backfill_role_creator_from_auditlog() -> None:
    """Set ``role.create_user`` from the first ``create_role`` auditlog row.

    Implemented in Python via SQLAlchemy expression language to be portable
    across MySQL and DM8:
      - Multi-table ``UPDATE...JOIN`` is MySQL-specific (DM8 follows Oracle).
      - ``CAST(... AS UNSIGNED)`` is a MySQL type alias; we filter the
        numeric-string rows in Python and rely on ``int()`` instead.
      - ``REGEXP`` is replaced with a portable digit check ``isdigit()``.
    """
    conn = op.get_bind()
    role_tbl = sa.Table('role', sa.MetaData(), autoload_with=conn)
    auditlog_tbl = sa.Table('auditlog', sa.MetaData(), autoload_with=conn)

    # Pull the earliest create_role row per object_id.
    rows = conn.execute(
        sa.select(
            auditlog_tbl.c.object_id,
            auditlog_tbl.c.operator_id,
            auditlog_tbl.c.create_time,
            auditlog_tbl.c.id,
        )
        .where(
            auditlog_tbl.c.system_id == 'system',
            auditlog_tbl.c.event_type == 'create_role',
            auditlog_tbl.c.object_type == 'role_conf',
        )
        .order_by(
            auditlog_tbl.c.object_id.asc(),
            auditlog_tbl.c.create_time.asc(),
            auditlog_tbl.c.id.asc(),
        )
    ).fetchall()

    creator_by_role: dict[int, int] = {}
    for row in rows:
        oid = row.object_id
        if not (oid and str(oid).isdigit()):
            continue
        role_id = int(oid)
        # First row wins thanks to ORDER BY; skip subsequent ones.
        creator_by_role.setdefault(role_id, row.operator_id)

    for role_id, creator_id in creator_by_role.items():
        conn.execute(
            sa.update(role_tbl)
            .where(
                role_tbl.c.id == role_id,
                role_tbl.c.create_user.is_(None),
            )
            .values(create_user=creator_id)
        )

def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'role', 'create_user'):
        op.add_column(
            'role',
            sa.Column('create_user', sa.Integer(), nullable=True, comment='Role creator user ID'),
        )

    if table_exists(conn, 'auditlog') and column_exists(conn, 'role', 'create_user'):
        _backfill_role_creator_from_auditlog()

def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, 'role', 'create_user'):
        op.drop_column('role', 'create_user')

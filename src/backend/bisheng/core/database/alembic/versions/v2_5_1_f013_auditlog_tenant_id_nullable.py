"""F013: Relax auditlog.tenant_id to NULL-able.

Revision ID: f013_auditlog_tenant_id_nullable
Revises: f012_merge_heads
Create Date: 2026-04-19

Background:
  F001 multi-tenant migration added ``tenant_id INT NOT NULL DEFAULT 1`` to
  every business table, including ``auditlog``. F014/F015 later updated the
  ``AuditLog`` ORM model to ``Optional[int]`` with ``nullable=True`` —
  reflecting that audit events can be system-level (login, config change)
  without a target tenant — but shipped no ``ALTER`` to the DB.

  The mismatch breaks user login on any DB upgraded from v2.5.0:
  ``AuditLogService.user_login`` builds ``AuditLog(tenant_id=None, ...)``,
  SQLAlchemy emits explicit ``NULL`` (bypassing the DB default 1), and
  MySQL rejects with error 1048 "Column 'tenant_id' cannot be null" — the
  login endpoint returns 500 even though password check and token_version
  refresh already succeeded.

Scope:
  Only ``auditlog.tenant_id`` is touched. Other business tables keep
  ``tenant_id NOT NULL DEFAULT 1`` — they describe tenant-owned resources
  and the F001 constraint is correct for them. ``auditlog`` is the
  exception because it also records tenant-free system events.

Idempotent: checks current nullability via Inspector before ALTER.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, is_column_nullable

revision: str = 'f013_auditlog_tenant_id_nullable'
down_revision: Union[str, Sequence[str], None] = 'f012_merge_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'auditlog', 'tenant_id'):
        return
    if is_column_nullable(conn, 'auditlog', 'tenant_id'):
        return
    op.alter_column('auditlog', 'tenant_id', nullable=True, existing_type=sa.Integer())


def downgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, 'auditlog', 'tenant_id'):
        return
    # Backfill NULL rows before re-adding NOT NULL constraint.
    auditlog = sa.Table('auditlog', sa.MetaData(), autoload_with=conn)
    conn.execute(
        sa.update(auditlog).where(auditlog.c.tenant_id.is_(None)).values(tenant_id=1)
    )
    op.alter_column(
        'auditlog', 'tenant_id',
        nullable=False,
        existing_type=sa.Integer(),
        server_default=sa.text('1'),
    )

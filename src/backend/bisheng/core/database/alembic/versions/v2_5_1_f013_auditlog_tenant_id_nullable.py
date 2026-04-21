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

Idempotent: checks current nullability via information_schema before ALTER.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f013_auditlog_tenant_id_nullable'
down_revision: Union[str, Sequence[str], None] = 'f012_merge_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_nullable(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            SELECT IS_NULLABLE FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :t
              AND COLUMN_NAME = :c
            """
        ),
        {'t': table, 'c': column},
    )
    row = result.first()
    return row is not None and row[0] == 'YES'


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :t
              AND COLUMN_NAME = :c
            """
        ),
        {'t': table, 'c': column},
    )
    return result.scalar() > 0


def upgrade() -> None:
    if not _column_exists('auditlog', 'tenant_id'):
        return
    if _is_nullable('auditlog', 'tenant_id'):
        return
    op.execute(
        sa.text('ALTER TABLE auditlog MODIFY COLUMN tenant_id INT NULL')
    )


def downgrade() -> None:
    if not _column_exists('auditlog', 'tenant_id'):
        return
    # Downgrade would require the column to be NOT NULL with a default.
    # Backfill NULL rows to 1 first, then re-add the constraint.
    op.execute(
        sa.text('UPDATE auditlog SET tenant_id = 1 WHERE tenant_id IS NULL')
    )
    op.execute(
        sa.text("ALTER TABLE auditlog MODIFY COLUMN tenant_id INT NOT NULL DEFAULT 1")
    )

"""F012: Backfill user.external_id for local accounts.

Revision ID: f012_backfill_local_external_id
Revises: f011_backfill_create_knowledge_web_menu
Create Date: 2026-04-19

Background:
  Commit 94323e3ec (2026-04-17) changed the password-login query from
  ``User.user_name == account`` to ``User.external_id == account`` — aligned
  with F009's org-sync model where external_id is the stable identity — but
  did not ship a data migration for pre-existing local accounts. As a result,
  every row with ``source='local' AND external_id IS NULL`` (including the
  bootstrap admin) becomes unable to log in via password.

  This migration backfills ``external_id = user_name`` for local accounts,
  restoring password login. The ``uk_user_source_external_id`` unique
  constraint on ``(source, external_id)`` naturally inherits user_name's
  former uniqueness within ``source='local'``.

Scope:
  - Only ``source='local'`` and ``delete=0`` rows are touched.
  - Rows that already have a non-NULL external_id are left alone (idempotent).
  - SSO-synced rows (source='feishu'/'wecom'/...) are untouched — their
    external_id is the authoritative external employee ID.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f012_backfill_local_external_id'
down_revision: Union[str, Sequence[str], None] = 'f011_backfill_create_knowledge_web_menu'
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
    if not _table_exists('user'):
        return
    op.execute(
        sa.text(
            """
            UPDATE `user`
            SET external_id = user_name
            WHERE external_id IS NULL
              AND source = 'local'
              AND `delete` = 0
            """
        )
    )


def downgrade() -> None:
    # Intentional no-op: clearing external_id would re-break login for users
    # who have since logged in or been referenced by newer flows.
    pass

"""F049: user.user_type — principal type column for service accounts (v3.0.0).

Revision ID: f049_user_user_type
Revises: linsight_pending_files
Create Date: 2026-08-17

Changes:
  - ALTER user: add ``user_type VARCHAR(16) NOT NULL DEFAULT 'human'`` plus the
    ``ix_user_user_type`` index. ``'service'`` marks a service account
    (F049 D1: the service-account principal reuses the ``user`` table; its
    extra attributes live in the companion ``service_account`` table).
    VARCHAR, not CHAR — DM8 CHAR trailing-space stripping is a legacy patch
    (design K5).

Data effect: only the ``server_default`` backfill performed by the DDL itself
(AC-51 zero migration) — every existing row reads as ``'human'``; no row is
UPDATEd here.

Downgrade caveat: dropping the column turns every service-account row
(``user_type='service'``) into an ordinary, human-visible user row (they keep
``source='service_account'`` / ``external_id=NULL`` / the password sentinel).
Delete all service accounts through the management API before downgrading, or
accept that they reappear as regular users. Idempotent: guarded by
``column_exists`` / ``index_exists`` because ``create_all()`` may already have
produced the column on a fresh install.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, index_exists

revision: str = "f049_user_user_type"
down_revision: Union[str, Sequence[str], None] = "linsight_pending_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "user"
_COLUMN = "user_type"
_INDEX = "ix_user_user_type"


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(16),
                nullable=False,
                server_default="human",
                comment="v3.0.0 F049: principal type — human | service",
            ),
        )
    if not index_exists(conn, _TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, [_COLUMN], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if index_exists(conn, _TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if column_exists(conn, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)

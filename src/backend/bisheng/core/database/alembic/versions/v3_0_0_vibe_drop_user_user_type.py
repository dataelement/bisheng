"""vibe_drop_user_user_type — retire the vibe-era ``user.user_type`` column (v3.0.0).

Revision ID: vibe_drop_user_user_type
Revises: merge_update_time_default_heads
Create Date: 2026-09-10

Why:
  ``3.0-vibe``'s F049 modelled service accounts as rows of ``user`` tagged
  ``user_type='service'`` (``f049_user_user_type``). The release line's F053
  keeps them in their own ``service_account`` table instead (F053 design K15 /
  K17), and the application factory now runs on that base (migration plan
  M4 / M5). Two principal models on one table would give F048 subject
  resolution two truths, so the column goes.

  ``f049_user_user_type`` stays in the tree untouched: environments that
  followed the vibe line have it in ``alembic_version`` history, and deleting
  the file would leave alembic unable to locate them (M5). This revision is the
  additive inverse, mounted on the vibe chain's last head.

Changes:
  - DROP INDEX ``ix_user_user_type`` (created by the F049 revision or by
    ``create_all()`` on a vibe-era fresh install — same name either way).
  - ALTER user DROP COLUMN ``user_type``.

Data effect: none beyond the column removal itself. On the vibe line every
service-account row was already dropped together with the vibe-shaped
``service_account`` / ``api_credential`` tables (plan §4 step 2); a database
that never ran the vibe line has no column and this revision is a no-op.

Idempotent: both steps are guarded, and the index is dropped before the
column so DM8 never sees a column removal with a dependent index.

Downgrade re-adds the column with the F049 shape (``VARCHAR(16) NOT NULL
DEFAULT 'human'`` + index). Every row comes back as ``'human'`` — which is
the truth, since no service account lives in this table any more.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists

revision: str = "vibe_drop_user_user_type"
down_revision: str | Sequence[str] | None = "merge_update_time_default_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "user"
_COLUMN = "user_type"
_INDEX = "ix_user_user_type"


def upgrade() -> None:
    if index_exists(_TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if column_exists(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)


def downgrade() -> None:
    if not column_exists(_TABLE, _COLUMN):
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
    if not index_exists(_TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, [_COLUMN], unique=False)

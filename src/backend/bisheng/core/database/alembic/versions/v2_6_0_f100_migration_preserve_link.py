"""F100: migration batches can leave a shortcut at the source.

A batch created with this flag publishes each file up one level instead of
copying it, so the flag has to survive on the batch row — preflight and
execution both read it, and a retry days later must take the same path.

Existing batches default to false and behave exactly as before.

Revision ID: f100_migration_preserve_link
Revises: f099_shared_storage_routing_unique
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f100_migration_preserve_link"
down_revision = "f099_shared_storage_routing_unique"
branch_labels = None
depends_on = None

_TABLE = "knowledge_migration_batch"
_COLUMN = "preserve_link"


def _has_column(bind) -> bool:
    return _COLUMN in {
        column["name"] for column in sa.inspect(bind).get_columns(_TABLE)
    }


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind):
        return
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Publish each unit up one level and leave a shortcut at the source",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind):
        return
    op.drop_column(_TABLE, _COLUMN)

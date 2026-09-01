"""Add linsight_session_version.pending_files (deferred attachment ingestion).

Attachment ingestion moved out of the submit request and into the Linsight
worker: submit now only records the RAW submitted file refs here, and the worker
materializes them into ``files`` before the run starts. ``files`` therefore keeps
its contract (only fully-ingested entries), so every downstream reader
(_init_file_directory / prepare_file_list / the workspace drawer) is untouched.

Nullable for backward compatibility: rows written before this column existed read
as NULL, i.e. nothing pending. ``JsonType`` keeps MySQL/DM8 compatible.

Revision ID: linsight_pending_files
Revises: f048_migration_item_message_longtext
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, column_exists

revision: str = "linsight_pending_files"
down_revision: Union[str, Sequence[str], None] = "f048_migration_item_message_longtext"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "linsight_session_version"
_COLUMN = "pending_files"


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, _TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, JsonType, nullable=True, comment="Submitted file refs awaiting worker-side ingestion"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, _TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)

"""Add immutable original origin IDs to knowledge files.

Revision ID: f081_knowledge_file_original_origin
Revises: f080_portal_discovery_enabled
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f081_knowledge_file_original_origin"
down_revision: str | Sequence[str] | None = "f080_portal_discovery_enabled"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledgefile"
_COLUMNS = (
    (
        "original_uploader_id",
        "User ID that first uploaded the canonical business document",
    ),
    (
        "original_knowledge_id",
        "Knowledge space ID where the canonical business document was first uploaded",
    ),
)


def _has_column(bind, table: str, column: str) -> bool:
    return any(item["name"] == column for item in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    for column_name, comment in _COLUMNS:
        if not _has_column(bind, _TABLE, column_name):
            op.add_column(
                _TABLE,
                sa.Column(column_name, sa.Integer(), nullable=True, comment=comment),
            )


def downgrade() -> None:
    bind = op.get_bind()
    for column_name, _comment in reversed(_COLUMNS):
        if _has_column(bind, _TABLE, column_name):
            op.drop_column(_TABLE, column_name)

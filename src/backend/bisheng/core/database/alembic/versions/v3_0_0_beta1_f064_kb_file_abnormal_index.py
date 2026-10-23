"""F064: composite index for document-KB abnormal file lookup.

Revision ID: f064_kb_file_abnormal_index
Revises: f056_user_string_lengths
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op

from bisheng.core.database.alembic_helpers.online import index_exists

revision: str = "f064_kb_file_abnormal_index"
down_revision: str | Sequence[str] | None = "f056_user_string_lengths"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledgefile"
_INDEX = "ix_knowledgefile_kb_status_type"


def upgrade() -> None:
    if not index_exists(_TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, ["knowledge_id", "status", "file_type"])


def downgrade() -> None:
    if index_exists(_TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)

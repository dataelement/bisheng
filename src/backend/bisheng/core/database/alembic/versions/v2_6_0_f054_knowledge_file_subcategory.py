"""Add second-level file category fields to knowledgefile.

Revision ID: f054_knowledge_file_subcategory
Revises: f053_knowledge_file_similarity_candidates
Create Date: 2026-07-06
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import index_exists

revision: str = "f054_knowledge_file_subcategory"
down_revision: Union[str, Sequence[str], None] = "f053_knowledge_file_similarity_candidates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "knowledgefile"
_INDEX_FILE_SUBCATEGORY_CODE = "ix_knowledgefile_file_subcategory_code"


def upgrade() -> None:
    if not table_exists(_TABLE):
        return

    if not column_exists(_TABLE, "file_subcategory_code"):
        op.add_column(
            _TABLE,
            sa.Column(
                "file_subcategory_code",
                sa.String(length=16),
                nullable=True,
                comment="Second-level file category code for portal filtering.",
            ),
        )
    if not column_exists(_TABLE, "file_subcategory_source"):
        op.add_column(
            _TABLE,
            sa.Column(
                "file_subcategory_source",
                sa.String(length=16),
                nullable=True,
                comment="Second-level category assignment source.",
            ),
        )

    conn = op.get_bind()
    if not index_exists(conn, _TABLE, _INDEX_FILE_SUBCATEGORY_CODE):
        op.create_index(_INDEX_FILE_SUBCATEGORY_CODE, _TABLE, ["file_subcategory_code"], unique=False)


def downgrade() -> None:
    if not table_exists(_TABLE):
        return

    conn = op.get_bind()
    if index_exists(conn, _TABLE, _INDEX_FILE_SUBCATEGORY_CODE):
        op.drop_index(_INDEX_FILE_SUBCATEGORY_CODE, table_name=_TABLE)
    if column_exists(_TABLE, "file_subcategory_source"):
        op.drop_column(_TABLE, "file_subcategory_source")
    if column_exists(_TABLE, "file_subcategory_code"):
        op.drop_column(_TABLE, "file_subcategory_code")

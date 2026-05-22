"""F040: knowledge_space_tag_library.owner_knowledge_id for private libraries.

A private library is bound 1:1 to a knowledge space via owner_knowledge_id and
hidden from the tenant-admin tag library list. The auto-tag service still reads
the row by id, so its logic is unchanged.

Revision ID: f040_tag_library_owner_knowledge
Revises: f039_knowledge_document_tables
Create Date: 2026-05-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision: str = "f040_tag_library_owner_knowledge"
down_revision: Union[str, Sequence[str], None] = "f039_knowledge_document_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIBRARY_TABLE = "knowledge_space_tag_library"
_OWNER_COLUMN = "owner_knowledge_id"
_OWNER_INDEX = "ix_knowledge_space_tag_library_owner_knowledge_id"


def upgrade() -> None:
    if not table_exists(_LIBRARY_TABLE):
        return
    if not column_exists(_LIBRARY_TABLE, _OWNER_COLUMN):
        op.add_column(
            _LIBRARY_TABLE,
            sa.Column(
                _OWNER_COLUMN,
                sa.Integer(),
                nullable=True,
                comment="拥有该私有库的知识空间ID; NULL 表示租户公共库",
            ),
        )
        op.create_index(_OWNER_INDEX, _LIBRARY_TABLE, [_OWNER_COLUMN])


def downgrade() -> None:
    if not table_exists(_LIBRARY_TABLE):
        return
    if column_exists(_LIBRARY_TABLE, _OWNER_COLUMN):
        # Purge private libraries first so they do not leak into the admin
        # tag library list after the discriminator column is dropped.
        op.get_bind().execute(
            sa.text(f"DELETE FROM {_LIBRARY_TABLE} WHERE {_OWNER_COLUMN} IS NOT NULL")
        )
        op.drop_index(_OWNER_INDEX, table_name=_LIBRARY_TABLE)
        op.drop_column(_LIBRARY_TABLE, _OWNER_COLUMN)

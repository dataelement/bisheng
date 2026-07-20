"""F046: widen knowledge-file names from 200 to 500 characters.

The ``knowledgefile.file_name`` column stores both uploaded file names and
knowledge-space folder names. Widen it together with the SQLModel constraint so
names accepted by the application can be persisted on existing installations.

Revision ID: f046_knowledge_file_name_length
Revises: f045_dks_is_hidden
Create Date: 2026-07-16
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision: str = "f046_knowledge_file_name_length"
down_revision: Union[str, Sequence[str], None] = "f045_dks_is_hidden"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if column_exists("knowledgefile", "file_name"):
        op.alter_column(
            "knowledgefile",
            "file_name",
            existing_type=sa.String(length=200),
            type_=sa.String(length=500),
            existing_nullable=False,
        )


def downgrade() -> None:
    if column_exists("knowledgefile", "file_name"):
        op.alter_column(
            "knowledgefile",
            "file_name",
            existing_type=sa.String(length=500),
            type_=sa.String(length=200),
            existing_nullable=False,
        )

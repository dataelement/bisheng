"""Add qa_expert.major column.

Revision ID: f049_add_qa_expert_major
Revises: f048_add_knowledge_is_favorite
Create Date: 2026-06-29
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f049_add_qa_expert_major"
down_revision: Union[str, Sequence[str], None] = "f048_add_knowledge_is_favorite"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, "qa_expert"):
        return
    if not column_exists(conn, "qa_expert", "major"):
        op.add_column(
            "qa_expert",
            sa.Column(
                "major",
                sa.String(length=255),
                nullable=True,
                comment="Expert major",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, "qa_expert") and column_exists(conn, "qa_expert", "major"):
        op.drop_column("qa_expert", "major")

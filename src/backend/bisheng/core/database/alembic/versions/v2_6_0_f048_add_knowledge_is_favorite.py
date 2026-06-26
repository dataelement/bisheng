"""Add knowledge.is_favorite boolean flag for favorites collection.

Revision ID: f048_add_knowledge_is_favorite
Revises: f047_department_sync_parent_external_id
Create Date: 2026-06-26
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = "f048_add_knowledge_is_favorite"
down_revision: Union[str, Sequence[str], None] = "f047_department_sync_parent_external_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, "knowledge", "is_favorite"):
        op.add_column(
            "knowledge",
            sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, "knowledge", "is_favorite"):
        op.drop_column("knowledge", "is_favorite")

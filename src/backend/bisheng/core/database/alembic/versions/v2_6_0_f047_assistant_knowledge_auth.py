"""F041: add knowledge_auth toggle to assistant.

F041 gives the assistant app a「用户知识库权限校验」toggle (default OFF, preserving
current behavior). When ON, knowledge-space retrieval is filtered by the runtime
user's view_file; when OFF, by the config author's (assistant creator). Only affects
knowledge spaces (type=3); document / QA KB behavior is unchanged.

Revision ID: f047_assistant_knowledge_auth
Revises: f046_citation_access_scope
Create Date: 2026-07-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = "f047_assistant_knowledge_auth"
down_revision: Union[str, Sequence[str], None] = "f046_citation_access_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, "assistant", "knowledge_auth"):
        op.add_column(
            "assistant",
            sa.Column(
                "knowledge_auth",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
                comment="F041 用户知识库权限校验: ON=runtime user view_file / OFF=config author (default OFF)",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, "assistant", "knowledge_auth"):
        op.drop_column("assistant", "knowledge_auth")

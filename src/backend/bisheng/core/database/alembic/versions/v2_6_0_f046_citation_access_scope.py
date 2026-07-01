"""F041: add access_scope gate to message_citation.

F041 (knowledge-space select in flow / assistant) tags each citation with a
retrieval access gate so the resolve endpoint honors the same permission gate the
retrieval used:
  - 'per_user': strict F029 view_file filter (drop when the viewer lacks view_file).
  - 'shared'  : config-author-scoped (permission toggle OFF) — keep source metadata,
                but still gate full-file preview/download URLs by the viewer view_file.
Persisted so history resolve keeps the gate; legacy rows default to 'per_user' (strict).

Revision ID: f046_citation_access_scope
Revises: f045_dks_is_hidden
Create Date: 2026-07-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists

revision: str = "f046_citation_access_scope"
down_revision: Union[str, Sequence[str], None] = "f045_dks_is_hidden"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not column_exists(conn, "message_citation", "access_scope"):
        op.add_column(
            "message_citation",
            sa.Column(
                "access_scope",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'per_user'"),
                comment="F041 retrieval access gate: 'per_user' (F029 strict view_file) | "
                "'shared' (config-author-scoped, permission toggle OFF)",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if column_exists(conn, "message_citation", "access_scope"):
        op.drop_column("message_citation", "access_scope")

"""Add message-to-citation relations while keeping citation payloads unique.

Revision ID: f055_message_citation_relation
Revises: f054_knowledge_file_subcategory
Create Date: 2026-07-13
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import index_exists, table_exists

revision: str = "f055_message_citation_relation"
down_revision: Union[str, Sequence[str], None] = "f054_knowledge_file_subcategory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CITATION_TABLE = "message_citation"
_CHAT_MESSAGE_TABLE = "chatmessage"
_RELATION_TABLE = "message_citation_relation"

_INDEXES = {
    "ix_message_citation_relation_tenant_id": ["tenant_id"],
    "ix_message_citation_relation_message_id": ["message_id"],
    "ix_message_citation_relation_citation_id": ["citation_id"],
}


def _create_relation_table() -> None:
    op.create_table(
        _RELATION_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Tenant ID",
        ),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("citation_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "message_id",
            "citation_id",
            name="uq_msg_citation_rel_message_citation",
        ),
    )


def _backfill_relations(conn) -> None:
    if not table_exists(conn, _CITATION_TABLE):
        return

    if table_exists(conn, _CHAT_MESSAGE_TABLE):
        tenant_expression = "COALESCE(cm.tenant_id, 1)"
        chat_join = f"LEFT JOIN {_CHAT_MESSAGE_TABLE} cm ON cm.id = mc.message_id"
    else:
        tenant_expression = "1"
        chat_join = ""

    conn.execute(
        sa.text(
            f"""
            INSERT INTO {_RELATION_TABLE} (tenant_id, message_id, citation_id)
            SELECT {tenant_expression}, mc.message_id, mc.citation_id
            FROM {_CITATION_TABLE} mc
            {chat_join}
            WHERE NOT EXISTS (
                SELECT 1
                FROM {_RELATION_TABLE} rel
                WHERE rel.message_id = mc.message_id
                  AND rel.citation_id = mc.citation_id
            )
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _RELATION_TABLE):
        _create_relation_table()

    for index_name, columns in _INDEXES.items():
        if not index_exists(conn, _RELATION_TABLE, index_name):
            op.create_index(index_name, _RELATION_TABLE, columns, unique=False)

    _backfill_relations(conn)


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, _RELATION_TABLE):
        op.drop_table(_RELATION_TABLE)

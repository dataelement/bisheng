"""Add knowledge.business_domain_codes for portal domain bindings.

Revision ID: f050_knowledge_business_domain_codes
Revises: f049_add_qa_expert_major
Create Date: 2026-07-02
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, column_exists, table_exists

revision: str = "f050_knowledge_business_domain_codes"
down_revision: Union[str, Sequence[str], None] = "f049_add_qa_expert_major"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KNOWLEDGE_TABLE = "knowledge"
_COLUMN = "business_domain_codes"


def upgrade() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _KNOWLEDGE_TABLE):
        return
    if not column_exists(conn, _KNOWLEDGE_TABLE, _COLUMN):
        op.add_column(
            _KNOWLEDGE_TABLE,
            sa.Column(
                _COLUMN,
                JsonType(),
                nullable=True,
                comment="门户业务域编码列表，仅知识空间使用",
            ),
        )
    conn.execute(
        sa.text(
            f"""
            UPDATE {_KNOWLEDGE_TABLE}
            SET {_COLUMN} = :empty_codes
            WHERE type = 3 AND {_COLUMN} IS NULL
            """
        ),
        {"empty_codes": "[]"},
    )


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, _KNOWLEDGE_TABLE) and column_exists(conn, _KNOWLEDGE_TABLE, _COLUMN):
        op.drop_column(_KNOWLEDGE_TABLE, _COLUMN)

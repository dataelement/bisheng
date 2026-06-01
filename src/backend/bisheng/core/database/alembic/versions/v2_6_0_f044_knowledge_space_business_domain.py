"""F044: knowledge space business domain bindings.

Revision ID: f044_knowledge_space_business_domain
Revises: f038_merge_remaining_heads, f043_backfill_channel_membership_relation
Create Date: 2026-06-01
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import table_exists
from bisheng.core.database.dialect_helpers import index_exists

revision: str = "f044_knowledge_space_business_domain"
down_revision: Union[str, Sequence[str], None] = (
    "f038_merge_remaining_heads",
    "f043_backfill_channel_membership_relation",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "knowledge_space_business_domain"


def upgrade() -> None:
    if table_exists(_TABLE):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Tenant ID",
        ),
        sa.Column(
            "space_id",
            sa.Integer(),
            sa.ForeignKey("knowledge.id", ondelete="CASCADE"),
            nullable=False,
            comment="Knowledge space id",
        ),
        sa.Column("domain_code", sa.String(length=16), nullable=False, comment="业务域编码"),
        sa.Column(
            "created_by",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="创建人ID",
        ),
        sa.Column(
            "create_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "update_time",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("space_id", "domain_code", name="uk_ksbd_space_domain"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ksbd_tenant_domain", _TABLE, ["tenant_id", "domain_code"])
    op.create_index("idx_ksbd_space", _TABLE, ["space_id"])


def downgrade() -> None:
    if not table_exists(_TABLE):
        return
    conn = op.get_bind()
    if index_exists(conn, _TABLE, "idx_ksbd_tenant_domain"):
        op.drop_index("idx_ksbd_tenant_domain", table_name=_TABLE)
    if index_exists(conn, _TABLE, "idx_ksbd_space"):
        op.drop_index("idx_ksbd_space", table_name=_TABLE)
    op.drop_table(_TABLE)

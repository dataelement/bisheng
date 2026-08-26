# ruff: noqa: RUF002, RUF003
"""知识空间统一共享存储：租户路由表（F1.2，方案 §6.2/§6.3）。

新增 ``knowledge_space_shared_storage_routing`` 表，作为"某租户的 SPACE 存储
是否路由到共享 Milvus collection / ES index"的单一真相源。切换租户路由是
对单行的原子 ``UPDATE``，同时递增 ``routing_version`` 供各进程做灰度一致性
断言（风险 R16）。

DDL 全部为增量、镜像级向后兼容（方案 §6.3/§7.4）：新表对旧镜像完全不可见，
所有列可空或带 server_default，不修改任何既有表。

Revision ID: f090_space_shared_storage_routing
Revises: f089_points_last_earned_at
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    index_exists,
    table_exists,
)

revision: str = "f090_space_shared_storage_routing"
down_revision: str | Sequence[str] | None = "f089_points_last_earned_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge_space_shared_storage_routing"
_TENANT_INDEX = "ix_knowledge_space_shared_storage_routing_tenant"


def upgrade() -> None:
    connection = op.get_bind()
    if table_exists(connection, _TABLE):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Tenant ID (one row per tenant)",
        ),
        sa.Column(
            "shared_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Whether this tenant's SPACE storage is routed to the shared store",
        ),
        sa.Column(
            "routing_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Monotonic version; bumped on every routing switch",
        ),
        sa.Column(
            "write_frozen",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="TENANT_WRITE_FROZEN migration flag; SPACE writes fail closed while set",
        ),
        sa.Column(
            "collection_name",
            sa.String(255),
            nullable=True,
            comment="Shared Milvus collection name",
        ),
        sa.Column(
            "index_name",
            sa.String(255),
            nullable=True,
            comment="Shared ES index name",
        ),
        sa.Column(
            "embedding_model_id",
            sa.Integer(),
            nullable=True,
            comment="Tenant-wide target embedding model ID for shared SPACE storage",
        ),
        sa.Column(
            "schema_fingerprint",
            sa.String(128),
            nullable=True,
            comment="Schema fingerprint recorded at shared-store bootstrap time",
        ),
        sa.Column(
            "migration_state",
            sa.String(64),
            nullable=True,
            comment="Migration state machine label (F4); empty when not migrating",
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
            server_default=UPDATE_TIME_SERVER_DEFAULT,
        ),
    )
    if not index_exists(connection, _TABLE, _TENANT_INDEX):
        op.create_index(_TENANT_INDEX, _TABLE, ["tenant_id"], unique=True)


def downgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, _TABLE):
        return
    if index_exists(connection, _TABLE, _TENANT_INDEX):
        op.drop_index(_TENANT_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)

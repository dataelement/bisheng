"""F038: knowledge space auto tags.

Revision ID: f038_knowledge_space_auto_tags
Revises: f037_merge_f036_heads
Create Date: 2026-05-19
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import CLOB
from sqlalchemy.dialects import mysql

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision: str = "f038_knowledge_space_auto_tags"
down_revision: Union[str, Sequence[str], None] = "f037_merge_f036_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIBRARY_TABLE = "knowledge_space_tag_library"
_KNOWLEDGE_TABLE = "knowledge"
_BUILTIN_LIBRARY_NAME = "通用标签库"
_BUILTIN_TAGS = [
    "政策制度",
    "产品资料",
    "技术文档",
    "项目资料",
    "财务资料",
    "人力资源",
    "市场销售",
    "客户案例",
    "培训资料",
    "其他",
]


def _json_type():
    return sa.Text().with_variant(mysql.JSON(), "mysql").with_variant(CLOB(), "dm")


def _seed_builtin_libraries() -> None:
    if not table_exists("tenant"):
        return
    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO {_LIBRARY_TABLE}
                (tenant_id, name, description, tags, tag_count, is_builtin, user_id, create_time, update_time)
            SELECT
                t.id,
                :name,
                :description,
                :tags,
                :tag_count,
                1,
                0,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM tenant t
            WHERE NOT EXISTS (
                SELECT 1 FROM {_LIBRARY_TABLE} l
                WHERE l.tenant_id = t.id AND l.name = :name AND l.is_builtin = 1
            )
            """
        ),
        {
            "name": _BUILTIN_LIBRARY_NAME,
            "description": "系统内置的通用自动标签候选库，可复制后按业务场景调整。",
            "tags": json.dumps(_BUILTIN_TAGS, ensure_ascii=False),
            "tag_count": len(_BUILTIN_TAGS),
        },
    )


def upgrade() -> None:
    if not table_exists(_LIBRARY_TABLE):
        op.create_table(
            _LIBRARY_TABLE,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "tenant_id",
                sa.Integer,
                nullable=False,
                server_default=sa.text("1"),
                comment="租户ID",
            ),
            sa.Column(
                "name", sa.String(length=200), nullable=False, comment="标签库名称"
            ),
            sa.Column(
                "description",
                sa.String(length=1000),
                nullable=True,
                comment="标签库说明",
            ),
            sa.Column("tags", _json_type(), nullable=False, comment="标签列表"),
            sa.Column(
                "tag_count",
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
                comment="标签数量",
            ),
            sa.Column(
                "is_builtin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
                comment="是否内置标签库",
            ),
            sa.Column(
                "user_id",
                sa.Integer,
                nullable=False,
                server_default=sa.text("0"),
                comment="创建人ID",
            ),
            sa.Column(
                "create_time",
                sa.DateTime,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "update_time",
                sa.DateTime,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )
        op.create_index(
            "ix_knowledge_space_tag_library_tenant_id", _LIBRARY_TABLE, ["tenant_id"]
        )
        op.create_index("ix_knowledge_space_tag_library_name", _LIBRARY_TABLE, ["name"])

    _seed_builtin_libraries()

    if table_exists(_KNOWLEDGE_TABLE):
        if not column_exists(_KNOWLEDGE_TABLE, "auto_tag_enabled"):
            op.add_column(
                _KNOWLEDGE_TABLE,
                sa.Column(
                    "auto_tag_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                    comment="是否启用自动标签",
                ),
            )
        if not column_exists(_KNOWLEDGE_TABLE, "auto_tag_library_id"):
            op.add_column(
                _KNOWLEDGE_TABLE,
                sa.Column(
                    "auto_tag_library_id",
                    sa.Integer(),
                    nullable=True,
                    comment="绑定的自动标签库ID",
                ),
            )
            op.create_index(
                "ix_knowledge_auto_tag_library_id",
                _KNOWLEDGE_TABLE,
                ["auto_tag_library_id"],
            )


def downgrade() -> None:
    if table_exists(_KNOWLEDGE_TABLE):
        if column_exists(_KNOWLEDGE_TABLE, "auto_tag_library_id"):
            op.drop_index(
                "ix_knowledge_auto_tag_library_id", table_name=_KNOWLEDGE_TABLE
            )
            op.drop_column(_KNOWLEDGE_TABLE, "auto_tag_library_id")
        if column_exists(_KNOWLEDGE_TABLE, "auto_tag_enabled"):
            op.drop_column(_KNOWLEDGE_TABLE, "auto_tag_enabled")
    if table_exists(_LIBRARY_TABLE):
        op.drop_index("ix_knowledge_space_tag_library_name", table_name=_LIBRARY_TABLE)
        op.drop_index(
            "ix_knowledge_space_tag_library_tenant_id", table_name=_LIBRARY_TABLE
        )
        op.drop_table(_LIBRARY_TABLE)

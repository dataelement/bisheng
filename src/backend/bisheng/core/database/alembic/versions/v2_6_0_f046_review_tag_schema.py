# ruff: noqa: RUF001
"""F046: 补齐审核标签与标签类型字段迁移。

Revision ID: f046_review_tag_schema
Revises: f045_user_guid
Create Date: 2026-06-18
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    UPDATE_TIME_SERVER_DEFAULT,
    JsonType,
    column_exists,
    constraint_exists,
    index_exists,
    is_column_nullable,
    table_exists,
)

revision: str = "f046_review_tag_schema"
down_revision: Union[str, Sequence[str], None] = "f045_user_guid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TAG_TABLE = "tag"
_LIBRARY_TABLE = "knowledge_space_tag_library"
_CONFIG_TABLE = "config"
_REVIEW_TAG_TABLE = "review_tag"
_REVIEW_TAG_LINK_TABLE = "review_tag_link"
_REVIEW_TAG_LINK_UNIQ = "resource_tag_uniq"

_WORKSTATION_KNOWLEDGE_SPACE_CONFIG = {
    "system_prompt": (
        "# 角色\n"
        "你是一个严谨的AI问答助手，你的任务是根据用户问题以及相关资料进行回答。\n"
        "在回答时，请注意以下几点：\n"
        "1. 请使用用户所使用的语言进行回答。\n"
        "2. 当【参考资料】中有明确与问题相关的信息时才进行回答，保持答案严谨、专业，"
        "不允许自行推测，在回答中标注参考资料出处。如果不同的参考来源有差异甚至冲突，"
        "则应都列举出来。\n"
        '3. 如果【参考资料】与用户问题无关，则回复“没有找到相关内容”或是“no content found"。\n'
        "4. 若文章内容中包含图片引用（例如：![image](路径/IMAGE_1.png)），请仍然使用 Markdown "
        "格式渲染图片，不要修改或删除。\n"
        "5. 当前时间是{cur_date}。"
    ),
    "user_prompt": "# 参考资料\n```\n{retrieved_file_content}\n```\n# 用户问题\n{question}",
    "max_chunk_size": 15000,
    "auto_tag_visible": True,
    "review_tag_visible": True,
}


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    conn = op.get_bind()
    if table_exists(conn, table_name) and not index_exists(conn, table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    conn = op.get_bind()
    if table_exists(conn, table_name) and index_exists(conn, table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    conn = op.get_bind()
    return constraint_exists(conn, table_name, constraint_name) or index_exists(conn, table_name, constraint_name)


def _drop_unique_constraint_if_exists(table_name: str, constraint_name: str) -> None:
    conn = op.get_bind()
    if not table_exists(conn, table_name):
        return
    if conn.dialect.name == "sqlite":
        return
    if constraint_exists(conn, table_name, constraint_name):
        op.drop_constraint(constraint_name, table_name, type_="unique")


def _add_tag_resource_type() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _TAG_TABLE):
        return
    if column_exists(conn, _TAG_TABLE, "resource_type"):
        return
    op.add_column(
        _TAG_TABLE,
        sa.Column(
            "resource_type",
            sa.String(length=60),
            nullable=False,
            server_default=sa.text("'manual_tag'"),
            comment="Resource Type",
        ),
    )


def _add_library_columns() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _LIBRARY_TABLE):
        return

    if not column_exists(conn, _LIBRARY_TABLE, "ai_tags"):
        op.add_column(
            _LIBRARY_TABLE,
            sa.Column("ai_tags", JsonType(), nullable=True, comment="AI生成的标签列表"),
        )
    if not column_exists(conn, _LIBRARY_TABLE, "ai_tag_count"):
        op.add_column(
            _LIBRARY_TABLE,
            sa.Column(
                "ai_tag_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
                comment="AI生成的标签数量",
            ),
        )
    if not column_exists(conn, _LIBRARY_TABLE, "resource_type"):
        op.add_column(
            _LIBRARY_TABLE,
            sa.Column(
                "resource_type",
                sa.String(length=60),
                nullable=False,
                server_default=sa.text("'manual_tag'"),
                comment="资源类型",
            ),
        )

    conn.execute(
        sa.text(f"UPDATE {_LIBRARY_TABLE} SET ai_tags = :empty_json WHERE ai_tags IS NULL"),
        {"empty_json": "[]"},
    )
    if conn.dialect.name != "sqlite" and is_column_nullable(conn, _LIBRARY_TABLE, "ai_tags"):
        op.alter_column(
            _LIBRARY_TABLE,
            "ai_tags",
            nullable=False,
            existing_type=JsonType(),
            existing_comment="AI生成的标签列表",
        )


def _update_workstation_knowledge_space_config() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _CONFIG_TABLE):
        return

    config = sa.table(
        _CONFIG_TABLE,
        sa.column("key", sa.String()),
        sa.column("value", sa.Text()),
    )
    conn.execute(
        sa.update(config)
        .where(config.c.key == "workstation_knowledge_space")
        .values(
            value=json.dumps(
                _WORKSTATION_KNOWLEDGE_SPACE_CONFIG,
                ensure_ascii=False,
            )
        )
    )


def _create_review_tag_table() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _REVIEW_TAG_TABLE):
        op.create_table(
            _REVIEW_TAG_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("business_type", sa.String(length=255), nullable=False),
            sa.Column("business_id", sa.String(length=36), nullable=True),
            sa.Column("user_id", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
                comment="Tenant ID",
            ),
            sa.Column(
                "resource_type",
                sa.String(length=60),
                nullable=False,
                server_default=sa.text("'manual_tag'"),
                comment="Resource Type",
            ),
            sa.Column("create_time", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime(), nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("review_status", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("reject_reason", sa.String(length=256), nullable=True),
            sa.Column("review_time", sa.DateTime(), nullable=True),
            sa.Column("remark", sa.String(length=256), nullable=True),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    _create_index_if_missing(_REVIEW_TAG_TABLE, "ix_tag_id", ["id"])
    _create_index_if_missing(_REVIEW_TAG_TABLE, "ix_tag_create_time", ["create_time"])
    _create_index_if_missing(_REVIEW_TAG_TABLE, "ix_tag_tenant_id", ["tenant_id"])
    _create_index_if_missing(_REVIEW_TAG_TABLE, "ix_tag_name", ["name"])
    _create_index_if_missing(_REVIEW_TAG_TABLE, "idx_tag_tenant_id", ["tenant_id"])


def _create_review_tag_link_table() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _REVIEW_TAG_LINK_TABLE):
        op.create_table(
            _REVIEW_TAG_LINK_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tag_id", sa.Integer(), nullable=False),
            sa.Column("resource_id", sa.String(length=255), nullable=False),
            sa.Column("resource_type", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "tenant_id",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
                comment="Tenant ID",
            ),
            sa.Column("create_time", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("update_time", sa.DateTime(), nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("remark", sa.String(length=256), nullable=True),
            sa.UniqueConstraint("resource_id", "resource_type", "tag_id", name=_REVIEW_TAG_LINK_UNIQ),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
        )

    _ensure_review_tag_link_unique_constraint()
    _create_index_if_missing(_REVIEW_TAG_LINK_TABLE, "ix_taglink_tenant_id", ["tenant_id"])
    _create_index_if_missing(_REVIEW_TAG_LINK_TABLE, "ix_taglink_tag_id", ["tag_id"])
    _create_index_if_missing(_REVIEW_TAG_LINK_TABLE, "ix_taglink_id", ["id"])
    _create_index_if_missing(_REVIEW_TAG_LINK_TABLE, "ix_taglink_create_time", ["create_time"])
    _create_index_if_missing(_REVIEW_TAG_LINK_TABLE, "idx_taglink_tenant_id", ["tenant_id"])


def _ensure_review_tag_link_unique_constraint() -> None:
    conn = op.get_bind()
    if not table_exists(conn, _REVIEW_TAG_LINK_TABLE):
        return
    if _unique_constraint_exists(_REVIEW_TAG_LINK_TABLE, _REVIEW_TAG_LINK_UNIQ):
        return

    duplicate = conn.execute(
        sa.text(
            f"""
            SELECT resource_id, resource_type, tag_id, COUNT(*) AS cnt
            FROM {_REVIEW_TAG_LINK_TABLE}
            GROUP BY resource_id, resource_type, tag_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "review_tag_link has duplicate resource_id/resource_type/tag_id rows; "
            "clean duplicates before adding resource_tag_uniq"
        )

    if conn.dialect.name != "sqlite":
        op.create_unique_constraint(
            _REVIEW_TAG_LINK_UNIQ,
            _REVIEW_TAG_LINK_TABLE,
            ["resource_id", "resource_type", "tag_id"],
        )


def upgrade() -> None:
    _add_tag_resource_type()
    _add_library_columns()
    _update_workstation_knowledge_space_config()
    _create_review_tag_table()
    _create_review_tag_link_table()


def downgrade() -> None:
    conn = op.get_bind()
    if table_exists(conn, _REVIEW_TAG_LINK_TABLE):
        _drop_unique_constraint_if_exists(_REVIEW_TAG_LINK_TABLE, _REVIEW_TAG_LINK_UNIQ)
        for index_name in (
            "idx_taglink_tenant_id",
            "ix_taglink_create_time",
            "ix_taglink_id",
            "ix_taglink_tag_id",
            "ix_taglink_tenant_id",
        ):
            _drop_index_if_exists(_REVIEW_TAG_LINK_TABLE, index_name)
        op.drop_table(_REVIEW_TAG_LINK_TABLE)

    if table_exists(conn, _REVIEW_TAG_TABLE):
        for index_name in (
            "idx_tag_tenant_id",
            "ix_tag_name",
            "ix_tag_tenant_id",
            "ix_tag_create_time",
            "ix_tag_id",
        ):
            _drop_index_if_exists(_REVIEW_TAG_TABLE, index_name)
        op.drop_table(_REVIEW_TAG_TABLE)

    if table_exists(conn, _LIBRARY_TABLE):
        if column_exists(conn, _LIBRARY_TABLE, "resource_type"):
            op.drop_column(_LIBRARY_TABLE, "resource_type")
        if column_exists(conn, _LIBRARY_TABLE, "ai_tag_count"):
            op.drop_column(_LIBRARY_TABLE, "ai_tag_count")
        if column_exists(conn, _LIBRARY_TABLE, "ai_tags"):
            op.drop_column(_LIBRARY_TABLE, "ai_tags")

    if table_exists(conn, _TAG_TABLE) and column_exists(conn, _TAG_TABLE, "resource_type"):
        op.drop_column(_TAG_TABLE, "resource_type")

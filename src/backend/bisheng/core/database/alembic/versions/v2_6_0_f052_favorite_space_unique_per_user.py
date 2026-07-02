"""Enforce one 『我的收藏』 favorite knowledge space per user (unique).

在 knowledge 表增加生成列 favorite_user_id = (is_favorite 时取 user_id，否则 NULL)，
并建唯一索引：NULL 可重复（普通空间不受约束），非 NULL 每个 user_id 至多一个，
从而在数据库层保证「每个用户至多一个收藏库」，根治并发懒创建可能产生的重复。

仅在 MySQL 上启用（首钢门户为 MySQL 8.0，生成列 + 唯一索引原生支持）；其它方言（如达梦）跳过。

Revision ID: f052_favorite_space_unique_per_user
Revises: f051_merge_f050_heads
Create Date: 2026-07-02
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

from bisheng.core.database.dialect_helpers import (
    column_exists,
    get_dialect_name,
    index_exists,
)

revision: str = "f052_favorite_space_unique_per_user"
down_revision: Union[str, Sequence[str], None] = "f051_merge_f050_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_knowledge_favorite_user"


def upgrade() -> None:
    conn = op.get_bind()
    if get_dialect_name(conn) != "mysql":
        return

    # 1) 去重：同一 user 若存在多个 is_favorite=1 的收藏库，保留 id 最小者，其余取消 is_favorite，
    #    以免建唯一索引时报冲突（当前数据每用户至多一个，此步一般为空操作）。
    op.execute(
        """
        UPDATE knowledge k
        JOIN (
            SELECT user_id, MIN(id) AS keep_id
            FROM knowledge
            WHERE is_favorite = 1
            GROUP BY user_id
            HAVING COUNT(*) > 1
        ) d ON k.user_id = d.user_id
        SET k.is_favorite = 0
        WHERE k.is_favorite = 1 AND k.id <> d.keep_id
        """
    )

    # 2) 生成列：is_favorite 时取 user_id，否则 NULL。
    if not column_exists(conn, "knowledge", "favorite_user_id"):
        op.execute(
            "ALTER TABLE knowledge "
            "ADD COLUMN favorite_user_id BIGINT "
            "GENERATED ALWAYS AS (CASE WHEN is_favorite = 1 THEN user_id END) STORED"
        )

    # 3) 唯一索引：每个用户至多一个收藏库。
    if not index_exists(conn, "knowledge", _INDEX_NAME):
        op.create_index(_INDEX_NAME, "knowledge", ["favorite_user_id"], unique=True)


def downgrade() -> None:
    conn = op.get_bind()
    if get_dialect_name(conn) != "mysql":
        return
    if index_exists(conn, "knowledge", _INDEX_NAME):
        op.drop_index(_INDEX_NAME, table_name="knowledge")
    if column_exists(conn, "knowledge", "favorite_user_id"):
        op.drop_column("knowledge", "favorite_user_id")

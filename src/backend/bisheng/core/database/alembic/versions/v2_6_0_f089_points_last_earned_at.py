# ruff: noqa: RUF002, RUF003
"""积分账户与排行快照增加最近获得时间，供首页榜同分排序。

Revision ID: f089_points_last_earned_at
Revises: f088_points_restore_pk_autoincrement
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f089_points_last_earned_at"
down_revision: str | Sequence[str] | None = "f088_points_restore_pk_autoincrement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind, table: str, column: str) -> bool:
    return any(item["name"] == column for item in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    """账户/快照加 last_earned_at；有流水时从 earn 回填账户字段。"""
    bind = op.get_bind()
    if _has_column(bind, "user_point_account", "last_earned_at") is False:
        op.add_column(
            "user_point_account",
            sa.Column(
                "last_earned_at",
                sa.DateTime(),
                nullable=True,
                comment="最近一次获得积分时间（仅 earn 更新；榜单同分排序用）",
            ),
        )
    if _has_column(bind, "point_rank_snapshot", "last_earned_at") is False:
        op.add_column(
            "point_rank_snapshot",
            sa.Column(
                "last_earned_at",
                sa.DateTime(),
                nullable=True,
                comment="刷榜时账户最近一次获得积分时间（同分排序；空则排后）",
            ),
        )
    if not (
        _has_column(bind, "user_point_account", "last_earned_at") and _has_column(bind, "user_point_log", "occurred_at")
    ):
        return
    dialect = bind.dialect.name
    if dialect in ("mysql", "mariadb"):
        # 回填：每用户最近一笔获得流水时间（direction=earn）。
        bind.execute(
            sa.text(
                """
                UPDATE user_point_account AS a
                INNER JOIN (
                    SELECT tenant_id, user_id, MAX(occurred_at) AS earned_at
                    FROM user_point_log
                    WHERE direction = 'earn'
                    GROUP BY tenant_id, user_id
                ) AS src
                    ON a.tenant_id = src.tenant_id AND a.user_id = src.user_id
                SET a.last_earned_at = src.earned_at
                WHERE a.last_earned_at IS NULL
                """
            )
        )
        return
    # 达梦等：相关子查询回填（无 MySQL JOIN UPDATE 语法）。
    bind.execute(
        sa.text(
            """
            UPDATE user_point_account
            SET last_earned_at = (
                SELECT MAX(occurred_at)
                FROM user_point_log
                WHERE user_point_log.tenant_id = user_point_account.tenant_id
                  AND user_point_log.user_id = user_point_account.user_id
                  AND user_point_log.direction = 'earn'
            )
            WHERE last_earned_at IS NULL
            """
        )
    )


def downgrade() -> None:
    """去掉最近获得时间列（榜单同分将回退为仅 user_id）。"""
    bind = op.get_bind()
    if _has_column(bind, "point_rank_snapshot", "last_earned_at"):
        op.drop_column("point_rank_snapshot", "last_earned_at")
    if _has_column(bind, "user_point_account", "last_earned_at"):
        op.drop_column("user_point_account", "last_earned_at")

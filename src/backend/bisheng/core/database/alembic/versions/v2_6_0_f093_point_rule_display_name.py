# ruff: noqa: RUF002
"""point_rule 增加 display_name：默认名 name 只读，展示名可运营修改。

Revision ID: f093_point_rule_display_name
Revises: f092_merge_points_display_name_heads

存量：display_name 先复制当前 name；再将 name 写回种子默认名（按 rule_code）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists
from bisheng.points.domain.constants.seed_rules import SEED_RULES

revision: str = "f093_point_rule_display_name"
down_revision: str | Sequence[str] | None = "f092_merge_points_display_name_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not table_exists(bind, "point_rule"):
        return
    if not column_exists(bind, "point_rule", "display_name"):
        op.add_column(
            "point_rule",
            sa.Column(
                "display_name",
                sa.String(40),
                nullable=True,
                comment="积分项展示名称（运营可改，列表与流水展示）",
            ),
        )
        bind.execute(sa.text("UPDATE point_rule SET display_name = name WHERE display_name IS NULL"))
        for rule in SEED_RULES:
            bind.execute(
                sa.text("UPDATE point_rule SET name = :default_name WHERE rule_code = :code"),
                {"default_name": rule["name"], "code": rule["rule_code"]},
            )
        op.alter_column("point_rule", "display_name", existing_type=sa.String(40), nullable=False)
    if column_exists(bind, "point_rule", "name"):
        try:
            op.alter_column(
                "point_rule",
                "name",
                existing_type=sa.String(40),
                nullable=False,
                comment="积分项默认名称（系统内置，运营不可改）",
            )
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    if table_exists(bind, "point_rule") and column_exists(bind, "point_rule", "display_name"):
        op.drop_column("point_rule", "display_name")

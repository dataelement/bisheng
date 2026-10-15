"""知识文档违规扣分: 补扣快照列, 并补种 R4-R6.

Revision ID: f116_knowledge_violation_deduct
Revises: f115_file_correction_scenario_seed

不覆盖已有规则的分值. 已存在的 R4-R6 行跳过.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists
from bisheng.points.domain.constants.seed_rules import SEED_RULES
from bisheng.points.domain.models import PointRule

revision: str = "f116_knowledge_violation_deduct"
down_revision: str | Sequence[str] | None = "f115_file_correction_scenario_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "point_pending_deduct"
_NEW_CODES = ("R4", "R5", "R6")


def _tenant_ids(bind) -> list[int]:
    """已有积分规则的租户. 表空时至少补租户 1."""
    rows = bind.execute(sa.text("SELECT DISTINCT tenant_id FROM point_rule")).fetchall()
    ids = sorted({int(row[0]) for row in rows})
    return ids or [1]


def upgrade() -> None:
    """加可空列并补种知识文档扣减规则."""
    bind = op.get_bind()
    if table_exists(bind, _TABLE):
        if not column_exists(bind, _TABLE, "scope_tier"):
            op.add_column(
                _TABLE,
                sa.Column(
                    "scope_tier",
                    sa.String(length=16),
                    nullable=True,
                    comment="知识文档扣分档位 public/department/team, 专家问答为空",
                ),
            )
        if not column_exists(bind, _TABLE, "score_snapshot"):
            op.add_column(
                _TABLE,
                sa.Column(
                    "score_snapshot",
                    sa.Integer(),
                    nullable=True,
                    comment="入队时已决定的扣分绝对值, 空则重试时按规则当前分值",
                ),
            )
    if not table_exists(bind, "point_rule"):
        return
    seeds = {row["rule_code"]: row for row in SEED_RULES if row["rule_code"] in _NEW_CODES}
    for tenant_id in _tenant_ids(bind):
        for code in _NEW_CODES:
            exists = bind.execute(
                sa.text("SELECT 1 FROM point_rule WHERE tenant_id = :tid AND rule_code = :code LIMIT 1"),
                {"tid": tenant_id, "code": code},
            ).first()
            if exists:
                continue
            rule = seeds[code]
            bind.execute(
                sa.insert(PointRule.__table__),
                [{"tenant_id": tenant_id, "remark": None, **rule}],
            )


def downgrade() -> None:
    """不删已种规则, 也不删可能已经写入的快照列."""
    pass

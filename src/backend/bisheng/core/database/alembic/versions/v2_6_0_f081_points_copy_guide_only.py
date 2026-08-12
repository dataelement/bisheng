"""point_copy 仅保留单条文案 guide。

Revision ID: f081_points_copy_guide_only
Revises: f080_points_rule_default_status

删除 earn_intro / deduct_intro 等历史多 key 行；若缺 guide 则按种子补种。
"""

from alembic import op
import sqlalchemy as sa

from bisheng.points.domain.constants.seed_rules import SEED_COPIES
from bisheng.points.domain.models.points import PointCopy

revision = "f081_points_copy_guide_only"
down_revision = "f080_points_rule_default_status"
branch_labels = None
depends_on = None

GUIDE_KEY = "guide"


def table_exists(bind, name: str) -> bool:
    """Cross-dialect table existence check."""
    return name in sa.inspect(bind).get_table_names()


def upgrade():
    """Drop non-guide copies; ensure each tenant has the guide seed row."""
    bind = op.get_bind()
    if not table_exists(bind, "point_copy"):
        return

    bind.execute(sa.text("DELETE FROM point_copy WHERE copy_key <> :key"), {"key": GUIDE_KEY})

    guide = next((c for c in SEED_COPIES if c["copy_key"] == GUIDE_KEY), None)
    if not guide:
        return

    tenant_ids = [
        int(r[0])
        for r in bind.execute(sa.text("SELECT DISTINCT tenant_id FROM point_rule")).fetchall()
    ]
    if not tenant_ids:
        tenant_ids = [1]

    for tenant_id in tenant_ids:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM point_copy WHERE tenant_id = :tid AND copy_key = :key LIMIT 1"
            ),
            {"tid": tenant_id, "key": GUIDE_KEY},
        ).first()
        if exists:
            continue
        bind.execute(
            sa.insert(PointCopy.__table__),
            [{"tenant_id": tenant_id, **guide}],
        )


def downgrade():
    """Irreversible data cleanup — no restore of legacy multi-key copies."""
    pass

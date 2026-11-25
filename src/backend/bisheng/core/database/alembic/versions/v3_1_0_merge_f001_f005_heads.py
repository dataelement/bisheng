"""合并 F001 积分扣费与 F005 技能自动启用的迁移端点。"""

revision = "v310_merge_f001_f005_heads"
down_revision = (
    "v310_f001_credit_billing_extension",
    "f005_linsight_skill_auto_enabled",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

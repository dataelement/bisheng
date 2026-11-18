"""Join beta1's F016 DSH call pricing migration and the F132 memory merge on 3.1.0-beta2."""

revision = "v310b2_merge_f016_pricing_memory_heads"
down_revision = (
    "v310b1_f016_dsh_call_pricing",
    "v310b2_merge_f132_memory_heads",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

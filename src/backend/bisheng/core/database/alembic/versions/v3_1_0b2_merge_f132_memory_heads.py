"""Join the F132 long-term memory migration onto the 3.1 release line."""

revision = "v310b2_merge_f132_memory_heads"
down_revision = (
    "v310b1_merge_tenant_identity",
    "f132_long_term_memory",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

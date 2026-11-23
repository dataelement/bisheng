"""Join F009, F118 deletion and work-130 release schema histories."""

revision = "v310b1_merge_f009_release_heads"
down_revision = (
    "v310b1_f009_managed_tenant",
    "f118_knowledge_delete_execution",
    "v310b1_merge_work130_heads",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

"""Join the 3.1 release schema and the work-130 deployment history."""

revision = "v310b1_merge_work130_heads"
down_revision = (
    "v310b1_f004_workflow_soft_delete",
    "f130_cloud_workbenches",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

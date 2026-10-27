"""Join the F059 runtime and inherited release-line schema histories.

The merge has no schema or data effect. Every existing parent remains intact.
"""

revision = "f059_merge_release_heads"
down_revision = ("f059_merge_f086_heads", "asr_rt_model_type", "merge_skill_center_heads")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass

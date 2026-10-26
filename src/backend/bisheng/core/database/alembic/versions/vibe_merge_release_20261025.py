"""Join Vibe access-name and current release migrations without rewriting either history."""

revision = "vibe_merge_release_20261025"
down_revision = ("f056_access_name_snapshot", "merge_main_work110_release300")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass

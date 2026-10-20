"""Join immutable deployed audit revisions with native DSH access."""

revision = "work110_merge_legacy_audit"
down_revision = ("work110_dsh_local_sessions", "f062_dsh_audit_tree")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass

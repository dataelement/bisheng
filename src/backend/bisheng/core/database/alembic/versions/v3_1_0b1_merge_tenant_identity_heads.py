"""Join tenant-consistency and account-identity release migrations."""

revision = "v310b1_merge_tenant_identity"
down_revision = (
    "v310b1_merge_f009_release_heads",
    "v310b1_f011_account_identity",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

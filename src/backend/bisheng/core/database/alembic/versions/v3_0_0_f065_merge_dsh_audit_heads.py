"""Join the unified DSH and desktop-install-policy migration histories.

Both parents have already shipped. Keep their ancestry unchanged and restore
the single head required by the API entrypoint without schema or data changes.

Revision ID: f065_merge_dsh_audit_heads
Revises: merge_dsh_heads, f065_dsh_install_policy_default_off
Create Date: 2026-10-15
"""

revision = "f065_merge_dsh_audit_heads"
down_revision = ("merge_dsh_heads", "f065_dsh_install_policy_default_off")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

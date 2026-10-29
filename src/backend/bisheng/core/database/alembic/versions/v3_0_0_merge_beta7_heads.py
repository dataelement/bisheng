"""Join beta7 content safety and release information migration histories."""

revision = "v300_merge_beta7_heads"
down_revision = ("f111_matched_words", "f112_release_notes")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

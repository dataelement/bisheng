"""Merge finetune dataset catalog and release migration heads.

Both parent revisions may already be applied independently. This merge keeps
those histories intact and restores one upgrade head without schema changes.
"""

from collections.abc import Sequence

revision: str = "v310_f025_merge_catalog_release"
down_revision: str | Sequence[str] | None = (
    "v310_f025_dataset_catalog",
    "v310_merge_f001_f005_heads",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join existing migration histories without changing the schema."""
    pass


def downgrade() -> None:
    """Split migration histories without changing the schema."""
    pass

"""merge_update_time_default_heads — re-collapse the graph after picking the update_time fix.

``update_time_default_align`` was written on ``feat/3.0.0-beta1``, where the head
was ``f051_channel_user_pin``. ``3.0-vibe`` is already past that point via
``merge_beta1_f051_heads``, so cherry-picking the revision onto this line left
**two heads**, which breaks ``alembic upgrade head`` outright.

This revision is the standard fix and follows the precedent already in this
directory (``f012_merge_heads``, ``f025_merge_f024_heads``,
``f037_merge_f036_heads``, ``f056_merge_beta1_vibe_heads``,
``merge_beta1_f051_heads``): a no-op with two ``down_revision``s that
re-collapses the graph to a single head.

**No DDL on purpose.** The alignment ALTERs live in ``update_time_default_align``
and still run exactly once; this revision only records that the two lines
converged.

The id carries no ``fNNN`` prefix on purpose: the two release lines number their
features independently, so a feature number here would name the wrong thing.

Revision ID: merge_update_time_default_heads
Revises: merge_beta1_f051_heads, update_time_default_align
Create Date: 2026-08-24
"""

from collections.abc import Sequence

revision: str = "merge_update_time_default_heads"
down_revision: tuple[str, ...] = ("merge_beta1_f051_heads", "update_time_default_align")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to do — the merge is the point."""


def downgrade() -> None:
    """Nothing to undo; the two chains downgrade independently."""

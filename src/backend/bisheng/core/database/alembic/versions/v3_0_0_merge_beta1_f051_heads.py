"""merge_beta1_f051_heads — re-collapse the graph after the second beta1 → 3.0-vibe merge.

The first merge (``f056_merge_beta1_vibe_heads``) joined the two lines at
``f050_creation_idempotency`` / ``f055_app_publish_tables``. ``feat/3.0.0-beta1``
then grew one more revision on its own chain:

* ``feat/3.0.0-beta1`` added ``f051_channel_user_pin`` on top of
  ``f050_creation_idempotency``
* ``3.0-vibe`` was already past that point via ``f056_merge_beta1_vibe_heads``

Merging the branches again therefore produced **two heads**, which breaks
``alembic upgrade head`` outright. This revision is the standard fix and follows
the precedent already in this directory (``f012_merge_heads``,
``f025_merge_f024_heads``, ``f037_merge_f036_heads``, ``f056_merge_beta1_vibe_heads``):
a no-op with two ``down_revision``s that re-collapses the graph to a single head.

**No DDL on purpose.** Both chains' migrations still run, each exactly once, in
their own order; this revision only records that the two lines converged again.

The id carries no ``fNNN`` prefix on purpose: the two release lines number their
features independently (beta1's F051 is not vibe's F051), so a feature number
here would name the wrong thing.

Revision ID: merge_beta1_f051_heads
Revises: f056_merge_beta1_vibe_heads, f051_channel_user_pin
Create Date: 2026-08-20
"""

from collections.abc import Sequence

revision: str = "merge_beta1_f051_heads"
down_revision: tuple[str, ...] = ("f056_merge_beta1_vibe_heads", "f051_channel_user_pin")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to do — the merge is the point."""


def downgrade() -> None:
    """Nothing to undo; the two chains downgrade independently."""

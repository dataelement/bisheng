"""f056_merge_beta1_vibe_heads — re-collapse the graph after merging beta1 into 3.0-vibe.

Two release lines each grew their own chain from a common ancestor:

* ``feat/3.0.0-beta1`` ended at ``f050_creation_idempotency``
* ``3.0-vibe`` ended at ``f055_app_publish_tables``

Merging the branches therefore produced **two heads**, which breaks
``alembic upgrade head`` outright. This revision is the standard fix and follows
the precedent already in this directory (``f012_merge_heads``,
``f025_merge_f024_heads``, ``f037_merge_f036_heads``): a no-op with two
``down_revision``s that re-collapses the graph to a single head.

**No DDL on purpose.** Both chains' migrations still run, each exactly once, in
their own order; this revision only records that the two lines converged. A
database sitting anywhere on either chain upgrades straight through it.

Revision ID: f056_merge_beta1_vibe_heads
Revises: f050_creation_idempotency, f055_app_publish_tables
Create Date: 2026-08-18
"""

from collections.abc import Sequence

revision: str = "f056_merge_beta1_vibe_heads"
down_revision: tuple[str, ...] = ("f050_creation_idempotency", "f055_app_publish_tables")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to do — the merge is the point."""


def downgrade() -> None:
    """Nothing to undo; the two chains downgrade independently."""

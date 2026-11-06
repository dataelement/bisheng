"""merge_beta2_openapi_heads — re-collapse the graph after moving the factory onto the beta2 open-API base.

Two release lines each grew their own chain past ``update_time_default_align``:

* ``feat/3.0.0-beta2`` (highway's F053 / F056) continued
  ``update_time_default_align`` → ``f053_api_credential_tables``
  → ``f053_delegate_session_subject`` → ``f053_pat_tenant_setting``
  → ``f056_user_string_lengths``.
* ``3.0-vibe`` had already folded ``update_time_default_align`` in through
  ``merge_update_time_default_heads`` and now ends at
  ``vibe_drop_user_user_type`` (the F049 ``user.user_type`` retirement).

Merging ``feat/3.0.0-beta2`` into the factory branch therefore produced **two
heads**, which breaks ``alembic upgrade head`` outright (migration plan M6).
This revision is the standard fix and follows the precedent already in this
directory (``f012_merge_heads``, ``f025_merge_f024_heads``,
``f037_merge_f036_heads``, ``f056_merge_beta1_vibe_heads``,
``merge_beta1_f051_heads``, ``merge_update_time_default_heads``): a no-op with
two ``down_revision``s that re-collapses the graph to a single head.

**No DDL on purpose.** Both chains' migrations still run, each exactly once,
in their own order; this revision only records that the two lines converged. A
database sitting anywhere on either chain upgrades straight through it.

The id carries no ``fNNN`` prefix on purpose: the two release lines number
their features independently, so a feature number here would name the wrong
thing.

Revision ID: merge_beta2_openapi_heads
Revises: vibe_drop_user_user_type, f056_user_string_lengths
Create Date: 2026-09-10
"""

from collections.abc import Sequence

revision: str = "merge_beta2_openapi_heads"
down_revision: tuple[str, ...] = ("vibe_drop_user_user_type", "f056_user_string_lengths")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to do — the merge is the point."""


def downgrade() -> None:
    """Nothing to undo; the two chains downgrade independently."""

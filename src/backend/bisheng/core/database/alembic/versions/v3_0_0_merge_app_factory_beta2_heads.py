"""merge_app_factory_beta2_heads — re-collapse the graph after the second beta2 sync.

The factory branch and the release line each grew past ``f056_user_string_lengths``
again after 2026-09-10:

* ``3.0-vibe`` / the factory branch ends at ``merge_beta2_openapi_heads`` (which
  folded ``vibe_drop_user_user_type`` into the beta2 open-API chain).
* ``feat/3.0.0-beta2`` continued ``f056_user_string_lengths``
  → ``f058_widen_projection_idempotency_key`` → ``f053_pat_default_ttl_365``
  → ``f066_pat_data_scope``, plus ``f064_kb_file_abnormal_index`` on a second
  branch, re-collapsed by its own ``merge_f064_f066_heads``.

Merging ``feat/3.0.0-beta2`` (03106e053) therefore produced two heads again. Same
fix as ``merge_beta2_openapi_heads``: a no-op revision with two
``down_revision``s. **No DDL on purpose** — every migration on either chain still
runs exactly once in its own order; a database sitting anywhere on either chain
upgrades straight through.

The id carries no ``fNNN`` prefix on purpose: the two release lines number their
features independently (both have an F054), so a feature number here would name
the wrong thing.

Revision ID: merge_app_factory_beta2_heads
Revises: merge_beta2_openapi_heads, merge_f064_f066_heads
Create Date: 2026-09-15
"""

from collections.abc import Sequence

revision: str = "merge_app_factory_beta2_heads"
down_revision: tuple[str, ...] = ("merge_beta2_openapi_heads", "merge_f064_f066_heads")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to do — the merge is the point."""


def downgrade() -> None:
    """Nothing to undo; the two chains downgrade independently."""

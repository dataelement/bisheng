"""F012 merge revision: rejoin the two concurrent f012 branches.

Revision ID: f012_merge_heads
Revises: f012_user_token_version, f012_backfill_local_external_id
Create Date: 2026-04-19

Background:
  Two F012 alembic migrations landed on 2.5.0-PM concurrently from
  parallel branches, both descending from
  ``f011_backfill_create_knowledge_web_menu``:

  1. ``f012_backfill_local_external_id`` — hotfix PR #1985 that backfills
     ``user.external_id`` for local accounts so password login works after
     94323e3ec.
  2. ``f011_tenant_tree → f012_user_token_version`` — v2.5.1 Tenant tree
     chain: adds ``parent_tenant_id`` / ``user_tenant.is_active`` / dept
     mount point fields / audit_log v2 / user.token_version (JWT
     invalidation counter).

  Before this merge the graph had two heads; alembic requires exactly one
  to know where HEAD is. This revision is a no-op join so ``alembic
  upgrade head`` can traverse both branches on any DB regardless of which
  branch it was upgraded through first.

Effect on DBs that already upgraded to ``f012_backfill_local_external_id``
(the typical 114 dev-server state at merge time):
  - ``alembic upgrade head`` walks the other branch
    (``f011_tenant_tree`` → ``f012_user_token_version``) and applies it,
    then lands on ``f012_merge_heads``.

Effect on DBs that already upgraded to ``f012_user_token_version``:
  - ``alembic upgrade head`` walks ``f012_backfill_local_external_id``
    then lands on ``f012_merge_heads``.
"""

from typing import Sequence, Union

revision: str = 'f012_merge_heads'
down_revision: Union[str, Sequence[str], None] = (
    'f012_user_token_version',
    'f012_backfill_local_external_id',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge revisions are intentionally empty — the purpose is to collapse
    # two alembic heads into one. All schema changes were done by the two
    # parent revisions.
    pass


def downgrade() -> None:
    # Reversing a merge forks the graph again; alembic handles this by
    # stepping back down each parent independently.
    pass

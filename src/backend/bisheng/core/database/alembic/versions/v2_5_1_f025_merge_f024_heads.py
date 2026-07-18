"""F025 merge revision: rejoin the two concurrent F024 branches.

Revision ID: f025_merge_f024_heads
Revises: f024_role_creator, f024_department_space_per_space_approval_settings
Create Date: 2026-04-22

Background:
  Two F024 revisions landed concurrently from the same parent
  ``f023_department_admin_membership_overlay``:

  1. ``f024_role_creator`` — adds ``role.create_user`` and backfills it.
  2. ``f024_department_space_per_space_approval_settings`` — adds
     per-space approval toggles on ``department_knowledge_space``.

  Without a merge revision, ``alembic upgrade head`` becomes ambiguous
  and operators must target a specific branch manually. This no-op merge
  restores a single canonical head so future upgrades can continue with
  the usual ``upgrade head`` workflow.
"""

from typing import Sequence, Union

revision: str = 'f025_merge_f024_heads'
down_revision: Union[str, Sequence[str], None] = (
    'f024_role_creator',
    'f024_department_space_per_space_approval_settings',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge revisions are intentionally empty: the schema changes live in
    # the two parent revisions, and this node exists only to restore a
    # single Alembic head.
    pass


def downgrade() -> None:
    # Stepping back through this merge splits the graph into its two F024
    # parents again; Alembic handles that automatically.
    pass

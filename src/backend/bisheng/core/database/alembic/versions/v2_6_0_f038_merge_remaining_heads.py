"""F038 merge revision: rejoin remaining concurrent migration heads.

Revision ID: f038_merge_remaining_heads
Revises: f034_knowledge_space_scope, f036_share_link_knowledge_space_file, f037_merge_f036_heads
Create Date: 2026-05-20

Background:
  Three heads existed after concurrent migration branches landed:

  1. ``f034_knowledge_space_scope`` — adds and backfills knowledge-space
     scope metadata.
  2. ``f036_share_link_knowledge_space_file`` — extends share-link resource
     types for knowledge-space file links.
  3. ``f037_merge_f036_heads`` — already merges the workstation-config and
     sensitive-word-policy F036 branches.

  Without this no-op merge revision, ``alembic upgrade head`` is ambiguous
  and fails with "Multiple head revisions are present".
"""

from typing import Sequence, Union

revision: str = 'f038_merge_remaining_heads'
down_revision: Union[str, Sequence[str], None] = (
    'f034_knowledge_space_scope',
    'f036_share_link_knowledge_space_file',
    'f037_merge_f036_heads',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge revisions are intentionally empty: schema/data changes live in
    # the parent revisions, and this node restores a single Alembic head.
    pass


def downgrade() -> None:
    # Stepping back through this merge splits the graph into its parent
    # heads again; Alembic handles that graph traversal.
    pass

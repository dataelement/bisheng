"""F051 merge revision: rejoin the two concurrent F050 heads.

Revision ID: f051_merge_f050_heads
Revises: f050_knowledge_business_domain_codes, f050_tag_library_m2m
Create Date: 2026-07-02

Background:
  Two independent heads landed concurrently on feat/2.5.0-sg:

  1. ``f050_knowledge_business_domain_codes`` — adds knowledge.business_domain_codes.
  2. ``f050_tag_library_m2m`` — tag-library many-to-many schema.

  Without this no-op merge revision, ``alembic upgrade head`` is ambiguous
  and fails with "Multiple head revisions are present". This node restores a
  single head so downstream migrations (favorites unique constraint) can chain.
"""

from typing import Sequence, Union

revision: str = "f051_merge_f050_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f050_knowledge_business_domain_codes",
    "f050_tag_library_m2m",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge revisions are intentionally empty: schema changes live in the
    # parent revisions, this node only restores a single Alembic head.
    pass


def downgrade() -> None:
    pass

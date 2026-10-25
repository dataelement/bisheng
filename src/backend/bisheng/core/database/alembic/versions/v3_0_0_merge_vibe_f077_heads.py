"""Merge the feat/3.0.0-vibe head with the F077 head on the release line.

Revision ID: merge_vibe_f077_heads
Revises: merge_vibe_beta4_heads, f077_subject_id_search_indexes
Create Date: 2026-10-19

``merge_vibe_beta4_heads`` is the feat/3.0.0-vibe head;
``f077_subject_id_search_indexes`` is the head of feat/3.0.0 after F077 added
its subject-search indexes. This no-op revision rejoins them so deployments can
keep using ``alembic upgrade head`` (singular).
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_vibe_f077_heads"
down_revision: Union[str, Sequence[str], None] = (
    "merge_vibe_beta4_heads",
    "f077_subject_id_search_indexes",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

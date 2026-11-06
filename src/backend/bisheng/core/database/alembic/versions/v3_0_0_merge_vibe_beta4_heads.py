"""Merge the feat/3.0.0-vibe head with the beta4 merge on the release line.

Revision ID: merge_vibe_beta4_heads
Revises: merge_vibe_release_line_heads, merge_beta4_heads
Create Date: 2026-10-12

``merge_vibe_release_line_heads`` is the feat/3.0.0-vibe head;
``merge_beta4_heads`` is the new single head of feat/3.0.0 after beta4 was
merged into it. This no-op revision rejoins them so deployments can keep
using ``alembic upgrade head`` (singular).
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_vibe_beta4_heads"
down_revision: Union[str, Sequence[str], None] = (
    "merge_vibe_release_line_heads",
    "merge_beta4_heads",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

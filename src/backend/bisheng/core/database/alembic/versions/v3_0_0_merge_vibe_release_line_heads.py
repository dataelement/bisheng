"""Merge the feat/3.0.0-vibe head with the feat/3.0.0 release-line head.

Revision ID: merge_vibe_release_line_heads
Revises: merge_vibe_beta3_dsh_market, merge_release_line_heads
Create Date: 2026-10-10

``merge_vibe_beta3_dsh_market`` is the feat/3.0.0-vibe head (hosted apps);
``merge_release_line_heads`` is the single head of feat/3.0.0, the release
line. This no-op revision rejoins them so deployments can keep using
``alembic upgrade head`` (singular).
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_vibe_release_line_heads"
down_revision: Union[str, Sequence[str], None] = (
    "merge_vibe_beta3_dsh_market",
    "merge_release_line_heads",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

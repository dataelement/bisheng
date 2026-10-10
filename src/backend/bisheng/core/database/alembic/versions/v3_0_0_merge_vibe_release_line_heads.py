"""Merge the three heads left after feat/3.0.0 was merged into feat/3.0.0-vibe.

Revision ID: merge_vibe_release_line_heads
Revises: merge_vibe_beta3_dsh_market, merge_dsh_heads, f064_merge_market_chat_id_index_heads
Create Date: 2026-10-10

``merge_vibe_beta3_dsh_market`` is the feat/3.0.0-vibe head (hosted apps);
``merge_dsh_heads`` and ``f064_merge_market_chat_id_index_heads`` came from
feat/3.0.0, the release line. This no-op revision rejoins them so deployments
can keep using ``alembic upgrade head`` (singular).
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_vibe_release_line_heads"
down_revision: Union[str, Sequence[str], None] = (
    "merge_vibe_beta3_dsh_market",
    "merge_dsh_heads",
    "f064_merge_market_chat_id_index_heads",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

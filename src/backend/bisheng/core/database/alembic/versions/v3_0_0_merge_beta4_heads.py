"""Re-collapse the heads after merging feat/3.0.0-beta4 into feat/3.0.0.

Revision ID: merge_beta4_heads
Revises: merge_release_line_heads, linsight_skill_default_checked
Create Date: 2026-10-10

``linsight_skill_default_checked`` was written on feat/3.0.0-beta4, which is
cut from main, so it chains after main's head
``f064_merge_market_chat_id_index_heads``. The release line had already moved
past that revision to ``merge_release_line_heads``, so the merge left two
heads. This no-op revision restores the single head that
``alembic upgrade head`` and ``entrypoint.sh`` require.
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_beta4_heads"
down_revision: Union[str, Sequence[str], None] = (
    "merge_release_line_heads",
    "linsight_skill_default_checked",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

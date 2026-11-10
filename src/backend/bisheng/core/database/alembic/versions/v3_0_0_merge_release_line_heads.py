"""Re-collapse the two heads on the feat/3.0.0 release line.

Revision ID: merge_release_line_heads
Revises: merge_dsh_heads, f064_merge_market_chat_id_index_heads
Create Date: 2026-10-10

``merge_dsh_heads`` (2026-09-21) and ``f064_merge_market_chat_id_index_heads``
(2026-10-08) each closed a fork that included ``f064_enterprise_market``, but
on different lines, so the release line ended up with both as heads. This
no-op revision restores the single head that ``alembic upgrade head`` and
``entrypoint.sh`` require.
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_release_line_heads"
down_revision: Union[str, Sequence[str], None] = (
    "merge_dsh_heads",
    "f064_merge_market_chat_id_index_heads",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

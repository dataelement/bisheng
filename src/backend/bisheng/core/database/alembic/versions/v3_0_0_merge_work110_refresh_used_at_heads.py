"""Rejoin the refresh-token grace column with the 130 release head.

``work110_dsh_refresh_used_at`` hangs off the 110-only session revision so that
line can cherry-pick one migration. On 130 that parent already has descendants,
so the new revision opens a second head. This no-op merge restores the single
head required by ``alembic upgrade head``.
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_work110_refresh_used_at_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f111_matched_words",
    "work110_dsh_refresh_used_at",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

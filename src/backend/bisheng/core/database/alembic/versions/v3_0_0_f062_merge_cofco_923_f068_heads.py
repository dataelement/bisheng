"""Re-collapse the graph after the F068 knowledge chat entry landed upstream.

Same shape as f057 and f059-f061 before it: the COFCO branch carries its own
merge revision, so every main-line revision pulled in afterwards opens a second
head. This one has no DDL; it only restores the single head
`alembic upgrade head` requires, which entrypoint.sh checks before it will
start the API.

Revision ID: f062_merge_cofco_923_f068_heads
Revises: f061_merge_cofco_909_f066_heads, f068_knowledge_chat_entry
Create Date: 2026-09-20
"""

from collections.abc import Sequence
from typing import Union

revision: str = "f062_merge_cofco_923_f068_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f061_merge_cofco_909_f066_heads",
    "f068_knowledge_chat_entry",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

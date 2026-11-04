"""Re-collapse the graph where the beta1 and beta2 lines meet in 3.0.0.

The unified 3.0.0 branch merges two lines that each kept adding revisions, so
the merge opens two heads. This one has no DDL; it only restores the single
head `alembic upgrade head` requires, which entrypoint.sh checks before it
will start the API.

Revision ID: merge_beta1_beta2_heads
Revises: f068_knowledge_chat_entry, merge_f064_f066_heads
Create Date: 2026-09-21
"""

from collections.abc import Sequence
from typing import Union

revision: str = "merge_beta1_beta2_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f068_knowledge_chat_entry",
    "merge_f064_f066_heads",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

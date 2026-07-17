"""F048: merge the knowledge-file and assistant-knowledge-auth heads.

Revision ID: f048_merge_f046_f047_heads
Revises: f046_knowledge_file_name_length, f047_assistant_knowledge_auth
Create Date: 2026-07-17

The two schema changes landed concurrently from ``f045_dks_is_hidden``. This
no-op revision rejoins both migration branches so deployments can continue to
use the canonical ``alembic upgrade head`` command.
"""

from collections.abc import Sequence
from typing import Union

revision: str = "f048_merge_f046_f047_heads"
down_revision: Union[str, Sequence[str], None] = (
    "f046_knowledge_file_name_length",
    "f047_assistant_knowledge_auth",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

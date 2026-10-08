"""Merge f064_enterprise_market and chatmessage_chat_id_index heads.

The DSH marketplace migration and the chatmessage.chat_id index restore were
added on separate lines; merging main into the release line left two heads, and
``alembic upgrade head`` refuses to run with more than one.

Revision ID: f064_merge_market_chat_id_index_heads
Revises: f064_enterprise_market, chatmessage_chat_id_index
Create Date: 2026-10-08
"""

from collections.abc import Sequence

revision: str = "f064_merge_market_chat_id_index_heads"
down_revision: str | Sequence[str] | None = (
    "f064_enterprise_market",
    "chatmessage_chat_id_index",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

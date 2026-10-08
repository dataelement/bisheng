"""Merge the enterprise-market and chat-message-index migration heads.

Revision ID: merge_enterprise_chat_heads
Revises: f064_enterprise_market, chatmessage_chat_id_index
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "merge_enterprise_chat_heads"
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

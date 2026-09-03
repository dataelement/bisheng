"""F050: add durable resource-creation idempotency keys.

Revision ID: f050_creation_idempotency
Revises: f035_skill_content_hash
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, index_exists

revision: str = "f050_creation_idempotency"
down_revision: str | Sequence[str] | None = "f035_skill_content_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KNOWLEDGE_TABLE = "knowledge"
_CHANNEL_TABLE = "channel"
_KNOWLEDGE_INDEX = "uq_knowledge_creation_request"
_CHANNEL_INDEX = "uq_channel_creation_request"


def _add_columns(table: str) -> None:
    if not column_exists(table, "creation_request_id"):
        op.add_column(
            table,
            sa.Column("creation_request_id", sa.String(length=64), nullable=True),
        )
    if not column_exists(table, "creation_payload_hash"):
        op.add_column(
            table,
            sa.Column("creation_payload_hash", sa.String(length=64), nullable=True),
        )


def upgrade() -> None:
    _add_columns(_KNOWLEDGE_TABLE)
    _add_columns(_CHANNEL_TABLE)

    if not index_exists(_KNOWLEDGE_TABLE, _KNOWLEDGE_INDEX):
        op.create_index(
            _KNOWLEDGE_INDEX,
            _KNOWLEDGE_TABLE,
            ["tenant_id", "user_id", "type", "creation_request_id"],
            unique=True,
        )
    if not index_exists(_CHANNEL_TABLE, _CHANNEL_INDEX):
        op.create_index(
            _CHANNEL_INDEX,
            _CHANNEL_TABLE,
            ["tenant_id", "user_id", "creation_request_id"],
            unique=True,
        )


def downgrade() -> None:
    if index_exists(_CHANNEL_TABLE, _CHANNEL_INDEX):
        op.drop_index(_CHANNEL_INDEX, table_name=_CHANNEL_TABLE)
    if index_exists(_KNOWLEDGE_TABLE, _KNOWLEDGE_INDEX):
        op.drop_index(_KNOWLEDGE_INDEX, table_name=_KNOWLEDGE_TABLE)

    if column_exists(_CHANNEL_TABLE, "creation_payload_hash"):
        op.drop_column(_CHANNEL_TABLE, "creation_payload_hash")
    if column_exists(_CHANNEL_TABLE, "creation_request_id"):
        op.drop_column(_CHANNEL_TABLE, "creation_request_id")
    if column_exists(_KNOWLEDGE_TABLE, "creation_payload_hash"):
        op.drop_column(_KNOWLEDGE_TABLE, "creation_payload_hash")
    if column_exists(_KNOWLEDGE_TABLE, "creation_request_id"):
        op.drop_column(_KNOWLEDGE_TABLE, "creation_request_id")

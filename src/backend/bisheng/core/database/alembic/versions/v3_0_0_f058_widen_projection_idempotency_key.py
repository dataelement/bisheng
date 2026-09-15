"""Widen ``permission_projection_operation.idempotency_key`` to 192.

The key is built from the resource id, and a channel id is 32 hex characters on
its own::

    channel-membership:<32-hex channel>:<user id>:<model key>:<version>

That reaches 67 characters for a six-digit user id, so every channel
subscription approval for such a user died at the insert — DM8 with
``[CODE:-6108] String truncated``, MySQL strict mode with ``Data too long``.
The approval itself was already committed, so the instance ended in
``execute_failed`` and the applicant saw "处理异常" for a subscription that had
been approved. Small user ids fit, which is why it surfaced only once the
customer's six-digit accounts started subscribing.

192 matches the width F046 already uses for its execution-step keys and leaves
room for longer ids and version counters. The column is half of
``uq_perm_projection_idempotency``; 192 characters stays far inside both
engines' index-key limits.

Revision ID: f058_widen_projection_idempotency_key
Revises: f056_user_string_lengths
Create Date: 2026-09-09
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists

revision: str = "f058_widen_projection_idempotency_key"
down_revision: Union[str, Sequence[str], None] = "f056_user_string_lengths"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "permission_projection_operation"
_COLUMN = "idempotency_key"


def upgrade() -> None:
    # A fresh database gets the table from the model at its current width, so
    # the column may already be 192 here.
    if not table_exists(_TABLE) or not column_exists(_TABLE, _COLUMN):
        return
    op.alter_column(
        _TABLE,
        _COLUMN,
        existing_type=sa.String(64),
        type_=sa.String(192),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Narrowing back would truncate keys written since the upgrade; leave the
    # wider column in place.
    pass

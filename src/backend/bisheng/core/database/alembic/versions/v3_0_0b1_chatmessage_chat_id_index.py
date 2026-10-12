"""Restore the chatmessage.chat_id index on databases that lost it.

``ChatMessage.chat_id`` has declared ``index=True`` since the first backend
commit, so ``create_all`` builds ``ix_chatmessage_chat_id`` on a fresh install.
But ``create_all`` never touches an existing table, and some long-lived
databases no longer carry the index (the shared test database was found
without it on 2026-10-01; how it was lost is not recorded). Every "messages of
one conversation" query then scans the whole table: on test (89k rows, large
text columns) that cost 0.8s on a warm cache and up to 168s on a cold one,
across chat history loads and task-mode submits alike.

Skips when any index already leads with ``chat_id`` (whatever its name), so a
database that kept or re-created it gets no duplicate. Downgrade is a no-op:
the index belongs to the model, not to this revision.

Revision ID: chatmessage_chat_id_index
Revises: f073_linsight_api_meta
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from bisheng.core.database.dialect_helpers import _reflect

revision: str = "chatmessage_chat_id_index"
down_revision: str | Sequence[str] | None = "f073_linsight_api_meta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "chatmessage"
_INDEX = "ix_chatmessage_chat_id"
_COLUMN = "chat_id"


def _has_leading_chat_id_index(conn) -> bool:
    for index in _reflect(conn, "get_indexes", _TABLE):
        columns = [str(name).lower() for name in index.get("column_names") or [] if name]
        if columns and columns[0] == _COLUMN:
            return True
    return False


def upgrade() -> None:
    if not _has_leading_chat_id_index(op.get_bind()):
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    # The index is part of the ChatMessage model (index=True); dropping it on
    # downgrade would recreate exactly the full-scan this revision repairs.
    pass

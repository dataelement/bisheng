"""F095: fold the single-library column into the knowledge↔library link table.

Revision ID: f095_retire_auto_tag_library_id
Revises: f094_tag_library_sort_weight
Create Date: 2026-08-21

``knowledge.auto_tag_library_id`` predates multi-library binding and has been
written alongside the link table ever since. Two records of one fact drift: a
link removed from one side stayed attached on the other, so a space could read
as unbound while auto-tagging kept using the library.

This moves every remaining value into the link table and blanks the column. The
column itself stays for now — callers may still send and read the singular
field, which application code now derives from the links. Dropping it is a
separate step once no caller depends on the wire field.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import column_exists, table_exists

revision: str = "f095_retire_auto_tag_library_id"
down_revision: str | Sequence[str] | None = "f094_tag_library_sort_weight"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KNOWLEDGE = "knowledge"
_LINK = "knowledge_tag_library_link"
_COLUMN = "auto_tag_library_id"


def upgrade() -> None:
    bind = op.get_bind()
    if not table_exists(bind, _KNOWLEDGE) or not table_exists(bind, _LINK):
        return
    if not column_exists(bind, _KNOWLEDGE, _COLUMN):
        return

    rows = bind.execute(
        sa.text(
            f"SELECT id, tenant_id, {_COLUMN} AS library_id FROM {_KNOWLEDGE} "
            f"WHERE {_COLUMN} IS NOT NULL"
        )
    ).fetchall()

    for row in rows:
        knowledge_id = int(row[0])
        tenant_id = int(row[1]) if row[1] is not None else 1
        library_id = int(row[2])

        existing = bind.execute(
            sa.text(
                f"SELECT id FROM {_LINK} WHERE knowledge_id = :kid AND tag_library_id = :lid"
            ),
            {"kid": knowledge_id, "lid": library_id},
        ).fetchone()
        if existing is None:
            # Only reachable for a space that was bound before the link table
            # existed and never re-saved since. Append rather than insert first:
            # whatever order it already had is the order it keeps.
            next_order = bind.execute(
                sa.text(f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {_LINK} WHERE knowledge_id = :kid"),
                {"kid": knowledge_id},
            ).scalar()
            bind.execute(
                sa.text(
                    f"INSERT INTO {_LINK} (tenant_id, knowledge_id, tag_library_id, sort_order) "
                    "VALUES (:tid, :kid, :lid, :ord)"
                ),
                {"tid": tenant_id, "kid": knowledge_id, "lid": library_id, "ord": int(next_order or 0)},
            )

    bind.execute(sa.text(f"UPDATE {_KNOWLEDGE} SET {_COLUMN} = NULL WHERE {_COLUMN} IS NOT NULL"))


def downgrade() -> None:
    """Re-seed the column from each space's first link.

    Not an exact inverse — a space bound to several libraries had only one of
    them in the column, and which one is no longer recorded.
    """
    bind = op.get_bind()
    if not table_exists(bind, _KNOWLEDGE) or not table_exists(bind, _LINK):
        return
    if not column_exists(bind, _KNOWLEDGE, _COLUMN):
        return

    # Looped in Python rather than one correlated UPDATE: the alias-and-subquery
    # form differs between MySQL and DM8, and a downgrade is rare enough that
    # clarity beats the round trips.
    rows = bind.execute(
        sa.text(
            f"SELECT knowledge_id, tag_library_id FROM {_LINK} ORDER BY knowledge_id, sort_order ASC, id ASC"
        )
    ).fetchall()
    first_by_knowledge: dict[int, int] = {}
    for row in rows:
        first_by_knowledge.setdefault(int(row[0]), int(row[1]))

    for knowledge_id, library_id in first_by_knowledge.items():
        bind.execute(
            sa.text(f"UPDATE {_KNOWLEDGE} SET {_COLUMN} = :lid WHERE id = :kid AND {_COLUMN} IS NULL"),
            {"lid": library_id, "kid": knowledge_id},
        )

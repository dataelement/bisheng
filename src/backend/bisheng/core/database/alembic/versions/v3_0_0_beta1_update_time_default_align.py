"""Align update_time DDL with what the models declare (ON UPDATE CURRENT_TIMESTAMP).

Revision ID: update_time_default_align
Revises: f051_channel_user_pin
Create Date: 2026-08-24

A table reaches a live database along one of two paths, and they disagreed:

* fresh install — ``SQLModel.metadata.create_all()`` emits the column exactly as
  the model declares it, so ``update_time`` gets
  ``DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP``;
* upgrade — the revision that first created the table emits its own DDL, and
  several wrote ``update_time`` with a plain ``CURRENT_TIMESTAMP`` default or
  with none at all instead of ``update_time_server_default(conn)``.

So the same release behaved differently depending on how the database was built.
On ``linsight_skill`` (created by f035 with no default at all) that surfaced as a
product bug: rows landed with a NULL update_time, and the skill list — which
sorts on that column — pushed a freshly imported skill to the last page.

This is a correction toward the declared intent, not a behaviour change being
introduced here: fresh MySQL installs have always had ON UPDATE, and on DaMeng
``_ensure_dm_triggers`` recreates a BEFORE UPDATE trigger for *every* table with
an update_time column on every boot. Upgraded MySQL databases were the outlier.

Cost: MySQL cannot change ON UPDATE in place, so each ALTER rebuilds its table.
The affected tables are small metadata tables; ``knowledge_document`` and
``knowledge_document_version`` are the only ones that grow with customer data
(one row per document), so a large installation should expect this revision to
take proportionally longer.
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import get_dialect_name, is_update_time_server_default

revision: str = "update_time_default_align"
down_revision: str | Sequence[str] | None = "f051_channel_user_pin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Guard the identifiers that go into the ALTER: they come from the model
# metadata and information_schema rather than from user input, but the
# statement is assembled as text because ON UPDATE has no SQLAlchemy construct.
_SAFE_TABLE = re.compile(r"^[A-Za-z0-9_]+$")
_SAFE_TYPE = re.compile(r"^datetime(\(\d\))?$", re.IGNORECASE)


def _tables_declaring_update_time_default() -> set[str]:
    """Tables whose model asks for the shared update_time server default.

    Tables owned by other components (the Java gateway's ``gt_*``) or whose
    model deliberately declares a plain default are not in this set and are
    left alone.
    """
    from bisheng.common.models.base import SQLModelSerializable
    from bisheng.core.database.model_discovery import import_all_sqlmodel_models

    import_all_sqlmodel_models()
    return {
        table.name
        for table in SQLModelSerializable.metadata.tables.values()
        if is_update_time_server_default(getattr(table.columns.get("update_time"), "server_default", None))
    }


def upgrade() -> None:
    conn = op.get_bind()
    if get_dialect_name(conn) != "mysql":
        # DaMeng: the boot-time BEFORE UPDATE triggers already give every
        # update_time column ON UPDATE semantics, independent of its default.
        # SQLite (tests) has no equivalent clause to align.
        return

    declared = _tables_declaring_update_time_default()
    if not declared:
        return

    drifted = conn.execute(
        sa.text(
            "SELECT TABLE_NAME, COLUMN_TYPE, IS_NULLABLE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = 'update_time' "
            "AND (COLUMN_DEFAULT IS NULL OR EXTRA NOT LIKE '%on update%')"
        )
    ).fetchall()

    for table_name, column_type, is_nullable in drifted:
        if table_name not in declared:
            continue
        if not _SAFE_TABLE.match(table_name) or not _SAFE_TYPE.match(column_type):
            continue
        null_spec = "NULL" if is_nullable == "YES" else "NOT NULL"
        op.execute(
            f"ALTER TABLE `{table_name}` MODIFY COLUMN `update_time` {column_type} "
            f"{null_spec} DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
        )


def downgrade() -> None:
    """No-op.

    Downgrading would mean re-creating the very drift this revision exists to
    remove, and it cannot know which of the two shapes a given table started
    from. A fresh install has never had the old shape at all.
    """

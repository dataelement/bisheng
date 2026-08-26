"""F049: align ``config.update_time`` with the model-declared shared default.

Revision ID: f049_config_update_time_on_update
Revises: f048_merge_f046_f047_heads
Create Date: 2026-08-26

The ``config`` table holds platform-global JSON state — most importantly the
``permission_relation_model_bindings_v1`` row whose ``update_time`` is read
by F040 (``ConfigDao.aget_config_version``) on every authorization read to
key the process-local relation-roster cache
(``relation_roster_cache.get_or_build``). The cache MUST see ``update_time``
advance on every config write, otherwise a freshly granted ReBAC binding
stays invisible to the reader for as long as the process lives.

A fresh install emits the column from the model via
``SQLModel.metadata.create_all()``: the model declared
``server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP")``
and the DDL came out as ``DEFAULT CURRENT_TIMESTAMP`` — missing
``ON UPDATE CURRENT_TIMESTAMP``. SQLAlchemy's ``onupdate=text(...)`` sets
the column on ORM updates, but the engine-level ON UPDATE clause is what
keeps the row truthful if any other path (another tool, an ad-hoc
migration, an operational SQL) ever touches the row, and it is what the
F040 version probe relies on as the source of truth.

This revision lines the column up with the dialect-aware
``UPDATE_TIME_SERVER_DEFAULT`` marker (now used by the model), which
compiles to ``DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP`` on
MySQL and ``DEFAULT CURRENT_TIMESTAMP`` on DaMeng (where boot-time
triggers already supply ON UPDATE). It is a no-op for any
``update_time`` column that is already correct (DML's EXTRA column already
contains ``on update``), and only re-emits the DDL for the ``config`` row
in upgrade environments where the ON UPDATE half is missing.

The fix mirrors ``update_time_default_align`` (v3.0.0-beta1) but is
scoped narrowly to the ``config`` table — the only one whose
``update_time`` is consulted as a read-side cache version. The wider
schema-drift audit landed later on the beta branch and is out of scope
here; this revision exists to ship the IKB8XT fix independently.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    get_dialect_name,
    is_update_time_server_default,
)

revision: str = "f049_config_update_time_on_update"
down_revision: Union[str, Sequence[str], None] = "f048_merge_f046_f047_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ON UPDATE has no SQLAlchemy construct, so the statement below is
# assembled as text. Guard the identifiers it interpolates against
# information_schema: the table name and column type come from the
# database, not user input, but the statement still must not accept
# anything that could break out of the literal.
_SAFE_TABLE = __import__("re").compile(r"^[A-Za-z0-9_]+$")
_SAFE_TYPE = __import__("re").compile(r"^datetime(\(\d\))?$", __import__("re").IGNORECASE)

_TABLE = "config"
_COLUMN = "update_time"


def _table_declares_the_marker() -> bool:
    """True if the ``Config`` SQLModel declares ``UPDATE_TIME_SERVER_DEFAULT``
    on its ``update_time`` column. The migration only runs when the model
    side has been fixed (it has, in this same change); otherwise we'd be
    writing DDL that the next ``create_all`` would not reproduce.
    """
    from bisheng.common.models.base import SQLModelSerializable
    from bisheng.core.database.model_discovery import import_all_sqlmodel_models

    import_all_sqlmodel_models()
    table = SQLModelSerializable.metadata.tables.get(_TABLE)
    if table is None or _COLUMN not in table.columns:
        return False
    return is_update_time_server_default(getattr(table.columns[_COLUMN], "server_default", None))


def upgrade() -> None:
    conn = op.get_bind()
    if get_dialect_name(conn) != "mysql":
        # DaMeng: boot-time BEFORE UPDATE triggers already give every
        # update_time column ON UPDATE semantics independent of the
        # default. SQLite (tests) has no equivalent clause.
        return

    if not _table_declares_the_marker():
        # Defensive: if the model side has reverted to the bare
        # ``text('CURRENT_TIMESTAMP')`` form, do nothing — re-emitting
        # the DDL to match would only re-introduce the drift the next
        # time someone runs create_all on a fresh database.
        return

    rows = conn.execute(
        sa.text(
            "SELECT TABLE_NAME, COLUMN_TYPE, IS_NULLABLE "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :table_name AND COLUMN_NAME = :column_name"
        ),
        {"table_name": _TABLE, "column_name": _COLUMN},
    ).fetchall()

    if not rows:
        return

    table_name, column_type, is_nullable = rows[0]
    # Defensive: the parameter binding scopes the SELECT to ``config``, but
    # belt-and-suspenders against an upstream reflection quirk: never act on
    # a row whose table name is not the one this migration owns.
    if table_name != _TABLE:
        return
    if not _SAFE_TABLE.match(table_name) or not _SAFE_TYPE.match(column_type):
        return

    null_spec = "NULL" if is_nullable == "YES" else "NOT NULL"
    op.execute(
        f"ALTER TABLE `{table_name}` MODIFY COLUMN `{_COLUMN}` {column_type} "
        f"{null_spec} DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
    )


def downgrade() -> None:
    """No-op.

    Downgrading would re-create the very drift this revision exists to
    remove. The legacy shape was an accident of an older model definition;
    a fresh install has never had it, and there is no safe target DDL
    to revert to without re-introducing the IKB8XT bug.
    """

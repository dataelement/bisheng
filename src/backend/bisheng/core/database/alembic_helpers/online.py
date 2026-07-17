"""Helpers for Alembic's online migration runtime.

These utilities are intentionally small and side-effect focused so they
can be unit-tested without importing Alembic's ``env.py`` module, which
executes the migration environment at import time.
"""

from alembic import op
from sqlalchemy import MetaData, column, inspect, select, table
from sqlalchemy.engine import Connection


def table_exists(table: str) -> bool:
    """True iff ``table`` is currently in the bound database's table list.

    Most v2.5.x migrations need this to gracefully handle two install
    paths: a fresh install where ``SQLModel.metadata.create_all()`` runs
    before alembic, and an upgrade where the table was created by a
    prior revision. Inlined per-migration before this helper landed —
    keep new revisions on this single source of truth.

    Comparison is case-insensitive: DaMeng (DM8) returns identifiers in
    uppercase while migration code uses lowercase names.
    """
    needle = table.lower()
    return needle in {n.lower() for n in inspect(op.get_bind()).get_table_names()}


def column_exists(table: str, column: str) -> bool:
    """True iff ``table.column`` exists. Companion to ``table_exists``.

    Case-insensitive for DaMeng compatibility (identifiers returned uppercase).
    Delegates to ``dialect_helpers.column_exists`` so the DaMeng
    identifier-case fallback (try as-given / upper / lower) is applied here
    too — a bare ``get_columns(table)`` raises or returns nothing for an
    UPPERCASE-stored DM table, which would wrongly report the column missing.
    """
    from bisheng.core.database.dialect_helpers import column_exists as _column_exists

    return _column_exists(op.get_bind(), table, column)


def bootstrap_fresh_database_schema(connection: Connection, metadata: MetaData) -> bool:
    """Create the current model schema only for a genuinely fresh database.

    The repository's base revision alters tables that predate Alembic instead
    of creating them. Fresh installs therefore need the SQLModel schema before
    replaying revisions. Existing or partially initialized databases must stay
    on the normal migration path so missing tables are reported rather than
    silently recreated.

    Returns:
        ``True`` when the model schema was created, else ``False``.
    """
    model_table_names = {
        model_table.name.casefold()
        for model_table in metadata.tables.values()
        if model_table.name.casefold() != "alembic_version"
    }
    if not model_table_names:
        raise RuntimeError("Cannot bootstrap a fresh database from empty model metadata")

    existing_table_names = {name.casefold() for name in inspect(connection).get_table_names()}
    if existing_table_names & model_table_names:
        return False

    if "alembic_version" in existing_table_names:
        version_table = table("alembic_version", column("version_num"))
        if connection.execute(select(version_table.c.version_num)).first() is not None:
            return False

    metadata.create_all(connection)
    return True


def finalize_online_migration_connection(connection: Connection) -> bool:
    """Commit any implicit SQLAlchemy 2 transaction left after migrations.

    Why this exists:
      - On MySQL, Alembic reports ``Will assume non-transactional DDL``.
      - Under SQLAlchemy 2, the first DML statement on a plain connection
        starts an implicit transaction ("autobegin").
      - Revision scripts that run DML (for example backfills) plus
        Alembic's own ``alembic_version`` update can therefore remain
        uncommitted even though DDL has already auto-committed.

    If the connection still reports an active transaction after Alembic's
    ``context.begin_transaction()`` block exits, commit it explicitly so
    DML side effects and the version-table update are durable.

    Returns:
        ``True`` if a commit was issued, else ``False``.
    """
    if not connection.in_transaction():
        return False
    connection.commit()
    return True

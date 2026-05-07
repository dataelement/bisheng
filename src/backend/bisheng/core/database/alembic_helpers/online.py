"""Helpers for Alembic's online migration runtime.

These utilities are intentionally small and side-effect focused so they
can be unit-tested without importing Alembic's ``env.py`` module, which
executes the migration environment at import time.
"""

from alembic import op
from sqlalchemy import inspect
from sqlalchemy.engine import Connection


def table_exists(table: str) -> bool:
    """True iff ``table`` is currently in the bound database's table list.

    Most v2.5.x migrations need this to gracefully handle two install
    paths: a fresh install where ``SQLModel.metadata.create_all()`` runs
    before alembic, and an upgrade where the table was created by a
    prior revision. Inlined per-migration before this helper landed —
    keep new revisions on this single source of truth.
    """
    return table in inspect(op.get_bind()).get_table_names()


def column_exists(table: str, column: str) -> bool:
    """True iff ``table.column`` exists. Companion to ``table_exists``."""
    return column in {c['name'] for c in inspect(op.get_bind()).get_columns(table)}


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

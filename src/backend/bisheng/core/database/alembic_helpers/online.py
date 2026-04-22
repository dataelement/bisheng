"""Helpers for Alembic's online migration runtime.

These utilities are intentionally small and side-effect focused so they
can be unit-tested without importing Alembic's ``env.py`` module, which
executes the migration environment at import time.
"""

from sqlalchemy.engine import Connection


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

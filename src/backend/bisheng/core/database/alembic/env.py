from logging.config import fileConfig

from sqlalchemy import text

from alembic import context
from alembic.ddl.impl import DefaultImpl

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.alembic_helpers.online import (
    finalize_online_migration_connection,
)


# Register DaMeng dialect with Alembic.
# Alembic ships implementations for mysql/postgresql/oracle/sqlite but not for
# 'dm'.  Without this registration MigrationContext.configure() raises KeyError.
# DaMeng is Oracle-compatible and uses auto-committed DDL (transactional_ddl=False).
class DaMengImpl(DefaultImpl):
    __dialect__ = "dm"
    transactional_ddl = False

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = SQLModelSerializable.metadata


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def ensure_alembic_version_table(connection) -> None:
    """Ensure long local revision ids fit into Alembic's version table.

    Uses SQLAlchemy Inspector — dialect-agnostic, works on MySQL and DaMeng.
    """
    from bisheng.core.database.dialect_helpers import table_exists, get_version_num_length

    dialect_name = connection.dialect.name
    if dialect_name not in ("mysql", "dm"):
        return

    if not table_exists(connection, "alembic_version"):
        connection.execute(
            text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(255) NOT NULL PRIMARY KEY"
                ")"
            )
        )
        return

    length = get_version_num_length(connection)
    if length is not None and int(length) < 255:
        # Column resize has no dialect-agnostic Alembic API outside a migration
        # context. Both MySQL and DaMeng support MODIFY syntax for ALTER TABLE.
        connection.execute(
            text("ALTER TABLE alembic_version MODIFY version_num VARCHAR(255) NOT NULL")
        )


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    from bisheng.core.database.manager import sync_get_database_connection
    database_conn_manager = sync_get_database_connection()

    with database_conn_manager.engine.connect() as connection:
        ensure_alembic_version_table(connection)
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

        # SQLAlchemy 2 autobegin can leave a pending DML transaction on
        # MySQL even when Alembic treats DDL as non-transactional. Commit
        # it explicitly so backfills and alembic_version updates persist.
        finalize_online_migration_connection(connection)


run_migrations_online()

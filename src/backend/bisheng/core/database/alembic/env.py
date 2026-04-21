from logging.config import fileConfig

from sqlalchemy import text

from alembic import context

from bisheng.common.models.base import SQLModelSerializable

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
    """Ensure long local revision ids fit into Alembic's version table."""
    dialect_name = connection.dialect.name
    if dialect_name != "mysql":
        return

    table_exists = connection.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'alembic_version'"
        )
    ).scalar()
    if not table_exists:
        connection.execute(
            text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(255) NOT NULL, "
                "PRIMARY KEY (version_num)"
                ")"
            )
        )
        return

    column_len = connection.execute(
        text(
            "SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'alembic_version' "
            "AND COLUMN_NAME = 'version_num'"
        )
    ).scalar()
    if column_len is not None and int(column_len) < 255:
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


run_migrations_online()

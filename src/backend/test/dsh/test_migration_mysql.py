"""F062 existing-user DDL against an explicitly isolated MySQL database."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_existing_user_additive_migration(dsh_database_url):
    engine = create_engine(dsh_database_url)
    assert engine.dialect.name == "mysql", "This test is the isolated MySQL migration gate"
    path = Path(__file__).resolve().parents[2] / "bisheng/core/database/alembic/versions/v3_0_0_f062_profile_version.py"
    spec = importlib.util.spec_from_file_location("f062_mysql_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        assert not inspect(connection).has_table("user"), "Refuse to modify a database with an existing user table"
        connection.execute(text("CREATE TABLE user (user_id INTEGER PRIMARY KEY, user_name VARCHAR(64) NOT NULL)"))
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO user VALUES (1, 'f062-test-only')"))
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
            assert connection.execute(text("SELECT dsh_profile_version FROM user")).scalar_one() == 0
            connection.execute(text("UPDATE user SET dsh_profile_version=7"))
            migration.downgrade()
            assert connection.execute(text("SELECT dsh_profile_version FROM user")).scalar_one() == 7
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE user"))
        engine.dispose()

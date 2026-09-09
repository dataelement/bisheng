"""Opt-in real MySQL acceptance for the additive F062 user profile migration."""

import importlib.util
import os
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import BigInteger, Column, Integer, MetaData, Table, create_engine, inspect, select
from sqlalchemy.engine import make_url


@pytest.fixture
def isolated_user_table():
    value = os.environ.get("DSH_PROFILE_MIGRATION_MYSQL_URL")
    if not value:
        pytest.skip("Set DSH_PROFILE_MIGRATION_MYSQL_URL to an isolated MySQL test database")
    if os.environ.get("DSH_PROFILE_MIGRATION_ISOLATED") != "1":
        raise pytest.UsageError("DSH_PROFILE_MIGRATION_ISOLATED=1 is required")
    url = make_url(value)
    if url.get_backend_name() != "mysql" or not (url.database or "").startswith("dsh_test_"):
        raise pytest.UsageError("Migration acceptance requires MySQL and a dsh_test_ database name")
    engine = create_engine(url, echo=False, hide_parameters=True)
    user = Table("user", MetaData(), Column("user_id", Integer, primary_key=True))
    created = False
    try:
        with engine.begin() as connection:
            if "user" in {name.casefold() for name in inspect(connection).get_table_names()}:
                raise pytest.UsageError("Refusing to change a pre-existing user table")
            user.create(connection, checkfirst=False)
            created = True
            connection.execute(user.insert().values(user_id=1))
        yield engine
    finally:
        try:
            if created:
                # Only this fixture-created table is removed; no pre-existing objects are touched.
                with engine.begin() as connection:
                    user.drop(connection, checkfirst=False)
        finally:
            engine.dispose()


def test_real_mysql_profile_upgrade_is_idempotent_and_downgrade_retains_counter(isolated_user_table):
    migration_file = (
        Path(__file__).resolve().parents[2] / "bisheng/core/database/alembic/versions/v3_0_0_f062_profile_version.py"
    )
    spec = importlib.util.spec_from_file_location("dsh_profile_migration_mysql_acceptance", migration_file)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with isolated_user_table.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        fields = {field["name"]: field for field in inspect(connection).get_columns("user")}
        version = fields["dsh_profile_version"]
        assert isinstance(version["type"], BigInteger)
        assert version["nullable"] is False
        assert str(version["default"]).strip("'\"() ") == "0"
        user = Table("user", MetaData(), autoload_with=connection)
        assert connection.execute(select(user.c.user_id, user.c.dsh_profile_version)).all() == [(1, 0)]
        connection.execute(user.update().where(user.c.user_id == 1).values(dsh_profile_version=7))
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert "dsh_profile_version" in {field["name"] for field in inspect(connection).get_columns("user")}
    with isolated_user_table.begin() as connection:
        retained = Table("user", MetaData(), autoload_with=connection)
        assert (
            connection.execute(select(retained.c.dsh_profile_version).where(retained.c.user_id == 1)).scalar_one() == 7
        )
        connection.execute(retained.insert().values(user_id=2))
        assert (
            connection.execute(select(retained.c.dsh_profile_version).where(retained.c.user_id == 2)).scalar_one() == 0
        )

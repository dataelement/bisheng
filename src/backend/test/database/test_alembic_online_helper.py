from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect

from bisheng.core.database.alembic_helpers.online import (
    bootstrap_fresh_database_schema,
    finalize_online_migration_connection,
)


def _model_metadata() -> MetaData:
    metadata = MetaData()
    Table("knowledge", metadata, Column("id", Integer, primary_key=True))
    Table("assistant", metadata, Column("id", Integer, primary_key=True))
    return metadata


class TestBootstrapFreshDatabaseSchema:
    def test_creates_model_tables_for_empty_database(self):
        engine = create_engine("sqlite://")
        metadata = _model_metadata()

        with engine.connect() as connection:
            created = bootstrap_fresh_database_schema(connection, metadata)

            assert created is True
            assert set(inspect(connection).get_table_names()) == {"assistant", "knowledge"}
            assert bootstrap_fresh_database_schema(connection, metadata) is False

    def test_allows_empty_version_table_left_by_failed_first_start(self):
        engine = create_engine("sqlite://")
        metadata = _model_metadata()
        version_metadata = MetaData()
        Table(
            "alembic_version",
            version_metadata,
            Column("version_num", String(255), primary_key=True),
        )

        with engine.connect() as connection:
            version_metadata.create_all(connection)

            assert bootstrap_fresh_database_schema(connection, metadata) is True
            assert set(inspect(connection).get_table_names()) == {
                "alembic_version",
                "assistant",
                "knowledge",
            }

    def test_does_not_bootstrap_database_with_recorded_revision(self):
        engine = create_engine("sqlite://")
        metadata = _model_metadata()
        version_metadata = MetaData()
        version_table = Table(
            "alembic_version",
            version_metadata,
            Column("version_num", String(255), primary_key=True),
        )

        with engine.connect() as connection:
            version_metadata.create_all(connection)
            connection.execute(version_table.insert().values(version_num="existing_revision"))

            assert bootstrap_fresh_database_schema(connection, metadata) is False
            assert inspect(connection).get_table_names() == ["alembic_version"]

    def test_does_not_fill_partially_initialized_database(self):
        engine = create_engine("sqlite://")
        metadata = _model_metadata()

        with engine.connect() as connection:
            metadata.tables["knowledge"].create(connection)

            assert bootstrap_fresh_database_schema(connection, metadata) is False
            assert inspect(connection).get_table_names() == ["knowledge"]

    def test_rejects_empty_model_metadata(self):
        engine = create_engine("sqlite://")

        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="empty model metadata"):
                bootstrap_fresh_database_schema(connection, MetaData())


class TestFinalizeOnlineMigrationConnection:
    def test_commits_when_connection_still_has_implicit_transaction(self):
        connection = MagicMock()
        connection.in_transaction.return_value = True

        committed = finalize_online_migration_connection(connection)

        assert committed is True
        connection.commit.assert_called_once_with()

    def test_noop_when_connection_has_no_open_transaction(self):
        connection = MagicMock()
        connection.in_transaction.return_value = False

        committed = finalize_online_migration_connection(connection)

        assert committed is False
        connection.commit.assert_not_called()

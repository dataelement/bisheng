from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect

from bisheng.core.database.alembic_helpers.online import (
    create_missing_model_tables,
    finalize_online_migration_connection,
    should_create_model_tables,
)


def _model_metadata() -> MetaData:
    metadata = MetaData()
    Table("knowledge", metadata, Column("id", Integer, primary_key=True))
    Table("assistant", metadata, Column("id", Integer, primary_key=True))
    return metadata


class TestCreateMissingModelTables:
    def test_creates_model_tables_for_empty_database(self):
        engine = create_engine("sqlite://")
        metadata = _model_metadata()

        with engine.connect() as connection:
            created = create_missing_model_tables(connection, metadata)

            assert created == ("assistant", "knowledge")
            assert set(inspect(connection).get_table_names()) == {"assistant", "knowledge"}
            assert create_missing_model_tables(connection, metadata) == ()

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

            assert create_missing_model_tables(connection, metadata) == ("assistant", "knowledge")
            assert set(inspect(connection).get_table_names()) == {
                "alembic_version",
                "assistant",
                "knowledge",
            }

    def test_fills_database_with_recorded_revision(self):
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

            assert create_missing_model_tables(connection, metadata) == ("assistant", "knowledge")
            assert set(inspect(connection).get_table_names()) == {
                "alembic_version",
                "assistant",
                "knowledge",
            }

    def test_fills_partially_initialized_database_without_altering_existing_table(self):
        engine = create_engine("sqlite://")
        metadata = MetaData()
        Table(
            "knowledge",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("name", String(255)),
        )
        Table("assistant", metadata, Column("id", Integer, primary_key=True))
        existing_metadata = MetaData()
        Table("knowledge", existing_metadata, Column("id", Integer, primary_key=True))

        with engine.connect() as connection:
            existing_metadata.create_all(connection)

            assert create_missing_model_tables(connection, metadata) == ("assistant",)
            assert set(inspect(connection).get_table_names()) == {"assistant", "knowledge"}
            assert [column["name"] for column in inspect(connection).get_columns("knowledge")] == ["id"]

    def test_rejects_empty_model_metadata(self):
        engine = create_engine("sqlite://")

        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="empty model metadata"):
                create_missing_model_tables(connection, MetaData())


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


class TestShouldCreateModelTables:
    @staticmethod
    def _context(operation: str, *, as_sql: bool = False):
        def migration_operation():
            return None

        migration_operation.__name__ = operation
        return SimpleNamespace(opts={"fn": migration_operation}, as_sql=as_sql)

    def test_allows_online_upgrade(self):
        assert should_create_model_tables(self._context("upgrade")) is True

    @pytest.mark.parametrize("operation", ["downgrade", "stamp", "current"])
    def test_rejects_non_upgrade_operations(self, operation):
        assert should_create_model_tables(self._context(operation)) is False

    def test_rejects_offline_upgrade(self):
        assert should_create_model_tables(self._context("upgrade", as_sql=True)) is False

from types import SimpleNamespace
from unittest.mock import call, patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import String

from bisheng.core.database.alembic.versions import (
    v2_6_0_f064_add_qa_expert_job_fields as migration,
)


def test_migration_metadata_extends_current_head() -> None:
    assert migration.revision == "f064_add_qa_expert_job_fields"
    assert migration.down_revision == "f063_knowledge_file_pdf_artifact"


def test_upgrade_adds_all_missing_nullable_job_fields() -> None:
    connection = SimpleNamespace()
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "column_exists", return_value=False) as column_exists,
        patch.object(migration.op, "add_column") as add_column,
    ):
        migration.upgrade()

    assert column_exists.call_args_list == [
        call(connection, "qa_expert", "position"),
        call(connection, "qa_expert", "job_family"),
        call(connection, "qa_expert", "job_category"),
    ]
    columns = [one.args[1] for one in add_column.call_args_list]
    assert [column.name for column in columns] == [
        "position",
        "job_family",
        "job_category",
    ]
    assert all(isinstance(column.type, String) for column in columns)
    assert all(column.type.length == 255 for column in columns)
    assert all(column.nullable is True for column in columns)
    assert [column.comment for column in columns] == [
        "Expert position",
        "Expert job family",
        "Expert job category",
    ]


def test_upgrade_skips_existing_columns_and_adds_remaining_columns() -> None:
    connection = SimpleNamespace()
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(
            migration,
            "column_exists",
            side_effect=lambda _connection, _table, column: column == "position",
        ),
        patch.object(migration.op, "add_column") as add_column,
    ):
        migration.upgrade()

    assert [one.args[1].name for one in add_column.call_args_list] == [
        "job_family",
        "job_category",
    ]


def test_upgrade_returns_when_table_does_not_exist() -> None:
    connection = SimpleNamespace()
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=False),
        patch.object(migration, "column_exists") as column_exists,
        patch.object(migration.op, "add_column") as add_column,
    ):
        migration.upgrade()

    column_exists.assert_not_called()
    add_column.assert_not_called()


def test_downgrade_drops_existing_columns_in_reverse_order() -> None:
    connection = SimpleNamespace()
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "column_exists", return_value=True),
        patch.object(migration.op, "drop_column") as drop_column,
    ):
        migration.downgrade()

    assert drop_column.call_args_list == [
        call("qa_expert", "job_category"),
        call("qa_expert", "job_family"),
        call("qa_expert", "position"),
    ]


def test_downgrade_returns_when_table_does_not_exist() -> None:
    connection = SimpleNamespace()
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=False),
        patch.object(migration, "column_exists") as column_exists,
        patch.object(migration.op, "drop_column") as drop_column,
    ):
        migration.downgrade()

    column_exists.assert_not_called()
    drop_column.assert_not_called()


def test_migration_round_trip_on_sqlite() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE qa_expert (id INTEGER PRIMARY KEY)"))
        operations = Operations(MigrationContext.configure(connection))

        with (
            patch.object(migration.op, "get_bind", return_value=connection),
            patch.object(migration.op, "add_column", wraps=operations.add_column),
            patch.object(migration.op, "drop_column", wraps=operations.drop_column),
        ):
            migration.upgrade()
            migration.upgrade()

            column_names = {column["name"] for column in sa.inspect(connection).get_columns("qa_expert")}
            assert column_names == {
                "id",
                "position",
                "job_family",
                "job_category",
            }

            migration.downgrade()

        remaining_columns = {column["name"] for column in sa.inspect(connection).get_columns("qa_expert")}
        assert remaining_columns == {"id"}

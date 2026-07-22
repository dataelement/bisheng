from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from bisheng.core.database.alembic.versions import (
    v2_6_0_f066_token_file_sync_rule as migration,
)
from bisheng.core.database.dialect_helpers import JsonType
from bisheng.developer_token.domain.models import DeveloperToken


def test_migration_extends_f064_head() -> None:
    assert migration.revision == "f066_token_file_sync_rule"
    assert migration.down_revision == "f064_add_qa_expert_job_fields"


def test_model_maps_nullable_json_rule() -> None:
    column = DeveloperToken.__table__.c.file_sync_rule

    assert isinstance(column.type, JsonType)
    assert column.nullable is True


def test_upgrade_adds_only_nullable_json_column() -> None:
    connection = SimpleNamespace()
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "column_exists", return_value=False),
        patch.object(migration.op, "add_column") as add_column,
        patch.object(migration.op, "execute") as execute,
    ):
        migration.upgrade()

    add_column.assert_called_once()
    table_name, column = add_column.call_args.args
    assert table_name == "developer_token"
    assert column.name == "file_sync_rule"
    assert isinstance(column.type, JsonType)
    assert column.nullable is True
    assert column.server_default is None
    execute.assert_not_called()


def test_upgrade_and_downgrade_are_guarded() -> None:
    connection = SimpleNamespace()
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=False),
        patch.object(migration, "column_exists") as column_exists,
        patch.object(migration.op, "add_column") as add_column,
        patch.object(migration.op, "drop_column") as drop_column,
    ):
        migration.upgrade()
        migration.downgrade()

    column_exists.assert_not_called()
    add_column.assert_not_called()
    drop_column.assert_not_called()


def test_migration_round_trip_preserves_existing_rows_as_null() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE developer_token (id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL)"))
        connection.execute(sa.text("INSERT INTO developer_token (id, name) VALUES (1, 'existing')"))
        operations = Operations(MigrationContext.configure(connection))

        with (
            patch.object(migration.op, "get_bind", return_value=connection),
            patch.object(migration.op, "add_column", wraps=operations.add_column),
            patch.object(migration.op, "drop_column", wraps=operations.drop_column),
        ):
            migration.upgrade()
            migration.upgrade()

            columns = {column["name"]: column for column in sa.inspect(connection).get_columns("developer_token")}
            assert columns["file_sync_rule"]["nullable"] is True
            value = connection.execute(sa.text("SELECT file_sync_rule FROM developer_token WHERE id = 1")).scalar_one()
            assert value is None

            migration.downgrade()

        remaining = {column["name"] for column in sa.inspect(connection).get_columns("developer_token")}
        assert remaining == {"id", "name"}

    engine.dispose()

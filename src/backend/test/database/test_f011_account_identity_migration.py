"""AC-32: additive identity metadata, idempotent DDL, guarded rollback."""

from importlib import import_module
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from bisheng.user.domain.models.account_identity import UserAccountReservation, UserIdentityWriteGuard
from bisheng.user.domain.models.user import User

migration = import_module("bisheng.core.database.alembic.versions.v3_1_0_f011_account_identity")


def test_upgrade_only_adds_metadata_and_extends_uniqueness():
    with (
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "column_exists", return_value=False),
        patch.object(
            migration, "unique_constraint_exists", side_effect=lambda _table, name: name == "uk_user_source_external_id"
        ),
        patch.object(migration, "index_exists", return_value=False),
        patch.object(migration, "op") as op,
    ):
        migration.upgrade()
    assert [call.args[1].name for call in op.add_column.call_args_list] == [
        "account_rule_version",
        "account_match_key",
        "nickname_customized",
        "legacy_sso_name",
    ]
    op.alter_column.assert_not_called()
    op.execute.assert_not_called()
    assert op.create_unique_constraint.call_args.args[2] == ["source", "external_id", "account_match_key"]
    op.drop_constraint.assert_called_once_with("uk_user_source_external_id", "user", type_="unique")


def test_upgrade_existing_schema_is_idempotent():
    with (
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "column_exists", return_value=True),
        patch.object(
            migration,
            "unique_constraint_exists",
            side_effect=lambda _table, name: name == "uk_user_source_account_match",
        ),
        patch.object(migration, "index_exists", return_value=False),
        patch.object(migration, "op") as op,
    ):
        migration.upgrade()
    op.add_column.assert_not_called()
    op.create_unique_constraint.assert_not_called()
    op.drop_constraint.assert_not_called()


def test_downgrade_refuses_to_erase_active_new_rules():
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = 1
    with (
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "column_exists", return_value=True),
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration.op, "drop_column") as drop,
    ):
        with pytest.raises(RuntimeError, match=r"forward|roll|identity"):
            migration.downgrade()
    drop.assert_not_called()


def test_upgrade_copies_the_legacy_sso_name_comparison_from_the_actual_mysql_column():
    connection = MagicMock()
    connection.dialect.name = "mysql"
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["user"]
    original = mysql.VARCHAR(128, charset="utf8mb4", collation="utf8mb4_bin")
    inspector.get_columns.return_value = [{"name": "user_name", "type": original}]
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration.sa, "inspect", return_value=inspector),
    ):
        copied = migration._legacy_name_type()
    assert copied is not original
    assert copied.length == 128 and copied.charset == "utf8mb4" and copied.collation == "utf8mb4_bin"


@pytest.mark.parametrize("dialect_name", ["mysql", "dm"])
def test_identity_models_compile_with_both_production_dialects(dialect_name):
    dialect = mysql.dialect() if dialect_name == "mysql" else pytest.importorskip("dmSQLAlchemy.dmpython").dialect()
    for model in (User, UserAccountReservation, UserIdentityWriteGuard):
        ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
        assert "CREATE TABLE" in ddl.upper()
        if dialect_name == "dm":
            assert "COLLATE" not in ddl.upper()
    assert User.__table__.c.user_name.type.length == 128
    assert User.__table__.c.external_id.type.length == 255

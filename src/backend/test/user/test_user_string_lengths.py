from unittest.mock import patch

import pytest
from sqlalchemy import String

from bisheng.core.database.alembic.versions import v3_0_0_beta1_f056_user_string_lengths as migration
from bisheng.user.domain.models.user import User

_EXPECTED_COLUMNS = (
    ("user_name", 128, False),
    ("email", 255, True),
    ("phone_number", 64, True),
    ("dept_id", 128, True),
    ("remark", 512, True),
    ("avatar", 512, True),
    ("password", 255, False),
)


@pytest.mark.parametrize(("column_name", "length", "nullable"), _EXPECTED_COLUMNS)
def test_user_string_columns_are_bounded(column_name: str, length: int, nullable: bool):
    column = User.__table__.c[column_name]

    assert column.type.length == length
    assert column.nullable is nullable


def test_migration_alters_all_existing_user_string_columns():
    with (
        patch.object(migration, "column_exists", return_value=True),
        patch.object(migration.op, "alter_column") as alter_column,
    ):
        migration.upgrade()

    assert alter_column.call_count == len(_EXPECTED_COLUMNS)
    for actual_call, (column_name, length, nullable) in zip(
        alter_column.call_args_list,
        _EXPECTED_COLUMNS,
        strict=True,
    ):
        assert actual_call.args == ("user", column_name)
        assert isinstance(actual_call.kwargs["existing_type"], String)
        assert isinstance(actual_call.kwargs["type_"], String)
        assert actual_call.kwargs["type_"].length == length
        assert actual_call.kwargs["existing_nullable"] is nullable


def test_migration_skips_missing_user_columns():
    with (
        patch.object(migration, "column_exists", return_value=False),
        patch.object(migration.op, "alter_column") as alter_column,
    ):
        migration.upgrade()

    alter_column.assert_not_called()

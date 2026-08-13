from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateTable

from bisheng.core.database.alembic.versions import (
    v2_6_0_f083_qa_answer_images_url_longtext as migration,
)
from bisheng.core.database.dialect_helpers import LargeText
from bisheng.database.models.qa_expert import Answer, Question


def test_qa_multi_value_asset_fields_support_long_object_reference_lists() -> None:
    images_url = ";".join(["https://minio.example/tmp-dir/image.jpg?" + "x" * 290] * 3)

    answer = Answer(question_id=29, content="回答", images_url=images_url)

    assert len(images_url) > 255
    assert answer.images_url == images_url
    assert isinstance(Answer.__table__.c.images_url.type, LargeText)
    assert isinstance(Answer.__table__.c.attachments.type, LargeText)
    assert isinstance(Question.__table__.c.attachments.type, LargeText)


def test_qa_multi_value_asset_fields_compile_to_large_text_for_mysql_and_dm() -> None:
    mysql_sql = "\n".join(
        str(CreateTable(table).compile(dialect=mysql.dialect()))
        for table in (Question.__table__, Answer.__table__)
    )
    dm_dialect = DefaultDialect()
    dm_dialect.name = "dm"
    dm_sql = "\n".join(
        str(CreateTable(table).compile(dialect=dm_dialect))
        for table in (Question.__table__, Answer.__table__)
    )

    assert mysql_sql.count("LONGTEXT") == 3
    assert dm_sql.count("CLOB") == 3


def test_migration_follows_current_branch_head() -> None:
    assert migration.revision == "f083_qa_answer_images_url_longtext"
    assert migration.down_revision == "f082_department_short_name"


def _connection(dialect: str) -> SimpleNamespace:
    return SimpleNamespace(dialect=SimpleNamespace(name=dialect), execute=MagicMock())


@pytest.mark.parametrize(
    ("dialect", "expected_existing_type", "expected_target_type"),
    [
        ("mysql", mysql.VARCHAR, mysql.LONGTEXT),
        ("dm", sa.VARCHAR, sa.CLOB),
    ],
)
def test_upgrade_widens_existing_column_for_supported_dialects(
    dialect: str,
    expected_existing_type: type,
    expected_target_type: type,
) -> None:
    connection = _connection(dialect)
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "column_exists", return_value=True),
        patch.object(migration, "get_column_type", return_value="varchar"),
        patch.object(migration.op, "alter_column") as alter_column,
    ):
        migration.upgrade()

    assert [one.args[:2] for one in alter_column.call_args_list] == list(migration._COLUMNS)
    assert all(isinstance(one.kwargs["existing_type"], expected_existing_type) for one in alter_column.call_args_list)
    assert all(isinstance(one.kwargs["type_"], expected_target_type) for one in alter_column.call_args_list)
    assert all(one.kwargs["existing_nullable"] is True for one in alter_column.call_args_list)


@pytest.mark.parametrize(
    ("table_present", "column_present", "current_type"),
    [
        (False, True, "varchar"),
        (True, False, "varchar"),
        (True, True, "longtext"),
    ],
)
def test_upgrade_is_idempotent_when_schema_needs_no_change(
    table_present: bool,
    column_present: bool,
    current_type: str,
) -> None:
    connection = _connection("mysql")
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=table_present),
        patch.object(migration, "column_exists", return_value=column_present),
        patch.object(migration, "get_column_type", return_value=current_type),
        patch.object(migration.op, "alter_column") as alter_column,
    ):
        migration.upgrade()

    alter_column.assert_not_called()


def test_downgrade_restores_varchar_when_all_values_fit() -> None:
    connection = _connection("mysql")
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "column_exists", return_value=True),
        patch.object(migration, "get_column_type", return_value="longtext"),
        patch.object(migration, "_max_column_length", return_value=255),
        patch.object(migration.op, "alter_column") as alter_column,
    ):
        migration.downgrade()

    assert [one.args[:2] for one in alter_column.call_args_list] == list(reversed(migration._COLUMNS))
    for one in alter_column.call_args_list:
        assert isinstance(one.kwargs["existing_type"], mysql.LONGTEXT)
        assert isinstance(one.kwargs["type_"], mysql.VARCHAR)
        assert one.kwargs["type_"].length == 255


def test_downgrade_rejects_values_that_would_be_truncated() -> None:
    connection = _connection("mysql")
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "column_exists", return_value=True),
        patch.object(migration, "get_column_type", return_value="longtext"),
        patch.object(migration, "_max_column_length", return_value=995),
        patch.object(migration.op, "alter_column") as alter_column,
    ):
        with pytest.raises(RuntimeError, match="existing maximum length is 995"):
            migration.downgrade()

    alter_column.assert_not_called()


def test_upgrade_skips_only_missing_targets_and_keeps_other_columns() -> None:
    connection = _connection("mysql")
    missing = ("qa_answer", "attachments")
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(
            migration,
            "column_exists",
            side_effect=lambda _bind, table, column: (table, column) != missing,
        ),
        patch.object(migration, "get_column_type", return_value="varchar"),
        patch.object(migration.op, "alter_column") as alter_column,
    ):
        migration.upgrade()

    assert [one.args[:2] for one in alter_column.call_args_list] == [
        ("qa_question", "attachments"),
        ("qa_answer", "images_url"),
    ]

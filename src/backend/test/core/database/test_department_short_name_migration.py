from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateTable

from bisheng.database.models.department import Department

MIGRATION_MODULE = "bisheng.core.database.alembic.versions.v2_6_0_f082_department_short_name"


def test_upgrade_adds_nullable_short_name_and_downgrade_removes_only_it(
    monkeypatch,
) -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE department (id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL)"))
        connection.execute(sa.text("INSERT INTO department (id, name) VALUES (1, '历史部门')"))
        monkeypatch.setattr(
            migration,
            "op",
            Operations(MigrationContext.configure(connection)),
        )

        migration.upgrade()
        migration.upgrade()

        columns = {column["name"]: column for column in sa.inspect(connection).get_columns("department")}
        legacy_short_name = connection.execute(sa.text("SELECT short_name FROM department WHERE id = 1")).scalar_one()

        assert migration.revision == "f082_department_short_name"
        assert migration.down_revision == "f081_knowledge_file_original_origin"
        assert isinstance(columns["short_name"]["type"], sa.String)
        assert columns["short_name"]["type"].length == 64
        assert columns["short_name"]["nullable"] is True
        assert columns["short_name"]["default"] is None
        assert legacy_short_name is None
        assert not sa.inspect(connection).get_indexes("department")

        migration.downgrade()
        remaining_columns = {column["name"] for column in sa.inspect(connection).get_columns("department")}
        remaining_row = connection.execute(sa.text("SELECT id, name FROM department WHERE id = 1")).one()

        assert "short_name" not in remaining_columns
        assert tuple(remaining_row) == (1, "历史部门")


def test_short_name_column_compiles_for_mysql_and_dm_compatible_dialect() -> None:
    mysql_sql = str(CreateTable(Department.__table__).compile(dialect=mysql.dialect()))
    dm_dialect = DefaultDialect()
    dm_dialect.name = "dm"
    dm_sql = str(CreateTable(Department.__table__).compile(dialect=dm_dialect))

    assert "short_name VARCHAR(64)" in mysql_sql
    assert "short_name VARCHAR(64)" in dm_sql

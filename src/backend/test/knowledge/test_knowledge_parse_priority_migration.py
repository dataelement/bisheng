from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateTable

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

MIGRATION_MODULE = "bisheng.core.database.alembic.versions.v2_6_0_f078_knowledge_parse_priority"


def test_upgrade_adds_nullable_column_without_backfill_and_downgrade_removes_it(monkeypatch) -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE knowledgefile (id INTEGER PRIMARY KEY, file_name VARCHAR(200) NOT NULL)")
        )
        connection.execute(sa.text("INSERT INTO knowledgefile (id, file_name) VALUES (1, 'legacy.pdf')"))
        monkeypatch.setattr(
            migration,
            "op",
            Operations(MigrationContext.configure(connection)),
        )

        migration.upgrade()
        columns = {column["name"]: column for column in sa.inspect(connection).get_columns("knowledgefile")}
        legacy_value = connection.execute(sa.text("SELECT parse_priority FROM knowledgefile WHERE id = 1")).scalar_one()

        assert columns["parse_priority"]["nullable"] is True
        assert legacy_value is None

        migration.downgrade()
        assert "parse_priority" not in {
            column["name"] for column in sa.inspect(connection).get_columns("knowledgefile")
        }


def test_model_column_compiles_for_mysql_and_dm_compatible_dialect() -> None:
    mysql_sql = str(CreateTable(KnowledgeFile.__table__).compile(dialect=mysql.dialect()))
    dm_dialect = DefaultDialect()
    dm_dialect.name = "dm"
    dm_sql = str(CreateTable(KnowledgeFile.__table__).compile(dialect=dm_dialect))

    assert "parse_priority VARCHAR(16)" in mysql_sql
    assert "parse_priority VARCHAR(16)" in dm_sql

from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateTable

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

MIGRATION_MODULE = "bisheng.core.database.alembic.versions.v2_6_0_f081_knowledge_file_original_origin"


def test_upgrade_adds_nullable_origin_columns_without_backfill_and_downgrade_removes_them(
    monkeypatch,
) -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE knowledgefile (id INTEGER PRIMARY KEY, user_id INTEGER, knowledge_id INTEGER NOT NULL)"
            )
        )
        connection.execute(sa.text("INSERT INTO knowledgefile (id, user_id, knowledge_id) VALUES (1, 501, 10)"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

        migration.upgrade()
        columns = {column["name"]: column for column in sa.inspect(connection).get_columns("knowledgefile")}
        legacy_origin = connection.execute(
            sa.text("SELECT original_uploader_id, original_knowledge_id FROM knowledgefile WHERE id = 1")
        ).one()

        assert migration.revision == "f081_knowledge_file_original_origin"
        assert migration.down_revision == "f080_portal_discovery_enabled"
        assert columns["original_uploader_id"]["nullable"] is True
        assert columns["original_knowledge_id"]["nullable"] is True
        assert tuple(legacy_origin) == (None, None)

        migration.downgrade()
        remaining = {column["name"] for column in sa.inspect(connection).get_columns("knowledgefile")}
        assert "original_uploader_id" not in remaining
        assert "original_knowledge_id" not in remaining


def test_origin_columns_compile_for_mysql_and_dm_compatible_dialect() -> None:
    mysql_sql = str(CreateTable(KnowledgeFile.__table__).compile(dialect=mysql.dialect()))
    dm_dialect = DefaultDialect()
    dm_dialect.name = "dm"
    dm_sql = str(CreateTable(KnowledgeFile.__table__).compile(dialect=dm_dialect))

    assert "original_uploader_id INTEGER" in mysql_sql
    assert "original_knowledge_id INTEGER" in mysql_sql
    assert "original_uploader_id INTEGER" in dm_sql
    assert "original_knowledge_id INTEGER" in dm_sql

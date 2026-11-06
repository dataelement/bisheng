"""Coverage AC: AC-66. Offline DDL checks do not establish real MySQL/DM8 acceptance."""

from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateColumn

from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent


def test_snapshot_migration_preserves_legacy_rows_and_is_idempotent():
    migration = import_module("bisheng.core.database.alembic.versions.v3_0_0_f111_matched_words")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE dsh_content_safety_event (id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO dsh_content_safety_event (id) VALUES ('e2e-word-migration')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
            with pytest.raises(RuntimeError, match="evidence must be retained"):
                migration.downgrade()
        assert connection.execute(text("SELECT matched_words FROM dsh_content_safety_event")).scalar_one() is None
        assert connection.execute(text("SELECT id FROM dsh_content_safety_event")).scalar_one() == "e2e-word-migration"
        column = next(
            item
            for item in inspect(connection).get_columns("dsh_content_safety_event")
            if item["name"] == "matched_words"
        )
        assert column["nullable"]
    engine.dispose()


def test_current_model_column_uses_portable_existing_json_type():
    column = DshContentSafetyEvent.__table__.c.matched_words
    assert column.nullable
    assert "matched_words" in str(CreateColumn(column).compile(dialect=mysql.dialect()))

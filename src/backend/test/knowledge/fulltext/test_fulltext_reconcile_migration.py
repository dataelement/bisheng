import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from bisheng.knowledge.domain.models.knowledge_fulltext_reconcile import FulltextReconcileIssue, FulltextReconcileRun


def test_migration_creates_model_columns_and_is_repeatable(monkeypatch):
    path = (
        Path(__file__).resolve().parents[3] / "bisheng/core/database/alembic/versions/v2_6_0_f106_fulltext_reconcile.py"
    )
    spec = importlib.util.spec_from_file_location("fulltext_reconcile_migration_under_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            migration.upgrade()
            for model in (FulltextReconcileRun, FulltextReconcileIssue):
                actual = {c["name"] for c in inspect(connection).get_columns(model.__tablename__)}
                assert actual == set(model.__table__.columns.keys())
                assert model.__tablename__ in str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
            migration.downgrade()
            migration.downgrade()
            assert not inspect(connection).get_table_names()
    finally:
        engine.dispose()

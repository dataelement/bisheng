"""Exercise the F077 index migration against a real local database."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_subject_search_indexes_are_reversible_and_idempotent(monkeypatch):
    path = (
        Path(__file__).resolve().parents[2]
        / "bisheng/core/database/alembic/versions"
        / "v3_0_0_f077_subject_id_search_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("f077_indexes", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for table in ("user", "department"):
            connection.execute(sa.text(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, external_id VARCHAR(255))'))
            connection.execute(sa.text(f'INSERT INTO "{table}" VALUES (1, :value)'), {"value": "local-001"})
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        monkeypatch.setattr(
            migration,
            "index_exists",
            lambda table, name: any(index["name"] == name for index in sa.inspect(connection).get_indexes(table)),
        )
        migration.upgrade()
        migration.upgrade()
        for table, name in migration._INDEXES:
            indexes = sa.inspect(connection).get_indexes(table)
            assert len(indexes) == 1
            assert indexes[0]["name"] == name
            assert indexes[0]["column_names"] == ["external_id"]
            assert not indexes[0]["unique"]
        migration.downgrade()
        migration.downgrade()
        for table, _ in migration._INDEXES:
            assert sa.inspect(connection).get_indexes(table) == []
            assert connection.execute(sa.text(f'SELECT external_id FROM "{table}"')).scalar_one() == "local-001"

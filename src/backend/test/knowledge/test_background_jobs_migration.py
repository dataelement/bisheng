from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from bisheng.core.database.alembic.versions import v2_6_0_f108_background_budgets as budgets
from bisheng.core.database.alembic.versions import v2_6_0_f109_background_jobs as jobs


def test_additive_migration_preserves_existing_retry_data_and_creates_empty_intents(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE failed_tuple (id INTEGER PRIMARY KEY, retry_count INTEGER, status VARCHAR(16))")
        )
        connection.execute(
            text("CREATE TABLE point_sync_outbox (id INTEGER PRIMARY KEY, retry_count INTEGER, status VARCHAR(16))")
        )
        for table in ("failed_tuple", "point_sync_outbox"):
            connection.execute(text(f"INSERT INTO {table} VALUES (1, 8, 'failed')"))
        operation = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(budgets, "op", operation)
        monkeypatch.setattr(jobs, "op", operation)
        budgets.upgrade()
        jobs.upgrade()
        budgets.upgrade()
        jobs.upgrade()
        for table in ("failed_tuple", "point_sync_outbox"):
            assert connection.execute(text(f"SELECT retry_count, status FROM {table}")).one() == (8, "failed")
        assert connection.execute(text("SELECT COUNT(*) FROM knowledge_background_job")).scalar() == 0
        assert "lease_owner" in {column["name"] for column in inspect(connection).get_columns("point_sync_outbox")}
        jobs.downgrade()
        budgets.downgrade()
        assert set(inspect(connection).get_table_names()) == {"failed_tuple", "point_sync_outbox"}
    engine.dispose()

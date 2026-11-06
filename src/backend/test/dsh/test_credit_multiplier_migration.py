from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_multiplier_migration_preserves_legacy_usage_and_repeats_safely():
    migration = import_module("bisheng.core.database.alembic.versions.f062_credit_multiplier")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE dsh_model_visibility (model_id BIGINT)"))
        connection.execute(text("CREATE TABLE dsh_model_call (total_tokens BIGINT)"))
        connection.execute(text("INSERT INTO dsh_model_visibility VALUES (7)"))
        connection.execute(text("INSERT INTO dsh_model_call VALUES (80)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        assert connection.execute(text("SELECT credit_rate FROM dsh_model_visibility")).scalar_one() == 100
        assert tuple(
            connection.execute(text("SELECT total_tokens, credit_rate, billed_tokens FROM dsh_model_call")).one()
        ) == (80, 100, None)
    engine.dispose()

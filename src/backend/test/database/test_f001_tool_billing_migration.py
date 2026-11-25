from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_f001_sqlite_upgrade_backfills_usage_and_creates_tool_pricing():
    revision = import_module("bisheng.core.database.alembic.versions.v3_1_0_f001_credit_billing_extension")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE dsh_monthly_usage (tenant_id INTEGER, user_id INTEGER, usage_month VARCHAR(7),"
            " model_id INTEGER, CONSTRAINT uq_dsh_usage_user_model_month"
            " UNIQUE (tenant_id, user_id, usage_month, model_id))"
        )
        connection.exec_driver_sql("INSERT INTO dsh_monthly_usage VALUES (1, 2, '2026-11', 3)")
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
            revision.upgrade()
            connection.exec_driver_sql("INSERT INTO dsh_tool_pricing (tenant_id, tool_id, updated_by) VALUES (1, 3, 2)")
            connection.exec_driver_sql("INSERT INTO dsh_monthly_usage VALUES (1, 2, '2026-11', 3, 'TOOL')")
            assert connection.exec_driver_sql("SELECT update_time FROM dsh_tool_pricing").scalar_one()
            assert connection.exec_driver_sql(
                "SELECT usage_type FROM dsh_monthly_usage ORDER BY usage_type"
            ).scalars().all() == ["MODEL", "TOOL"]
            revision.downgrade()
        assert connection.exec_driver_sql("SELECT model_id FROM dsh_monthly_usage").scalars().all() == [3]
        assert not inspect(connection).has_table("dsh_tool_pricing")

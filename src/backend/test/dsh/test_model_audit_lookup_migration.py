"""Real DDL replay is idempotent for both upgraded and model-created audit tables."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest


def migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "bisheng/core/database/alembic/versions/v3_0_0_work110_dsh_audit_model_lookup.py"
    )
    spec = importlib.util.spec_from_file_location("audit_lookup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("fresh", [False, True])
def test_migration_adds_only_missing_schema_and_never_backfills_rows(fresh):
    revision = migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        if fresh:
            DshModelAuditRequest.__table__.create(connection)
        else:
            connection.exec_driver_sql(
                "CREATE TABLE dsh_model_audit_request (request_id VARCHAR(36) PRIMARY KEY, tenant_id BIGINT, model_id BIGINT, model_name VARCHAR(2048), started_at DATETIME)"
            )
            connection.exec_driver_sql(
                "INSERT INTO dsh_model_audit_request VALUES ('e2e-legacy',2,42,'Provider / Old','2026-10-15')"
            )
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
            revision.upgrade()
        columns = {column["name"]: column for column in sa.inspect(connection).get_columns(revision.TABLE)}
        assert columns["model_name_digest"]["nullable"]
        indexes = {index["name"]: index["column_names"] for index in sa.inspect(connection).get_indexes(revision.TABLE)}
        for name, expected in revision.INDEXES.items():
            assert indexes[name] == expected
        if not fresh:
            assert connection.exec_driver_sql(
                "SELECT model_name,model_name_digest FROM dsh_model_audit_request"
            ).one() == ("Provider / Old", None)


def test_mysql_and_dm_indexes_have_only_bounded_columns():
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateIndex

    for index in DshModelAuditRequest.__table__.indexes:
        if index.name in migration().INDEXES:
            ddl = str(CreateIndex(index).compile(dialect=dialect()))
            assert "model_name," not in ddl and "LIKE" not in ddl
            assert all(not isinstance(column.type, sa.String) or column.type.length <= 64 for column in index.columns)

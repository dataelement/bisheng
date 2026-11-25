"""Offline bootstrap, downgrade guard and operation identity regression tests."""

from importlib import import_module

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql
from sqlmodel import SQLModel

from bisheng.core.database.tenant_filter import _TENANT_AWARE_MODEL_MODULES
from bisheng.knowledge.domain.models import provider_control, provider_tag_import

migration = import_module("bisheng.core.database.alembic.versions.v3_1_0_f026_provider_control")


def test_f026_tables_bootstrap_and_protected_downgrade():
    names = migration.CONTROL_TABLES
    tables = [SQLModel.metadata.tables[name] for name in names]
    assert {provider_control.__name__, provider_tag_import.__name__}.issubset(_TENANT_AWARE_MODEL_MODULES)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        with pytest.raises(RuntimeError, match="bootstrap incomplete"):
            migration.upgrade()
        SQLModel.metadata.create_all(conn, tables=tables)
        migration.upgrade()
        migration.upgrade()
        instance = tables[-1]
        conn.execute(
            instance.insert().values(
                tenant_id=1, provider_key="weknora", endpoint="test", credential_ref="ref", remote_scope_id="Case"
            )
        )
        with pytest.raises(RuntimeError, match="rollback blocked"):
            migration.downgrade()
        assert conn.scalar(sa.select(sa.func.count()).select_from(instance)) == 1
        for table in tables:
            assert table.c.tenant_id.nullable is False
            assert str(sa.schema.CreateTable(table).compile(dialect=mysql.dialect()))
        # A verified empty disposable fixture models the DBA-prepared rollback boundary.
    with sa.create_engine("sqlite://").begin() as empty, Operations.context(MigrationContext.configure(empty)):
        migration.downgrade()

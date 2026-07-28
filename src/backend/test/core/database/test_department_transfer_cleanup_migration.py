from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, create_engine, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateTable

from bisheng.core.database.dialect_helpers import JsonType


def test_cleanup_models_define_required_constraints_and_indexes():
    from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
        DepartmentTransferPermissionCleanupEvent,
        DepartmentTransferPermissionCleanupItem,
    )

    event_table = DepartmentTransferPermissionCleanupEvent.__table__
    item_table = DepartmentTransferPermissionCleanupItem.__table__

    assert {constraint.name for constraint in event_table.constraints} >= {"uk_dtpc_event_key"}
    assert {index.name for index in event_table.indexes} >= {
        "idx_dtpc_status_retry",
        "idx_dtpc_user_changed",
    }
    assert {constraint.name for constraint in item_table.constraints} >= {
        "uk_dtpc_item_event_key",
    }
    assert {index.name for index in item_table.indexes} >= {
        "idx_dtpc_item_user_status",
        "idx_dtpc_item_event_status",
    }


def test_json_and_boolean_columns_compile_for_mysql_and_dm_compatible_dialect():
    metadata = MetaData()
    table = Table(
        "dtpc_compile_probe",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("snapshot", JsonType(), nullable=False),
        Column("snapshot_complete", Boolean, nullable=False),
        Column("status", String(24), nullable=False),
    )

    mysql_ddl = str(
        __import__("sqlalchemy").schema.CreateTable(table).compile(dialect=mysql.dialect()),
    )
    assert "JSON" in mysql_ddl
    assert "snapshot_complete" in mysql_ddl

    dm_dialect = DefaultDialect()
    dm_dialect.name = "dm"
    dm_ddl = str(CreateTable(table).compile(dialect=dm_dialect))
    assert "CLOB" in dm_ddl
    assert "SMALLINT" in dm_ddl

    # 迁移不得调用方言 JSON 操作符。
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "bisheng/core/database/alembic/versions/v2_6_0_f070_department_transfer_permission_cleanup.py"
    )
    spec = importlib.util.spec_from_file_location("dtpc_migration", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == (
        "f067_add_knowledge_file_alias_name",
        "f067_clinic_space_level_team_ks",
        "f069_department_space_binding_backfill",
    )


def test_cleanup_migration_upgrade_and_downgrade_smoke():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "bisheng/core/database/alembic/versions/v2_6_0_f070_department_transfer_permission_cleanup.py"
    )
    spec = importlib.util.spec_from_file_location("dtpc_migration_smoke", migration_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert set(inspect(connection).get_table_names()) >= {
            "department_transfer_permission_cleanup_event",
            "department_transfer_permission_cleanup_item",
        }

        module.downgrade()
        assert not {
            "department_transfer_permission_cleanup_event",
            "department_transfer_permission_cleanup_item",
        } & set(inspect(connection).get_table_names())

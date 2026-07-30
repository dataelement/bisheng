"""F048 schema contract tests.

覆盖 AC: AC-137, AC-138, AC-139, AC-140, AC-146, AC-158
"""

from __future__ import annotations

import ast
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import tenant_filter
from bisheng.core.database.alembic.versions import f048_permission_model_grants as revision
from bisheng.permission.domain import models as permission_models

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION_PATH = BACKEND_ROOT / "bisheng/core/database/alembic/versions/f048_permission_model_grants.py"

F048_TABLES = {
    "authorization_model_release",
    "permission_catalog_release",
    "permission_action",
    "permission_action_resource_scope",
    "permission_model",
    "permission_model_action",
    "permission_catalog_projection_tuple",
    "permission_grant",
    "permission_grant_assignee",
    "resource_permission_mode",
    "permission_projection_operation",
    "permission_projection_tuple",
    "permission_migration_run",
    "permission_migration_item",
}

TENANT_TABLES = {
    "permission_grant",
    "permission_grant_assignee",
    "resource_permission_mode",
    "permission_projection_operation",
    "permission_projection_tuple",
}


def test_f048_models_register_complete_portable_schema() -> None:
    """All F048 ORM tables have audit timestamps and portable scalar types."""

    assert permission_models.PermissionGrant.__tablename__ == "permission_grant"
    tables = SQLModel.metadata.tables
    assert F048_TABLES <= set(tables)
    for name in F048_TABLES:
        table = tables[name]
        assert {"id", "create_time", "update_time"} <= set(table.c.keys())
        model = next(
            candidate
            for candidate in SQLModelSerializable.__subclasses__()
            if getattr(candidate, "__tablename__", None) == name
        )
        assert issubclass(model, SQLModelSerializable)
        for column in table.c:
            assert not isinstance(column.type, sa.JSON)
            assert not isinstance(column.type, sa.Enum)


def test_tenant_tables_are_non_nullable_and_discovered() -> None:
    tenant_filter._force_import_all_models()
    discovered = tenant_filter._discover_tenant_aware_tables()
    assert TENANT_TABLES <= discovered
    for name in TENANT_TABLES:
        assert SQLModel.metadata.tables[name].c.tenant_id.nullable is False

    migration_item = SQLModel.metadata.tables["permission_migration_item"]
    assert migration_item.c.tenant_id.nullable is True
    assert "permission_catalog_release" not in discovered
    assert "permission_migration_run" not in discovered


def test_f048_unique_and_foreign_key_contract() -> None:
    tables = SQLModel.metadata.tables
    unique_names = {
        constraint.name
        for table_name in F048_TABLES
        for constraint in tables[table_name].constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    assert {
        "uq_perm_catalog_release_key",
        "uq_perm_action_release_code",
        "uq_perm_model_release_key",
        "uq_perm_grant_resource_model",
        "uq_perm_assignee_source",
        "uq_resource_permission_mode",
        "uq_perm_projection_idempotency",
        "uq_perm_projection_tuple",
        "uq_perm_migration_environment",
        "uq_perm_migration_item_source",
    } <= unique_names

    foreign_targets = {fk.target_fullname for table_name in F048_TABLES for fk in tables[table_name].foreign_keys}
    assert {
        "authorization_model_release.id",
        "permission_catalog_release.id",
        "permission_action.id",
        "permission_model.id",
        "permission_grant.id",
        "permission_projection_operation.id",
        "permission_migration_run.id",
    } <= foreign_targets


def test_f048_revision_is_the_single_alembic_head() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(BACKEND_ROOT / "bisheng/core/database/alembic"),
    )
    assert ScriptDirectory.from_config(config).get_heads() == ["f048_permission_grants"]


def test_f048_revision_is_static_ddl_only() -> None:
    source = REVISION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported_modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported_modules <= {
        "__future__",
        "collections.abc",
        "sqlalchemy",
        "alembic",
        "bisheng.core.database.alembic_helpers.online",
    }

    forbidden_calls = {
        "execute",
        "bulk_insert",
        "get_context",
        "get_bind().execute",
    }
    call_names = {_qualified_name(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not (forbidden_calls & call_names)
    assert all("openfga" not in module.casefold() for module in imported_modules)
    assert "config_service" not in source
    assert "permission.domain.services" not in source
    assert "scripts." not in source


def test_f048_revision_upgrade_is_idempotent_and_downgrades() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            revision.upgrade()
            assert F048_TABLES <= set(inspect(connection).get_table_names())
            revision.upgrade()
            revision.downgrade()
            assert not (F048_TABLES & set(inspect(connection).get_table_names()))


def test_f048_tables_compile_for_mysql_without_native_enum_or_json() -> None:
    for name in F048_TABLES:
        ddl = str(CreateTable(SQLModel.metadata.tables[name]).compile(dialect=mysql.dialect()))
        normalized = ddl.upper()
        assert " JSON" not in normalized
        assert " ENUM(" not in normalized


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _qualified_name(node.func)
    return ""

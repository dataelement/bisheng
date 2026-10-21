"""AC-06, AC-35, AC-61: static model contracts, without a DM8 connection."""

from importlib import import_module

import pytest
from sqlalchemy import CLOB, JSON, BigInteger, String, UniqueConstraint
from sqlalchemy.dialects.mysql import dialect as mysql_dialect
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateIndex, CreateTable

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RUNTIME_TABLES,
    RuntimeArtifact,
    RuntimeTransfer,
    ScopedRuntimeRecord,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import KUBERNETES_TABLES, RuntimeExecutionResource
from bisheng.core.database.dialect_helpers import JsonType, is_update_time_server_default
from bisheng.core.database.model_discovery import discover_sqlmodel_module_names


def test_runtime_tables_follow_discovery_scope_and_constraints():
    assert "bisheng.app_runtime.domain.models.runtime_delivery" in discover_sqlmodel_module_names()
    assert len(RUNTIME_TABLES) == 15
    assert len(KUBERNETES_TABLES) == 2
    constraint_names = set()
    for model in (*RUNTIME_TABLES, *KUBERNETES_TABLES):
        table = model.__table__
        assert tuple(table.primary_key.columns.keys()) == ("id",)
        assert not table.c.id.nullable and table.c.id.type.length == 36
        assert is_update_time_server_default(table.c.update_time.server_default)
        assert not table.dialect_kwargs
        if issubclass(model, ScopedRuntimeRecord):
            assert not table.c.tenant_id.nullable and table.c.tenant_id.index
            assert not table.c.app_id.nullable and table.c.app_id.index
        else:
            assert "tenant_id" not in table.c
        unique = [item for item in table.constraints if isinstance(item, UniqueConstraint)]
        assert len(unique) == (2 if model is RuntimeExecutionResource else 1)
        for item in unique:
            assert item.name and item.name not in constraint_names
            nullable = {column.name for column in item.columns if column.nullable}
            expected_nullable = set()
            if model is RuntimeTransfer and item.name == "uq_rt_transfer_authority":
                expected_nullable = {"authorization_id"}  # Historical rows are backfilled out of band.
            if model is RuntimeExecutionResource and item.name == "uq_rt_resource_uid":
                expected_nullable = {"uid"}  # Intent is committed before the API assigns a UID.
            assert nullable == expected_nullable
            constraint_names.add(item.name)
        for column in table.c:
            if isinstance(column.type, String):
                assert column.type.length and column.type.length <= 512


@pytest.mark.parametrize("engine", ["mysql", "dm"])
def test_runtime_models_compile_portable_types_and_defaults(engine):
    # dmPython/dmSQLAlchemy is not installed on macOS. This exercises the
    # shared helper's dm branch with SQLAlchemy's generic compiler only;
    # it does not establish driver-specific DDL or real database behavior.
    dialect = mysql_dialect() if engine == "mysql" else DefaultDialect()
    dialect.name = engine
    for model in (*RUNTIME_TABLES, *KUBERNETES_TABLES):
        table = model.__table__
        ddl = str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=dialect))
        assert "CURRENT_TIMESTAMP" in ddl
        assert ("ON UPDATE" in ddl) == (engine == "mysql")
        for column in table.c:
            if isinstance(column.type, JsonType):
                storage = column.type.load_dialect_impl(dialect)
                assert isinstance(storage, JSON if engine == "mysql" else CLOB)
                if engine == "dm":
                    assert "CLOB" in ddl and " JSON" not in ddl


@pytest.mark.parametrize("model,field", [(RuntimeArtifact, "size_bytes"), (RuntimeTransfer, "offset")])
def test_byte_counters_hold_the_documented_snapshot_limit(model, field):
    column = model.__table__.c[field]
    assert isinstance(column.type, BigInteger)
    assert not column.nullable and column.default.arg == 0
    assert 10 * 1024**3 > 2**31 - 1


def migration(monkeypatch, kind="integer", present=True):
    module = import_module("bisheng.core.database.alembic.versions.f086_runtime_byte_counters")
    calls = []
    monkeypatch.setattr(module.op, "get_bind", lambda: object())
    monkeypatch.setattr(module, "table_exists", lambda table: present)
    monkeypatch.setattr(module, "column_exists", lambda table, column: present)
    monkeypatch.setattr(module, "get_column_type", lambda *args: kind)
    monkeypatch.setattr(module.op, "alter_column", lambda *args, **kwargs: calls.append((args, kwargs)))
    return module, calls


def test_upgrade_widens_both_existing_counters(monkeypatch):
    module, calls = migration(monkeypatch)
    module.upgrade()
    assert [args for args, _ in calls] == [("runtime_artifact", "size_bytes"), ("runtime_transfer", "offset")]
    assert all(isinstance(kwargs["type_"], BigInteger) and kwargs["existing_nullable"] is False for _, kwargs in calls)
    assert module.down_revision == "merge_vibe_f077_heads"
    module.downgrade()
    assert len(calls) == 2  # A downgrade must not narrow existing large counters.


@pytest.mark.parametrize("kind,present", [("BIGINT", True), ("biginteger", True), ("integer", False)])
def test_upgrade_skips_fresh_or_missing_tables(monkeypatch, kind, present):
    module, calls = migration(monkeypatch, kind, present)
    module.upgrade()
    assert not calls


def test_upgrade_rejects_an_unexpected_column_type(monkeypatch):
    module, calls = migration(monkeypatch, "varchar")
    with pytest.raises(RuntimeError, match="Unexpected byte-counter"):
        module.upgrade()
    assert not calls

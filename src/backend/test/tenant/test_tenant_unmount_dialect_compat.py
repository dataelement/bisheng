"""F011 unmount resource-migration: dialect safety + preset exclusion.

Regression for the DaMeng (达梦) production failure on
``DELETE /api/v1/departments/{id}/mount-tenant``:

    Invalid schema name [INFORMATION_SCHEMA]
    [SQL: SELECT table_name FROM information_schema.tables
          WHERE table_schema = DATABASE()]

``_filter_existing_tables`` used the MySQL-only ``information_schema.tables`` +
``DATABASE()`` combo to skip un-migrated tables. DaMeng (Oracle-compatible) has
no ``INFORMATION_SCHEMA`` schema and no ``DATABASE()`` function, so unmount blew
up before any resource could be migrated back to Root.

The fix drops the catalog probe entirely and filters the migration whitelist
against the ORM's registered metadata (no SQL, dialect-agnostic). It also
excludes *preset* tool rows from migration: preset tools/types are copied into
every Child on creation, so Root already owns its own — migrating the Child's
copies back would duplicate them.

These tests pin the corrected contract:
  1. Source guard — the service must not reach for MySQL-only catalog SQL.
  2. ``_filter_known_tables`` keeps only whitelist entries that map to a live
     SQLModel table, and drops retired entries (``dataset`` has no model).
  3. The migration delegates to ``abulk_update_tenant_id`` with a row filter
     that excludes preset rows for the two tool tables.
  4. ``abulk_update_tenant_id`` actually appends the extra predicate to the
     UPDATE for filtered tables, and leaves other tables untouched.
"""

from __future__ import annotations

import inspect as py_inspect
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# Import the real models so their tables register in SQLModel.metadata, the
# way the FastAPI app does on startup (via api.router). `_filter_known_tables`
# inspects that metadata, so the tables it should keep must be imported here.
import bisheng.database.models.flow
import bisheng.knowledge.domain.models.knowledge
import bisheng.tool.domain.models.gpts_tools  # noqa: F401
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao
from bisheng.tenant.domain.services import tenant_mount_service
from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService


def test_filter_known_tables_avoids_mysql_only_catalog_sql():
    source = py_inspect.getsource(TenantMountService._filter_known_tables)
    assert "information_schema" not in source.lower()
    assert "DATABASE()" not in source


def test_filter_known_tables_keeps_mapped_drops_retired():
    # `flow`/`knowledge` map to live models; `dataset` has no model (retired);
    # `__totally_made_up__` never existed.
    kept = TenantMountService._filter_known_tables(["flow", "knowledge", "dataset", "__totally_made_up__"])
    assert kept == ["flow", "knowledge"]


def test_preset_row_filter_targets_the_two_tool_tables():
    filters = tenant_mount_service._UNMOUNT_MIGRATE_ROW_FILTERS
    assert set(filters) == {"t_gpts_tools", "t_gpts_tools_type"}
    for expr in filters.values():
        assert expr == "is_preset != 1"


async def test_migrate_passes_preset_row_filter_to_dao():
    captured = {}

    async def _fake_bulk(*, tables, from_tenant_id, to_tenant_id, table_row_filters):
        captured["tables"] = tables
        captured["from"] = from_tenant_id
        captured["to"] = to_tenant_id
        captured["filters"] = table_row_filters
        return dict.fromkeys(tables, 0)

    with patch.object(TenantDao, "abulk_update_tenant_id", side_effect=_fake_bulk):
        await TenantMountService._migrate_child_resources_to_root(42)

    # Retired `dataset` is filtered out; tool tables survive and carry the
    # preset-exclusion predicate.
    assert "dataset" not in captured["tables"]
    assert "t_gpts_tools" in captured["tables"]
    assert captured["from"] == 42
    assert captured["to"] == ROOT_TENANT_ID
    assert captured["filters"] == {
        "t_gpts_tools": "is_preset != 1",
        "t_gpts_tools_type": "is_preset != 1",
    }


async def test_abulk_update_appends_extra_predicate_only_where_given():
    executed: list[str] = []

    class _Res:
        rowcount = 0

    session = MagicMock()
    session.execute = AsyncMock(side_effect=lambda stmt, params: (executed.append(str(stmt)), _Res())[1])
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    @asynccontextmanager
    async def _fake_factory():
        yield session

    with (
        patch.object(tenant_mount_service, "get_async_db_session", _fake_factory),
        patch("bisheng.database.models.tenant.get_async_db_session", _fake_factory),
    ):
        await TenantDao.abulk_update_tenant_id(
            tables=["flow", "t_gpts_tools"],
            from_tenant_id=7,
            to_tenant_id=ROOT_TENANT_ID,
            table_row_filters={"t_gpts_tools": "is_preset != 1"},
        )

    flow_sql = next(s for s in executed if "flow" in s)
    tools_sql = next(s for s in executed if "t_gpts_tools" in s)
    assert "AND is_preset != 1" not in flow_sql
    assert "AND is_preset != 1" in tools_sql

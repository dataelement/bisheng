"""A child tenant resolves a builtin tool_key to its own row, not the root row.

Every tenant owns one row per builtin tool_key (unique on tool_key + tenant_id).
The tenant filter lets a child tenant also see root rows (visible set {child, 1}),
so an unordered ``.first()`` returned the root row. On 114 (2026-11-20) this
made a child-tenant user's explicit selection of the code interpreter (own row
id 90010) look implicit: the use-permission check ran against the root tenant's
tool type, failed, and the interpreter was silently dropped.

SQLite returns rows in rowid order, so each test inserts the root row first.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.tool.domain.models import gpts_tools as gpts_mod
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao

CODE_KEY = "bisheng_code_interpreter"
ROOT_TENANT, CHILD_TENANT, OTHER_CHILD, BARE_CHILD = 1, 36, 38, 40
ROOT_ROW, CHILD_ROW, OTHER_ROW = 6, 90010, 90047


@pytest.fixture
def tool_store(tmp_path, monkeypatch):
    from bisheng.core.database import tenant_filter

    database = tmp_path / "tools.sqlite"
    engine = create_engine(f"sqlite:///{database}")
    SQLModel.metadata.create_all(engine, tables=[GptsTools.__table__])
    with Session(engine) as session, bypass_tenant_filter():
        # Root row first: an unordered lookup would return it.
        session.add(GptsTools(id=ROOT_ROW, name="code", tool_key=CODE_KEY, type=6, tenant_id=ROOT_TENANT))
        session.add(GptsTools(id=CHILD_ROW, name="code", tool_key=CODE_KEY, type=22, tenant_id=CHILD_TENANT))
        session.add(GptsTools(id=OTHER_ROW, name="code", tool_key=CODE_KEY, type=38, tenant_id=OTHER_CHILD))
        session.commit()
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{database}")

    @asynccontextmanager
    async def async_session():
        async with AsyncSession(async_engine) as session:
            yield session

    @contextmanager
    def sync_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(gpts_mod, "get_async_db_session", async_session)
    monkeypatch.setattr(gpts_mod, "get_sync_db_session", sync_session)

    # Real tenant filter: the child sees its own rows plus root rows.
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    tenant_filter.register_tenant_filter_events()
    assert "t_gpts_tools" in tenant_filter._tenant_aware_tables
    yield
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    engine.dispose()


@contextmanager
def _as_child(tenant_id: int):
    tid_token = set_current_tenant_id(tenant_id)
    vis_token = set_visible_tenant_ids(frozenset({tenant_id, ROOT_TENANT}))
    try:
        yield
    finally:
        visible_tenant_ids.reset(vis_token)
        current_tenant_id.reset(tid_token)


async def test_async_lookup_prefers_current_tenant_row(tool_store):
    with _as_child(CHILD_TENANT):
        row = await GptsToolsDao.aget_tool_by_tool_key(tool_key=CODE_KEY)
    assert (row.id, row.type) == (CHILD_ROW, 22)


def test_sync_lookup_prefers_current_tenant_row(tool_store):
    with _as_child(CHILD_TENANT):
        row = GptsToolsDao.get_tool_by_tool_key(CODE_KEY)
    assert (row.id, row.type) == (CHILD_ROW, 22)


async def test_tenant_without_own_row_falls_back_to_visible_root_row(tool_store):
    with _as_child(BARE_CHILD):
        row = await GptsToolsDao.aget_tool_by_tool_key(tool_key=CODE_KEY)
        sync_row = GptsToolsDao.get_tool_by_tool_key(CODE_KEY)
    assert row.id == ROOT_ROW
    assert sync_row.id == ROOT_ROW


async def test_root_tenant_still_resolves_root_row(tool_store):
    tid_token = set_current_tenant_id(ROOT_TENANT)
    try:
        row = await GptsToolsDao.aget_tool_by_tool_key(tool_key=CODE_KEY)
    finally:
        current_tenant_id.reset(tid_token)
    assert row.id == ROOT_ROW


@pytest.fixture
def code_tool_binding(monkeypatch):
    from bisheng.tool.domain.services.executor import ToolExecutor

    async def tool_type(tool_type_id):
        return SimpleNamespace(id=tool_type_id, tenant_id=None, extra={"type": "container"})

    monkeypatch.setattr(GptsToolsDao, "aget_one_tool_type", AsyncMock(side_effect=tool_type))
    permission = AsyncMock()
    monkeypatch.setattr(ToolExecutor, "_ensure_use_permission_async", permission)
    init_one = AsyncMock(return_value=object())
    monkeypatch.setattr(ToolExecutor, "init_by_tool_id", init_one)
    return SimpleNamespace(permission=permission, init_one=init_one)


async def test_child_tenant_explicit_selection_binds_own_interpreter(tool_store, code_tool_binding, tmp_path):
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    selected = [100, CHILD_ROW]
    with _as_child(CHILD_TENANT):
        tools = await LinsightWorkbenchImpl._init_bisheng_code_tool(selected, str(tmp_path), 90022)

    assert len(tools) == 1
    # Recognised as the explicit selection: consumed so it is not built twice.
    assert selected == [100]
    checked_type = code_tool_binding.permission.await_args.args[0]
    assert checked_type.id == 22
    assert code_tool_binding.init_one.await_args.kwargs["tool"].id == CHILD_ROW


async def test_child_tenant_explicit_selection_denied_still_raises(tool_store, code_tool_binding, tmp_path):
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    code_tool_binding.permission.side_effect = PermissionError("denied")
    with _as_child(CHILD_TENANT), pytest.raises(PermissionError):
        await LinsightWorkbenchImpl._init_bisheng_code_tool([CHILD_ROW], str(tmp_path), 90022)
    code_tool_binding.init_one.assert_not_awaited()

"""Upgrade path for the web fetch built-in tool (F085 design decision 8).

An existing database never re-imports the seed JSON, so startup inserts the
root rows, projects their permission and copies them to child tenants.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common import init_data
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.permission.application.system_resource_reconcile import SystemOwnedResourceSpec
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType


@pytest.fixture()
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=[GptsTools.__table__, GptsToolsType.__table__])
    db_session = AsyncSession(bind=engine, expire_on_commit=False)
    yield db_session
    await db_session.close()
    await engine.dispose()


async def _rows(session):
    types = (await session.exec(select(GptsToolsType))).all()
    tools = (await session.exec(select(GptsTools))).all()
    return types, tools


async def test_inserts_type_and_tool_matching_the_seed(session):
    inserted = await init_data._ensure_web_fetch_tool(session)

    types, tools = await _rows(session)
    assert inserted is True
    assert [row.name for row in types] == ["网页读取"]
    assert len(tools) == 1
    tool, tool_type = tools[0], types[0]
    assert tool.tool_key == "web_fetch"
    assert tool.type == tool_type.id
    assert tool.tenant_id == tool_type.tenant_id == 1
    assert tool.is_preset == tool_type.is_preset == 1
    assert tool.user_id is None and tool_type.user_id is None
    assert [param["name"] for param in tool.api_params] == ["url"]
    assert json.loads(tool_type.extra) == {
        "type": "deepseek",
        "config": {"deepseek": {"api_key": "", "base_url": ""}},
        "max_chars": 20000,
    }


async def test_second_run_does_not_insert_again(session):
    await init_data._ensure_web_fetch_tool(session)

    inserted = await init_data._ensure_web_fetch_tool(session)

    types, tools = await _rows(session)
    assert inserted is False
    assert len(types) == 1 and len(tools) == 1


async def test_config_is_separate_from_web_search(session):
    session.add(GptsToolsType(name="联网搜索", is_preset=1, extra='{"type": "bing"}', tenant_id=1))
    await session.commit()

    await init_data._ensure_web_fetch_tool(session)

    types, _ = await _rows(session)
    by_name = {row.name: row for row in types}
    assert by_name["联网搜索"].id != by_name["网页读取"].id
    assert json.loads(by_name["联网搜索"].extra) == {"type": "bing"}


def _settings(openfga: bool, multi_tenant: bool):
    return SimpleNamespace(
        openfga=SimpleNamespace(enabled=openfga, recent_consistency_window_seconds=1),
        multi_tenant=SimpleNamespace(enabled=multi_tenant),
    )


async def test_sync_copies_missing_tenants_in_their_tenant_context_then_projects():
    seen_tenants = []

    async def copy(tenant_id):
        seen_tenants.append((tenant_id, get_current_tenant_id()))

    project = AsyncMock()
    with (
        patch.object(init_data, "settings", _settings(openfga=True, multi_tenant=True)),
        patch.object(init_data, "_project_web_fetch_tool_types", project),
        patch.object(init_data, "_tenants_missing_web_fetch_tool", AsyncMock(return_value=[3, 5])),
        patch("bisheng.workstation.domain.services.WorkStationService.acopy_root_builtin_tools_to_tenant", copy),
    ):
        await init_data._sync_web_fetch_tool()

    assert seen_tenants == [(3, 3), (5, 5)]
    assert get_current_tenant_id() is None
    project.assert_awaited_once()


async def test_sync_skips_projection_and_copy_when_disabled():
    project = AsyncMock()
    missing = AsyncMock(return_value=[3])
    with (
        patch.object(init_data, "settings", _settings(openfga=False, multi_tenant=False)),
        patch.object(init_data, "_project_web_fetch_tool_types", project),
        patch.object(init_data, "_tenants_missing_web_fetch_tool", missing),
    ):
        await init_data._sync_web_fetch_tool()

    project.assert_not_awaited()
    missing.assert_not_awaited()


async def test_sync_failure_does_not_break_startup():
    copy = AsyncMock(side_effect=[RuntimeError("tenant 3 broken"), None])
    with (
        patch.object(init_data, "settings", _settings(openfga=True, multi_tenant=True)),
        patch.object(init_data, "_project_web_fetch_tool_types", AsyncMock(side_effect=RuntimeError("fga down"))),
        patch.object(init_data, "_tenants_missing_web_fetch_tool", AsyncMock(return_value=[3, 5])),
        patch("bisheng.workstation.domain.services.WorkStationService.acopy_root_builtin_tools_to_tenant", copy),
    ):
        await init_data._sync_web_fetch_tool()

    assert copy.await_count == 2


def _spec(tenant_id: int, type_id: int) -> SystemOwnedResourceSpec:
    return SystemOwnedResourceSpec(
        tenant_id=tenant_id,
        resource_type="tool",
        resource_id=str(type_id),
        action_codes=("use",),
        context_version=f"v{tenant_id}",
    )


async def test_projection_writes_only_missing_types_each_in_its_tenant_context():
    # Tenant 1 is projected; tenants 3 and 5 have rows but no projection (a failed copy).
    inventory = SimpleNamespace(resources=(_spec(1, 18), _spec(3, 30), _spec(5, 50), _spec(5, 51)))
    states = [
        SimpleNamespace(resource=_spec(1, 18), state="CURRENT"),
        SimpleNamespace(resource=_spec(3, 30), state="MISSING"),
        SimpleNamespace(resource=_spec(5, 50), state="MISSING"),
    ]
    written = []

    async def reconcile(runtime, specs, *, apply, operator_id):
        written.append((specs[0].tenant_id, get_current_tenant_id()))
        if specs[0].tenant_id == 3:
            raise RuntimeError("one tenant fails")

    components = SimpleNamespace(facade=object(), marker=SimpleNamespace(wait_until_ready=AsyncMock()))
    with (
        patch.object(init_data, "settings", _settings(openfga=True, multi_tenant=True)),
        patch.object(init_data, "_web_fetch_tool_types_by_tenant", AsyncMock(return_value={1: 18, 3: 30, 5: 50})),
        patch(
            "bisheng.api.services.f048_system_resource_bootstrap.load_system_owned_resource_inventory",
            AsyncMock(return_value=inventory),
        ),
        patch(
            "bisheng.permission.application.system_resource_reconcile.inspect_system_owned_resources",
            AsyncMock(return_value=states),
        ) as inspect,
        patch(
            "bisheng.permission.application.process_runtime.get_f048_process_runtime",
            AsyncMock(return_value=SimpleNamespace(components=components)),
        ),
        patch("bisheng.permission.application.system_resource_reconcile.reconcile_system_owned_resources", reconcile),
    ):
        await init_data._project_web_fetch_tool_types()

    # Tenant 5's other preset type (51) is not a web fetch type and is not inspected.
    assert {spec.resource_id for spec in inspect.await_args.args[0]} == {"18", "30", "50"}
    assert written == [(3, 3), (5, 5)]
    assert get_current_tenant_id() is None


async def test_projection_writes_nothing_when_all_current():
    inventory = SimpleNamespace(resources=(_spec(1, 18),))
    runtime = AsyncMock()
    with (
        patch.object(init_data, "_web_fetch_tool_types_by_tenant", AsyncMock(return_value={1: 18})),
        patch(
            "bisheng.api.services.f048_system_resource_bootstrap.load_system_owned_resource_inventory",
            AsyncMock(return_value=inventory),
        ),
        patch(
            "bisheng.permission.application.system_resource_reconcile.inspect_system_owned_resources",
            AsyncMock(return_value=[SimpleNamespace(resource=_spec(1, 18), state="CURRENT")]),
        ),
        patch("bisheng.permission.application.process_runtime.get_f048_process_runtime", runtime),
    ):
        await init_data._project_web_fetch_tool_types()

    runtime.assert_not_awaited()

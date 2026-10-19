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
    return SimpleNamespace(openfga=SimpleNamespace(enabled=openfga), multi_tenant=SimpleNamespace(enabled=multi_tenant))


async def test_sync_projects_root_and_copies_missing_tenants():
    project = AsyncMock()
    copy = AsyncMock()
    with (
        patch.object(init_data, "settings", _settings(openfga=True, multi_tenant=True)),
        patch.object(init_data, "_project_root_web_fetch_tool", project),
        patch.object(init_data, "_tenants_missing_web_fetch_tool", AsyncMock(return_value=[3, 5])),
        patch("bisheng.workstation.domain.services.WorkStationService.acopy_root_builtin_tools_to_tenant", copy),
    ):
        await init_data._sync_web_fetch_tool()

    project.assert_awaited_once()
    assert [call.args[0] for call in copy.await_args_list] == [3, 5]


async def test_sync_skips_projection_and_copy_when_disabled():
    project = AsyncMock()
    missing = AsyncMock(return_value=[3])
    with (
        patch.object(init_data, "settings", _settings(openfga=False, multi_tenant=False)),
        patch.object(init_data, "_project_root_web_fetch_tool", project),
        patch.object(init_data, "_tenants_missing_web_fetch_tool", missing),
    ):
        await init_data._sync_web_fetch_tool()

    project.assert_not_awaited()
    missing.assert_not_awaited()


async def test_sync_failure_does_not_break_startup():
    copy = AsyncMock(side_effect=[RuntimeError("tenant 3 broken"), None])
    with (
        patch.object(init_data, "settings", _settings(openfga=True, multi_tenant=True)),
        patch.object(init_data, "_project_root_web_fetch_tool", AsyncMock(side_effect=RuntimeError("fga down"))),
        patch.object(init_data, "_tenants_missing_web_fetch_tool", AsyncMock(return_value=[3, 5])),
        patch("bisheng.workstation.domain.services.WorkStationService.acopy_root_builtin_tools_to_tenant", copy),
    ):
        await init_data._sync_web_fetch_tool()

    assert copy.await_count == 2

"""Preset classification must not depend on historical creator metadata."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import InvalidCatalogActionError, PermissionInvalidResourceError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao, GptsToolsType
from bisheng.tool.domain.services.f048_tool_permission import F048ToolPermissionAdapter, ToolDaoPermissionLoader
from bisheng.tool.domain.services.permission_migration_source import (
    SqlToolMigrationRepository,
    ToolPermissionMigrationSource,
)
from bisheng.tool.domain.services.tool import ToolServices
from bisheng.workstation.domain.services.workstation_service import WorkStationService


@pytest.mark.parametrize("owner_user_id", [None, 1, 7])
@pytest.mark.parametrize("tool_kind", [ToolPresetType.API, ToolPresetType.PRESET, ToolPresetType.MCP])
async def test_runtime_classification_uses_type_and_keeps_action_guards(monkeypatch, owner_user_id, tool_kind):
    row = GptsToolsType(id=902, tenant_id=5, user_id=owner_user_id, name="Tool", is_preset=tool_kind.value)
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=row))
    versions = SimpleNamespace(get_permission_version=AsyncMock(return_value=(2, "tool-context")))
    loader = ToolDaoPermissionLoader(versions)
    permission = SimpleNamespace(check_action=AsyncMock(return_value=True))
    adapter = F048ToolPermissionAdapter(loader=loader, permission=permission)
    actor = PermissionActor(user_id=7, current_tenant_id=5)

    record = await loader.load_permission_record("902")

    assert record.preset is (tool_kind == ToolPresetType.PRESET)
    assert record.owner_user_id == owner_user_id
    if tool_kind != ToolPresetType.PRESET and owner_user_id is None:
        with pytest.raises(PermissionInvalidResourceError):
            await adapter.check_action(resource_id="902", actor=actor, action="use")
        permission.check_action.assert_not_awaited()
        return

    assert await adapter.check_action(resource_id="902", actor=actor, action="use")
    if tool_kind == ToolPresetType.PRESET:
        with pytest.raises(InvalidCatalogActionError):
            await adapter.resolve_permission_target(resource_id="902", actor=actor, action="edit")
    else:
        assert await adapter.check_action(resource_id="902", actor=actor, action="edit")


@pytest.mark.parametrize("owner_user_id", [None, 1, 7])
@pytest.mark.parametrize("tool_kind", [ToolPresetType.API, ToolPresetType.PRESET, ToolPresetType.MCP])
def test_new_permission_record_uses_type_independently_of_creator(owner_user_id, tool_kind):
    row = GptsToolsType(id=902, tenant_id=5, user_id=owner_user_id, name="Tool", is_preset=tool_kind.value)

    record = ToolServices._new_permission_record(row)

    assert record.preset is (tool_kind == ToolPresetType.PRESET)
    assert record.owner_user_id == owner_user_id


@pytest.mark.parametrize("allowed", [True, False])
async def test_workstation_presets_with_creator_still_require_use_permission(monkeypatch, allowed):
    from bisheng.permission.application import business_authorization

    row = GptsToolsType(id=902, tenant_id=5, user_id=1, name="Web search", is_preset=1)
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=row))
    loader = ToolDaoPermissionLoader(SimpleNamespace(get_permission_version=AsyncMock(return_value=(2, "context"))))
    adapter = F048ToolPermissionAdapter(loader=loader, permission=SimpleNamespace())
    actor = PermissionActor(user_id=7, current_tenant_id=5)

    async def resolve(*, resource_type, resource_id, actor, action):
        assert resource_type == "tool"
        return await adapter.resolve_permission_target(resource_id=resource_id, actor=actor, action=action)

    runtime = SimpleNamespace(batch_check_actions=AsyncMock(return_value=(allowed,)))
    monkeypatch.setattr(business_authorization, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(
        business_authorization, "get_f048_resource_registry", AsyncMock(return_value=SimpleNamespace(resolve=resolve))
    )
    monkeypatch.setattr(business_authorization, "get_f048_runtime", AsyncMock(return_value=runtime))
    groups = [{"id": 902, "name": "Web search", "children": [{"id": 123, "tool_key": "web_search"}]}]
    user = UserPayload(user_id=7, tenant_id=5, user_role=[])

    result = await WorkStationService.afilter_tools_by_use_permission(groups, user)

    assert result == (groups if allowed else [])
    runtime.batch_check_actions.assert_awaited_once()
    assert runtime.batch_check_actions.await_args.args[0] == actor
    assert runtime.batch_check_actions.await_args.args[1][0].resource_id == "902"
    assert runtime.batch_check_actions.await_args.args[2] == "use"


@pytest.fixture
async def tool_session_factory():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all, tables=[GptsToolsType.__table__, GptsTools.__table__])

    @asynccontextmanager
    async def factory():
        # These tests exercise classification, not request-level tenant selection.
        with bypass_tenant_filter():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

    try:
        yield factory
    finally:
        await engine.dispose()


async def test_sql_migration_classifies_only_presets_as_system_owned(tool_session_factory):
    async with tool_session_factory() as session:
        session.add_all(
            [
                GptsToolsType(id=6, tenant_id=1, name="Preset", is_preset=1, user_id=None),
                GptsToolsType(id=902, tenant_id=1, name="Legacy preset", is_preset=1, user_id=1),
                GptsToolsType(id=1323, tenant_id=1, name="API", is_preset=0, user_id=7),
                GptsToolsType(id=1324, tenant_id=1, name="MCP", is_preset=2, user_id=None),
            ]
        )
        await session.commit()
    source = ToolPermissionMigrationSource(SqlToolMigrationRepository(session_factory=tool_session_factory))

    page = await source.aexport(cursor=None, limit=10)

    assert [(item.resource_id, item.ownership_kind, item.system_allowlisted) for item in page.items] == [
        ("6", "SYSTEM", True),
        ("902", "SYSTEM", True),
        ("1323", "USER", False),
        ("1324", "USER", False),
    ]
    assert page.items[1].owner_user_id == 1


@pytest.mark.parametrize("owner_user_id", [None, 1])
async def test_tenant_copy_projects_presets_with_historical_creator(monkeypatch, tool_session_factory, owner_user_id):
    from bisheng.workstation.domain.services import workstation_service

    async with tool_session_factory() as session:
        session.add(GptsToolsType(id=902, tenant_id=1, name="Web search", is_preset=1, user_id=owner_user_id))
        session.add(
            GptsTools(
                id=10,
                tenant_id=1,
                type=902,
                name="Web search",
                tool_key="web_search",
                is_preset=1,
                user_id=owner_user_id,
            )
        )
        await session.commit()
    monkeypatch.setattr(workstation_service, "get_async_db_session", tool_session_factory)
    monkeypatch.setattr(workstation_service, "settings", SimpleNamespace(openfga=SimpleNamespace(enabled=True)))
    runtime = object()
    monkeypatch.setattr(workstation_service, "get_f048_runtime", AsyncMock(return_value=runtime))
    reconcile = AsyncMock(return_value=SimpleNamespace(current_count=1))
    monkeypatch.setattr(workstation_service, "reconcile_system_owned_resources", reconcile)

    result = await WorkStationService.acopy_root_builtin_tools_to_tenant(3)

    assert result["created_types"] == result["created_tools"] == result["projected_types"] == 1
    async with tool_session_factory() as session:
        copied_type = (await session.exec(select(GptsToolsType).where(GptsToolsType.tenant_id == 3))).one()
        copied_tool = (await session.exec(select(GptsTools).where(GptsTools.tenant_id == 3))).one()
    assert copied_type.is_preset == copied_tool.is_preset == 1
    assert copied_type.user_id == copied_tool.user_id == owner_user_id
    reconcile.assert_awaited_once()
    specs = reconcile.await_args.args[1]
    assert len(specs) == 1
    assert specs[0].tenant_id == 3
    assert specs[0].resource_id == str(copied_type.id)
    assert specs[0].action_codes == ("use", "visible")

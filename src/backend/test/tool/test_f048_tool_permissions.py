"""F048 tool authorization contracts."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionFGAUnavailableError,
    PermissionInvalidResourceError,
)
from bisheng.common.errcode.tool import ToolTypeIsPresetError
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)
from bisheng.tool.domain.models.gpts_tools import GptsToolsType
from bisheng.tool.domain.services.f048_tool_permission import (
    F048ToolPermissionAdapter,
    ToolPermissionRecord,
)
from bisheng.tool.domain.services.tool import (
    ToolResourceAuthorizationPort,
    ToolServices,
)


class _Loader:
    def __init__(self, records: tuple[ToolPermissionRecord, ...]):
        self.records = {record.resource_id: record for record in records}

    async def load_permission_record(self, resource_id):
        return self.records.get(resource_id)


class _Permission:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.error: Exception | None = None

    async def check_action(self, actor, target, action):
        self.calls.append(("check", (actor, target, action)))
        if self.error is not None:
            raise self.error
        return True

    async def batch_check_actions(self, actor, targets, action):
        self.calls.append(("batch", (actor, targets, action)))
        return tuple(True for _ in targets)

    async def authorize_created(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"status": "FINALIZED"}

    async def authorize_system_owned(self, **kwargs):
        self.calls.append(("system", kwargs))
        return {"status": "FINALIZED"}

    async def project_delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return {"status": "FINALIZED"}


def _record(
    *,
    resource_id: str = "10",
    tenant_id: int = 5,
    status: str = "ACTIVE",
    preset: bool = False,
    system_allowlisted: bool = False,
) -> ToolPermissionRecord:
    return ToolPermissionRecord(
        tenant_id=tenant_id,
        resource_id=resource_id,
        status=status,
        owner_user_id=None if preset else 7,
        permission_version=2,
        context_version=f"tool-{resource_id}-v2",
        preset=preset,
        system_allowlisted=system_allowlisted,
    )


def _actor(tenant_id: int = 5) -> PermissionActor:
    return PermissionActor(user_id=7, current_tenant_id=tenant_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    ("visible", "use", "edit", "delete", "manage_permission"),
)
async def test_custom_tool_uses_exact_action(action) -> None:
    record = _record()
    permission = _Permission()
    adapter = F048ToolPermissionAdapter(
        loader=_Loader((record,)),
        permission=permission,
    )

    assert await adapter.check_action(
        resource_id="10",
        actor=_actor(),
        action=action,
    )
    assert permission.calls[0][1][2] == action


@pytest.mark.asyncio
async def test_tool_business_port_builds_verified_target() -> None:
    record = _record()
    adapter = F048ToolPermissionAdapter(
        loader=_Loader((record,)),
        permission=_Permission(),
    )
    port = ToolResourceAuthorizationPort(adapter)

    target = await port.resolve_permission_target(
        resource_id="10",
        actor=_actor(),
        action="visible",
    )

    assert target.resource_type == "tool"
    assert target.tenant_id == 5


@pytest.mark.asyncio
async def test_custom_tool_create_projects_protected_owner() -> None:
    record = _record()
    permission = _Permission()
    adapter = F048ToolPermissionAdapter(
        loader=_Loader((record,)),
        permission=permission,
    )

    await adapter.authorize_created(record=record, actor=_actor())

    create = permission.calls[0][1]
    assert create["mode"] == "CUSTOM"
    assert create["owner_user_id"] == 7
    assert create["protected"] is True


@pytest.mark.asyncio
async def test_preset_tool_create_projects_read_only_system_actions() -> None:
    preset = _record(preset=True, system_allowlisted=True)
    permission = _Permission()
    adapter = F048ToolPermissionAdapter(
        loader=_Loader((preset,)),
        permission=permission,
    )

    await adapter.authorize_created(record=preset, actor=_actor())

    system = permission.calls[0][1]
    assert system["action_codes"] == ("use", "visible")
    assert "owner_user_id" not in system


@pytest.mark.asyncio
async def test_preset_tool_requires_both_predicate_and_read_allowlist() -> None:
    preset = _record(preset=True, system_allowlisted=True)
    adapter = F048ToolPermissionAdapter(
        loader=_Loader((preset,)),
        permission=_Permission(),
    )
    assert await adapter.check_action(
        resource_id="10",
        actor=_actor(),
        action="use",
    )
    with pytest.raises(InvalidCatalogActionError):
        await adapter.check_action(
            resource_id="10",
            actor=_actor(),
            action="edit",
        )

    blocked = replace(preset, system_allowlisted=False)
    adapter = F048ToolPermissionAdapter(
        loader=_Loader((blocked,)),
        permission=_Permission(),
    )
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.resolve_permission_target(
            resource_id="10",
            actor=_actor(),
            action="visible",
        )


@pytest.mark.asyncio
async def test_fga_failure_does_not_fallback_to_legacy_tool_service() -> None:
    permission = _Permission()
    permission.error = PermissionFGAUnavailableError()
    adapter = F048ToolPermissionAdapter(
        loader=_Loader((_record(),)),
        permission=permission,
    )

    with pytest.raises(PermissionFGAUnavailableError):
        await adapter.check_action(
            resource_id="10",
            actor=_actor(),
            action="use",
        )
    assert len(permission.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record",
    (
        None,
        _record(tenant_id=6),
        _record(status="DELETED"),
    ),
)
async def test_invalid_tool_business_facts_fail_closed(record) -> None:
    adapter = F048ToolPermissionAdapter(
        loader=_Loader(tuple(row for row in (record,) if row is not None)),
        permission=_Permission(),
    )
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.resolve_permission_target(
            resource_id="10",
            actor=_actor(),
            action="visible",
        )


@pytest.mark.asyncio
async def test_custom_tool_create_rejects_forged_preset_type() -> None:
    service = ToolServices(
        login_user=UserPayload(
            user_id=7,
            tenant_id=5,
            user_role=[],
        )
    )

    with pytest.raises(ToolTypeIsPresetError):
        await service.add_tools(SimpleNamespace(is_preset=1))


@pytest.mark.asyncio
async def test_refresh_mcp_requires_exact_edit_action(monkeypatch) -> None:
    tool_type = SimpleNamespace(id=10, name="MCP", type=10)
    require_action = AsyncMock()
    refresh = AsyncMock()
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.GptsToolsDao.aget_user_tool_type",
        AsyncMock(return_value=[tool_type]),
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.GptsToolsDao.aget_list_by_type",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.require_business_action",
        require_action,
    )
    monkeypatch.setattr(ToolServices, "refresh_mcp_tools", refresh)
    login_user = UserPayload(
        user_id=7,
        tenant_id=5,
        user_role=[],
    )

    assert await ToolServices(login_user=login_user).refresh_all_mcp() == []

    require_action.assert_awaited_once_with(
        login_user,
        resource_type="tool",
        resource_id=10,
        action="edit",
    )
    refresh.assert_awaited_once_with(tool_type, [])


@pytest.mark.asyncio
async def test_tool_list_uses_requested_action_and_exact_button_actions(
    monkeypatch,
) -> None:
    tool_type = GptsToolsType(
        id=10,
        tenant_id=1,
        user_id=7,
        name="API",
        is_preset=0,
    )
    batch_actions = AsyncMock(
        return_value={
            "10": frozenset({"visible", "edit"}),
        }
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.GptsToolsDao.aget_tenant_tool_type",
        AsyncMock(return_value=[tool_type]),
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.GptsToolsDao.aget_list_by_type",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.batch_check_business_actions",
        batch_actions,
    )
    login_user = UserPayload(
        user_id=7,
        tenant_id=1,
        user_role=[],
    )

    result = await ToolServices(login_user=login_user).get_tool_list(action="visible")

    assert [item.id for item in result] == [10]
    assert result[0].write is True
    assert result[0].delete is False
    assert batch_actions.await_args.kwargs["actions"] == (
        "visible",
        "edit",
        "delete",
    )


@pytest.mark.asyncio
async def test_delete_tool_checks_delete_then_projects_lifecycle(
    monkeypatch,
) -> None:
    tool_type = GptsToolsType(
        id=10,
        tenant_id=5,
        user_id=7,
        name="API",
        is_preset=0,
    )
    require_action = AsyncMock()
    adapter = SimpleNamespace(
        load_permission_record=AsyncMock(return_value=_record()),
        project_delete=AsyncMock(),
    )
    delete_row = AsyncMock()
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.GptsToolsDao.aget_one_tool_type",
        AsyncMock(return_value=tool_type),
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.GptsToolsDao.delete_tool_type",
        delete_row,
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.require_business_action",
        require_action,
    )
    monkeypatch.setattr(
        "bisheng.tool.domain.services.tool.get_f048_resource_adapter",
        lambda resource_type: adapter,
    )
    monkeypatch.setattr(ToolServices, "delete_tool_hook", AsyncMock())
    login_user = UserPayload(
        user_id=7,
        tenant_id=5,
        user_role=[],
    )

    assert await ToolServices(login_user=login_user).delete_tools(10)

    require_action.assert_awaited_once_with(
        login_user,
        resource_type="tool",
        resource_id=10,
        action="delete",
    )
    adapter.project_delete.assert_awaited_once()
    delete_row.assert_awaited_once_with(10)

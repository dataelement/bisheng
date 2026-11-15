"""Desktop catalogs and Work consume the same visible tool set. AC-35/68/79/82/83."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.open_api import PersonalTokenDataScopeError
from bisheng.dsh.domain.services.capability_catalog import CapabilityCatalogService
from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService
from bisheng.linsight.domain.services.user_skills import UserSkillsService
from bisheng.tool.domain.services.tool import ToolServices
from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService


@pytest.fixture
def desktop(monkeypatch):
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    tool = SimpleNamespace(id=1, is_preset=0, name="API tool", tool_key="api-tool", desc="Tool", is_delete=0)
    group = SimpleNamespace(id=10, name="API", description="Tools", is_preset=0, children=[tool])
    requests = []

    async def groups(service, is_preset=None, action="visible"):
        requests.append((service.login_user, action))
        return [group] if action == "visible" else []

    monkeypatch.setattr(ToolServices, "get_tool_list", groups)
    monkeypatch.setattr(UserSkillsService, "records", AsyncMock(return_value=[]))
    disabled = AsyncMock(return_value=set())
    save = AsyncMock()
    monkeypatch.setattr(UserToolAvailabilityService, "disabled_ids", disabled)
    monkeypatch.setattr(UserToolAvailabilityService, "save", save)
    publications = SimpleNamespace(audit=AsyncMock())
    work = WorkCapabilitiesService(user, publications)
    executor = SimpleNamespace(args_schema={"type": "object"}, ainvoke=AsyncMock(return_value={"ok": True}))
    work._executor = AsyncMock(return_value=executor)
    return SimpleNamespace(
        user=user,
        work=work,
        catalog=CapabilityCatalogService(user, work),
        executor=executor,
        requests=requests,
        disabled=disabled,
        save=save,
    )


async def test_capability_catalog_keeps_visible_tool_and_original_identity(desktop):
    result = await desktop.catalog.list()
    assert [item["id"] for item in result["items"]] == ["tool:1"]
    assert result["items"][0]["ready"] is True
    assert desktop.requests == [(desktop.user, "visible")]


async def test_picker_keeps_visible_tools_without_default_selection(desktop):
    result = await desktop.catalog.picker_tools()
    assert result[0]["children"][0]["id"] == 1
    assert result[0]["default_checked"] is False
    assert desktop.requests == [(desktop.user, "visible")]


async def test_account_availability_still_requires_visible_tool(desktop):
    assert await desktop.catalog.set_availability(1, False) == {"tool_id": 1, "enabled": False}
    desktop.save.assert_awaited_once_with(1, False)
    assert desktop.requests == [(desktop.user, "visible")]


async def test_work_discovery_and_execution_recheck_same_visible_set(desktop):
    assert [tool["name"] for tool in await desktop.work.list_tools()] == ["bisheng_tool_1"]
    assert await desktop.work.call_tool("bisheng_tool_1", {}) == {"ok": True}
    assert desktop.requests == [(desktop.user, "visible"), (desktop.user, "visible")]
    desktop.disabled.return_value = {1}
    desktop.work._executor.reset_mock()
    assert await desktop.work.list_tools() == []
    with pytest.raises(HTTPException) as error:
        await desktop.work.call_tool("bisheng_tool_1", {})
    assert error.value.status_code == 403
    desktop.work._executor.assert_not_awaited()
    desktop.executor.ainvoke.assert_awaited_once()


async def test_catalog_retains_account_disabled_metadata_without_execution(desktop):
    desktop.disabled.return_value = {1}
    result = await desktop.catalog.list()
    assert result["items"][0]["ready"] is False
    assert result["items"][0]["availability_enabled"] is False
    assert await desktop.work._tools() == {}
    desktop.work._executor.assert_not_awaited()


@pytest.mark.parametrize("entry", ["catalog", "picker", "discovery", "execution"])
async def test_scope_failure_propagates_before_executor(desktop, monkeypatch, entry):
    monkeypatch.setattr(ToolServices, "get_tool_list", AsyncMock(side_effect=PersonalTokenDataScopeError()))
    operation = {
        "catalog": desktop.catalog.list,
        "picker": desktop.catalog.picker_tools,
        "discovery": desktop.work.list_tools,
        "execution": lambda: desktop.work.call_tool("bisheng_tool_1", {}),
    }[entry]
    with pytest.raises(PersonalTokenDataScopeError):
        await operation()
    desktop.work._executor.assert_not_awaited()

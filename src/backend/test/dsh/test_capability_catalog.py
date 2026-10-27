import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bisheng.dsh.domain.services.capability_catalog import CapabilityCatalogService


@pytest.fixture(autouse=True)
def account_availability(monkeypatch):
    from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService

    monkeypatch.setattr(UserToolAvailabilityService, "disabled_ids", AsyncMock(return_value=set()))


def tool(id=1, kind=1, name="Current time", key="get_current_time"):
    return SimpleNamespace(id=id, is_preset=kind, name=name, tool_key=key, desc="Description", is_delete=0)


def make_service(monkeypatch, rows):
    module = ModuleType("bisheng.tool.domain.services.tool")
    group = SimpleNamespace(
        id=12,
        is_preset=0,
        description="Tools",
        name="Enterprise tools",
        children=rows,
        api_key="private-test-key",
        openapi_schema="private headers",
    )
    module.ToolServices = lambda **kwargs: SimpleNamespace(get_tool_list=AsyncMock(return_value=[group]))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    work = SimpleNamespace(
        publications=SimpleNamespace(list_enabled=AsyncMock(return_value={1})),
        _tools=AsyncMock(return_value={row.id: row for row in rows}),
        _skills=AsyncMock(return_value={}),
        call_tool=AsyncMock(return_value='{"available": 85, "demo_data": true}'),
    )
    from bisheng.linsight.domain.services.user_skills import UserSkillsService

    async def records(self, available_only=True):
        return [(skill, True) for skill in (await work._skills()).values()]

    monkeypatch.setattr(UserSkillsService, "records", records)
    return CapabilityCatalogService(SimpleNamespace(tenant_id=2, user_id=7), work), work


async def test_catalog_uses_resource_permissions_without_publication(monkeypatch):
    app, _ = make_service(monkeypatch, [tool(), tool(2, key="email_send_email")])
    result = await app.list()
    assert len(result["items"]) == 2
    assert result["items"][0]["trial"]["arguments"] == {"timezone": "Asia/Shanghai"}
    assert result["items"][1]["ready"] is True
    app.work.publications.list_enabled.assert_not_awaited()
    assert "private-test-key" not in json.dumps(result)
    assert "openapi_schema" not in json.dumps(result)


async def test_readonly_demo_still_calls_the_normal_authorized_work_path(monkeypatch):
    app, work = make_service(monkeypatch, [tool(1, 2, "demo_check_inventory", "hash")])
    result = await app.trial(1, {"product_code": "MAT-001"})
    work.call_tool.assert_awaited_once_with("bisheng_tool_1", {"product_code": "MAT-001"})
    assert result["result"]["available"] == 85
    assert result["demo_data"] is True


async def test_permission_revocation_propagates_without_executing_another_path(monkeypatch):
    app, work = make_service(monkeypatch, [tool()])
    work.call_tool.side_effect = HTTPException(403, "revoked")
    with pytest.raises(HTTPException) as error:
        await app.trial(1, {"timezone": "Asia/Shanghai"})
    assert error.value.status_code == 403


async def test_arbitrary_enterprise_tools_have_no_inline_execution(monkeypatch):
    app, work = make_service(monkeypatch, [tool(1, key="email_send_email")])
    with pytest.raises(HTTPException) as error:
        await app.trial(1, {})
    assert error.value.status_code == 404
    work.call_tool.assert_not_awaited()


async def test_bounded_demo_arguments(monkeypatch):
    app, work = make_service(monkeypatch, [tool()])
    with pytest.raises(HTTPException) as error:
        await app.trial(1, {"timezone": "a" * 5000})
    assert error.value.status_code == 413
    work.call_tool.assert_not_awaited()


async def test_mcp_error_payload_is_audited_as_incomplete(monkeypatch):
    from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService

    _app, work = make_service(monkeypatch, [tool(1, 2, "demo_check_inventory", "hash")])
    service = WorkCapabilitiesService(SimpleNamespace(tenant_id=2), work.publications)
    service._tools = work._tools
    executor = SimpleNamespace(
        args_schema={"type": "object"}, ainvoke=AsyncMock(return_value='{"isError":true,"content":[]}')
    )
    service._executor = AsyncMock(return_value=executor)
    work.publications.audit = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await service.call_tool("bisheng_tool_1", {})
    assert error.value.status_code == 502
    assert [call.args[-1]["status"] for call in work.publications.audit.await_args_list] == ["STARTED", "INCOMPLETE"]


async def test_skill_requires_all_its_tools_to_be_usable(monkeypatch):
    app, work = make_service(monkeypatch, [tool()])
    work._skills.return_value = {1: SimpleNamespace(id=1)}
    work._skill_info = lambda row: {
        "id": 1,
        "title": "Order review",
        "description": "Review",
        "name": "bisheng-2-1-order",
    }
    work._read_bundle = lambda row: {"tool_ids": [99]}
    catalog = await app.list()
    skill = next(row for row in catalog["items"] if row["kind"] == "skill")
    assert skill["ready"] is False


async def test_picker_catalog_is_safe_and_defaults_to_no_selection(monkeypatch):
    app, work = make_service(monkeypatch, [tool()])
    rows = await app.picker_tools()
    assert rows[0]["default_checked"] is False
    assert rows[0]["children"][0]["id"] == 1
    assert "api_key" not in json.dumps(rows)
    assert "openapi_schema" not in json.dumps(rows)
    work.publications.list_enabled.assert_not_awaited()


async def test_work_call_accepts_resource_permission_without_publication(monkeypatch):
    from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService

    _, work = make_service(monkeypatch, [tool()])
    work.publications.audit = AsyncMock()
    work.publications.list_enabled.return_value = set()
    service = WorkCapabilitiesService(SimpleNamespace(tenant_id=2), work.publications)
    service._tools = work._tools
    executor = SimpleNamespace(args_schema={"type": "object"}, ainvoke=AsyncMock(return_value="time"))
    service._executor = AsyncMock(return_value=executor)
    assert await service.call_tool("bisheng_tool_1", {}) == "time"
    work.publications.list_enabled.assert_not_awaited()
    work._tools.return_value = {}
    with pytest.raises(HTTPException) as error:
        await service.call_tool("bisheng_tool_1", {})
    assert error.value.status_code == 403
    assert executor.ainvoke.await_count == 1


async def test_separate_publication_is_retired(monkeypatch):
    from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService

    _, work = make_service(monkeypatch, [])
    service = WorkCapabilitiesService(SimpleNamespace(tenant_id=2), work.publications)
    with pytest.raises(HTTPException) as error:
        await service.publish("tool", 1, False)
    assert error.value.status_code == 410


async def test_skill_loading_rechecks_resource_state_after_read(monkeypatch):
    from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService

    _, work = make_service(monkeypatch, [tool()])
    work.publications.audit = AsyncMock()
    service = WorkCapabilitiesService(SimpleNamespace(tenant_id=2), work.publications)
    skill = SimpleNamespace(id=1, name="review", display_name="Review", description="Review", content_hash="a" * 64)
    service._skills = AsyncMock(side_effect=[{1: skill}, {}])
    service._tools = work._tools
    service._read_bundle = lambda row: {"tool_ids": [1], "files": [], "content": "Review"}
    with pytest.raises(HTTPException) as error:
        await service.read_skill("bisheng-skill://2/1/" + "a" * 64)
    assert error.value.status_code == 409
    work.publications.audit.assert_not_awaited()


async def test_account_disabled_search_remains_manageable_but_picker_marks_it_disabled(monkeypatch):
    from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService

    monkeypatch.setattr(UserToolAvailabilityService, "disabled_ids", AsyncMock(return_value={38}))
    app, _ = make_service(monkeypatch, [tool(38, key="web_search"), tool()])
    items = (await app.list())["items"]
    search = next(item for item in items if item["resource_id"] == 38)
    assert search["availability_enabled"] is False
    assert search["ready"] is False
    assert next(item for item in items if item["resource_id"] == 1)["ready"] is True
    picker = await app.picker_tools()
    assert next(child for child in picker[0]["children"] if child["id"] == 38)["enabled"] is False


async def test_only_authorized_tools_can_change_account_availability(monkeypatch):
    from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService

    save = AsyncMock()
    monkeypatch.setattr(UserToolAvailabilityService, "save", save)
    app, work = make_service(monkeypatch, [tool(38, key="web_search"), tool()])
    work.publications.audit = AsyncMock()
    assert await app.set_availability(38, False) == {"tool_id": 38, "enabled": False}
    save.assert_awaited_once_with(38, False)
    work.publications.audit.assert_awaited_once()
    for forbidden in (999,):
        with pytest.raises(HTTPException) as failure:
            await app.set_availability(forbidden, False)
        assert failure.value.status_code == 404
    assert await app.set_availability(1, False) == {"tool_id": 1, "enabled": False}
    assert save.await_count == 2


@pytest.mark.parametrize("kind", [0, 1, 2])
async def test_each_tool_kind_can_be_disabled_and_removed_from_work(monkeypatch, kind):
    from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService
    from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService

    app, _ = make_service(monkeypatch, [tool(7, kind)])
    disabled = AsyncMock(return_value=set())
    monkeypatch.setattr(UserToolAvailabilityService, "disabled_ids", disabled)
    work = WorkCapabilitiesService(SimpleNamespace(tenant_id=2, user_id=7))
    assert set(await work._tools()) == {7}
    disabled.return_value = {7}
    item = (await app.list())["items"][0]
    assert item["availability_enabled"] is False
    assert item["ready"] is False
    assert (await app.picker_tools())[0]["children"][0]["enabled"] is False
    assert await work._tools() == {}
    work._executor = AsyncMock()
    with pytest.raises(HTTPException) as failure:
        await work.call_tool("bisheng_tool_7", {})
    assert failure.value.status_code == 403
    work._executor.assert_not_awaited()


async def test_dedicated_knowledge_adapter_uses_the_same_account_boundary(monkeypatch):
    from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService
    from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService

    make_service(monkeypatch, [tool(7, key="bisheng_knowledge_search")])
    work = WorkCapabilitiesService(SimpleNamespace(tenant_id=2, user_id=7))
    await work.ensure_tool_key_enabled("bisheng_knowledge_search")
    monkeypatch.setattr(UserToolAvailabilityService, "disabled_ids", AsyncMock(return_value={7}))
    with pytest.raises(HTTPException) as failure:
        await work.ensure_tool_key_enabled("bisheng_knowledge_search")
    assert failure.value.status_code == 403


@pytest.mark.parametrize("target_id", [1, 2, 3])
async def test_tool_order_stays_stable_across_availability_changes_and_reload(monkeypatch, target_id):
    from bisheng.tool.domain.services.user_availability import UserToolAvailabilityService

    tools = [tool(3, 2), tool(4, 1), tool(2, 1), tool(1, 0)]
    disabled = AsyncMock(return_value={4})
    monkeypatch.setattr(UserToolAvailabilityService, "disabled_ids", disabled)
    app, _ = make_service(monkeypatch, tools)
    initial = (await app.list())["items"]
    expected_ids = [item["id"] for item in initial]

    for enabled in (False, True, False):
        disabled.return_value = {4} if enabled else {4, target_id}
        for catalog in (app, make_service(monkeypatch, list(reversed(tools)))[0]):
            items = (await catalog.list())["items"]
            assert [item["id"] for item in items] == expected_ids
            target = next(item for item in items if item["resource_id"] == target_id)
            assert target["availability_enabled"] is enabled
            assert target["ready"] is enabled

@pytest.mark.parametrize("kind", [0, 1, 2])
async def test_catalog_exposes_stable_translation_identity_for_builtins(monkeypatch, kind):
    app, _ = make_service(monkeypatch, [tool(9, kind, "Configured name", "tianyancha_get_company_baseinfo")])
    row = (await app.list())["items"][0]
    assert row["tool_key"] == ("tianyancha_get_company_baseinfo" if kind == 1 else None)
    assert row["name"] == "Configured name"
    assert row["description"] == "Description"
    assert row["provider"] == "Enterprise tools"
    assert row["resource_id"] == 9
    assert row["invocation_name"] == "mcp__bisheng__bisheng_tool_9"

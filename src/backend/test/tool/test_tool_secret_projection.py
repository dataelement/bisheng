"""Tool response secrets must not leak or overwrite saved execution secrets."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsType, GptsToolsTypeRead
from bisheng.tool.domain.services import tool

CANARY = "synthetic-api-key-DO-NOT-EXPOSE"


@pytest.mark.parametrize("action", ["use", "visible"])
@pytest.mark.parametrize("editable", [False, True])
async def test_tool_list_masks_api_key_on_response_copy(monkeypatch, editable, action):
    row = GptsToolsType(
        id=11,
        name="Shared tool",
        user_id=8,
        tenant_id=1,
        is_preset=ToolPresetType.API.value,
        api_key=CANARY,
        extra=json.dumps({"api_key": CANARY}),
        openapi_schema=json.dumps({"mcpServers": {"x": {"headers": {"Authorization": CANARY}}}}),
    )
    child = GptsTools(id=12, type=11, name="call", tool_key="call", extra=json.dumps({"api_key": CANARY}))
    before = deepcopy(row.model_dump()), deepcopy(child.model_dump())
    monkeypatch.setattr(tool.GptsToolsDao, "aget_tenant_tool_type", AsyncMock(return_value=[row]))
    monkeypatch.setattr(tool.GptsToolsDao, "aget_list_by_type", AsyncMock(return_value=[child]))

    async def permissions(*_args, actions, **_kwargs):
        return {"11": frozenset(actions if editable else set(actions) - {"edit"})}

    monkeypatch.setattr(tool, "batch_check_business_actions", permissions)
    from types import SimpleNamespace

    monkeypatch.setattr(tool, "resolve_permission_actor", AsyncMock(return_value=SimpleNamespace(current_tenant_id=1)))
    monkeypatch.setattr(
        tool,
        "get_f048_runtime",
        AsyncMock(
            return_value=SimpleNamespace(
                list_visible_objects=AsyncMock(return_value=SimpleNamespace(object_ids=["11"]))
            )
        ),
    )
    result = await tool.ToolServices(
        login_user=UserPayload(user_id=4, user_name="reader", tenant_id=1, user_role=[])
    ).get_tool_list(action=action)
    assert CANARY not in json.dumps([x.model_dump() for x in result], default=str)
    assert result[0].api_key == "********"
    assert row.model_dump() == before[0]
    assert child.model_dump() == before[1]
    if action == "visible" and editable:
        assert "mcpServers" in result[0].openapi_schema
        assert "********" in result[0].openapi_schema
    else:
        assert result[0].openapi_schema == ""
        assert result[0].extra == "{}"


@pytest.mark.parametrize("submitted,expected", [("********", CANARY), ("replacement-key", "replacement-key"), ("", "")])
async def test_masked_api_key_update_preserves_saved_secret(monkeypatch, submitted, expected):
    saved = GptsToolsType(id=11, name="Shared tool", user_id=8, tenant_id=1, api_key=CANARY)
    req = GptsToolsTypeRead(id=11, name="Updated", api_key=submitted, children=[])
    monkeypatch.setattr(tool.GptsToolsDao, "aget_list_by_type", AsyncMock(return_value=[]))
    write = AsyncMock()
    monkeypatch.setattr(tool.GptsToolsDao, "update_tool_type", write)
    await tool.ToolServices._update_gpts_tools(saved, req)
    assert saved.api_key == expected
    assert write.call_args.args[0].api_key == expected


def test_nested_mask_roundtrip_restores_only_secret_fields_without_mutation():
    from bisheng.tool.domain.services.read_projection import mask_configuration, restore_masked_configuration

    original = {"servers": [{"Authorization": CANARY, "config": {"db_password": CANARY}, "name": "old"}]}
    before = deepcopy(original)
    projected = mask_configuration(original)
    assert CANARY not in json.dumps(projected)
    projected["servers"][0]["name"] = "new"
    restored = restore_masked_configuration(projected, original)
    assert restored["servers"][0]["Authorization"] == CANARY
    assert restored["servers"][0]["config"]["db_password"] == CANARY
    assert restored["servers"][0]["name"] == "new"
    assert original == before


async def test_preset_config_mask_roundtrip_keeps_nested_list_secrets(monkeypatch):
    saved = GptsToolsType(
        id=11,
        name="Preset",
        is_preset=ToolPresetType.PRESET.value,
        extra=json.dumps({"servers": [{"api_key": CANARY}]}),
    )
    monkeypatch.setattr(tool.GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=saved))
    write = AsyncMock()
    monkeypatch.setattr(tool.GptsToolsDao, "update_tools_extra", write)
    service = tool.ToolServices(login_user=UserPayload(user_id=1, tenant_id=1, user_role=[], is_global_super=True))
    await service.update_tool_config(11, {"servers": [{"api_key": "********"}]})
    assert json.loads(write.call_args.args[1])["servers"][0]["api_key"] == CANARY


async def test_authorized_mcp_update_restores_mask_before_schema_discovery(monkeypatch):
    schema = {"mcpServers": {"server": {"url": "https://example.invalid/mcp", "headers": {"Authorization": CANARY}}}}
    saved = GptsToolsType(
        id=11, name="MCP", is_preset=ToolPresetType.MCP.value, openapi_schema=json.dumps(schema), api_key=CANARY
    )
    request_schema = deepcopy(schema)
    request_schema["mcpServers"]["server"]["headers"]["Authorization"] = "********"
    req = GptsToolsTypeRead(
        id=11,
        name="MCP",
        is_preset=ToolPresetType.MCP.value,
        openapi_schema=json.dumps(request_schema),
        api_key="********",
        children=[],
    )
    monkeypatch.setattr(tool.GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=saved))
    monkeypatch.setattr(tool.GptsToolsDao, "get_one_tool_type_by_name", AsyncMock(return_value=saved))
    monkeypatch.setattr(tool.GptsToolsDao, "aget_list_by_type", AsyncMock(return_value=[]))
    monkeypatch.setattr(tool.GptsToolsDao, "update_tool_type", AsyncMock())
    authorize = AsyncMock()
    monkeypatch.setattr(tool, "require_business_action", authorize)
    discovery = AsyncMock()
    monkeypatch.setattr(tool.ToolServices, "parse_mcp_schema", discovery)
    monkeypatch.setattr(tool.ToolServices, "update_tool_hook", AsyncMock())
    service = tool.ToolServices(login_user=UserPayload(user_id=8, tenant_id=1, user_role=[]))
    result = await service.update_tools(req)
    authorize.assert_awaited_once()
    assert json.loads(discovery.call_args.args[0]) == schema
    assert saved.api_key == CANARY
    assert json.loads(saved.openapi_schema) == schema
    assert CANARY not in json.dumps(result.model_dump(), default=str)
    assert req.api_key == "********"
    assert json.loads(req.openapi_schema) == request_schema


async def test_partial_preset_update_merges_nested_config_without_data_loss(monkeypatch):
    old = {"config": {"local": {"endpoint": "https://example.invalid", "api_key": CANARY, "keep": 1}}, "other": True}
    saved = GptsToolsType(id=11, name="Preset", is_preset=ToolPresetType.PRESET.value, extra=json.dumps(old))
    monkeypatch.setattr(tool.GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=saved))
    write = AsyncMock()
    monkeypatch.setattr(tool.GptsToolsDao, "update_tools_extra", write)
    submitted = {"config": {"local": {"api_key": "********", "new_field": 2}}}
    service = tool.ToolServices(login_user=UserPayload(user_id=1, tenant_id=1, user_role=[], is_global_super=True))
    await service.update_tool_config(11, submitted)
    result = json.loads(write.call_args.args[1])
    assert result == {
        "config": {"local": {"endpoint": "https://example.invalid", "api_key": CANARY, "keep": 1, "new_field": 2}},
        "other": True,
    }
    assert json.loads(saved.extra) == old
    assert submitted["config"]["local"]["api_key"] == "********"


@pytest.mark.parametrize("old", ["[]", '"text"', "not-json", "null"])
async def test_malformed_stored_preset_config_rejects_before_write(monkeypatch, old):
    saved = GptsToolsType(id=11, name="Preset", is_preset=ToolPresetType.PRESET.value, extra=old)
    monkeypatch.setattr(tool.GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=saved))
    write = AsyncMock()
    monkeypatch.setattr(tool.GptsToolsDao, "update_tools_extra", write)
    service = tool.ToolServices(login_user=UserPayload(user_id=1, tenant_id=1, user_role=[], is_global_super=True))
    with pytest.raises(ValueError):
        await service.update_tool_config(11, {"config": {"api_key": "********"}})
    write.assert_not_awaited()

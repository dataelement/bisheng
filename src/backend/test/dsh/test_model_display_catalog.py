from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import WSModel
from bisheng.dsh.domain.services.model_display import configured_display_names, model_display_name


def test_display_names_preserve_provider_and_fall_back_for_blank_labels():
    config = SimpleNamespace(
        models=[WSModel(id="42", displayName="  Custom label  "), WSModel(id="43", displayName=" ")]
    )
    names = configured_display_names(config)
    model = SimpleNamespace(id=42, model_name="vendor-id", name="internal alias")
    assert names == {"42": "Custom label"}
    assert (
        model_display_name(model, SimpleNamespace(name="Provider A", type="openai"), names["42"])
        == "Provider A / Custom label"
    )
    assert (
        model_display_name(model, SimpleNamespace(name="Provider B", type="openai"), names["42"])
        == "Provider B / Custom label"
    )
    assert model_display_name(model, SimpleNamespace(name="Provider A", type="openai"), " ") == "Provider A / vendor-id"


@pytest.mark.asyncio
async def test_chat_projection_uses_stored_labels_and_keeps_permission_filter(monkeypatch):
    from bisheng.common.services import config_service
    from bisheng.dsh import runtime
    from bisheng.dsh.domain.schemas.chat import ChatCapabilities
    from bisheng.dsh.domain.services.model_catalog import project_workbench_config
    from bisheng.dsh.infrastructure import model_capabilities
    from bisheng.llm.domain.schemas import WorkbenchModelConfig
    from bisheng.llm.domain.services.llm import LLMService

    config = WorkbenchModelConfig(
        models=[
            WSModel(id="42", displayName="Custom label", description="Retain"),
            WSModel(id="99", displayName="Private"),
        ],
        chat_default_model_id="42",
    )
    monkeypatch.setattr(config_service, "settings", SimpleNamespace(dsh=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(runtime, "read_policy", AsyncMock(return_value=SimpleNamespace(allowed_model_ids=[42])))
    monkeypatch.setattr(
        LLMService,
        "get_dsh_model_snapshot",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=42, model_name="vendor-id", name="alias"),
                SimpleNamespace(id=7, name="Provider", type="openai"),
            )
        ),
    )
    monkeypatch.setattr(model_capabilities, "desktop_model_capabilities", AsyncMock(return_value=ChatCapabilities()))
    result = await project_workbench_config(config, 20)
    assert [(model.id, model.displayName) for model in result.models] == [("42", "Custom label")]
    assert result.models[0].provider_id == "7"
    assert result.models[0].provider_name == "Provider"
    assert result.chat_default_model_id == "42"
    assert config.models[0].displayName == "Custom label"
    assert config.models[0].description == "Retain"
    assert len(config.models) == 2


@pytest.mark.asyncio
async def test_admin_settings_preserve_raw_metadata_and_check_tenant_scope(monkeypatch):
    from importlib import import_module

    from bisheng.llm.domain.schemas import WorkbenchModelConfig

    api = import_module("bisheng.llm.api.router")
    config = WorkbenchModelConfig(
        models=[
            WSModel(id="42", displayName="Custom label", description="Retain"),
            WSModel(id="99", displayName="Private"),
        ],
        chat_default_model_id="99",
    )
    guard = AsyncMock()
    reader = AsyncMock(return_value=(config, False, False))
    monkeypatch.setattr(api, "_resolve_write_target", lambda user: 7)
    monkeypatch.setattr(api, "_assert_can_write_system_config", guard)
    monkeypatch.setattr(api.LLMService, "aget_workbench_llm_with_meta", reader)
    user = SimpleNamespace(user_id=20)
    response = await api.get_workbench_settings(user)
    guard.assert_awaited_once_with(user, 7)
    reader.assert_awaited_once_with(tenant_id=7)
    payload = response["data"]["data"] if isinstance(response, dict) else response.data["data"]
    assert [row["displayName"] for row in payload["models"]] == ["Custom label", "Private"]
    assert payload["models"][0]["description"] == "Retain"
    assert payload["chat_default_model_id"] == "99"


@pytest.mark.asyncio
async def test_admin_settings_scope_denial_precedes_metadata_read(monkeypatch):
    from importlib import import_module

    api = import_module("bisheng.llm.api.router")
    reader = AsyncMock()
    monkeypatch.setattr(api, "_resolve_write_target", lambda user: 7)
    monkeypatch.setattr(api, "_assert_can_write_system_config", AsyncMock(side_effect=PermissionError("tenant")))
    monkeypatch.setattr(api.LLMService, "aget_workbench_llm_with_meta", reader)
    with pytest.raises(PermissionError):
        await api.get_workbench_settings(SimpleNamespace(user_id=20))
    reader.assert_not_awaited()

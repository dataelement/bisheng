from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import WSModel
from bisheng.dsh.domain.services.model_display import configured_display_names, model_display_name


async def test_cross_home_management_display_does_not_build_personal_policy(monkeypatch):
    """AC-42: display the verified target config without inventing a Home."""
    from bisheng.common.services import config_service
    from bisheng.core.context.tenant import get_current_tenant_id, management_tenant_scope
    from bisheng.dsh import runtime
    from bisheng.dsh.domain.services import model_catalog
    from bisheng.llm.domain.schemas import WorkbenchModelConfig
    from bisheng.llm.domain.services.llm import LLMService

    monkeypatch.setattr(config_service, "settings", SimpleNamespace(dsh=SimpleNamespace(enabled=True)))
    operator = SimpleNamespace(user_id=191, tenant_id=1, is_global_super=True)
    verified = WorkbenchModelConfig(models=[WSModel(id="42")])
    monkeypatch.setattr(LLMService, "get_workbench_llm", AsyncMock(return_value=verified))
    personal = AsyncMock(side_effect=AssertionError("must not build a child-tenant personal policy"))
    monkeypatch.setattr(runtime, "read_policy", personal)
    projector = AsyncMock(return_value=[WSModel(id="42")])
    monkeypatch.setattr(model_catalog, "_project_models", projector)
    with management_tenant_scope(60):
        result = await model_catalog.workbench_models_for_display(operator)
        assert get_current_tenant_id() == 60
    assert result[0].id == "42"
    assert operator.tenant_id == 1
    personal.assert_not_awaited()
    projector.assert_awaited_once_with(verified, [42])


async def test_cross_home_display_denies_non_super_instead_of_faking_policy():
    """AC-42: a scope value is not an administrator grant."""
    from bisheng.common.errcode.dsh import DshModelNotAllowedError
    from bisheng.core.context.tenant import management_tenant_scope
    from bisheng.dsh.domain.services.model_catalog import workbench_models_for_display

    with management_tenant_scope(60), pytest.raises(DshModelNotAllowedError):
        await workbench_models_for_display(SimpleNamespace(user_id=9, tenant_id=1, is_global_super=False))


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
    monkeypatch.setattr(api, "_read_default_metadata", reader)
    user = SimpleNamespace(user_id=20)
    response = await api.get_workbench_settings(user)
    guard.assert_awaited_once_with(user, 7)
    reader.assert_awaited_once_with("linsight_llm", user)
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
    monkeypatch.setattr(api, "_read_default_metadata", reader)
    with pytest.raises(PermissionError):
        await api.get_workbench_settings(SimpleNamespace(user_id=20))
    reader.assert_not_awaited()


async def test_cross_home_display_without_dsh_uses_verified_online_candidates(monkeypatch):
    from bisheng.common.services import config_service
    from bisheng.core.context.tenant import management_tenant_scope
    from bisheng.dsh.domain.services import model_catalog
    from bisheng.llm.domain.schemas import WorkbenchModelConfig
    from bisheng.llm.domain.services.llm import LLMService

    monkeypatch.setattr(config_service, "settings", SimpleNamespace(dsh=SimpleNamespace(enabled=False)))
    verified = WorkbenchModelConfig(models=[WSModel(id="42", displayName="Target label")])
    monkeypatch.setattr(LLMService, "get_workbench_llm", AsyncMock(return_value=verified))
    model = SimpleNamespace(id=42, model_name="model", name="internal")
    server = SimpleNamespace(id=7, name="Provider", type="openai")
    monkeypatch.setattr(LLMService, "aget_online_chat_models", AsyncMock(return_value=[(model, server)]))
    personal = AsyncMock(side_effect=AssertionError("management display must not read personal policy"))
    monkeypatch.setattr(model_catalog, "read_visible_model_ids", personal)
    with management_tenant_scope(60):
        models = await model_catalog.workbench_models_for_display(
            SimpleNamespace(user_id=191, tenant_id=1, is_global_super=True)
        )
    assert [(row.id, row.displayName) for row in models] == [("42", "Target label")]
    personal.assert_not_awaited()


async def test_same_home_display_keeps_mode_aware_user_catalog(monkeypatch):
    from bisheng.dsh.domain.services import model_catalog

    expected = [WSModel(id="42")]
    reader = AsyncMock(return_value=expected)
    monkeypatch.setattr(model_catalog, "user_workbench_models", reader)
    operator = SimpleNamespace(user_id=191, tenant_id=1, is_global_super=True)
    assert await model_catalog.workbench_models_for_display(operator) == expected
    reader.assert_awaited_once_with(191, None)

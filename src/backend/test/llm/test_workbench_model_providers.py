from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.api.v1.schemas import WSModel
from bisheng.llm.domain.models import LLMDao
from bisheng.llm.domain.schemas import WorkbenchModelConfig
from bisheng.llm.domain.services.llm import LLMService
from bisheng.workstation.domain.services.workstation_service import WorkStationService


async def test_picker_projects_providers_only_for_configured_models_without_credentials(monkeypatch):
    config = WorkbenchModelConfig(models=[WSModel(id="42", name="old", displayName="Custom label")])
    monkeypatch.setattr(LLMService, "get_workbench_llm", AsyncMock(return_value=config))
    monkeypatch.setattr(
        LLMDao,
        "aget_model_by_ids",
        AsyncMock(return_value=[SimpleNamespace(id=42, server_id=7, model_name="vendor/model")]),
    )
    monkeypatch.setattr(
        LLMDao,
        "aget_server_by_ids",
        AsyncMock(return_value=[SimpleNamespace(id=7, name="Provider", type="openai", config={"api_key": "secret"})]),
    )
    monkeypatch.setattr(WorkStationService, "_aresolve_tenant_config", AsyncMock(return_value=("{}", False, 1, False)))
    result = await WorkStationService.aget_config()
    model = result.models[0].model_dump()
    assert (model["id"], model["name"], model["displayName"]) == ("42", "vendor/model", "Custom label")
    assert (model["provider_id"], model["provider_name"]) == ("7", "Provider")
    assert "config" not in model
    assert "api_key" not in model
    assert config.models[0].name == "old"


async def test_empty_picker_does_not_read_the_provider_catalog(monkeypatch):
    monkeypatch.setattr(LLMService, "get_workbench_llm", AsyncMock(return_value=WorkbenchModelConfig(models=[])))
    read = AsyncMock()
    monkeypatch.setattr(LLMDao, "aget_server_by_ids", read)
    assert (await LLMService.get_workbench_llm_for_picker()).models == []
    read.assert_not_awaited()

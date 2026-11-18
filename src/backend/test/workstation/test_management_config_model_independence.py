"""Workbench administration must remain usable when model defaults are invalid."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import WorkstationConfig
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.llm.domain.services.llm import LLMService
from bisheng.workstation.api.endpoints import config as config_endpoint
from bisheng.workstation.domain.services.workstation_service import WorkStationService


@pytest.fixture
def invalid_model_defaults(monkeypatch):
    reader = AsyncMock(side_effect=ResourceReferenceInvalidError(reason="reference_target_invalid"))
    monkeypatch.setattr(LLMService, "get_workbench_llm", reader)
    monkeypatch.setattr(WorkStationService, "sync_tool_info", classmethod(lambda cls, tools: tools))
    return reader


def _stored_config():
    return {
        "welcomeMessage": "Saved tenant welcome",
        "tabDisplayName": "Tenant home",
        "tools": [],
        "orgKbs": [],
        "recommendedApps": [],
        "models": [{"id": "908", "name": "legacy unavailable model"}],
    }


@pytest.mark.parametrize("inherited", [False, True])
async def test_management_get_preserves_settings_and_provenance_without_model_admission(
    monkeypatch, invalid_model_defaults, inherited
):
    source_tenant = 1 if inherited else 60
    resolve = AsyncMock(return_value=(json.dumps(_stored_config()), inherited, source_tenant, not inherited))
    monkeypatch.setattr(WorkStationService, "_aresolve_tenant_config", resolve)

    # The real inherited projection still runs; these empty resource pools need no DB.
    response = await config_endpoint.get_daily_config(request=None, login_user=SimpleNamespace(user_id=191))

    assert response.status_code == 200
    assert response.data["data"]["welcomeMessage"] == "Saved tenant welcome"
    assert response.data["data"]["tabDisplayName"] == "Tenant home"
    assert response.data["data"]["models"] is None
    assert response.data["inherited_from_root"] is inherited
    assert response.data["source_tenant_id"] == source_tenant
    assert response.data["has_override"] is not inherited
    assert response.data["is_fallback"] is False
    invalid_model_defaults.assert_not_awaited()


async def test_management_save_and_readback_do_not_admit_model_defaults(monkeypatch, invalid_model_defaults):
    stored = {}

    async def save(key, *, payload):
        stored["payload"] = payload

    async def resolve(key):
        return stored["payload"], False, 60, True

    monkeypatch.setattr(WorkStationService, "_aupsert_tenant_config", save)
    monkeypatch.setattr(WorkStationService, "_aresolve_tenant_config", resolve)
    config = WorkstationConfig(**_stored_config())
    config.welcomeMessage = "Updated tenant welcome"

    response = await config_endpoint.update_daily_config(request=None, data=config, login_user=SimpleNamespace())

    assert response.status_code == 200
    assert response.data.welcomeMessage == "Updated tenant welcome"
    assert response.data.models is None
    assert json.loads(stored["payload"])["models"] is None
    invalid_model_defaults.assert_not_awaited()


async def test_runtime_config_still_rejects_invalid_model_defaults(monkeypatch, invalid_model_defaults):
    monkeypatch.setattr(
        WorkStationService,
        "_aresolve_tenant_config",
        AsyncMock(return_value=(json.dumps(_stored_config()), False, 60, True)),
    )

    with pytest.raises(ResourceReferenceInvalidError):
        await WorkStationService.get_daily_chat_config()

    invalid_model_defaults.assert_awaited_once()


async def test_management_config_still_propagates_storage_failure(monkeypatch, invalid_model_defaults):
    monkeypatch.setattr(
        WorkStationService, "_aresolve_tenant_config", AsyncMock(side_effect=RuntimeError("storage unavailable"))
    )

    with pytest.raises(RuntimeError, match="storage unavailable"):
        await WorkStationService.get_daily_chat_config_with_meta()

    invalid_model_defaults.assert_not_awaited()

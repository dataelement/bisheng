"""Consolidation model option in the workstation config (AC-106)."""

import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import WorkstationConfig, WSModel
from bisheng.common.errcode.memory import MemoryNoModelError
from bisheng.memory.domain.services import consolidation_model
from bisheng.workstation.domain.services.workstation_service import WorkStationService


def test_ac106_memory_model_id_saved_and_read_back():
    """AC-106: memory_model_id survives the JSON persistence used by the config store."""
    cfg = WorkstationConfig(memory_model_id=42)
    payload = json.dumps(cfg.model_copy(update={"models": None}).model_dump(mode="json"))
    parsed = WorkStationService.parse_config(SimpleNamespace(value=payload))
    assert parsed.memory_model_id == 42


def test_ac106_missing_field_defaults_to_none():
    parsed = WorkStationService.parse_config(SimpleNamespace(value=json.dumps({"welcomeMessage": "hi"})))
    assert parsed.memory_model_id is None


def test_ac106_only_tenant_admin_can_update():
    """AC-106: the save endpoint is the existing daily config endpoint guarded by the tenant-admin dependency."""
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.workstation.api.endpoints import config as config_endpoints

    dep = inspect.signature(config_endpoints.update_daily_config).parameters["login_user"].default
    assert dep.dependency == UserPayload.get_tenant_admin_user


def test_no_memory_switch_in_workstation_config():
    """There is no tenant-level memory switch: memory_model_id is the only memory field."""
    memory_fields = [name for name in WorkstationConfig.model_fields if "memory" in name.lower()]
    assert memory_fields == ["memory_model_id"]


def _cfg(memory_model_id=None, models=None):
    return WorkstationConfig(memory_model_id=memory_model_id, models=models)


@pytest.mark.parametrize(
    "cfg,expected",
    [
        (_cfg(7, [WSModel(id="3")]), 7),
        (_cfg(None, [WSModel(id="3"), WSModel(id="4")]), 3),
    ],
)
async def test_ac106_resolve_model(monkeypatch, cfg, expected):
    """AC-106: configured model first, otherwise the first workstation model."""
    monkeypatch.setattr(consolidation_model.WorkStationService, "aget_config", AsyncMock(return_value=cfg))
    assert await consolidation_model.resolve_memory_model_id() == expected


@pytest.mark.parametrize("cfg", [_cfg(None, []), _cfg(None, None), None])
async def test_ac106_no_model_available(monkeypatch, cfg):
    monkeypatch.setattr(consolidation_model.WorkStationService, "aget_config", AsyncMock(return_value=cfg))
    with pytest.raises(MemoryNoModelError):
        await consolidation_model.resolve_memory_model_id()


async def test_ac106_child_tenant_inherits_root_value(monkeypatch):
    """A child tenant without its own config gets the root value through aget_config's inheritance."""
    root_value = json.dumps({"memory_model_id": 9})
    monkeypatch.setattr(
        WorkStationService,
        "_aresolve_tenant_config",
        AsyncMock(return_value=(root_value, True, 1, False)),
    )
    monkeypatch.setattr(
        WorkStationService, "_aproject_daily_config_for_current_tenant", AsyncMock(side_effect=lambda cfg, _tid: cfg)
    )
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service.LLMService.get_workbench_llm",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(WorkStationService, "_apply_workbench_models", classmethod(lambda cls, cfg, _wb: cfg))
    assert await consolidation_model.resolve_memory_model_id() == 9

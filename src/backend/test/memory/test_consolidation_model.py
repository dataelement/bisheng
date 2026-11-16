"""Memory consolidation model in the system model settings, workbench section (AC-106)."""

import inspect
import json
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import WorkstationConfig
from bisheng.common.errcode.memory import MemoryNoModelError
from bisheng.llm.domain.schemas import WorkbenchModelConfig, WSModel
from bisheng.llm.domain.services import llm as llm_service
from bisheng.llm.domain.services.llm import LLMService
from bisheng.memory.domain.services import consolidation_model


def test_ac106_memory_llm_saved_and_read_back():
    """AC-106: memory_llm survives the JSON persistence of the workbench model settings."""
    payload = json.dumps(WorkbenchModelConfig(memory_llm=WSModel(id="42")).model_dump(mode="json"))
    assert WorkbenchModelConfig(**json.loads(payload)).memory_llm.id == "42"
    assert WorkbenchModelConfig(**json.loads("{}")).memory_llm is None


def test_ac106_only_tenant_admin_can_update():
    """AC-106: saved through the existing workbench model endpoint guarded by the tenant-admin dependency."""
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.llm.api import router as llm_router

    dep = inspect.signature(llm_router.update_workbench_llm).parameters["login_user"].default
    assert dep.dependency == UserPayload.get_tenant_admin_user


def test_workstation_config_has_no_memory_field():
    """The setting moved to the system model settings; the workbench (daily chat) config has none."""
    assert [name for name in WorkstationConfig.model_fields if "memory" in name.lower()] == []


def test_memory_llm_is_a_checked_model_reference():
    """Inaccessible models are dropped like the other single-model fields."""
    cfg = WorkbenchModelConfig(memory_llm=WSModel(id="5"), chat_title_llm=WSModel(id="6"))
    assert "5" in llm_service._workbench_model_ref_values(cfg)
    filtered = LLMService._filter_workbench_config(cfg, {6})
    assert filtered.memory_llm is None and filtered.chat_title_llm.id == "6"


def _cfg(memory_llm=None, models=None):
    return WorkbenchModelConfig(memory_llm=WSModel(id=memory_llm) if memory_llm else None, models=models)


@pytest.mark.parametrize(
    "cfg,expected",
    [
        (_cfg("7", [WSModel(id="3")]), 7),
        (_cfg(None, [WSModel(id="3"), WSModel(id="4")]), 3),
    ],
)
async def test_ac106_resolve_model(monkeypatch, cfg, expected):
    """AC-106: the configured model first, otherwise the first daily-chat model."""
    monkeypatch.setattr(consolidation_model.LLMService, "get_workbench_llm", AsyncMock(return_value=cfg))
    assert await consolidation_model.resolve_memory_model_id() == expected


@pytest.mark.parametrize("cfg", [_cfg(None, []), _cfg(None, None), None])
async def test_ac106_no_model_available(monkeypatch, cfg):
    monkeypatch.setattr(consolidation_model.LLMService, "get_workbench_llm", AsyncMock(return_value=cfg))
    with pytest.raises(MemoryNoModelError):
        await consolidation_model.resolve_memory_model_id()


async def test_ac106_child_tenant_inherits_root_value(monkeypatch):
    """A child tenant without its own row gets the root value through the settings inheritance."""
    root_value = json.dumps({"memory_llm": {"id": "9"}})
    monkeypatch.setattr(llm_service, "_resolve_tenant_id", lambda tenant_id: 2)
    monkeypatch.setattr(
        llm_service.TenantSystemModelConfigDao, "aresolve", AsyncMock(return_value=(root_value, True, False))
    )
    monkeypatch.setattr(
        LLMService,
        "_sanitize_workbench_config_refs",
        classmethod(lambda cls, cfg, _tid, inherited_from_root: _identity(cfg)),
    )
    assert await consolidation_model.resolve_memory_model_id() == 9


async def _identity(value):
    return value

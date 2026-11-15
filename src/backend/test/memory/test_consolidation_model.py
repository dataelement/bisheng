"""Memory consolidation model in the system model settings, workbench section (AC-106)."""

import inspect
import json
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import WorkstationConfig
from bisheng.common.errcode.memory import MemoryNoModelError
from bisheng.llm.domain.schemas import WorkbenchModelConfig, WSModel
from bisheng.llm.domain.services import llm as llm_service
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
    """memory_llm is a saved model reference like the other single-model fields, so deleting
    or hiding the model is fenced and an invalid id fails the admitted read."""
    from bisheng.llm.domain.services.default_reference_extractor import extract_model_default_references

    cfg = WorkbenchModelConfig(memory_llm=WSModel(id="5"), chat_title_llm=WSModel(id="6"))
    slots = {ref.slot_key: ref.target.target_id for ref in extract_model_default_references("linsight_llm", cfg)}
    assert slots["memory_llm.id"] == "5" and slots["chat_title_llm.id"] == "6"


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
    """A child tenant without its own row reads the root value the admitted read returns."""
    from types import SimpleNamespace

    root_value = json.dumps({"memory_llm": {"id": "9"}})
    runtime = SimpleNamespace(arequire_default=AsyncMock(return_value=SimpleNamespace(payload_json=root_value)))
    monkeypatch.setattr(llm_service, "get_model_default_read_runtime", lambda: runtime)
    monkeypatch.setattr(llm_service, "current_model_default_tenant", lambda _tenant_id: 2)
    assert await consolidation_model.resolve_memory_model_id() == 9

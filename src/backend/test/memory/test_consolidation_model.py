"""Memory consolidation model in the system model settings, workbench section (AC-106)."""

import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import WorkstationConfig
from bisheng.common.errcode.memory import MemoryNoModelError
from bisheng.llm.domain.repositories.reference_target_repository import ModelReferenceTargetRepository
from bisheng.llm.domain.schemas import WorkbenchModelConfig, WSModel
from bisheng.llm.domain.services.default_reference_extractor import (
    WORKBENCH_MODEL_OBJECTS,
    extract_model_default_references,
)
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
    """memory_llm is a model reference slot of the workbench defaults, like the other single-model fields.

    3.1 checks system-model defaults through the reference bindings: every saved
    slot is extracted and its target model verified, so an inaccessible model
    cannot be saved or read back.
    """
    assert "memory_llm" in WORKBENCH_MODEL_OBJECTS
    cfg = WorkbenchModelConfig(memory_llm=WSModel(id="5"), chat_title_llm=WSModel(id="6"))
    refs = {(ref.slot_key, ref.target.target_id) for ref in extract_model_default_references("linsight_llm", cfg)}
    assert {("memory_llm.id", "5"), ("chat_title_llm.id", "6")} <= refs


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
    """A child tenant without its own row gets the root value through the settings inheritance.

    3.1 resolves system-model defaults generically per key (Root row when the
    child has none and Root shares defaults; covered for every key in
    test/knowledge_unification/test_llm_default_repository.py). What is
    memory-specific: the child may use the Root-owned memory_llm model, and
    consolidation picks it from the inherited workbench payload.
    """
    root_value = '{"memory_llm":{"id":"9"}}'
    topology = {
        1: SimpleNamespace(id=1, parent_tenant_id=None, share_default_to_children=1),
        101: SimpleNamespace(id=101, parent_tenant_id=1, share_default_to_children=0),
    }
    configs = [SimpleNamespace(tenant_id=1, key="linsight_llm", value=root_value)]
    assert 9 in ModelReferenceTargetRepository._inherited_ids(topology, configs, 101)

    inherited = WorkbenchModelConfig.model_validate_json(root_value)
    monkeypatch.setattr(consolidation_model.LLMService, "get_workbench_llm", AsyncMock(return_value=inherited))
    assert await consolidation_model.resolve_memory_model_id() == 9

"""The first LLM a platform adds becomes its conversation-title model."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.llm.domain.schemas import WorkbenchModelConfig, WSModel
from bisheng.llm.domain.services.llm import LLMService


@pytest.fixture
def config_store(monkeypatch):
    store = {"workbench": WorkbenchModelConfig(), "saved": None}

    async def get_workbench():
        return store["workbench"]

    async def update(_user, workbench, _tasks):
        store["saved"] = workbench

    monkeypatch.setattr(LLMService, "get_workbench_llm", get_workbench)
    monkeypatch.setattr(LLMService, "update_workbench_llm", update)
    # The LLM branch also seeds the knowledge, evaluation and assistant slots.
    monkeypatch.setattr(
        LLMService,
        "aget_knowledge_llm",
        AsyncMock(return_value=SimpleNamespace(extract_title_model_id=1, source_model_id=1, qa_similar_model_id=1)),
    )
    monkeypatch.setattr(LLMService, "get_evaluation_llm", AsyncMock(return_value=SimpleNamespace(model_id=1)))
    monkeypatch.setattr(
        LLMService, "get_assistant_llm", AsyncMock(return_value=SimpleNamespace(auto_llm=1, llm_list=[1]))
    )
    return store


@pytest.mark.parametrize("empty_slot", [None, WSModel(id="")])
async def test_first_llm_fills_an_empty_title_slot(config_store, empty_slot):
    config_store["workbench"].chat_title_llm = empty_slot

    await LLMService.set_default_model(SimpleNamespace(id=30, model_type="llm", model_name="dsv4"))

    assert config_store["saved"].chat_title_llm.id == "30"


async def test_a_chosen_title_model_is_kept(config_store):
    config_store["workbench"].chat_title_llm = WSModel(id="7")

    await LLMService.set_default_model(SimpleNamespace(id=30, model_type="llm", model_name="dsv4"))

    assert config_store["saved"] is None


@pytest.mark.parametrize("first_llm_id, seeded", [(30, True), (5, False)])
async def test_only_the_first_llm_on_the_platform_seeds_defaults(monkeypatch, first_llm_id, seeded):
    from bisheng.llm.domain.models.llm_server import LLMDao

    monkeypatch.setattr(LLMDao, "aget_model_by_type", AsyncMock(return_value=SimpleNamespace(id=first_llm_id)))
    set_default = AsyncMock()
    monkeypatch.setattr(LLMService, "set_default_model", set_default)
    monkeypatch.setattr(LLMService, "probe_models_in_background", AsyncMock())
    server = SimpleNamespace(models=[SimpleNamespace(id=30, model_type="llm")])

    await LLMService.add_llm_server_hook(None, None, server)

    assert set_default.await_count == (1 if seeded else 0)

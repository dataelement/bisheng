"""F002 coverage AC: AC-01, AC-11, AC-16; retired defaults cannot execute or bind."""

from types import SimpleNamespace

import pytest

from bisheng.common.models.config import ConfigKeyEnum
from bisheng.llm.domain.schemas import KnowledgeLLMConfig, WorkbenchModelConfig
from bisheng.llm.domain.services.default_reference_extractor import extract_model_default_references
from bisheng.llm.domain.services.system_model_autofill import fill_empty_slots


@pytest.mark.parametrize("value", [999, "deleted-model", {"invalid": True}])
def test_retired_knowledge_model_is_ignored_even_in_raw_historical_payload(value):
    payload = {"source_model_id": value, "qa_similar_model_id": 12}
    assert "source_model_id" not in KnowledgeLLMConfig.model_validate(payload).model_dump()
    refs = extract_model_default_references("knowledge_llm", payload)
    assert [(ref.slot_key, ref.target.target_id) for ref in refs] == [("qa_similar_model_id", "12")]


@pytest.mark.parametrize("value", [None, {"id": "999"}, {"broken": True}])
def test_retired_workbench_embedding_is_ignored(value):
    payload = {"embedding_model": value, "models": [{"id": "12"}]}
    assert "embedding_model" not in WorkbenchModelConfig.model_validate(payload).model_dump()
    refs = extract_model_default_references("linsight_llm", payload)
    assert [(ref.slot_key, ref.target.target_id) for ref in refs] == [("models.12.id", "12")]


def test_automatic_configuration_never_fills_retired_slots():
    model = SimpleNamespace(id=12, model_type="embedding", model_name="embedding")
    assert fill_empty_slots(ConfigKeyEnum.LINSIGHT_LLM, WorkbenchModelConfig(), model) == []
    knowledge = KnowledgeLLMConfig()
    assert fill_empty_slots(ConfigKeyEnum.KNOWLEDGE_LLM, knowledge, model) == ["knowledge_llm.embedding_model_id"]
    filled = fill_empty_slots(
        ConfigKeyEnum.KNOWLEDGE_LLM, knowledge, SimpleNamespace(id=13, model_type="llm", model_name="chat")
    )
    assert "knowledge_llm.source_model_id" not in filled

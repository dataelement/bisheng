"""Registry of system-model settings a newly added model fills when empty (F118 / 3.1)."""

from types import SimpleNamespace

from bisheng.common.models.config import ConfigKeyEnum
from bisheng.llm.domain.schemas import (
    AssistantLLMConfig,
    EvaluationLLMConfig,
    KnowledgeLLMConfig,
    WorkbenchModelConfig,
    WSModel,
)
from bisheng.llm.domain.services.system_model_autofill import KIND_ASR, SLOTS, fill_empty_slots, kind_of

LLM = SimpleNamespace(id=1, model_type="llm", model_name="chat-a")
EMBED = SimpleNamespace(id=2, model_type="embedding", model_name="embed-a")
ASR = SimpleNamespace(id=3, model_type="asr_rt", model_name="asr-a")
TTS = SimpleNamespace(id=4, model_type="tts", model_name="tts-a")


def test_every_slot_id_is_unique():
    assert len({slot.id for slot in SLOTS}) == len(SLOTS)


def test_first_llm_fills_every_llm_setting_including_later_ones():
    workbench = WorkbenchModelConfig()
    filled = fill_empty_slots(ConfigKeyEnum.LINSIGHT_LLM, workbench, LLM)

    assert set(filled) == {
        "linsight_llm.models",
        "linsight_llm.chat_default_model_id",
        "linsight_llm.linsight_default_model_id",
        "linsight_llm.chat_title_llm",
    }
    assert [m.id for m in workbench.models] == ["1"]
    assert workbench.linsight_default_model_id == "1"
    assert workbench.chat_default_model_id == "1"
    assert workbench.embedding_model is None  # another kind

    workflow = EvaluationLLMConfig()
    assert fill_empty_slots(ConfigKeyEnum.WORKFLOW_LLM, workflow, LLM) == ["workflow_llm.model_id"]
    assert workflow.model_id == 1

    assistant = AssistantLLMConfig()
    fill_empty_slots(ConfigKeyEnum.ASSISTANT_LLM, assistant, LLM)
    assert assistant.auto_llm.model_id == 1
    assert assistant.llm_list[0].model_id == 1


def test_defaults_point_into_the_configured_model_list():
    workbench = WorkbenchModelConfig(models=[WSModel(id="7", name="chat-b")], chat_default_model_id="7")

    fill_empty_slots(ConfigKeyEnum.LINSIGHT_LLM, workbench, LLM)

    assert workbench.linsight_default_model_id == "7"
    assert [m.id for m in workbench.models] == ["7"]


def test_set_values_are_kept():
    knowledge = KnowledgeLLMConfig(embedding_model_id=9)
    assert fill_empty_slots(ConfigKeyEnum.KNOWLEDGE_LLM, knowledge, EMBED) == []
    assert knowledge.embedding_model_id == 9


def test_speech_models_fill_workbench_and_knowledge_slots():
    workbench = WorkbenchModelConfig()
    knowledge = KnowledgeLLMConfig()
    assert fill_empty_slots(ConfigKeyEnum.LINSIGHT_LLM, workbench, ASR) == ["linsight_llm.asr_model"]
    assert fill_empty_slots(ConfigKeyEnum.KNOWLEDGE_LLM, knowledge, ASR) == ["knowledge_llm.asr_model_id"]
    assert fill_empty_slots(ConfigKeyEnum.LINSIGHT_LLM, workbench, TTS) == ["linsight_llm.tts_model"]
    assert workbench.embedding_model is None
    assert fill_empty_slots(ConfigKeyEnum.LINSIGHT_LLM, workbench, EMBED) == ["linsight_llm.embedding_model"]
    assert kind_of("asr") == KIND_ASR
    assert kind_of("rerank") is None

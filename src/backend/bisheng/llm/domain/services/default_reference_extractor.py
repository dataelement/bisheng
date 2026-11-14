"""Only the five original business configurations contribute default bindings."""

from types import MappingProxyType

from pydantic import BaseModel

from bisheng.llm.domain.schemas import AssistantLLMConfig, EvaluationLLMConfig, KnowledgeLLMConfig, WorkbenchModelConfig
from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    TargetKey,
    canonical_target_id,
    normalize_references,
)

MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION = "model-default-v1"
MODEL_DEFAULT_SCHEMAS = MappingProxyType(
    {
        "knowledge_llm": KnowledgeLLMConfig,
        "assistant_llm": AssistantLLMConfig,
        "evaluation_llm": EvaluationLLMConfig,
        "workflow_llm": EvaluationLLMConfig,
        "linsight_llm": WorkbenchModelConfig,
    }
)
KNOWLEDGE_MODEL_SLOTS = (
    "embedding_model_id",
    "source_model_id",
    "extract_title_model_id",
    "qa_similar_model_id",
    "asr_model_id",
)
WORKBENCH_MODEL_OBJECTS = ("embedding_model", "asr_model", "tts_model", "chat_title_llm", "memory_llm", "image_read_model")


def extract_model_default_references(key: str, payload: dict | BaseModel) -> tuple[ReferenceSpec, ...]:
    if key not in MODEL_DEFAULT_SCHEMAS:
        raise ValueError("only original system-model keys are reference sources")
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    if not isinstance(payload, dict):
        raise ValueError("model defaults must be a JSON object")
    # Validate the business shape, but extract raw IDs so coercion cannot turn a
    # boolean into model 1. This function never rewrites the original JSON.
    MODEL_DEFAULT_SCHEMAS[key].model_validate(payload)
    result = []

    def add(slot, value):
        if value is None or value == "":
            return
        result.append(ReferenceSpec(slot, TargetKey("model", canonical_target_id(value))))

    def member(array, member_field, suffix):
        for item in payload.get(array) or ():
            value = item.get(member_field)
            if value is None or value == "":
                continue
            normalized = canonical_target_id(value)
            add(f"{array}.{normalized}.{suffix}", value)

    if key == "knowledge_llm":
        for name in KNOWLEDGE_MODEL_SLOTS:
            add(name, payload.get(name))
    elif key == "assistant_llm":
        member("llm_list", "model_id", "model_id")
        add("auto_llm.model_id", (payload.get("auto_llm") or {}).get("model_id"))
    elif key in {"evaluation_llm", "workflow_llm"}:
        add("model_id", payload.get("model_id"))
    else:
        member("models", "id", "id")
        for name in ("linsight_default_model_id", "chat_default_model_id"):
            add(name, payload.get(name))
        for name in WORKBENCH_MODEL_OBJECTS:
            add(f"{name}.id", (payload.get(name) or {}).get("id"))
    return normalize_references(tuple(result))

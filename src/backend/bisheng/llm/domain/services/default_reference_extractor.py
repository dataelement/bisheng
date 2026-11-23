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
WORKBENCH_MODEL_OBJECTS = ("embedding_model", "asr_model", "tts_model", "chat_title_llm", "image_read_model")


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


def validate_model_default_slots(key: str, slots: tuple[str, ...], references: tuple[ReferenceSpec, ...]) -> None:
    """Only source-defined list members or statically registered scalar slots."""
    if key not in MODEL_DEFAULT_SCHEMAS or not isinstance(slots, tuple) or len(set(slots)) != len(slots):
        raise ValueError("invalid model-default slot selection")
    static = {
        "knowledge_llm": KNOWLEDGE_MODEL_SLOTS,
        "assistant_llm": ("auto_llm.model_id",),
        "evaluation_llm": ("model_id",),
        "workflow_llm": ("model_id",),
        "linsight_llm": (
            "linsight_default_model_id",
            "chat_default_model_id",
            *(f"{name}.id" for name in WORKBENCH_MODEL_OBJECTS),
        ),
    }
    registered = set(static[key]) | {reference.slot_key for reference in references}
    if any(not isinstance(slot, str) or slot not in registered for slot in slots):
        raise ValueError("unknown model-default slot")


def project_model_default(key: str, payload: dict, slots: tuple[str, ...]) -> dict:
    """Preserve parameters, but never return an unadmitted model reference."""
    from copy import deepcopy

    result = deepcopy(payload)
    if key == "knowledge_llm":
        for name in KNOWLEDGE_MODEL_SLOTS:
            if name not in slots:
                result[name] = None
    elif key == "assistant_llm":
        result["llm_list"] = [
            item
            for item in result.get("llm_list") or []
            if item.get("model_id") not in (None, "")
            and f"llm_list.{canonical_target_id(item['model_id'])}.model_id" in slots
        ]
        if "auto_llm.model_id" not in slots:
            result["auto_llm"] = None
    elif key in {"evaluation_llm", "workflow_llm"}:
        if "model_id" not in slots:
            result["model_id"] = None
    else:
        result["models"] = [
            item
            for item in result.get("models") or []
            if item.get("id") not in (None, "") and f"models.{canonical_target_id(item['id'])}.id" in slots
        ]
        for name in ("linsight_default_model_id", "chat_default_model_id"):
            if name not in slots:
                result[name] = None
        for name in WORKBENCH_MODEL_OBJECTS:
            if f"{name}.id" not in slots:
                result[name] = None
    return result


def model_default_slot_types(key: str, slot: str) -> frozenset[str]:
    if slot in {"embedding_model_id", "embedding_model.id"}:
        return frozenset({"embedding"})
    if slot in {"asr_model_id", "asr_model.id"}:
        return frozenset({"asr", "asr_rt"})
    if slot == "tts_model.id":
        return frozenset({"tts"})
    return frozenset({"llm"})


def model_default_models_are_callable(key, references, states):
    return all(
        (state := states.get(int(reference.target.target_id))) is not None
        and state.online
        and state.model_type in model_default_slot_types(key, reference.slot_key)
        for reference in references
    )

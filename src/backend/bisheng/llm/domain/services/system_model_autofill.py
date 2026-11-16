"""Registry of the system-model settings a newly added model fills when empty.

The system-model settings ("系统模型设置") are stored as typed JSON per tenant.
Every setting that takes a model is registered once in ``SLOTS``. When a provider
save adds a model, ``LLMService.set_default_model`` fills each empty slot of that
model's kind in the tenant's own configs (an inherited Root config is left
inherited). A new setting only needs a new ``ModelSlot`` entry.

F118 (3.1): writes go through ``ModelDefaultApplication`` so the reference index
stays in step, and API startup never rewrites a payload; filling settings on an
existing deployment that adds no model is an offline upgrade step.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from bisheng.api.v1.schemas import WSModel
from bisheng.common.models.config import ConfigKeyEnum
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models import LLMModel
from bisheng.llm.domain.schemas import (
    AssistantLLMConfig,
    AssistantLLMItem,
    EvaluationLLMConfig,
    KnowledgeLLMConfig,
    WorkbenchModelConfig,
)

# Model kinds a slot can take. ASR covers file and realtime ASR, as the
# platform's ASR pickers do.
KIND_LLM = "llm"
KIND_EMBEDDING = "embedding"
KIND_ASR = "asr"
KIND_TTS = "tts"

CONFIG_TYPES: dict[ConfigKeyEnum, type[BaseModel]] = {
    ConfigKeyEnum.KNOWLEDGE_LLM: KnowledgeLLMConfig,
    ConfigKeyEnum.ASSISTANT_LLM: AssistantLLMConfig,
    ConfigKeyEnum.EVALUATION_LLM: EvaluationLLMConfig,
    ConfigKeyEnum.WORKFLOW_LLM: EvaluationLLMConfig,
    ConfigKeyEnum.LINSIGHT_LLM: WorkbenchModelConfig,
}


@dataclass(frozen=True)
class ModelSlot:
    """One system-model setting that takes a model.

    ``id`` is stored in the ledger: never rename an existing id, or the slot is
    treated as new and filled again.
    """

    id: str
    config_key: ConfigKeyEnum
    kind: str
    is_set: Callable[[Any], bool]
    fill: Callable[[Any, LLMModel], None]


def _field_slot(config_key: ConfigKeyEnum, field: str, kind: str) -> ModelSlot:
    """A setting that stores a bare model id."""
    return ModelSlot(
        id=f"{config_key.value}.{field}",
        config_key=config_key,
        kind=kind,
        is_set=lambda cfg: getattr(cfg, field) not in (None, ""),
        fill=lambda cfg, model: setattr(cfg, field, model.id),
    )


def _ws_slot(field: str, kind: str) -> ModelSlot:
    """A workbench setting that stores a ``WSModel``."""
    return ModelSlot(
        id=f"{ConfigKeyEnum.LINSIGHT_LLM.value}.{field}",
        config_key=ConfigKeyEnum.LINSIGHT_LLM,
        kind=kind,
        is_set=lambda cfg: bool(getattr(cfg, field) and getattr(cfg, field).id),
        fill=lambda cfg, model: setattr(cfg, field, WSModel(id=str(model.id), name=model.model_name)),
    )


def _ws_option(model: LLMModel) -> WSModel:
    return WSModel(id=str(model.id), name=model.model_name, displayName=model.model_name)


def _fill_workbench_models(cfg: WorkbenchModelConfig, model: LLMModel) -> None:
    cfg.models = [_ws_option(model)]


def _workbench_default_slot(field: str) -> ModelSlot:
    """A workbench default that must be one of the selectable ``models``."""

    def fill(cfg: WorkbenchModelConfig, model: LLMModel) -> None:
        if not cfg.models:
            cfg.models = [_ws_option(model)]
        setattr(cfg, field, str(cfg.models[0].id))

    return ModelSlot(
        id=f"{ConfigKeyEnum.LINSIGHT_LLM.value}.{field}",
        config_key=ConfigKeyEnum.LINSIGHT_LLM,
        kind=KIND_LLM,
        is_set=lambda cfg: getattr(cfg, field) not in (None, ""),
        fill=fill,
    )


def _fill_assistant_auto(cfg: AssistantLLMConfig, model: LLMModel) -> None:
    cfg.auto_llm = AssistantLLMItem(model_id=model.id)


def _fill_assistant_list(cfg: AssistantLLMConfig, model: LLMModel) -> None:
    cfg.llm_list = [AssistantLLMItem(model_id=model.id, default=True)]


# Order matters inside one config: the workbench model list comes before the
# defaults that must point into it. ``image_read_model`` is left out on purpose:
# it needs an image-capable model and has no admin picker.
SLOTS: tuple[ModelSlot, ...] = (
    _field_slot(ConfigKeyEnum.KNOWLEDGE_LLM, "embedding_model_id", KIND_EMBEDDING),
    _field_slot(ConfigKeyEnum.KNOWLEDGE_LLM, "source_model_id", KIND_LLM),
    _field_slot(ConfigKeyEnum.KNOWLEDGE_LLM, "extract_title_model_id", KIND_LLM),
    _field_slot(ConfigKeyEnum.KNOWLEDGE_LLM, "qa_similar_model_id", KIND_LLM),
    _field_slot(ConfigKeyEnum.KNOWLEDGE_LLM, "asr_model_id", KIND_ASR),
    ModelSlot(
        id=f"{ConfigKeyEnum.ASSISTANT_LLM.value}.auto_llm",
        config_key=ConfigKeyEnum.ASSISTANT_LLM,
        kind=KIND_LLM,
        is_set=lambda cfg: bool(cfg.auto_llm and cfg.auto_llm.model_id),
        fill=_fill_assistant_auto,
    ),
    ModelSlot(
        id=f"{ConfigKeyEnum.ASSISTANT_LLM.value}.llm_list",
        config_key=ConfigKeyEnum.ASSISTANT_LLM,
        kind=KIND_LLM,
        is_set=lambda cfg: bool(cfg.llm_list),
        fill=_fill_assistant_list,
    ),
    _field_slot(ConfigKeyEnum.EVALUATION_LLM, "model_id", KIND_LLM),
    _field_slot(ConfigKeyEnum.WORKFLOW_LLM, "model_id", KIND_LLM),
    ModelSlot(
        id=f"{ConfigKeyEnum.LINSIGHT_LLM.value}.models",
        config_key=ConfigKeyEnum.LINSIGHT_LLM,
        kind=KIND_LLM,
        is_set=lambda cfg: bool(cfg.models),
        fill=_fill_workbench_models,
    ),
    _workbench_default_slot("chat_default_model_id"),
    _workbench_default_slot("linsight_default_model_id"),
    _ws_slot("embedding_model", KIND_EMBEDDING),
    _ws_slot("asr_model", KIND_ASR),
    _ws_slot("tts_model", KIND_TTS),
    _ws_slot("chat_title_llm", KIND_LLM),
)


def _kind_of(model_type: str) -> str | None:
    if model_type == LLMModelType.LLM.value:
        return KIND_LLM
    if model_type == LLMModelType.EMBEDDING.value:
        return KIND_EMBEDDING
    if model_type == LLMModelType.TTS.value:
        return KIND_TTS
    if LLMModelType.is_speech(model_type):
        return KIND_ASR
    return None


def kind_of(model_type: str) -> str | None:
    """The slot kind a model type fills, or ``None`` when no slot takes it."""
    return _kind_of((model_type or "").strip())


def fill_empty_slots(config_key: ConfigKeyEnum, cfg: BaseModel, model: LLMModel) -> list[str]:
    """Fill the empty slots of ``config_key`` that take ``model``'s kind. Returns their ids."""
    kind = kind_of(model.model_type)
    filled = []
    for slot in SLOTS:
        if slot.config_key == config_key and slot.kind == kind and not slot.is_set(cfg):
            slot.fill(cfg, model)
            filled.append(slot.id)
    return filled

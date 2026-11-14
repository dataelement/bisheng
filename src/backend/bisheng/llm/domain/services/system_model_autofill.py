"""Fill empty system-model settings from the tenant's own models.

The system-model settings ("系统模型设置") are stored as typed JSON rows in
``tenant_system_model_config``. When a tenant has a model of the right type and a
setting is still empty, this module fills that setting with the tenant's first
model of that type (online models first, then the lowest id).

Every setting that takes a model is registered once in ``SLOTS``. A new setting
only needs a new ``ModelSlot`` entry: the next model save or the next startup
fills it on every existing deployment, without a migration of its own.

Each tenant has a ledger row (``AUTOFILL_LEDGER_KEY``) that lists the slot ids
already handled. A slot enters the ledger when this module fills it, or when this
module first sees it already set. A slot in the ledger is never filled again, so
an admin who later clears an optional setting keeps it empty. A slot stays out
of the ledger while the tenant has no model of its type.

A tenant whose config row for a key is inherited from Root is skipped for that
key: writing an own row would cut the inheritance.

Triggers: a provider save that adds models (``LLMService.add_llm_server_hook`` and
``LLMService.update_llm_server``) and every API startup (``main.lifespan``) for
every tenant that owns at least one model. The fill is deterministic (same
models -> same choice), so concurrent startups on several nodes write the same
values.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger
from pydantic import BaseModel
from sqlmodel import col, select

from bisheng.api.v1.schemas import WSModel
from bisheng.common.models.config import ConfigKeyEnum
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models import LLMModel
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfigDao
from bisheng.llm.domain.schemas import (
    AssistantLLMConfig,
    AssistantLLMItem,
    EvaluationLLMConfig,
    KnowledgeLLMConfig,
    WorkbenchModelConfig,
)

AUTOFILL_LEDGER_KEY = ConfigKeyEnum.SYSTEM_MODEL_AUTOFILL.value

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


async def _first_model_by_kind(tenant_id: int) -> dict[str, LLMModel]:
    """The tenant's own first model of each kind: online first, then lowest id."""
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            rows = (
                await session.exec(
                    select(LLMModel)
                    .where(LLMModel.tenant_id == tenant_id)
                    .order_by(col(LLMModel.online).desc(), col(LLMModel.id).asc())
                )
            ).all()
    picked: dict[str, LLMModel] = {}
    for row in rows:
        kind = _kind_of((row.model_type or "").strip())
        if kind and kind not in picked:
            picked[kind] = row
    return picked


async def _read_ledger(tenant_id: int) -> set[str]:
    row = await TenantSystemModelConfigDao.aget(tenant_id, AUTOFILL_LEDGER_KEY)
    if row is None or not row.value:
        return set()
    try:
        payload = json.loads(row.value)
    except (TypeError, ValueError):
        logger.warning("system-model autofill ledger is not JSON for tenant {}; starting over", tenant_id)
        return set()
    slots = payload.get("slots") if isinstance(payload, dict) else None
    return {str(one) for one in slots} if isinstance(slots, list) else set()


async def _read_own_config(tenant_id: int, key: ConfigKeyEnum) -> BaseModel | None:
    """The tenant's own config for ``key``; ``None`` when the value is inherited."""
    value, inherited, _ = await TenantSystemModelConfigDao.aresolve(tenant_id=tenant_id, key=key.value)
    if inherited:
        return None
    return CONFIG_TYPES[key](**(json.loads(value) if value else {}))


async def autofill_system_models(tenant_id: int, slots: tuple[ModelSlot, ...] = SLOTS) -> list[str]:
    """Fill the tenant's empty, not-yet-handled settings. Returns the filled slot ids.

    Runs inside the tenant's own scope: startup has no tenant context, and the
    tenant filter rejects unscoped reads of tenant tables.
    """
    with tenant_execution_scope(tenant_id):
        return await _autofill_in_scope(tenant_id, slots)


async def _autofill_in_scope(tenant_id: int, slots: tuple[ModelSlot, ...]) -> list[str]:
    ledger = await _read_ledger(tenant_id)
    pending = [slot for slot in slots if slot.id not in ledger]
    if not pending:
        return []
    models = await _first_model_by_kind(tenant_id)
    if not models:
        return []

    configs: dict[ConfigKeyEnum, BaseModel | None] = {}
    changed: set[ConfigKeyEnum] = set()
    filled: list[str] = []
    new_ledger = set(ledger)
    for slot in pending:
        if slot.config_key not in configs:
            configs[slot.config_key] = await _read_own_config(tenant_id, slot.config_key)
        cfg = configs[slot.config_key]
        if cfg is None:
            continue
        if slot.is_set(cfg):
            new_ledger.add(slot.id)
            continue
        model = models.get(slot.kind)
        if model is None:
            continue
        slot.fill(cfg, model)
        new_ledger.add(slot.id)
        changed.add(slot.config_key)
        filled.append(slot.id)

    for key in changed:
        await TenantSystemModelConfigDao.aupsert(
            tenant_id=tenant_id,
            key=key.value,
            value=json.dumps(configs[key].model_dump(), ensure_ascii=False),
        )
    if new_ledger != ledger:
        await TenantSystemModelConfigDao.aupsert(
            tenant_id=tenant_id,
            key=AUTOFILL_LEDGER_KEY,
            value=json.dumps({"slots": sorted(new_ledger)}, ensure_ascii=False),
        )
    if filled:
        logger.info("system-model autofill tenant={} filled={}", tenant_id, filled)
    return filled


async def autofill_all_tenants() -> dict[int, list[str]]:
    """Startup pass: run the autofill for every tenant that owns a model."""
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            tenant_ids = (await session.exec(select(LLMModel.tenant_id).distinct())).all()
    result: dict[int, list[str]] = {}
    for tenant_id in sorted(tid for tid in tenant_ids if tid):
        try:
            result[tenant_id] = await autofill_system_models(tenant_id)
        except Exception:
            logger.exception("system-model autofill failed for tenant {}", tenant_id)
    return result

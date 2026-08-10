from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from bisheng.common.models.config import ConfigDao
from bisheng.permission.domain.application_permission_template import (
    APPLICATION_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.channel_permission_template import CHANNEL_PERMISSION_TEMPLATE
from bisheng.permission.domain.knowledge_library_permission_template import (
    KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.knowledge_space_permission_template import (
    KNOWLEDGE_SPACE_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.tool_permission_template import TOOL_PERMISSION_TEMPLATE

logger = logging.getLogger(__name__)

RELATION_MODELS_KEY = "permission_relation_models_v1"
RELATION_MODEL_BINDINGS_KEY = "permission_relation_model_bindings_v1"
_GRANT_TIER_VALUES = frozenset({"owner", "manager", "usage"})
_PERMISSION_TEMPLATES = (
    KNOWLEDGE_SPACE_PERMISSION_TEMPLATE,
    APPLICATION_PERMISSION_TEMPLATE,
    KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE,
    TOOL_PERMISSION_TEMPLATE,
    CHANNEL_PERMISSION_TEMPLATE,
)
_RELATION_MODEL_NAME_PREFIX_PAIRS = tuple(
    (template.get("title") or "", item.get("label") or "")
    for template in _PERMISSION_TEMPLATES
    for column in template.get("columns", [])
    for item in column.get("items", [])
)


def infer_grant_tier(relation: str) -> str:
    if relation == "owner":
        return "owner"
    if relation == "manager":
        return "manager"
    return "usage"


def normalize_relation_model_name(name: str | None) -> str:
    text = (name or "").strip()
    for title, label in _RELATION_MODEL_NAME_PREFIX_PAIRS:
        if title and label and text == f"{title}{label}":
            return label
    return text


def normalize_model_dict(model: dict) -> dict:
    result = dict(model)
    result["name"] = normalize_relation_model_name(result.get("name"))
    grant_tier = result.get("grant_tier")
    if grant_tier not in _GRANT_TIER_VALUES:
        result["grant_tier"] = infer_grant_tier(result.get("relation") or "")
    if not _validate_tier_relation(result["grant_tier"], result.get("relation") or ""):
        result["grant_tier"] = infer_grant_tier(result.get("relation") or "")
    if "permissions_explicit" not in result:
        permissions = result.get("permissions") or []
        result["permissions_explicit"] = False if result.get("is_system") else bool(permissions)
    return result


def _validate_tier_relation(grant_tier: str, relation: str) -> bool:
    if grant_tier == "owner":
        return relation == "owner"
    if grant_tier == "manager":
        return relation == "manager"
    if grant_tier == "usage":
        return relation in {"editor", "viewer"}
    return False


def default_relation_models() -> list[dict]:
    return [
        {
            "id": relation,
            "name": name,
            "relation": relation,
            "grant_tier": infer_grant_tier(relation),
            "permissions": [],
            "permissions_explicit": False,
            "is_system": True,
        }
        for relation, name in (
            ("owner", "所有者"),
            ("manager", "可管理"),
            ("editor", "可编辑"),
            ("viewer", "可查看"),
        )
    ]


def roster_cache_tenant_id() -> int:
    from bisheng.core.context.tenant import get_current_tenant_id

    return get_current_tenant_id() or 0


async def get_relation_models(
    *,
    build: Callable[[], Awaitable[list[dict]]] | None = None,
    tenant_id_resolver: Callable[[], int] | None = None,
) -> list[dict]:
    from bisheng.permission.domain.services import relation_roster_cache

    version = await ConfigDao.aget_config_version(RELATION_MODELS_KEY)
    return await relation_roster_cache.get_or_build(
        name="relation_models",
        tenant_id=(tenant_id_resolver or roster_cache_tenant_id)(),
        version=version,
        build=build or build_relation_models,
    )


async def build_relation_models() -> list[dict]:
    row = await ConfigDao.aget_config_by_key(RELATION_MODELS_KEY)
    if not row or not (row.value or "").strip():
        models = default_relation_models()
        await save_relation_models(models)
        return models
    try:
        models = json.loads(row.value or "[]")
    except json.JSONDecodeError:
        logger.warning("invalid permission relation-model config; restoring defaults")
        models = default_relation_models()
        await save_relation_models(models)
        return models
    if not models:
        models = default_relation_models()
        await save_relation_models(models)
        return models
    return models


async def save_relation_models(models: list[dict]) -> None:
    await ConfigDao.insert_or_update_config(
        RELATION_MODELS_KEY,
        json.dumps(models, ensure_ascii=False),
    )


async def get_bindings(
    *,
    build: Callable[[], Awaitable[list[dict]]] | None = None,
    tenant_id_resolver: Callable[[], int] | None = None,
) -> list[dict]:
    from bisheng.permission.domain.services import relation_roster_cache

    version = await ConfigDao.aget_config_version(RELATION_MODEL_BINDINGS_KEY)
    return await relation_roster_cache.get_or_build(
        name="relation_bindings",
        tenant_id=(tenant_id_resolver or roster_cache_tenant_id)(),
        version=version,
        build=build or build_bindings,
    )


async def build_bindings() -> list[dict]:
    row = await ConfigDao.aget_config_by_key(RELATION_MODEL_BINDINGS_KEY)
    if not row or not (row.value or "").strip():
        return []
    try:
        bindings = json.loads(row.value or "[]")
    except json.JSONDecodeError:
        logger.warning("invalid permission relation-model binding config; ignoring bindings")
        return []
    normalized = await migrate_legacy_knowledge_library_bindings(bindings)
    if normalized != bindings:
        await save_bindings(normalized)
    return normalized


async def save_bindings(bindings: list[dict]) -> None:
    await ConfigDao.insert_or_update_config(
        RELATION_MODEL_BINDINGS_KEY,
        json.dumps(bindings, ensure_ascii=False),
    )


def binding_key_with_scope(
    resource_type: str,
    resource_id: str,
    subject_type: str,
    subject_id: int,
    relation: str,
    include_children,
) -> str:
    normalized = bool(include_children) if subject_type == "department" else None
    scope = "-" if normalized is None else ("1" if normalized else "0")
    return f"{resource_type}:{resource_id}:{subject_type}:{subject_id}:{relation}:{scope}"


async def migrate_legacy_knowledge_library_bindings(bindings: list[dict]) -> list[dict]:
    legacy_ids = {
        int(binding.get("resource_id"))
        for binding in bindings
        if binding.get("resource_type") == "knowledge_space" and str(binding.get("resource_id", "")).isdigit()
    }
    if not legacy_ids:
        return bindings

    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum

    knowledge_rows = await KnowledgeDao.aget_list_by_ids(sorted(legacy_ids))
    knowledge_type_map = {row.id: row.type for row in knowledge_rows}
    normalized: list[dict] = []
    for binding in bindings:
        migrated = dict(binding)
        resource_id = migrated.get("resource_id")
        if migrated.get("resource_type") == "knowledge_space" and str(resource_id).isdigit():
            knowledge_type = knowledge_type_map.get(int(resource_id))
            if knowledge_type is not None and knowledge_type != KnowledgeTypeEnum.SPACE.value:
                migrated["resource_type"] = "knowledge_library"
                migrated["key"] = binding_key_with_scope(
                    "knowledge_library",
                    str(resource_id),
                    migrated.get("subject_type"),
                    int(migrated.get("subject_id")),
                    migrated.get("relation"),
                    migrated.get("include_children"),
                )
        normalized.append(migrated)
    return normalized

"""Resolve review-tag similarity threshold from tenant override and system config."""

from __future__ import annotations

import json

from bisheng.api.v1.schemas import KnowledgeSpaceConfig
from bisheng.common.models.config import ConfigDao, ConfigKeyEnum
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.workstation.domain.models.tenant_workstation_config import TenantWorkstationConfigDao

DEFAULT_REVIEW_TAG_SIMILARITY_THRESHOLD = 0.85


def _clamp_threshold(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def get_system_review_tag_similarity_threshold() -> float:
    conf = bisheng_settings.get_knowledge()
    tag_library = getattr(conf, "tag_library", None)
    if tag_library is not None:
        return _clamp_threshold(tag_library.review_tag_similarity_threshold)
    return DEFAULT_REVIEW_TAG_SIMILARITY_THRESHOLD


async def async_get_system_review_tag_similarity_threshold() -> float:
    conf = await bisheng_settings.async_get_knowledge()
    tag_library = getattr(conf, "tag_library", None)
    if tag_library is not None:
        return _clamp_threshold(tag_library.review_tag_similarity_threshold)
    return DEFAULT_REVIEW_TAG_SIMILARITY_THRESHOLD


def _parse_tenant_threshold_from_payload(payload: str | None) -> float | None:
    if not payload:
        return None
    try:
        cfg = KnowledgeSpaceConfig(**json.loads(payload))
    except Exception:
        return None
    if cfg.review_tag_similarity_threshold is None:
        return None
    return _clamp_threshold(cfg.review_tag_similarity_threshold)


def _resolve_tenant_config_payload_sync(tenant_id: int | None) -> str | None:
    if tenant_id is None:
        return None
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    if not WorkStationService._multi_tenant_enabled():
        legacy = ConfigDao.get_config(ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE)
        return legacy.value if legacy and legacy.value else None
    value, _, _, _ = TenantWorkstationConfigDao.resolve(int(tenant_id), ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE.value)
    return value


async def _resolve_tenant_config_payload_async(tenant_id: int | None) -> str | None:
    if tenant_id is None:
        return None
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    if not WorkStationService._multi_tenant_enabled():
        legacy = await ConfigDao.aget_config(ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE)
        return legacy.value if legacy and legacy.value else None
    value, _, _, _ = await TenantWorkstationConfigDao.aresolve(
        int(tenant_id),
        ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE.value,
    )
    return value


def resolve_review_tag_similarity_threshold_sync(tenant_id: int | None) -> float:
    system = get_system_review_tag_similarity_threshold()
    tenant_val = _parse_tenant_threshold_from_payload(_resolve_tenant_config_payload_sync(tenant_id))
    return tenant_val if tenant_val is not None else system


async def resolve_review_tag_similarity_threshold_async(tenant_id: int | None) -> float:
    system = await async_get_system_review_tag_similarity_threshold()
    tenant_val = _parse_tenant_threshold_from_payload(await _resolve_tenant_config_payload_async(tenant_id))
    return tenant_val if tenant_val is not None else system

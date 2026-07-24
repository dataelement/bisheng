"""Redis + in-process cache for Link B tenant tag resolver catalogs (P5)."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from bisheng.database.models.review_tags import ReviewTag
from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.knowledge.domain.schemas.link_b_tag_resolver_schema import (
    CachedPendingReviewTagRow,
    LinkBTagResolverCatalogSnapshot,
)

logger = logging.getLogger(__name__)

LINK_B_CATALOG_CACHE_TTL = 120
LINK_B_CATALOG_KEY_VERSION = "v1"
LINK_B_CATALOG_REDIS_KEY_TEMPLATE = "tenant:{tenant_id}:tag_resolver_catalog:{version}"
LINK_B_PROCESS_CACHE_MAX_ENTRIES = 64

_process_cache: OrderedDict[int, tuple[float, dict[str, Any]]] = OrderedDict()


@dataclass(frozen=True)
class LinkBCatalogCacheStats:
    source: str
    load_ms: float


class LinkBTagResolverCatalogCache:
    """Tenant-wide Link B catalog cache with Redis TTL and process LRU fallback."""

    @classmethod
    def load_sync(
        cls,
        tenant_id: int | None,
        resource_type: TagResourceTypeEnum = TagResourceTypeEnum.AI_AUTO_TAG,
    ) -> LinkBTagResolverCatalogSnapshot:
        if tenant_id is None:
            return LinkBTagResolverCatalogSnapshot(library_by_key={}, pending_catalog=[], cache_source="db")

        started = time.perf_counter()
        cached_payload = cls._get_process_cache(int(tenant_id))
        if cached_payload is not None:
            snapshot = cls._snapshot_from_payload(cached_payload, cache_source="process")
            logger.debug(
                "tag_resolver_catalog_cache_hit tenant_id={} source=process load_ms={:.2f}",
                tenant_id,
                (time.perf_counter() - started) * 1000,
            )
            return snapshot

        cached_payload = cls._get_redis_cache(int(tenant_id))
        if cached_payload is not None:
            cls._set_process_cache(int(tenant_id), cached_payload)
            snapshot = cls._snapshot_from_payload(cached_payload, cache_source="redis")
            logger.debug(
                "tag_resolver_catalog_cache_hit tenant_id={} source=redis load_ms={:.2f}",
                tenant_id,
                (time.perf_counter() - started) * 1000,
            )
            return snapshot

        payload = cls._load_payload_from_db(int(tenant_id), resource_type)
        cls._set_process_cache(int(tenant_id), payload)
        cls._set_redis_cache(int(tenant_id), payload)
        snapshot = cls._snapshot_from_payload(payload, cache_source="db")
        logger.info(
            "tag_resolver_catalog_cache_miss tenant_id={} source=db load_ms={:.2f} library_size={} pending_size={}",
            tenant_id,
            (time.perf_counter() - started) * 1000,
            len(snapshot.library_by_key),
            len(snapshot.pending_catalog),
        )
        return snapshot

    @classmethod
    def invalidate_sync(cls, tenant_id: int | None) -> None:
        if tenant_id is None:
            return
        tenant_key = int(tenant_id)
        cls._clear_process_cache(tenant_key)
        cls._delete_redis_cache(tenant_key)

    @classmethod
    async def invalidate_async(cls, tenant_id: int | None) -> None:
        cls.invalidate_sync(tenant_id)

    @staticmethod
    def _redis_key(tenant_id: int) -> str:
        return LINK_B_CATALOG_REDIS_KEY_TEMPLATE.format(
            tenant_id=tenant_id,
            version=LINK_B_CATALOG_KEY_VERSION,
        )

    @classmethod
    def _load_payload_from_db(cls, tenant_id: int, resource_type: TagResourceTypeEnum) -> dict[str, Any]:
        from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService

        library_by_key = TagLibraryTagService.build_tenant_library_by_key_sync(tenant_id)
        pending_tags = TagLibraryTagService.list_tenant_pending_review_catalog_sync(tenant_id, resource_type)
        return {
            "library_by_key": library_by_key,
            "pending_rows": [cls._serialize_pending_tag(tag) for tag in pending_tags],
            "resource_type": resource_type.value,
        }

    @staticmethod
    def _serialize_pending_tag(tag: ReviewTag) -> CachedPendingReviewTagRow:
        return CachedPendingReviewTagRow(
            id=tag.id,
            name=(tag.name or "").strip(),
            resource_type=tag.resource_type,
            business_type=tag.business_type,
            business_id=tag.business_id,
            tenant_id=tag.tenant_id,
            review_status=int(tag.review_status or 0),
            is_deleted=bool(tag.is_deleted),
        )

    @staticmethod
    def _deserialize_pending_tag(row: CachedPendingReviewTagRow | dict[str, Any]) -> ReviewTag:
        if isinstance(row, CachedPendingReviewTagRow):
            data = row
        else:
            data = CachedPendingReviewTagRow(**row)
        return ReviewTag(
            id=data.id,
            name=data.name,
            resource_type=data.resource_type,
            business_type=data.business_type,
            business_id=data.business_id,
            tenant_id=data.tenant_id,
            review_status=data.review_status,
            is_deleted=data.is_deleted,
        )

    @classmethod
    def _snapshot_from_payload(cls, payload: dict[str, Any], *, cache_source: str) -> LinkBTagResolverCatalogSnapshot:
        pending_rows = payload.get("pending_rows") or []
        return LinkBTagResolverCatalogSnapshot(
            library_by_key=dict(payload.get("library_by_key") or {}),
            pending_catalog=[cls._deserialize_pending_tag(row) for row in pending_rows],
            cache_source=cache_source,  # type: ignore[arg-type]
        )

    @classmethod
    def _get_process_cache(cls, tenant_id: int) -> dict[str, Any] | None:
        entry = _process_cache.get(tenant_id)
        if entry is None:
            return None
        expires_at, payload = entry
        if time.monotonic() >= expires_at:
            _process_cache.pop(tenant_id, None)
            return None
        _process_cache.move_to_end(tenant_id)
        return payload

    @classmethod
    def _set_process_cache(cls, tenant_id: int, payload: dict[str, Any]) -> None:
        _process_cache[tenant_id] = (time.monotonic() + LINK_B_CATALOG_CACHE_TTL, payload)
        _process_cache.move_to_end(tenant_id)
        while len(_process_cache) > LINK_B_PROCESS_CACHE_MAX_ENTRIES:
            _process_cache.popitem(last=False)

    @classmethod
    def _clear_process_cache(cls, tenant_id: int) -> None:
        _process_cache.pop(tenant_id, None)

    @classmethod
    def _get_redis_cache(cls, tenant_id: int) -> dict[str, Any] | None:
        try:
            from bisheng.core.cache.redis_manager import get_redis_client_sync

            redis = get_redis_client_sync()
            payload = redis.get(cls._redis_key(tenant_id))
            if isinstance(payload, dict):
                return payload
        except Exception as exc:
            logger.debug("tag_resolver_catalog_redis_get_failed tenant_id={} error={}", tenant_id, exc)
        return None

    @classmethod
    def _set_redis_cache(cls, tenant_id: int, payload: dict[str, Any]) -> None:
        try:
            from bisheng.core.cache.redis_manager import get_redis_client_sync

            redis = get_redis_client_sync()
            redis.set(cls._redis_key(tenant_id), payload, expiration=LINK_B_CATALOG_CACHE_TTL)
        except Exception as exc:
            logger.debug("tag_resolver_catalog_redis_set_failed tenant_id={} error={}", tenant_id, exc)

    @classmethod
    def _delete_redis_cache(cls, tenant_id: int) -> None:
        try:
            from bisheng.core.cache.redis_manager import get_redis_client_sync

            redis = get_redis_client_sync()
            redis.delete(cls._redis_key(tenant_id))
        except Exception as exc:
            logger.debug("tag_resolver_catalog_redis_delete_failed tenant_id={} error={}", tenant_id, exc)

    @classmethod
    def clear_process_cache_for_tests(cls) -> None:
        _process_cache.clear()

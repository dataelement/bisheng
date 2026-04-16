from __future__ import annotations

from typing import Dict, List, Optional

from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.core.cache.redis_manager import get_redis_client, get_redis_client_sync


class CitationRuntimeCacheService:
    """Cache citation registry items for temporary and persisted conversations."""

    CACHE_PREFIX = 'citation:runtime'
    DEFAULT_TTL = 60 * 60 * 24 * 30

    def __init__(self, ttl: int | None = None):
        self.ttl = ttl or self.DEFAULT_TTL

    @classmethod
    def _build_key(cls, citation_id: str) -> str:
        return f'{cls.CACHE_PREFIX}:{citation_id}'

    @staticmethod
    def _normalize_item(item: CitationRegistryItemSchema | Dict) -> Dict:
        if isinstance(item, CitationRegistryItemSchema):
            return item.model_dump(exclude_none=False)
        return dict(item)

    @staticmethod
    def _parse_item(item: Optional[Dict]) -> Optional[CitationRegistryItemSchema]:
        if not item:
            return None
        return CitationRegistryItemSchema.model_validate(item)

    async def save_citations(self, items: List[CitationRegistryItemSchema]) -> List[CitationRegistryItemSchema]:
        if not items:
            return []

        redis_client = await get_redis_client()
        mapping = {
            self._build_key(item.citationId): self._normalize_item(item)
            for item in items
            if item and item.citationId
        }
        if mapping:
            await redis_client.amset(mapping, expiration=self.ttl)
        return items

    def save_citations_sync(self, items: List[CitationRegistryItemSchema]) -> List[CitationRegistryItemSchema]:
        if not items:
            return []

        redis_client = get_redis_client_sync()
        mapping = {
            self._build_key(item.citationId): self._normalize_item(item)
            for item in items
            if item and item.citationId
        }
        if mapping:
            redis_client.mset(mapping, expiration=self.ttl)
        return items

    async def get_citation(self, citation_id: str) -> Optional[CitationRegistryItemSchema]:
        if not citation_id:
            return None

        redis_client = await get_redis_client()
        cached_item = await redis_client.aget(self._build_key(citation_id))
        return self._parse_item(cached_item)

    def get_citation_sync(self, citation_id: str) -> Optional[CitationRegistryItemSchema]:
        if not citation_id:
            return None

        redis_client = get_redis_client_sync()
        cached_item = redis_client.get(self._build_key(citation_id))
        return self._parse_item(cached_item)

    async def get_citations_by_ids(self, citation_ids: List[str]) -> List[CitationRegistryItemSchema]:
        if not citation_ids:
            return []

        redis_client = await get_redis_client()
        keys = [self._build_key(citation_id) for citation_id in citation_ids if citation_id]
        if not keys:
            return []

        values = await redis_client.amget(keys)
        if not values:
            return []

        item_by_id: Dict[str, CitationRegistryItemSchema] = {}
        for value in values:
            item = self._parse_item(value)
            if item and item.citationId:
                item_by_id[item.citationId] = item
        return [item_by_id[citation_id] for citation_id in citation_ids if citation_id in item_by_id]

    def get_citations_by_ids_sync(self, citation_ids: List[str]) -> List[CitationRegistryItemSchema]:
        if not citation_ids:
            return []

        redis_client = get_redis_client_sync()
        keys = [self._build_key(citation_id) for citation_id in citation_ids if citation_id]
        if not keys:
            return []

        values = redis_client.mget(keys)
        if not values:
            return []

        item_by_id: Dict[str, CitationRegistryItemSchema] = {}
        for value in values:
            item = self._parse_item(value)
            if item and item.citationId:
                item_by_id[item.citationId] = item
        return [item_by_id[citation_id] for citation_id in citation_ids if citation_id in item_by_id]

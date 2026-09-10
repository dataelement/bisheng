"""复用 Redis 保存短期分页快照。避免去重 ID 随页数撑大 URL。"""

import re
from uuid import uuid4

from bisheng.core.cache.redis_conn import RedisClient
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.storage.tenant_storage import get_redis_key_prefix
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_cursor_repository import (
    KnowledgeFulltextCursorRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_search_schema import KnowledgeFulltextSearchSession


class KnowledgeFulltextCursorRepositoryImpl(KnowledgeFulltextCursorRepository):
    # 与全文 PIT 的 2 分钟有效期一致。每页独立保存以避免重试污染上一页状态。
    TTL_SECONDS = 120

    def __init__(self, redis_client: RedisClient | None = None):
        self.redis = redis_client

    async def _redis(self) -> RedisClient:
        if self.redis is None:
            self.redis = await get_redis_client()
        return self.redis

    @staticmethod
    def _key(token: str) -> str:
        tenant_id = get_current_tenant_id() or DEFAULT_TENANT_ID
        return f"{get_redis_key_prefix(tenant_id)}portal:fulltext:document-cursor:v1:{token}"

    async def save(self, state: KnowledgeFulltextSearchSession) -> str:
        token = uuid4().hex
        redis = await self._redis()
        await redis.async_connection.set(self._key(token), state.model_dump_json(), ex=self.TTL_SECONDS)
        return token

    async def load(self, token: str) -> KnowledgeFulltextSearchSession | None:
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            return None
        redis = await self._redis()
        raw = await redis.async_connection.get(self._key(token))
        return KnowledgeFulltextSearchSession.model_validate_json(raw) if raw is not None else None

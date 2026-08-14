"""门户全文高级检索的 readiness、PIT 与游标编排。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from elastic_transport import TransportError
from elasticsearch import ApiError, NotFoundError

from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
from bisheng.common.errcode.knowledge import (
    KnowledgeFulltextIndexIncompatibleError,
    KnowledgeFulltextSearchUnavailableError,
    KnowledgeInvalidCursorError,
)
from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_index_repository_impl import (
    KnowledgeFulltextIndexConfigurationError,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_index_repository import (
    KnowledgeFulltextIndexRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_search_repository import (
    KnowledgeFulltextSearchRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_search_schema import (
    KnowledgeFulltextAdvancedSearchQuery,
    KnowledgeFulltextSearchBatch,
    KnowledgeFulltextSearchSession,
    KnowledgeFulltextSearchSort,
    KnowledgeFulltextUploaderSupport,
)

logger = logging.getLogger(__name__)


class KnowledgeFulltextReadinessGuard:
    """进程内短缓存只读校验，避免每个请求重复读取完整 Mapping。"""  # noqa: RUF002

    def __init__(
        self,
        index_repository: KnowledgeFulltextIndexRepository,
        *,
        ttl_seconds: float = constants.KNOWLEDGE_FULLTEXT_SEARCH_READINESS_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.index_repository = index_repository
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._valid_until = 0.0
        self._lock = asyncio.Lock()

    async def ensure_ready(self) -> None:
        now = self.clock()
        if now < self._valid_until:
            return
        async with self._lock:
            now = self.clock()
            if now < self._valid_until:
                return
            try:
                await self.index_repository.validate_read_index()
            except KnowledgeFulltextIndexConfigurationError as exc:
                raise KnowledgeFulltextIndexIncompatibleError(exception=exc) from exc
            except (ApiError, TransportError) as exc:
                raise KnowledgeFulltextSearchUnavailableError(exception=exc) from exc
            self._valid_until = self.clock() + self.ttl_seconds


class KnowledgeFulltextSearchService:
    def __init__(
        self,
        *,
        repository: KnowledgeFulltextSearchRepository,
        readiness_guard: KnowledgeFulltextReadinessGuard,
    ):
        self.repository = repository
        self.readiness_guard = readiness_guard

    @staticmethod
    def context_signature(query: KnowledgeFulltextAdvancedSearchQuery) -> str:
        payload = query.model_dump(mode="json")
        raw = json.dumps(
            {"schema": "portal-fulltext-advanced-v1", "query": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def expected_sort_values(query: KnowledgeFulltextAdvancedSearchQuery) -> int:
        if query.sort == KnowledgeFulltextSearchSort.RELEVANCE:
            return 4 if query.has_keywords else 3
        if query.sort in {
            KnowledgeFulltextSearchSort.UPDATED_AT_DESC,
            KnowledgeFulltextSearchSort.UPDATED_AT_ASC,
        }:
            return 3
        return 5 if query.has_keywords else 4

    async def begin(
        self,
        query: KnowledgeFulltextAdvancedSearchQuery,
        *,
        cursor: str | None,
    ) -> KnowledgeFulltextSearchSession:
        await self.readiness_guard.ensure_ready()
        context = self.context_signature(query)
        expected_sort_values = self.expected_sort_values(query)
        if cursor:
            try:
                values = decode_cursor(
                    cursor,
                    expected_key_len=expected_sort_values + 1,
                    expected_context=context,
                )
            except CursorDecodeError as exc:
                raise KnowledgeInvalidCursorError(exception=exc) from exc
            if not values or not isinstance(values[0], str) or not values[0]:
                raise KnowledgeInvalidCursorError(msg="Invalid pagination cursor")
            return KnowledgeFulltextSearchSession(
                pit_id=values[0],
                search_after=list(values[1:]),
                context_signature=context,
                expected_sort_values=expected_sort_values,
            )

        try:
            pit_id = await self.repository.open_pit()
        except KnowledgeFulltextIndexConfigurationError as exc:
            raise KnowledgeFulltextIndexIncompatibleError(exception=exc) from exc
        except (ApiError, TransportError) as exc:
            raise KnowledgeFulltextSearchUnavailableError(exception=exc) from exc
        return KnowledgeFulltextSearchSession(
            pit_id=pit_id,
            context_signature=context,
            expected_sort_values=expected_sort_values,
        )

    async def fetch(
        self,
        query: KnowledgeFulltextAdvancedSearchQuery,
        session: KnowledgeFulltextSearchSession,
        *,
        size: int,
    ) -> KnowledgeFulltextSearchBatch:
        try:
            batch = await self.repository.search(
                query,
                pit_id=session.pit_id,
                search_after=session.search_after,
                size=size,
            )
        except NotFoundError as exc:
            raise KnowledgeInvalidCursorError(exception=exc) from exc
        except (ApiError, TransportError) as exc:
            raise KnowledgeFulltextSearchUnavailableError(exception=exc) from exc
        session.pit_id = batch.pit_id
        if batch.hits:
            last_sort = batch.hits[-1].sort_values
            if len(last_sort) != session.expected_sort_values:
                raise KnowledgeFulltextIndexIncompatibleError(
                    msg="全文检索排序契约不兼容，请联系管理员"  # noqa: RUF001
                )
            session.search_after = list(last_sort)
        return batch

    @staticmethod
    def encode_next_cursor(
        session: KnowledgeFulltextSearchSession,
        *,
        sort_values: list[Any],
    ) -> str:
        if len(sort_values) != session.expected_sort_values:
            raise KnowledgeFulltextIndexIncompatibleError(
                msg="全文检索排序契约不兼容，请联系管理员"  # noqa: RUF001
            )
        return encode_cursor(
            (session.pit_id, *sort_values),
            context=session.context_signature,
        )

    async def close(self, session: KnowledgeFulltextSearchSession) -> None:
        try:
            await self.repository.close_pit(session.pit_id)
        except (ApiError, TransportError) as exc:
            # PIT 有限 TTL 会最终回收，关闭失败不改变已完成查询的业务响应。  # noqa: RUF003
            logger.warning("close fulltext search PIT failed: error=%s", type(exc).__name__)

    async def find_uploader_supports(
        self,
        *,
        space_ids: list[int],
        uploader_ids: list[int],
        per_uploader_limit: int,
    ) -> list[KnowledgeFulltextUploaderSupport]:
        await self.readiness_guard.ensure_ready()
        try:
            return await self.repository.find_uploader_supports(
                space_ids=space_ids,
                uploader_ids=uploader_ids,
                per_uploader_limit=per_uploader_limit,
            )
        except KnowledgeFulltextIndexConfigurationError as exc:
            raise KnowledgeFulltextIndexIncompatibleError(exception=exc) from exc
        except (ApiError, TransportError) as exc:
            raise KnowledgeFulltextSearchUnavailableError(exception=exc) from exc

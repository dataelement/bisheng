"""Production content search used to derive per-user recommendation interests."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_repository_impl import (
    PortalRecommendationRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_telemetry_repository import (
    PortalInterestHit,
    PortalSearchQuerySignal,
)
from bisheng.knowledge.domain.services.portal_recommendation_behavior_service import normalize_search_query

ProjectionLoader = Callable[[], Awaitable[Sequence[Any]] | Sequence[Any]]
SpaceLoader = Callable[[Sequence[int]], Awaitable[Sequence[Any]] | Sequence[Any]]
EsSearcher = Callable[[Sequence[str], dict], Awaitable[dict] | dict]


class PortalRecommendationContentSearcher:
    """Search only current-tenant, projection-eligible files across space ES indexes."""

    MAX_PROJECTION_CANDIDATES = 10_000

    def __init__(
        self,
        *,
        projection_loader: ProjectionLoader | None = None,
        space_loader: SpaceLoader | None = None,
        es_searcher: EsSearcher | None = None,
    ):
        self._projection_loader = projection_loader
        self._space_loader = space_loader
        self._es_searcher = es_searcher

    async def _load_projections(self) -> Sequence[Any]:
        if self._projection_loader is not None:
            result = self._projection_loader()
            return await result if inspect.isawaitable(result) else result
        async with get_async_db_session() as session:
            return await PortalRecommendationRepositoryImpl(session).list_latest_recommendable(
                space_ids=None,
                limit=self.MAX_PROJECTION_CANDIDATES,
            )

    async def _load_spaces(self, space_ids: Sequence[int]) -> Sequence[Any]:
        if self._space_loader is not None:
            result = self._space_loader(space_ids)
            return await result if inspect.isawaitable(result) else result
        return await KnowledgeDao.aget_list_by_ids(list(space_ids))

    async def _search_es(self, index_names: Sequence[str], body: dict, first_space: Any) -> dict:
        if self._es_searcher is not None:
            result = self._es_searcher(index_names, body)
            return await result if inspect.isawaitable(result) else result
        vector_store = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=first_space)
        return await vector_store.client.search(index=list(index_names), body=body)

    async def search(
        self,
        tenant_id: int,
        queries: Sequence[PortalSearchQuerySignal],
        limit: int,
    ) -> list[PortalInterestHit]:
        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != int(tenant_id):
            raise PermissionError("interest search tenant does not match current context")
        normalized_queries = [normalize_search_query(signal.query) for signal in queries]
        normalized_queries = list(dict.fromkeys(query for query in normalized_queries if query))[:20]
        if not normalized_queries:
            return []

        projections = list(await self._load_projections())
        file_to_space = {
            int(record.file_id): int(record.space_id)
            for record in projections
            if bool(record.recommendable)
        }
        if not file_to_space:
            return []
        spaces = list(await self._load_spaces(sorted(set(file_to_space.values()))))
        spaces = [space for space in spaces if getattr(space, "index_name", None)]
        if not spaces:
            return []

        should: list[dict] = []
        fields = (
            ("title", "metadata.document_name"),
            ("tag", "metadata.tags"),
            ("tag", "metadata.user_metadata.tags"),
            ("summary", "metadata.abstract"),
        )
        for query_index, query in enumerate(normalized_queries):
            for field_name, es_field in fields:
                should.append(
                    {
                        "match": {
                            es_field: {
                                "query": query,
                                "_name": f"q{query_index}:{field_name}",
                            }
                        }
                    }
                )
        body = {
            "query": {
                "bool": {
                    "filter": [{"terms": {"metadata.document_id": sorted(file_to_space)}}],
                    "should": should,
                    "minimum_should_match": 1,
                }
            },
            "collapse": {"field": "metadata.document_id"},
            "size": min(max(int(limit), 1), 50),
            "_source": ["metadata.document_id"],
        }
        response = await self._search_es(
            [str(space.index_name) for space in spaces],
            body,
            spaces[0],
        )
        hits: list[PortalInterestHit] = []
        for hit in (response.get("hits") or {}).get("hits", []):
            metadata = (hit.get("_source") or {}).get("metadata") or {}
            raw_file_id = metadata.get("document_id")
            if not str(raw_file_id or "").isdigit():
                continue
            file_id = int(raw_file_id)
            space_id = file_to_space.get(file_id)
            if space_id is None:
                continue
            scores: dict[str, list[float]] = {}
            for matched_name in hit.get("matched_queries") or []:
                try:
                    query_token, field_name = str(matched_name).split(":", 1)
                    query_index = int(query_token.removeprefix("q"))
                    query = normalized_queries[query_index]
                except (IndexError, TypeError, ValueError):
                    continue
                values = scores.setdefault(query, [0.0, 0.0, 0.0])
                if field_name == "title":
                    values[0] = 1.0
                elif field_name == "tag":
                    values[1] = 1.0
                elif field_name == "summary":
                    values[2] = 1.0
            if scores:
                hits.append(
                    PortalInterestHit(
                        space_id=space_id,
                        file_id=file_id,
                        query_field_scores={key: tuple(value) for key, value in scores.items()},
                    )
                )
        return hits[: min(max(int(limit), 1), 50)]

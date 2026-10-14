"""基于共享存储生成租户内的用户兴趣推荐候选。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.contracts.retrieval_scope import EntryRef
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_repository_impl import (
    PortalRecommendationRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_telemetry_repository import (
    PortalInterestHit,
    PortalSearchQuerySignal,
)
from bisheng.knowledge.domain.services.knowledge_retrieval_scope_resolver import (
    RetrievalScopeResolverSettings,
    SqlKnowledgeRetrievalScopeResolver,
)
from bisheng.knowledge.domain.services.portal_recommendation_behavior_service import normalize_search_query
from bisheng.knowledge.rag.shared_space_storage import abuild_shared_space_reader_for_tenant

ProjectionLoader = Callable[[], Awaitable[Sequence[Any]] | Sequence[Any]]


class PortalRecommendationContentSearcher:
    """仅检索有效推荐入口; 用户展示权限仍由推荐接口校验。"""

    MAX_PROJECTION_CANDIDATES = 10_000
    CANDIDATE_BATCH_SIZE = 200

    def __init__(self, *, projection_loader: ProjectionLoader | None = None) -> None:
        self._projection_loader = projection_loader

    async def _load_projections(self) -> Sequence[Any]:
        if self._projection_loader is not None:
            result = self._projection_loader()
            return await result if inspect.isawaitable(result) else result
        async with get_async_db_session() as session:
            return await PortalRecommendationRepositoryImpl(session).list_latest_recommendable(
                space_ids=None,
                limit=self.MAX_PROJECTION_CANDIDATES,
            )

    @staticmethod
    def _field_scores(names: Sequence[str], queries: Sequence[str]) -> dict[str, tuple[float, float, float]]:
        scores = {}
        field_indexes = {"title": 0, "tag": 1, "summary": 2}
        for name in names:
            try:
                token, field = str(name).split(":", 1)
                if not token.startswith("q"):
                    continue
                index = int(token[1:])
                if not 0 <= index < len(queries) or field not in field_indexes:
                    continue
                values = scores.setdefault(queries[index], [0.0, 0.0, 0.0])
                values[field_indexes[field]] = 1.0
            except (TypeError, ValueError):
                continue
        return {query: tuple(values) for query, values in scores.items()}

    async def search(
        self,
        tenant_id: int,
        queries: Sequence[PortalSearchQuerySignal],
        limit: int,
    ) -> list[PortalInterestHit]:
        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != int(tenant_id):
            raise PermissionError("interest search tenant does not match current context")
        normalized = list(dict.fromkeys(normalize_search_query(signal.query) for signal in queries))
        normalized = [query for query in normalized if query][:20]
        if not normalized:
            return []
        projections = list(await self._load_projections())[: self.MAX_PROJECTION_CANDIDATES]
        eligible = {
            int(record.file_id): int(record.space_id)
            for record in projections
            if record.recommendable and int(record.tenant_id or 0) == int(tenant_id)
        }
        if not eligible:
            return []
        fields = (
            ("title", "metadata.document_name"),
            ("tag", "metadata.tags"),
            ("tag", "metadata.user_metadata.tags"),
            ("summary", "metadata.abstract"),
        )
        matches = [
            (f"q{index}:{name}", field, query) for index, query in enumerate(normalized) for name, field in fields
        ]
        reader = await abuild_shared_space_reader_for_tenant(tenant_id)
        result_limit = min(max(int(limit), 1), 50)
        by_document: dict[int, tuple[tuple[float, int, int], PortalInterestHit]] = {}
        file_ids = sorted(eligible)
        # 每批独立读取数据库当前状态, 限制 SQL 参数和共享身份过滤长度。
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                files = KnowledgeFileRepositoryImpl(session)
                documents = KnowledgeDocumentRepositoryImpl(session)
                versions = KnowledgeDocumentVersionRepositoryImpl(session)
                for offset in range(0, len(file_ids), self.CANDIDATE_BATCH_SIZE):
                    batch_ids = file_ids[offset : offset + self.CANDIDATE_BATCH_SIZE]
                    entries = await files.find_by_ids(batch_ids)
                    candidates = [
                        entry
                        for entry in entries
                        if int(entry.id) in batch_ids
                        and (
                            SqlKnowledgeRetrievalScopeResolver._is_resolvable_explicit_entry(
                                entry,
                                tenant_id=int(tenant_id),
                                expected_space_id=eligible[int(entry.id)],
                            )
                            and entry.file_type == FileType.FILE.value
                            and entry.status == KnowledgeFileStatus.SUCCESS.value
                            and entry.deleted_at is None
                            and entry.reference_document_id
                        )
                    ]
                    if not candidates:
                        continue
                    allowed = {(int(entry.knowledge_id), int(entry.id)) for entry in candidates}
                    spaces = sorted({space for space, _entry in allowed})

                    async def space_checker(
                        _tenant: int,
                        _user: str,
                        space: int,
                        spaces: frozenset[int] = frozenset(spaces),
                    ) -> bool:
                        return int(_tenant) == int(tenant_id) and int(space) in spaces

                    async def entry_checker(
                        _tenant: int,
                        _user: str,
                        space: int,
                        file_id: int,
                        allowed: frozenset[tuple[int, int]] = frozenset(allowed),
                    ) -> bool:
                        # 推荐资格仅用于内部候选范围, 不能替代最终用户权限。
                        return int(_tenant) == int(tenant_id) and (int(space), int(file_id)) in allowed

                    resolver = SqlKnowledgeRetrievalScopeResolver(
                        file_repository=files,
                        document_repository=documents,
                        version_repository=versions,
                        space_read_checker=space_checker,
                        entry_view_checker=entry_checker,
                        settings_provider=lambda: RetrievalScopeResolverSettings(
                            routing_version=reader.expected_routing_version,
                        ),
                    )
                    scope = await resolver.resolve_request(
                        user_id="portal-recommendation-candidates",
                        tenant_id=tenant_id,
                        space_ids=spaces,
                        entry_refs=[
                            EntryRef(space_id=entry.knowledge_id, entry_file_id=entry.id) for entry in candidates
                        ],
                    )
                    constraints = await resolver.resolve_current_generation_constraints(
                        scope,
                        sorted({int(entry.reference_document_id) for entry in candidates}),
                    )
                    if not constraints:
                        continue
                    filter_ = resolver.build_backend_filter(
                        scope,
                        canonical_document_ids=[item.canonical_document_id for item in constraints],
                        canonical_version_ids=[item.canonical_version_id for item in constraints],
                        generation_constraints=constraints,
                    )
                    raw_hits = await reader.search_metadata(filter_, matches=matches, limit=result_limit)
                    mapped = await resolver.map_and_authorize_hits(
                        scope,
                        [item.chunk for item in raw_hits],
                        strict_explicit=True,
                    )
                    names = {
                        (int(item.chunk.canonical_document_id), int(item.chunk.chunk_index)): item.matched_queries
                        for item in raw_hits
                    }
                    for hit in mapped:
                        scores = self._field_scores(
                            names[(int(hit.canonical_document_id), hit.chunk_index)], normalized
                        )
                        if not scores:
                            continue
                        candidate = PortalInterestHit(
                            space_id=int(hit.space_id),
                            file_id=int(hit.entry_file_id),
                            query_field_scores=scores,
                        )
                        key = int(hit.canonical_document_id)
                        previous = by_document.get(key)
                        rank = (-hit.score, candidate.space_id, candidate.file_id)
                        if previous is None or rank < previous[0]:
                            by_document[key] = (rank, candidate)
        return [candidate for _rank, candidate in sorted(by_document.values(), key=lambda item: item[0])][:result_limit]

import asyncio
import json
from collections import defaultdict

from bisheng.citation.domain.repositories.interfaces.message_citation_repository import MessageCitationRepository
from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationPayloadSchema,
    WebCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.citation.domain.services.citation_runtime_cache_service import CitationRuntimeCacheService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService


class CitationResolveService:
    """Resolve persisted citation items into a unified response payload.

    F029 (knowledge QA permission filter) moved the access check from the
    legacy RBAC ``AccessType.KNOWLEDGE`` space-level probe (an arch-guard
    RULE-8 violation) to the ReBAC + Fine-grained ``view_file`` per-file
    visibility primitive. The new flow filters out RAG citations the user
    cannot see before enrichment; anonymous callers (share-link / public
    flows) keep the original "always enrich" behaviour. See
    features/v2.6.0/029-knowledge-qa-permission-filter/spec.md §7.3.
    """

    def __init__(
        self,
        repository: MessageCitationRepository,
        runtime_cache_service: CitationRuntimeCacheService | None = None,
    ):
        self.registry_service = CitationRegistryService(repository)
        self.runtime_cache_service = runtime_cache_service or CitationRuntimeCacheService()

    # ------------------------------------------------------------------
    # F029 — view_file filter
    # ------------------------------------------------------------------

    async def _resolve_rag_space_pairs(
        self,
        items: list[CitationRegistryItemSchema],
    ) -> dict[int, set[int]]:
        """Group RAG citations by knowledge_id and collect their documentIds.

        When the persisted payload is missing ``knowledgeId`` it is looked up
        via ``KnowledgeFileDao.query_by_id_sync`` (matches the enrichment
        path so the filter sees the same space the URLs would be issued
        for). RAG citations whose file_id is unresolvable are returned
        keyed under ``space_id=0`` so they can later be dropped.
        """
        grouped: dict[int, set[int]] = defaultdict(set)
        for item in items:
            if item.type != CitationType.RAG:
                continue
            payload = RagCitationPayloadSchema.model_validate(item.sourcePayload)
            file_id = payload.documentId
            if file_id is None:
                continue
            space_id = payload.knowledgeId
            if space_id is None:
                file_info = await asyncio.to_thread(KnowledgeFileDao.query_by_id_sync, file_id)
                if file_info is None:
                    grouped[0].add(int(file_id))
                    continue
                space_id = file_info.knowledge_id
            grouped[int(space_id)].add(int(file_id))
        return grouped

    async def _filter_visible_rag_items(
        self,
        items: list[CitationRegistryItemSchema],
        login_user: UserPayload | None,
    ) -> list[CitationRegistryItemSchema]:
        """Drop RAG citations whose documentId fails ``view_file``.

        Anonymous callers (``login_user is None``) bypass the filter — this
        preserves the legacy share-link behaviour spec'd in AC-20. Web
        citations always pass through (AC-19). Admin users always pass
        through (handled by the underlying service short-circuit).
        """
        if login_user is None or not items:
            return list(items)

        grouped = await self._resolve_rag_space_pairs(items)
        if not grouped:
            # No RAG items needing a filter — return as-is.
            return list(items)

        from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
            KnowledgeFileVisibilityService,
        )

        visibility = KnowledgeFileVisibilityService(request=None, login_user=login_user)

        permitted: dict[int, set[int]] = {}
        for space_id, file_ids in grouped.items():
            if space_id == 0 or not file_ids:
                permitted[space_id] = set()
                continue
            permitted[space_id] = await visibility.post_filter_visible_files(space_id, file_ids)

        filtered: list[CitationRegistryItemSchema] = []
        for item in items:
            if item.type != CitationType.RAG:
                filtered.append(item)
                continue
            payload = RagCitationPayloadSchema.model_validate(item.sourcePayload)
            file_id = payload.documentId
            if file_id is None:
                continue
            space_id = payload.knowledgeId
            if space_id is None:
                file_info = await asyncio.to_thread(KnowledgeFileDao.query_by_id_sync, file_id)
                space_id = int(file_info.knowledge_id) if file_info is not None else 0
            if int(file_id) in permitted.get(int(space_id), set()):
                filtered.append(item)
        return filtered

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    @staticmethod
    async def _resolve_bbox(file_id: int | None, bbox: str | None) -> str | None:
        """Prefer persisted bbox and gracefully fall back to file bbox metadata."""
        if bbox:
            return bbox
        if file_id is None:
            return None

        file_bbox = await asyncio.to_thread(KnowledgeService.get_file_bbox, None, None, file_id)
        if file_bbox is None:
            return None
        return json.dumps(file_bbox, ensure_ascii=False)

    async def _enrich_rag_item(
        self,
        item: CitationRegistryItemSchema,
        login_user: UserPayload | None,
    ) -> CitationRegistryItemSchema:
        """Enrich a RAG citation with file share URLs and best-effort bbox details.

        F029: by the time enrichment runs the upstream ``_filter_visible_rag_items``
        has already removed citations the user cannot see; URLs / bbox are
        therefore always populated for surviving items (anonymous callers
        too, preserving the share-link behaviour).
        """
        del login_user  # filter step already enforced visibility
        payload = RagCitationPayloadSchema.model_validate(item.sourcePayload)
        file_id = payload.documentId

        if file_id is not None:
            # The file metadata lookups below hit tenant-scoped tables. An
            # anonymous share-page resolve carries NO tenant context, so without a
            # bypass these raise "Missing tenant context" (NoTenantContextError) and
            # every RAG citation comes back empty even though its row exists.
            # Bypassing is safe here: the citation is already pinned by its unique
            # id, and visibility was enforced upstream (logged-in) / granted by the
            # share link (anonymous). asyncio.to_thread copies the context, so the
            # bypass flag reaches the sync DAO calls.
            from bisheng.core.context.tenant import bypass_tenant_filter

            with bypass_tenant_filter():
                file_info = await asyncio.to_thread(KnowledgeFileDao.query_by_id_sync, file_id)
                if file_info is not None:
                    payload.documentId = payload.documentId or file_info.id
                    payload.knowledgeId = payload.knowledgeId or file_info.knowledge_id
                    payload.documentName = payload.documentName or file_info.file_name

                    download_url, preview_url = await asyncio.to_thread(
                        KnowledgeService.get_file_share_url,
                        None,
                        file_info,
                    )
                    payload.downloadUrl = download_url or payload.downloadUrl
                    payload.previewUrl = preview_url or payload.previewUrl
                    if payload.items:
                        first_item = payload.items[0]
                        resolved_bbox = await self._resolve_bbox(file_info.id, first_item.bbox)
                        payload.items[0] = first_item.model_copy(update={"bbox": resolved_bbox})

        return item.model_copy(update={"sourcePayload": payload})

    @staticmethod
    def _enrich_web_item(item: CitationRegistryItemSchema) -> CitationRegistryItemSchema:
        """Normalize persisted web payload before returning it."""
        payload = WebCitationPayloadSchema.model_validate(item.sourcePayload)
        payload.url = CitationRegistryService.normalize_url(payload.url)
        return item.model_copy(update={"sourcePayload": payload})

    async def _enrich_item(
        self,
        item: CitationRegistryItemSchema,
        login_user: UserPayload | None,
    ) -> CitationRegistryItemSchema:
        """Enrich a citation item based on its type."""
        if item.type == CitationType.RAG:
            return await self._enrich_rag_item(item, login_user)
        return self._enrich_web_item(item)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve_citation(
        self,
        citation_id: str,
        login_user: UserPayload | None = None,
    ) -> CitationRegistryItemSchema:
        """Resolve one citation item by business ID.

        Raises ``NotFoundError`` either when the citation does not exist or
        when the logged-in user lacks ``view_file`` for the underlying RAG
        document (AC-18). Anonymous callers and web citations always
        return the enriched payload.
        """
        item = await self.runtime_cache_service.get_citation(citation_id)
        if item is None:
            item = await self.registry_service.get_citation(citation_id)
        if item is None:
            raise NotFoundError()
        if item.type == CitationType.RAG and login_user is not None:
            visible = await self._filter_visible_rag_items([item], login_user)
            if not visible:
                raise NotFoundError()
            item = visible[0]
        return await self._enrich_item(item, login_user)

    async def resolve_citations(
        self,
        citation_ids: list[str],
        login_user: UserPayload | None = None,
    ) -> list[CitationRegistryItemSchema]:
        """Resolve multiple citation items in one round trip.

        For logged-in callers the items are first filtered through
        ``_filter_visible_rag_items`` so any citation pointing at a file
        the user cannot ``view_file`` is dropped entirely (AC-16 / AC-17)
        before enrichment runs.
        """
        cached_items = await self.runtime_cache_service.get_citations_by_ids(citation_ids)
        cached_by_id: dict[str, CitationRegistryItemSchema] = {item.citationId: item for item in cached_items}
        missing_ids = [citation_id for citation_id in citation_ids if citation_id not in cached_by_id]
        items = cached_items
        if missing_ids:
            items.extend(await self.registry_service.list_citations_by_ids(missing_ids))

        items = await self._filter_visible_rag_items(items, login_user)

        enriched_items = await asyncio.gather(*(self._enrich_item(item, login_user) for item in items))
        item_map: dict[str, CitationRegistryItemSchema] = {item.citationId: item for item in enriched_items}
        return [item_map[citation_id] for citation_id in citation_ids if citation_id in item_map]

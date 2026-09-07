import asyncio
import json
from collections import defaultdict

from bisheng.citation.domain.repositories.interfaces.message_citation_repository import MessageCitationRepository
from bisheng.citation.domain.schemas.citation_schema import (
    ArticleCitationPayloadSchema,
    CitationRegistryItemSchema,
    CitationType,
    CitationUnresolvedReason,
    RagCitationPayloadSchema,
    ResolveCitationResponse,
    UnresolvedCitationSchema,
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
    legacy RBAC space-level probe (an arch-guard
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

    async def _permitted_file_ids(
        self,
        items: list[CitationRegistryItemSchema],
        login_user: UserPayload | None,
    ) -> set[int] | None:
        """Return the flat set of RAG documentIds the user holds ``view_file`` on.

        Returns ``None`` for anonymous callers (``login_user is None``) — meaning
        "no gating" (legacy share-link behaviour, AC-20). Admin short-circuits to
        the full input set inside ``post_filter_visible_files``. document_id is
        globally unique, so a flat set is sufficient across spaces.
        """
        if login_user is None or not items:
            return None
        grouped = await self._resolve_rag_space_pairs(items)
        if not grouped:
            return set()

        from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
            KnowledgeFileVisibilityService,
        )

        visibility = KnowledgeFileVisibilityService(request=None, login_user=login_user)
        allowed: set[int] = set()
        for space_id, file_ids in grouped.items():
            if space_id == 0 or not file_ids:
                continue
            allowed |= await visibility.post_filter_visible_files(space_id, file_ids)
        return allowed

    @staticmethod
    def _rag_url_allowed(item: CitationRegistryItemSchema, permitted: set[int] | None) -> bool:
        """Whether the viewer may receive full-file preview/download URLs (view_file)."""
        if item.type != CitationType.RAG or permitted is None:  # web / anonymous → allowed
            return True
        payload = RagCitationPayloadSchema.model_validate(item.sourcePayload)
        return payload.documentId is not None and int(payload.documentId) in permitted

    def _apply_tier_filter(
        self,
        items: list[CitationRegistryItemSchema],
        permitted: set[int] | None,
    ) -> list[CitationRegistryItemSchema]:
        """F041 tiered gate. Web citations always pass. ``per_user`` RAG citations
        are dropped when the file fails ``view_file``. ``shared`` RAG citations
        (toggle-OFF knowledge-space sources) are kept regardless — their full-file
        URLs are gated later in enrichment. ``permitted is None`` (anonymous) keeps
        everything (AC-19/20/21).
        """
        if permitted is None:
            return list(items)
        filtered: list[CitationRegistryItemSchema] = []
        for item in items:
            if item.type != CitationType.RAG:
                filtered.append(item)
                continue
            if item.accessScope == "shared" or self._rag_url_allowed(item, permitted):
                filtered.append(item)
        return filtered

    async def _filter_visible_rag_items(
        self,
        items: list[CitationRegistryItemSchema],
        login_user: UserPayload | None,
    ) -> list[CitationRegistryItemSchema]:
        """Resolve view_file permission and apply the tiered filter in one step.

        Kept as the single-call entry (used by ``resolve_citation`` and existing
        F029 tests); ``resolve_citations`` computes ``permitted`` once and reuses it
        for both filtering and enrichment URL gating.
        """
        permitted = await self._permitted_file_ids(items, login_user)
        return self._apply_tier_filter(items, permitted)

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
        url_allowed: bool = True,
    ) -> CitationRegistryItemSchema:
        """Enrich a RAG citation with source metadata and (when permitted) file URLs.

        F029: ``per_user`` survivors are always ``url_allowed`` (the filter dropped
        the rest). F041: a ``shared`` citation (toggle-OFF space source) can survive
        the filter while ``url_allowed`` is False — then we fill source metadata
        (documentName / knowledgeId) but withhold the full-file preview/download URLs
        and bbox (AC-21).
        """
        del login_user  # filter step already enforced view_file for per_user
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

                    if url_allowed:
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
    def _is_anonymous_readable(item: CitationRegistryItemSchema) -> bool:
        """Whether a caller with no logged-in user may receive this source.

        F054 overrides F029 AC-20, which deliberately let anonymous callers
        through unfiltered so share links kept working — that is exactly the
        hole being closed: handing out a share link also handed out the
        knowledge files behind it, signed preview URLs included. Knowledge and
        article sources are refused outright, ``shared`` tier included: that
        tier decides *which logged-in user* may open a file, so with no logged-in
        user there is nobody for it to answer for. Web citations stay readable —
        they are public URLs holding no tenant data, and blacking them out would
        strip share-page badges for no security gain.
        """
        return item.type == CitationType.WEB

    @staticmethod
    def _enrich_article_item(item: CitationRegistryItemSchema) -> CitationRegistryItemSchema:
        """Validate a persisted article payload before returning it.

        Nothing to sign or look up: the article's own locator and URL are stored
        on the citation, and channel-side visibility was enforced when the answer
        was produced.
        """
        payload = ArticleCitationPayloadSchema.model_validate(item.sourcePayload)
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
        url_allowed: bool = True,
    ) -> CitationRegistryItemSchema:
        """Enrich a citation item based on its type."""
        if item.type == CitationType.RAG:
            return await self._enrich_rag_item(item, login_user, url_allowed=url_allowed)
        if item.type == CitationType.ARTICLE:
            return self._enrich_article_item(item)
        if item.type == CitationType.WEB:
            return self._enrich_web_item(item)
        # Unknown type (a newer writer, an older reader): hand it back untouched
        # rather than guessing at a payload shape and raising.
        return item

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
            # Rule 1 before rule 2: for a caller with no logged-in user an
            # unknown id must look exactly like a refused one, or the reason
            # itself becomes a way to probe which ids ever existed.
            raise NotFoundError(
                reason=(
                    CitationUnresolvedReason.FORBIDDEN.value
                    if login_user is None
                    else CitationUnresolvedReason.EXPIRED.value
                )
            )
        if login_user is None and not self._is_anonymous_readable(item):
            # F054 overrides F029 AC-20: knowledge and article sources are
            # refused without a logged-in user.
            raise NotFoundError(reason=CitationUnresolvedReason.FORBIDDEN.value)
        url_allowed = True
        if item.type == CitationType.RAG and login_user is not None:
            permitted = await self._permitted_file_ids([item], login_user)
            url_allowed = self._rag_url_allowed(item, permitted)
            # per_user + no view_file → not found (AC-18); shared survives with
            # metadata but no full-file URL (AC-21).
            if not url_allowed and item.accessScope != "shared":
                raise NotFoundError(reason=CitationUnresolvedReason.FORBIDDEN.value)
        try:
            return await self._enrich_item(item, login_user, url_allowed=url_allowed)
        except NotFoundError:
            # Past the permission gate, so naming the source as gone is safe.
            raise NotFoundError(reason=CitationUnresolvedReason.EXPIRED.value) from None

    async def resolve_citations(
        self,
        citation_ids: list[str],
        login_user: UserPayload | None = None,
    ) -> list[CitationRegistryItemSchema]:
        """Resolve multiple citation items, returning only the ones that resolved.

        Kept for callers that do not need the reasons; the reasons live on
        ``resolve_citations_with_reasons``.
        """
        return (await self.resolve_citations_with_reasons(citation_ids, login_user)).items

    async def resolve_citations_with_reasons(
        self,
        citation_ids: list[str],
        login_user: UserPayload | None = None,
    ) -> ResolveCitationResponse:
        """Resolve citations and say why each unresolved one did not make it.

        The reasons are decided in a fixed order, and the order is a safety
        property rather than a preference (design §3 decision 5):

        1. no logged-in user            -> forbidden
        2. no record in cache or DB     -> expired
        3. record exists, view_file no  -> forbidden
        4. record exists, permitted, underlying source gone -> expired

        Rule 1 outranks rule 2 on purpose. If an unknown id came back as
        "expired" while a real one came back as "forbidden", an anonymous caller
        could probe which citation ids ever existed just by watching the reason
        flip.
        """
        unresolved: dict[str, CitationUnresolvedReason] = {}

        cached_items = await self.runtime_cache_service.get_citations_by_ids(citation_ids)
        item_by_id: dict[str, CitationRegistryItemSchema] = {item.citationId: item for item in cached_items}
        missing_ids = [citation_id for citation_id in citation_ids if citation_id not in item_by_id]
        if missing_ids:
            for item in await self.registry_service.list_citations_by_ids(missing_ids):
                item_by_id[item.citationId] = item

        items = [item_by_id[citation_id] for citation_id in citation_ids if citation_id in item_by_id]

        if login_user is None:
            # Rule 1, applied before anything else so an unknown id is
            # indistinguishable from a refused one.
            for citation_id in citation_ids:
                item = item_by_id.get(citation_id)
                if item is None or not self._is_anonymous_readable(item):
                    unresolved[citation_id] = CitationUnresolvedReason.FORBIDDEN
            items = [item for item in items if self._is_anonymous_readable(item)]
            permitted = None
        else:
            # Rule 2 — nothing known about it, so nothing can leak by saying so.
            for citation_id in citation_ids:
                if citation_id not in item_by_id:
                    unresolved[citation_id] = CitationUnresolvedReason.EXPIRED
            # Rule 3 — INV-7 and its F041 tiering, untouched by this feature.
            permitted = await self._permitted_file_ids(items, login_user)
            visible_items = self._apply_tier_filter(items, permitted)
            visible_ids = {item.citationId for item in visible_items}
            for item in items:
                if item.citationId not in visible_ids:
                    unresolved[item.citationId] = CitationUnresolvedReason.FORBIDDEN
            items = visible_items

        enriched_by_id: dict[str, CitationRegistryItemSchema] = {}
        for item in items:
            try:
                enriched_by_id[item.citationId] = await self._enrich_item(
                    item, login_user, url_allowed=self._rag_url_allowed(item, permitted)
                )
            except NotFoundError:
                # Rule 4 — past the permission gate, so naming it as gone leaks
                # nothing the caller was not already entitled to see.
                unresolved[item.citationId] = CitationUnresolvedReason.EXPIRED

        return ResolveCitationResponse(
            items=[enriched_by_id[cid] for cid in citation_ids if cid in enriched_by_id],
            unresolved=[
                UnresolvedCitationSchema(citationId=cid, reason=unresolved[cid])
                for cid in citation_ids
                if cid in unresolved
            ],
        )

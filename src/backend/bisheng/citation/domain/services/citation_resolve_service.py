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
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
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
        knowledge_file_repository: KnowledgeFileRepository | None = None,
    ):
        self.registry_service = CitationRegistryService(repository)
        self.runtime_cache_service = runtime_cache_service or CitationRuntimeCacheService()
        self.knowledge_file_repository = knowledge_file_repository

    # ------------------------------------------------------------------
    # F029 — view_file filter
    # ------------------------------------------------------------------

    async def _resolve_rag_space_pairs(
        self,
        items: list[CitationRegistryItemSchema],
    ) -> dict[int, set[int]]:
        """Group RAG citations by knowledge_id and collect their documentIds.

        Missing ``knowledgeId`` values are returned under ``space_id=0`` so
        direct callers fail closed. Public logged-in resolve paths always run
        the explicit-tenant canonicalization batch before reaching this helper.
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
                grouped[0].add(int(file_id))
                continue
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

        visibility = self._build_visibility_service(login_user)
        allowed: set[int] = set()
        for space_id, file_ids in grouped.items():
            if space_id == 0 or not file_ids:
                continue
            allowed |= await visibility.post_filter_rebac_visible_files(space_id, file_ids)
        return allowed

    @staticmethod
    def _build_visibility_service(login_user: UserPayload):
        from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
            KnowledgeFileVisibilityService,
        )

        return KnowledgeFileVisibilityService(request=None, login_user=login_user)

    async def _canonicalize_rag_items(
        self,
        items: list[CitationRegistryItemSchema],
        login_user: UserPayload | None,
    ) -> list[CitationRegistryItemSchema]:
        """Refresh persisted RAG locations before any permission or URL decision."""

        if login_user is None or not items:
            return list(items)
        file_ids = sorted(
            {
                int(payload.documentId)
                for item in items
                if item.type == CitationType.RAG
                and (payload := RagCitationPayloadSchema.model_validate(item.sourcePayload)).documentId is not None
            }
        )
        if not file_ids:
            return list(items)

        visibility = self._build_visibility_service(login_user)
        tenant_id = visibility.require_explicit_tenant()
        if self.knowledge_file_repository is None:
            raise RuntimeError("citation resolve requires KnowledgeFileRepository")
        file_rows = await self.knowledge_file_repository.find_by_ids_for_tenant(
            tenant_id=int(tenant_id),
            entity_ids=file_ids,
        )
        rows_by_id = {int(row.id): row for row in file_rows}
        candidate_space_ids = {
            int(row.knowledge_id)
            for row in rows_by_id.values()
            if row.knowledge_id is not None and int(row.knowledge_id) > 0
        }
        candidate_space_ids.update(
            int(payload.knowledgeId)
            for item in items
            if item.type == CitationType.RAG
            and (payload := RagCitationPayloadSchema.model_validate(item.sourcePayload)).knowledgeId is not None
            and int(payload.knowledgeId) > 0
        )
        authoritative_space_ids = await visibility.authoritative_mutation_space_ids(
            space_ids=sorted(candidate_space_ids),
            resource_ids=file_ids,
        )

        canonical: list[CitationRegistryItemSchema] = []
        for item in items:
            if item.type != CitationType.RAG:
                canonical.append(item)
                continue
            payload = RagCitationPayloadSchema.model_validate(item.sourcePayload)
            file_id = int(payload.documentId or 0)
            file_row = rows_by_id.get(file_id)
            if file_row is None:
                continue
            authoritative_space_id = authoritative_space_ids.get(file_id, int(file_row.knowledge_id))
            canonical_payload = payload.model_copy(update={"knowledgeId": authoritative_space_id})
            canonical_payload = self._rewrite_rag_payload_name(
                canonical_payload,
                projected_name=str(file_row.file_name),
                replaced_name=payload.documentName,
            )
            canonical.append(item.model_copy(update={"sourcePayload": canonical_payload}))
        return canonical

    async def _file_change_visible_ids(
        self,
        items: list[CitationRegistryItemSchema],
        login_user: UserPayload | None,
    ) -> set[int] | None:
        """Return RAG IDs not hidden by F046, batched across all cited spaces."""
        if login_user is None or not items:
            return None
        grouped = await self._resolve_rag_space_pairs(items)
        space_ids = sorted(space_id for space_id in grouped if space_id > 0)
        resource_ids = sorted(
            {
                resource_id
                for space_id, file_ids in grouped.items()
                if space_id > 0
                for resource_id in file_ids
            }
        )
        if not space_ids or not resource_ids:
            return set()
        visibility = self._build_visibility_service(login_user)
        return await visibility.filter_file_change_visible_ids(
            space_ids=space_ids,
            resource_ids=resource_ids,
        )

    @staticmethod
    def _apply_file_change_filter(
        items: list[CitationRegistryItemSchema],
        visible_ids: set[int] | None,
    ) -> list[CitationRegistryItemSchema]:
        """F046 is a hard deny and therefore precedes accessScope tiering."""
        if visible_ids is None:
            return list(items)
        filtered: list[CitationRegistryItemSchema] = []
        for item in items:
            if item.type != CitationType.RAG:
                filtered.append(item)
                continue
            payload = RagCitationPayloadSchema.model_validate(item.sourcePayload)
            if payload.documentId is not None and int(payload.documentId) in visible_ids:
                filtered.append(item)
        return filtered

    async def _project_old_file_names(
        self,
        items: list[CitationRegistryItemSchema],
        login_user: UserPayload | None,
    ) -> list[CitationRegistryItemSchema]:
        if login_user is None or not items:
            return list(items)
        grouped = await self._resolve_rag_space_pairs(items)
        visibility = self._build_visibility_service(login_user)
        names: dict[int, tuple[str, str]] = {}
        for space_id, file_ids in grouped.items():
            if space_id > 0 and file_ids:
                names.update(
                    await visibility.old_name_projection(
                        space_id=space_id,
                        resource_ids=file_ids,
                    )
                )
        projected: list[CitationRegistryItemSchema] = []
        for item in items:
            if item.type != CitationType.RAG:
                projected.append(item)
                continue
            payload = RagCitationPayloadSchema.model_validate(item.sourcePayload)
            old_and_new = names.get(int(payload.documentId or 0))
            if old_and_new is None:
                projected.append(item)
                continue
            projected_name, replaced_name = old_and_new
            payload = self._rewrite_rag_payload_name(
                payload,
                projected_name=projected_name,
                replaced_name=replaced_name,
            )
            projected.append(item.model_copy(update={"sourcePayload": payload}))
        return projected

    @staticmethod
    def _rewrite_rag_payload_name(
        payload: RagCitationPayloadSchema,
        *,
        projected_name: str,
        replaced_name: str | None,
    ) -> RagCitationPayloadSchema:
        if not projected_name:
            return payload
        updated_items = [
            child.model_copy(
                update={
                    "content": child.content.replace(replaced_name, projected_name)
                    if isinstance(child.content, str) and replaced_name
                    else child.content
                }
            )
            for child in payload.items
        ]
        return payload.model_copy(
            update={
                "documentName": projected_name,
                "snippet": payload.snippet.replace(replaced_name, projected_name)
                if isinstance(payload.snippet, str) and replaced_name
                else payload.snippet,
                "items": updated_items,
            }
        )

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
        items = await self._canonicalize_rag_items(items, login_user)
        items = await self._project_old_file_names(items, login_user)
        permitted = await self._permitted_file_ids(items, login_user)
        file_change_visible_ids = await self._file_change_visible_ids(items, login_user)
        items = self._apply_file_change_filter(items, file_change_visible_ids)
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
        url_allowed = True
        if item.type == CitationType.RAG and login_user is not None:
            canonical_items = await self._canonicalize_rag_items([item], login_user)
            if not canonical_items:
                raise NotFoundError()
            item = (await self._project_old_file_names(canonical_items, login_user))[0]
            permitted = await self._permitted_file_ids([item], login_user)
            file_change_visible_ids = await self._file_change_visible_ids([item], login_user)
            if not self._apply_file_change_filter([item], file_change_visible_ids):
                raise NotFoundError()
            url_allowed = self._rag_url_allowed(item, permitted)
            # per_user + no view_file → not found (AC-18); shared survives with
            # metadata but no full-file URL (AC-21).
            if not url_allowed and item.accessScope != "shared":
                raise NotFoundError()
        return await self._enrich_item(item, login_user, url_allowed=url_allowed)

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

        items = await self._canonicalize_rag_items(items, login_user)
        items = await self._project_old_file_names(items, login_user)
        permitted = await self._permitted_file_ids(items, login_user)
        file_change_visible_ids = await self._file_change_visible_ids(items, login_user)
        items = self._apply_file_change_filter(items, file_change_visible_ids)
        items = self._apply_tier_filter(items, permitted)
        enriched_items = await asyncio.gather(
            *(self._enrich_item(item, login_user, url_allowed=self._rag_url_allowed(item, permitted)) for item in items)
        )
        item_map: dict[str, CitationRegistryItemSchema] = {item.citationId: item for item in enriched_items}
        return [item_map[citation_id] for citation_id in citation_ids if citation_id in item_map]

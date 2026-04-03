import asyncio
import json
from typing import Dict, List, Optional

from bisheng.citation.domain.repositories.interfaces.message_citation_repository import MessageCitationRepository
from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationPayloadSchema,
    WebCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService


class CitationResolveService:
    """Resolve persisted citation items into a unified response payload."""

    def __init__(self, repository: MessageCitationRepository):
        self.registry_service = CitationRegistryService(repository)

    @staticmethod
    async def _has_file_access(login_user: UserPayload, knowledge_id: Optional[int]) -> bool:
        """Check whether the current user can access a knowledge citation."""
        if knowledge_id is None:
            return False
        knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
        if knowledge is None:
            return False
        return login_user.access_check(knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE)

    @staticmethod
    async def _resolve_bbox(file_id: Optional[int], bbox: Optional[str]) -> Optional[str]:
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
        login_user: Optional[UserPayload],
    ) -> CitationRegistryItemSchema:
        """Enrich a RAG citation with file share URLs and best-effort bbox details."""
        payload = RagCitationPayloadSchema.model_validate(item.sourcePayload)
        file_id = payload.fileId or payload.documentId

        if file_id is not None:
            file_info = await asyncio.to_thread(KnowledgeFileDao.query_by_id_sync, file_id)
            if file_info is not None:
                payload.fileId = file_info.id
                payload.documentId = payload.documentId or file_info.id
                payload.knowledgeId = payload.knowledgeId or file_info.knowledge_id
                payload.documentName = payload.documentName or file_info.file_name

                has_access = login_user is None or await self._has_file_access(login_user, file_info.knowledge_id)
                if has_access:
                    download_url, preview_url = await asyncio.to_thread(
                        KnowledgeService.get_file_share_url,
                        None,
                        file_info,
                    )
                    payload.downloadUrl = download_url or payload.downloadUrl
                    payload.previewUrl = preview_url or payload.previewUrl
                    payload.bbox = await self._resolve_bbox(file_info.id, payload.bbox)

        return item.model_copy(update={'sourcePayload': payload})

    @staticmethod
    def _enrich_web_item(item: CitationRegistryItemSchema) -> CitationRegistryItemSchema:
        """Normalize persisted web payload before returning it."""
        payload = WebCitationPayloadSchema.model_validate(item.sourcePayload)
        payload.url = CitationRegistryService.normalize_url(payload.url)
        return item.model_copy(update={'sourcePayload': payload})

    async def _enrich_item(
        self,
        item: CitationRegistryItemSchema,
        login_user: Optional[UserPayload],
    ) -> CitationRegistryItemSchema:
        """Enrich a citation item based on its type."""
        if item.type == CitationType.RAG:
            return await self._enrich_rag_item(item, login_user)
        return self._enrich_web_item(item)

    async def resolve_citation(
        self,
        citation_id: str,
        login_user: Optional[UserPayload] = None,
    ) -> CitationRegistryItemSchema:
        """Resolve one citation item by business ID."""
        item = await self.registry_service.get_citation(citation_id)
        if item is None:
            raise NotFoundError()
        return await self._enrich_item(item, login_user)

    async def resolve_citations(
        self,
        citation_ids: List[str],
        login_user: Optional[UserPayload] = None,
    ) -> List[CitationRegistryItemSchema]:
        """Resolve multiple citation items in one round trip."""
        items = await self.registry_service.list_citations_by_ids(citation_ids)
        enriched_items = await asyncio.gather(*(self._enrich_item(item, login_user) for item in items))
        item_map: Dict[str, CitationRegistryItemSchema] = {
            item.citationId: item
            for item in enriched_items
        }
        return [item_map[citation_id] for citation_id in citation_ids if citation_id in item_map]

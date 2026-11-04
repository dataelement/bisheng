"""Shared retrieval orchestration for REST and MCP entry points."""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from bisheng.open_endpoints.domain.schemas.filelib import RetrieveChunk, RetrieveReq, RetrieveResp
from bisheng.open_endpoints.domain.services.filelib_retrieve_source_service import (
    EMPTY_RETRIEVE_SOURCE_LINK,
    FilelibRetrieveSourceService,
    RetrieveSourceRef,
)

if TYPE_CHECKING:
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
    from bisheng.knowledge.rag.async_retrieval_runtime import AsyncRetrievalRuntime

logger = logging.getLogger(__name__)


class FilelibRetrieveService:
    def __init__(
        self,
        chat_service: "KnowledgeSpaceChatService",
        source_service: FilelibRetrieveSourceService,
        retrieval_runtime: "AsyncRetrievalRuntime",
    ) -> None:
        self.chat_service = chat_service
        self.source_service = source_service
        self.retrieval_runtime = retrieval_runtime
        self.timeout_seconds = retrieval_runtime.config.total_timeout_seconds

    async def retrieve(
        self, req: RetrieveReq, *, file_ids_by_knowledge: Mapping[int, Sequence[int]] | None = None
    ) -> RetrieveResp:
        kb_filters = None
        if req.filters and req.filters.knowledge_base_filters:
            kb_filters = {
                item.knowledge_base_id: {"tags": item.tags, "tag_match_mode": item.tag_match_mode}
                for item in req.filters.knowledge_base_filters
            }
        scope: dict[int, set[int]] | None = None
        if file_ids_by_knowledge is not None:
            if any(type(key) is not int for key in file_ids_by_knowledge) or set(file_ids_by_knowledge) != set(
                req.knowledge_base_ids
            ):
                raise ValueError("file scope must cover exactly the requested knowledge spaces")
            scope = {}
            kb_filters = kb_filters or {}
            for knowledge_id, file_ids in file_ids_by_knowledge.items():
                if not isinstance(file_ids, Sequence) or any(type(item) is not int or item <= 0 for item in file_ids):
                    raise ValueError("file scope requires positive integer entry ids")
                scope[knowledge_id] = set(file_ids)
                kb_filters.setdefault(knowledge_id, {})["file_ids"] = sorted(scope[knowledge_id])
            if not any(scope.values()):
                return RetrieveResp(chunks=[], total=0)

        results = await self.chat_service.aretrieve_chunks(
            query=req.query,
            knowledge_base_ids=req.knowledge_base_ids,
            kb_filters=kb_filters,
            top_k=req.top_k,
            max_content=req.max_content,
            **({"strict_file_scope": True} if scope is not None else {}),
        )
        if scope is not None and any(
            kb_id not in scope or int(doc.metadata.get("document_id", 0)) not in scope[kb_id] for kb_id, doc in results
        ):
            raise ValueError("retrieval returned an entry outside the requested file scope")
        prepared_results = [
            (
                kb_id,
                doc,
                RetrieveSourceRef(
                    entry_file_id=int(doc.metadata.get("document_id", 0)),
                    canonical_document_id=doc.metadata.get("canonical_document_id"),
                    canonical_version_id=doc.metadata.get("canonical_version_id"),
                ),
            )
            for kb_id, doc in results
        ]
        source_refs = list(
            dict.fromkeys(source_ref for _, _, source_ref in prepared_results if source_ref.entry_file_id > 0)
        )
        try:
            source_links = await asyncio.wait_for(
                self.source_service.resolve_links(source_refs),
                timeout=self.retrieval_runtime.config.source_link_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("retrieve source links timed out document_count=%s", len(source_refs))
            source_links = {}

        chunks = []
        for kb_id, doc, source_ref in prepared_results:
            source_link = source_links.get(source_ref.entry_file_id, EMPTY_RETRIEVE_SOURCE_LINK)
            chunks.append(
                RetrieveChunk(
                    content=doc.page_content,
                    knowledge_id=kb_id,
                    document_id=source_ref.entry_file_id,
                    document_name=str(doc.metadata.get("document_name", "")),
                    chunk_index=int(doc.metadata.get("chunk_index", 0)),
                    source_url=source_link.source_url,
                    source_full_url=source_link.source_full_url,
                )
            )
        return RetrieveResp(chunks=chunks, total=len(chunks))

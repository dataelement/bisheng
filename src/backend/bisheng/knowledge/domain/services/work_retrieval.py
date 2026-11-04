"""Shared retrieval contract for authenticated desktop and server-side tools."""

from bisheng.knowledge.domain.schemas.work_retrieval import WorkRetrievalRequest
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService


async def retrieve_workspace_chunks(service: KnowledgeSpaceChatService, request: WorkRetrievalRequest) -> dict:
    results = await service.aretrieve_chunks(
        query=request.query,
        knowledge_base_ids=list(dict.fromkeys(request.space_ids)),
        top_k=10,
        max_content=12000,
    )
    return {
        "chunks": [
            {
                "content": doc.page_content,
                "space_id": space_id,
                "document_id": doc.metadata.get("document_id"),
                "document_name": doc.metadata.get("document_name", ""),
                "chunk_index": doc.metadata.get("chunk_index"),
            }
            for space_id, doc in results
        ]
    }

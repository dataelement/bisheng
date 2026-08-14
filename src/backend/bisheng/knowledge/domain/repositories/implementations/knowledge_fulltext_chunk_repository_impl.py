"""从当前知识库 RAG ES 稳定分页读取全文 Chunk。"""

from __future__ import annotations

from elasticsearch import AsyncElasticsearch

from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_chunk_repository import (
    KnowledgeFulltextChunkRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextChunk


class KnowledgeFulltextChunkRepositoryImpl(KnowledgeFulltextChunkRepository):
    PIT_KEEP_ALIVE = "1m"

    def __init__(self, client: AsyncElasticsearch, *, page_size: int = 500):
        if not 1 <= page_size <= 2000:
            raise ValueError("page_size must be between 1 and 2000")
        self.client = client
        self.page_size = page_size

    async def list_all(
        self,
        *,
        index_name: str,
        file_id: int,
        knowledge_id: int,
    ) -> list[KnowledgeFulltextChunk]:
        chunks: list[KnowledgeFulltextChunk] = []
        search_after: list | None = None
        pit_response = await self.client.open_point_in_time(
            index=index_name,
            keep_alive=self.PIT_KEEP_ALIVE,
        )
        pit_id = pit_response.get("id")
        if not isinstance(pit_id, str) or not pit_id:
            raise ValueError("RAG chunk point in time has no id")
        try:
            while True:
                kwargs = {
                    "pit": {"id": pit_id, "keep_alive": self.PIT_KEEP_ALIVE},
                    "query": {"term": {"metadata.document_id": file_id}},
                    "sort": [
                        {"metadata.chunk_index": "asc"},
                        {"_shard_doc": "asc"},
                    ],
                    "size": self.page_size,
                    "source": ["text", "metadata.document_id", "metadata.knowledge_id", "metadata.chunk_index"],
                }
                if search_after is not None:
                    kwargs["search_after"] = search_after
                response = await self.client.search(**kwargs)
                rotated_pit_id = response.get("pit_id")
                if isinstance(rotated_pit_id, str) and rotated_pit_id:
                    pit_id = rotated_pit_id
                hits = response.get("hits", {}).get("hits", [])
                if not hits:
                    break
                for hit in hits:
                    source = hit.get("_source")
                    if not isinstance(source, dict) or not isinstance(source.get("metadata"), dict):
                        raise ValueError("RAG chunk _source or metadata is invalid")
                    metadata = source["metadata"]
                    chunks.append(
                        KnowledgeFulltextChunk(
                            es_id=str(hit.get("_id", "")),
                            document_id=int(metadata["document_id"]),
                            knowledge_id=int(metadata["knowledge_id"]),
                            chunk_index=int(metadata["chunk_index"]),
                            text=str(source.get("text", "")),
                        )
                    )
                sort_value = hits[-1].get("sort")
                if not isinstance(sort_value, list):
                    raise ValueError("RAG chunk search result has no stable sort value")
                search_after = sort_value
        finally:
            await self.client.close_point_in_time(id=pit_id)
        return chunks

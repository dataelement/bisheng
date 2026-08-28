"""从当前知识库 RAG ES 稳定分页读取全文 Chunk。"""

from __future__ import annotations

from elasticsearch import AsyncElasticsearch

from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_chunk_repository import (
    KnowledgeFulltextChunkRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextChunk,
    KnowledgeFulltextChunkSource,
)


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
        source: KnowledgeFulltextChunkSource,
    ) -> list[KnowledgeFulltextChunk]:
        chunk_source = source
        chunks: list[KnowledgeFulltextChunk] = []
        search_after: list | None = None
        pit_kwargs = {
            "index": chunk_source.index_name,
            "keep_alive": self.PIT_KEEP_ALIVE,
        }
        if chunk_source.routing:
            pit_kwargs["routing"] = chunk_source.routing
        pit_response = await self.client.open_point_in_time(**pit_kwargs)
        pit_id = pit_response.get("id")
        if not isinstance(pit_id, str) or not pit_id:
            raise ValueError("RAG chunk point in time has no id")
        try:
            while True:
                if chunk_source.shared:
                    query = {
                        "bool": {
                            "filter": [
                                {"term": {"metadata.tenant_id": chunk_source.tenant_id}},
                                {
                                    "term": {
                                        "metadata.canonical_document_id": (
                                            chunk_source.canonical_document_id
                                        )
                                    }
                                },
                                {
                                    "term": {
                                        "metadata.canonical_version_id": (
                                            chunk_source.canonical_version_id
                                        )
                                    }
                                },
                                {
                                    "term": {
                                        "metadata.content_generation": (
                                            chunk_source.content_generation
                                        )
                                    }
                                },
                                {"term": {"metadata.knowledge_ids": chunk_source.knowledge_id}},
                            ]
                        }
                    }
                else:
                    query = {"term": {"metadata.document_id": chunk_source.file_id}}
                kwargs = {
                    "pit": {"id": pit_id, "keep_alive": self.PIT_KEEP_ALIVE},
                    "query": query,
                    "sort": [
                        {"metadata.chunk_index": "asc"},
                        {"_shard_doc": "asc"},
                    ],
                    "size": self.page_size,
                    "source": [
                        "text",
                        "metadata.document_id",
                        "metadata.knowledge_id",
                        "metadata.chunk_index",
                    ],
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
                    document_source = hit.get("_source")
                    if not isinstance(document_source, dict) or not isinstance(
                        document_source.get("metadata"), dict
                    ):
                        raise ValueError("RAG chunk _source or metadata is invalid")
                    metadata = document_source["metadata"]
                    chunks.append(
                        KnowledgeFulltextChunk(
                            es_id=str(hit.get("_id", "")),
                            document_id=(
                                int(chunk_source.file_id)
                                if chunk_source.shared
                                else int(metadata["document_id"])
                            ),
                            knowledge_id=(
                                int(chunk_source.knowledge_id)
                                if chunk_source.shared
                                else int(metadata["knowledge_id"])
                            ),
                            chunk_index=int(metadata["chunk_index"]),
                            text=str(document_source.get("text", "")),
                        )
                    )
                sort_value = hits[-1].get("sort")
                if not isinstance(sort_value, list):
                    raise ValueError("RAG chunk search result has no stable sort value")
                search_after = sort_value
        finally:
            await self.client.close_point_in_time(id=pit_id)
        return chunks

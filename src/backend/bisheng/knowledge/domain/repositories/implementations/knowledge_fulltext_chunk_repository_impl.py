"""从当前知识库 RAG ES 稳定分页读取全文 Chunk。"""

from __future__ import annotations

from elasticsearch import AsyncElasticsearch
from collections import defaultdict

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

    @staticmethod
    def _query(source):
        if not source.shared:
            return {"term": {"metadata.document_id": source.file_id}}
        return {"bool": {"filter": [{"term": {f"metadata.{key}": value}} for key, value in {
            "tenant_id": source.tenant_id, "canonical_document_id": source.canonical_document_id,
            "canonical_version_id": source.canonical_version_id, "content_generation": source.content_generation,
            "knowledge_ids": source.knowledge_id,
        }.items()]}}

    async def list_many(self, sources: list[KnowledgeFulltextChunkSource]) -> dict[int, list[KnowledgeFulltextChunk] | Exception]:
        groups = defaultdict(list)
        for source in sources:
            groups[source.index_name].append(source)
        results = {source.file_id: [] for source in sources}
        for index, group in groups.items():
            pit_id = None
            try:
                response = await self.client.open_point_in_time(index=index, keep_alive=self.PIT_KEEP_ALIVE)
                pit_id = response.get("id")
                if not pit_id:
                    raise ValueError("RAG chunk point in time has no id")
                after = None
                # 同索引一次读取多文档; 持续分页直到空页, 不截断大文档。
                while True:
                    kwargs = dict(pit={"id": pit_id, "keep_alive": self.PIT_KEEP_ALIVE},
                        query={"bool": {"should": [self._query(source) for source in group], "minimum_should_match": 1}},
                        sort=[{"_shard_doc": "asc"}], size=self.page_size,
                        source=["text", "metadata"])
                    if after is not None:
                        kwargs["search_after"] = after
                    response = await self.client.search(**kwargs)
                    pit_id = response.get("pit_id") or pit_id
                    if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
                        raise RuntimeError("RAG chunk batch query incomplete")
                    hits = response.get("hits", {}).get("hits", [])
                    if not hits:
                        break
                    for hit in hits:
                        content = hit.get("_source", {})
                        metadata = content.get("metadata", {})
                        for source in group:
                            if source.shared:
                                match = all(metadata.get(key) == value for key, value in {
                                    "tenant_id": source.tenant_id, "canonical_document_id": source.canonical_document_id,
                                    "canonical_version_id": source.canonical_version_id, "content_generation": source.content_generation,
                                }.items()) and source.knowledge_id in (metadata.get("knowledge_ids") or [])
                            else:
                                match = str(metadata.get("document_id")) == str(source.file_id)
                            if match:
                                results[source.file_id].append(KnowledgeFulltextChunk(
                                    es_id=str(hit["_id"]), document_id=source.file_id, knowledge_id=source.knowledge_id,
                                    chunk_index=int(metadata["chunk_index"]), text=str(content.get("text", "")),
                                ))
                    next_after = hits[-1].get("sort")
                    if not isinstance(next_after, list) or next_after == after:
                        raise ValueError("RAG chunk batch pagination did not advance")
                    after = next_after
            except Exception as exc:
                results.update({source.file_id: exc for source in group})
            finally:
                if pit_id:
                    await self.client.close_point_in_time(id=pit_id)
        return results

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

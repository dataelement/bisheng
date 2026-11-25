"""MemoryIndex over Elasticsearch (keyword) and Milvus (vector) (design decision 12).

- ES index ``bisheng_memory_item`` and Milvus collection
  ``bisheng_memory_item_{embedding_model_id}`` are shared by all tenants; every
  write carries ``tenant_id``, ``user_id`` and ``item_id`` metadata, and every
  search filters on the scope produced by ``build_scope_filter``.
- Does not reuse ``core/vectorstore/multi_retriever.py``; fusion is in search.py.
- Embedding uses the tenant's knowledge default embedding model, called as the
  memory owner with application type ``memory``; each call times out after 3 s.
"""

from __future__ import annotations

import asyncio

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.llm.domain.services.llm import LLMService
from bisheng.memory.domain.ports import IndexHit, MemoryContext, VectorUnconfigured, build_scope_filter

ES_INDEX_NAME = "bisheng_memory_item"
EMBED_TIMEOUT_SECONDS = 3.0


def milvus_collection_name(model_id: str) -> str:
    return f"{ES_INDEX_NAME}_{model_id}"


def _es_store():
    from bisheng.common.schemas.rag_schema import RagMetadataFieldSchema
    from bisheng.knowledge.rag.elasticsearch_factory import ElasticsearchFactory

    schemas = [
        RagMetadataFieldSchema(field_name="tenant_id", field_type="int64"),
        RagMetadataFieldSchema(field_name="user_id", field_type="int64"),
        RagMetadataFieldSchema(field_name="item_id", field_type="text"),
    ]
    return ElasticsearchFactory.init_vectorstore(ES_INDEX_NAME, metadata_schemas=schemas)


def _milvus_store(collection_name: str, embedding):
    from bisheng.common.schemas.rag_schema import RagMetadataFieldSchema
    from bisheng.knowledge.rag.milvus_factory import MilvusFactory

    schemas = [
        RagMetadataFieldSchema(field_name="tenant_id", field_type="int64"),
        RagMetadataFieldSchema(field_name="user_id", field_type="int64"),
        RagMetadataFieldSchema(field_name="item_id", field_type="text", kwargs={"max_length": 64}),
    ]
    return MilvusFactory.init_vectorstore(collection_name, embedding, metadata_schemas=schemas)


async def default_embedding_loader(ctx: MemoryContext):
    """(model_id, Embeddings) of the tenant's knowledge default embedding, or (None, None)."""
    config = await LLMService.aget_knowledge_llm(tenant_id=ctx.tenant_id)
    model_id = getattr(config, "embedding_model_id", None)
    if not model_id:
        return None, None
    embedding = await LLMService.get_bisheng_embedding(
        model_id=model_id,
        app_id=ApplicationTypeEnum.MEMORY.value,
        app_name=ApplicationTypeEnum.MEMORY.value,
        app_type=ApplicationTypeEnum.MEMORY,
        user_id=ctx.user_id,
    )
    return str(model_id), embedding


def _milvus_scope(scope: dict) -> str:
    return f"tenant_id == {int(scope['tenant_id'])} and user_id == {int(scope['user_id'])}"


class PlatformMemoryIndex:
    def __init__(self, es_factory=None, milvus_factory=None, embedding_loader=None):
        self._es_factory = es_factory or _es_store
        self._milvus_factory = milvus_factory or _milvus_store
        self._embedding_loader = embedding_loader or default_embedding_loader
        self._es = None

    def _get_es(self):
        if self._es is None:
            self._es = self._es_factory()
        return self._es

    async def current_model_id(self, ctx: MemoryContext) -> str | None:
        model_id, _ = await self._embedding_loader(ctx)
        return model_id

    async def upsert(self, ctx: MemoryContext, item_id: str, content: str) -> str | None:
        scope = build_scope_filter(ctx)
        meta = {**scope, "item_id": item_id}
        es = self._get_es()
        await es.adelete(ids=[item_id])
        await es.aadd_texts([content], metadatas=[meta], ids=[item_id])
        model_id, embedding = await self._embedding_loader(ctx)
        if not model_id:
            return None
        vector = await asyncio.wait_for(embedding.aembed_documents([content]), timeout=EMBED_TIMEOUT_SECONDS)
        milvus = self._milvus_factory(milvus_collection_name(model_id), embedding)
        expr = f'{_milvus_scope(scope)} and item_id in ["{item_id}"]'
        await asyncio.to_thread(milvus.delete, expr=expr)
        await asyncio.to_thread(milvus.add_embeddings, [content], vector, metadatas=[meta])
        return model_id

    async def delete(self, ctx: MemoryContext, item_ids: list[str]) -> None:
        if not item_ids:
            return
        scope = build_scope_filter(ctx)
        await self._get_es().adelete(ids=list(item_ids))
        model_id, embedding = await self._embedding_loader(ctx)
        if not model_id:
            return
        milvus = self._milvus_factory(milvus_collection_name(model_id), embedding)
        quoted = ", ".join(f'"{i}"' for i in item_ids)
        await asyncio.to_thread(milvus.delete, expr=f"{_milvus_scope(scope)} and item_id in [{quoted}]")

    async def delete_user(self, ctx: MemoryContext) -> None:
        scope = build_scope_filter(ctx)
        es = self._get_es()
        await es.client.delete_by_query(
            index=ES_INDEX_NAME,
            query={
                "bool": {
                    "filter": [
                        {"term": {"metadata.tenant_id": scope["tenant_id"]}},
                        {"term": {"metadata.user_id": scope["user_id"]}},
                    ]
                }
            },
            conflicts="proceed",
        )
        model_id, embedding = await self._embedding_loader(ctx)
        if model_id:
            milvus = self._milvus_factory(milvus_collection_name(model_id), embedding)
            await asyncio.to_thread(milvus.delete, expr=_milvus_scope(scope))

    async def keyword_search(self, scope: dict, query: str, limit: int) -> list[IndexHit]:
        flt = [
            {"term": {"metadata.tenant_id": scope["tenant_id"]}},
            {"term": {"metadata.user_id": scope["user_id"]}},
        ]
        results = await self._get_es().asimilarity_search_with_score(query, k=limit, filter=flt)
        return [IndexHit(item_id=doc.metadata["item_id"], score=float(score)) for doc, score in results]

    async def vector_search(self, ctx: MemoryContext, scope: dict, query: str, limit: int) -> list[IndexHit]:
        model_id, embedding = await self._embedding_loader(ctx)
        if not model_id:
            raise VectorUnconfigured()
        vector = await asyncio.wait_for(embedding.aembed_query(query), timeout=EMBED_TIMEOUT_SECONDS)
        milvus = self._milvus_factory(milvus_collection_name(model_id), embedding)
        results = await asyncio.to_thread(
            milvus.similarity_search_with_score_by_vector, vector, k=limit, expr=_milvus_scope(scope)
        )
        return [IndexHit(item_id=doc.metadata["item_id"], score=-float(score)) for doc, score in results]

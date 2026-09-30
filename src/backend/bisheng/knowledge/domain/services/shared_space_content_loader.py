"""主版本切换或显式重建从原文件恢复内容，不依赖旧空间索引。"""

import asyncio
from collections.abc import Sequence
from dataclasses import replace

from bisheng.knowledge.domain.contracts.shared_space_storage import SharedContentChunk
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.shared_space_direct_ingestion_service import SharedSpaceDirectIngestionService
from bisheng.knowledge.rag.knowledge_file_pipeline import KnowledgeFilePipeline
from bisheng.knowledge.rag.pipeline.types import PipelineConfig, PipelineStage
from bisheng.knowledge.rag.shared_space_storage import resolve_space_shared_routing
from bisheng.llm.domain import LLMService


async def embed_shared_content_chunks(
    file: KnowledgeFile, chunks: Sequence[SharedContentChunk],
) -> tuple[SharedContentChunk, ...]:
    """正文已有时仅补缺失向量, 不下载原文件或调用解析流水线。"""
    def embed() -> tuple[SharedContentChunk, ...]:
        missing = [index for index, chunk in enumerate(chunks) if chunk.vector is None]
        if not missing:
            return tuple(chunks)
        route = resolve_space_shared_routing(int(file.tenant_id or 1), KnowledgeTypeEnum.SPACE.value)
        embeddings = LLMService.get_bisheng_knowledge_embedding_sync(
            invoke_user_id=file.user_id, model_id=route.embedding_model_id,
        )
        vectors = embeddings.embed_documents([chunks[index].text for index in missing])
        if len(vectors) != len(missing):
            raise ValueError("embedding result count does not match stored chunks")
        result = list(chunks)
        for index, vector in zip(missing, vectors, strict=True):
            result[index] = replace(chunks[index], vector=list(vector))
        return tuple(result)

    return await asyncio.to_thread(embed)


async def load_shared_content_from_original(file: KnowledgeFile):
    def load():
        route = resolve_space_shared_routing(int(file.tenant_id or 1), KnowledgeTypeEnum.SPACE.value)
        pipeline = KnowledgeFilePipeline(
            invoke_user_id=file.user_id, db_file=file, no_summary=True, vector_store=[],
        )
        documents = pipeline.run(PipelineConfig(stop_at=PipelineStage.TRANSFORMER)).documents
        # 重建不重新生成摘要，但必须保留数据库中已经保存的摘要。
        for document in documents:
            document.metadata["abstract"] = file.abstract
        embeddings = LLMService.get_bisheng_knowledge_embedding_sync(
            invoke_user_id=file.user_id, model_id=route.embedding_model_id,
        )
        vectors = embeddings.embed_documents([str(document.page_content or "") for document in documents])
        return SharedSpaceDirectIngestionService._build_chunks(documents, vectors)

    return await asyncio.to_thread(load)

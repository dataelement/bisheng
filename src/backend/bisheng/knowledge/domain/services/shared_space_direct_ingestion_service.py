"""已路由 SPACE 知识库的解析结果直接写入共享存储。"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from langchain_core.documents import Document

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
from bisheng.knowledge.domain.contracts.shared_space_storage import (
    ContentProjectionIdentity,
    ContentUpsertRequest,
    MembershipUpdateRequest,
    SharedContentChunk,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
    KnowledgeDocumentDistributionService,
    SharedContentIngestionTarget,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
    KnowledgeDocumentPermissionActivationService,
)
from bisheng.knowledge.rag.shared_space_storage import (
    TenantRoutingSnapshot,
    build_shared_space_components_for_tenant,
    tenant_target_embedding_model_id,
)
from bisheng.llm.domain import LLMService
from bisheng.utils.async_utils import run_async_safe

logger = logging.getLogger(__name__)


class SharedSpaceDirectIngestionService:
    """将解析切片直接写入租户绑定的共享存储。"""

    @staticmethod
    def _build_chunks(
        documents: Sequence[Document],
        vectors: Sequence[Sequence[float]],
    ) -> tuple[SharedContentChunk, ...]:
        if len(documents) != len(vectors):
            raise ValueError("embedding result count does not match parsed chunks")
        chunks: list[SharedContentChunk] = []
        seen_indexes: set[int] = set()
        for offset, (document, vector) in enumerate(zip(documents, vectors, strict=True)):
            metadata = dict(document.metadata or {})
            raw_index = metadata.get("chunk_index")
            chunk_index = offset if raw_index is None else int(raw_index)
            if chunk_index in seen_indexes:
                raise ValueError(f"duplicate parsed chunk_index {chunk_index}")
            seen_indexes.add(chunk_index)
            metadata.pop("tenant_id", None)
            chunks.append(
                SharedContentChunk(
                    chunk_index=chunk_index,
                    text=str(document.page_content or ""),
                    vector=list(vector),
                    metadata=metadata,
                )
            )
        return tuple(chunks)

    @staticmethod
    def _distribution_service(session) -> KnowledgeDocumentDistributionService:
        file_repository = KnowledgeFileRepositoryImpl(session)
        return KnowledgeDocumentDistributionService(
            session=session,
            document_repository=KnowledgeDocumentRepositoryImpl(session),
            version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
            file_repository=file_repository,
            permission_activation_service=(
                KnowledgeDocumentPermissionActivationService(file_repository=file_repository)
            ),
        )

    @classmethod
    async def _prepare_target(
        cls,
        *,
        tenant_id: int,
        file_id: int,
    ) -> SharedContentIngestionTarget:
        async with get_async_db_session() as session:
            return await cls._distribution_service(session).prepare_shared_content_ingestion(
                tenant_id=tenant_id,
                source_file_id=file_id,
            )

    @classmethod
    async def _finalize_target(
        cls,
        *,
        target: SharedContentIngestionTarget,
    ) -> None:
        async with get_async_db_session() as session:
            await cls._distribution_service(session).finalize_shared_content_ingestion(target=target)

    @classmethod
    async def _write_and_finalize(
        cls,
        *,
        writer,
        target: SharedContentIngestionTarget,
        chunks: tuple[SharedContentChunk, ...],
        embedding_model_id: int,
    ) -> None:
        await writer.upsert_content(
            ContentUpsertRequest(
                identity=ContentProjectionIdentity(
                    tenant_id=target.tenant_id,
                    canonical_document_id=target.canonical_document_id,
                    canonical_version_id=target.canonical_version_id,
                    content_file_id=target.content_file_id,
                    content_generation=target.content_generation,
                    embedding_model_id=str(embedding_model_id),
                ),
                knowledge_ids=target.knowledge_ids,
                chunks=chunks,
            )
        )
        await writer.update_membership(
            MembershipUpdateRequest(
                tenant_id=target.tenant_id,
                canonical_document_id=target.canonical_document_id,
                knowledge_ids=target.knowledge_ids,
                membership_generation=target.membership_generation,
                content_generation=target.content_generation,
            )
        )
        await cls._finalize_target(target=target)

    @classmethod
    def ingest_documents_sync(
        cls,
        *,
        knowledge: Knowledge,
        file_record: KnowledgeFile,
        documents: Sequence[Document],
        routing: TenantRoutingSnapshot,
    ) -> None:
        """完成单文件向量化与持久化。整个过程不访问旧存储。"""
        if not documents:
            raise ValueError("shared ingestion received no parsed chunks")
        tenant_id = int(file_record.tenant_id or knowledge.tenant_id or 0)
        if tenant_id <= 0 or int(routing.tenant_id) != tenant_id:
            raise ValueError("shared ingestion tenant routing mismatch")

        embedding_model_id = tenant_target_embedding_model_id(routing)
        embeddings = LLMService.get_bisheng_knowledge_embedding_sync(
            invoke_user_id=int(file_record.updater_id or file_record.user_id or 0),
            model_id=embedding_model_id,
        )
        vectors = embeddings.embed_documents([str(document.page_content or "") for document in documents])
        chunks = cls._build_chunks(documents, vectors)
        dimension = len(chunks[0].vector or ())
        if dimension <= 0:
            raise ValueError("shared ingestion embedding dimension is empty")

        target = run_async_safe(
            cls._prepare_target(tenant_id=tenant_id, file_id=int(file_record.id)),
            timeout=None,
        )
        components = build_shared_space_components_for_tenant(
            tenant_id,
            embedding_dimension=dimension,
        )
        if components is None:
            raise SharedStorageContractError(
                SharedStorageErrorCode.ROUTING_NOT_CONFIGURED,
                "shared routing disappeared before direct ingestion",
                tenant_id=tenant_id,
            )
        writer, _reader = components
        run_async_safe(
            cls._write_and_finalize(
                writer=writer,
                target=target,
                chunks=chunks,
                embedding_model_id=embedding_model_id,
            ),
            timeout=None,
        )
        logger.info(
            "shared direct ingestion completed tenant_id=%s file_id=%s document_id=%s generation=%s chunks=%s",
            tenant_id,
            file_record.id,
            target.canonical_document_id,
            target.content_generation,
            len(chunks),
        )

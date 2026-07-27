"""KnowledgeDocumentRepository implementation."""
from typing import List, Optional

from sqlmodel import col, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)


class KnowledgeDocumentRepositoryImpl(
    BaseRepositoryImpl[KnowledgeDocument, int], KnowledgeDocumentRepository
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeDocument)

    async def find_by_id(self, entity_id: int) -> Optional[KnowledgeDocument]:
        # Override: use populate_existing so reads after bulk UPDATE statements
        # (e.g. update_primary_version_id) return fresh data from the DB instead
        # of a stale expired instance from the SQLAlchemy identity map.
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.id == entity_id)
        result = await self.session.execute(stmt.execution_options(populate_existing=True))
        return result.scalars().first()

    async def find_by_knowledge_id(self, knowledge_id: int) -> List[KnowledgeDocument]:
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.knowledge_id == knowledge_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_id_for_update(
        self,
        entity_id: int,
    ) -> Optional[KnowledgeDocument]:
        stmt = (
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == entity_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def find_by_ids_for_update(
        self,
        entity_ids: list[int],
    ) -> List[KnowledgeDocument]:
        if not entity_ids:
            return []
        stmt = (
            select(KnowledgeDocument)
            .where(col(KnowledgeDocument.id).in_(sorted(set(entity_ids))))
            .order_by(KnowledgeDocument.id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_in_folder(
        self, knowledge_id: int, file_level_path: Optional[str]
    ) -> List[KnowledgeDocument]:
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.knowledge_id == knowledge_id,
            KnowledgeDocument.file_level_path == file_level_path,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_primary_version_id(
        self, document_id: int, primary_version_id: Optional[int]
    ) -> None:
        stmt = (
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .values(primary_version_id=primary_version_id)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def increment_content_generation(self, document_id: int) -> int:
        document = await self.find_by_id_for_update(document_id)
        if document is None:
            raise ValueError(f"KnowledgeDocument {document_id} does not exist")
        document.content_generation += 1
        self.session.add(document)
        await self.session.flush()
        return document.content_generation

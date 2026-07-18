"""KnowledgeDocumentVersionRepository implementation."""
from typing import List, Optional

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)


class KnowledgeDocumentVersionRepositoryImpl(
    BaseRepositoryImpl[KnowledgeDocumentVersion, int],
    KnowledgeDocumentVersionRepository,
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeDocumentVersion)

    async def find_by_document_id(self, document_id: int) -> List[KnowledgeDocumentVersion]:
        stmt = (
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document_id)
            .order_by(KnowledgeDocumentVersion.version_no)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_primary(self, document_id: int) -> Optional[KnowledgeDocumentVersion]:
        stmt = select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.document_id == document_id,
            KnowledgeDocumentVersion.is_primary == True,  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def find_by_knowledge_file_id(
        self, knowledge_file_id: int
    ) -> Optional[KnowledgeDocumentVersion]:
        stmt = select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.knowledge_file_id == knowledge_file_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def next_version_no(self, document_id: int) -> int:
        stmt = select(func.max(KnowledgeDocumentVersion.version_no)).where(
            KnowledgeDocumentVersion.document_id == document_id
        )
        result = await self.session.execute(stmt)
        current_max = result.scalar()
        if current_max is None:
            return 1
        return int(current_max) + 1

    async def find_non_primary_file_ids(
        self, document_ids: Optional[List[int]] = None
    ) -> List[int]:
        stmt = select(KnowledgeDocumentVersion.knowledge_file_id).where(
            KnowledgeDocumentVersion.is_primary == False,  # noqa: E712
        )
        if document_ids is not None:
            stmt = stmt.where(col(KnowledgeDocumentVersion.document_id).in_(document_ids))
        result = await self.session.execute(stmt)
        return [int(row) for row in result.scalars().all()]

    async def find_primary_versions_by_file_ids(
        self, file_ids: List[int]
    ) -> List[KnowledgeDocumentVersion]:
        """Return primary version rows for the given file ids.

        Each returned row corresponds to one visible page item.  We filter on
        is_primary=True so we only pull the row that is currently shown, and
        we can look up version_no for each file in O(1) after loading.
        """
        if not file_ids:
            return []
        stmt = select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.is_primary == True,  # noqa: E712
            col(KnowledgeDocumentVersion.knowledge_file_id).in_(file_ids),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_non_primary_file_ids_by_knowledge_ids(
        self, knowledge_ids: List[int]
    ) -> List[int]:
        """Return knowledge_file_id of all non-primary version rows whose
        parent document belongs to any of the given knowledge_ids.

        Empty knowledge_ids -> []. JOINs knowledge_document on document_id.
        """
        if not knowledge_ids:
            return []
        stmt = (
            select(KnowledgeDocumentVersion.knowledge_file_id)
            .join(
                KnowledgeDocument,
                KnowledgeDocumentVersion.document_id == KnowledgeDocument.id,
            )
            .where(
                KnowledgeDocumentVersion.is_primary == False,  # noqa: E712
                col(KnowledgeDocument.knowledge_id).in_(knowledge_ids),
            )
        )
        result = await self.session.execute(stmt)
        return [int(row) for row in result.scalars().all()]

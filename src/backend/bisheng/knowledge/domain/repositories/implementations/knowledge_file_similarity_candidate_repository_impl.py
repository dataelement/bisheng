"""KnowledgeFileSimilarityCandidateRepository implementation."""

from sqlalchemy import delete, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import (
    KnowledgeFileSimilarityCandidate,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_similarity_candidate_repository import (
    KnowledgeFileSimilarityCandidateRepository,
)


class KnowledgeFileSimilarityCandidateRepositoryImpl(
    BaseRepositoryImpl[KnowledgeFileSimilarityCandidate, int],
    KnowledgeFileSimilarityCandidateRepository,
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeFileSimilarityCandidate)

    async def find_by_source_file_id(
        self,
        source_file_id: int,
        *,
        limit: int | None = None,
    ) -> list[KnowledgeFileSimilarityCandidate]:
        stmt = (
            select(KnowledgeFileSimilarityCandidate)
            .where(KnowledgeFileSimilarityCandidate.source_file_id == source_file_id)
            .order_by(
                KnowledgeFileSimilarityCandidate.sort_order,
                KnowledgeFileSimilarityCandidate.similarity.desc(),
            )
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_source_file_ids(
        self,
        source_file_ids: list[int],
    ) -> list[KnowledgeFileSimilarityCandidate]:
        if not source_file_ids:
            return []
        stmt = (
            select(KnowledgeFileSimilarityCandidate)
            .where(col(KnowledgeFileSimilarityCandidate.source_file_id).in_(source_file_ids))
            .order_by(
                KnowledgeFileSimilarityCandidate.source_file_id,
                KnowledgeFileSimilarityCandidate.sort_order,
                KnowledgeFileSimilarityCandidate.similarity.desc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_actionable_source_file_ids(
        self,
        source_file_ids: list[int],
    ) -> set[int]:
        if not source_file_ids:
            return set()
        source_file = aliased(KnowledgeFile)
        candidate_file = aliased(KnowledgeFile)
        primary_version = aliased(KnowledgeDocumentVersion)
        all_versions = aliased(KnowledgeDocumentVersion)
        stmt = (
            select(KnowledgeFileSimilarityCandidate.source_file_id)
            .join(
                source_file,
                source_file.id == KnowledgeFileSimilarityCandidate.source_file_id,
            )
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeFileSimilarityCandidate.candidate_document_id,
            )
            .join(
                primary_version,
                primary_version.id == KnowledgeDocument.primary_version_id,
            )
            .join(
                candidate_file,
                candidate_file.id == primary_version.knowledge_file_id,
            )
            .join(all_versions, all_versions.document_id == KnowledgeDocument.id)
            .where(
                col(KnowledgeFileSimilarityCandidate.source_file_id).in_(source_file_ids),
                KnowledgeFileSimilarityCandidate.knowledge_id == source_file.knowledge_id,
                KnowledgeDocument.knowledge_id == source_file.knowledge_id,
                primary_version.knowledge_file_id == KnowledgeFileSimilarityCandidate.candidate_file_id,
                candidate_file.file_type == FileType.FILE.value,
                candidate_file.status == KnowledgeFileStatus.SUCCESS.value,
            )
            .group_by(
                KnowledgeFileSimilarityCandidate.source_file_id,
                KnowledgeFileSimilarityCandidate.candidate_document_id,
            )
            .having(func.count(all_versions.id) == 1)
        )
        result = await self.session.execute(stmt)
        return {int(source_file_id) for source_file_id in result.scalars().all()}

    async def replace_for_source_file(
        self,
        source_file_id: int,
        candidates: list[KnowledgeFileSimilarityCandidate],
    ) -> list[KnowledgeFileSimilarityCandidate]:
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                return await self._replace_for_source_file_once(source_file_id, candidates)
            except IntegrityError:
                await self.session.rollback()
                if attempt + 1 >= max_attempts:
                    raise
                for candidate in candidates:
                    candidate.id = None
        return candidates

    async def _replace_for_source_file_once(
        self,
        source_file_id: int,
        candidates: list[KnowledgeFileSimilarityCandidate],
    ) -> list[KnowledgeFileSimilarityCandidate]:
        await self.session.execute(select(KnowledgeFile.id).where(KnowledgeFile.id == source_file_id).with_for_update())
        await self.session.execute(
            delete(KnowledgeFileSimilarityCandidate).where(
                KnowledgeFileSimilarityCandidate.source_file_id == source_file_id
            )
        )
        if candidates:
            self.session.add_all(candidates)
        await self.session.commit()
        for candidate in candidates:
            await self.session.refresh(candidate)
        return candidates

    async def delete_by_source_file_id(self, source_file_id: int) -> int:
        result = await self.session.execute(
            delete(KnowledgeFileSimilarityCandidate).where(
                KnowledgeFileSimilarityCandidate.source_file_id == source_file_id
            )
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    async def delete_by_file_ids(self, file_ids: list[int]) -> int:
        if not file_ids:
            return 0
        result = await self.session.execute(
            delete(KnowledgeFileSimilarityCandidate).where(
                or_(
                    col(KnowledgeFileSimilarityCandidate.source_file_id).in_(file_ids),
                    col(KnowledgeFileSimilarityCandidate.candidate_file_id).in_(file_ids),
                )
            )
        )
        await self.session.commit()
        return int(result.rowcount or 0)

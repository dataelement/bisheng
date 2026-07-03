"""KnowledgeFileSimilarityCandidateRepository implementation."""

from sqlalchemy import delete, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
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
        await self.session.execute(
            select(KnowledgeFile.id)
            .where(KnowledgeFile.id == source_file_id)
            .with_for_update()
        )
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

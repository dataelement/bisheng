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
        """Source files with at least one candidate the user can still act on.

        A candidate counts when its document still points at the file the scan
        matched (the primary version) and that file is a parsed, non-folder
        entry. How many versions the target document already has is not part of
        it: linking accepts a versioned target, so excluding one here only hid
        the badge on work the user could have done.
        """
        if not source_file_ids:
            return set()
        from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
            KnowledgeFileRepositoryImpl,
        )

        rows = await self.find_by_source_file_ids(source_file_ids)
        ids = sorted({value for row in rows for value in (row.source_file_id, row.candidate_file_id)})
        files = KnowledgeFileRepositoryImpl(self.session)
        contexts = {}
        for start in range(0, len(ids), 500):
            contexts.update(await files.resolve_similarity_files(ids[start : start + 500]))
        actionable = set()
        for row in rows:
            source, candidate = contexts.get(row.source_file_id), contexts.get(row.candidate_file_id)
            if (
                source is None
                or candidate is None
                or not source.valid
                or not candidate.valid
                or candidate.document is None
            ):
                continue
            if source.entry.knowledge_id != row.knowledge_id or candidate.entry.knowledge_id != row.knowledge_id:
                continue
            if (
                source.entry.tenant_id != candidate.entry.tenant_id
                or candidate.document.id != row.candidate_document_id
            ):
                continue
            if source.document is not None and source.document.id == candidate.document.id:
                continue
            if source.cached_with(candidate):
                actionable.add(row.source_file_id)
        return actionable

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

"""Repository interface for persisted file similarity candidates."""

from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import (
    KnowledgeFileSimilarityCandidate,
)


class KnowledgeFileSimilarityCandidateRepository(
    BaseRepository[KnowledgeFileSimilarityCandidate, int],
    ABC,
):
    """Repository for cached similarity candidates."""

    @abstractmethod
    async def find_by_source_file_id(
        self,
        source_file_id: int,
        *,
        limit: int | None = None,
    ) -> list[KnowledgeFileSimilarityCandidate]:
        """Return cached candidates for one source file."""

    @abstractmethod
    async def find_by_source_file_ids(
        self,
        source_file_ids: list[int],
    ) -> list[KnowledgeFileSimilarityCandidate]:
        """Return cached candidates for multiple source files."""

    @abstractmethod
    async def find_actionable_source_file_ids(
        self,
        source_file_ids: list[int],
    ) -> set[int]:
        """Return source file IDs that have at least one merge-actionable candidate."""

    @abstractmethod
    async def replace_for_source_file(
        self,
        source_file_id: int,
        candidates: list[KnowledgeFileSimilarityCandidate],
    ) -> list[KnowledgeFileSimilarityCandidate]:
        """Replace all cached candidates for one source file."""

    @abstractmethod
    async def delete_by_source_file_id(self, source_file_id: int) -> int:
        """Delete cached candidates for one source file."""

    @abstractmethod
    async def delete_by_file_ids(self, file_ids: list[int]) -> int:
        """Delete rows where any listed file is the source or candidate."""

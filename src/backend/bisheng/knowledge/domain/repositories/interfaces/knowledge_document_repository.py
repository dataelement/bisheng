"""KnowledgeDocument repository interface."""
from abc import ABC, abstractmethod
from typing import List, Optional

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument


class KnowledgeDocumentRepository(BaseRepository[KnowledgeDocument, int], ABC):
    """Repository for logical documents (the anchor of a version chain)."""

    @abstractmethod
    async def find_by_knowledge_id(self, knowledge_id: int) -> List[KnowledgeDocument]:
        """List all documents in a knowledge space."""

    @abstractmethod
    async def find_by_id_for_update(
        self,
        entity_id: int,
    ) -> Optional[KnowledgeDocument]:
        """Lock one document row for a distribution state transition."""

    @abstractmethod
    async def find_by_ids_for_update(
        self,
        entity_ids: list[int],
    ) -> List[KnowledgeDocument]:
        """Lock document rows in stable ID order."""

    @abstractmethod
    async def find_in_folder(
        self, knowledge_id: int, file_level_path: Optional[str]
    ) -> List[KnowledgeDocument]:
        """List documents under a specific folder (None = root)."""

    @abstractmethod
    async def update_primary_version_id(
        self, document_id: int, primary_version_id: Optional[int]
    ) -> None:
        """Update the primary pointer and flush without committing."""

    @abstractmethod
    async def increment_content_generation(self, document_id: int) -> int:
        """Lock the document, increment its content generation, and flush."""

"""KnowledgeDocumentVersion repository interface."""
from abc import ABC, abstractmethod
from typing import List, Optional

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion


class KnowledgeDocumentVersionRepository(
    BaseRepository[KnowledgeDocumentVersion, int], ABC
):
    """Repository for version rows inside a logical document."""

    @abstractmethod
    async def find_by_document_id(self, document_id: int) -> List[KnowledgeDocumentVersion]:
        """List all versions of a logical document, ordered by version_no asc."""

    @abstractmethod
    async def find_primary(self, document_id: int) -> Optional[KnowledgeDocumentVersion]:
        """Return the current primary version of a logical document."""

    @abstractmethod
    async def find_by_knowledge_file_id(
        self, knowledge_file_id: int
    ) -> Optional[KnowledgeDocumentVersion]:
        """Locate the version row of a given physical file (1:1)."""

    @abstractmethod
    async def next_version_no(self, document_id: int) -> int:
        """Return the next version_no for a document (max+1, or 1 if empty)."""

    @abstractmethod
    async def find_non_primary_file_ids(
        self, document_ids: Optional[List[int]] = None
    ) -> List[int]:
        """File ids of all non-primary versions. If document_ids is given, restrict to those documents."""

    @abstractmethod
    async def find_primary_versions_by_file_ids(
        self, file_ids: List[int]
    ) -> List[KnowledgeDocumentVersion]:
        """Return primary version rows whose knowledge_file_id is in file_ids.

        Used by list_space_children to enrich page items with version_no and
        is_multi_version.  Only rows with is_primary=True are returned so the
        caller can quickly look up version metadata for each visible file.
        """

    @abstractmethod
    async def find_non_primary_file_ids_by_knowledge_ids(
        self, knowledge_ids: List[int]
    ) -> List[int]:
        """Return knowledge_file_id of all non-primary version rows whose
        parent document belongs to any of the given knowledge_ids.

        Empty knowledge_ids -> []. JOINs knowledge_document on document_id.
        """

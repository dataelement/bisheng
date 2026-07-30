from abc import ABC, abstractmethod

from bisheng.citation.domain.models.message_citation import MessageCitation, MessageCitationRelation
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class MessageCitationRepository(BaseRepository[MessageCitation, int], ABC):
    """Repository interface for accessing message citation records."""

    @abstractmethod
    async def find_by_message_id(self, message_id: int) -> list[MessageCitation]:
        """Find all citations for a single message."""
        pass

    @abstractmethod
    async def find_by_citation_id(self, citation_id: str) -> MessageCitation | None:
        """Find one citation by its business citation ID."""
        pass

    @abstractmethod
    async def bulk_create(self, citations: list[MessageCitation]) -> list[MessageCitation]:
        """Create citations in batch."""
        pass

    @abstractmethod
    async def ensure_citations(self, citations: list[MessageCitation]) -> list[MessageCitation]:
        """Return globally stored citations, creating only missing IDs."""
        pass

    @abstractmethod
    async def ensure_relations(
        self,
        relations: list[MessageCitationRelation],
    ) -> list[MessageCitationRelation]:
        """Idempotently associate citations with messages."""
        pass

    @abstractmethod
    async def find_by_citation_ids(self, citation_ids: list[str]) -> list[MessageCitation]:
        """Find citations by multiple business citation IDs."""
        pass

    @abstractmethod
    async def find_by_message_ids_grouped(self, message_ids: list[int]) -> dict[int, list[MessageCitation]]:
        """Find citations for multiple messages and group them by message ID."""
        pass

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from bisheng.citation.domain.models.message_citation import MessageCitation
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class MessageCitationRepository(BaseRepository[MessageCitation, int], ABC):
    """Repository interface for accessing message citation records."""

    @abstractmethod
    async def find_by_message_id(self, message_id: int) -> List[MessageCitation]:
        """Find all citations for a single message."""
        pass

    @abstractmethod
    async def find_by_citation_id(self, citation_id: str) -> Optional[MessageCitation]:
        """Find one citation by its business citation ID."""
        pass

    @abstractmethod
    async def bulk_create(self, citations: List[MessageCitation]) -> List[MessageCitation]:
        """Create citations in batch."""
        pass

    @abstractmethod
    async def find_by_citation_ids(self, citation_ids: List[str]) -> List[MessageCitation]:
        """Find citations by multiple business citation IDs."""
        pass

    @abstractmethod
    async def find_by_message_ids_grouped(self, message_ids: List[int]) -> Dict[int, List[MessageCitation]]:
        """Find citations for multiple messages and group them by message ID."""
        pass

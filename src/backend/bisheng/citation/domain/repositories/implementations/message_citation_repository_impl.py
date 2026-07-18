from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional

from sqlmodel import Session, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.citation.domain.models.message_citation import MessageCitation
from bisheng.citation.domain.repositories.interfaces.message_citation_repository import MessageCitationRepository
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl


class MessageCitationRepositoryImpl(BaseRepositoryImpl[MessageCitation, int], MessageCitationRepository):
    """Repository implementation for message citation records."""

    def __init__(self, session: AsyncSession | Session):
        super().__init__(session, MessageCitation)

    async def find_by_message_id(self, message_id: int) -> List[MessageCitation]:
        """Find all citations for a single message."""
        query = (
            select(MessageCitation)
            .where(MessageCitation.message_id == message_id)
            .order_by(MessageCitation.id.asc())
        )
        result = await self.session.exec(query)
        return list(result.all())

    def find_by_message_id_sync(self, message_id: int) -> List[MessageCitation]:
        """Find all citations for a single message synchronously."""
        query = (
            select(MessageCitation)
            .where(MessageCitation.message_id == message_id)
            .order_by(MessageCitation.id.asc())
        )
        result = self.session.exec(query)
        return list(result.all())

    async def find_by_citation_id(self, citation_id: str) -> Optional[MessageCitation]:
        """Find one citation by its business citation ID."""
        query = select(MessageCitation).where(MessageCitation.citation_id == citation_id)
        result = await self.session.exec(query)
        return result.first()

    async def bulk_create(self, citations: List[MessageCitation]) -> List[MessageCitation]:
        """Create citations in batch."""
        if not citations:
            return []
        return await self.bulk_save(citations)

    def bulk_create_sync(self, citations: List[MessageCitation]) -> List[MessageCitation]:
        """Create citations in batch synchronously."""
        if not citations:
            return []
        return self.bulk_save_sync(citations)

    async def find_by_citation_ids(self, citation_ids: List[str]) -> List[MessageCitation]:
        """Find citations by multiple business citation IDs."""
        if not citation_ids:
            return []

        query = (
            select(MessageCitation)
            .where(col(MessageCitation.citation_id).in_(citation_ids))
            .order_by(MessageCitation.id.asc())
        )
        result = await self.session.exec(query)
        return list(result.all())

    async def find_by_message_ids_grouped(self, message_ids: List[int]) -> Dict[int, List[MessageCitation]]:
        """Find citations for multiple messages and group them by message ID."""
        if not message_ids:
            return {}

        query = (
            select(MessageCitation)
            .where(col(MessageCitation.message_id).in_(message_ids))
            .order_by(MessageCitation.message_id.asc(), MessageCitation.id.asc())
        )
        result = await self.session.exec(query)

        grouped_citations: DefaultDict[int, List[MessageCitation]] = defaultdict(list)
        for citation in result.all():
            grouped_citations[citation.message_id].append(citation)

        return dict(grouped_citations)

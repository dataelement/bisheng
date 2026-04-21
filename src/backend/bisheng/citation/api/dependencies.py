from typing import TYPE_CHECKING

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.citation.domain.repositories.implementations.message_citation_repository_impl import (
    MessageCitationRepositoryImpl,
)
from bisheng.citation.domain.repositories.interfaces.message_citation_repository import MessageCitationRepository
from bisheng.common.dependencies.core_deps import get_db_session

if TYPE_CHECKING:
    from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
    from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService


async def get_message_citation_repository(
    session: AsyncSession = Depends(get_db_session),
) -> MessageCitationRepository:
    """Provide MessageCitationRepository instance."""
    return MessageCitationRepositoryImpl(session)


async def get_citation_registry_service(
    repository: MessageCitationRepository = Depends(get_message_citation_repository),
) -> 'CitationRegistryService':
    """Provide CitationRegistryService instance."""
    from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService

    return CitationRegistryService(repository)


async def get_citation_resolve_service(
    repository: MessageCitationRepository = Depends(get_message_citation_repository),
) -> 'CitationResolveService':
    """Provide CitationResolveService instance."""
    from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService

    return CitationResolveService(repository)

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header
from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.citation.domain.repositories.implementations.message_citation_repository_impl import (
    MessageCitationRepositoryImpl,
)
from bisheng.citation.domain.repositories.interfaces.message_citation_repository import MessageCitationRepository
from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.share_link.domain.repositories.implementations.share_link_repository_impl import (
    ShareLinkRepositoryImpl,
)
from bisheng.share_link.domain.services.share_link_service import ShareLinkService

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
) -> "CitationRegistryService":
    """Provide CitationRegistryService instance."""
    from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService

    return CitationRegistryService(repository)


async def get_citation_resolve_service(
    repository: MessageCitationRepository = Depends(get_message_citation_repository),
) -> "CitationResolveService":
    """Provide CitationResolveService instance."""
    from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService

    return CitationResolveService(repository)


async def get_optional_share_link(
    share_token: Annotated[str | None, Header(alias="share-token")] = None,
    session: AsyncSession = Depends(get_db_session),
) -> ShareLink | None:
    """Resolve an optional share-token header without failing the request.

    An unknown or revoked token means there is no share grant. The caller then
    falls back to the normal owner check. This stays in the citation module so
    the endpoint does not import another module's API layer.
    """
    if not share_token:
        return None
    service = ShareLinkService(share_link_repository=ShareLinkRepositoryImpl(session))
    try:
        return await service.get_share_link_by_token(share_token)
    except NotFoundError:
        logger.debug("share-token header did not resolve to an active share link")
        return None

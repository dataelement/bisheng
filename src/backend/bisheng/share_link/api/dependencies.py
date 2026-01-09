from typing import Annotated, Union

from fastapi import Depends, Header
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.share_link.domain.repositories.implementations.share_link_repository_impl import ShareLinkRepositoryImpl
from bisheng.share_link.domain.repositories.interfaces.share_link_repository import ShareLinkRepository
from bisheng.share_link.domain.services.share_link_service import ShareLinkService


async def get_share_link_repository(
        session: AsyncSession = Depends(get_db_session),
) -> ShareLinkRepository:
    """DapatkanShareLinkRepositoryInstance Dependencies"""
    return ShareLinkRepositoryImpl(session)


async def get_share_link_service(
        share_link_repository: ShareLinkRepository = Depends(get_share_link_repository),
) -> 'ShareLinkService':
    """DapatkanShareLinkServiceInstance Dependencies"""
    return ShareLinkService(share_link_repository=share_link_repository)


# Resolve share links in request headerstokenand return the corresponding sharing link information
async def header_share_token_parser(
        share_token: Annotated[str | None, Header(alias="share-token")] = None,
        share_link_service: ShareLinkService = Depends(get_share_link_service),
) -> Union['ShareLink', None]:
    """According to the request headershare-tokenGet shared link info"""
    if not share_token:
        return None

    share_link = await share_link_service.get_share_link_by_token(share_token)
    return share_link

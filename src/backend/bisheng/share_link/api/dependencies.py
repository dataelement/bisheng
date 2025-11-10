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
    """获取ShareLinkRepository实例的依赖项"""
    return ShareLinkRepositoryImpl(session)


async def get_share_link_service(
        share_link_repository: ShareLinkRepository = Depends(get_share_link_repository),
) -> 'ShareLinkService':
    """获取ShareLinkService实例的依赖项"""
    return ShareLinkService(share_link_repository=share_link_repository)


# 解析请求头中的共享链接token，并返回对应的共享链接信息
async def header_share_token_parser(
        share_token: Annotated[str | None, Header(alias="share-token")] = None,
        share_link_service: ShareLinkService = Depends(get_share_link_service),
) -> Union['ShareLink', None]:
    """根据请求头中的share-token获取共享链接信息"""
    if not share_token:
        return None

    share_link = await share_link_service.get_share_link_by_token(share_token)
    return share_link

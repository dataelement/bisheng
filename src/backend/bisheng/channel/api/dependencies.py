from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import \
    ChannelInfoSourceRepositoryImpl
from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
from bisheng.channel.domain.repositories.interfaces.channel_info_source_repository import ChannelInfoSourceRepository
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.channel.domain.repositories.implementations.article_read_repository_impl import ArticleReadRepositoryImpl
from bisheng.channel.domain.repositories.interfaces.article_read_repository import ArticleReadRepository
from bisheng.common.repositories.implementations.space_channel_member_repository_impl import \
    SpaceChannelMemberRepositoryImpl
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository


async def get_channel_repository(
        session: AsyncSession = Depends(get_db_session),
) -> ChannelRepository:
    """Adaptation ChannelRepositoryInstance Dependencies"""
    return ChannelRepositoryImpl(session)


async def get_space_channel_member_repository(
        session: AsyncSession = Depends(get_db_session),
) -> 'SpaceChannelMemberRepository':
    """Adaptation SpaceChannelMemberRepositoryInstance Dependencies"""
    return SpaceChannelMemberRepositoryImpl(session)


async def get_channel_info_source_repository(
        session: AsyncSession = Depends(get_db_session),
) -> 'ChannelInfoSourceRepository':
    """Adaptation ChannelInfoSourceRepository Dependencies"""
    return ChannelInfoSourceRepositoryImpl(session)


def get_article_es_service() -> ArticleEsService:
    """Get ArticleEsService instance"""
    return ArticleEsService()

async def get_article_read_repository(
        session: AsyncSession = Depends(get_db_session),
) -> ArticleReadRepository:
    """Adaptation ArticleReadRepository Dependencies"""
    return ArticleReadRepositoryImpl(session)


async def get_channel_service(
        session: AsyncSession = Depends(get_db_session),
) -> 'ChannelService':
    """Adaptation ChannelServiceInstance Dependencies"""

    channel_repository = await get_channel_repository(session)
    space_channel_member_repository = await get_space_channel_member_repository(session)
    channel_info_source_repository = await get_channel_info_source_repository(session)
    article_es_service = get_article_es_service()
    article_read_repository = await get_article_read_repository(session)

    return ChannelService(
        channel_repository=channel_repository,
        space_channel_member_repository=space_channel_member_repository,
        channel_info_source_repository=channel_info_source_repository,
        article_es_service=article_es_service,
        article_read_repository=article_read_repository,
    )


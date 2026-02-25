from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.core_deps import get_db_session
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


async def get_channel_service(
        channel_repository: ChannelRepository = Depends(get_channel_repository),
        space_channel_member_repository: SpaceChannelMemberRepository = Depends(get_space_channel_member_repository)
) -> 'ChannelService':
    """Adaptation ChannelServiceInstance Dependencies"""
    from bisheng.channel.domain.services.channel_service import ChannelService
    return ChannelService(channel_repository=channel_repository,
                          space_channel_member_repository=space_channel_member_repository)

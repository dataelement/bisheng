from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.services.channel_subscribe_approval_handler import ChannelSubscribeApprovalHandler
from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.repositories.implementations.space_channel_member_repository_impl import SpaceChannelMemberRepositoryImpl
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository
from bisheng.message.domain.repositories.implementations.inbox_message_repository_impl import \
    InboxMessageRepositoryImpl
from bisheng.message.domain.repositories.implementations.inbox_message_read_repository_impl import \
    InboxMessageReadRepositoryImpl
from bisheng.message.domain.repositories.interfaces.inbox_message_repository import InboxMessageRepository
from bisheng.message.domain.repositories.interfaces.inbox_message_read_repository import InboxMessageReadRepository
from bisheng.message.domain.services.message_service import MessageService


async def get_inbox_message_repository(
        session: AsyncSession = Depends(get_db_session),
) -> InboxMessageRepository:
    """Provide InboxMessageRepository instance."""
    return InboxMessageRepositoryImpl(session)


async def get_inbox_message_read_repository(
        session: AsyncSession = Depends(get_db_session),
) -> InboxMessageReadRepository:
    """Provide InboxMessageReadRepository instance."""
    return InboxMessageReadRepositoryImpl(session)


async def get_space_channel_member_repository(
        session: AsyncSession = Depends(get_db_session),
) -> SpaceChannelMemberRepository:
    """Provide SpaceChannelMemberRepository instance."""
    return SpaceChannelMemberRepositoryImpl(session)


async def get_message_service(
        session: AsyncSession = Depends(get_db_session),
) -> MessageService:
    """Provide MessageService instance with all dependencies."""
    message_repository = await get_inbox_message_repository(session)
    message_read_repository = await get_inbox_message_read_repository(session)
    space_channel_member_repository = await get_space_channel_member_repository(session)

    message_service: MessageService

    async def notify_sender(
            sender: int,
            text: str,
            receiver_user_ids: list[int],
            content_type: str = "text",
    ):
        return await message_service.send_generic_notify(
            sender=sender,
            text=text,
            receiver_user_ids=receiver_user_ids,
            content_type=content_type,
        )

    channel_subscribe_handler = ChannelSubscribeApprovalHandler(
        space_channel_member_repository=space_channel_member_repository,
        notify_sender=notify_sender,
    )

    message_service = MessageService(
        message_repository=message_repository,
        message_read_repository=message_read_repository,
        approval_handlers=[channel_subscribe_handler],
    )

    return message_service

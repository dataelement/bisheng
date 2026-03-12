from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
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


async def get_message_service(
        session: AsyncSession = Depends(get_db_session),
) -> MessageService:
    """Provide MessageService instance with all dependencies."""
    message_repository = await get_inbox_message_repository(session)
    message_read_repository = await get_inbox_message_read_repository(session)

    return MessageService(
        message_repository=message_repository,
        message_read_repository=message_read_repository,
    )

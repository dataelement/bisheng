import logging
from typing import List, Optional

from sqlalchemy import func, or_, JSON
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.message.domain.models.inbox_message import InboxMessage, MessageStatusEnum, MessageTypeEnum
from bisheng.message.domain.repositories.interfaces.inbox_message_repository import InboxMessageRepository

logger = logging.getLogger(__name__)


class InboxMessageRepositoryImpl(BaseRepositoryImpl[InboxMessage, int], InboxMessageRepository):
    """Inbox Message repository implementation."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, InboxMessage)

    def _apply_receiver_filter(self, query, user_id: int):
        """Apply JSON_CONTAINS filter for the receiver field."""
        return query.where(
            func.json_contains(InboxMessage.receiver, str(user_id))
        )

    async def find_messages_by_receiver(
        self,
        user_id: int,
        message_type: Optional[MessageTypeEnum] = None,
        status: Optional[MessageStatusEnum] = None,
        keyword: Optional[str] = None,
        only_unread: bool = False,
        read_message_ids: Optional[List[int]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[InboxMessage]:
        """Find messages by receiver user ID with optional filters and pagination."""
        query = select(InboxMessage)

        # Filter by receiver using JSON_CONTAINS
        query = self._apply_receiver_filter(query, user_id)

        if message_type is not None:
            query = query.where(InboxMessage.message_type == message_type)

        if status is not None:
            query = query.where(InboxMessage.status == status)

        if keyword:
            like_pattern = f'%{keyword}%'
            # Search in JSON content field - use raw SQL cast for JSON search
            query = query.where(
                func.cast(InboxMessage.content, func.text()).like(like_pattern)
            )

        # Filter only unread messages by excluding read message IDs
        if only_unread and read_message_ids:
            query = query.where(col(InboxMessage.id).notin_(read_message_ids))
        elif only_unread and not read_message_ids:
            # All messages are unread if no read IDs provided, no extra filter needed
            pass

        # Sort: unread first (by excluding read IDs), then by create_time desc
        query = query.order_by(InboxMessage.create_time.desc())

        # Pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.session.exec(query)
        return list(result.all())

    async def count_messages_by_receiver(
        self,
        user_id: int,
        message_type: Optional[MessageTypeEnum] = None,
        status: Optional[MessageStatusEnum] = None,
        keyword: Optional[str] = None,
        only_unread: bool = False,
        read_message_ids: Optional[List[int]] = None,
    ) -> int:
        """Count messages by receiver user ID with optional filters."""
        query = select(func.count()).select_from(InboxMessage)

        query = self._apply_receiver_filter(query, user_id)

        if message_type is not None:
            query = query.where(InboxMessage.message_type == message_type)

        if status is not None:
            query = query.where(InboxMessage.status == status)

        if keyword:
            like_pattern = f'%{keyword}%'
            query = query.where(
                func.cast(InboxMessage.content, func.text()).like(like_pattern)
            )

        if only_unread and read_message_ids:
            query = query.where(col(InboxMessage.id).notin_(read_message_ids))

        result = await self.session.exec(query)
        return result.one()

    async def count_unread_by_receiver(
        self,
        user_id: int,
        read_message_ids: Optional[List[int]] = None,
        message_type: Optional[MessageTypeEnum] = None,
    ) -> int:
        """Count unread messages for a specific user."""
        query = select(func.count()).select_from(InboxMessage)

        query = self._apply_receiver_filter(query, user_id)

        if message_type is not None:
            query = query.where(InboxMessage.message_type == message_type)

        # Exclude read messages
        if read_message_ids:
            query = query.where(col(InboxMessage.id).notin_(read_message_ids))

        result = await self.session.exec(query)
        return result.one()

    async def update_message_after_approval(
        self,
        message_id: int,
        status: MessageStatusEnum,
        content: list,
        operator_user_id: int,
    ) -> Optional[InboxMessage]:
        """Atomically update message status, content, and operator after approval action."""
        message = await self.find_by_id(message_id)
        if not message:
            return None
        message.status = status
        message.content = content
        message.operator_user_id = operator_user_id
        return await self.update(message)

    async def update_message_content(
        self,
        message_id: int,
        content: list,
    ) -> Optional[InboxMessage]:
        """Update message content (e.g., after approval_id backfill)."""
        message = await self.find_by_id(message_id)
        if not message:
            return None
        message.content = content
        return await self.update(message)

    async def get_all_message_ids_by_receiver(
        self,
        user_id: int,
    ) -> List[int]:
        """Get all message IDs where the user is a receiver, using JSON_CONTAINS."""
        query = select(InboxMessage.id)
        query = self._apply_receiver_filter(query, user_id)
        result = await self.session.exec(query)
        return list(result.all())

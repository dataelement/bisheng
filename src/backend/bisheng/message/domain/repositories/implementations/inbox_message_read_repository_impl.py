import logging
from typing import List

from sqlalchemy import func
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.message.domain.models.inbox_message_read import InboxMessageRead
from bisheng.message.domain.repositories.interfaces.inbox_message_read_repository import InboxMessageReadRepository

logger = logging.getLogger(__name__)


class InboxMessageReadRepositoryImpl(BaseRepositoryImpl[InboxMessageRead, int], InboxMessageReadRepository):
    """Inbox Message Read repository implementation."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, InboxMessageRead)

    async def mark_as_read(self, message_id: int, user_id: int) -> InboxMessageRead:
        """Mark a message as read for a specific user. Idempotent - skips if already read."""
        existing = await self.find_one(message_id=message_id, user_id=user_id)
        if existing:
            return existing

        record = InboxMessageRead(message_id=message_id, user_id=user_id)
        return await self.save(record)

    async def batch_mark_as_read(self, message_ids: List[int], user_id: int) -> int:
        """Batch mark messages as read. Returns number of newly marked records."""
        if not message_ids:
            return 0

        # Find which messages are already read
        query = select(InboxMessageRead.message_id).where(
            InboxMessageRead.user_id == user_id,
            col(InboxMessageRead.message_id).in_(message_ids)
        )
        result = await self.session.exec(query)
        already_read_ids = set(result.all())

        # Create records for unread messages only
        new_records = []
        for msg_id in message_ids:
            if msg_id not in already_read_ids:
                new_records.append(InboxMessageRead(message_id=msg_id, user_id=user_id))

        if new_records:
            self.session.add_all(new_records)
            await self.session.commit()

        return len(new_records)

    async def is_read(self, message_id: int, user_id: int) -> bool:
        """Check if a message has been read by a specific user."""
        existing = await self.find_one(message_id=message_id, user_id=user_id)
        return existing is not None

    async def get_read_message_ids(self, user_id: int) -> List[int]:
        """Get all read message IDs for a specific user."""
        query = select(InboxMessageRead.message_id).where(
            InboxMessageRead.user_id == user_id
        )
        result = await self.session.exec(query)
        return list(result.all())

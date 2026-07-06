import logging

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
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
        try:
            return await self.save(record)
        except IntegrityError:
            # A concurrent request inserted the same (message_id, user_id) between
            # our find_one and save, tripping the ix_inbox_message_read_msg_user
            # unique index. Roll back and return the row that won the race so
            # marking-as-read stays idempotent instead of surfacing a 500.
            await self.session.rollback()
            existing = await self.find_one(message_id=message_id, user_id=user_id)
            if existing:
                return existing
            raise  # not a duplicate-key race — a real failure, surface it

    async def batch_mark_as_read(self, message_ids: list[int], user_id: int) -> int:
        """Batch mark messages as read. Returns number of newly marked records.

        Idempotent under concurrency: if a competing request inserts the same
        (message_id, user_id) in the SELECT->INSERT window, one unique-constraint
        conflict would otherwise roll back the *whole* batch (leaving every
        message unread and 500ing the API). Instead we roll back, re-read what
        now exists and insert only the still-missing ids. Same dialect-agnostic
        pattern as ChannelInfoSourceRepositoryImpl.batch_add.
        """
        if not message_ids:
            return 0

        new_records = await self._build_unread_records(message_ids, user_id)
        if not new_records:
            return 0

        try:
            self.session.add_all(new_records)
            await self.session.commit()
            return len(new_records)
        except IntegrityError:
            await self.session.rollback()
            remaining = await self._build_unread_records(message_ids, user_id)
            if remaining:
                self.session.add_all(remaining)
                await self.session.commit()
            return len(remaining)

    async def _build_unread_records(self, message_ids: list[int], user_id: int) -> list[InboxMessageRead]:
        """Build read-records for ids not yet read by the user.

        Dedupes the input (``dict.fromkeys`` preserves order) so duplicate ids in
        a single request cannot self-collide on the unique index.
        """
        query = select(InboxMessageRead.message_id).where(
            InboxMessageRead.user_id == user_id,
            col(InboxMessageRead.message_id).in_(message_ids),
        )
        result = await self.session.exec(query)
        already_read_ids = set(result.all())

        return [
            InboxMessageRead(message_id=msg_id, user_id=user_id)
            for msg_id in dict.fromkeys(message_ids)
            if msg_id not in already_read_ids
        ]

    async def is_read(self, message_id: int, user_id: int) -> bool:
        """Check if a message has been read by a specific user."""
        existing = await self.find_one(message_id=message_id, user_id=user_id)
        return existing is not None

    async def get_read_message_ids(self, user_id: int) -> list[int]:
        """Get all read message IDs for a specific user."""
        query = select(InboxMessageRead.message_id).where(InboxMessageRead.user_id == user_id)
        result = await self.session.exec(query)
        return list(result.all())

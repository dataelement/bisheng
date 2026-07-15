from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.message.domain.models.message_push_outbox import (
    MessagePushOutbox,
    MessagePushOutboxStatus,
)
from bisheng.message.domain.repositories.interfaces.message_push_outbox_repository import (
    MessagePushOutboxRepository,
)


class MessagePushOutboxRepositoryImpl(BaseRepositoryImpl[MessagePushOutbox, int], MessagePushOutboxRepository):
    """Repository implementation for message push outbox records."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, MessagePushOutbox)

    async def find_pending_ready(
        self,
        before: datetime,
        limit: int,
    ) -> list[MessagePushOutbox]:
        """Find pending records ready for retry/push before ``before``."""
        query = (
            select(MessagePushOutbox)
            .where(
                MessagePushOutbox.status == MessagePushOutboxStatus.PENDING,
                (MessagePushOutbox.next_retry_at.is_(None)) | (MessagePushOutbox.next_retry_at <= before),
            )
            .order_by(MessagePushOutbox.id.asc())
            .limit(limit)
        )
        result = await self.session.exec(query)
        return list(result.all())

    async def mark_sent(
        self,
        outbox_id: int,
        sent_at: datetime,
    ) -> MessagePushOutbox | None:
        """Mark a record as sent and clear failure_reason."""
        message = await self.find_by_id(outbox_id)
        if message is None:
            return None
        message.status = MessagePushOutboxStatus.SENT
        message.sent_at = sent_at
        message.failure_reason = None
        return await self.update(message)

    async def mark_pending_retry(
        self,
        outbox_id: int,
        retry_count: int,
        next_retry_at: datetime,
        failure_reason: str,
    ) -> MessagePushOutbox | None:
        """Update a record for retry."""
        message = await self.find_by_id(outbox_id)
        if message is None:
            return None
        message.status = MessagePushOutboxStatus.PENDING
        message.retry_count = retry_count
        message.next_retry_at = next_retry_at
        message.failure_reason = failure_reason
        return await self.update(message)

    async def mark_failed(
        self,
        outbox_id: int,
        retry_count: int,
        failure_reason: str,
    ) -> MessagePushOutbox | None:
        """Mark a record as finally failed."""
        message = await self.find_by_id(outbox_id)
        if message is None:
            return None
        message.status = MessagePushOutboxStatus.FAILED
        message.retry_count = retry_count
        message.failure_reason = failure_reason
        return await self.update(message)

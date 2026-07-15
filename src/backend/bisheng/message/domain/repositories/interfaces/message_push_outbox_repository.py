from abc import ABC, abstractmethod
from datetime import datetime

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.message.domain.models.message_push_outbox import MessagePushOutbox


class MessagePushOutboxRepository(BaseRepository[MessagePushOutbox, int], ABC):
    """Repository interface for message push outbox records."""

    @abstractmethod
    async def find_pending_ready(
        self,
        before: datetime,
        limit: int,
    ) -> list[MessagePushOutbox]:
        """Find pending records ready for retry/push before ``before``.

        A record is ready when ``status='pending'`` and
        ``next_retry_at IS NULL OR next_retry_at <= before``.
        """
        pass

    @abstractmethod
    async def mark_sent(
        self,
        outbox_id: int,
        sent_at: datetime,
    ) -> MessagePushOutbox | None:
        """Mark a record as sent and clear failure_reason."""
        pass

    @abstractmethod
    async def mark_pending_retry(
        self,
        outbox_id: int,
        retry_count: int,
        next_retry_at: datetime,
        failure_reason: str,
    ) -> MessagePushOutbox | None:
        """Update a record for retry."""
        pass

    @abstractmethod
    async def mark_failed(
        self,
        outbox_id: int,
        retry_count: int,
        failure_reason: str,
    ) -> MessagePushOutbox | None:
        """Mark a record as finally failed."""
        pass

from abc import ABC, abstractmethod
from typing import List

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.message.domain.models.inbox_message_read import InboxMessageRead


class InboxMessageReadRepository(BaseRepository[InboxMessageRead, int], ABC):
    """Inbox Message Read repository interface for managing read status records."""

    @abstractmethod
    async def mark_as_read(self, message_id: int, user_id: int) -> InboxMessageRead:
        """Mark a message as read for a specific user. Idempotent operation."""
        pass

    @abstractmethod
    async def batch_mark_as_read(self, message_ids: List[int], user_id: int) -> int:
        """Batch mark messages as read. Returns number of newly marked records."""
        pass

    @abstractmethod
    async def is_read(self, message_id: int, user_id: int) -> bool:
        """Check if a message has been read by a specific user."""
        pass

    @abstractmethod
    async def get_read_message_ids(self, user_id: int) -> List[int]:
        """Get all read message IDs for a specific user."""
        pass

from abc import ABC, abstractmethod
from typing import List, Optional

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.message.domain.models.inbox_message import InboxMessage, MessageStatusEnum, MessageTypeEnum


class InboxMessageRepository(BaseRepository[InboxMessage, int], ABC):
    """Inbox Message repository interface for managing in-app messages."""

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def count_unread_by_receiver(
        self,
        user_id: int,
        read_message_ids: Optional[List[int]] = None,
        message_type: Optional[MessageTypeEnum] = None,
    ) -> int:
        """Count unread messages for a specific user."""
        pass

    @abstractmethod
    async def update_message_status(
        self,
        message_id: int,
        status: MessageStatusEnum,
    ) -> Optional[InboxMessage]:
        """Update message approval status."""
        pass

    @abstractmethod
    async def update_message_content(
        self,
        message_id: int,
        content: list,
    ) -> Optional[InboxMessage]:
        """Update message content (e.g., after approval action)."""
        pass

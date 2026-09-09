from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.message.domain.models.inbox_message import InboxMessage, MessageStatusEnum, MessageTypeEnum
from bisheng.message.domain.schemas.message_schema import ReadStateEnum


class InboxMessageRepository(BaseRepository[InboxMessage, int], ABC):
    """Inbox Message repository interface for managing in-app messages."""

    @abstractmethod
    async def find_messages_by_receiver(
        self,
        user_id: int,
        message_type: MessageTypeEnum | None = None,
        action_codes: list[str] | None = None,
        exclude_action_codes: list[str] | None = None,
        status: MessageStatusEnum | None = None,
        keyword: str | None = None,
        read_state: ReadStateEnum = ReadStateEnum.ALL,
        read_message_ids: list[int] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[InboxMessage]:
        """Find messages by receiver user ID with optional filters and pagination.

        ``read_state`` drives the read filter: ALL applies none, UNREAD excludes
        ``read_message_ids``, READ keeps only ``read_message_ids`` (empty list => empty result).
        """
        pass

    @abstractmethod
    async def count_messages_by_receiver(
        self,
        user_id: int,
        message_type: MessageTypeEnum | None = None,
        action_codes: list[str] | None = None,
        exclude_action_codes: list[str] | None = None,
        status: MessageStatusEnum | None = None,
        keyword: str | None = None,
        read_state: ReadStateEnum = ReadStateEnum.ALL,
        read_message_ids: list[int] | None = None,
    ) -> int:
        """Count messages by receiver user ID with optional filters."""
        pass

    @abstractmethod
    async def count_unread_by_receiver(
        self,
        user_id: int,
        read_message_ids: list[int] | None = None,
        message_type: MessageTypeEnum | None = None,
        action_codes: list[str] | None = None,
        exclude_action_codes: list[str] | None = None,
    ) -> int:
        """Count unread messages for a specific user."""
        pass

    @abstractmethod
    async def update_message_after_approval(
        self,
        message_id: int,
        status: MessageStatusEnum,
        content: list,
        operator_user_id: int,
    ) -> InboxMessage | None:
        """Atomically update message status, content, and operator after approval action."""
        pass

    @abstractmethod
    async def update_message_content(
        self,
        message_id: int,
        content: list,
    ) -> InboxMessage | None:
        """Update message content (e.g., after approval_id backfill)."""
        pass

    @abstractmethod
    async def get_all_message_ids_by_receiver(
        self,
        user_id: int,
        exclude_action_codes: list[str] | None = None,
    ) -> list[int]:
        """Get all message IDs where the user is a receiver, minus any excluded action codes."""
        pass

    @abstractmethod
    async def batch_approve_channel_subscription_messages(
        self,
        channel_id: str,
        operator_user_id: int,
    ) -> int:
        """Batch approve all pending channel subscription messages for a specific channel.

        Updates all messages with action_code='request_channel' and status=wait_approve
        that contain the specified channel_id in their content.

        Returns the number of messages updated.
        """
        pass

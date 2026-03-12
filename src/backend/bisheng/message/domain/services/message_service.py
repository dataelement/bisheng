import logging
from typing import List, Optional, Any, Dict

from bisheng.common.errcode.message import (
    MessageNotFoundError,
    MessagePermissionDeniedError,
    MessageAlreadyApprovedError,
)
from bisheng.message.domain.models.inbox_message import InboxMessage, MessageTypeEnum, MessageStatusEnum
from bisheng.message.domain.repositories.interfaces.inbox_message_repository import InboxMessageRepository
from bisheng.message.domain.repositories.interfaces.inbox_message_read_repository import InboxMessageReadRepository
from bisheng.message.domain.schemas.message_schema import (
    MessageItemResponse,
    MessagePageResponse,
    UnreadCountResponse,
    ApprovalActionEnum,
    TabTypeEnum,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.user.domain.models.user import UserDao

logger = logging.getLogger(__name__)


class MessageService:
    """Service layer for in-app messaging (inbox) operations."""

    def __init__(
        self,
        message_repository: 'InboxMessageRepository',
        message_read_repository: 'InboxMessageReadRepository',
    ):
        self.message_repository = message_repository
        self.message_read_repository = message_read_repository

    async def send_message(
        self,
        content: List[Dict[str, Any]],
        sender: int,
        message_type: MessageTypeEnum,
        receiver: List[int],
        status: MessageStatusEnum = MessageStatusEnum.WAIT_APPROVE,
    ) -> InboxMessage:
        """Create and save a new inbox message."""
        message = InboxMessage(
            content=content,
            sender=sender,
            message_type=message_type,
            receiver=receiver,
            status=status,
        )
        saved_message = await self.message_repository.save(message)
        logger.info(
            "Inbox message sent: id=%s, type=%s, sender=%s, receivers=%s",
            saved_message.id, message_type.value, sender, receiver,
        )
        return saved_message

    async def get_message_list(
        self,
        login_user: UserPayload,
        tab: TabTypeEnum = TabTypeEnum.ALL,
        only_unread: bool = False,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> MessagePageResponse:
        """Get paginated message list for the current user with read status annotation."""
        # 1. Get read message IDs for this user
        read_message_ids = await self.message_read_repository.get_read_message_ids(login_user.user_id)
        read_set = set(read_message_ids)

        # 2. Determine message type filter based on tab
        message_type = None
        if tab == TabTypeEnum.REQUEST:
            message_type = MessageTypeEnum.APPROVE

        # 3. Query messages
        messages = await self.message_repository.find_messages_by_receiver(
            user_id=login_user.user_id,
            message_type=message_type,
            keyword=keyword,
            only_unread=only_unread,
            read_message_ids=read_message_ids if only_unread else None,
            page=page,
            page_size=page_size,
        )

        # 4. Count total
        total = await self.message_repository.count_messages_by_receiver(
            user_id=login_user.user_id,
            message_type=message_type,
            keyword=keyword,
            only_unread=only_unread,
            read_message_ids=read_message_ids if only_unread else None,
        )

        # 5. Batch query sender user names
        sender_ids = list({m.sender for m in messages})
        sender_map: Dict[int, str] = {}
        if sender_ids:
            users = await UserDao.aget_user_by_ids(sender_ids)
            sender_map = {u.user_id: u.user_name for u in users}

        # 6. Build response
        items = []
        for msg in messages:
            items.append(MessageItemResponse(
                id=msg.id,
                content=msg.content,
                sender=msg.sender,
                sender_name=sender_map.get(msg.sender),
                message_type=msg.message_type.value,
                status=msg.status.value,
                is_read=msg.id in read_set,
                create_time=msg.create_time,
                update_time=msg.update_time,
            ))

        return MessagePageResponse(data=items, total=total)

    async def get_unread_count(self, login_user: UserPayload) -> UnreadCountResponse:
        """Get unread message counts grouped by type."""
        read_message_ids = await self.message_read_repository.get_read_message_ids(login_user.user_id)

        total = await self.message_repository.count_unread_by_receiver(
            user_id=login_user.user_id,
            read_message_ids=read_message_ids,
        )
        notify_count = await self.message_repository.count_unread_by_receiver(
            user_id=login_user.user_id,
            read_message_ids=read_message_ids,
            message_type=MessageTypeEnum.NOTIFY,
        )
        approve_count = await self.message_repository.count_unread_by_receiver(
            user_id=login_user.user_id,
            read_message_ids=read_message_ids,
            message_type=MessageTypeEnum.APPROVE,
        )

        return UnreadCountResponse(total=total, notify=notify_count, approve=approve_count)

    async def mark_as_read(self, message_ids: List[int], login_user: UserPayload) -> int:
        """Mark specific messages as read for the current user."""
        return await self.message_read_repository.batch_mark_as_read(message_ids, login_user.user_id)

    async def mark_all_as_read(self, login_user: UserPayload) -> int:
        """Mark all messages as read for the current user."""
        read_message_ids = await self.message_read_repository.get_read_message_ids(login_user.user_id)

        # Get all message IDs for this user
        all_messages = await self.message_repository.find_messages_by_receiver(
            user_id=login_user.user_id,
            page=1,
            page_size=10000,  # Large enough to cover all messages
        )
        all_msg_ids = [m.id for m in all_messages]

        # Filter out already read messages
        unread_ids = [mid for mid in all_msg_ids if mid not in set(read_message_ids)]
        if not unread_ids:
            return 0

        return await self.message_read_repository.batch_mark_as_read(unread_ids, login_user.user_id)

    async def handle_approval(
        self,
        message_id: int,
        action: ApprovalActionEnum,
        login_user: UserPayload,
    ) -> InboxMessage:
        """
        Handle approval action (agree/reject) on an approval message.
        Updates message content to reflect the action result and changes status.
        """
        # 1. Find the message
        message = await self.message_repository.find_by_id(message_id)
        if not message:
            raise MessageNotFoundError()

        # 2. Verify the current user is a receiver
        if login_user.user_id not in message.receiver:
            raise MessagePermissionDeniedError()

        # 3. Check if already processed
        if message.status in (MessageStatusEnum.APPROVED, MessageStatusEnum.REJECTED):
            raise MessageAlreadyApprovedError()

        # 4. Update status
        new_status = (
            MessageStatusEnum.APPROVED
            if action == ApprovalActionEnum.AGREE
            else MessageStatusEnum.REJECTED
        )

        # 5. Update content - replace interactive elements with result text
        updated_content = self._update_content_after_approval(message.content, action)

        # 6. Persist changes
        await self.message_repository.update_message_status(message_id, new_status)
        updated_message = await self.message_repository.update_message_content(message_id, updated_content)

        # 7. Auto-mark as read after action
        await self.message_read_repository.mark_as_read(message_id, login_user.user_id)

        logger.info(
            "Approval action processed: message_id=%s, action=%s, user=%s",
            message_id, action.value, login_user.user_id,
        )

        return updated_message

    @staticmethod
    def _update_content_after_approval(
        content: List[Dict[str, Any]],
        action: ApprovalActionEnum,
    ) -> List[Dict[str, Any]]:
        """
        Update message content after approval action.
        - Replace 'user' type with 'text' type (remove interactivity)
        - Replace 'business_url' type with 'text' type
        - Set agree_reject_button content to the action result
        """
        updated = []
        for item in content:
            new_item = dict(item)
            item_type = item.get('type', '')

            if item_type == 'user':
                new_item['type'] = 'text'

            elif item_type == 'business_url':
                new_item['type'] = 'text'

            elif item_type == 'agree_reject_button':
                new_item['content'] = action.value

            updated.append(new_item)

        return updated

    async def delete_message(self, message_id: int, login_user: UserPayload) -> bool:
        """Delete (soft or hard) a message for the current user."""
        message = await self.message_repository.find_by_id(message_id)
        if not message:
            raise MessageNotFoundError()

        if login_user.user_id not in message.receiver:
            raise MessagePermissionDeniedError()

        return await self.message_repository.delete(message_id)

    @staticmethod
    def build_channel_subscribe_approval_content(
        applicant_user_id: int,
        applicant_user_name: str,
        channel_id: str,
        channel_name: str,
        approval_message_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Build the message content structure for a channel subscription approval request.
        Follows the approval message content format defined in the PRD.
        """
        content = [
            {
                "type": "user",
                "content": f"@{applicant_user_name}",
                "metadata": {"user_id": applicant_user_id},
            },
            {
                "type": "system_text",
                "content": "request_channel",
            },
            {
                "type": "business_url",
                "content": f"--{channel_name}",
                "metadata": {
                    "business_type": "channel_id",
                    "data": {"channel_id": channel_id},
                },
            },
            {
                "type": "agree_reject_button",
                "content": "",
                "metadata": {
                    "business_type": "request_channel",
                    "data": {"approval_id": str(approval_message_id or "")},
                },
            },
        ]
        return content

    async def send_channel_subscribe_approval(
        self,
        applicant_user_id: int,
        applicant_user_name: str,
        channel_id: str,
        channel_name: str,
        receiver_user_ids: List[int],
    ) -> InboxMessage:
        """
        Send a channel subscription approval notification to channel creator and admins.
        """
        # Build initial content without approval_id (will be set after message creation)
        content = self.build_channel_subscribe_approval_content(
            applicant_user_id=applicant_user_id,
            applicant_user_name=applicant_user_name,
            channel_id=channel_id,
            channel_name=channel_name,
        )

        # Create the message
        message = await self.send_message(
            content=content,
            sender=applicant_user_id,
            message_type=MessageTypeEnum.APPROVE,
            receiver=receiver_user_ids,
            status=MessageStatusEnum.WAIT_APPROVE,
        )

        # Update the approval_id in the content to reference the message itself
        updated_content = []
        for item in content:
            new_item = dict(item)
            if item.get('type') == 'agree_reject_button':
                metadata = dict(item.get('metadata', {}))
                data = dict(metadata.get('data', {}))
                data['approval_id'] = str(message.id)
                metadata['data'] = data
                new_item['metadata'] = metadata
            updated_content.append(new_item)

        await self.message_repository.update_message_content(message.id, updated_content)
        message.content = updated_content

        return message

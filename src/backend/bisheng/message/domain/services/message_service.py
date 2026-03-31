import copy
import logging
from typing import List, Optional, Any, Dict

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.message import (
    MessageNotFoundError,
    MessagePermissionDeniedError,
    MessageAlreadyApprovedError,
)
from bisheng.message.domain.models.inbox_message import InboxMessage, MessageTypeEnum, MessageStatusEnum
from bisheng.message.domain.repositories.interfaces.inbox_message_read_repository import InboxMessageReadRepository
from bisheng.message.domain.repositories.interfaces.inbox_message_repository import InboxMessageRepository
from bisheng.message.domain.schemas.message_schema import (
    MessageItemResponse,
    MessagePageResponse,
    UnreadCountResponse,
    ApprovalActionEnum,
    TabTypeEnum, MessageContentItem,
)
from bisheng.message.domain.services.approval_handler import ApprovalHandler
from bisheng.database.models.user_group import UserGroupDao
from bisheng.user.domain.models.user import UserDao

logger = logging.getLogger(__name__)


class MessageService:
    """Service layer for in-app messaging (inbox) operations."""

    def __init__(
            self,
            message_repository: 'InboxMessageRepository',
            message_read_repository: 'InboxMessageReadRepository',
            approval_handlers: Optional[List[ApprovalHandler]] = None,
    ):
        self.message_repository = message_repository
        self.message_read_repository = message_read_repository
        self._handler_map: Dict[str, ApprovalHandler] = {}

        for handler in approval_handlers or []:
            action_code = handler.get_action_code()
            if action_code in self._handler_map:
                logger.warning("Duplicate approval handler registered for action_code=%s", action_code)
            self._handler_map[action_code] = handler

    async def send_message(
            self,
            content: List[Dict[str, Any]],
            sender: int,
            message_type: MessageTypeEnum,
            receiver: List[int],
            status: MessageStatusEnum = MessageStatusEnum.WAIT_APPROVE,
            action_code: Optional[str] = None,
    ) -> InboxMessage:
        """Create and save a new inbox message."""
        message = InboxMessage(
            content=content,
            sender=sender,
            message_type=message_type,
            receiver=receiver,
            status=status,
            action_code=action_code,
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

        # 6. Batch query group names for users referenced in message content
        content_user_ids = self._extract_content_user_ids(messages)
        user_group_name_map = await self._build_user_group_name_map(content_user_ids)

        # 7. Build response
        items = []
        for msg in messages:
            items.append(MessageItemResponse(
                id=msg.id,
                content=self._enrich_message_content_with_group_names(msg.content, user_group_name_map),
                sender=msg.sender,
                sender_name=sender_map.get(msg.sender),
                message_type=msg.message_type.value,
                status=msg.status.value,
                action_code=msg.action_code,
                operator_user_id=msg.operator_user_id,
                is_read=msg.id in read_set,
                create_time=msg.create_time,
                update_time=msg.update_time,
            ))

        return MessagePageResponse(data=items, total=total)

    @staticmethod
    def _extract_content_user_ids(messages: List[InboxMessage]) -> List[int]:
        """Extract distinct user IDs from content items with type=user."""
        user_ids: set[int] = set()
        for message in messages:
            for item in message.content or []:
                if item.get('type') != 'user':
                    continue

                metadata = item.get('metadata') or {}
                user_id = metadata.get('user_id')
                if isinstance(user_id, int):
                    user_ids.add(user_id)

        return list(user_ids)

    @staticmethod
    async def _build_user_group_name_map(user_ids: List[int]) -> Dict[int, List[str]]:
        """Build a map from user_id to the user's group names."""
        if not user_ids:
            return {}

        user_groups_map = await UserGroupDao.aget_user_groups_batch(user_ids)
        return {
            user_id: [group.group_name for group in groups]
            for user_id, groups in user_groups_map.items()
        }

    @staticmethod
    def _enrich_message_content_with_group_names(
            content: List[Dict[str, Any]],
            user_group_name_map: Dict[int, List[str]],
    ) -> List[Dict[str, Any]]:
        """Attach group_names into metadata for content items with type=user."""
        enriched_content = []
        for item in content or []:
            if item.get('type') != 'user':
                enriched_content.append(item)
                continue

            metadata = item.get('metadata')
            if not isinstance(metadata, dict):
                enriched_content.append(item)
                continue

            user_id = metadata.get('user_id')
            if not isinstance(user_id, int):
                enriched_content.append(item)
                continue

            new_item = dict(item)
            new_metadata = dict(metadata)
            new_metadata['group_names'] = user_group_name_map.get(user_id, [])
            new_item['metadata'] = new_metadata
            enriched_content.append(new_item)

        return enriched_content

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
        read_set = set(read_message_ids)

        # Use dedicated method to get all message IDs without loading full objects
        all_msg_ids = await self.message_repository.get_all_message_ids_by_receiver(login_user.user_id)

        # Filter out already read messages
        unread_ids = [mid for mid in all_msg_ids if mid not in read_set]
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
        Executes handler business logic FIRST, then persists state changes.
        If handler fails, message status remains unchanged (rollback-safe).
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

        # 4. Determine new status
        new_status = (
            MessageStatusEnum.APPROVED
            if action == ApprovalActionEnum.AGREE
            else MessageStatusEnum.REJECTED
        )

        original_content = copy.deepcopy(message.content)
        action_code = self._extract_action_code(message)

        # 5. Execute handler FIRST — if it fails, message status stays unchanged
        handler = self._handler_map.get(action_code)
        if handler:
            handler_message = InboxMessage(
                id=message.id,
                content=original_content,
                sender=message.sender,
                message_type=message.message_type,
                receiver=list(message.receiver),
                status=message.status,
                action_code=message.action_code,
                create_time=message.create_time,
                update_time=message.update_time,
            )
            if action == ApprovalActionEnum.AGREE:
                await handler.on_approved(handler_message, login_user.user_id)
            else:
                await handler.on_rejected(handler_message, login_user.user_id)

        # 6. Update content — set button result text
        updated_content = self._update_content_after_approval(original_content, action)

        # 7. Persist all changes atomically (status + content + operator)
        updated_message = await self.message_repository.update_message_after_approval(
            message_id=message_id,
            status=new_status,
            content=updated_content,
            operator_user_id=login_user.user_id,
        )

        # 8. Auto-mark as read after action
        await self.message_read_repository.mark_as_read(message_id, login_user.user_id)

        logger.info(
            "Approval action processed: message_id=%s, action=%s, operator=%s",
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
        - Preserve 'user' and 'business_url' types for continued clickability
        - Set agree_reject_button content to the action result
        """
        updated = []
        for item in content:
            new_item = dict(item)
            item_type = item.get('type', '')

            if item_type == 'agree_reject_button':
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
    def build_generic_notify_content(
            content_list: List[MessageContentItem | Dict],
    ) -> List[Dict[str, Any]]:
        """
        Build generic notification content.
        """
        return [one if isinstance(one, dict) else one.to_message() for one in content_list]

    async def send_generic_notify(
            self,
            sender: int,
            receiver_user_ids: List[int],
            content_item_list: List[MessageContentItem | Dict],
    ) -> InboxMessage:
        """
        Send a generic notification message to specific receivers.
        """
        content = self.build_generic_notify_content(content_item_list)

        message = await self.send_message(
            content=content,
            sender=sender,
            message_type=MessageTypeEnum.NOTIFY,
            receiver=receiver_user_ids,
            status=MessageStatusEnum.APPROVED,  # Notify messages don't need approval
        )
        return message

    @staticmethod
    def build_generic_approval_content(
            applicant_user_id: int,
            applicant_user_name: str,
            action_code: str,
            business_type: str,
            business_id: str,
            business_name: str,
            button_action_code: str,
            approval_message_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Build the generic message content structure for a business approval request.
        """
        content = [
            {
                "type": "user",
                "content": f"@{applicant_user_name}",
                "metadata": {"user_id": applicant_user_id},
            },
            {
                "type": "system_text",
                "content": action_code,
            },
            {
                "type": "business_url",
                "content": f"--{business_name}",
                "metadata": {
                    "business_type": business_type,
                    "data": {business_type: business_id},
                },
            },
            {
                "type": "agree_reject_button",
                "content": "",
                "metadata": {
                    "action_code": button_action_code,
                    "data": {"approval_id": str(approval_message_id or "")},
                },
            },
        ]
        return content

    async def send_generic_approval(
            self,
            applicant_user_id: int,
            applicant_user_name: str,
            action_code: str,
            business_type: str,
            business_id: str,
            business_name: str,
            button_action_code: str,
            receiver_user_ids: List[int],
    ) -> InboxMessage:
        """
        Send a generic approval notification to specific receivers.
        Saves the message first, then backfills approval_id in a single update.
        """
        content = self.build_generic_approval_content(
            applicant_user_id=applicant_user_id,
            applicant_user_name=applicant_user_name,
            action_code=action_code,
            business_type=business_type,
            business_id=business_id,
            business_name=business_name,
            button_action_code=button_action_code,
        )

        # Create the message with action_code stored on model for reliable routing
        message = await self.send_message(
            content=content,
            sender=applicant_user_id,
            message_type=MessageTypeEnum.APPROVE,
            receiver=receiver_user_ids,
            status=MessageStatusEnum.WAIT_APPROVE,
            action_code=button_action_code,
        )

        # Backfill approval_id in content to reference the message itself
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

        updated_message = await self.message_repository.update_message_content(message.id, updated_content)

        return updated_message

    @staticmethod
    def _extract_action_code(message: InboxMessage) -> str:
        """
        Extract approval action code. Prefers model-level action_code field,
        falls back to content JSON for backward compatibility with old messages.
        """
        # Prefer model field (set by send_generic_approval)
        if message.action_code:
            return message.action_code

        # Fallback: extract from content JSON (supports both old key 'business_type' and new key 'action_code')
        for item in (message.content or []):
            if item.get('type') != 'agree_reject_button':
                continue

            metadata = item.get('metadata', {})
            code = metadata.get('action_code') or metadata.get('business_type')
            if isinstance(code, str):
                return code

        return ""

    async def batch_approve_channel_subscription_messages(
            self,
            channel_id: str,
            operator_user_id: int,
    ) -> int:
        """
        Batch approve all pending channel subscription messages for a specific channel.

        This is used when a channel's visibility changes from REVIEW to PUBLIC,
        automatically approving all pending subscription requests.

        Returns the number of messages updated.
        """
        count = await self.message_repository.batch_approve_channel_subscription_messages(
            channel_id=channel_id,
            operator_user_id=operator_user_id,
        )
        if count > 0:
            logger.info(
                "Batch approved %d channel subscription messages for channel_id=%s, operator=%s",
                count, channel_id, operator_user_id,
            )
        return count

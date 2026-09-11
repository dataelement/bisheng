import logging
from typing import List, Optional

from sqlalchemy import Text, and_, cast, func, or_
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.message.domain.models.inbox_message import InboxMessage, MessageStatusEnum, MessageTypeEnum
from bisheng.message.domain.repositories.interfaces.inbox_message_repository import InboxMessageRepository

logger = logging.getLogger(__name__)

SEARCHABLE_CONTENT_TYPES = ('user', 'business_url')
MAX_CONTENT_ITEMS_FOR_KEYWORD_SEARCH = 10


def _get_dialect(session: AsyncSession) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind else 'mysql'


class InboxMessageRepositoryImpl(BaseRepositoryImpl[InboxMessage, int], InboxMessageRepository):
    """Inbox Message repository implementation."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, InboxMessage)

    def _apply_receiver_filter(self, query, user_id: int):
        """Filter messages by receiver user_id.

        MySQL: uses native JSON_CONTAINS for exact integer containment.
        DaMeng/others: uses text-boundary LIKE patterns against the CLOB-stored
        JSON array (serialized by JsonType as "[1, 2, 3]").
        """
        if _get_dialect(self.session) == 'mysql':
            return query.where(func.json_contains(InboxMessage.receiver, str(user_id)))

        # JsonType serializes with Python's default separator ", " so the array
        # looks like "[1, 2, 3]". Match user_id at JSON element boundaries.
        uid = str(user_id)
        receiver_text = cast(InboxMessage.receiver, Text())
        return query.where(
            or_(
                receiver_text == f'[{uid}]',               # only element
                receiver_text.like(f'[{uid}, %'),           # first element
                receiver_text.like(f'%, {uid}]'),           # last element
                receiver_text.like(f'%, {uid}, %'),         # middle element
            )
        )

    def _apply_content_keyword_filter(self, query, keyword: str):
        """Filter messages by keyword in content items.

        MySQL: uses JSON_EXTRACT / JSON_UNQUOTE for structured path lookup.
        DaMeng/others: falls back to full-text LIKE on the serialized content
        column (less precise but avoids MySQL-specific JSON functions).
        """
        like_pattern = f'%{keyword}%'

        if _get_dialect(self.session) == 'mysql':
            searchable_conditions = []
            for index in range(MAX_CONTENT_ITEMS_FOR_KEYWORD_SEARCH):
                item_type = func.json_unquote(
                    func.json_extract(InboxMessage.content, f'$[{index}].type')
                )
                item_content = func.json_unquote(
                    func.json_extract(InboxMessage.content, f'$[{index}].content')
                )
                searchable_conditions.append(
                    and_(
                        item_type.in_(SEARCHABLE_CONTENT_TYPES),
                        item_content.like(like_pattern),
                    )
                )
            return query.where(or_(*searchable_conditions))

        # DaMeng: content is stored as CLOB; use a simple LIKE on the whole column.
        return query.where(cast(InboxMessage.content, Text()).like(like_pattern))

    async def find_messages_by_receiver(
        self,
        user_id: int,
        message_type: Optional[MessageTypeEnum] = None,
        action_codes: Optional[List[str]] = None,
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

        if message_type is not None and action_codes:
            query = query.where(
                or_(
                    InboxMessage.message_type == message_type,
                    col(InboxMessage.action_code).in_(action_codes),
                )
            )
        elif message_type is not None:
            query = query.where(InboxMessage.message_type == message_type)
        elif action_codes:
            query = query.where(col(InboxMessage.action_code).in_(action_codes))

        if status is not None:
            query = query.where(InboxMessage.status == status)

        if keyword:
            query = self._apply_content_keyword_filter(query, keyword)

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
        action_codes: Optional[List[str]] = None,
        status: Optional[MessageStatusEnum] = None,
        keyword: Optional[str] = None,
        only_unread: bool = False,
        read_message_ids: Optional[List[int]] = None,
    ) -> int:
        """Count messages by receiver user ID with optional filters."""
        query = select(func.count()).select_from(InboxMessage)

        query = self._apply_receiver_filter(query, user_id)

        if message_type is not None and action_codes:
            query = query.where(
                or_(
                    InboxMessage.message_type == message_type,
                    col(InboxMessage.action_code).in_(action_codes),
                )
            )
        elif message_type is not None:
            query = query.where(InboxMessage.message_type == message_type)
        elif action_codes:
            query = query.where(col(InboxMessage.action_code).in_(action_codes))

        if status is not None:
            query = query.where(InboxMessage.status == status)

        if keyword:
            query = self._apply_content_keyword_filter(query, keyword)

        if only_unread and read_message_ids:
            query = query.where(col(InboxMessage.id).notin_(read_message_ids))

        result = await self.session.exec(query)
        return result.one()

    async def count_unread_by_receiver(
        self,
        user_id: int,
        read_message_ids: Optional[List[int]] = None,
        message_type: Optional[MessageTypeEnum] = None,
        action_codes: Optional[List[str]] = None,
        exclude_action_codes: Optional[List[str]] = None,
    ) -> int:
        """Count unread messages for a specific user."""
        query = select(func.count()).select_from(InboxMessage)

        query = self._apply_receiver_filter(query, user_id)

        if message_type is not None and action_codes:
            query = query.where(
                or_(
                    InboxMessage.message_type == message_type,
                    col(InboxMessage.action_code).in_(action_codes),
                )
            )
        elif message_type is not None:
            query = query.where(InboxMessage.message_type == message_type)
        elif action_codes:
            query = query.where(col(InboxMessage.action_code).in_(action_codes))

        if exclude_action_codes:
            query = query.where(
                or_(
                    InboxMessage.action_code.is_(None),
                    col(InboxMessage.action_code).notin_(exclude_action_codes),
                )
            )

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
        from sqlalchemy import update

        # Match channel_id anywhere in the serialized content CLOB/JSON.
        # cast to Text works on all dialects since JsonType stores as text on DaMeng.
        channel_id_json = f'%"channel_id": "{channel_id}"%'

        query = (
            update(InboxMessage)
            .where(
                InboxMessage.action_code == "request_channel",
                InboxMessage.status == MessageStatusEnum.WAIT_APPROVE,
                cast(InboxMessage.content, Text()).like(channel_id_json),
            )
            .values(
                status=MessageStatusEnum.APPROVED,
                operator_user_id=operator_user_id,
            )
        )
        result = await self.session.exec(query)
        await self.session.commit()
        return result.rowcount

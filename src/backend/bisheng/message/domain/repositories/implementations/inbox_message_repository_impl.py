import logging

from sqlalchemy import Text, and_, cast, false, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.message.domain.models.inbox_message import InboxMessage, MessageStatusEnum, MessageTypeEnum
from bisheng.message.domain.repositories.interfaces.inbox_message_repository import InboxMessageRepository
from bisheng.message.domain.schemas.message_schema import ReadStateEnum

logger = logging.getLogger(__name__)

SEARCHABLE_CONTENT_TYPES = ("user", "business_url")
MAX_CONTENT_ITEMS_FOR_KEYWORD_SEARCH = 10


def _get_dialect(session: AsyncSession) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind else "mysql"


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
        if _get_dialect(self.session) == "mysql":
            return query.where(func.json_contains(InboxMessage.receiver, str(user_id)))

        # JsonType serializes with Python's default separator ", " so the array
        # looks like "[1, 2, 3]". Match user_id at JSON element boundaries.
        uid = str(user_id)
        receiver_text = cast(InboxMessage.receiver, Text())
        return query.where(
            or_(
                receiver_text == f"[{uid}]",  # only element
                receiver_text.like(f"[{uid}, %"),  # first element
                receiver_text.like(f"%, {uid}]"),  # last element
                receiver_text.like(f"%, {uid}, %"),  # middle element
            )
        )

    def _apply_content_keyword_filter(self, query, keyword: str):
        """Filter messages by keyword in content items.

        MySQL: uses JSON_EXTRACT / JSON_UNQUOTE for structured path lookup.
        DaMeng/others: falls back to full-text LIKE on the serialized content
        column (less precise but avoids MySQL-specific JSON functions).
        """
        like_pattern = f"%{keyword}%"

        if _get_dialect(self.session) == "mysql":
            searchable_conditions = []
            for index in range(MAX_CONTENT_ITEMS_FOR_KEYWORD_SEARCH):
                item_type = func.json_unquote(func.json_extract(InboxMessage.content, f"$[{index}].type"))
                item_content = func.json_unquote(func.json_extract(InboxMessage.content, f"$[{index}].content"))
                searchable_conditions.append(
                    and_(
                        item_type.in_(SEARCHABLE_CONTENT_TYPES),
                        item_content.like(like_pattern),
                    )
                )
            return query.where(or_(*searchable_conditions))

        # DaMeng: content is stored as CLOB; use a simple LIKE on the whole column.
        return query.where(cast(InboxMessage.content, Text()).like(like_pattern))

    def _apply_action_code_filters(
        self,
        query,
        message_type: MessageTypeEnum | None = None,
        action_codes: list[str] | None = None,
        exclude_action_codes: list[str] | None = None,
    ):
        """Apply message_type / action_code inclusion and exclusion filters.

        ``message_type`` and ``action_codes`` are OR-ed (a message matches either),
        while ``exclude_action_codes`` always narrows the result. Messages with a
        NULL action_code are never excluded.
        """
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

        return query

    @staticmethod
    def _apply_read_state_filter(
        query,
        read_state: ReadStateEnum,
        read_message_ids: list[int] | None,
    ):
        """Apply the read-state filter against the caller-supplied read message IDs.

        ALL applies no filter; UNREAD excludes the read IDs (no read IDs => everything
        is unread); READ keeps only the read IDs (no read IDs => empty result).
        """
        if read_state == ReadStateEnum.UNREAD:
            if read_message_ids:
                query = query.where(col(InboxMessage.id).notin_(read_message_ids))
        elif read_state == ReadStateEnum.READ:
            if not read_message_ids:
                return query.where(false())
            query = query.where(col(InboxMessage.id).in_(read_message_ids))

        return query

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
        """Find messages by receiver user ID with optional filters and pagination."""
        query = select(InboxMessage)

        # Filter by receiver using JSON_CONTAINS
        query = self._apply_receiver_filter(query, user_id)

        query = self._apply_action_code_filters(query, message_type, action_codes, exclude_action_codes)

        if status is not None:
            query = query.where(InboxMessage.status == status)

        if keyword:
            query = self._apply_content_keyword_filter(query, keyword)

        query = self._apply_read_state_filter(query, read_state, read_message_ids)

        # Newest first
        query = query.order_by(InboxMessage.create_time.desc())

        # Pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.session.exec(query)
        return list(result.all())

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
        query = select(func.count()).select_from(InboxMessage)

        query = self._apply_receiver_filter(query, user_id)

        query = self._apply_action_code_filters(query, message_type, action_codes, exclude_action_codes)

        if status is not None:
            query = query.where(InboxMessage.status == status)

        if keyword:
            query = self._apply_content_keyword_filter(query, keyword)

        query = self._apply_read_state_filter(query, read_state, read_message_ids)

        result = await self.session.exec(query)
        return result.one()

    async def count_unread_by_receiver(
        self,
        user_id: int,
        read_message_ids: list[int] | None = None,
        message_type: MessageTypeEnum | None = None,
        action_codes: list[str] | None = None,
        exclude_action_codes: list[str] | None = None,
    ) -> int:
        """Count unread messages for a specific user."""
        query = select(func.count()).select_from(InboxMessage)

        query = self._apply_receiver_filter(query, user_id)

        query = self._apply_action_code_filters(query, message_type, action_codes, exclude_action_codes)

        # Exclude read messages
        query = self._apply_read_state_filter(query, ReadStateEnum.UNREAD, read_message_ids)

        result = await self.session.exec(query)
        return result.one()

    async def update_message_after_approval(
        self,
        message_id: int,
        status: MessageStatusEnum,
        content: list,
        operator_user_id: int,
    ) -> InboxMessage | None:
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
    ) -> InboxMessage | None:
        """Update message content (e.g., after approval_id backfill)."""
        message = await self.find_by_id(message_id)
        if not message:
            return None
        message.content = content
        return await self.update(message)

    async def get_all_message_ids_by_receiver(
        self,
        user_id: int,
        exclude_action_codes: list[str] | None = None,
    ) -> list[int]:
        """Get all message IDs where the user is a receiver, using JSON_CONTAINS."""
        query = select(InboxMessage.id)
        query = self._apply_receiver_filter(query, user_id)
        query = self._apply_action_code_filters(query, exclude_action_codes=exclude_action_codes)
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

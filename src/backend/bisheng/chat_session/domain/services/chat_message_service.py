from typing import Optional

from loguru import logger

from bisheng.api.services.chat_imp import comment_answer
from bisheng.api.v1.schemas import AddChatMessages, ChatInput
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, ServerError, UnAuthorizedError
from bisheng.common.errcode.tenant_sharing import TenantContextMissingError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao, LikedType
from bisheng.database.models.session import MessageSessionDao, SensitiveStatus


def _resolve_leaf_tenant_id(login_user: UserPayload) -> int:
    """F017 §5.4: resolve the leaf tenant id for derived-data writes.

    Priority (INV-T13):
      1. ``get_current_tenant_id()`` — the ContextVar set by F012's HTTP /
         WS / Celery middleware. This is the authoritative read-time
         tenant (admin-scope override > JWT leaf).
      2. ``login_user.tenant_id`` — fall back to the JWT payload so a unit
         test or a synchronous call path without the middleware still
         writes *some* tenant, but only when login_user was supplied.
    Raises ``TenantContextMissingError`` (19504) when both are absent;
    that refusal is spec AC-11's guard against NULL-tenant derived data.
    """
    tid = get_current_tenant_id()
    if tid is not None:
        return tid
    if login_user is not None and getattr(login_user, 'tenant_id', None) is not None:
        return login_user.tenant_id
    raise TenantContextMissingError()


class ChatMessageService:
    """Chat message CRUD and feedback services."""

    @staticmethod
    def add_qa_messages(data: AddChatMessages, login_user: UserPayload, request_ip: str) -> list:
        """Add a Q&A message pair. Creates session if needed.

        Returns the saved message list.

        F017 §5.4: both messages carry ``tenant_id = user's leaf tenant``
        (NOT the resource tenant). Child users talking to a Root-shared
        assistant produce Child-owned messages, keeping Root's quota usage
        free of Child traffic (INV-T13).
        """
        import json

        logger.debug(f'gateway add_chat_messages {data}')
        flow_id = data.flow_id
        chat_id = data.chat_id
        if not chat_id or not flow_id:
            raise ServerError.http_exception()

        # F017 AC-11: refuse to persist derived data with a NULL tenant.
        leaf_tenant_id = _resolve_leaf_tenant_id(login_user)

        save_human_message = data.human_message
        flow_info = FlowDao.get_flow_by_id(flow_id)
        if flow_info and flow_info.flow_type == FlowType.WORKFLOW.value:
            try:
                tmp_human_message = json.loads(data.human_message)
                for node_id, node_input in tmp_human_message.items():
                    save_human_message = node_input.get('message')
            except Exception:
                save_human_message = data.human_message

        human_message = ChatMessage(
            flow_id=flow_id,
            chat_id=chat_id,
            user_id=login_user.user_id,
            is_bot=False,
            message=save_human_message,
            sensitive_status=SensitiveStatus.VIOLATIONS.value,
            type='human',
            category='question',
            tenant_id=leaf_tenant_id,
        )
        bot_message = ChatMessage(
            flow_id=flow_id,
            chat_id=chat_id,
            user_id=login_user.user_id,
            is_bot=True,
            message=data.answer_message,
            sensitive_status=SensitiveStatus.PASS.value,
            type='bot',
            category='answer',
            tenant_id=leaf_tenant_id,
        )
        message_dbs = ChatMessageDao.insert_batch([human_message, bot_message])
        MessageSessionDao.update_sensitive_status(chat_id, SensitiveStatus.VIOLATIONS)

        from bisheng.chat_session.domain.chat import ChatSessionService
        ChatSessionService.get_or_create_session(chat_id, flow_id, login_user, request_ip)

        return message_dbs

    @staticmethod
    async def acreate(
        user_id: int,
        chat_id: str,
        flow_id: str,
        message: str,
        *,
        is_bot: bool = False,
        category: str = 'question',
        msg_type: str = 'human',
        sensitive_status: int = SensitiveStatus.VIOLATIONS.value,
        login_user: Optional[UserPayload] = None,
    ) -> ChatMessage:
        """F017 §5.4 derived-data writer (new async path).

        Forces ``tenant_id = get_current_tenant_id()`` (user leaf, not
        resource tenant). Raises ``TenantContextMissingError`` when
        context is missing — callers must not paper over a None.
        """
        leaf_tenant_id = _resolve_leaf_tenant_id(login_user)
        chat_message = ChatMessage(
            flow_id=flow_id,
            chat_id=chat_id,
            user_id=user_id,
            is_bot=is_bot,
            message=message,
            sensitive_status=sensitive_status,
            type=msg_type,
            category=category,
            tenant_id=leaf_tenant_id,
        )
        # Reuse sync insert (DAO lacks async insert_one for ChatMessage).
        return ChatMessageDao.insert_batch([chat_message])[0]

    @staticmethod
    def update_message(
        message_id: int,
        message: str,
        category: Optional[str],
        login_user: UserPayload,
    ) -> None:
        """Update message content with authorization check."""
        logger.info(
            f'update_chat_message message_id={message_id} message={message} login_user={login_user.user_name}'
        )
        chat_message = ChatMessageDao.get_message_by_id(message_id)
        if not chat_message:
            raise NotFoundError.http_exception()
        if chat_message.user_id != login_user.user_id:
            raise UnAuthorizedError.http_exception()

        chat_message.message = message
        if category:
            chat_message.category = category
        chat_message.source = False
        chat_message.sensitive_status = SensitiveStatus.VIOLATIONS.value

        ChatMessageDao.update_message_model(chat_message)
        MessageSessionDao.update_sensitive_status(chat_message.chat_id, SensitiveStatus.VIOLATIONS)

    @staticmethod
    def delete_message(user_id: int, message_id: str) -> None:
        """Delete a message by ID."""
        ChatMessageDao.delete_by_message_id(user_id, message_id)

    @staticmethod
    def like_response(data: ChatInput) -> None:
        """Process like/dislike with session counter updates."""
        message_id = data.message_id
        message = ChatMessageDao.get_message_by_id(data.message_id)
        if not message:
            raise NotFoundError.http_exception()

        if message.liked == data.liked:
            return

        like_count = 0
        dislike_count = 0
        if message.liked == LikedType.UNRATED.value:
            if data.liked == LikedType.LIKED.value:
                like_count = 1
            elif data.liked == LikedType.DISLIKED.value:
                dislike_count = 1
        elif message.liked == LikedType.LIKED.value:
            like_count = -1
            if data.liked == LikedType.DISLIKED.value:
                dislike_count = 1
        elif message.liked == LikedType.DISLIKED.value:
            dislike_count = -1
            if data.liked == LikedType.LIKED.value:
                like_count = 1

        message.liked = data.liked
        ChatMessageDao.update_message_model(message)
        logger.info('k=s act=liked message_id={} liked={}', message_id, data.liked)

        MessageSessionDao.add_like_count(message.chat_id, like_count)
        MessageSessionDao.add_dislike_count(message.chat_id, dislike_count)

    @staticmethod
    def mark_copied(message_id: int) -> None:
        """Mark a message as copied with session counter update."""
        message = ChatMessageDao.get_message_by_id(message_id)
        if not message:
            raise NotFoundError.http_exception()
        if message.copied != 1:
            ChatMessageDao.update_message_copied(message_id, 1)
            MessageSessionDao.add_copied_count(message.chat_id, 1)

    @staticmethod
    def comment_on_answer(message_id: int, comment: str) -> None:
        """Add a comment to a message answer."""
        comment_answer(message_id, comment)

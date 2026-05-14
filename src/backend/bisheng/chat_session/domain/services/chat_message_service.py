from typing import Optional

from loguru import logger

from bisheng.api.services.chat_imp import comment_answer
from bisheng.api.v1.schemas import AddChatMessages, ChatInput
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, ServerError, UnAuthorizedError
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao, LikedType
from bisheng.database.models.session import MessageSessionDao, SensitiveStatus


class ChatMessageService:
    """Chat message CRUD and feedback services."""

    @staticmethod
    def add_qa_messages(data: AddChatMessages, login_user: UserPayload, request_ip: str) -> list:
        """Add a Q&A message pair. Creates session if needed.

        Returns the saved message list.
        """
        import json

        logger.debug(f'gateway add_chat_messages {data}')
        flow_id = data.flow_id
        chat_id = data.chat_id
        if not chat_id or not flow_id:
            raise ServerError.http_exception()

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
        )
        message_dbs = ChatMessageDao.insert_batch([human_message, bot_message])
        MessageSessionDao.update_sensitive_status(chat_id, SensitiveStatus.VIOLATIONS)

        from bisheng.chat_session.domain.chat import ChatSessionService
        ChatSessionService.get_or_create_session(chat_id, flow_id, login_user, request_ip)

        return message_dbs

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

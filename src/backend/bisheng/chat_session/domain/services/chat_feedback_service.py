from loguru import logger

from bisheng.chat_session.domain.feedback import feedback_allowed, feedback_fields
from bisheng.chat_session.domain.repositories.implementations.chat_feedback_repository_impl import (
    ChatFeedbackRepositoryImpl,
)
from bisheng.chat_session.domain.schemas.feedback import CommentMessageInput, LikeMessageInput
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session


class ChatFeedbackService:
    @staticmethod
    async def update(
        message_id: int, user: UserPayload, *, liked: int | None = None, comment: str | None = None
    ) -> dict:
        # 领域入口同样验证参数, 防止内部调用绕过端点校验。
        if liked is not None:
            liked = LikeMessageInput(message_id=message_id, liked=liked).liked
        if comment is not None:
            comment = CommentMessageInput(message_id=message_id, comment=comment).comment
        tenant_id = get_current_tenant_id() or getattr(user, "tenant_id", None)
        if tenant_id is None:
            raise UnAuthorizedError.http_exception()
        async with get_async_db_session() as session:
            async with session.begin():
                repo = ChatFeedbackRepositoryImpl(session)
                message = await repo.lock_message(message_id)
                if message is None:
                    raise NotFoundError.http_exception()
                if message.user_id != user.user_id or message.tenant_id != tenant_id:
                    raise UnAuthorizedError.http_exception()
                if not feedback_allowed(message):
                    raise UnAuthorizedError.http_exception(msg="该消息不支持评价")
                chat = await repo.lock_chat(message.chat_id)
                if chat is None or chat.is_delete:
                    raise NotFoundError.http_exception()
                if chat.user_id != user.user_id or chat.tenant_id != tenant_id:
                    raise UnAuthorizedError.http_exception()
                if liked is not None:
                    previous = message.liked or 0
                    chat.like = (chat.like or 0) + int(liked == 1) - int(previous == 1)
                    chat.dislike = (chat.dislike or 0) + int(liked == 2) - int(previous == 2)
                    message.liked = liked
                if comment is not None:
                    message.remark = comment
                await repo.flush()
                result = feedback_fields(message)
                result.pop("feedback_allowed")
            logger.info(
                "chat_feedback_saved message_id={} user_id={} liked={}", message_id, user.user_id, result["liked"]
            )
            return result

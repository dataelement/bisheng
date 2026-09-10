from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.chat_session.domain.repositories.interfaces.chat_feedback_repository import ChatFeedbackRepository
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession


class ChatFeedbackRepositoryImpl(BaseRepositoryImpl[ChatMessage, int], ChatFeedbackRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session, ChatMessage)

    async def lock_message(self, message_id: int) -> ChatMessage | None:
        result = await self.session.exec(select(ChatMessage).where(ChatMessage.id == message_id).with_for_update())
        return result.first()

    async def lock_chat(self, chat_id: str) -> MessageSession | None:
        # 同一会话下不同回答的评价也要串行更新, 避免累计数丢失。
        result = await self.session.exec(
            select(MessageSession).where(MessageSession.chat_id == chat_id).with_for_update()
        )
        return result.first()

    async def flush(self) -> None:
        await self.session.flush()

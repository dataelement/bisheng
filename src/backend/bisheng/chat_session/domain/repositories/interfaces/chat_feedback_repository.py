from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession


class ChatFeedbackRepository(BaseRepository[ChatMessage, int], ABC):
    @abstractmethod
    async def list_comments(self, chat_ids: list[str]) -> list[dict]: ...

    @abstractmethod
    async def lock_message(self, message_id: int) -> ChatMessage | None: ...

    @abstractmethod
    async def lock_chat(self, chat_id: str) -> MessageSession | None: ...

    @abstractmethod
    async def flush(self) -> None: ...

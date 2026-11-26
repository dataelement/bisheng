"""Conversation persistence injected by the owning business entry point."""

from contextlib import AbstractContextManager
from typing import Any, Protocol


class ConversationPersistencePort(Protocol):
    def scope(self, chat_id: str, resource_id: str, user_id: int) -> AbstractContextManager: ...

    def save(self, message: Any, new_session: Any = None) -> tuple[Any, Any]: ...

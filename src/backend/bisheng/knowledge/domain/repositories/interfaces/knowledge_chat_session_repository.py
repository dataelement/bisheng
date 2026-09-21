from abc import ABC, abstractmethod
from dataclasses import dataclass

from bisheng.database.models.session import MessageSession

MAX_KNOWLEDGE_CHAT_REHOME_FLOWS = 500


@dataclass(frozen=True)
class KnowledgeChatSessionRehomeResult:
    matched_count: int
    updated_count: int


class KnowledgeChatSessionRepository(ABC):
    """Persistence contract for F068 knowledge-space session entry semantics."""

    @abstractmethod
    async def list_by_effective_entry(
        self,
        entry_flow_id: str,
        user_id: int,
    ) -> list[MessageSession]:
        """List the user's active sessions currently visible at an entry."""

    @abstractmethod
    async def get_by_chat_and_effective_entry(
        self,
        chat_id: str,
        entry_flow_id: str,
        user_id: int,
    ) -> MessageSession | None:
        """Return one active session only when it belongs to the requested entry."""

    @abstractmethod
    async def find_first_by_effective_entry(
        self,
        entry_flow_id: str,
        user_id: int,
    ) -> MessageSession | None:
        """Return the newest active session at an entry."""

    @abstractmethod
    async def rehome_by_flows(
        self,
        source_root_flow_id: str,
        source_flow_ids: list[str],
    ) -> KnowledgeChatSessionRehomeResult:
        """Set the root entry for active, not-yet-rehomed sessions in exact flows."""

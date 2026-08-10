from __future__ import annotations

from abc import ABC, abstractmethod

from bisheng.knowledge.domain.schemas.knowledge_parse_queue_schema import (
    KnowledgeParseQueueTicket,
    KnowledgeParseTicketSnapshot,
)


class KnowledgeParseQueueRepository(ABC):
    @abstractmethod
    async def create_publishing(self, ticket: KnowledgeParseQueueTicket) -> int: ...

    @abstractmethod
    async def mark_queued(self, ticket: KnowledgeParseQueueTicket) -> bool: ...

    @abstractmethod
    async def remove_ticket(self, ticket: KnowledgeParseQueueTicket) -> None: ...

    @abstractmethod
    async def get_file_ticket_snapshots(
        self,
        *,
        tenant_id: int,
        knowledge_id: int,
        file_ids: list[int],
    ) -> dict[int, list[KnowledgeParseTicketSnapshot]]: ...

    @abstractmethod
    async def active_attempt_count(self) -> int: ...

    @abstractmethod
    async def waiting_ticket_count(self) -> int: ...

from abc import ABC, abstractmethod
from datetime import datetime

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextAggregateType,
    KnowledgeFulltextDesiredAction,
    KnowledgeFulltextOutbox,
)


class KnowledgeFulltextOutboxRepository(ABC):
    @abstractmethod
    async def validate_storage(self) -> None: ...

    @abstractmethod
    async def list_by_ids(self, outbox_ids: list[int]) -> list[KnowledgeFulltextOutbox]: ...

    @abstractmethod
    async def list_auto_repair_candidates(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[KnowledgeFulltextOutbox]: ...

    @abstractmethod
    async def request_sync(
        self,
        *,
        aggregate_type: KnowledgeFulltextAggregateType,
        aggregate_id: int,
        desired_action: KnowledgeFulltextDesiredAction,
        trigger_type: str,
        tenant_id: int,
        max_retries: int,
        knowledge_id: int | None = None,
    ) -> KnowledgeFulltextOutbox: ...

    @abstractmethod
    async def claim(
        self,
        *,
        outbox_id: int,
        revision: int,
        lease_owner: str,
        now: datetime,
        lease_until: datetime,
    ) -> KnowledgeFulltextOutbox | None: ...

    @abstractmethod
    async def mark_success(
        self,
        *,
        outbox_id: int,
        revision: int,
        lease_owner: str,
        now: datetime,
    ) -> bool: ...

    @abstractmethod
    async def request_auto_repair(
        self,
        *,
        outbox_id: int,
        revision: int,
        lease_owner: str | None,
        fingerprint: str,
        error_type: str,
        now: datetime,
    ) -> str: ...

    @abstractmethod
    async def claim_auto_repair(
        self,
        *,
        outbox_id: int,
        fingerprint: str,
        lease_owner: str,
        now: datetime,
        lease_until: datetime,
    ) -> KnowledgeFulltextOutbox | None: ...

    @abstractmethod
    async def finish_auto_repair(
        self,
        *,
        outbox_id: int,
        fingerprint: str,
        lease_owner: str,
        success: bool,
        error_type: str | None,
        now: datetime,
    ) -> bool: ...

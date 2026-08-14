"""供业务事务写入全文同步意图的薄领域服务。"""

from __future__ import annotations

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextAggregateType,
    KnowledgeFulltextDesiredAction,
    KnowledgeFulltextOutbox,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_outbox_repository import (
    KnowledgeFulltextOutboxRepository,
)


class KnowledgeFulltextEventService:
    def __init__(
        self,
        repository: KnowledgeFulltextOutboxRepository,
        *,
        multi_tenant_enabled: bool,
        max_retries: int = 8,
    ):
        if multi_tenant_enabled:
            raise ValueError("knowledge fulltext index is not compatible with multi-tenant mode")
        self.repository = repository
        self.max_retries = max_retries

    async def request_file_sync(
        self,
        *,
        file_id: int,
        knowledge_id: int,
        trigger_type: str,
        tenant_id: int,
    ) -> KnowledgeFulltextOutbox:
        return await self._request_file(
            file_id=file_id,
            knowledge_id=knowledge_id,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type=trigger_type,
            tenant_id=tenant_id,
        )

    async def request_file_delete(
        self,
        *,
        file_id: int,
        knowledge_id: int | None,
        trigger_type: str,
        tenant_id: int,
    ) -> KnowledgeFulltextOutbox:
        return await self._request_file(
            file_id=file_id,
            knowledge_id=knowledge_id,
            desired_action=KnowledgeFulltextDesiredAction.DELETE_CURRENT,
            trigger_type=trigger_type,
            tenant_id=tenant_id,
        )

    async def request_knowledge_fanout(
        self,
        *,
        knowledge_id: int,
        trigger_type: str,
        tenant_id: int,
    ) -> KnowledgeFulltextOutbox:
        return await self._request_knowledge(
            knowledge_id=knowledge_id,
            desired_action=KnowledgeFulltextDesiredAction.FANOUT_CURRENT,
            trigger_type=trigger_type,
            tenant_id=tenant_id,
        )

    async def request_knowledge_delete(
        self,
        *,
        knowledge_id: int,
        trigger_type: str,
        tenant_id: int,
    ) -> KnowledgeFulltextOutbox:
        return await self._request_knowledge(
            knowledge_id=knowledge_id,
            desired_action=KnowledgeFulltextDesiredAction.DELETE_SCOPE,
            trigger_type=trigger_type,
            tenant_id=tenant_id,
        )

    async def _request_file(
        self,
        *,
        file_id: int,
        knowledge_id: int | None,
        desired_action: KnowledgeFulltextDesiredAction,
        trigger_type: str,
        tenant_id: int,
    ) -> KnowledgeFulltextOutbox:
        return await self.repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=file_id,
            knowledge_id=knowledge_id,
            desired_action=desired_action,
            trigger_type=trigger_type,
            tenant_id=tenant_id,
            max_retries=self.max_retries,
        )

    async def _request_knowledge(
        self,
        *,
        knowledge_id: int,
        desired_action: KnowledgeFulltextDesiredAction,
        trigger_type: str,
        tenant_id: int,
    ) -> KnowledgeFulltextOutbox:
        return await self.repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.KNOWLEDGE,
            aggregate_id=knowledge_id,
            knowledge_id=knowledge_id,
            desired_action=desired_action,
            trigger_type=trigger_type,
            tenant_id=tenant_id,
            max_retries=self.max_retries,
        )

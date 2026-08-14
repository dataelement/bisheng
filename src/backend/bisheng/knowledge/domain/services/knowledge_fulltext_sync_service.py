"""把已领取的文件或知识库 Outbox 收敛到当前全文索引状态。"""

from __future__ import annotations

from datetime import datetime

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextAggregateType,
    KnowledgeFulltextDesiredAction,
    KnowledgeFulltextOutbox,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_chunk_repository import (
    KnowledgeFulltextChunkRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_engagement_repository import (
    KnowledgeFulltextEngagementRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_index_repository import (
    KnowledgeFulltextIndexRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_outbox_repository import (
    KnowledgeFulltextOutboxRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_source_repository import (
    KnowledgeFulltextSourceRepository,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_document_service import (
    KnowledgeFulltextDocumentService,
    KnowledgeFulltextProjectionAction,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_rebuild_service import (
    KnowledgeFulltextProjectionNotReadyError,
    KnowledgeFulltextRebuildService,
)


class KnowledgeFulltextSyncService:
    def __init__(
        self,
        *,
        outbox_repository: KnowledgeFulltextOutboxRepository,
        source_repository: KnowledgeFulltextSourceRepository,
        chunk_repository: KnowledgeFulltextChunkRepository,
        index_repository: KnowledgeFulltextIndexRepository,
        rebuild_service: KnowledgeFulltextRebuildService,
        document_service: KnowledgeFulltextDocumentService,
        fanout_batch_size: int,
        max_retries: int = 8,
        engagement_repository: KnowledgeFulltextEngagementRepository | None = None,
    ):
        self.outbox_repository = outbox_repository
        self.source_repository = source_repository
        self.chunk_repository = chunk_repository
        self.index_repository = index_repository
        self.rebuild_service = rebuild_service
        self.document_service = document_service
        self.fanout_batch_size = fanout_batch_size
        self.max_retries = max_retries
        self.engagement_repository = engagement_repository

    async def sync_claimed(
        self,
        row: KnowledgeFulltextOutbox,
        *,
        lease_owner: str,
        now: datetime,
    ) -> str:
        if row.aggregate_type == KnowledgeFulltextAggregateType.FILE.value:
            return await self._sync_file(row, lease_owner=lease_owner, now=now)
        if row.aggregate_type == KnowledgeFulltextAggregateType.KNOWLEDGE.value:
            return await self._sync_knowledge(row, lease_owner=lease_owner, now=now)
        raise ValueError(f"unsupported fulltext aggregate type: {row.aggregate_type}")

    async def _sync_file(
        self,
        row: KnowledgeFulltextOutbox,
        *,
        lease_owner: str,
        now: datetime,
    ) -> str:
        file_id = int(row.aggregate_id)
        snapshot = await self.source_repository.get_current_snapshot(file_id)
        action = (
            KnowledgeFulltextProjectionAction.DELETE if snapshot is None else self.document_service.decide(snapshot)
        )
        if action == KnowledgeFulltextProjectionAction.RETRY:
            raise KnowledgeFulltextProjectionNotReadyError("projection or RAG chunks are not ready")

        document = None
        if action == KnowledgeFulltextProjectionAction.UPSERT:
            index_name = await self.source_repository.get_knowledge_index_name(snapshot.knowledge_id)
            if not index_name:
                raise KnowledgeFulltextProjectionNotReadyError("knowledge RAG index is not ready")
            chunks = await self.chunk_repository.list_all(
                index_name=index_name,
                file_id=file_id,
                knowledge_id=snapshot.knowledge_id,
            )
            rebuilt = self.rebuild_service.rebuild(
                chunks,
                file_id=file_id,
                knowledge_id=snapshot.knowledge_id,
            )
            engagement = None
            if self.engagement_repository is not None:
                engagement = (await self.engagement_repository.get_totals([file_id]))[file_id]
            document = self.document_service.build(
                snapshot,
                content=rebuilt.content,
                chunk_count=rebuilt.chunk_count,
                content_hash=rebuilt.content_hash,
                sync_revision=row.desired_revision,
                indexed_at=now,
                engagement=engagement,
            )

        if not await self.outbox_repository.is_current_lease(
            outbox_id=int(row.id),
            revision=row.desired_revision,
            lease_owner=lease_owner,
            now=now,
        ):
            await self.outbox_repository.release_pending(
                outbox_id=int(row.id),
                revision=row.desired_revision,
                lease_owner=lease_owner,
            )
            return "stale"

        if action == KnowledgeFulltextProjectionAction.UPSERT:
            await self.index_repository.upsert(document)
            result = "upsert"
        elif action == KnowledgeFulltextProjectionAction.DELETE:
            await self.index_repository.delete(file_id)
            result = "delete"
        else:
            result = "keep"
        await self.outbox_repository.mark_success(
            outbox_id=int(row.id),
            revision=row.desired_revision,
            lease_owner=lease_owner,
            now=now,
        )
        return result

    async def _sync_knowledge(
        self,
        row: KnowledgeFulltextOutbox,
        *,
        lease_owner: str,
        now: datetime,
    ) -> str:
        knowledge_id = int(row.aggregate_id)
        if row.desired_action == KnowledgeFulltextDesiredAction.DELETE_SCOPE.value:
            if not await self.outbox_repository.is_current_lease(
                outbox_id=int(row.id),
                revision=row.desired_revision,
                lease_owner=lease_owner,
                now=now,
            ):
                await self.outbox_repository.release_pending(
                    outbox_id=int(row.id),
                    revision=row.desired_revision,
                    lease_owner=lease_owner,
                )
                return "stale"
            await self.index_repository.delete_scope(knowledge_id)
            await self.outbox_repository.mark_success(
                outbox_id=int(row.id),
                revision=row.desired_revision,
                lease_owner=lease_owner,
                now=now,
            )
            return "delete_scope"
        if row.desired_action != KnowledgeFulltextDesiredAction.FANOUT_CURRENT.value:
            raise ValueError(f"unsupported knowledge fulltext action: {row.desired_action}")

        after_file_id = None
        if row.fanout_cursor:
            after_file_id = int(row.fanout_cursor.get("file_id"))
        file_ids = await self.source_repository.list_file_ids(
            knowledge_id=knowledge_id,
            after_file_id=after_file_id,
            limit=self.fanout_batch_size,
        )
        for file_id in file_ids:
            await self.outbox_repository.request_sync(
                aggregate_type=KnowledgeFulltextAggregateType.FILE,
                aggregate_id=file_id,
                knowledge_id=knowledge_id,
                desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
                trigger_type=row.trigger_type,
                tenant_id=row.tenant_id,
                max_retries=self.max_retries,
            )
        cursor = {"file_id": file_ids[-1]} if file_ids else row.fanout_cursor
        await self.outbox_repository.save_fanout_cursor(
            outbox_id=int(row.id),
            revision=row.desired_revision,
            lease_owner=lease_owner,
            cursor=cursor,
        )
        if len(file_ids) < self.fanout_batch_size:
            await self.outbox_repository.mark_success(
                outbox_id=int(row.id),
                revision=row.desired_revision,
                lease_owner=lease_owner,
                now=now,
            )
            return "fanout_complete"
        await self.outbox_repository.release_pending(
            outbox_id=int(row.id),
            revision=row.desired_revision,
            lease_owner=lease_owner,
        )
        return "fanout_pending"

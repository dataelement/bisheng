from __future__ import annotations

import logging
from datetime import datetime, timezone

from bisheng.knowledge.domain.models.knowledge_file import (
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_parse_queue_repository import (
    KnowledgeParseQueueRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_parse_queue_schema import (
    KnowledgeParsePositionState,
    KnowledgeParseQueuePositionItem,
    KnowledgeParseQueuePositionsResponse,
    KnowledgeParseTicketState,
)

logger = logging.getLogger(__name__)


class KnowledgeParseQueueQueryService:
    def __init__(
        self,
        *,
        file_repository: KnowledgeFileRepository,
        visibility_service,
        authorization_service,
        queue_service: KnowledgeParseQueueService,
        login_user,
    ):
        self.file_repository = file_repository
        self.visibility_service = visibility_service
        self.authorization_service = authorization_service
        self.queue_service = queue_service
        self.login_user = login_user

    async def query(
        self,
        *,
        knowledge_id: int,
        file_ids: list[int],
    ) -> KnowledgeParseQueuePositionsResponse:
        space = await self.authorization_service.require_parse_queue_read(knowledge_id)
        candidates = await self.file_repository.find_by_ids_in_knowledge(file_ids, knowledge_id)
        visible_files = await self.visibility_service.filter_visible(
            login_user=self.login_user,
            knowledge_id=knowledge_id,
            files=candidates,
        )
        return await self.queue_service.get_positions(
            tenant_id=int(space.tenant_id),
            knowledge_id=knowledge_id,
            files=visible_files,
        )


class KnowledgeParseQueueService:
    def __init__(self, queue_repository: KnowledgeParseQueueRepository):
        self.queue_repository = queue_repository

    async def get_positions(
        self,
        *,
        tenant_id: int,
        knowledge_id: int,
        files: list[KnowledgeFile],
    ) -> KnowledgeParseQueuePositionsResponse:
        as_of = datetime.now(timezone.utc)
        file_ids = [int(file.id) for file in files if file.id is not None]
        try:
            snapshots_by_file = await self.queue_repository.get_file_ticket_snapshots(
                tenant_id=tenant_id,
                knowledge_id=knowledge_id,
                file_ids=file_ids,
            )
            active_count = await self.queue_repository.active_attempt_count()
            waiting_count = await self.queue_repository.waiting_ticket_count()
        except Exception:
            logger.exception(
                "knowledge parse queue position lookup failed tenant_id=%s knowledge_id=%s file_ids=%s",
                tenant_id,
                knowledge_id,
                file_ids,
            )
            return KnowledgeParseQueuePositionsResponse(
                items=[self._fallback_item(file) for file in files],
                active_count=0,
                waiting_count=None,
                as_of=as_of,
            )

        items: list[KnowledgeParseQueuePositionItem] = []
        for file in files:
            snapshots = snapshots_by_file.get(int(file.id), [])
            processing = sorted(
                (
                    ticket
                    for ticket in snapshots
                    if ticket.state is KnowledgeParseTicketState.PROCESSING and ticket.active_attempt_count > 0
                ),
                key=lambda ticket: ticket.sequence,
            )
            if processing:
                items.append(
                    KnowledgeParseQueuePositionItem(
                        file_id=int(file.id),
                        state=KnowledgeParsePositionState.PROCESSING,
                    )
                )
                continue

            queued = sorted(
                (
                    ticket
                    for ticket in snapshots
                    if ticket.state is KnowledgeParseTicketState.QUEUED and ticket.ahead_waiting_count is not None
                ),
                key=lambda ticket: (ticket.priority.celery_priority, ticket.sequence),
            )
            if queued:
                items.append(
                    KnowledgeParseQueuePositionItem(
                        file_id=int(file.id),
                        state=KnowledgeParsePositionState.QUEUED,
                        ahead_waiting_count=queued[0].ahead_waiting_count,
                    )
                )
                continue
            items.append(self._fallback_item(file))

        return KnowledgeParseQueuePositionsResponse(
            items=items,
            active_count=active_count,
            waiting_count=waiting_count,
            as_of=as_of,
        )

    @staticmethod
    def _fallback_item(file: KnowledgeFile) -> KnowledgeParseQueuePositionItem:
        in_flight = file.status in {
            KnowledgeFileStatus.WAITING.value,
            KnowledgeFileStatus.PROCESSING.value,
        }
        return KnowledgeParseQueuePositionItem(
            file_id=int(file.id),
            state=(KnowledgeParsePositionState.UNAVAILABLE if in_flight else KnowledgeParsePositionState.NOT_QUEUED),
        )

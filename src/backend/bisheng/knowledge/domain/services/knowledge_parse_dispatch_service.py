from __future__ import annotations

import logging
import uuid
from typing import Any

from bisheng.common.constants.enums.knowledge_parse_priority import KnowledgeParsePriority
from bisheng.core.config.celery_queues import KNOWLEDGE_PARSE_QUEUE
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_parse_queue_redis_repository import (
    KnowledgeParseQueueRedisRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_parse_queue_schema import (
    KnowledgeParseAttemptKind,
    KnowledgeParseQueueTicket,
)
from bisheng.knowledge.domain.services.knowledge_parse_priority_snapshot_service import (
    KnowledgeParsePrioritySnapshotService,
)
from bisheng.role.domain.repositories.implementations.role_priority_repository_impl import (
    RolePriorityRepositoryImpl,
)
from bisheng.role.domain.services.knowledge_parse_priority_service import (
    KnowledgeParsePriorityService,
)
from bisheng.utils.async_utils import run_async_safe

logger = logging.getLogger(__name__)


class KnowledgeParseDispatchService:
    """Publish one broker message for each file parsing attempt."""

    def __init__(
        self,
        snapshot_service: KnowledgeParsePrioritySnapshotService | None = None,
        queue_repository: KnowledgeParseQueueRedisRepository | None = None,
        ticket_id_factory=None,
    ):
        self.snapshot_service = snapshot_service
        self.queue_repository = queue_repository or KnowledgeParseQueueRedisRepository()
        self.ticket_id_factory = ticket_id_factory or (lambda: str(uuid.uuid4()))

    async def dispatch(
        self,
        *,
        attempt_kind: KnowledgeParseAttemptKind | str,
        file_id: int,
        preview_cache_key: str | None = None,
        callback_url: str | None = None,
        operator_user_id: int | None = None,
        operator_is_global_super: bool | None = None,
        tenant_id: int | None = None,
        knowledge_id: int | None = None,
        task: Any = None,
    ) -> str:
        attempt_kind = KnowledgeParseAttemptKind(attempt_kind)
        priority, file_tenant_id, file_knowledge_id = await self._get_dispatch_context(
            file_id=file_id,
            operator_user_id=operator_user_id,
            operator_is_global_super=operator_is_global_super,
        )
        tenant_id = tenant_id or file_tenant_id or get_current_tenant_id()
        knowledge_id = knowledge_id or file_knowledge_id
        ticket_id = self.ticket_id_factory()
        task = task or self._load_task(attempt_kind)
        headers = {
            "knowledge_parse_priority": priority.value,
            "knowledge_parse_attempt_kind": attempt_kind.value,
            "knowledge_parse_queue_ticket_id": ticket_id,
            "knowledge_parse_file_id": file_id,
        }
        if tenant_id is not None:
            headers["tenant_id"] = int(tenant_id)
        if knowledge_id is not None:
            headers["knowledge_id"] = int(knowledge_id)

        ticket = None
        if tenant_id is not None and knowledge_id is not None:
            ticket = KnowledgeParseQueueTicket(
                queue_ticket_id=ticket_id,
                tenant_id=int(tenant_id),
                knowledge_id=int(knowledge_id),
                file_id=file_id,
                attempt_kind=attempt_kind,
                priority=priority,
            )
            try:
                await self.queue_repository.create_publishing(ticket)
            except Exception:
                logger.exception(
                    "knowledge parse queue index create failed ticket_id=%s file_id=%s tenant_id=%s attempt_kind=%s",
                    ticket_id,
                    file_id,
                    tenant_id,
                    attempt_kind.value,
                )
        try:
            result = task.apply_async(
                args=[file_id, preview_cache_key, callback_url],
                queue=KNOWLEDGE_PARSE_QUEUE,
                priority=priority.celery_priority,
                headers=headers,
                task_id=ticket_id,
            )
        except Exception:
            logger.exception(
                "knowledge parse task publish failed file_id=%s attempt_kind=%s priority=%s",
                file_id,
                attempt_kind.value,
                priority.value,
            )
            if ticket is not None:
                try:
                    await self.queue_repository.remove_ticket(ticket)
                except Exception:
                    logger.exception(
                        "knowledge parse queue index publish cleanup failed ticket_id=%s file_id=%s",
                        ticket_id,
                        file_id,
                    )
            raise
        if ticket is not None:
            try:
                await self.queue_repository.mark_queued(ticket)
            except Exception:
                logger.exception(
                    "knowledge parse queue index queued transition failed ticket_id=%s file_id=%s",
                    ticket_id,
                    file_id,
                )
        return str(getattr(result, "id", "") or ticket_id)

    def dispatch_sync(self, **kwargs: Any) -> str:
        return run_async_safe(self.dispatch(**kwargs), timeout=None)

    async def _get_dispatch_context(
        self,
        *,
        file_id: int,
        operator_user_id: int | None,
        operator_is_global_super: bool | None,
    ) -> tuple[KnowledgeParsePriority, int | None, int | None]:
        if self.snapshot_service is not None:
            return (
                await self.snapshot_service.get_or_create(
                    file_id=file_id,
                    operator_user_id=operator_user_id,
                    operator_is_global_super=operator_is_global_super,
                ),
                None,
                None,
            )

        async with get_async_db_session() as session:
            file_repository = KnowledgeFileRepositoryImpl(session)
            snapshot_service = KnowledgeParsePrioritySnapshotService(
                file_repository,
                KnowledgeParsePriorityService(RolePriorityRepositoryImpl(session)),
            )
            priority = await snapshot_service.get_or_create(
                file_id=file_id,
                operator_user_id=operator_user_id,
                operator_is_global_super=operator_is_global_super,
            )
            file = await file_repository.find_by_id(file_id)
            return (
                priority,
                int(file.tenant_id) if file and file.tenant_id is not None else None,
                int(file.knowledge_id) if file else None,
            )

    @staticmethod
    def _load_task(attempt_kind: KnowledgeParseAttemptKind) -> Any:
        from bisheng.worker.knowledge.file_worker import (
            parse_knowledge_file_celery,
            retry_knowledge_file_celery,
        )

        return (
            parse_knowledge_file_celery
            if attempt_kind is KnowledgeParseAttemptKind.INITIAL
            else retry_knowledge_file_celery
        )


async def dispatch_knowledge_parse_task(**kwargs: Any) -> str:
    return await KnowledgeParseDispatchService().dispatch(**kwargs)


def dispatch_knowledge_parse_task_sync(**kwargs: Any) -> str:
    return KnowledgeParseDispatchService().dispatch_sync(**kwargs)

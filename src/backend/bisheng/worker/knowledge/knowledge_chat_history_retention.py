from time import monotonic, time

from loguru import logger

from bisheng.knowledge.domain.repositories.implementations.knowledge_chat_session_repository_impl import (
    KnowledgeChatSessionRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_space_chat_history_retention_service import (
    KnowledgeSpaceChatHistoryRetentionService,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

TASK_NAME = "bisheng.worker.knowledge.knowledge_chat_history_retention.rehome_knowledge_chat_sessions"


@bisheng_celery.task(bind=True, name=TASK_NAME, acks_late=True, max_retries=3)
def rehome_knowledge_chat_sessions(
    self,
    *,
    source_space_id: int,
    source_flow_ids: list[str],
    reason: str,
    dispatched_at_ms: int,
) -> dict[str, int]:
    started = monotonic()
    try:
        result = run_async_task(
            lambda: _rehome(
                source_space_id=source_space_id,
                source_flow_ids=source_flow_ids,
            )
        )
        duration_ms = int((monotonic() - started) * 1000)
        queue_delay_ms = max(0, int(time() * 1000) - dispatched_at_ms - duration_ms)
        logger.info(
            "knowledge_chat_entry.rehome source_space={} reason={} flow_count={} "
            "matched_count={} updated_count={} queue_delay_ms={} duration_ms={} retry_count={}",
            source_space_id,
            reason,
            len(source_flow_ids),
            result["matched_count"],
            result["updated_count"],
            queue_delay_ms,
            duration_ms,
            self.request.retries,
        )
        return result
    except Exception as exc:
        logger.exception(
            "knowledge_chat_entry.task_failed stage=execute source_space={} reason={} source_flows={} retry_count={}",
            source_space_id,
            reason,
            source_flow_ids,
            self.request.retries,
        )
        retry_countdown = min(30, 2 ** (self.request.retries + 1))
        raise self.retry(exc=exc, countdown=retry_countdown)


async def _rehome(
    *,
    source_space_id: int,
    source_flow_ids: list[str],
) -> dict[str, int]:
    repository = KnowledgeChatSessionRepositoryImpl()
    service = KnowledgeSpaceChatHistoryRetentionService(repository)
    result = await service.rehome_by_flows(source_space_id, source_flow_ids)
    return {
        "matched_count": result.matched_count,
        "updated_count": result.updated_count,
    }

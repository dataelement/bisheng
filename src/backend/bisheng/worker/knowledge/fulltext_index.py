"""全文索引 Outbox Dispatcher 与 Consumer。"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from uuid import uuid4

from elasticsearch import AsyncElasticsearch
from loguru import logger
from pymysql.err import OperationalError as PyMySQLOperationalError
from sqlalchemy.exc import OperationalError

from bisheng.common.services.config_service import settings
from bisheng.core.config.celery_queues import DEFAULT_CELERY_QUEUE, KNOWLEDGE_PARSE_QUEUE
from bisheng.core.context.tenant import current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.core.search.elasticsearch.manager import get_es_connection, get_statistics_es_connection
from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextAggregateType,
    KnowledgeFulltextDesiredAction,
    KnowledgeFulltextOutbox,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_chunk_repository_impl import (
    KnowledgeFulltextChunkRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_engagement_repository_impl import (
    KnowledgeFulltextEngagementRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_index_repository_impl import (
    KnowledgeFulltextIndexRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_outbox_repository_impl import (
    KnowledgeFulltextOutboxRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_source_repository_impl import (
    KnowledgeFulltextSourceRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_auto_repair_service import (
    KnowledgeFulltextAutoRepairDecision,
    KnowledgeFulltextAutoRepairService,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_dispatch_service import (
    dispatch_knowledge_fulltext_outbox_async,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_document_service import (
    KnowledgeFulltextDocumentService,
    KnowledgeFulltextProjectionAction,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_rebuild_service import (
    KnowledgeFulltextRebuildService,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_sync_service import (
    KnowledgeFulltextSyncService,
)
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


def register_fulltext_beat_schedule() -> None:
    schedule = dict(bisheng_celery.conf.beat_schedule or {})
    schedule.setdefault(
        "dispatch_knowledge_fulltext_outbox",
        {
            "task": constants.KNOWLEDGE_FULLTEXT_DISPATCH_TASK,
            "schedule": constants.KNOWLEDGE_FULLTEXT_DISPATCH_INTERVAL_SECONDS,
        },
    )
    bisheng_celery.conf.beat_schedule = schedule


register_fulltext_beat_schedule()


@bisheng_celery.task(
    acks_late=True,
    name="bisheng.worker.knowledge.fulltext_index.dispatch",
)
def dispatch_knowledge_fulltext_outbox() -> int:
    return run_async_task(_dispatch)


@bisheng_celery.task(
    acks_late=True,
    time_limit=720,
    soft_time_limit=700,
    name="bisheng.worker.knowledge.fulltext_index.consume",
)
def consume_knowledge_fulltext_outbox(outbox_id: int, revision: int) -> bool:
    return run_async_task(
        lambda: _consume(
            outbox_id=int(outbox_id),
            revision=int(revision),
        )
    )


@bisheng_celery.task(
    acks_late=True,
    time_limit=900,
    soft_time_limit=880,
    name="bisheng.worker.knowledge.fulltext_index.repair_source",
)
def repair_knowledge_fulltext_source(outbox_id: int, revision: int, fingerprint: str) -> bool:
    return _run_auto_repair(
        outbox_id=int(outbox_id),
        revision=int(revision),
        fingerprint=str(fingerprint),
    )


def publish_knowledge_fulltext_outbox(
    *,
    outbox_id: int,
    revision: int,
    dispatch_source: str,
) -> None:
    tenant_token = current_tenant_id.set(None)
    try:
        consume_knowledge_fulltext_outbox.apply_async(
            kwargs={
                "outbox_id": outbox_id,
                "revision": revision,
            },
            queue=DEFAULT_CELERY_QUEUE,
            retry=False,
        )
    finally:
        current_tenant_id.reset(tenant_token)
    logger.bind(
        outbox_id=outbox_id,
        revision=revision,
        dispatch_source=dispatch_source,
        status="published",
    ).info("knowledge fulltext outbox published")


def publish_knowledge_fulltext_auto_repair(
    *,
    outbox_id: int,
    revision: int,
    fingerprint: str,
    dispatch_source: str,
) -> None:
    tenant_token = current_tenant_id.set(None)
    try:
        repair_knowledge_fulltext_source.apply_async(
            kwargs={
                "outbox_id": outbox_id,
                "revision": revision,
                "fingerprint": fingerprint,
            },
            queue=KNOWLEDGE_PARSE_QUEUE,
            retry=False,
        )
    finally:
        current_tenant_id.reset(tenant_token)
    logger.bind(
        outbox_id=outbox_id,
        revision=revision,
        fingerprint_prefix=fingerprint[:12],
        dispatch_source=dispatch_source,
        status="published",
    ).info("knowledge fulltext auto repair published")


async def _dispatch() -> int:
    async with get_async_db_session() as session:
        repository = KnowledgeFulltextOutboxRepositoryImpl(session)

        def sender(*, outbox_id: int, revision: int) -> None:
            publish_knowledge_fulltext_outbox(
                outbox_id=outbox_id,
                revision=revision,
                dispatch_source="beat_compensation",
            )

        fulltext_count = await dispatch_knowledge_fulltext_outbox_async(
            multi_tenant_enabled=settings.multi_tenant.enabled,
            repository=repository,
            sender=sender,
        )
    repair_count = await _dispatch_auto_repairs()
    logger.bind(
        status="dispatched",
        dispatched_count=fulltext_count,
        repair_dispatched_count=repair_count,
    ).info("knowledge fulltext outbox dispatch completed")
    return fulltext_count + repair_count


async def _dispatch_auto_repairs() -> int:
    dispatches: list[tuple[int, int, str]] = []
    now = datetime.now()
    async with get_async_db_session() as session:
        repository = KnowledgeFulltextOutboxRepositoryImpl(session)
        source_repository = KnowledgeFulltextSourceRepositoryImpl(session)
        candidates = await repository.list_auto_repair_candidates(
            now=now,
            limit=constants.KNOWLEDGE_FULLTEXT_AUTO_REPAIR_BATCH_SIZE,
        )
        for row in candidates:
            payload = dict(row.payload_snapshot or {})
            repair = dict(payload.get("fulltext_auto_repair") or {})
            fingerprint = str(repair.get("fingerprint") or "")
            if row.error_summary in {
                "KnowledgeFulltextAutoRepairRequested:repair_pending",
                "KnowledgeFulltextAutoRepairProcessing:repair_processing",
            }:
                if fingerprint:
                    dispatches.append((int(row.id), int(row.desired_revision), fingerprint))
                continue

            error_type = str(row.error_summary or "").partition(":")[0]
            decision = KnowledgeFulltextAutoRepairService.decide_error_type(
                error_type,
                retry_count=int(row.retry_count),
            )
            if decision is not KnowledgeFulltextAutoRepairDecision.REQUEST:
                continue
            source = await source_repository.get_auto_repair_source(int(row.aggregate_id))
            if source is None:
                continue
            fingerprint = KnowledgeFulltextAutoRepairService.fingerprint(source)
            result = await repository.request_auto_repair(
                outbox_id=int(row.id),
                revision=int(row.desired_revision),
                lease_owner=None,
                fingerprint=fingerprint,
                error_type=error_type,
                now=now,
            )
            if result in {"requested", "already_requested"}:
                dispatches.append((int(row.id), int(row.desired_revision), fingerprint))
        await session.commit()

    published = 0
    for outbox_id, revision, fingerprint in dispatches:
        try:
            publish_knowledge_fulltext_auto_repair(
                outbox_id=outbox_id,
                revision=revision,
                fingerprint=fingerprint,
                dispatch_source="beat_compensation",
            )
            published += 1
        except Exception:
            logger.bind(
                outbox_id=outbox_id,
                revision=revision,
                fingerprint_prefix=fingerprint[:12],
                status="publish_failed",
            ).exception("knowledge fulltext auto repair publish failed")
    return published


async def _consume(*, outbox_id: int, revision: int) -> bool:
    lease_owner = uuid4().hex
    now = datetime.now()
    row_snapshot = None
    try:
        constants.ensure_runtime_compatible(multi_tenant_enabled=settings.multi_tenant.enabled)
        async with get_async_db_session() as session:
            outbox_repository = KnowledgeFulltextOutboxRepositoryImpl(session)
            row = await outbox_repository.claim(
                outbox_id=outbox_id,
                revision=revision,
                lease_owner=lease_owner,
                now=now,
                lease_until=now + timedelta(seconds=constants.KNOWLEDGE_FULLTEXT_LEASE_TTL_SECONDS),
            )
            row_snapshot = KnowledgeFulltextOutbox.model_validate(row.model_dump()) if row is not None else None
            await session.commit()
            if row_snapshot is None:
                return False

        es_client = await get_es_connection()
        statistics_es_client = await get_statistics_es_connection()
        index_repository = KnowledgeFulltextIndexRepositoryImpl(es_client)
        await index_repository.ensure_index()
        started_at = datetime.now()
        result = await _sync_claimed_with_db_retry(
            row_snapshot=row_snapshot,
            lease_owner=lease_owner,
            es_client=es_client,
            statistics_es_client=statistics_es_client,
            index_repository=index_repository,
        )
        duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
        logger.bind(
            outbox_id=outbox_id,
            aggregate_type=row_snapshot.aggregate_type,
            aggregate_id=row_snapshot.aggregate_id,
            file_id=(row_snapshot.aggregate_id if row_snapshot.aggregate_type == "file" else None),
            knowledge_id=row_snapshot.knowledge_id,
            revision=revision,
            trigger=row_snapshot.trigger_type,
            status=result,
            duration_ms=duration_ms,
        ).info("knowledge fulltext sync completed")
        return True
    except Exception as exc:
        repair_dispatch = None
        async with get_async_db_session() as failure_session:
            failure_repository = KnowledgeFulltextOutboxRepositoryImpl(failure_session)
            decision = KnowledgeFulltextAutoRepairService.decide(
                exc,
                retry_count=int(row_snapshot.retry_count) if row_snapshot is not None else 0,
            )
            repair_result = "ignored"
            if (
                decision is KnowledgeFulltextAutoRepairDecision.REQUEST
                and row_snapshot is not None
                and row_snapshot.aggregate_type == "file"
            ):
                source_repository = KnowledgeFulltextSourceRepositoryImpl(failure_session)
                source = await source_repository.get_auto_repair_source(int(row_snapshot.aggregate_id))
                if source is not None:
                    fingerprint = KnowledgeFulltextAutoRepairService.fingerprint(source)
                    repair_result = await failure_repository.request_auto_repair(
                        outbox_id=outbox_id,
                        revision=revision,
                        lease_owner=lease_owner,
                        fingerprint=fingerprint,
                        error_type=type(exc).__name__,
                        now=datetime.now(),
                    )
                    if repair_result in {"requested", "already_requested"}:
                        repair_dispatch = (fingerprint, repair_result)
            if repair_result in {"ignored", "stale"}:
                await failure_repository.mark_failure(
                    outbox_id=outbox_id,
                    revision=revision,
                    lease_owner=lease_owner,
                    now=datetime.now(),
                    error_summary=type(exc).__name__,
                    retry_base_seconds=constants.KNOWLEDGE_FULLTEXT_RETRY_BASE_SECONDS,
                    retry_max_seconds=constants.KNOWLEDGE_FULLTEXT_RETRY_MAX_SECONDS,
                )
            await failure_session.commit()
        if repair_dispatch is not None:
            fingerprint, repair_result = repair_dispatch
            try:
                publish_knowledge_fulltext_auto_repair(
                    outbox_id=outbox_id,
                    revision=revision,
                    fingerprint=fingerprint,
                    dispatch_source="consumer_failure",
                )
            except Exception:
                logger.bind(
                    outbox_id=outbox_id,
                    revision=revision,
                    fingerprint_prefix=fingerprint[:12],
                    repair_result=repair_result,
                    status="publish_failed",
                ).exception("knowledge fulltext auto repair publish failed")
        logger.bind(
            outbox_id=outbox_id,
            revision=revision,
            status="failed",
            error_type=type(exc).__name__,
        ).exception("knowledge fulltext sync failed")
        return False


async def _sync_claimed_with_db_retry(
    *,
    row_snapshot: KnowledgeFulltextOutbox,
    lease_owner: str,
    es_client: AsyncElasticsearch,
    statistics_es_client: AsyncElasticsearch,
    index_repository: KnowledgeFulltextIndexRepositoryImpl,
) -> str:
    max_attempts = constants.KNOWLEDGE_FULLTEXT_DB_RETRY_MAX_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            return await _sync_claimed_once(
                row_snapshot=row_snapshot,
                lease_owner=lease_owner,
                es_client=es_client,
                statistics_es_client=statistics_es_client,
                index_repository=index_repository,
            )
        except OperationalError as exc:
            error_code = _mysql_operational_error_code(exc)
            if not _should_retry_fanout_transaction(row_snapshot, error_code) or attempt >= max_attempts:
                raise
            delay_seconds = _db_retry_delay_seconds(attempt)
            logger.bind(
                outbox_id=row_snapshot.id,
                knowledge_id=row_snapshot.knowledge_id,
                revision=row_snapshot.desired_revision,
                attempt=attempt,
                max_attempts=max_attempts,
                mysql_error_code=error_code,
                retry_delay_seconds=round(delay_seconds, 3),
            ).warning("knowledge fulltext fanout transaction lock conflict; retrying")
            await asyncio.sleep(delay_seconds)
    raise RuntimeError("unreachable knowledge fulltext database retry state")


async def _sync_claimed_once(
    *,
    row_snapshot: KnowledgeFulltextOutbox,
    lease_owner: str,
    es_client: AsyncElasticsearch,
    statistics_es_client: AsyncElasticsearch,
    index_repository: KnowledgeFulltextIndexRepositoryImpl,
) -> str:
    async with get_async_db_session() as session:
        sync_service = KnowledgeFulltextSyncService(
            outbox_repository=KnowledgeFulltextOutboxRepositoryImpl(session),
            source_repository=KnowledgeFulltextSourceRepositoryImpl(session),
            chunk_repository=KnowledgeFulltextChunkRepositoryImpl(
                es_client,
                page_size=constants.KNOWLEDGE_FULLTEXT_CHUNK_PAGE_SIZE,
            ),
            index_repository=index_repository,
            rebuild_service=KnowledgeFulltextRebuildService(
                max_overlap_chars=constants.KNOWLEDGE_FULLTEXT_MAX_OVERLAP_CHARS
            ),
            document_service=KnowledgeFulltextDocumentService(
                index_schema_version=constants.KNOWLEDGE_FULLTEXT_INDEX_SCHEMA_VERSION
            ),
            fanout_batch_size=constants.KNOWLEDGE_FULLTEXT_FANOUT_BATCH_SIZE,
            max_retries=constants.KNOWLEDGE_FULLTEXT_MAX_RETRIES,
            engagement_repository=KnowledgeFulltextEngagementRepositoryImpl(
                daily_client=es_client,
                raw_client=statistics_es_client,
            ),
        )
        result = await sync_service.sync_claimed(
            row_snapshot,
            lease_owner=lease_owner,
            now=datetime.now(),
        )
        await session.commit()
        return result


def _mysql_operational_error_code(exc: OperationalError) -> int | None:
    if not isinstance(exc.orig, PyMySQLOperationalError):
        return None
    args = getattr(exc.orig, "args", ())
    if not args:
        return None
    try:
        return int(args[0])
    except (TypeError, ValueError):
        return None


def _should_retry_fanout_transaction(row: KnowledgeFulltextOutbox, error_code: int | None) -> bool:
    return (
        error_code in {1205, 1213}
        and row.aggregate_type == KnowledgeFulltextAggregateType.KNOWLEDGE.value
        and row.desired_action == KnowledgeFulltextDesiredAction.FANOUT_CURRENT.value
    )


def _db_retry_delay_seconds(attempt: int) -> float:
    base_delay = constants.KNOWLEDGE_FULLTEXT_DB_RETRY_BASE_SECONDS * (2 ** max(0, attempt - 1))
    lower_bound = min(constants.KNOWLEDGE_FULLTEXT_DB_RETRY_MAX_SECONDS, base_delay)
    upper_bound = min(constants.KNOWLEDGE_FULLTEXT_DB_RETRY_MAX_SECONDS, base_delay * 3)
    return random.uniform(lower_bound, upper_bound)


async def _claim_auto_repair(*, outbox_id: int, fingerprint: str, lease_owner: str):
    now = datetime.now()
    async with get_async_db_session() as session:
        repository = KnowledgeFulltextOutboxRepositoryImpl(session)
        row = await repository.claim_auto_repair(
            outbox_id=outbox_id,
            fingerprint=fingerprint,
            lease_owner=lease_owner,
            now=now,
            lease_until=now + timedelta(seconds=constants.KNOWLEDGE_FULLTEXT_AUTO_REPAIR_LEASE_SECONDS),
        )
        snapshot = KnowledgeFulltextOutbox.model_validate(row.model_dump()) if row is not None else None
        await session.commit()
        return snapshot


async def _load_auto_repair_context(file_id: int):
    async with get_async_db_session() as session:
        repository = KnowledgeFulltextSourceRepositoryImpl(session)
        return (
            await repository.get_auto_repair_source(file_id),
            await repository.get_current_snapshot(file_id),
        )


async def _finish_auto_repair(
    *,
    outbox_id: int,
    fingerprint: str,
    lease_owner: str,
    success: bool,
    error_type: str | None,
) -> bool:
    async with get_async_db_session() as session:
        result = await KnowledgeFulltextOutboxRepositoryImpl(session).finish_auto_repair(
            outbox_id=outbox_id,
            fingerprint=fingerprint,
            lease_owner=lease_owner,
            success=success,
            error_type=error_type,
            now=datetime.now(),
        )
        await session.commit()
        return result


async def _run_logical_entry_projection_repair(
    *,
    file_id: int,
    tenant_id: int,
    lease_owner: str,
) -> bool:
    async with get_async_db_session() as session:
        repository = KnowledgeFileRepositoryImpl(session)
        requested = await repository.request_projection_rebuild(file_id)
        if not requested:
            await session.rollback()
            return False
        await session.commit()

    async with get_async_db_session() as session:
        from bisheng.worker.knowledge.document_projection import (
            _build_document_projection_service,
        )

        file_repository = KnowledgeFileRepositoryImpl(session)
        service = await _build_document_projection_service(
            session=session,
            file_repository=file_repository,
            document_repository=KnowledgeDocumentRepositoryImpl(session),
            version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
            tenant_id=tenant_id,
        )
        result = await service.process_entry(
            tenant_id=tenant_id,
            entry_id=file_id,
            lease_owner=f"fulltext-repair:{lease_owner}",
        )
        return result.status == "ready"


def _run_auto_repair(*, outbox_id: int, revision: int, fingerprint: str) -> bool:
    lease_owner = uuid4().hex
    row = run_async_task(
        lambda: _claim_auto_repair(
            outbox_id=outbox_id,
            fingerprint=fingerprint,
            lease_owner=lease_owner,
        )
    )
    if row is None:
        return False

    from bisheng.knowledge.domain.models.knowledge_file import (
        KnowledgeFileDao,
        KnowledgeFileEntryType,
        KnowledgeFileStatus,
    )
    from bisheng.worker.knowledge.file_worker import run_retry_knowledge_parse_lifecycle

    file_id = int(row.aggregate_id)
    source, snapshot = run_async_task(lambda: _load_auto_repair_context(file_id))
    eligible_snapshot = (
        snapshot.model_copy(update={"status": str(KnowledgeFileStatus.SUCCESS.value)}) if snapshot is not None else None
    )
    source_is_current = (
        source is not None
        and KnowledgeFulltextAutoRepairService.fingerprint(source) == fingerprint
        and eligible_snapshot is not None
        and KnowledgeFulltextDocumentService.decide(eligible_snapshot) is KnowledgeFulltextProjectionAction.UPSERT
    )
    if not source_is_current:
        run_async_task(
            lambda: _finish_auto_repair(
                outbox_id=outbox_id,
                fingerprint=fingerprint,
                lease_owner=lease_owner,
                success=False,
                error_type="KnowledgeFulltextAutoRepairSourceChanged",
            )
        )
        return False

    files = KnowledgeFileDao.get_file_by_ids([file_id])
    if not files or files[0].status not in {
        KnowledgeFileStatus.SUCCESS.value,
        KnowledgeFileStatus.WAITING.value,
        KnowledgeFileStatus.PROCESSING.value,
    }:
        run_async_task(
            lambda: _finish_auto_repair(
                outbox_id=outbox_id,
                fingerprint=fingerprint,
                lease_owner=lease_owner,
                success=False,
                error_type="KnowledgeFulltextAutoRepairFileNotEligible",
            )
        )
        return False

    file = files[0]
    try:
        if file.entry_type in {
            KnowledgeFileEntryType.PUBLISH.value,
            KnowledgeFileEntryType.SHARE.value,
        }:
            if file.tenant_id is None:
                run_async_task(
                    lambda: _finish_auto_repair(
                        outbox_id=outbox_id,
                        fingerprint=fingerprint,
                        lease_owner=lease_owner,
                        success=False,
                        error_type="KnowledgeFulltextAutoRepairTenantMissing",
                    )
                )
                return False
            success = run_async_task(
                lambda: _run_logical_entry_projection_repair(
                    file_id=file_id,
                    tenant_id=int(file.tenant_id),
                    lease_owner=lease_owner,
                )
            )
            run_async_task(
                lambda: _finish_auto_repair(
                    outbox_id=outbox_id,
                    fingerprint=fingerprint,
                    lease_owner=lease_owner,
                    success=success,
                    error_type=(None if success else "KnowledgeFulltextAutoRepairProjectionFailed"),
                )
            )
            logger.bind(
                outbox_id=outbox_id,
                revision=revision,
                file_id=file_id,
                repair_mode="projection",
                fingerprint_prefix=fingerprint[:12],
                status="completed" if success else "failed",
            ).info("knowledge fulltext auto repair completed")
            return success

        if file.entry_type not in {None, KnowledgeFileEntryType.MANAGER.value} or not file.object_name:
            run_async_task(
                lambda: _finish_auto_repair(
                    outbox_id=outbox_id,
                    fingerprint=fingerprint,
                    lease_owner=lease_owner,
                    success=False,
                    error_type="KnowledgeFulltextAutoRepairPhysicalSourceMissing",
                )
            )
            return False

        if file.status == KnowledgeFileStatus.SUCCESS.value:
            KnowledgeFileDao.update_file_status(
                [file_id],
                KnowledgeFileStatus.WAITING,
                "knowledge_fulltext_auto_repair",
            )
        run_retry_knowledge_parse_lifecycle(file_id)
        refreshed = KnowledgeFileDao.get_file_by_ids([file_id])
        success = bool(refreshed and refreshed[0].status == KnowledgeFileStatus.SUCCESS.value)
        run_async_task(
            lambda: _finish_auto_repair(
                outbox_id=outbox_id,
                fingerprint=fingerprint,
                lease_owner=lease_owner,
                success=success,
                error_type=None if success else "KnowledgeFulltextAutoRepairParseFailed",
            )
        )
        logger.bind(
            outbox_id=outbox_id,
            revision=revision,
            file_id=file_id,
            repair_mode="parse",
            fingerprint_prefix=fingerprint[:12],
            status="completed" if success else "failed",
        ).info("knowledge fulltext auto repair completed")
        return success
    except Exception:
        logger.bind(
            outbox_id=outbox_id,
            revision=revision,
            file_id=file_id,
            fingerprint_prefix=fingerprint[:12],
            status="crashed",
        ).exception("knowledge fulltext auto repair crashed")
        raise

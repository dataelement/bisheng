from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextAggregateType,
    KnowledgeFulltextDesiredAction,
    KnowledgeFulltextOutbox,
    KnowledgeFulltextOutboxStatus,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_outbox_repository_impl import (
    KnowledgeFulltextOutboxRepositoryImpl,
)


async def make_session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeFulltextOutbox.__table__.create)
    return engine, AsyncSession(engine, expire_on_commit=False)


async def test_request_sync_merges_revisions_without_committing_caller_transaction():
    engine, session = await make_session()
    try:
        repository = KnowledgeFulltextOutboxRepositoryImpl(session)
        first = await repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=7,
            knowledge_id=9,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type="parse_success",
            tenant_id=1,
            max_retries=8,
        )
        second = await repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=7,
            knowledge_id=10,
            desired_action=KnowledgeFulltextDesiredAction.DELETE_CURRENT,
            trigger_type="file_deleted",
            tenant_id=1,
            max_retries=8,
        )

        assert first.id == second.id
        assert second.desired_revision == 2
        assert second.desired_action == "delete_current"
        assert second.knowledge_id == 10
        assert second.status == "pending"
        await session.rollback()

        assert await session.get(KnowledgeFulltextOutbox, first.id) is None
    finally:
        await session.close()
        await engine.dispose()


async def test_claim_and_success_use_lease_and_revision_cas():
    engine, session = await make_session()
    now = datetime(2026, 1, 1)
    try:
        repository = KnowledgeFulltextOutboxRepositoryImpl(session)
        row = await repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=7,
            knowledge_id=9,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type="parse_success",
            tenant_id=1,
            max_retries=8,
        )
        await session.commit()

        claimed = await repository.claim(
            outbox_id=row.id,
            revision=1,
            lease_owner="worker-a",
            now=now,
            lease_until=now + timedelta(minutes=10),
        )
        duplicate = await repository.claim(
            outbox_id=row.id,
            revision=1,
            lease_owner="worker-b",
            now=now,
            lease_until=now + timedelta(minutes=10),
        )
        wrong_owner = await repository.mark_success(
            outbox_id=row.id,
            revision=1,
            lease_owner="worker-b",
            now=now,
        )
        applied = await repository.mark_success(
            outbox_id=row.id,
            revision=1,
            lease_owner="worker-a",
            now=now,
        )

        assert claimed is not None
        assert duplicate is None
        assert wrong_owner is False
        assert applied is True
        saved = await session.get(KnowledgeFulltextOutbox, row.id)
        assert saved.applied_revision == 1
        assert saved.status == KnowledgeFulltextOutboxStatus.SUCCESS.value
    finally:
        await session.close()
        await engine.dispose()


async def test_failure_backoff_exhaustion_and_new_revision_reactivation():
    engine, session = await make_session()
    now = datetime(2026, 1, 1)
    try:
        repository = KnowledgeFulltextOutboxRepositoryImpl(session)
        row = await repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=7,
            knowledge_id=9,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type="parse_success",
            tenant_id=1,
            max_retries=1,
        )
        await session.commit()
        await repository.claim(
            outbox_id=row.id,
            revision=1,
            lease_owner="worker-a",
            now=now,
            lease_until=now + timedelta(minutes=10),
        )
        assert await repository.mark_failure(
            outbox_id=row.id,
            revision=1,
            lease_owner="worker-a",
            now=now,
            error_summary="secret body must not appear: 正文",
            retry_base_seconds=30,
            retry_max_seconds=60,
        )
        failed = await session.get(KnowledgeFulltextOutbox, row.id)
        assert failed.status == KnowledgeFulltextOutboxStatus.FAILED.value
        assert failed.retry_count == 1
        assert failed.error_summary == "RuntimeError:sync_failed"
        assert (
            await repository.claim(
                outbox_id=row.id,
                revision=1,
                lease_owner="late-duplicate",
                now=now + timedelta(minutes=20),
                lease_until=now + timedelta(minutes=30),
            )
            is None
        )

        reactivated = await repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=7,
            knowledge_id=9,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type="metadata_updated",
            tenant_id=1,
            max_retries=1,
        )
        assert reactivated.desired_revision == 2
        assert reactivated.retry_count == 0
        assert reactivated.status == KnowledgeFulltextOutboxStatus.PENDING.value
    finally:
        await session.close()
        await engine.dispose()


async def test_dispatchable_excludes_retry_exhausted_failed_rows():
    engine, session = await make_session()
    now = datetime(2026, 1, 1)
    try:
        exhausted = KnowledgeFulltextOutbox(
            tenant_id=1,
            aggregate_type="file",
            aggregate_id=7,
            knowledge_id=9,
            desired_action="sync_current",
            desired_revision=1,
            applied_revision=0,
            trigger_type="parse_success",
            status=KnowledgeFulltextOutboxStatus.FAILED.value,
            retry_count=1,
            max_retries=1,
        )
        session.add(exhausted)
        await session.commit()

        rows = await KnowledgeFulltextOutboxRepositoryImpl(session).list_dispatchable(
            now=now,
            limit=100,
        )

        assert rows == []
    finally:
        await session.close()
        await engine.dispose()


async def test_auto_repair_request_and_claim_are_single_winner_per_fingerprint():
    engine, session = await make_session()
    now = datetime(2026, 8, 13, 18, 0, 0)
    try:
        repository = KnowledgeFulltextOutboxRepositoryImpl(session)
        row = await repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=7,
            knowledge_id=9,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type="historical_backfill",
            tenant_id=1,
            max_retries=8,
        )
        await session.commit()
        claimed = await repository.claim(
            outbox_id=row.id,
            revision=1,
            lease_owner="fulltext-worker",
            now=now,
            lease_until=now + timedelta(minutes=10),
        )
        assert claimed is not None

        requested = await repository.request_auto_repair(
            outbox_id=row.id,
            revision=1,
            lease_owner="fulltext-worker",
            fingerprint="a" * 64,
            error_type="KnowledgeFulltextChunkCorruptedError",
            now=now,
        )
        assert requested == "requested"
        await session.commit()

        first_claim = await repository.claim_auto_repair(
            outbox_id=row.id,
            fingerprint="a" * 64,
            lease_owner="repair-worker-a",
            now=now,
            lease_until=now + timedelta(minutes=12),
        )
        await repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=7,
            knowledge_id=9,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type="parse_finalized",
            tenant_id=1,
            max_retries=8,
        )
        duplicate_claim = await repository.claim_auto_repair(
            outbox_id=row.id,
            fingerprint="a" * 64,
            lease_owner="repair-worker-b",
            now=now,
            lease_until=now + timedelta(minutes=12),
        )

        assert first_claim is not None
        assert first_claim.aggregate_id == 7
        assert duplicate_claim is None
    finally:
        await session.close()
        await engine.dispose()


async def test_same_auto_repair_fingerprint_is_exhausted_but_new_source_version_can_request():
    engine, session = await make_session()
    now = datetime(2026, 8, 13, 18, 0, 0)
    try:
        repository = KnowledgeFulltextOutboxRepositoryImpl(session)
        row = await repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=7,
            knowledge_id=9,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type="historical_backfill",
            tenant_id=1,
            max_retries=8,
        )
        await session.commit()

        assert await repository.request_auto_repair(
            outbox_id=row.id,
            revision=1,
            lease_owner=None,
            fingerprint="a" * 64,
            error_type="KnowledgeFulltextChunkCorruptedError",
            now=now,
        ) == "requested"
        assert await repository.request_auto_repair(
            outbox_id=row.id,
            revision=1,
            lease_owner=None,
            fingerprint="a" * 64,
            error_type="KnowledgeFulltextChunkCorruptedError",
            now=now,
        ) == "already_requested"
        claimed = await repository.claim_auto_repair(
            outbox_id=row.id,
            fingerprint="a" * 64,
            lease_owner="repair-worker",
            now=now,
            lease_until=now + timedelta(minutes=12),
        )
        assert claimed is not None
        assert await repository.finish_auto_repair(
            outbox_id=row.id,
            fingerprint="a" * 64,
            lease_owner="repair-worker",
            success=True,
            error_type=None,
            now=now + timedelta(minutes=1),
        )
        assert await repository.request_auto_repair(
            outbox_id=row.id,
            revision=1,
            lease_owner=None,
            fingerprint="a" * 64,
            error_type="KnowledgeFulltextChunkCorruptedError",
            now=now + timedelta(minutes=2),
        ) == "exhausted"
        assert await repository.request_auto_repair(
            outbox_id=row.id,
            revision=1,
            lease_owner=None,
            fingerprint="b" * 64,
            error_type="KnowledgeFulltextChunkCorruptedError",
            now=now,
        ) == "requested"
    finally:
        await session.close()
        await engine.dispose()


async def test_auto_repair_candidates_include_exhausted_source_errors_and_pending_repairs():
    engine, session = await make_session()
    now = datetime(2026, 8, 13, 18, 0, 0)
    try:
        for file_id, error_summary in (
            (7, "KnowledgeFulltextChunkNotReadyError:sync_failed"),
            (8, "KnowledgeFulltextChunkCorruptedError:sync_failed"),
            (9, "KnowledgeFulltextAutoRepairRequested:repair_pending"),
            (10, "ConnectionError:sync_failed"),
        ):
            session.add(
                KnowledgeFulltextOutbox(
                    tenant_id=1,
                    aggregate_type="file",
                    aggregate_id=file_id,
                    knowledge_id=9,
                    desired_action="sync_current",
                    desired_revision=1,
                    applied_revision=0,
                    trigger_type="historical_backfill",
                    status="failed",
                    retry_count=8,
                    max_retries=8,
                    error_summary=error_summary,
                )
            )
        await session.commit()

        rows = await KnowledgeFulltextOutboxRepositoryImpl(session).list_auto_repair_candidates(
            now=now,
            limit=100,
        )

        assert [row.aggregate_id for row in rows] == [7, 8, 9]
    finally:
        await session.close()
        await engine.dispose()


async def test_backfill_preflight_and_bounded_status_read_are_read_only():
    engine, session = await make_session()
    try:
        repository = KnowledgeFulltextOutboxRepositoryImpl(session)
        first = await repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=7,
            knowledge_id=9,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type="historical_backfill",
            tenant_id=1,
            max_retries=8,
        )
        second = await repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=8,
            knowledge_id=9,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type="historical_backfill",
            tenant_id=1,
            max_retries=8,
        )
        await session.commit()

        await repository.validate_storage()
        rows = await repository.list_by_ids([second.id, first.id])

        assert [row.id for row in rows] == [first.id, second.id]
        assert all(row.desired_revision == 1 for row in rows)
    finally:
        await session.close()
        await engine.dispose()

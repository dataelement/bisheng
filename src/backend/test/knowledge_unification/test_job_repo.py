"""T061: durable processing request/item, lease and recovery contracts.

Coverage: AC-49, AC-50, AC-53, AC-54, AC-86. SQLite exercises real SQL
transactions and unique constraints; MySQL/DM8 lock concurrency is separate.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeIdempotencyConflictError, KnowledgeProcessingJobNotFoundError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt
from bisheng.knowledge.domain.repositories.processing_job_repository import (
    NewProcessingItem,
    ProcessingConfiguration,
    ProcessingJobRepository,
)
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget


@pytest.fixture
def job_tenant(tenant_context):
    tenant_context(101)


@pytest.fixture
async def job_session(job_tenant):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn,
                tables=[
                    Knowledge.__table__,
                    KnowledgeProcessingJob.__table__,
                    KnowledgeProcessingItem.__table__,
                    KnowledgeProcessingRetryReceipt.__table__,
                ],
            )
        )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Knowledge(id=1, tenant_id=101, user_id=11, name="one", type=3, model_config_revision=7))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def clock():
    return [datetime(2026, 11, 5, 3, 0)]


@pytest.fixture
def repository(clock):
    return ProcessingJobRepository(clock=lambda: clock[0])


@pytest.fixture
def configuration():
    return ProcessingConfiguration(model_config_revision=7, index_generation="index-7")


def item(file_id):
    return NewProcessingItem(
        target=ResourceVersionTarget(file_id=file_id, document_id=file_id + 100, version_id=file_id + 200),
        expected_space_id=1,
        processing_snapshot={"actual_rule": "unchanged-original"},
    )


async def create(repository, session, configuration, **overrides):
    args = {
        "space_id": 1,
        "kind": "embedding_rebuild",
        "idempotency_key": "request-1",
        "actor_user_id": 11,
        "actor_reference": {"actor_type": "person", "actor_id": "11", "scope_digest": "original"},
        "parameters": {"audit_model_id": "not-authoritative"},
        "configuration": configuration,
        "items": [item(8), item(9)],
    }
    return await repository.acreate(session, **{**args, **overrides})


async def completed_pair(repository, session, configuration):
    created = await create(repository, session, configuration)
    lease = await repository.aclaim(session, created.job.id, configuration=configuration)
    first = await repository.aclaim_next_item(session, lease, configuration=configuration)
    assert await repository.acomplete_item(session, first.lease, configuration=configuration, succeeded=True)
    second = await repository.aclaim_next_item(session, lease, configuration=configuration)
    assert await repository.asave_checkpoint(
        session, second.lease, configuration=configuration, step="source_page", checkpoint={"page": 17}
    )
    assert await repository.acomplete_item(
        session, second.lease, configuration=configuration, succeeded=False, error_code=10915
    )
    finished = await repository.afinalize(session, lease, configuration=configuration)
    return finished, first.item, second.item


async def test_duplicate_request_returns_same_job_and_items(job_session, repository, configuration):
    first = await create(repository, job_session, configuration)
    again = await create(repository, job_session, configuration, items=[item(9), item(8)])
    assert first.job.id == again.job.id
    assert first.reused is False and again.reused is True
    assert first.job.state == "accepted"
    assert first.job.pending_dispatch is True
    assert len((await job_session.exec(select(KnowledgeProcessingJob))).all()) == 1
    assert len((await job_session.exec(select(KnowledgeProcessingItem))).all()) == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"parameters": {"audit_model_id": "another"}},
        {"actor_user_id": 12},
        {"actor_reference": {"actor_type": "person", "actor_id": "11", "scope_digest": "expanded"}},
        {"items": [item(8)]},
    ],
)
async def test_same_key_different_canonical_request_conflicts(job_session, repository, configuration, overrides):
    await create(repository, job_session, configuration)
    with pytest.raises(KnowledgeIdempotencyConflictError):
        await create(repository, job_session, configuration, **overrides)
    assert len((await job_session.exec(select(KnowledgeProcessingJob))).all()) == 1


async def test_creation_joins_owner_transaction(job_session, repository, configuration):
    await create(repository, job_session, configuration)
    await job_session.rollback()
    assert not (await job_session.exec(select(KnowledgeProcessingJob))).all()
    assert not (await job_session.exec(select(KnowledgeProcessingItem))).all()


async def test_duplicate_version_input_does_not_write_partial_job(job_session, repository, configuration):
    with pytest.raises(ValueError, match="duplicate"):
        await create(repository, job_session, configuration, items=[item(8), item(8)])
    assert not (await job_session.exec(select(KnowledgeProcessingJob))).all()


async def test_partial_progress_and_failed_only_retry(job_session, repository, configuration):
    job, success, failed = await completed_pair(repository, job_session, configuration)
    assert job.state == "partial_failed"
    assert (job.total_count, job.succeeded_count, job.failed_count, job.pending_count) == (2, 1, 1, 0)
    original_id = job.id
    retried = await repository.aretry_failed(
        job_session,
        job.id,
        idempotency_key="retry-1",
        expected_job_revision=job.revision,
        actor_user_id=11,
        actor_reference=job.actor_reference,
        configuration=configuration,
    )
    assert retried.job.id == original_id and retried.job.state == "accepted"
    assert success.state == "succeeded"
    assert failed.state == "pending" and failed.checkpoint == {"page": 17}
    lease = await repository.aclaim(job_session, job.id, configuration=configuration)
    next_item = await repository.aclaim_next_item(job_session, lease, configuration=configuration)
    assert next_item.item.id == failed.id
    assert next_item.item.attempt == 2
    assert await repository.acomplete_item(job_session, next_item.lease, configuration=configuration, succeeded=True)
    assert await repository.aclaim_next_item(job_session, lease, configuration=configuration) is None
    finished = await repository.afinalize(job_session, lease, configuration=configuration)
    assert finished.state == "succeeded" and finished.succeeded_count == 2


async def test_retry_key_is_persistent_not_reapplied_after_another_failure(job_session, repository, configuration):
    job, _, failed = await completed_pair(repository, job_session, configuration)
    expected = job.revision
    params = {
        "idempotency_key": "retry-same",
        "expected_job_revision": expected,
        "actor_user_id": 11,
        "actor_reference": job.actor_reference,
        "configuration": configuration,
    }
    retried = await repository.aretry_failed(job_session, job.id, **params)
    assert retried.reused is False
    lease = await repository.aclaim(job_session, job.id, configuration=configuration)
    claimed = await repository.aclaim_next_item(job_session, lease, configuration=configuration)
    await repository.acomplete_item(job_session, claimed.lease, configuration=configuration, succeeded=False)
    await repository.afinalize(job_session, lease, configuration=configuration)
    await job_session.commit()
    await job_session.refresh(job)
    again = await repository.aretry_failed(job_session, job.id, **params)
    assert again.reused is True and again.job.state == "partial_failed"
    assert failed.state == "failed" and failed.attempt == 2
    receipts = (await job_session.exec(select(KnowledgeProcessingRetryReceipt))).all()
    assert len(receipts) == 1 and receipts[0].item_count == 1
    with pytest.raises(KnowledgeIdempotencyConflictError):
        await repository.aretry_failed(job_session, job.id, **{**params, "expected_job_revision": job.revision})


async def test_active_job_lease_cannot_be_claimed_twice(job_session, repository, configuration):
    created = await create(repository, job_session, configuration)
    lease = await repository.aclaim(job_session, created.job.id, configuration=configuration)
    assert lease is not None
    assert await repository.aclaim(job_session, created.job.id, configuration=configuration) is None


async def test_expired_takeover_rejects_old_checkpoint_and_finalize(job_session, repository, configuration, clock):
    created = await create(repository, job_session, configuration)
    first = await repository.aclaim(job_session, created.job.id, configuration=configuration, lease_seconds=10)
    old_item = await repository.aclaim_next_item(job_session, first, configuration=configuration)
    clock[0] += timedelta(seconds=11)
    assert await repository.arenew(job_session, first, configuration=configuration) is None
    second = await repository.aclaim(job_session, created.job.id, configuration=configuration)
    assert second.claim_generation == first.claim_generation + 1
    assert not await repository.asave_checkpoint(
        job_session, old_item.lease, configuration=configuration, step="late", checkpoint={"bad": True}
    )
    assert not await repository.acomplete_item(job_session, old_item.lease, configuration=configuration, succeeded=True)
    new_item = await repository.aclaim_next_item(job_session, second, configuration=configuration)
    assert new_item.item.id == old_item.item.id
    assert new_item.lease.claim_generation == old_item.lease.claim_generation + 1
    assert await repository.acomplete_item(job_session, new_item.lease, configuration=configuration, succeeded=True)


@pytest.mark.parametrize(
    "current",
    [
        ProcessingConfiguration(model_config_revision=8, index_generation="index-7"),
        ProcessingConfiguration(model_config_revision=7, index_generation="replacement-index"),
    ],
)
async def test_new_configuration_marks_obsolete_without_rebinding(job_session, repository, configuration, current):
    created = await create(repository, job_session, configuration)
    assert await repository.aclaim(job_session, created.job.id, configuration=current) is None
    assert created.job.state == "obsolete"
    assert created.job.error_code == 10997
    await job_session.commit()
    assert await repository.aclaim(job_session, created.job.id, configuration=configuration) is None
    assert created.job.parameters == {"audit_model_id": "not-authoritative"}


async def test_configuration_change_before_item_finalize_rejects_result(job_session, repository, configuration):
    created = await create(repository, job_session, configuration)
    lease = await repository.aclaim(job_session, created.job.id, configuration=configuration)
    claimed = await repository.aclaim_next_item(job_session, lease, configuration=configuration)
    assert not await repository.acomplete_item(
        job_session,
        claimed.lease,
        configuration=ProcessingConfiguration(model_config_revision=8, index_generation="index-7"),
        succeeded=True,
    )
    assert created.job.state == "obsolete" and claimed.item.state != "succeeded"


async def test_unrelated_space_changes_do_not_expire_task(job_session, repository, configuration):
    created = await create(repository, job_session, configuration)
    space = await job_session.get(Knowledge, 1)
    space.name = "renamed"
    space.description = "irrelevant"
    space.processing_config_version = 9
    await job_session.flush()
    assert await repository.aclaim(job_session, created.job.id, configuration=configuration) is not None
    assert created.job.scope_manifest[0]["processing_snapshot"] == {"actual_rule": "unchanged-original"}


async def test_pending_items_cannot_make_job_succeeded(job_session, repository, configuration):
    created = await create(repository, job_session, configuration)
    lease = await repository.aclaim(job_session, created.job.id, configuration=configuration)
    assert await repository.afinalize(job_session, lease, configuration=configuration) is None
    assert created.job.state == "running"


async def test_foreign_job_and_space_are_not_available(job_session, repository, configuration):
    created = await create(repository, job_session, configuration)
    token = set_current_tenant_id(202)
    try:
        with pytest.raises(KnowledgeProcessingJobNotFoundError):
            await repository.aget(job_session, created.job.id)
        with pytest.raises(SpaceNotFoundError):
            await create(repository, job_session, configuration, idempotency_key="foreign")
    finally:
        current_tenant_id.reset(token)
    assert created.job.state == "accepted"


async def test_live_item_heartbeat_extends_only_with_live_job_lease(job_session, repository, configuration, clock):
    created = await create(repository, job_session, configuration)
    lease = await repository.aclaim(job_session, created.job.id, configuration=configuration, lease_seconds=10)
    claimed = await repository.aclaim_next_item(job_session, lease, configuration=configuration)
    clock[0] += timedelta(seconds=5)
    renewed_job = await repository.arenew(job_session, lease, configuration=configuration, lease_seconds=30)
    renewed_item = await repository.arenew_item(job_session, claimed.lease, configuration=configuration)
    assert renewed_item.lease_until == renewed_job.lease_until
    clock[0] += timedelta(seconds=7)
    assert await repository.asave_checkpoint(
        job_session, renewed_item, configuration=configuration, step="next-page", checkpoint={"page": 1}
    )
    clock[0] += timedelta(seconds=30)
    assert await repository.arenew_item(job_session, renewed_item, configuration=configuration) is None

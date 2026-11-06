"""T610: real SQL query boundaries, retry provenance and broker recovery CAS."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.knowledge import KnowledgeProcessingJobNotFoundError, ResourceReferenceInvalidError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingConfiguration
from bisheng.worker import tenant_context as workers
from test.knowledge_unification.test_job_repo import (
    clock as clock,
)
from test.knowledge_unification.test_job_repo import (
    completed_pair,
    create,
    item,
)
from test.knowledge_unification.test_job_repo import (
    configuration as configuration,
)
from test.knowledge_unification.test_job_repo import (
    job_session as job_session,
)
from test.knowledge_unification.test_job_repo import (
    job_tenant as job_tenant,
)
from test.knowledge_unification.test_job_repo import (
    repository as repository,
)


@pytest.fixture(autouse=True)
def job_query_tenant_filters(monkeypatch):
    from bisheng.core.database import tenant_filter

    names = tenant_filter._tenant_aware_tables | {
        "knowledge",
        "knowledge_processing_job",
        "knowledge_processing_item",
        "knowledge_processing_retry_receipt",
    }
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    tenant_filter.register_tenant_filter_events()


@pytest.fixture
def actual_processing_task(job_tenant, monkeypatch):
    sender = SimpleNamespace(
        name="bisheng.worker.knowledge.processing_jobs.execute_processing_job",
        request=SimpleNamespace(id="actual-attempt", headers={"tenant_id": 101}, called_directly=False),
    )
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    workers.restore_tenant_context(sender=sender)
    try:
        yield sender
    finally:
        workers.reset_tenant_context(sender=sender)


async def test_failed_attempt_records_actual_counts_and_can_retry_fresh_actor(
    job_session, repository, configuration, actual_processing_task
):
    root = await job_session.get(Knowledge, 1)
    root.index_generation = configuration.index_generation
    await job_session.flush()
    result = await create(repository, job_session, configuration)
    lease = await repository.aclaim(job_session, result.job.id, configuration=configuration)
    first = await repository.aclaim_next_item(job_session, lease, configuration=configuration)
    await repository.acomplete_item(job_session, first.lease, configuration=configuration, succeeded=True)
    second = await repository.aclaim_next_item(job_session, lease, configuration=configuration)
    await repository.asave_checkpoint(
        job_session, second.lease, configuration=configuration, step="page", checkpoint={"page": 2}
    )
    failed = await repository.afail_attempt(
        job_session, result.job.id, expected_job_revision=result.job.revision, error_code=201, lease=lease
    )
    assert failed.state == "partial_failed" and (failed.succeeded_count, failed.failed_count, failed.pending_count) == (
        1,
        1,
        0,
    )
    assert second.item.state == "failed" and second.item.checkpoint == {"page": 2}
    assert not failed.pending_dispatch
    retry = await repository.aretry_failed(
        job_session,
        failed.id,
        idempotency_key="new-authority",
        expected_job_revision=failed.revision,
        actor_user_id=12,
        actor_reference={"actor_id": 12},
        configuration=configuration,
    )
    assert retry.job.state == "accepted" and first.item.state == "succeeded" and second.item.state == "pending"


async def test_failure_cas_reads_actual_configuration_and_never_rebases_from_caller(
    job_session, repository, configuration, actual_processing_task
):
    result = await create(repository, job_session, configuration)
    root = await job_session.get(Knowledge, 1)
    root.model_config_revision = configuration.model_config_revision + 1
    await job_session.flush()
    assert (
        await repository.afail_attempt(
            job_session, result.job.id, expected_job_revision=result.job.revision + 1, error_code=201
        )
        is None
    )
    obsolete = await repository.afail_attempt(
        job_session, result.job.id, expected_job_revision=result.job.revision, error_code=201
    )
    assert obsolete.state == "obsolete" and not obsolete.pending_dispatch


async def test_failure_requires_actual_background_proof(job_session, repository, configuration):
    result = await create(repository, job_session, configuration)
    with pytest.raises(ResourceReferenceInvalidError):
        await repository.afail_attempt(job_session, result.job.id, expected_job_revision=0, error_code=201)


async def test_job_pages_are_complete_and_stable_for_tied_acceptance_time(job_session, repository, configuration):
    jobs = [
        (await create(repository, job_session, configuration, idempotency_key=f"request-{i}")).job for i in range(5)
    ]
    expected = sorted((row.id for row in jobs), reverse=True)
    observed = []
    for page in range(1, 4):
        result = await repository.alist_jobs(job_session, 1, page=page, page_size=2)
        assert result.total == 5
        observed.extend(row.id for row in result.rows)
    assert observed == expected
    assert not (await repository.alist_jobs(job_session, 1, page=1, page_size=2, state="failed")).rows


async def test_request_key_lookup_uses_real_tenant_kind_and_key(job_session, repository, configuration):
    job = (await create(repository, job_session, configuration)).job
    assert await repository.aget_by_request_key(job_session, "embedding_rebuild", "request-1", lock=True) is job
    assert await repository.aget_by_request_key(job_session, "embedding_rebuild", "missing") is None
    assert await repository.aget_by_request_key(job_session, "file_reprocess", "request-1") is None
    token = set_current_tenant_id(202)
    try:
        assert await repository.aget_by_request_key(job_session, "embedding_rebuild", "request-1") is None
    finally:
        current_tenant_id.reset(token)


async def test_item_query_applies_current_visible_scope_before_pagination(job_session, repository, configuration):
    job = (await create(repository, job_session, configuration, items=[item(9), item(8), item(10)])).job
    first = await repository.alist_items(job_session, job.id, page=1, page_size=1, visible_file_ids=(8, 10))
    second = await repository.alist_items(job_session, job.id, page=2, page_size=1, visible_file_ids=(8, 10))
    assert first.total == second.total == 2
    assert [row.file_id for row in (*first.rows, *second.rows)] == [8, 10]
    hidden = await repository.alist_items(job_session, job.id, page=1, page_size=20, visible_file_ids=())
    assert hidden.total == 0 and not hidden.rows
    filtered = await repository.alist_items(
        job_session, job.id, page=1, page_size=20, visible_file_ids=(8, 9, 10), state="failed"
    )
    assert filtered.total == 0


async def test_query_and_dispatch_do_not_cross_tenants(job_session, repository, configuration, clock):
    job = (await create(repository, job_session, configuration)).job
    token = set_current_tenant_id(202)
    try:
        with pytest.raises(SpaceNotFoundError):
            await repository.alist_jobs(job_session, 1, page=1, page_size=20)
        with pytest.raises(KnowledgeProcessingJobNotFoundError):
            await repository.alist_items(job_session, job.id, page=1, page_size=20, visible_file_ids=(8, 9))
        with pytest.raises(KnowledgeProcessingJobNotFoundError):
            await repository.alatest_retry_actor(job_session, job.id)
        assert not await repository.adispatch_candidates(job_session, now=clock[0])
    finally:
        current_tenant_id.reset(token)


async def test_latest_retry_actor_is_durable_and_late_old_key_cannot_replace_it(job_session, repository, configuration):
    job, _, _ = await completed_pair(repository, job_session, configuration)
    assert await repository.alatest_retry_actor(job_session, job.id) == job.actor_reference
    first = {
        "idempotency_key": "retry-first",
        "expected_job_revision": job.revision,
        "actor_user_id": 12,
        "actor_reference": {"actor_user_id": 12, "credential": "first"},
        "configuration": configuration,
    }
    await repository.aretry_failed(job_session, job.id, **first)
    lease = await repository.aclaim(job_session, job.id, configuration=configuration)
    claimed = await repository.aclaim_next_item(job_session, lease, configuration=configuration)
    await repository.acomplete_item(job_session, claimed.lease, configuration=configuration, succeeded=False)
    await repository.afinalize(job_session, lease, configuration=configuration)
    latest = {"actor_user_id": 13, "credential": "current"}
    await repository.aretry_failed(
        job_session,
        job.id,
        idempotency_key="retry-second",
        expected_job_revision=job.revision,
        actor_user_id=13,
        actor_reference=latest,
        configuration=configuration,
    )
    assert (await repository.aretry_failed(job_session, job.id, **first)).reused
    observed = await repository.alatest_retry_actor(job_session, job.id)
    assert observed == latest and job.actor_user_id == 11
    observed["credential"] = "mutated-copy"
    assert await repository.alatest_retry_actor(job_session, job.id) == latest


async def test_dispatch_scan_recovers_accepted_and_expired_running_only(job_session, repository, configuration, clock):
    accepted = (await create(repository, job_session, configuration, idempotency_key="accepted")).job
    running = (await create(repository, job_session, configuration, idempotency_key="running")).job
    obsolete = (await create(repository, job_session, configuration, idempotency_key="obsolete")).job
    await repository.aclaim(job_session, running.id, configuration=configuration, lease_seconds=10)
    await repository.aclaim(
        job_session,
        obsolete.id,
        configuration=ProcessingConfiguration(model_config_revision=8, index_generation="index-7"),
    )
    assert [row.job_id for row in await repository.adispatch_candidates(job_session, now=clock[0])] == [accepted.id]
    clock[0] += timedelta(seconds=11)
    result = await repository.adispatch_candidates(job_session, now=clock[0])
    assert {row.job_id for row in result} == {accepted.id, running.id}
    assert all(row.tenant_id == 101 for row in result)
    pages = []
    cursor = None
    while True:
        page = await repository.adispatch_candidates(job_session, now=clock[0], after_id=cursor, limit=1)
        if not page:
            break
        pages.extend(row.job_id for row in page)
        cursor = page[-1].job_id
    assert pages == sorted({accepted.id, running.id})


@pytest.mark.parametrize("published", [True, False])
async def test_publish_result_keeps_durable_intent_until_a_valid_claim(
    job_session, repository, configuration, clock, published
):
    job = (await create(repository, job_session, configuration)).job
    assert await repository.arecord_dispatch(
        job_session,
        job.id,
        expected_revision=job.revision,
        published=published,
        error_code=None if published else 10000,
        next_at=clock[0] + timedelta(seconds=30),
    )
    assert job.pending_dispatch and job.state == "accepted" and job.dispatch_attempts == 1
    assert not await repository.adispatch_candidates(job_session, now=clock[0])
    clock[0] += timedelta(seconds=31)
    assert [row.job_id for row in await repository.adispatch_candidates(job_session, now=clock[0])] == [job.id]
    await repository.aclaim(job_session, job.id, configuration=configuration, expected_job_revision=job.revision)
    assert job.state == "running" and not job.pending_dispatch


async def test_old_message_or_publish_ack_cannot_take_over_new_retry(job_session, repository, configuration, clock):
    job, _, _ = await completed_pair(repository, job_session, configuration)
    old_revision = job.revision
    await repository.aretry_failed(
        job_session,
        job.id,
        idempotency_key="new-retry",
        expected_job_revision=old_revision,
        actor_user_id=12,
        actor_reference={"actor_user_id": 12},
        configuration=configuration,
    )
    current_revision = job.revision
    assert not await repository.arecord_dispatch(
        job_session, job.id, expected_revision=old_revision, published=True, next_at=clock[0] + timedelta(hours=1)
    )
    assert (
        await repository.aclaim(job_session, job.id, configuration=configuration, expected_job_revision=old_revision)
        is None
    )
    assert job.state == "accepted" and job.revision == current_revision and job.pending_dispatch
    assert (
        await repository.aclaim(
            job_session, job.id, configuration=configuration, expected_job_revision=current_revision
        )
        is not None
    )


async def test_dispatch_update_is_part_of_owner_transaction(job_session, repository, configuration, clock):
    job = (await create(repository, job_session, configuration)).job
    job_id = job.id
    await job_session.commit()
    await repository.arecord_dispatch(
        job_session,
        job_id,
        expected_revision=0,
        published=False,
        error_code=10000,
        next_at=clock[0] + timedelta(minutes=1),
    )
    await job_session.rollback()
    row = await job_session.get(KnowledgeProcessingJob, job_id)
    assert row.dispatch_attempts == 0 and row.pending_dispatch

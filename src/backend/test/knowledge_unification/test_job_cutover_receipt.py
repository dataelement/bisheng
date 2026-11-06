"""T624: actual model Owner/R2 cutover, job acknowledgement and retry.

No model, SourceReadRuntime, scope repository or job method is replaced.
Only FGA/sharing and Celery's current-task transport are fixture boundaries.
"""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.database import tenant_filter
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as Models
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt
from bisheng.knowledge.domain.repositories.processing_job_repository import NewProcessingItem
from bisheng.knowledge.domain.repositories.processing_owner_repository import ProcessingOwnerRepository
from bisheng.worker import tenant_context as workers
from test.knowledge_unification import test_processing_owner as fixtures
from test.knowledge_unification.test_kn_model_bindings import state as business_state

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing


@pytest.fixture
async def cutover(processing, monkeypatch):
    context, owner = processing
    for model in (
        KnowledgeFile,
        KnowledgeDocument,
        KnowledgeDocumentVersion,
        KnowledgeProcessingJob,
        KnowledgeProcessingItem,
        KnowledgeProcessingRetryReceipt,
    ):
        model.__table__.create(context.sync, checkfirst=True)
    names = tenant_filter._tenant_aware_tables | {
        "knowledgefile",
        "knowledge_processing_job",
        "knowledge_processing_item",
        "knowledge_processing_retry_receipt",
    }
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", names)
    async with context.sessions() as session:
        session.add_all(
            [
                KnowledgeFile(id=81, tenant_id=101, knowledge_id=40, file_name="first"),
                KnowledgeFile(id=82, tenant_id=101, knowledge_id=40, file_name="second"),
                KnowledgeDocument(id=80, knowledge_id=40, primary_version_id=181),
                KnowledgeDocumentVersion(id=181, document_id=80, knowledge_file_id=81, version_no=1, is_primary=True),
                KnowledgeDocumentVersion(id=182, document_id=80, knowledge_file_id=82, version_no=2, is_primary=False),
            ]
        )
        await session.commit()
    async with context.sessions() as session:
        actual = await owner.aprepare(session, 40, identity=context.user, parameters={}, operation_id="own-operation")
        versions = await ProcessingOwnerRepository().aload_scope(session, 40, for_update=True)
        created = await owner.jobs.acreate(
            session,
            space_id=40,
            kind="embedding_rebuild",
            idempotency_key="own-job",
            actor_user_id=7,
            actor_reference={"actor_id": 7},
            parameters={"operation_id": "own-operation"},
            configuration=actual.configuration,
            items=[NewProcessingItem(target=row.target, expected_space_id=40) for row in versions],
        )
        job = created.job
        lease = await owner.jobs.aclaim(session, job.id, configuration=actual.configuration)
        first = await owner.jobs.aclaim_next_item(session, lease, configuration=actual.configuration)
        await owner.jobs.acomplete_item(session, first.lease, configuration=actual.configuration, succeeded=True)
        second = await owner.jobs.aclaim_next_item(session, lease, configuration=actual.configuration)
        await owner.jobs.acomplete_item(
            session, second.lease, configuration=actual.configuration, succeeded=False, error_code=10915
        )
        await session.commit()
    sender = SimpleNamespace(
        name="bisheng.worker.knowledge.processing_jobs.execute_processing_job",
        request=SimpleNamespace(id="actual-processing-task", headers={"tenant_id": 101}, called_directly=False),
    )
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    workers.restore_tenant_context(sender=sender)
    try:
        yield context, owner, job.id, lease, actual.configuration
    finally:
        workers.reset_tenant_context(sender=sender)


async def finalize(fixture, session, lease=None):
    _, owner, job_id, original, _ = fixture
    job = await owner.jobs.aget(session, job_id)
    return await owner.afinalize_and_ack(session, job, lease or original)


async def test_actual_same_operation_cutover_advances_expected_but_preserves_acceptance(cutover):
    context, _, _, _, original = cutover
    async with context.sessions() as session:
        job = await finalize(cutover, session)
        assert job.state == "partial_failed"
        assert job.expected_model_config_revision == original.model_config_revision + 1
        assert job.accepted_model_config_revision == original.model_config_revision
        assert job.expected_index_generation == original.index_generation
        await session.commit()
    row = next(row for row in business_state(context)["knowledge"] if row["id"] == 40)
    assert row["model_transition"] is None and row["state"] == 1
    assert row["model_config_revision"] == job.expected_model_config_revision


async def test_caller_rollback_reverts_business_r2_and_job_ack_together(cutover):
    context, _, job_id, _, original = cutover
    before = business_state(context)
    async with context.sessions() as session:
        assert (await finalize(cutover, session)).state == "partial_failed"
        await session.rollback()
    assert business_state(context) == before
    async with context.sessions() as session:
        job = await session.get(KnowledgeProcessingJob, job_id)
        assert job.state == "running" and job.expected_model_config_revision == original.model_config_revision


async def test_r2_failure_cannot_acknowledge_or_publish_model(cutover, monkeypatch):
    context, owner, job_id, _, original = cutover
    before = business_state(context)
    monkeypatch.setattr(
        context.runtime, "aapply_source_bindings", AsyncMock(side_effect=RuntimeError("actual R2 failed"))
    )
    async with context.sessions() as session:
        with pytest.raises(RuntimeError, match="actual R2 failed"):
            await finalize(cutover, session)
        await session.rollback()
    assert business_state(context) == before
    async with context.sessions() as session:
        assert (await owner.jobs.aget(session, job_id)).expected_model_config_revision == original.model_config_revision


@pytest.mark.parametrize("invalid", ["lease", "expired", "pending", "missing_acceptance"])
async def test_old_lease_or_missing_original_evidence_cannot_cut_over(cutover, invalid):
    context, _, job_id, lease, _ = cutover
    before = business_state(context)
    async with context.sessions() as session:
        if invalid == "lease":
            assert await finalize(cutover, session, replace(lease, lease_token="expired-owner")) is None
        elif invalid == "expired":
            job = await session.get(KnowledgeProcessingJob, job_id)
            job.lease_until -= timedelta(days=1)
            await session.flush()
            assert await finalize(cutover, session) is None
        elif invalid == "pending":
            job = await session.get(KnowledgeProcessingJob, job_id)
            item = (await owner_items(cutover, session))[0]
            item.state = "pending"
            await session.flush()
            assert await finalize(cutover, session) is None
        else:
            job = await session.get(KnowledgeProcessingJob, job_id)
            job.accepted_model_config_revision = None
            await session.flush()
            with pytest.raises(ResourceReferenceInvalidError):
                await finalize(cutover, session)
        await session.rollback()
    assert business_state(context) == before


async def owner_items(fixture, session):
    _, owner, job_id, _, _ = fixture
    return (await owner.jobs.alist_items(session, job_id, page=1, page_size=100, visible_file_ids=(81, 82))).rows


async def test_failed_only_retry_after_own_cutover_uses_same_job_and_current_business_model(cutover):
    context, owner, job_id, _, original = cutover
    async with context.sessions() as session:
        job = await finalize(cutover, session)
        current = await owner.aread_current(session, 40, job=job)
        await owner.jobs.aretry_failed(
            session,
            job.id,
            idempotency_key="retry-own",
            expected_job_revision=job.revision,
            actor_user_id=7,
            actor_reference={"actor_id": 7},
            configuration=current.configuration,
        )
        lease = await owner.jobs.aclaim(session, job.id, configuration=current.configuration)
        item = await owner.jobs.aclaim_next_item(session, lease, configuration=current.configuration)
        assert item.item.file_id == 82
        await owner.jobs.acomplete_item(session, item.lease, configuration=current.configuration, succeeded=True)
        assert (await owner.afinalize_and_ack(session, job, lease)).state == "succeeded"
        assert job.id == job_id and job.accepted_model_config_revision == original.model_config_revision
        assert job.expected_model_config_revision == original.model_config_revision + 1
        await session.commit()


async def test_later_same_model_intent_invalidates_the_old_job(cutover):
    context, owner, job_id, _, _ = cutover
    async with context.sessions() as session:
        await finalize(cutover, session)
        await session.commit()
    async with context.sessions() as session:
        new = await Models.aprepare_rebuild(session, 40, 11, login_user=context.user, operation_id="later-same-model")
        await Models.aapply_model_change(session, new)
        await session.commit()
    async with context.sessions() as session:
        job = await owner.jobs.aget(session, job_id)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await owner.aread_current(session, 40, job=job)


async def test_actual_a_to_b_to_a_business_operations_do_not_revive_old_job(cutover):
    context, owner, job_id, _, _ = cutover
    async with context.sessions() as session:
        await finalize(cutover, session)
        await session.commit()
    for selected in (12, 11):
        async with context.sessions() as session:
            plan = await Models.aprepare_rebuild(session, 40, selected, login_user=context.user)
            row = await Models.aapply_model_change(session, plan)
            final = await Models.aprepare_finalization(
                session,
                40,
                operation_id=plan.operation_id,
                expected_model_config_revision=row.model_config_revision,
                expected_index_generation=row.index_generation,
            )
            await Models.aapply_finalization(session, final)
            await session.commit()
    async with context.sessions() as session:
        old = await owner.jobs.aget(session, job_id)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await owner.aread_current(session, 40, job=old)


async def test_repository_refuses_an_unsigned_acknowledgement(cutover):
    context, owner, _, lease, _ = cutover
    async with context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await owner.jobs.aacknowledge_cutover(session, lease, receipt={"before": 1, "after": 2})


async def test_missing_acceptance_cannot_finish_a_retry_after_business_cutover(cutover):
    context, owner, _, _, _ = cutover
    async with context.sessions() as session:
        job = await finalize(cutover, session)
        current = await owner.aread_current(session, 40, job=job)
        await owner.jobs.aretry_failed(
            session,
            job.id,
            idempotency_key="retry-without-audit",
            expected_job_revision=job.revision,
            actor_user_id=7,
            actor_reference={"actor_id": 7},
            configuration=current.configuration,
        )
        lease = await owner.jobs.aclaim(session, job.id, configuration=current.configuration)
        item = await owner.jobs.aclaim_next_item(session, lease, configuration=current.configuration)
        await owner.jobs.acomplete_item(session, item.lease, configuration=current.configuration, succeeded=True)
        job.accepted_model_config_revision = None
        await session.flush()
        with pytest.raises(ResourceReferenceInvalidError):
            await owner.afinalize_and_ack(session, job, lease)

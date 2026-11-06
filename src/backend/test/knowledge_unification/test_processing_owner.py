"""T620: processing reads and prepares through the real model Owner/Core.

Knowledge, model eligibility, full source admission and R2 use real SQLite;
only the existing permission/sharing transport boundaries are doubled.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.database import tenant_filter
from bisheng.knowledge.application import processing_owner as module
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as Models
from bisheng.knowledge.application.processing_owner import KnowledgeProcessingOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt
from bisheng.knowledge.domain.repositories.processing_job_repository import NewProcessingItem, ProcessingConfiguration
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.worker import tenant_context as workers
from test.knowledge_unification import test_kn_model_source as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission


@pytest.fixture
def processing(admission, monkeypatch):
    context, runtime, _, _ = admission
    monkeypatch.setattr(module, "get_knowledge_model_read_runtime", AsyncMock(return_value=runtime))
    return context, KnowledgeProcessingOwner()


async def test_read_uses_actual_current_model_and_ignores_job_model_hint(processing):
    context, owner = processing
    async with context.sessions() as session:
        state = await owner.aread_current(session, 40, identity=context.user)
        assert state.model_id == 11 and state.configuration == ProcessingConfiguration(0, "g0")
        assert state.operation_id is None
        job = SimpleNamespace(
            space_id=40,
            expected_model_config_revision=0,
            expected_index_generation="g0",
            parameters={"operation_id": "irrelevant", "embedding_model_id": 33},
        )
        assert (await owner.aread_current(session, 40, identity=context.user, job=job)).model_id == 11


async def test_prepare_same_model_owns_new_operation_and_same_transaction(processing):
    context, owner = processing
    before = fixtures.fixtures.state(context)
    async with context.sessions() as session:
        prepared = await owner.aprepare(session, 40, identity=context.user, parameters={}, operation_id="job-operation")
        assert prepared.model_id == 11 and prepared.operation_id == "job-operation"
        assert prepared.configuration.model_config_revision == 1
        assert prepared.configuration.index_generation != "g0"
        assert prepared.admitted.slot_key == "model_transition.pending_model_id"
        await session.rollback()
    assert fixtures.fixtures.state(context) == before


async def test_pending_actual_model_not_job_hint_is_used_and_whole_source_must_stay_valid(processing):
    context, owner = processing
    async with context.sessions() as session:
        prepared = await owner.aprepare(
            session, 40, identity=context.user, parameters={"embedding_model_id": 12}, operation_id="new-model"
        )
        job = SimpleNamespace(
            space_id=40,
            expected_model_config_revision=prepared.configuration.model_config_revision,
            expected_index_generation=prepared.configuration.index_generation,
            parameters={"operation_id": "new-model", "embedding_model_id": 33},
        )
        assert (await owner.aread_current(session, 40, job=job)).model_id == 12
        await session.commit()
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
    async with context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await owner.aread_current(session, 40, job=job)


async def test_new_intent_revision_or_generation_rejects_old_job_even_if_model_matches(processing):
    context, owner = processing
    job = SimpleNamespace(
        space_id=40,
        expected_model_config_revision=0,
        expected_index_generation="g0",
        parameters={"operation_id": "old"},
    )
    async with context.sessions() as session:
        change = await Models.aprepare_rebuild(session, 40, 11, login_user=context.user)
        await Models.aapply_model_change(session, change)
        await session.commit()
    async with context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await owner.aread_current(session, 40, job=job)


async def test_owner_rejects_unowned_space_and_parameter_model_is_never_a_read_fallback(processing):
    context, owner = processing
    async with context.sessions() as session, session.begin():
        await session.execute(
            sa.update(Knowledge).where(Knowledge.id == 40, Knowledge.tenant_id == 101).values(model=None)
        )
    async with context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await owner.aread_current(session, 20)
        with pytest.raises(ReferenceCoverageNotReadyError):
            await owner.aread_current(session, 40)


async def test_preview_validates_new_target_without_applying_business_or_r2(processing):
    context, owner = processing
    before = fixtures.fixtures.state(context)
    async with context.sessions() as session:
        preview = await owner.apreview(session, 40, identity=context.user, parameters={"embedding_model_id": 12})
        assert preview.expected_revision == 0 and preview.expected_generation == "g0"
        assert preview.transition["pending_model_id"] == "12"
        await session.commit()
    assert fixtures.fixtures.state(context) == before


async def test_preview_allows_new_valid_target_to_repair_revoked_old_shared_model(processing):
    context, owner = processing
    async with context.sessions() as session:
        # Recreate a separate actual source so this scenario has no in-flight
        # rebuild. No source/R2 mutation is bypassed for the tested request.
        await Models.acreate(
            session,
            Knowledge(id=41, tenant_id=101, user_id=7, name="shared", type=3, model="22", index_generation="g0"),
            login_user=context.user,
            project_created=AsyncMock(),
        )
        await session.commit()
    context.sharing.allowed = frozenset()
    before = fixtures.fixtures.state(context)
    async with context.sessions() as session:
        preview = await owner.apreview(session, 41, identity=context.user, parameters={"embedding_model_id": 12})
        assert preview.model == "12" and preview.transition["current_model_id"] == "12"
        await session.commit()
    assert fixtures.fixtures.state(context) == before


@pytest.fixture
async def retry_fence(processing, monkeypatch):
    context, owner = processing
    for model in (KnowledgeProcessingJob, KnowledgeProcessingItem, KnowledgeProcessingRetryReceipt):
        model.__table__.create(context.sync, checkfirst=True)
    monkeypatch.setattr(
        tenant_filter,
        "_tenant_aware_tables",
        tenant_filter._tenant_aware_tables
        | {"knowledge_processing_job", "knowledge_processing_item", "knowledge_processing_retry_receipt"},
    )
    monkeypatch.setattr(module, "require_business_action", AsyncMock(), raising=False)
    clock = [datetime.now(UTC).replace(tzinfo=None)]
    owner.jobs.clock = lambda: clock[0]
    sender = SimpleNamespace(
        name="bisheng.worker.knowledge.processing_jobs.execute_processing_job",
        request=SimpleNamespace(id="fence-attempt", headers={"tenant_id": 101}, called_directly=False),
    )
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    workers.restore_tenant_context(sender=sender)
    try:
        async with context.sessions() as session:
            actual = await owner.aprepare(session, 40, identity=context.user, parameters={}, operation_id="fenced-job")
            created = await owner.jobs.acreate(
                session,
                space_id=40,
                kind="embedding_rebuild",
                idempotency_key="fenced-job",
                actor_user_id=7,
                actor_reference={"actor_id": 7},
                parameters={"operation_id": "fenced-job"},
                configuration=actual.configuration,
                items=[
                    NewProcessingItem(
                        target=ResourceVersionTarget(file_id=81 + i, document_id=80, version_id=181 + i),
                        expected_space_id=40,
                    )
                    for i in range(2)
                ],
            )
            lease = await owner.jobs.aclaim(session, created.job.id, configuration=actual.configuration)
            for succeeded in (True, False):
                item = await owner.jobs.aclaim_next_item(session, lease, configuration=actual.configuration)
                await owner.jobs.acomplete_item(
                    session, item.lease, configuration=actual.configuration, succeeded=succeeded, error_code=10915
                )
            job = await owner.afinalize_and_ack(session, created.job, lease)
            current = await owner.aread_current(session, 40, job=job)
            await session.commit()
        yield SimpleNamespace(
            context=context, owner=owner, job_id=job.id, configuration=current.configuration, clock=clock
        )
    finally:
        workers.reset_tenant_context(sender=sender)


async def begin_retry(fixture, session, key="retry"):
    job = await fixture.owner.jobs.aget(session, fixture.job_id)
    result = await fixture.owner.jobs.aretry_failed(
        session,
        job.id,
        idempotency_key=key,
        expected_job_revision=job.revision,
        actor_user_id=7,
        actor_reference={"actor_id": 7},
        configuration=fixture.configuration,
    )
    await fixture.owner.abegin_retry_fence(session, result.job, identity=fixture.context.user)
    return result.job


async def test_current_retry_fence_and_receipt_rollback_together(retry_fence):
    fixture = retry_fence
    before = fixtures.fixtures.state(fixture.context)
    async with fixture.context.sessions() as session:
        job = await begin_retry(fixture, session)
        root = await Models.repository.aget(session, 40)
        assert root.state == 3 and root.model_transition is None
        assert (root.model_config_revision, root.index_generation) == (
            fixture.configuration.model_config_revision,
            fixture.configuration.index_generation,
        )
        successful = (
            await fixture.owner.jobs.alist_items(
                session, job.id, page=1, page_size=10, state="succeeded", visible_file_ids=(81, 82)
            )
        ).rows[0]
        assert "retry_fence" not in successful.checkpoint
        await session.rollback()
    assert fixtures.fixtures.state(fixture.context) == before


async def test_fail_and_release_current_fence_are_one_transaction(retry_fence):
    fixture = retry_fence
    async with fixture.context.sessions() as session:
        job = await begin_retry(fixture, session)
        lease = await fixture.owner.jobs.aclaim(session, job.id, configuration=fixture.configuration)
        await session.commit()
    async with fixture.context.sessions() as session:
        failed = await fixture.owner.afail_attempt(
            session, job.id, expected_job_revision=job.revision, error_code=25001, lease=lease
        )
        assert failed.state == "partial_failed" and (await Models.repository.aget(session, 40)).state == 1
        await session.rollback()
    async with fixture.context.sessions() as session:
        assert (await Models.repository.aget(session, 40)).state == 3
        assert (await fixture.owner.jobs.aget(session, job.id)).state == "running"


async def test_same_retry_takeover_can_release_but_old_lease_cannot(retry_fence):
    fixture = retry_fence
    async with fixture.context.sessions() as session:
        job = await begin_retry(fixture, session)
        old = await fixture.owner.jobs.aclaim(session, job.id, configuration=fixture.configuration, lease_seconds=1)
        fixture.clock[0] += timedelta(seconds=2)
        current = await fixture.owner.jobs.aclaim(session, job.id, configuration=fixture.configuration)
        assert (
            await fixture.owner.afail_attempt(
                session, job.id, expected_job_revision=job.revision, error_code=25001, lease=old
            )
            is None
        )
        assert (await Models.repository.aget(session, 40)).state == 3
        assert (
            await fixture.owner.afail_attempt(
                session, job.id, expected_job_revision=job.revision, error_code=25001, lease=current
            )
            is not None
        )
        assert (await Models.repository.aget(session, 40)).state == 1


async def test_rejected_preclaim_releases_only_its_current_retry_and_can_restart(retry_fence):
    fixture = retry_fence
    async with fixture.context.sessions() as session:
        job = await begin_retry(fixture, session)
        failed = await fixture.owner.afail_attempt(
            session, job.id, expected_job_revision=job.revision, error_code=25001
        )
        assert failed.state == "partial_failed" and (await Models.repository.aget(session, 40)).state == 1
        await session.commit()
    async with fixture.context.sessions() as session:
        await begin_retry(fixture, session, key="fresh-authority")
        assert (await Models.repository.aget(session, 40)).state == 3


async def test_owner_retry_coordinates_actual_resource_lock_ledger_and_fence(retry_fence):
    fixture = retry_fence
    async with fixture.context.sessions() as session:
        job = await fixture.owner.jobs.aget(session, fixture.job_id)
        result = await fixture.owner.aretry_failed(
            session,
            job.id,
            identity=fixture.context.user,
            idempotency_key="coordinated",
            expected_job_revision=job.revision,
            actor_user_id=7,
            actor_reference={"actor_id": 7},
        )
        assert not result.reused and result.job.state == "accepted"
        assert (await Models.repository.aget(session, 40)).state == 3


async def test_current_retry_normal_completion_releases_owned_fence(retry_fence):
    fixture = retry_fence
    async with fixture.context.sessions() as session:
        job = await begin_retry(fixture, session)
        lease = await fixture.owner.jobs.aclaim(session, job.id, configuration=fixture.configuration)
        item = await fixture.owner.jobs.aclaim_next_item(session, lease, configuration=fixture.configuration)
        checkpoint = dict(item.item.checkpoint)
        await fixture.owner.jobs.acomplete_item(
            session, item.lease, configuration=fixture.configuration, succeeded=True
        )
        result = await fixture.owner.afinalize_and_ack(session, job, lease)
        assert result.state == "succeeded" and item.item.checkpoint == checkpoint
        assert (await Models.repository.aget(session, 40)).state == 1


async def test_failure_never_releases_another_business_operation(retry_fence):
    fixture = retry_fence
    async with fixture.context.sessions() as session:
        job = await begin_retry(fixture, session)
        root = await Models.repository.aget(session, 40)
        root.model_transition = {"operation_id": "other-operation"}
        await session.flush()
        await fixture.owner.afail_attempt(session, job.id, expected_job_revision=job.revision, error_code=25001)
        assert root.state == 3 and root.model_transition == {"operation_id": "other-operation"}

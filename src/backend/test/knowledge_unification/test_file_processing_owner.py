"""T673: real model/source/version/rule reads and atomic item/file writes."""

import json
from types import SimpleNamespace

import pytest

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeProcessingConflictError
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as Models
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.schemas.processing_settings import ProcessingOverrides
from bisheng.knowledge.rag.knowledge_file_pipeline import FileProcessingResult
from bisheng.worker import tenant_context as workers
from test.knowledge_unification import test_job_service as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application

TARGETS = [{"file_id": 81, "version_id": 181}]


@pytest.fixture
async def files(application, monkeypatch):
    app = application
    async with app.context.sessions() as session:
        for ident in (81, 82):
            row = await session.get(KnowledgeFile, ident)
            row.object_name = f"source/{ident}.txt"
            row.md5 = f"md5-{ident}"
            row.user_metadata = {"preserved": ident}
            row.split_rule = FileProcessBase(knowledge_id=40, chunk_size=333).model_dump_json()
        await session.commit()
    sender = SimpleNamespace(
        name="bisheng.worker.knowledge.processing_jobs.execute_processing_job",
        request=SimpleNamespace(id="owner-native", headers={"tenant_id": 101}, called_directly=False),
    )
    monkeypatch.setattr(workers, "current_task", SimpleNamespace(_get_current_object=lambda: sender))
    workers.restore_tenant_context(sender=sender)
    try:
        yield app
    finally:
        workers.reset_tenant_context(sender=sender)


async def preview(app, session, targets=TARGETS):
    return await app.owner.apreview_file_processing(
        session,
        40,
        identity=app.context.user,
        kind="file_resplit",
        targets=targets,
        overrides=ProcessingOverrides(document={"chunk_size": 222}),
    )


async def accept(app, session, targets=TARGETS):
    prepared = await preview(app, session, targets)
    items = await app.owner.aprepare_file_processing(
        session,
        40,
        identity=app.context.user,
        kind="file_resplit",
        targets=targets,
        overrides=ProcessingOverrides(document={"chunk_size": 222}),
        expected_configuration=prepared.configuration,
        expected_source_revisions=prepared.source_revisions,
        operation_id="file-operation",
    )
    result = await app.owner.jobs.acreate(
        session,
        space_id=40,
        kind="file_resplit",
        idempotency_key="file-operation",
        actor_user_id=7,
        actor_reference={"actor_id": 7},
        parameters={"operation_id": "file-operation"},
        configuration=prepared.configuration,
        items=items,
    )
    return result.job, prepared


async def claim(app, session, job, prepared):
    lease = await app.owner.jobs.aclaim(session, job.id, configuration=prepared.configuration)
    item = await app.owner.jobs.aclaim_next_item(session, lease, configuration=prepared.configuration)
    assert await app.owner.scope.astart_processed_file(session, item.lease, jobs=app.owner.jobs)
    return lease, item


def outcome(item, status=2, count=3, patch=None):
    return FileProcessingResult(
        item.item.file_id,
        item.item.processing_snapshot["source_revision"],
        status,
        count,
        patch or {},
        None if status == 2 else 10953,
    )


async def test_preview_has_actual_frozen_rules_and_zero_business_mutation(files):
    async with files.context.sessions() as session:
        before = (await session.get(KnowledgeFile, 81)).model_dump(mode="json")
        plan = await preview(files, session)
        assert plan.configuration.model_config_revision == 0 and plan.configuration.index_generation == "g0"
        assert plan.items[0].target.document_id == 80
        assert plan.items[0].processing_snapshot["effective_processing"]["effective_rule"]["chunk_size"] == 222
        assert set(plan.items[0].processing_snapshot) == {
            "schema_version",
            "mode",
            "original_status",
            "effective_processing",
            "source_revision",
        }
        await session.commit()
    async with files.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).model_dump(mode="json") == before


async def test_acceptance_rule_file_status_and_item_rollback_together(files):
    async with files.context.sessions() as session:
        await accept(files, session)
        row = await session.get(KnowledgeFile, 81)
        assert row.status == 5 and json.loads(row.split_rule)["chunk_size"] == 222
        assert (await session.get(Knowledge, 40)).model_config_revision == 0
        await session.rollback()
    async with files.context.sessions() as session:
        row = await session.get(KnowledgeFile, 81)
        assert row.status == 2 and json.loads(row.split_rule)["chunk_size"] == 333


async def test_source_or_configuration_drift_between_preview_and_accept_rejects(files):
    async with files.context.sessions() as session:
        plan = await preview(files, session)
        (await session.get(KnowledgeFile, 81)).object_name = "replacement"
        await session.flush()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await files.owner.aprepare_file_processing(
                session,
                40,
                identity=files.context.user,
                kind="file_resplit",
                targets=TARGETS,
                overrides=ProcessingOverrides(document={"chunk_size": 222}),
                expected_configuration=plan.configuration,
                expected_source_revisions=plan.source_revisions,
                operation_id="changed",
            )
        assert (await session.get(KnowledgeFile, 81)).status == 2


async def test_target_inflight_or_overlapping_active_job_is_conflict(files):
    async with files.context.sessions() as session:
        (await session.get(KnowledgeFile, 81)).status = 1
        await session.flush()
        with pytest.raises(KnowledgeProcessingConflictError):
            await preview(files, session)
        await session.rollback()
    async with files.context.sessions() as session:
        job, _ = await accept(files, session)
        # Status alone is insufficient: even a stale successful projection
        # cannot admit overlapping work while the durable ledger is active.
        (await session.get(KnowledgeFile, 81)).status = 2
        await session.flush()
        with pytest.raises(KnowledgeProcessingConflictError):
            await preview(files, session)
        assert job.state == "accepted"


async def test_success_completion_is_actual_version_and_borrows_transaction(files):
    async with files.context.sessions() as session:
        job, prepared = await accept(files, session)
        lease, item = await claim(files, session, job, prepared)
        assert (await session.get(KnowledgeFile, 81)).status == 1
        assert await files.owner.scope.acomplete_processed_file(
            session, item.lease, jobs=files.owner.jobs, outcome=outcome(item, patch={"abstract": "actual parse"})
        )
        assert item.item.state == "succeeded" and (await session.get(KnowledgeFile, 81)).status == 2
        assert (await session.get(KnowledgeFile, 81)).abstract == "actual parse"
        assert (await session.get(KnowledgeFile, 82)).abstract is None
        assert (await files.owner.afinalize_and_ack(session, job, lease)).state == "succeeded"
        root = await Models.repository.aget(session, 40)
        assert root.model_transition is None and root.model_config_revision == 0 and root.index_generation == "g0"
        await session.rollback()
    async with files.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 81)).abstract is None


@pytest.mark.parametrize("status", [3, 7])
async def test_failure_safety_and_retry_keep_original_snapshot_without_model_fence(files, status):
    async with files.context.sessions() as session:
        job, prepared = await accept(files, session)
        lease, item = await claim(files, session, job, prepared)
        before = dict(item.item.processing_snapshot)
        assert await files.owner.scope.acomplete_processed_file(
            session,
            item.lease,
            jobs=files.owner.jobs,
            outcome=outcome(item, status=status, count=0, patch={"user_metadata": {"transient": True}}),
        )
        assert (await session.get(KnowledgeFile, 81)).status == status
        assert (await session.get(KnowledgeFile, 81)).user_metadata == {"preserved": 81}
        job = await files.owner.afinalize_and_ack(session, job, lease)
        assert job.state == "failed"
        result = await files.owner.aretry_failed(
            session,
            job.id,
            identity=files.context.user,
            idempotency_key="retry",
            expected_job_revision=job.revision,
            actor_user_id=7,
            actor_reference={"actor_id": 7},
        )
        assert not result.reused and item.item.processing_snapshot == before
        assert (await session.get(KnowledgeFile, 81)).status == 5
        assert (await session.get(Knowledge, 40)).state == 1


async def test_global_failure_updates_only_unfinished_owned_files_and_rolls_back(files):
    async with files.context.sessions() as session:
        job, prepared = await accept(files, session, [*TARGETS, {"file_id": 82, "version_id": 182}])
        lease, first = await claim(files, session, job, prepared)
        await files.owner.scope.acomplete_processed_file(
            session, first.lease, jobs=files.owner.jobs, outcome=outcome(first)
        )
        second = await files.owner.jobs.aclaim_next_item(session, lease, configuration=prepared.configuration)
        await files.owner.scope.astart_processed_file(session, second.lease, jobs=files.owner.jobs)
        await session.commit()
    async with files.context.sessions() as session:
        failed = await files.owner.afail_attempt(
            session, job.id, expected_job_revision=job.revision, lease=lease, error_code=10953
        )
        assert failed.state == "partial_failed"
        assert (await session.get(KnowledgeFile, 81)).status == 2
        assert (await session.get(KnowledgeFile, 82)).status == 3
        await session.rollback()
    async with files.context.sessions() as session:
        assert (await session.get(KnowledgeFile, 82)).status == 1


async def test_unknown_patch_zero_success_and_late_source_change_never_finalize(files):
    async with files.context.sessions() as session:
        job, prepared = await accept(files, session)
        _, item = await claim(files, session, job, prepared)
        for invalid in (outcome(item, count=0), outcome(item, patch={"knowledge_id": 999})):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await files.owner.scope.acomplete_processed_file(
                    session, item.lease, jobs=files.owner.jobs, outcome=invalid
                )
        (await session.get(KnowledgeFile, 81)).md5 = "replaced"
        await session.flush()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await files.owner.scope.acomplete_processed_file(
                session, item.lease, jobs=files.owner.jobs, outcome=outcome(item)
            )
        assert item.item.state == "running"

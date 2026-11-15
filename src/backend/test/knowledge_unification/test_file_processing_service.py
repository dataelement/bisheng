"""T675: actual opaque plan/acceptance/retry with native SQL Owners."""

from types import SimpleNamespace

import pytest
from sqlmodel import select

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingConflictError
from bisheng.knowledge.application.file_processing_adapter import system_processing_defaults
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.schemas.processing_job import (
    ProcessingCreateRequest,
    ProcessingPrecheckRequest,
    ProcessingRetryRequest,
)
from bisheng.knowledge.domain.schemas.processing_settings import ProcessingSettingsWrite
from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService
from bisheng.knowledge.domain.services.processing_settings_service import ProcessingSettingsService
from bisheng.knowledge.rag.knowledge_file_pipeline import FileProcessingResult
from test.knowledge_unification import test_file_processing_owner as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files


@pytest.fixture
def service(files):
    return SimpleNamespace(
        app=ProcessingJobService(
            owner=files.owner, available_kinds={"embedding_rebuild", "file_resplit", "file_reprocess"}
        ),
        files=files,
    )


def command(kind="file_resplit", targets=None):
    return ProcessingPrecheckRequest.model_validate(
        {
            "kind": kind,
            "targets": targets or [{"file_id": 81, "version_id": 181}],
            "parameters": {"overrides": {"document": {"chunk_size": 222}}},
        }
    )


async def precheck(service, session, request=None):
    return await service.app.aprecheck(
        session, 40, request or command(), identity=service.files.context.user, entry_kind="web"
    )


async def create(service, session, plan):
    return await service.app.acreate(
        session,
        40,
        ProcessingCreateRequest(
            idempotency_key="file-http", confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest
        ),
        identity=service.files.context.user,
        entry_kind="web",
    )


@pytest.mark.parametrize("kind", ["file_resplit", "file_reprocess"])
async def test_confirmed_selection_accepts_one_real_version_and_replays_same_job(service, kind):
    files = service.files
    async with files.context.sessions() as session:
        plan = await precheck(service, session, command(kind, [{"file_id": 82, "version_id": 182}]))
        assert plan.can_execute and plan.impact["overwrite_manual_chunks"] is True
        assert plan.impact["selected_version_count"] == 1
        assert all(item.id == 40 for item in plan.valid_items)
        assert "hidden secret" not in plan.model_dump_json()
        accepted = await create(service, session, plan)
        replay = await create(service, session, plan)
        assert replay.job_id == accepted.job_id and replay.reused and accepted.state == "accepted"
        job = await files.owner.jobs.aget(session, accepted.job_id)
        assert job.kind == kind and job.expected_model_config_revision == job.accepted_model_config_revision == 0
        items = (await session.exec(select(KnowledgeProcessingItem))).all()
        assert len(items) == 1 and (items[0].file_id, items[0].document_id, items[0].version_id) == (82, 80, 182)
        assert items[0].processing_snapshot["effective_processing"]["effective_rule"]["chunk_size"] == 222
        assert (await session.get(KnowledgeFile, 82)).status == 5 and (await session.get(KnowledgeFile, 81)).status == 2
        root = await session.get(Knowledge, 40)
        assert root.model_transition is None and root.model_config_revision == 0 and root.index_generation == "g0"
        assert len((await session.exec(select(KnowledgeDocumentVersion))).all()) == 2
        await session.commit()


async def test_new_source_change_requires_new_confirmation_and_leaves_no_job(service):
    async with service.files.context.sessions() as session:
        plan = await precheck(service, session)
        (await session.get(KnowledgeFile, 81)).object_name = "different.txt"
        await session.flush()
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await create(service, session, plan)
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
        assert (await session.get(KnowledgeFile, 81)).status == 2


async def test_unavailable_assembly_refuses_file_kind_before_acceptance(service):
    unavailable = ProcessingJobService(owner=service.files.owner)
    async with service.files.context.sessions() as session:
        with pytest.raises(KnowledgeProcessingConflictError):
            await unavailable.aprecheck(session, 40, command(), identity=service.files.context.user, entry_kind="web")


async def test_active_target_blocks_overlap_but_not_other_file(service):
    async with service.files.context.sessions() as session:
        await create(service, session, await precheck(service, session))
        with pytest.raises(KnowledgeProcessingConflictError):
            await precheck(service, session)
        other = await precheck(service, session, command(targets=[{"file_id": 82, "version_id": 182}]))
        assert other.can_execute


async def test_partial_retry_preserves_success_and_accepted_rules_after_default_change(service):
    files = service.files
    async with files.context.sessions() as session:
        plan = await precheck(
            service, session, command(targets=[{"file_id": 81, "version_id": 181}, {"file_id": 82, "version_id": 182}])
        )
        accepted = await create(service, session, plan)
        job = await files.owner.jobs.aget(session, accepted.job_id)
        current = await files.owner.aread_current(session, 40, job=job)
        lease = await files.owner.jobs.aclaim(session, job.id, configuration=current.configuration)
        completed = []
        for status in (2, 3):
            item = await files.owner.jobs.aclaim_next_item(session, lease, configuration=current.configuration)
            await files.owner.scope.astart_processed_file(session, item.lease, jobs=files.owner.jobs)
            await files.owner.scope.acomplete_processed_file(
                session,
                item.lease,
                jobs=files.owner.jobs,
                outcome=FileProcessingResult(
                    item.item.file_id, item.item.processing_snapshot["source_revision"], status, 2 if status == 2 else 0
                ),
            )
            completed.append(item.item)
        job = await files.owner.afinalize_and_ack(session, job, lease)
        success_before = completed[0].model_dump(mode="json")
        frozen_failed = dict(completed[1].processing_snapshot)
        defaults = system_processing_defaults(40).model_dump(mode="json")
        defaults["document"]["chunk_size"] = 900
        await ProcessingSettingsService(service.app.settings).save_settings(
            session,
            40,
            ProcessingSettingsWrite.model_validate({"expected_config_version": 0, "defaults": defaults}),
            system_defaults=system_processing_defaults(40),
        )
        retry = await service.app.aretry(
            session,
            40,
            job.id,
            ProcessingRetryRequest(idempotency_key="failed-only", expected_job_revision=job.revision),
            identity=files.context.user,
            entry_kind="web",
        )
        assert retry.error is None and retry.data.accepted
        assert completed[0].model_dump(mode="json") == success_before
        assert completed[1].state == "pending" and completed[1].processing_snapshot == frozen_failed
        assert (await session.get(KnowledgeFile, 81)).status == 2 and (await session.get(KnowledgeFile, 82)).status == 5
        assert (await session.get(Knowledge, 40)).state == 1


async def test_accepted_plan_and_file_queue_all_rollback_when_caller_cancels(service):
    async with service.files.context.sessions() as session:
        await create(service, session, await precheck(service, session))
        await session.rollback()
    async with service.files.context.sessions() as session:
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
        assert (await session.get(KnowledgeFile, 81)).status == 2

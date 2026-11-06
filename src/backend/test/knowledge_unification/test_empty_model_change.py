"""T683: empty/all-skipped model changes use real business scope and R2.

SQLite proves native transaction ownership and rejection, not MySQL lock
scheduling. Only FGA/sharing transports use the existing fixture doubles.
"""

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, update
from sqlmodel import select

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import (
    KnowledgeNoEmbeddingError,
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.knowledge.application import model_reference as module
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as Models
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.repositories.processing_job_repository import NewProcessingItem, ProcessingConfiguration
from bisheng.knowledge.domain.repositories.processing_owner_repository import ProcessingOwnerRepository
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget
from test.knowledge_unification import test_job_service as fixtures
from test.knowledge_unification.test_kn_model_bindings import state

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application


@pytest.fixture
async def empty(application):
    async with application.context.sessions() as session:
        await session.execute(delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == 80))
        await session.execute(delete(KnowledgeDocument).where(KnowledgeDocument.knowledge_id == 40))
        await session.execute(
            delete(KnowledgeFile).where(KnowledgeFile.tenant_id == 101, KnowledgeFile.knowledge_id == 40)
        )
        await session.commit()
    return application


async def add_file(session, status=3, *, file_id=81):
    document_id, version_id = file_id + 100, file_id + 200
    session.add_all(
        [
            KnowledgeFile(id=file_id, tenant_id=101, knowledge_id=40, file_name=f"{file_id}.txt", status=status),
            KnowledgeDocument(id=document_id, knowledge_id=40, primary_version_id=version_id),
            KnowledgeDocumentVersion(
                id=version_id, document_id=document_id, knowledge_file_id=file_id, version_no=1, is_primary=True
            ),
        ]
    )
    await session.flush()


async def prepare(app, session, model=12, **expected):
    return await Models.aprepare_empty_model_change(
        session,
        40,
        model,
        login_user=app.context.user,
        expected_model_config_revision=expected.get("revision", 0),
        expected_index_generation=expected.get("generation", "g0"),
        operation_id="empty-explicit-change",
    )


@pytest.mark.parametrize("contents", ["empty", "folder", "all_skipped"])
async def test_actual_empty_or_complete_skipped_scope_switches_current_slot_without_job(empty, contents):
    app = empty
    async with app.context.sessions() as session:
        if contents == "folder":
            session.add(KnowledgeFile(id=90, tenant_id=101, knowledge_id=40, file_name="folder", file_type=0))
        elif contents == "all_skipped":
            for file_id, status in ((81, 3), (82, 6), (83, 7)):
                await add_file(session, status, file_id=file_id)
        await session.commit()
    before = state(app.context)
    async with app.context.sessions() as session:
        change = await prepare(app, session)
        assert change.model == "12" and change.transition is None and change.changed
        assert change.next_state == KnowledgeState.PUBLISHED.value
        assert (await session.get(Knowledge, 40)).model == "11"
        # Preparing is not a hidden finalize, and has no business/R2 effect.
        await session.commit()
    assert state(app.context) == before
    async with app.context.sessions() as session:
        change = await prepare(app, session)
        row = await Models.aapply_model_change(session, change)
        assert row.model == "12" and row.model_transition is None
        assert row.state == KnowledgeState.PUBLISHED.value and row.model_config_revision == 1
        assert row.index_generation != "g0"
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()
        assert not (await session.exec(select(KnowledgeProcessingItem))).all()
        await session.commit()
    refs = state(app.context)["business_resource_reference"]
    assert {(row["slot_key"], row["target_id"]) for row in refs if row["source_id"] == "40"} == {("model", "12")}
    async with app.context.sessions() as session:
        if contents == "all_skipped":
            assert [(await session.get(KnowledgeFile, value)).status for value in (81, 82, 83)] == [3, 6, 7]


async def test_business_change_and_r2_borrow_external_rollback(empty):
    before = state(empty.context)
    async with empty.context.sessions() as session:
        await Models.aapply_model_change(session, await prepare(empty, session))
        await session.rollback()
    assert state(empty.context) == before


@pytest.mark.parametrize("status", [1, 2, 4, 5, None])
async def test_rebuildable_or_inflight_physical_files_are_not_empty(empty, status):
    async with empty.context.sessions() as session:
        await add_file(session, status)
        await session.commit()
    before = state(empty.context)
    async with empty.context.sessions() as session:
        with pytest.raises(KnowledgeProcessingConflictError):
            await prepare(empty, session)
        await session.rollback()
    assert state(empty.context) == before


@pytest.mark.parametrize(
    "broken", ["unversioned", "empty_document", "missing_file", "foreign_file", "duplicate_file", "primary"]
)
async def test_complete_physical_document_version_chain_is_required(empty, broken):
    async with empty.context.sessions() as session:
        await add_file(session)
        if broken == "unversioned":
            await session.execute(delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.id == 281))
            await session.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == 181))
        elif broken == "empty_document":
            session.add(KnowledgeDocument(id=99, knowledge_id=40))
        elif broken == "missing_file":
            await session.execute(delete(KnowledgeFile).where(KnowledgeFile.id == 81, KnowledgeFile.tenant_id == 101))
        elif broken == "foreign_file":
            row = await session.get(KnowledgeFile, 81)
            row.tenant_id = 202
        elif broken == "duplicate_file":
            session.add(KnowledgeDocumentVersion(id=282, document_id=181, knowledge_file_id=81, version_no=2))
        else:
            (await session.get(KnowledgeDocument, 181)).primary_version_id = 999
        await session.commit()
    async with empty.context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await prepare(empty, session)
        await session.rollback()


async def test_directory_referenced_by_orphan_version_is_not_a_complete_empty_scope(empty):
    async with empty.context.sessions() as session:
        session.add(KnowledgeFile(id=90, tenant_id=101, knowledge_id=40, file_name="folder", file_type=0))
        session.add(
            KnowledgeDocumentVersion(id=290, document_id=999, knowledge_file_id=90, version_no=1, is_primary=True)
        )
        await session.commit()
    async with empty.context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await prepare(empty, session)


async def test_primary_integrity_check_reads_each_of_400_versions_once(empty):
    total = 400
    async with empty.context.sessions() as session:
        session.add(KnowledgeDocument(id=99, knowledge_id=40, primary_version_id=2000))
        for number in range(total):
            session.add(
                KnowledgeFile(id=1000 + number, tenant_id=101, knowledge_id=40, file_name=str(number), status=3)
            )
            session.add(
                KnowledgeDocumentVersion(
                    id=2000 + number,
                    document_id=99,
                    knowledge_file_id=1000 + number,
                    version_no=number + 1,
                    is_primary=number == 0,
                )
            )
        await session.commit()
    reads = 0
    original = KnowledgeDocumentVersion.__getattribute__

    def observe(instance, name):
        nonlocal reads
        if name == "is_primary":
            reads += 1
        return original(instance, name)

    async with empty.context.sessions() as session:
        with patch.object(KnowledgeDocumentVersion, "__getattribute__", observe):
            await ProcessingOwnerRepository().aassert_empty_model_change(session, 40)
    assert reads <= total * 3


@pytest.mark.parametrize("job_state", ["accepted", "running"])
async def test_active_durable_job_blocks_even_when_file_projection_is_failed(empty, job_state):
    async with empty.context.sessions() as session:
        await add_file(session)
        result = await empty.owner.jobs.acreate(
            session,
            space_id=40,
            kind="file_reprocess",
            idempotency_key="other-real-operation",
            actor_user_id=7,
            actor_reference={"actor_id": 7},
            parameters={},
            configuration=ProcessingConfiguration(0, "g0"),
            items=[NewProcessingItem(ResourceVersionTarget(file_id=81, document_id=181, version_id=281), 40)],
        )
        result.job.state = job_state
        await session.commit()
    async with empty.context.sessions() as session:
        with pytest.raises(KnowledgeProcessingConflictError):
            await prepare(empty, session)


@pytest.mark.parametrize("drift", ["source", "successful_file", "new_file"])
async def test_apply_rechecks_locked_complete_scope_in_original_transaction(empty, drift):
    async with empty.context.sessions() as session:
        await add_file(session)
        await session.commit()
    before = state(empty.context)
    async with empty.context.sessions() as session:
        change = await prepare(empty, session)
        if drift == "new_file":
            await add_file(session, file_id=82)
        else:
            row = await session.get(KnowledgeFile, 81)
            if drift == "source":
                row.object_name = "replacement-source"
            else:
                row.status = 2
            await session.flush()
        with pytest.raises((KnowledgeOperationPlanConflictError, KnowledgeProcessingConflictError)):
            await Models.aapply_model_change(session, change)
        await session.rollback()
    assert state(empty.context) == before


async def test_plan_rejects_copy_and_other_transaction(empty):
    async with empty.context.sessions() as session:
        change = await prepare(empty, session)
        with pytest.raises(ResourceReferenceInvalidError):
            await Models.aapply_model_change(session, replace(change))
        await session.commit()
    async with empty.context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await Models.aapply_model_change(session, change)


async def test_r2_failure_rolls_back_current_model_state_and_revision(empty, monkeypatch):
    before = state(empty.context)
    async with empty.context.sessions() as session:
        change = await prepare(empty, session)
        monkeypatch.setattr(change.runtime, "aapply_source_bindings", AsyncMock(side_effect=RuntimeError("R2 failed")))
        with pytest.raises(RuntimeError, match="R2 failed"):
            await Models.aapply_model_change(session, change)
        await session.rollback()
    assert state(empty.context) == before


@pytest.mark.parametrize("model", [33, 999])
async def test_new_target_is_verified_by_real_model_owner(empty, model):
    before = state(empty.context)
    async with empty.context.sessions() as session:
        with pytest.raises((KnowledgeNoEmbeddingError, ResourceReferenceInvalidError)):
            await prepare(empty, session, model)
        await session.rollback()
    assert state(empty.context) == before


async def test_actual_permission_and_expected_revision_are_required(empty, monkeypatch):
    async with empty.context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await prepare(empty, session, revision=1)
    monkeypatch.setattr(module, "require_business_action", AsyncMock(side_effect=UnAuthorizedError()))
    async with empty.context.sessions() as session:
        with pytest.raises(UnAuthorizedError):
            await prepare(empty, session)


async def test_explicit_repair_can_release_revoked_old_shared_model(empty):
    async with empty.context.sessions() as session:
        await Models.acreate(
            session,
            Knowledge(id=41, tenant_id=101, user_id=7, name="empty shared", type=3, model="22", index_generation="g0"),
            login_user=empty.context.user,
            project_created=AsyncMock(),
        )
        await session.commit()
    empty.context.sharing.allowed = frozenset()
    async with empty.context.sessions() as session:
        change = await Models.aprepare_empty_model_change(session, 41, 12, login_user=empty.context.user)
        await Models.aapply_model_change(session, change)
        await session.commit()
    refs = state(empty.context)["business_resource_reference"]
    assert {(row["slot_key"], row["target_id"]) for row in refs if row["source_id"] == "41"} == {("model", "12")}


async def test_same_current_model_is_not_a_manual_rebuild(empty):
    before = state(empty.context)
    async with empty.context.sessions() as session:
        change = await prepare(empty, session, 11)
        assert not change.changed
        await Models.aapply_model_change(session, change)
        await session.commit()
    assert state(empty.context) == before


async def test_same_model_with_revoked_share_is_invalid_rather_than_repaired_noop(empty):
    async with empty.context.sessions() as session:
        await Models.acreate(
            session,
            Knowledge(id=41, tenant_id=101, user_id=7, name="empty shared", type=3, model="22", index_generation="g0"),
            login_user=empty.context.user,
            project_created=AsyncMock(),
        )
        await session.commit()
    empty.context.sharing.allowed = frozenset()
    before = state(empty.context)
    async with empty.context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await Models.aprepare_empty_model_change(session, 41, 22, login_user=empty.context.user)
        await session.rollback()
    assert state(empty.context) == before


@pytest.mark.parametrize("values", [{"model_config_revision": 1}, {"index_generation": "changed-generation"}])
@pytest.mark.parametrize("model", [11, 12])
async def test_apply_preserves_real_configuration_cas_even_with_stale_identity_map(empty, values, model):
    before = state(empty.context)
    async with empty.context.sessions() as session:
        change = await prepare(empty, session, model)
        await session.execute(
            update(Knowledge)
            .where(Knowledge.id == 40, Knowledge.tenant_id == 101)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await Models.aapply_model_change(session, change)
        await session.rollback()
    assert state(empty.context) == before


@pytest.mark.parametrize("values", [{"model_config_revision": 1}, {"index_generation": "changed-generation"}])
async def test_prepare_rechecks_original_issued_plan_after_real_scope_refresh(empty, monkeypatch, values):
    actual_scope = ProcessingOwnerRepository.aassert_empty_model_change

    async def change_before_scope(self, session, space_id):
        # Inject a real SQL change between the two preparations. The complete
        # scope method still runs, including its native populate_existing read.
        await session.execute(
            update(Knowledge)
            .where(Knowledge.id == space_id, Knowledge.tenant_id == 101)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return await actual_scope(self, session, space_id)

    monkeypatch.setattr(ProcessingOwnerRepository, "aassert_empty_model_change", change_before_scope)
    before = state(empty.context)
    async with empty.context.sessions() as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await prepare(empty, session, 11)
        await session.rollback()
    assert state(empty.context) == before


async def test_skipped_scope_still_does_not_enable_pure_manual_rebuild(empty):
    async with empty.context.sessions() as session:
        await add_file(session)
        await session.commit()
    async with empty.context.sessions() as session:
        plan = await fixtures.precheck(empty, session)
        assert not plan.can_execute
        assert not (await session.exec(select(KnowledgeProcessingJob))).all()

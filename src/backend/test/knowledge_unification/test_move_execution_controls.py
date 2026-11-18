"""Native move tenant, FK, pending and transaction controls at the real kernel."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Doc
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt as Retry
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingJobRepository
from test.knowledge_unification import test_move_execution_kernel as kernel
from test.knowledge_unification import test_move_job_ready as ready
from test.knowledge_unification.test_job_query_dispatch import actual_processing_task as actual_processing_task
from test.knowledge_unification.test_job_repo import job_tenant as job_tenant

store, tenant, moving, accepted, built = kernel.store, kernel.tenant, kernel.moving, kernel.accepted, kernel.built


async def ready_item(session, built):
    await ready.mark(session, built, await ready.logical(session, built))
    return (await session.execute(sa.select(ready.Item).where(ready.Item.job_id == built.job_id))).scalars().one()


@pytest.mark.parametrize("bad", ["tenant", "document", "primary", "version"])
async def test_actual_after_chain_never_filters_broken_links_into_a_success(built, bad):
    kernel.composed(built)
    async with built.sessions() as session, session.begin():
        item = await ready_item(session, built)
        item_id, file_id, doc_id, version_id = item.id, item.file_id, item.document_id, item.version_id
    async with built.sessions() as session, session.begin():
        if bad == "tenant":
            await session.execute(sa.update(ready.File).where(ready.File.id == file_id).values(tenant_id=202))
        elif bad == "document":
            await session.execute(sa.update(Doc).where(Doc.id == doc_id).values(knowledge_id=999))
        elif bad == "primary":
            await session.execute(sa.update(Doc).where(Doc.id == doc_id).values(primary_version_id=999))
        else:
            await session.execute(sa.update(Version).where(Version.id == version_id).values(knowledge_file_id=999))
    async with built.sessions() as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.execution.aread_item(session, job_id=built.job_id, item_id=item_id)


@pytest.mark.parametrize("pending", ["root", "file", "document", "version", "item"])
async def test_pending_after_mutation_is_rejected_without_flush_or_overwrite(built, pending):
    kernel.composed(built)
    async with built.sessions() as session, session.begin():
        item = await ready_item(session, built)
        ids = {
            "root": (Knowledge, 10, "name"),
            "file": (ready.File, item.file_id, "file_name"),
            "document": (Doc, item.document_id, "file_level_path"),
            "version": (Version, item.version_id, "version_no"),
            "item": (ready.Item, item.id, "step"),
        }
        model, ident, field = ids[pending]
        row = await session.get(model, ident)
        setattr(row, field, 99 if field == "version_no" else "uncommitted caller data")
        before = dict(sa.inspect(row).dict)
        flushes = []
        sa.event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.execution.aread_item(session, job_id=built.job_id, item_id=item.id)
        assert not flushes and sa.inspect(row).dict == before and row in session.dirty
        await session.rollback()


async def test_read_only_facts_preserve_unrelated_pending_but_execution_requires_clean_native_unit(built):
    kernel.composed(built)
    async with built.sessions() as session, session.begin():
        item = await ready_item(session, built)
        extra = ready.File(id=999, tenant_id=101, knowledge_id=11, file_name="caller data", file_type=1)
        session.add(extra)
        flushes = []
        sa.event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        assert await built.execution.aread_item(session, job_id=built.job_id, item_id=item.id)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.arenew(session, built.lease, configuration=ready.CONFIG, _move=True)
        assert not flushes and extra in session.new
        await session.rollback()


@pytest.mark.parametrize("changed", ["tenant", "transaction", "issuer"])
async def test_context_changed_during_native_read_never_returns_facts(built, monkeypatch, changed):
    kernel.composed(built)
    token = None
    verifier = built.cutover.projection_verifier
    async with built.sessions() as session:
        await session.begin()
        original = session.execute

        async def change(*args, **kwargs):
            nonlocal token
            value = await original(*args, **kwargs)
            if changed == "tenant":
                token = set_current_tenant_id(202)
            elif changed == "transaction":
                await session.commit()
                await session.begin()
            else:
                built.cutover.projection_verifier = object()
            return value

        monkeypatch.setattr(session, "execute", change)
        try:
            with pytest.raises((KnowledgeOperationPlanConflictError, ValueError)):
                await built.execution.aread_configuration(session, job_id=built.job_id)
        finally:
            built.cutover.projection_verifier = verifier
            if token is not None:
                current_tenant_id.reset(token)
            await session.rollback()


async def test_missing_source_root_stops_durably_and_bypass_never_reads_configuration(built):
    kernel.composed(built)
    async with built.sessions() as session, session.begin():
        with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
            await built.execution.aread_configuration(session, job_id=built.job_id)
        await session.execute(sa.delete(Knowledge).where(Knowledge.id == 10))
    async with built.sessions() as session, session.begin():
        assert await built.repo.arenew(session, built.lease, configuration=ready.CONFIG, _move=True) is None
    async with built.sessions() as session:
        job = await built.repo.aget_execution(session, built.job_id)
        assert job.state == "obsolete" and "source_space_missing" in job.obsolete_reason


async def test_actual_other_native_issuer_cannot_authorize_the_same_item_in_the_same_transaction(built):
    kernel.composed(built)
    async with built.sessions() as session, session.begin():
        await ready_item(session, built)
        other = type(built.bridge)(repository=type(built.bridge.repository)(environment="test"))
        evidence = await other.arequire_finalized(session, job_id=built.job_id, expectations=built.expectations)
        with pytest.raises(PermissionPublishNotReadyError):
            await kernel.claim(session, built, evidence=evidence)
        item = (await session.execute(sa.select(ready.Item).where(ready.Item.job_id == built.job_id))).scalars().one()
        assert item.state == "pending" and item.attempt == 0


@pytest.mark.parametrize("code", [10994, None, True, -1, "provider private detail"])
async def test_failed_item_updates_only_owned_file_with_a_public_error_code(built, code):
    kernel.composed(built)
    async with built.sessions() as session, session.begin():
        await ready_item(session, built)
        evidence = await kernel.proof(session, built)
        claimed = await kernel.claim(session, built, evidence=evidence)
        if code == 10994:
            assert await built.repo.acomplete_item(
                session,
                claimed.lease,
                configuration=ready.CONFIG,
                succeeded=False,
                error_code=code,
                _move=True,
                move_projection_evidence=evidence,
            )
            assert claimed.item.state == "failed" and claimed.item.error_code == code
            row = await session.get(ready.File, claimed.item.file_id)
            assert row.status == 3 and row.remark == '{"code": 10994}'
        else:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await built.repo.acomplete_item(
                    session,
                    claimed.lease,
                    configuration=ready.CONFIG,
                    succeeded=False,
                    error_code=code,
                    _move=True,
                    move_projection_evidence=evidence,
                )
            assert claimed.item.state == "running"
            assert (await session.get(ready.File, claimed.item.file_id)).status == 4


@pytest.mark.parametrize("changed", ["subject", "audit", "future-revision"])
async def test_latest_retry_identity_rejects_unaccepted_or_inconsistent_native_facts(
    built, actual_processing_task, changed
):
    from test.knowledge_unification.test_move_job_retry import fail, retry_args

    kernel.composed(built)
    async with built.sessions() as session, session.begin():
        failed = await fail(session, built)
        await built.repo.aretry_failed(session, built.job_id, **retry_args(failed.revision), _move=True)
        assert (await built.repo.alatest_retry_actor(session, built.job_id))["actor"]["subject_id"] == 50
        patch = {
            "subject": {"actor_subject_id": 12},
            "audit": {"actor_user_id": 7},
            "future-revision": {"accepted_job_revision": 99999},
        }[changed]
        await session.execute(sa.update(Retry.__table__).where(Retry.job_id == built.job_id).values(**patch))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.alatest_retry_actor(session, built.job_id)


async def test_plain_transport_recorder_still_works_without_move_execution_authority(built):
    async with built.sessions() as session, session.begin():
        await session.execute(
            sa.update(ready.Job)
            .where(ready.Job.id == built.job_id)
            .values(
                state="accepted",
                pending_dispatch=True,
                lease_token=None,
                lease_until=None,
            )
        )
        row = await built.repo.aget_execution(session, built.job_id)
        plain = ProcessingJobRepository()
        assert await plain.arecord_dispatch(
            session,
            built.job_id,
            expected_revision=row.revision,
            published=True,
            next_at=built.clock[0],
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await plain.aclaim(session, built.job_id, configuration=ready.CONFIG)

"""T979: real J1a/P1/K1 receipts, ready gates, and partial native commits."""

import asyncio
import importlib
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan as Plan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.move_cutover_repository import MoveCutoverRepository
from bisheng.knowledge.domain.repositories.move_job_repository import MoveJobRepository
from bisheng.knowledge.domain.repositories.processing_job_repository import ProcessingJobRepository
from bisheng.knowledge.domain.schemas.processing_job import JobAccepted
from bisheng.knowledge.domain.schemas.processing_job_acceptance import ProcessingConfiguration, _digest
from bisheng.permission.application.identity import PermissionActor
from bisheng.permission.domain.models import AuthorizationModelRelease, PermissionCatalogRelease
from bisheng.permission.domain.repositories.move_projection_repository import MoveProjectionExpectation
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from test.knowledge_unification.test_move_job_reservation import accepted as accepted
from test.knowledge_unification.test_move_job_reservation import create, jobs
from test.knowledge_unification.test_move_job_reservation import moving as moving
from test.knowledge_unification.test_move_job_reservation import store as store
from test.knowledge_unification.test_move_job_reservation import tenant as tenant
from test.knowledge_unification.test_move_projection import compose

CONFIG = ProcessingConfiguration(4, "generation-4")


def api():
    return importlib.import_module("bisheng.knowledge.domain.repositories.move_job_ready_repository")


async def pipeline(moving, accepted, monkeypatch, *, zero=None, count=1):
    if count > 1:
        async with AsyncSession(moving.engine) as session:
            await session.execute(
                sa.insert(File.__table__),
                [
                    {
                        "id": 1000 + n,
                        "tenant_id": 101,
                        "knowledge_id": 10,
                        "file_name": str(n),
                        "file_type": 1,
                        "file_level_path": "/50",
                        "level": 1,
                        "status": 2,
                    }
                    for n in range(count - 1)
                ],
            )
            await session.execute(
                sa.insert(Version.__table__),
                [
                    {
                        "id": 20000 + n,
                        "document_id": 80,
                        "knowledge_file_id": 1000 + n,
                        "version_no": n + 3,
                        "is_primary": False,
                    }
                    for n in range(count - 1)
                ],
            )
            await session.commit()
    confirmed = await accepted(zero=zero)
    move, cutover = jobs(moving)
    job = (await create(moving, confirmed.args, move)).job
    clock = [datetime.now()]
    cutover.clock = lambda: clock[0]
    ready = api().MoveJobReadyRepository(move_jobs=move, clock=lambda: clock[0])
    repo = ProcessingJobRepository(move_jobs=move, move_ready=ready, clock=lambda: clock[0])

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(moving.engine, expire_on_commit=False) as session:
            yield session

    async with sessions() as session, session.begin():
        lease = await repo.aclaim(session, job.id, configuration=CONFIG)
        assert lease is not None  # Job leasing must be possible before logical ready.
    expectations = []
    for change in confirmed.scope.parent_changes:
        common = {
            "tenant_id": 101,
            "resource_type": change.resource_type,
            "resource_id": str(change.resource_id),
            "resource_version": change.expected_permission_version,
            "context_version": confirmed.scope.scope_digest,
        }
        before = VerifiedPermissionTarget.from_business_service(
            **common, parent_type=change.old_parent_type, parent_id=str(change.old_parent_id)
        )
        after = VerifiedPermissionTarget.from_business_service(
            **common, parent_type=change.new_parent_type, parent_id=str(change.new_parent_id)
        )
        expectations.append(
            MoveProjectionExpectation(
                job.id,
                101,
                change.resource_type,
                str(change.resource_id),
                before,
                after,
                change.mode,
                change.expected_permission_version,
                confirmed.scope.changes_digest,
                (7,),
            )
        )
    p1 = await compose(SimpleNamespace(engine=moving.engine, sessions=sessions), monkeypatch, tuple(expectations))
    async with moving.engine.begin() as connection:
        await connection.execute(
            sa.insert(AuthorizationModelRelease),
            {
                "id": 1,
                "environment": "test",
                "store_id": "actual-store",
                "model_id": "actual-model",
                "model_version": "f048",
                "model_checksum": "a" * 64,
                "required_relations_checksum": "b" * 64,
                "openfga_version": "1",
                "status": "ACTIVE",
            },
        )
        await connection.execute(
            sa.insert(PermissionCatalogRelease),
            {
                "id": 1,
                "release_key": "current",
                "version": 1,
                "status": "CURRENT",
                "write_fenced": False,
                "required_authorization_model_release_id": 1,
                "draft_owner_id": 7,
                "idempotency_key": "catalog",
                "checksum": "c" * 64,
            },
        )
    assert (
        await p1.bridge.aexecute_or_resume(
            job_id=job.id, changes=tuple(expectations), actor=PermissionActor(user_id=7, current_tenant_id=101)
        )
    ).complete
    cutover.projection_verifier = p1.bridge
    return SimpleNamespace(
        job_id=job.id,
        confirmed=confirmed,
        move=move,
        cutover=cutover,
        ready=ready,
        repo=repo,
        clock=clock,
        lease=lease,
        sessions=sessions,
        bridge=p1.bridge,
        expectations=tuple(expectations),
    )


async def logical(session, built):
    prepared = await built.cutover.aprepare_cutover(session, job_id=built.job_id, lease=built.lease)
    evidence = await built.bridge.arequire_finalized(session, job_id=built.job_id, expectations=built.expectations)
    return await built.cutover.aapply_logical(session, prepared=prepared, projection_evidence=evidence)


async def mark(session, built, receipt):
    return await built.repo.amark_move_ready(session, logical_receipt=receipt, lease=built.lease)


@pytest.mark.parametrize("zero", [None, "empty", "skipped"])
async def test_native_receipt_marks_items_then_job_and_zero_items_only_now_succeed(moving, accepted, monkeypatch, zero):
    built = await pipeline(moving, accepted, monkeypatch, zero=zero)
    async with built.sessions() as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.aclaim_next_item(session, built.lease, configuration=CONFIG)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.afinalize(session, built.lease, configuration=CONFIG)
        await session.execute(
            sa.update(Item.__table__)
            .where(Item.job_id == built.job_id)
            .values(checkpoint={"prior": {"zero": 0}}, result={"preserved": True}, attempt=3)
        )
        receipt = await logical(session, built)
        result = await mark(session, built, receipt)
        assert isinstance(result, JobAccepted) and not result.reused and result.job_id == built.job_id
        job = await session.get(Job, built.job_id)
        assert set(job.move_logical_marker) == {
            "move_schema",
            "job_id",
            "plan_id",
            "request_hash",
            "after_scope_digest",
            "projection_evidence_digest",
            "index_item_count",
            "ready_claim_generation",
        }
        assert job.move_logical_marker["projection_evidence_digest"] == receipt.projection_evidence_digest
        assert job.move_logical_marker["ready_claim_generation"] == built.lease.claim_generation
        assert job.state == ("succeeded" if zero else "running")
        assert result.state == job.state
        assert (job.finished_at is not None) == bool(zero)
        assert not job.pending_dispatch
        rows = (await session.execute(sa.select(Item).where(Item.job_id == built.job_id))).scalars().all()
        for item in rows:
            assert item.state == "pending" and item.attempt == 3 and item.result == {"preserved": True}
            assert item.checkpoint["prior"] == {"zero": 0}
            stored = item.checkpoint["logical_move"]
            assert stored["job_marker_digest"] == _digest(job.move_logical_marker)
            assert stored["processing_snapshot_digest"] == _digest(item.processing_snapshot)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await mark(session, built, receipt)  # Exact original receipt is one-use.


@pytest.mark.parametrize("bad", ["bare", "issuer", "nested", "lease", "hash", "subject", "plan"])
async def test_actual_receipt_job_subject_hash_plan_and_lease_are_required(moving, accepted, monkeypatch, bad):
    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
        if bad == "bare":
            receipt = {"job_id": built.job_id}
        elif bad == "issuer":
            built.ready = api().MoveJobReadyRepository(
                move_jobs=MoveJobRepository(cutover=MoveCutoverRepository(scope_repository=moving.repo))
            )
            built.repo = ProcessingJobRepository(move_ready=built.ready)
        elif bad == "lease":
            built.lease = replace(built.lease, lease_token="wrong-token")
        elif bad in ("hash", "subject"):
            values = {"request_hash": "f" * 64} if bad == "hash" else {"actor_subject_id": 99}
            await session.execute(sa.update(Job.__table__).where(Job.id == built.job_id).values(**values))
        elif bad == "plan":
            await session.execute(
                sa.update(Plan.__table__)
                .where(Plan.id == built.confirmed.plan.confirmation_id)
                .values(operation_id="other-job")
            )
        if bad == "nested":
            async with session.begin_nested():
                with pytest.raises(KnowledgeOperationPlanConflictError):
                    await mark(session, built, receipt)
        else:
            with pytest.raises(Exception) as failure:
                await mark(session, built, receipt)
            assert type(failure.value).__module__.startswith("bisheng.common.errcode")
        assert (await session.get(Job, built.job_id)).move_logical_marker is None


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_partial_item_markers_caught_and_committed_are_never_ready(moving, accepted, monkeypatch, failure):
    built = await pipeline(moving, accepted, monkeypatch, count=2)
    hit = []

    def inject(_c, _cu, sql, _params, _ctx, _many):
        if not hit and sql.lstrip().upper().startswith("UPDATE KNOWLEDGE_PROCESSING_ITEM"):
            hit.append(True)
            raise failure("after first real item marker write")

    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
        execute = session.execute
        if failure is asyncio.CancelledError:
            # Cancel after the native await returns. Cancelling inside the DBAPI
            # hook invalidates the connection and makes outer commit impossible.
            async def cancelled(statement, *args, **kwargs):
                result = await execute(statement, *args, **kwargs)
                if not hit and getattr(statement, "is_update", False) and statement.table.name == Item.__tablename__:
                    hit.append(True)
                    raise asyncio.CancelledError("after first native item marker write")
                return result

            monkeypatch.setattr(session, "execute", cancelled)
        else:
            sa.event.listen(moving.engine.sync_engine, "after_cursor_execute", inject)
        try:
            with pytest.raises(failure):
                await mark(session, built, receipt)
        finally:
            if failure is asyncio.CancelledError:
                monkeypatch.setattr(session, "execute", execute)
            else:
                sa.event.remove(moving.engine.sync_engine, "after_cursor_execute", inject)
    async with built.sessions() as session, session.begin():
        rows = (await session.execute(sa.select(Item).where(Item.job_id == built.job_id))).scalars().all()
        assert hit and 0 < sum("logical_move" in item.checkpoint for item in rows) < len(rows)
        assert (await session.get(Job, built.job_id)).move_logical_marker is None
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.aclaim_next_item(session, built.lease, configuration=CONFIG)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.afinalize(session, built.lease, configuration=CONFIG)


async def test_callers_native_rollback_reverts_business_and_ready_together(moving, accepted, monkeypatch):
    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session:
        transaction = await session.begin()
        await mark(session, built, await logical(session, built))
        await transaction.rollback()
    async with built.sessions() as session:
        assert (await session.get(Job, built.job_id)).move_logical_marker is None
        assert (await session.get(File, 81)).knowledge_id == 10
        assert all("logical_move" not in item.checkpoint for item in (await session.execute(sa.select(Item))).scalars())


async def test_takeover_keeps_original_marker_and_all_checkpoint_mutations_protect_it(moving, accepted, monkeypatch):
    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        await mark(session, built, await logical(session, built))
        original = deepcopy((await session.get(Job, built.job_id)).move_logical_marker)
    built.clock[0] += timedelta(seconds=901)
    async with built.sessions() as session, session.begin():
        assert await built.repo.arenew(session, built.lease, configuration=CONFIG) is None
        built.lease = await built.repo.aclaim(session, built.job_id, configuration=CONFIG)
        assert built.lease.claim_generation > original["ready_claim_generation"]
        current = await built.repo.aclaim_next_item(session, built.lease, configuration=CONFIG)
        assert current is not None
        marker = deepcopy(current.item.checkpoint["logical_move"])
        assert await built.repo.asave_checkpoint(
            session, current.lease, configuration=CONFIG, step="move_copy", checkpoint={"native": 1}
        )
        assert current.item.checkpoint == {"native": 1, "logical_move": marker}
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.asave_checkpoint(
                session, current.lease, configuration=CONFIG, step="bad", checkpoint={"logical_move": {"forged": True}}
            )
        assert await built.repo.acomplete_item(session, current.lease, configuration=CONFIG, succeeded=True)
        final = await built.repo.afinalize(session, built.lease, configuration=CONFIG)
        assert final.state == "succeeded" and final.move_logical_marker == original


@pytest.mark.parametrize("bad", ["snapshot", "target", "item-marker", "job-marker", "bool-marker"])
async def test_modified_snapshot_target_or_ready_fact_cannot_sign_or_use_an_item_lease(
    moving, accepted, monkeypatch, bad
):
    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        await mark(session, built, await logical(session, built))
        claimed = await built.repo.aclaim_next_item(session, built.lease, configuration=CONFIG)
        if bad == "job-marker":
            marker = deepcopy((await session.get(Job, built.job_id)).move_logical_marker)
            marker["request_hash"] = "f" * 64
            await session.execute(
                sa.update(Job.__table__).where(Job.id == built.job_id).values(move_logical_marker=marker)
            )
        elif bad == "bool-marker":
            checkpoint = deepcopy(claimed.item.checkpoint)
            checkpoint["logical_move"]["move_schema"] = True
            await session.execute(
                sa.update(Item.__table__).where(Item.id == claimed.item.id).values(checkpoint=checkpoint)
            )
        else:
            value = {
                "snapshot": {"processing_snapshot": {"tampered": True}},
                "target": {"file_id": 999},
                "item-marker": {"checkpoint": {"logical_move": {"forged": True}}},
            }[bad]
            await session.execute(sa.update(Item.__table__).where(Item.id == claimed.item.id).values(**value))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.acomplete_item(session, claimed.lease, configuration=CONFIG, succeeded=True)


async def test_unconfigured_move_ready_port_is_closed(moving, accepted):
    confirmed = await accepted()
    job = (await create(moving, confirmed.args)).job
    async with AsyncSession(moving.engine) as session, session.begin():
        repo = ProcessingJobRepository()
        lease = await repo.aclaim(session, job.id, configuration=CONFIG)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.amark_move_ready(session, logical_receipt={}, lease=lease)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aclaim_next_item(session, lease, configuration=CONFIG)


async def test_receipt_from_committed_prior_transaction_cannot_mark_ready(moving, accepted, monkeypatch):
    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
    async with built.sessions() as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await mark(session, built, receipt)
        assert (await session.get(Job, built.job_id)).move_logical_marker is None


async def test_pre_ready_item_lease_and_checkpoint_cannot_bypass_guard(moving, accepted, monkeypatch):
    from bisheng.knowledge.domain.schemas.processing_job_acceptance import ItemLease

    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        item = (await session.execute(sa.select(Item))).scalars().one()
        await session.execute(
            sa.update(Item.__table__)
            .where(Item.id == item.id)
            .values(
                state="running",
                lease_token="observed-native-token",
                claim_generation=1,
                lease_until=built.lease.lease_until,
            )
        )
        lease = ItemLease(built.lease, item.id, "observed-native-token", 1, built.lease.lease_until)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.asave_checkpoint(
                session, lease, configuration=CONFIG, step="forged", checkpoint={"logical_move": {}}
            )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.acomplete_item(session, lease, configuration=CONFIG, succeeded=True)


@pytest.mark.parametrize("changed", ["foreign-item", "missing-item", "file-after", "root-after"])
async def test_receipt_does_not_hide_changed_native_closure_after_issuance(moving, accepted, monkeypatch, changed):
    from bisheng.knowledge.domain.models.knowledge import Knowledge

    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
        if changed == "foreign-item":
            await session.execute(
                sa.insert(Item.__table__).values(
                    id="foreign-extra",
                    tenant_id=202,
                    job_id=built.job_id,
                    file_id=999,
                    document_id=80,
                    version_id=999,
                    expected_space_id=11,
                    processing_snapshot={},
                    checkpoint={},
                    result={},
                )
            )
        elif changed == "missing-item":
            await session.execute(sa.delete(Item.__table__).where(Item.job_id == built.job_id))
        elif changed == "file-after":
            await session.execute(
                sa.update(File.__table__).where(File.id == 81).values(object_name="changed-after-receipt")
            )
        else:
            await session.execute(
                sa.update(Knowledge.__table__).where(Knowledge.id == 10).values(model_config_revision=99)
            )
        with pytest.raises(Exception) as failure:
            await mark(session, built, receipt)
        assert type(failure.value).__module__.startswith("bisheng.common.errcode")
        assert (await session.get(Job, built.job_id)).move_logical_marker is None


async def test_lease_expiring_after_item_flush_cannot_write_global_ready(moving, accepted, monkeypatch):
    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
        execute, expired = session.execute, []

        async def expire(statement, *args, **kwargs):
            result = await execute(statement, *args, **kwargs)
            if not expired and getattr(statement, "is_update", False) and statement.table.name == Item.__tablename__:
                expired.append(True)
                built.clock[0] += timedelta(seconds=901)
            return result

        monkeypatch.setattr(session, "execute", expire)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await mark(session, built, receipt)
        monkeypatch.setattr(session, "execute", execute)
    async with built.sessions() as session, session.begin():
        assert expired and (await session.get(Job, built.job_id)).move_logical_marker is None
        built.lease = await built.repo.aclaim(session, built.job_id, configuration=CONFIG)
        assert built.lease is not None
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await built.repo.aclaim_next_item(session, built.lease, configuration=CONFIG)


async def test_fresh_receipt_after_takeover_preserves_historical_marker_and_successes(moving, accepted, monkeypatch):
    built = await pipeline(moving, accepted, monkeypatch, count=2)
    async with built.sessions() as session, session.begin():
        await mark(session, built, await logical(session, built))
        done = await built.repo.aclaim_next_item(session, built.lease, configuration=CONFIG)
        assert await built.repo.acomplete_item(
            session, done.lease, configuration=CONFIG, succeeded=True, result={"original": 1}
        )
        before = deepcopy((await session.get(Job, built.job_id)).move_logical_marker)
        completed = (
            done.item.id,
            done.item.state,
            done.item.attempt,
            deepcopy(done.item.result),
            deepcopy(done.item.checkpoint),
        )
    built.clock[0] += timedelta(seconds=901)
    async with built.sessions() as session, session.begin():
        built.lease = await built.repo.aclaim(session, built.job_id, configuration=CONFIG)
        result = await mark(session, built, await logical(session, built))
        assert result.reused
        assert (await session.get(Job, built.job_id)).move_logical_marker == before
        row = await session.get(Item, completed[0])
        assert (row.id, row.state, row.attempt, row.result, row.checkpoint) == completed


async def test_unknown_result_after_final_job_marker_does_not_compensate_committed_ready(moving, accepted, monkeypatch):
    built = await pipeline(moving, accepted, monkeypatch)
    hit = []

    def uncertain(_c, _cu, sql, _params, _ctx, _many):
        if not hit and sql.lstrip().upper().startswith("UPDATE KNOWLEDGE_PROCESSING_JOB"):
            hit.append(True)
            raise RuntimeError("after final real Job marker write")

    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
        sa.event.listen(moving.engine.sync_engine, "after_cursor_execute", uncertain)
        try:
            with pytest.raises(RuntimeError, match="final real Job"):
                await mark(session, built, receipt)
        finally:
            sa.event.remove(moving.engine.sync_engine, "after_cursor_execute", uncertain)
    async with built.sessions() as session, session.begin():
        assert hit and (await session.get(Job, built.job_id)).move_logical_marker is not None
        assert await built.repo.aclaim_next_item(session, built.lease, configuration=CONFIG) is not None

"""Formal all-tenant freeze owns no transaction and never writes business rows."""

from dataclasses import FrozenInstanceError

import pytest
from sqlalchemy import event
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from test.knowledge_unification import test_migration_ledger as old

ledger = old.ledger
repo = old.repo
IDS = (101, 202)


async def freeze(repo, session, **changes):
    return await repo.afreeze_all(
        session, **(old.IDENTITY | {"tenant_ids": IDS, "baseline_ref": old.BASELINE, "plan_ref": old.PLAN} | changes)
    )


async def get(repo, session, **changes):
    return await repo.aget_global_freeze(session, **(old.IDENTITY | {"tenant_ids": IDS} | changes))


async def test_actual_disabled_tenant_is_included_and_caller_commit_controls_all_rows(repo, ledger):
    async with AsyncSession(ledger, expire_on_commit=False) as session, session.begin():
        assert await get(repo, session) is None
        result = await freeze(repo, session)
        assert result.tenant_ids == IDS and result.baseline_ref == old.BASELINE and result.plan_ref == old.PLAN
        assert session.in_transaction()
        with bypass_tenant_filter():
            rows = (
                (await session.execute(select(KnowledgeUnificationRun).order_by(KnowledgeUnificationRun.tenant_id)))
                .scalars()
                .all()
            )
        assert [(row.tenant_id, row.phase) for row in rows] == [(101, "baseline_frozen"), (202, "baseline_frozen")]
        assert all(row.source_coverage == {} and row.origin == "migration" for row in rows)
        with pytest.raises(FrozenInstanceError):
            result.run_id = "other"
    async with AsyncSession(ledger) as session, session.begin():
        assert await get(repo, session) == result


async def test_complete_replay_is_zero_mutation_and_requires_same_descriptors(repo, ledger):
    async with AsyncSession(ledger) as session, session.begin():
        await freeze(repo, session)
    writes = []
    async with AsyncSession(ledger) as session, session.begin():
        event.listen(session.sync_session, "before_flush", lambda *args: writes.append(True))
        assert (await freeze(repo, session)).baseline_ref == old.BASELINE
        assert writes == []
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await freeze(repo, session, plan_ref=old.PLAN | {"sha256": "c" * 64})
        assert writes == []


@pytest.mark.parametrize("ids", [(101,), (202, 101), (101, 101, 202), (101, True), [101, 202], ()])
async def test_exact_actual_tenant_set_and_order_are_mandatory(repo, ledger, ids):
    async with AsyncSession(ledger) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await freeze(repo, session, tenant_ids=ids)
        assert not session.new and not session.dirty


@pytest.mark.parametrize("state", ["partial", "failed", "mixed", "writer", "other_run", "empty_origin"])
async def test_existing_inconsistent_runs_are_rejected_before_any_flush(repo, ledger, state):
    async with AsyncSession(ledger) as session, session.begin():
        for ident in IDS if state != "partial" else IDS[:1]:
            with tenant_execution_scope(ident):
                await old.freeze(repo, session)
        with bypass_tenant_filter():
            rows = (await session.execute(select(KnowledgeUnificationRun))).scalars().all()
        if state == "failed":
            rows[-1].phase = "failed"
            rows[-1].checkpoints = {"_failed_from_phase": "baseline_frozen"}
            rows[-1].error_code, rows[-1].error_reason = 10998, "failed"
        elif state == "mixed":
            rows[-1].phase = "preparing"
            rows[-1].baseline_ref = rows[-1].plan_ref = {}
            rows[-1].baseline_hash = rows[-1].plan_hash = None
        elif state == "writer":
            rows[-1].writer_contract_version = "other-writer"
        elif state == "other_run":
            session.add(
                KnowledgeUnificationRun(tenant_id=101, run_id="different-run", writer_contract_version=old.WRITER)
            )
        elif state == "empty_origin":
            rows[-1].origin = "empty_tenant"
        await session.flush()
    async with AsyncSession(ledger) as session, session.begin():
        flushes = []
        event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await freeze(repo, session)
        assert flushes == []


async def test_tenant_drift_and_pending_business_are_not_silently_flushed(repo, ledger):
    async with AsyncSession(ledger) as session, session.begin():
        tenant = (await session.execute(select(Tenant).where(Tenant.id == 101))).scalar_one()
        tenant.tenant_name = "caller-private-edit"
        flushes = []
        event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        assert await get(repo, session) is None
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await freeze(repo, session)
        assert tenant in session.dirty and flushes == []
        await session.rollback()
    async with AsyncSession(ledger) as session, session.begin():
        await freeze(repo, session)
    async with AsyncSession(ledger) as session, session.begin():
        session.add(Tenant(id=303, tenant_code="new", tenant_name="New"))
        await session.flush()
    async with AsyncSession(ledger) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await get(repo, session)


async def test_external_rollback_removes_every_tenant_freeze_and_locks_are_ordered(repo, ledger):
    async with AsyncSession(ledger) as session:
        await session.begin()
        locks = []
        event.listen(
            session.sync_session,
            "do_orm_execute",
            lambda state: (
                locks.append(state.statement)
                if state.is_select and state.statement._for_update_arg is not None
                else None
            ),
        )
        await freeze(repo, session)
        assert locks and "tenant" in str(locks[0])
        assert all("ORDER BY" in str(statement) for statement in locks)
        await session.rollback()
    async with AsyncSession(ledger) as session, session.begin():
        assert await get(repo, session) is None


async def test_native_transaction_and_non_bypassed_scope_are_required(repo, ledger):
    async with AsyncSession(ledger) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await freeze(repo, session)
        await session.begin()
        with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
            await freeze(repo, session)


@pytest.mark.parametrize("later_phase", ["converting", "backfilling", "verifying", "verified", "completed"])
async def test_same_frozen_proof_survives_independent_tenant_progress_without_reinventory(repo, ledger, later_phase):
    async with AsyncSession(ledger) as session, session.begin():
        result = await freeze(repo, session)
        with bypass_tenant_filter():
            row = (
                await session.execute(select(KnowledgeUnificationRun).where(KnowledgeUnificationRun.tenant_id == 202))
            ).scalar_one()
        row.phase = later_phase
        await session.flush()
    async with AsyncSession(ledger) as session, session.begin():
        flushes = []
        event.listen(session.sync_session, "before_flush", lambda *args: flushes.append(True))
        assert await get(repo, session) == result
        assert await freeze(repo, session) == result
        assert flushes == []

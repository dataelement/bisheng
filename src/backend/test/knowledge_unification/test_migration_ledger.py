"""T159: immutable migration evidence and caller-owned progress transactions.

覆盖 AC: AC-56, AC-63, AC-64, AC-85, AC-89, AC-93.
Native SQLite verifies storage, isolation and sequential CAS, not MySQL locks.
DM8 runtime verification is waived by the user; portable SQL remains required.
"""

import importlib
from copy import deepcopy
from itertools import pairwise

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.core.database import tenant_filter
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.knowledge.domain.repositories.reference_legacy_evidence_repository import KnowledgeLegacyEvidenceRepository
from bisheng.resource_reference.application.contracts import SourceKey

WRITER = "f118-v1"
RUN = "maintenance-1"
BASELINE = {"object_key": "runs/maintenance-1/baseline.json", "sha256": "a" * 64}
PLAN = {"object_key": "runs/maintenance-1/plan.json", "sha256": "b" * 64}
HASHES = {"baseline_hash": BASELINE["sha256"], "plan_hash": PLAN["sha256"]}
IDENTITY = {"run_id": RUN, "writer_contract_version": WRITER}
PHASES = ["baseline_frozen", "converting", "backfilling", "verifying", "verified", "completed"]
EMPTY = {"cursor": None, "processed_count": 0, "digest": None, "complete": False}
FIRST = {"cursor": "resource-7", "processed_count": 7, "digest": "c" * 64, "complete": False}
DONE = {"cursor": "resource-9", "processed_count": 9, "digest": "d" * 64, "complete": True}


@pytest.fixture
def repo():
    module = importlib.import_module("bisheng.knowledge.domain.repositories.unification_run_repository")
    return module.KnowledgeUnificationRunRepository()


@pytest.fixture
async def ledger(monkeypatch):
    names = {KnowledgeUnificationRun.__tablename__}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()
    token = set_current_tenant_id(101)
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda conn: SQLModel.metadata.create_all(
                    conn, tables=[Tenant.__table__, KnowledgeUnificationRun.__table__]
                )
            )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    Tenant(id=101, tenant_code="first", tenant_name="First", status="disabled"),
                    Tenant(id=202, tenant_code="second", tenant_name="Second"),
                ]
            )
            await session.commit()
        yield engine
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


async def freeze(repo, session):
    await repo.aget_or_create(session, **IDENTITY)
    return await repo.afreeze(session, **IDENTITY, baseline_ref=BASELINE, plan_ref=PLAN)


async def converting(repo, session):
    await freeze(repo, session)
    return await repo.aadvance(session, **IDENTITY, **HASHES, expected_phase="baseline_frozen", next_phase="converting")


async def checkpoint(repo, session, expected, value, **changes):
    args = dict(
        IDENTITY, **HASHES, expected_phase="converting", checkpoint_key="knowledge", expected_checkpoint=expected
    )
    args.update(changes)
    return await repo.acheckpoint(session, **args, checkpoint=value)


async def test_schema_precheck_is_read_only_and_creation_locks_the_real_tenant_first(repo, ledger):
    statements = []
    async with AsyncSession(ledger) as session:

        def observe(state):
            statement = state.statement
            tables = tuple(table.name for table in statement.get_final_froms()) if state.is_select else ()
            statements.append((tables, statement._for_update_arg is not None))

        event.listen(session.sync_session, "do_orm_execute", observe)
        await repo.aschema_precheck(session)
        assert await repo.aget(session, **IDENTITY) is None
        assert not session.new
        statements.clear()
        row = await repo.aget_or_create(session, **IDENTITY)
        locks = [tables for tables, locked in statements if locked]
        assert locks[0] == ("tenant",) and locks[1] == ("knowledge_unification_run",)
        assert (row.tenant_id, row.origin, row.phase, row.writer_contract_version) == (
            101,
            "migration",
            "preparing",
            WRITER,
        )
        assert row.baseline_hash is row.plan_hash is None
        assert (
            row.baseline_ref == row.plan_ref == row.checkpoints == row.source_coverage == row.verification_report == {}
        )
        assert (await repo.aget_or_create(session, **IDENTITY)).id == row.id


async def test_schema_precheck_does_not_autoflush_the_callers_pending_writes(repo, ledger):
    async with AsyncSession(ledger) as session:
        pending = KnowledgeUnificationRun(run_id="pending-owner-write", writer_contract_version=WRITER)
        session.add(pending)
        await repo.aschema_precheck(session)
        assert pending in session.new
        assert pending.tenant_id is None


async def test_freeze_is_immutable_idempotent_and_consumable_by_the_actual_legacy_reader(repo, ledger):
    async with AsyncSession(ledger) as session:
        row = await freeze(repo, session)
        source = SourceKey(101, "assistant", "a1", "current")
        assert KnowledgeLegacyEvidenceRepository._facts(row, source, RUN, "original-slot") == (
            RUN,
            BASELINE["sha256"],
            "original-slot",
        )
        original_id = row.id
        for phase, next_phase in pairwise(PHASES):
            row = await repo.aadvance(session, **IDENTITY, **HASHES, expected_phase=phase, next_phase=next_phase)
            repeated = await repo.afreeze(session, **IDENTITY, baseline_ref=deepcopy(BASELINE), plan_ref=deepcopy(PLAN))
            assert repeated.id == original_id and repeated.phase == next_phase
            assert repeated.source_coverage == repeated.verification_report == {}
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aadvance(session, **IDENTITY, **HASHES, expected_phase="completed", next_phase="converting")


@pytest.mark.parametrize("field", ["baseline_ref", "plan_ref"])
async def test_changed_frozen_hash_or_locator_is_rejected_without_rewinding(repo, ledger, field):
    async with AsyncSession(ledger) as session:
        row = await converting(repo, session)
        for changed in ("sha256", "object_key"):
            refs = {"baseline_ref": deepcopy(BASELINE), "plan_ref": deepcopy(PLAN)}
            refs[field][changed] = "e" * 64 if changed == "sha256" else "runs/other-plan.json"
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.afreeze(session, **IDENTITY, **refs)
            assert row.phase == "converting" and row.baseline_ref == BASELINE and row.plan_ref == PLAN


@pytest.mark.parametrize(
    "descriptor",
    [
        {},
        {"object_key": "runs/a", "sha256": "A" * 64},
        {"object_key": "runs/a", "sha256": "z" * 64},
        {"object_key": "runs/a", "sha256": "a" * 63},
        {"object_key": " ", "sha256": "a" * 64},
        {"object_key": "/private/tmp/baseline.json", "sha256": "a" * 64},
        {"object_key": "file:baseline.json", "sha256": "a" * 64},
        {"object_key": "https://objects/a?signature=example", "sha256": "a" * 64},
        {"object_key": "runs/a", "sha256": "a" * 64, "business_config": {"private": "not-stored"}},
    ],
)
async def test_artifacts_accept_only_the_frozen_durable_descriptor(repo, ledger, descriptor):
    async with AsyncSession(ledger) as session:
        row = await repo.aget_or_create(session, **IDENTITY)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.afreeze(session, **IDENTITY, baseline_ref=descriptor, plan_ref=PLAN)
        assert row.phase == "preparing" and row.baseline_ref == {} and row.baseline_hash is None


@pytest.mark.parametrize(
    "phase,next_phase,hashes",
    [
        ("preparing", "converting", {"baseline_hash": None, "plan_hash": None}),
        ("baseline_frozen", "backfilling", HASHES),
        ("converting", "baseline_frozen", HASHES),
        ("failed", "converting", HASHES),
        ("converting", "backfilling", dict(HASHES, baseline_hash="f" * 64)),
    ],
)
async def test_advancement_requires_the_exact_phase_and_original_hashes(repo, ledger, phase, next_phase, hashes):
    async with AsyncSession(ledger) as session:
        row = await repo.aget_or_create(session, **IDENTITY) if phase == "preparing" else await freeze(repo, session)
        if phase == "converting":
            row = await converting(repo, session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aadvance(session, **IDENTITY, **hashes, expected_phase=phase, next_phase=next_phase)
        assert row.phase == (
            "preparing" if phase == "preparing" else "converting" if phase == "converting" else "baseline_frozen"
        )


async def test_checkpoint_cas_replay_and_monotonic_progress(repo, ledger):
    async with AsyncSession(ledger) as session:
        await converting(repo, session)
        row = await checkpoint(repo, session, None, FIRST)
        original = deepcopy(row.checkpoints)
        assert (await checkpoint(repo, session, None, FIRST)).checkpoints == original
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await checkpoint(repo, session, None, DONE)
        await checkpoint(repo, session, FIRST, DONE)
        assert (await repo.aget(session, **IDENTITY)).checkpoints["converting"]["knowledge"] == DONE
        for regression in (FIRST, dict(DONE, processed_count=8), dict(DONE, complete=False)):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await checkpoint(repo, session, DONE, regression)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await checkpoint(repo, session, DONE, DONE, expected_phase="backfilling")


@pytest.mark.parametrize(
    "bad_checkpoint",
    [
        {"cursor": None},
        dict(EMPTY, processed_count=-1),
        dict(EMPTY, processed_count=True),
        dict(EMPTY, cursor={"full_config": "forbidden"}),
        dict(EMPTY, digest="A" * 64),
        dict(EMPTY, complete=1),
        dict(EMPTY, authorization="not-stored"),
    ],
)
async def test_checkpoint_payload_is_closed_and_does_not_store_configuration(repo, ledger, bad_checkpoint):
    async with AsyncSession(ledger) as session:
        row = await converting(repo, session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await checkpoint(repo, session, None, bad_checkpoint)
        assert row.checkpoints == {}


async def test_failed_conversion_resumes_only_its_original_baseline_and_checkpoint(repo, ledger):
    async with AsyncSession(ledger, expire_on_commit=False) as session:
        await converting(repo, session)
        row = await checkpoint(repo, session, None, FIRST)
        saved_id = row.id
        await repo.afail(
            session,
            **IDENTITY,
            **HASHES,
            expected_phase="converting",
            error_code=10994,
            error_reason="batch_incomplete",
        )
        assert row.phase == "failed" and row.checkpoints["converting"]["knowledge"] == FIRST
        with pytest.raises(ReferenceCoverageNotReadyError):
            KnowledgeLegacyEvidenceRepository._facts(row, SourceKey(101, "assistant", "a1", "current"), RUN, "ev")
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.afreeze(session, **IDENTITY, baseline_ref=BASELINE, plan_ref=PLAN)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aresume(session, **IDENTITY, baseline_hash="f" * 64, plan_hash=PLAN["sha256"])
        await session.commit()
    async with AsyncSession(ledger) as session:
        row = await repo.aresume(session, **IDENTITY, **HASHES)
        assert row.id == saved_id and row.phase == "converting"
        assert row.baseline_ref == BASELINE and row.plan_ref == PLAN
        assert row.checkpoints["converting"]["knowledge"] == FIRST
        assert row.error_code is row.error_reason is None
        await checkpoint(repo, session, FIRST, DONE)


async def test_failed_preparation_cannot_claim_a_frozen_baseline(repo, ledger):
    async with AsyncSession(ledger) as session:
        await repo.aget_or_create(session, **IDENTITY)
        hashes = {"baseline_hash": None, "plan_hash": None}
        row = await repo.afail(
            session,
            **IDENTITY,
            **hashes,
            expected_phase="preparing",
            error_code=10994,
            error_reason="inventory_incomplete",
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aresume(session, **IDENTITY, **HASHES)
        row = await repo.aresume(session, **IDENTITY, **hashes)
        assert row.phase == "preparing" and row.baseline_ref == {} and row.plan_hash is None
        with pytest.raises(ReferenceCoverageNotReadyError):
            KnowledgeLegacyEvidenceRepository._facts(row, SourceKey(101, "assistant", "a1", "current"), RUN, "ev")


async def test_owner_rollback_removes_new_run_and_reverts_frozen_checkpoint_progress(repo, ledger):
    async with AsyncSession(ledger) as session:
        await converting(repo, session)
        await checkpoint(repo, session, None, FIRST)
        await session.rollback()
    async with AsyncSession(ledger) as session:
        assert await repo.aget(session, **IDENTITY) is None
        await converting(repo, session)
        await checkpoint(repo, session, None, FIRST)
        await session.commit()
        await checkpoint(repo, session, FIRST, DONE)
        await repo.afail(
            session,
            **IDENTITY,
            **HASHES,
            expected_phase="converting",
            error_code=10994,
            error_reason="batch_incomplete",
        )
        await session.rollback()
        row = await repo.aget(session, **IDENTITY)
        assert row.phase == "converting" and row.checkpoints["converting"]["knowledge"] == FIRST


async def test_other_run_or_writer_cannot_replace_an_existing_tenant_baseline(repo, ledger):
    async with AsyncSession(ledger) as session:
        await freeze(repo, session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aget_or_create(session, run_id="replacement", writer_contract_version=WRITER)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aget(session, run_id=RUN, writer_contract_version="f118-other")
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.afreeze(
                session, run_id=RUN, writer_contract_version="f118-other", baseline_ref=BASELINE, plan_ref=PLAN
            )


async def test_same_run_id_in_another_tenant_is_independent_and_root_visibility_does_not_expand_it(repo, ledger):
    async with AsyncSession(ledger) as session:
        first = await freeze(repo, session)
        first_id = first.id
        await session.commit()
    token = set_current_tenant_id(202)
    try:
        async with AsyncSession(ledger) as session:
            assert await repo.aget(session, **IDENTITY) is None
            second = await freeze(repo, session)
            assert second.tenant_id == 202 and second.id != first_id
            await session.commit()
    finally:
        current_tenant_id.reset(token)
    async with AsyncSession(ledger) as session:
        assert (await repo.aget(session, **IDENTITY)).id == first_id


async def test_empty_tenant_origin_cannot_be_adopted_as_a_migration(repo, ledger):
    async with AsyncSession(ledger) as session:
        session.add(KnowledgeUnificationRun(tenant_id=101, **IDENTITY, origin="empty_tenant", phase="completed"))
        await session.flush()
        for method in (repo.aget, repo.aget_or_create):
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await method(session, **IDENTITY)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.afreeze(session, **IDENTITY, baseline_ref=BASELINE, plan_ref=PLAN)


async def test_missing_real_tenant_and_bypassed_or_ambiguous_scope_fail_closed(repo, ledger):
    async with AsyncSession(ledger) as session:
        token = set_current_tenant_id(303)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.aget_or_create(session, **IDENTITY)
        finally:
            current_tenant_id.reset(token)
        with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aget(session, **IDENTITY)
        token = set_current_tenant_id(None)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.aschema_precheck(session)
        finally:
            current_tenant_id.reset(token)


@pytest.mark.parametrize("structure", ["missing_table", "missing_column"])
async def test_schema_precheck_fails_without_repairing_incomplete_existing_storage(repo, ledger, structure):
    async with ledger.begin() as connection:
        await connection.run_sync(lambda conn: KnowledgeUnificationRun.__table__.drop(conn))
        if structure == "missing_column":
            await connection.execute(text("CREATE TABLE knowledge_unification_run (id VARCHAR(36) PRIMARY KEY)"))
    async with AsyncSession(ledger) as session:
        with pytest.raises(ReferenceCoverageNotReadyError):
            await repo.aschema_precheck(session)
    async with ledger.connect() as connection:
        columns = await connection.run_sync(
            lambda conn: (
                [column["name"] for column in inspect(conn).get_columns("knowledge_unification_run")]
                if inspect(conn).has_table("knowledge_unification_run")
                else None
            )
        )
    assert columns == (["id"] if structure == "missing_column" else None)


async def test_tampered_persisted_frozen_descriptor_is_not_accepted_as_authority(repo, ledger):
    async with AsyncSession(ledger) as session:
        row = await freeze(repo, session)
        row.baseline_hash = "e" * 64
        await session.flush()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.aget(session, **IDENTITY)
        rows = (await session.execute(select(KnowledgeUnificationRun))).scalars().all()
        assert len(rows) == 1 and rows[0].baseline_hash == "e" * 64

"""Native Run fencing; SQLite does not establish MySQL/DM NOWAIT behavior."""

from contextlib import asynccontextmanager
from hashlib import sha256

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.knowledge.domain.repositories.unification_executor_repository import UnificationExecutorRepository


@pytest.fixture
async def execution_sessions():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: SQLModel.metadata.create_all(c, tables=[Tenant.__table__, KnowledgeUnificationRun.__table__])
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    with tenant_execution_scope(1):
        async with sessions() as session, session.begin():
            session.add(Tenant(id=1, tenant_code="root", tenant_name="Root"))
        yield sessions
    await engine.dispose()


async def test_native_attempt_rejects_unknown_dispatch_and_stale_sql_token(execution_sessions):
    repo = UnificationExecutorRepository()
    inputs = {"run_id": "upgrade-1", "writer_contract_version": "f118-v1"}
    async with execution_sessions() as session, session.begin():
        attempt = await repo.abegin_attempt(session, **inputs)
    async with execution_sessions() as session, session.begin():
        ticket = await repo.abegin_external(session, **inputs, token=attempt, kind="fga", identity={"batch": 1})
    async with execution_sessions() as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await repo.abegin_attempt(session, **inputs)
        assert caught.value.kwargs["reason"] == "migration_executor_recovery_required"
    async with execution_sessions() as session, session.begin():
        await repo.afinish_external(
            session, **inputs, token=attempt, ticket=ticket, outcome="acknowledged", receipt="a" * 64
        )
        await repo.afinish_attempt(session, **inputs, token=attempt)
    async with execution_sessions() as session, session.begin():
        replacement = await repo.abegin_attempt(session, **inputs)
        assert replacement != attempt
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.acheck_attempt(session, **inputs, token=attempt)
        await repo.acheck_attempt(session, **inputs, token=replacement)


async def test_attempt_checkpoint_has_exact_native_fields_and_completed_is_read_only(execution_sessions):
    repo = UnificationExecutorRepository()
    inputs = {"run_id": "upgrade-1", "writer_contract_version": "f118-v1"}
    async with execution_sessions() as session, session.begin():
        token = await repo.abegin_attempt(session, **inputs)
        row = await repo.runs.aget(session, **inputs)
        assert set(row.checkpoints["preparing"]["executor_attempt_v1"]) == {
            "cursor",
            "processed_count",
            "digest",
            "complete",
        }
        await repo.afinish_attempt(session, **inputs, token=token)
    async with execution_sessions() as session, session.begin():
        row = await repo.runs._required(session, **inputs)
        row.phase = "completed"
        row.baseline_hash = "a" * 64
        row.plan_hash = "b" * 64
        row.baseline_ref = {"object_key": "baseline", "sha256": "a" * 64}
        row.plan_ref = {"object_key": "plan", "sha256": "b" * 64}
        session.add(row)
    async with execution_sessions() as session, session.begin():
        assert await repo.abegin_attempt(session, **inputs) is None


async def test_failure_positions_include_the_native_retirement_checkpoint(execution_sessions):
    from bisheng.knowledge.domain.repositories.unification_upgrade_repository import UpgradeRunRepository

    repo = UnificationExecutorRepository()
    inputs = {"run_id": "upgrade-1", "writer_contract_version": "f118-v1"}
    cursor = "native-retirement-position-7"
    async with execution_sessions() as session, session.begin():
        row = await repo.runs.aget_or_create(session, **inputs)
        row.phase = "backfilling"
        row.baseline_hash, row.plan_hash = "a" * 64, "b" * 64
        row.baseline_ref = {"object_key": "original-baseline", "sha256": row.baseline_hash}
        row.plan_ref = {"object_key": "original-plan", "sha256": row.plan_hash}
        session.add(row)
        await session.flush()
        await repo.runs.acheckpoint(
            session,
            **inputs,
            baseline_hash=row.baseline_hash,
            plan_hash=row.plan_hash,
            expected_phase="backfilling",
            checkpoint_key="references_retired",
            expected_checkpoint=None,
            checkpoint={"cursor": cursor, "processed_count": 7, "digest": "c" * 64, "complete": False},
        )
    async with execution_sessions() as session, session.begin():
        state = await UpgradeRunRepository().aload_state(session, **inputs)
    assert state.positions == (
        {
            "tenant_id": 1,
            "phase": "backfilling",
            "checkpoint": "references_retired",
            "processed_count": 7,
            "complete": False,
            "cursor_sha256": sha256(cursor.encode()).hexdigest(),
        },
    )
    assert cursor not in str(state.positions)

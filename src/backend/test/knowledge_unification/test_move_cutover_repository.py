"""T926: actual plan/native TX cutover; P1 positive evidence follows its fixed prefix."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeOperationPlanChangedError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.knowledge.domain.repositories.move_cutover_repository import MoveCutoverRepository
from bisheng.knowledge.domain.repositories.operation_plan_repository import OperationPlanRepository
from test.knowledge_unification import test_move_scope_repository as fixtures

store, tenant, moving = fixtures.store, fixtures.tenant, fixtures.moving
ACTOR = {"tenant_id": 101, "actor_user_id": 7, "entry_kind": "web", "required_action": "move", "space_id": 10}


async def confirmation(session, scope):
    return await OperationPlanRepository().acreate(
        session,
        operation="move",
        space_id=10,
        actor_reference=ACTOR,
        targets=[leaf.target for leaf in scope.leaves],
        target_revisions={"scope_digest": scope.scope_digest},
        source_revisions={"source": scope.source, "destination": scope.destination},
        parameters=scope.to_parameters(),
        impact={"logical_count": len(scope.files)},
        expires_at=datetime.now() + timedelta(hours=1),
    )


@pytest.mark.parametrize("tamper", ["metadata", "destination", "actor", "plan"])
async def test_reservation_reloads_real_scope_and_confirmation_before_issuing(moving, tamper):
    async with AsyncSession(moving.engine, expire_on_commit=False) as session:
        scope = await fixtures.load(moving, session)
        plan = await confirmation(session, scope)
        await session.commit()
        if tamper == "metadata":
            scope.files[1].after["user_metadata"]["keep"]["field_value"] = "changed"
        elif tamper == "destination":
            scope = replace(scope, destination_space_id=20)
        actor = {**ACTOR, "actor_user_id": 8} if tamper == "actor" else ACTOR
        digest = "f" * 64 if tamper == "plan" else plan.plan_digest
        repo = MoveCutoverRepository(scope_repository=moving.repo)
        with pytest.raises((KnowledgeOperationPlanConflictError, KnowledgeOperationPlanChangedError)):
            await repo.aprepare_reservation(
                session,
                scope=scope,
                confirmation_id=plan.confirmation_id,
                plan_digest=digest,
                actor_user_id=actor["actor_user_id"],
                actor_reference=actor,
            )
        assert (await session.get(KnowledgeFile, 81)).knowledge_id == 10


async def test_reservation_has_actual_native_tx_identity_and_never_moves_or_commits(moving):
    repo = MoveCutoverRepository(scope_repository=moving.repo)
    async with AsyncSession(moving.engine, expire_on_commit=False) as session:
        scope = await fixtures.load(moving, session)
        plan = await confirmation(session, scope)
        await session.commit()
        receipt = await repo.aprepare_reservation(
            session,
            scope=scope,
            confirmation_id=plan.confirmation_id,
            plan_digest=plan.plan_digest,
            actor_user_id=7,
            actor_reference=ACTOR,
        )
        assert len(receipt.job_id) == 36 and receipt.plan_id == plan.confirmation_id
        assert receipt.scope_digest == scope.scope_digest
        repo.assert_reservation_current(receipt, session)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            repo.assert_reservation_current(replace(receipt), session)
        assert (await session.get(KnowledgeFile, 81)).knowledge_id == 10
        await session.rollback()
        await session.execute(select(KnowledgeFile.id).limit(1))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            repo.assert_reservation_current(receipt, session)
    async with AsyncSession(moving.engine) as session:
        stored = await session.get(KnowledgeOperationPlan, plan.confirmation_id)
        assert stored.operation_id is None


async def test_native_mutator_rejects_caller_pending_before_savepoint_autoflush(moving):
    async with AsyncSession(moving.engine) as session:
        scope = await fixtures.load(moving, session)
        plan = await confirmation(session, scope)
        await session.commit()
        other = await session.get(KnowledgeFile, 81)
        other.remark = "caller-owned-pending"
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await MoveCutoverRepository(scope_repository=moving.repo).aprepare_reservation(
                session,
                scope=scope,
                confirmation_id=plan.confirmation_id,
                plan_digest=plan.plan_digest,
                actor_user_id=7,
                actor_reference=ACTOR,
            )
        assert other in session.dirty and other.remark == "caller-owned-pending"

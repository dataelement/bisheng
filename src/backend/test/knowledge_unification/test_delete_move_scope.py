"""Deletion may narrow native move guards only against complete frozen scope."""

from copy import deepcopy

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan as Plan
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.knowledge_deletion_execution_repository import (
    KnowledgeDeletionExecutionRepository,
)
from bisheng.knowledge.domain.repositories.source_move_input_repository import SourceMoveInputRepository
from test.knowledge_unification import test_move_job_reservation as native

store, tenant, moving, accepted = native.store, native.tenant, native.moving, native.accepted


@pytest.mark.parametrize("state", ["accepted", "running", "failed", "partial_failed", "obsolete"])
async def test_unrelated_delete_scope_passes_both_sides_but_related_files_and_whole_space_stay_protected(
    moving, accepted, state
):
    job = (await native.create(moving, (await accepted()).args)).job
    async with AsyncSession(moving.engine) as session, session.begin():
        await session.execute(sa.update(Job).where(Job.id == job.id).values(state=state))
        source, target = SourceMoveInputRepository(), KnowledgeDeletionExecutionRepository()
        await source.arequire_released(session, space_id=10, file_ids=(98592, 98593))
        await target.arequire_transfer_idle(session, space_id=11, file_ids=(98592, 98593))
        for related in (50, 81, 82):
            with pytest.raises(KnowledgeProcessingConflictError):
                await source.arequire_released(session, space_id=10, file_ids=(98592, related))
            with pytest.raises(KnowledgeProcessingConflictError):
                await target.arequire_transfer_idle(session, space_id=11, file_ids=(98592, related))
        with pytest.raises(KnowledgeProcessingConflictError):
            await source.arequire_released(session, space_id=10)
        with pytest.raises(KnowledgeProcessingConflictError):
            await target.arequire_transfer_idle(session, space_id=11)


@pytest.mark.parametrize("damage", ["missing_plan", "manifest", "scope", "item", "foreign_item"])
async def test_unknown_move_scope_cannot_release_unrelated_target_deletion(moving, accepted, damage):
    prepared = await accepted()
    job = (await native.create(moving, prepared.args)).job
    async with AsyncSession(moving.engine) as session, session.begin():
        if damage == "missing_plan":
            await session.execute(sa.delete(Plan).where(Plan.id == job.parameters["confirmation_id"]))
        elif damage == "manifest":
            await session.execute(sa.update(Job).where(Job.id == job.id).values(scope_manifest=[]))
        elif damage == "scope":
            await session.execute(
                sa.update(Plan).where(Plan.id == job.parameters["confirmation_id"]).values(parameters={})
            )
        elif damage == "item":
            await session.execute(sa.delete(Item).where(Item.job_id == job.id))
        else:
            await session.execute(sa.update(Item).where(Item.job_id == job.id).values(tenant_id=202))
        with pytest.raises(KnowledgeProcessingConflictError):
            await KnowledgeDeletionExecutionRepository().arequire_transfer_idle(session, space_id=11, file_ids=(98592,))


async def test_destination_checks_every_page_of_unsettled_moves(moving, accepted):
    prepared = await accepted(zero="empty")
    job = (await native.create(moving, prepared.args)).job
    async with AsyncSession(moving.engine) as session, session.begin():
        original_plan = await session.get(Plan, job.parameters["confirmation_id"])
        original_job = await session.get(Job, job.id)
        plan_data = {column.name: getattr(original_plan, column.name) for column in Plan.__table__.c}
        job_data = {column.name: getattr(original_job, column.name) for column in Job.__table__.c}
        for index in range(201):
            plan_id, job_id = f"plan-{index:04}", f"job-{index:04}"
            new_plan = deepcopy(plan_data)
            new_job = deepcopy(job_data)
            new_plan.update(id=plan_id, operation_id=job_id)
            new_job.update(id=job_id, idempotency_key=job_id, state="failed")
            new_job["parameters"].update(confirmation_id=plan_id, operation_id=job_id)
            if index < 200:
                session.add(Plan(**new_plan))
            session.add(Job(**new_job))
        await session.flush()
        with pytest.raises(KnowledgeProcessingConflictError):
            await KnowledgeDeletionExecutionRepository().arequire_transfer_idle(session, space_id=11, file_ids=(98592,))


@pytest.mark.parametrize("state", ["accepted", "running", "failed", "partial_failed", "obsolete", "succeeded"])
async def test_scoped_target_guard_preserves_active_copy_protection_but_ignores_terminal_copy(moving, state):
    async with AsyncSession(moving.engine) as session, session.begin():
        session.add(
            Job(
                id="copy",
                tenant_id=101,
                space_id=11,
                kind="space_copy",
                state=state,
                actor_user_id=7,
                idempotency_key="copy",
                request_hash="a" * 64,
                expected_model_config_revision=0,
                total_count=1,
            )
        )
        await session.flush()
        guard = KnowledgeDeletionExecutionRepository()
        if state in {"accepted", "running"}:
            with pytest.raises(KnowledgeProcessingConflictError):
                await guard.arequire_transfer_idle(session, space_id=11, file_ids=(98592,))
        else:
            await guard.arequire_transfer_idle(session, space_id=11, file_ids=(98592,))

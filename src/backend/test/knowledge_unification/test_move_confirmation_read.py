"""§121: trusted persisted confirmation facts, never permission or acceptance."""

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from test.knowledge_unification import test_move_job_reservation as fixtures

store, tenant, moving, accepted = fixtures.store, fixtures.tenant, fixtures.moving, fixtures.accepted


@pytest.mark.parametrize("bad", [None, "source", "digest"])
async def test_public_confirmation_read_binds_actual_plan_to_source_and_digest(moving, accepted, bad):
    confirmed = await accepted()
    repo, _ = fixtures.jobs(moving)
    async with fixtures.AsyncSession(moving.engine) as session, session.begin():
        args = {
            "source_space_id": 11 if bad == "source" else 10,
            "confirmation_id": confirmed.plan.confirmation_id,
            "plan_digest": "f" * 64 if bad == "digest" else confirmed.plan.plan_digest,
        }
        if bad:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.aread_move_confirmation(session, **args)
        else:
            result = await repo.aread_move_confirmation(session, **args)
            assert result.actor_reference == confirmed.origin and result.parameters == confirmed.scope.to_parameters()
            assert result.operation_id is None and result.operation == "move"


@pytest.mark.parametrize("bad", ["operation", "expired"])
async def test_confirmation_read_keeps_native_hash_validation_and_expiry_is_for_accept(moving, accepted, bad):
    from datetime import timedelta

    import sqlalchemy as sa

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanExpiredError
    from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan as Plan
    from bisheng.knowledge.domain.repositories.operation_plan_repository import _digest

    confirmed = await accepted()
    repo, _ = fixtures.jobs(moving)
    async with fixtures.AsyncSession(moving.engine) as session, session.begin():
        plan = await repo._plan(session, confirmed.plan.confirmation_id)
        if bad == "operation":
            plan.operation = "file_reprocess"
        else:
            plan.expires_at = repo.clock() - timedelta(seconds=1)
        plan.request_hash = _digest(repo.cutover.plans._payload(plan))
        plan.plan_digest = repo.cutover.plans._plan_digest(plan)
        await session.execute(
            sa.update(Plan.__table__)
            .where(Plan.id == plan.id)
            .values(
                operation=plan.operation,
                expires_at=plan.expires_at,
                request_hash=plan.request_hash,
                plan_digest=plan.plan_digest,
            )
        )
    async with fixtures.AsyncSession(moving.engine) as session, session.begin():
        if bad == "operation":
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.aread_move_confirmation(
                    session, source_space_id=10, confirmation_id=plan.id, plan_digest=plan.plan_digest
                )
        else:
            actual = await repo.aread_move_confirmation(
                session, source_space_id=10, confirmation_id=plan.id, plan_digest=plan.plan_digest
            )
            assert actual.expires_at == plan.expires_at
            with pytest.raises(KnowledgeOperationPlanExpiredError):
                await repo.acreate_move_reserved(session, **{**confirmed.args, "plan_digest": plan.plan_digest})

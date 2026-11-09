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
        args = dict(
            source_space_id=11 if bad == "source" else 10,
            confirmation_id=confirmed.plan.confirmation_id,
            plan_digest="f" * 64 if bad == "digest" else confirmed.plan.plan_digest,
        )
        if bad:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await repo.aread_move_confirmation(session, **args)
        else:
            result = await repo.aread_move_confirmation(session, **args)
            assert result.actor_reference == confirmed.origin and result.parameters == confirmed.scope.to_parameters()
            assert result.operation_id is None and result.operation == "move"

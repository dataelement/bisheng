"""§121 claim peek uses actual native eligibility before same-TX P1 and claim."""

from datetime import timedelta

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from test.knowledge_unification import test_move_execution_repository as fixtures
from test.knowledge_unification.test_move_execution_fixtures import CONFIG, item_evidence, logical, mark, pipeline

store, tenant, moving, accepted = fixtures.store, fixtures.tenant, fixtures.moving, fixtures.accepted


@pytest.mark.parametrize(
    "states",
    [
        ("pending", "pending", "pending"),
        ("fresh", "pending", "pending"),
        ("null", "pending", "pending"),
        ("expired", "pending", "pending"),
        ("succeeded", "fresh", "pending"),
        ("fresh", "fresh", "fresh"),
        ("failed", "succeeded", "obsolete"),
        ("expired", "null", "pending"),
    ],
)
async def test_peek_and_original_claim_same_real_rows_order_and_eligibility(moving, accepted, monkeypatch, states):
    built = await pipeline(moving, accepted, monkeypatch, count=3)
    async with built.sessions() as session, session.begin():
        await mark(session, built, await logical(session, built))
        rows = (
            (
                await session.execute(
                    sa.select(fixtures.ready.Item)
                    .where(fixtures.ready.Item.job_id == built.job_id)
                    .order_by(fixtures.ready.Item.file_id, fixtures.ready.Item.version_id)
                )
            )
            .scalars()
            .all()
        )
        for row, state in zip(rows, states, strict=True):
            row.state = state if state in ("pending", "failed", "succeeded", "obsolete") else "running"
            row.lease_until = (
                None if state == "null" else built.clock[0] + timedelta(seconds=50 if state == "fresh" else -1)
            )
    async with built.sessions() as session, session.begin():
        before = (
            (
                await session.execute(
                    sa.select(fixtures.ready.Item.__table__).where(fixtures.ready.Item.job_id == built.job_id)
                )
            )
            .mappings()
            .all()
        )
        peek = await built.execution.apeek_claimable_item(session, lease=built.lease, jobs=built.repo)
        after = (
            (
                await session.execute(
                    sa.select(fixtures.ready.Item.__table__).where(fixtures.ready.Item.job_id == built.job_id)
                )
            )
            .mappings()
            .all()
        )
        assert before == after
        claimed = await built.repo.aclaim_next_item(
            session,
            built.lease,
            configuration=CONFIG,
            _move=True,
            move_projection_evidence=await item_evidence(session, built),
        )
        assert (peek.item_id if peek else None) == (claimed.item.id if claimed else None)
        if peek:
            actual = await built.execution.aread_item(session, job_id=built.job_id, item_id=claimed.item.id)
            assert peek.leaf.projection_anchor == actual.leaf.projection_anchor


@pytest.mark.parametrize("bad", ["ready", "tenant", "bypass", "stale_lease"])
async def test_peek_requires_actual_ready_context_and_lease(moving, accepted, monkeypatch, bad):
    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        if bad != "ready":
            await mark(session, built, await logical(session, built))
        if bad == "stale_lease":
            from dataclasses import replace

            lease = replace(built.lease, lease_token="stale")
            assert await built.execution.apeek_claimable_item(session, lease=lease, jobs=built.repo) is None
        elif bad in ("tenant", "bypass"):
            with tenant_execution_scope(202) if bad == "tenant" else bypass_tenant_filter():
                with pytest.raises(KnowledgeOperationPlanConflictError):
                    await built.execution.apeek_claimable_item(session, lease=built.lease, jobs=built.repo)
        else:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await built.execution.apeek_claimable_item(session, lease=built.lease, jobs=built.repo)


async def test_peek_none_configuration_is_committed_as_obsolete(moving, accepted, monkeypatch):
    built = await pipeline(moving, accepted, monkeypatch)
    async with built.sessions() as session, session.begin():
        await mark(session, built, await logical(session, built))
        await session.execute(
            sa.update(fixtures.Knowledge.__table__).where(fixtures.Knowledge.id == 10).values(model_config_revision=5)
        )
    async with built.sessions() as session, session.begin():
        assert await built.execution.apeek_claimable_item(session, lease=built.lease, jobs=built.repo) is None
    async with built.sessions() as session:
        assert (await built.repo.aget_execution(session, built.job_id)).state == "obsolete"

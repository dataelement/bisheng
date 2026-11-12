"""Linear acceptance validation and constant single-item/parent execution reads."""

import math
from time import perf_counter

import pytest
import sqlalchemy as sa

from bisheng.knowledge.domain.repositories.move_job_repository import MoveJobRepository
from test.knowledge_unification import test_move_execution_kernel as kernel
from test.knowledge_unification import test_move_job_ready as ready

store, tenant, moving, accepted = kernel.store, kernel.tenant, kernel.moving, kernel.accepted


@pytest.mark.parametrize("count", [401, 10001])
async def test_full_acceptance_is_linear_then_projection_and_item_guards_are_constant(
    moving, accepted, monkeypatch, count, record_property
):
    built = await ready.pipeline(moving, accepted, monkeypatch, count=count)
    kernel.composed(built)
    original = MoveJobRepository._projection
    projections = []

    def project(plan, job_id):
        projections.append(len(plan.parameters["leaves"]))
        return original(plan, job_id)

    monkeypatch.setattr(MoveJobRepository, "_projection", staticmethod(project))
    statements, aggregates = [], []

    def before(c, u, sql, params, context, many):
        statements.append((sql, params))
        if "GROUP BY" in sql and ready.Item.__tablename__ in sql:
            context.move_aggregate_start = perf_counter()

    def after(c, u, sql, params, context, many):
        if hasattr(context, "move_aggregate_start"):
            aggregates.append(perf_counter() - context.move_aggregate_start)

    sa.event.listen(moving.engine.sync_engine, "before_cursor_execute", before)
    sa.event.listen(moving.engine.sync_engine, "after_cursor_execute", after)
    async with built.sessions() as session, session.begin():
        fact = await built.execution.avalidate_attempt(session, lease=built.lease, jobs=built.repo)
        assert fact.position == "before" and fact.scope.leaves
    full = [sql for sql, _ in statements if sql.lstrip().upper().startswith("SELECT")]
    assert projections == [count + 1]
    assert len(full) == 12 + 15 * math.ceil(count / 200)
    actual_item_pages = [sql for sql in full if "processing_snapshot" in sql.partition("FROM")[0]]
    assert len(actual_item_pages) == math.ceil(count / 200)
    async with built.sessions() as session, session.begin():
        await ready.mark(session, built, await ready.logical(session, built))
    statements.clear()
    async with built.sessions() as session, session.begin():
        evidence = await kernel.proof(session, built)
        claimed = await kernel.claim(session, built, evidence=evidence)
        statements.clear()
        assert (
            await built.execution.aguard_item(session, claimed.lease, jobs=built.repo, projection_evidence=evidence)
            is not None
        )
        guard = [sql for sql, _ in statements if sql.lstrip().upper().startswith("SELECT")]
        assert len(guard) == 24
        assert sum("processing_snapshot" in sql.partition("FROM")[0] for sql in guard) == 1
        assert all("scope_manifest" not in sql.partition("FROM")[0] for sql in guard)
        assert all("target_manifest" not in sql and "knowledge_operation_plan.parameters" not in sql for sql in guard)
        statements.clear()
        assert (
            await built.execution.aread_projection(
                session, lease=built.lease, resource_type="folder", resource_id=50, jobs=built.repo
            )
            is not None
        )
        projection = [sql for sql, _ in statements if sql.lstrip().upper().startswith("SELECT")]
        assert len(projection) == 6
        assert not any("processing_snapshot" in sql or "scope_manifest" in sql for sql in projection)
        await kernel.finish(session, built, claimed, evidence=evidence)
    assert projections == [count + 1, count + 1]  # Full logical ready remains its original single acceptance pass.
    record_property("native_item_count", count)
    record_property("native_full_acceptance_selects", len(full))
    record_property("native_single_item_guard_selects", len(guard))
    record_property("native_projection_selects", len(projection))
    print(
        {
            "items": count,
            "full": len(full),
            "guard": len(guard),
            "projection": len(projection),
            "original_count_aggregate_ms": [round(value * 1000, 3) for value in aggregates],
        }
    )

"""T979: one linear ready pass, then bounded individual execution reads."""

import math

import pytest
import sqlalchemy as sa

from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem as Item
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.move_job_repository import MoveJobRepository
from test.knowledge_unification.test_move_job_ready import CONFIG, logical, mark, pipeline
from test.knowledge_unification.test_move_job_ready import accepted as accepted
from test.knowledge_unification.test_move_job_ready import moving as moving
from test.knowledge_unification.test_move_job_ready import store as store
from test.knowledge_unification.test_move_job_ready import tenant as tenant


@pytest.mark.parametrize("count", [401, 10001])
async def test_native_ready_pages_and_later_claims_never_reload_full_scope(moving, accepted, monkeypatch, count):
    built = await pipeline(moving, accepted, monkeypatch, count=count)
    original, calls = MoveJobRepository._projection, []

    def project(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(MoveJobRepository, "_projection", staticmethod(project))
    position, positions = built.cutover._position, []

    async def read_position(*args, **kwargs):
        positions.append(True)
        return await position(*args, **kwargs)

    statements = []

    def record(_c, _cu, sql, params, _ctx, _many):
        statements.append((sql, params))

    sa.event.listen(moving.engine.sync_engine, "before_cursor_execute", record)
    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
        monkeypatch.setattr(built.cutover, "_position", read_position)
        statements.clear()
        await mark(session, built, receipt)
        assert calls == [True] and positions == [True]
    ready_selects = [(sql, params) for sql, params in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(ready_selects) <= 40 + 12 * math.ceil(count / 200)
    item_pages = [
        (sql, params)
        for sql, params in ready_selects
        if "processing_snapshot" in sql and "knowledge_processing_item" in sql
    ]
    assert len(item_pages) <= math.ceil(count / 200) + 1
    assert all("LIMIT" in sql and params[-2] <= 200 for sql, params in item_pages)
    statements.clear()
    async with built.sessions() as session, session.begin():
        for _ in range(3):
            value = await built.repo.aclaim_next_item(session, built.lease, configuration=CONFIG)
            assert value is not None
            assert await built.repo.acomplete_item(session, value.lease, configuration=CONFIG, succeeded=True)
        succeeded = (await session.execute(sa.select(Job.succeeded_count).where(Job.id == built.job_id))).scalar_one()
        assert succeeded == 3
    assert calls == [True] and positions == [True]
    selects = [sql for sql, _ in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 24
    assert all("scope_manifest" not in sql.partition("FROM")[0] for sql in selects)
    assert all("knowledge_operation_plan" not in sql for sql in selects)
    claims = [sql for sql in selects if "knowledge_processing_item.state IN" in sql]
    assert len(claims) == 3 and all("LIMIT" in sql for sql in claims)
    async with built.sessions() as session:
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(Item).where(Item.job_id == built.job_id))
        ).scalar_one() == count
    print(
        {
            "items": count,
            "ready_selects": len(ready_selects),
            "item_pages": len(item_pages),
            "three_claim_complete_selects": len(selects),
        }
    )

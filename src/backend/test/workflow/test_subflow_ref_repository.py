"""F086: SubflowRefRepositoryImpl against a real (SQLite) database."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.workflow.domain.models.subflow_ref import WorkflowSubflowRef
from bisheng.workflow.domain.repositories.implementations.subflow_ref_repository_impl import SubflowRefRepositoryImpl


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(WorkflowSubflowRef.__table__.create)
    async with AsyncSession(bind=engine, expire_on_commit=False) as one:
        with bypass_tenant_filter():
            yield one
    await engine.dispose()


async def _rows(session) -> list[tuple[str, str]]:
    result = await session.exec(select(WorkflowSubflowRef).order_by(WorkflowSubflowRef.id))
    return [(one.parent_flow_id, one.child_flow_id) for one in result.all()]


async def test_replace_keeps_unchanged_rows_and_swaps_the_rest(session):
    repo = SubflowRefRepositoryImpl(session)
    await repo.replace_for_parent("p1", ["a", "b", "a"])
    await repo.replace_for_parent("p2", ["a"])
    first_ids = {one.child_flow_id: one.id for one in (await session.exec(select(WorkflowSubflowRef))).all()}

    await repo.replace_for_parent("p1", ["b", "c"])

    assert sorted(await _rows(session)) == [("p1", "b"), ("p1", "c"), ("p2", "a")]
    kept = (await session.exec(select(WorkflowSubflowRef).where(WorkflowSubflowRef.child_flow_id == "b"))).one()
    assert kept.id == first_ids["b"]


async def test_delete_for_parent_only_touches_that_parent(session):
    repo = SubflowRefRepositoryImpl(session)
    await repo.replace_for_parent("p1", ["a"])
    await repo.replace_for_parent("p2", ["a"])
    await repo.delete_for_parent("p1")
    assert await _rows(session) == [("p2", "a")]


async def test_list_referrer_ids_in_reference_order(session):
    repo = SubflowRefRepositoryImpl(session)
    await repo.replace_for_parent("p2", ["a"])
    await repo.replace_for_parent("p1", ["a", "b"])
    assert await repo.list_referrer_ids("a") == ["p2", "p1"]
    assert await repo.list_referrer_ids("b") == ["p1"]
    assert await repo.list_referrer_ids("none") == []


async def test_replace_retries_when_another_save_wrote_the_same_row(session):
    repo = SubflowRefRepositoryImpl(session)
    await repo.replace_for_parent("p1", ["a"])
    real_rows = repo._rows_for_parent
    stale_reads = []

    async def stale_once(parent_flow_id):
        # The first read misses the row another save just committed.
        if not stale_reads:
            stale_reads.append(parent_flow_id)
            return []
        return await real_rows(parent_flow_id)

    repo._rows_for_parent = stale_once
    await repo.replace_for_parent("p1", ["a", "b"])

    assert stale_reads == ["p1"]
    assert sorted(await _rows(session)) == [("p1", "a"), ("p1", "b")]


async def test_replace_gives_up_after_repeated_conflicts(session):
    repo = SubflowRefRepositoryImpl(session)
    await repo.replace_for_parent("p1", ["a"])

    async def always_stale(parent_flow_id):
        return []

    repo._rows_for_parent = always_stale
    with pytest.raises(IntegrityError):
        await repo.replace_for_parent("p1", ["a"])
    repo._rows_for_parent = SubflowRefRepositoryImpl(session)._rows_for_parent
    assert await _rows(session) == [("p1", "a")]


async def test_list_child_ids(session):
    repo = SubflowRefRepositoryImpl(session)
    await repo.replace_for_parent("p1", ["a", "b"])
    assert sorted(await repo.list_child_ids("p1")) == ["a", "b"]
    assert await repo.list_child_ids("none") == []

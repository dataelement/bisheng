"""T725: native SQL anomaly filtering stays bounded and tenant-safe."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter, set_visible_tenant_ids
from bisheng.core.database import tenant_filter
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.knowledge_space_listing_repository import KnowledgeSpaceListingRepository
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceListItemResp


def space(ident, *, tenant=101, kind=3, name="matched"):
    return Knowledge(id=ident, tenant_id=tenant, user_id=99, name=name, type=kind, update_time=datetime(2026, 11, 6))


def file(ident, space_id, *, status=3, kind=1, tenant=101):
    return KnowledgeFile(
        id=ident, tenant_id=tenant, knowledge_id=space_id, file_name=f"file-{ident}", status=status, file_type=kind
    )


@pytest.fixture
def concrete_tenant(tenant_context):
    tenant_context(101)


@pytest.fixture
async def store(concrete_tenant, monkeypatch):
    register_tenant_filter_events()
    monkeypatch.setattr(
        tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {"knowledge", "knowledgefile"}
    )
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    metadata = sa.MetaData()
    Knowledge.__table__.to_metadata(metadata)
    KnowledgeFile.__table__.to_metadata(metadata)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    facts = SimpleNamespace(open_sessions=0, selects=[])

    @sa.event.listens_for(engine.sync_engine, "before_cursor_execute")
    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            facts.selects.append((statement, parameters, context.compiled.params))

    @asynccontextmanager
    async def sessions():
        facts.open_sessions += 1
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session
        finally:
            facts.open_sessions -= 1

    async def seed(*rows):
        async with sessions() as session:
            with bypass_tenant_filter():
                session.add_all(rows)
                await session.commit()
        facts.selects.clear()

    try:
        yield SimpleNamespace(
            engine=engine, facts=facts, seed=seed, repository=KnowledgeSpaceListingRepository(sessions)
        )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("status", [None, 1, 2, 3, 4, 5, 6, 7])
@pytest.mark.parametrize("kind", [0, 1])
async def test_only_abnormal_files_match_native_candidate_filter(store, status, kind):
    await store.seed(space(1), file(10, 1, status=status, kind=kind))
    rows = await store.repository.alist_candidates(has_abnormal=True)
    assert [row.id for row in rows] == ([1] if kind == 1 and status in {3, 6, 7} else [])
    assert len(store.facts.selects) == 1
    assert "exists" in store.facts.selects[0][0].lower()


@pytest.mark.parametrize("flag", [None, False, True])
async def test_filter_is_sql_before_seek_limit_and_admin_count(store, flag):
    await store.seed(
        *(space(ident) for ident in range(1, 9)),
        space(9, tenant=202),
        space(10, kind=1),
        space(11, name="other"),
        file(101, 2),
        file(102, 4, status=6),
        file(103, 6, status=7),
        file(104, 8, tenant=202),  # corrupt foreign FK cannot make own space abnormal
        file(105, 9, tenant=202),
        file(106, 10),
        file(107, 11),
    )
    expected = [6, 4, 2] if flag else list(range(8, 0, -1))
    visible = []
    after = None
    for _ in range(8):
        rows = await store.repository.alist_candidates(keyword="matched", after=after, limit=2, has_abnormal=flag)
        visible.extend(row.id for row in rows)
        if not rows:
            break
        after = (rows[-1].update_time, rows[-1].id)
    assert visible == expected
    rows, total = await store.repository.alist_admin(keyword="matched", page=2, page_size=2, has_abnormal=flag)
    assert total == len(expected) and [row.id for row in rows] == expected[2:4]


async def test_final_page_marker_one_exists_query_for_200_ids_and_large_success_population(store):
    await store.seed(
        *(space(ident) for ident in range(1, 201)),
        space(201, tenant=202),
        space(202, kind=1),
        *(file(ident + 1000, 1, status=2) for ident in range(10001)),
        file(20001, 2, status=3),
        file(20002, 3, status=6),
        file(20003, 4, status=7),
        file(20004, 5, kind=0),
        file(20005, 6, tenant=202),
        file(20006, 201, tenant=202),
        file(20007, 202),
    )
    # Native fixture statistics keep SQLite's cost estimate independent of
    # Python's unordered index-creation order; production uses its own planner.
    async with store.engine.begin() as connection:
        await connection.exec_driver_sql("ANALYZE")
    token = set_visible_tenant_ids(frozenset({101, 202}))
    try:
        found = await store.repository.aexists_abnormal_files(space_ids=list(range(1, 201)))
    finally:
        from bisheng.core.context import tenant

        tenant.visible_tenant_ids.reset(token)
    assert found == {2, 3, 4}
    assert len(store.facts.selects) == 1 and store.facts.open_sessions == 0
    statement, parameters, _ = store.facts.selects[0]
    sql = statement.lower()
    assert "exists" in sql and "join" not in sql and "count(" not in sql
    assert "knowledgefile.tenant_id = knowledge.tenant_id" in sql
    async with store.engine.connect() as connection:
        plan = (await connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters)).all()
    assert any("ix_knowledgefile_kb_status_type" in str(row) for row in plan), plan


async def test_empty_marker_does_not_open_connection(store):
    assert await store.repository.aexists_abnormal_files(space_ids=[]) == set()
    assert store.facts.selects == [] and store.facts.open_sessions == 0


@pytest.mark.parametrize("ids", [[True], [0], [-1], ["1"], list(range(1, 202))])
async def test_marker_rejects_non_page_inputs_before_sql(store, ids):
    with pytest.raises(ValueError):
        await store.repository.aexists_abnormal_files(space_ids=ids)
    assert store.facts.selects == []


def test_light_list_dto_has_actual_boolean_default_without_detail_counters():
    item = KnowledgeSpaceListItemResp.model_validate(space(1))
    assert item.has_abnormal_files is False
    assert "file_num" not in item.model_dump()

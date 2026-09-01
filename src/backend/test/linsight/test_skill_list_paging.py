"""F035 management-list regression tests: paging determinism, ordering of
freshly created / legacy rows, and keyword coverage.

Field symptom (114, 2026-08-24): a skill imported minutes ago could not be found
in the management list. Three defects compounded:

1. ``DAO.create`` never wrote ``update_time``; the list sorts on it and MySQL
   orders NULL last under DESC, so a just-imported skill landed on the LAST page
   while the API still reported ``update_time`` (serialized as ``update_time or
   create_time``) as "just now".
2. ``ORDER BY update_time DESC`` had no tiebreaker. Skills seeded in one batch
   share an update_time to the second, so OFFSET paging cut the tie group at an
   arbitrary point: the same row surfaced on two pages while another was never
   listed at all (31 rows total, 29 reachable by paging through every page).
3. ``keyword`` matched ``display_name``/``description`` only, while the
   duplicate check rejects on ``name`` + ``display_name`` — so an import could
   be refused as "already exists" for a name the list could not search for.
"""

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import col, update

import bisheng.linsight.domain.models.linsight_skill as model_module
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao

ROOT = 1
# The whole seeded batch shares this timestamp — that is what makes the tie
# group large enough for the paging defect to bite.
BATCH_TIME = datetime(2026, 8, 14, 19, 18, 24)
BATCH_SIZE = 12
PAGE_SIZE = 5


def _skill(
    name: str,
    *,
    display_name: str | None = None,
    description: str = "seeded skill",
    create_time: datetime = BATCH_TIME,
    update_time: datetime | None = BATCH_TIME,
) -> LinsightSkill:
    skill = LinsightSkill(
        tenant_id=ROOT,
        name=name,
        display_name=display_name or name,
        description=description,
        enabled=True,
        source="manual",
        object_path=f"data/skills/{ROOT}/{name}",
        size=10,
        created_by=7,
        create_time=create_time,
    )
    skill.update_time = update_time
    return skill


@contextmanager
def _as_request():
    t1 = set_current_tenant_id(ROOT)
    t2 = set_visible_tenant_ids(frozenset({ROOT}))
    try:
        yield
    finally:
        current_tenant_id.reset(t1)
        visible_tenant_ids.reset(t2)


async def _insert_raw(skill: LinsightSkill) -> LinsightSkill:
    """Insert bypassing ``DAO.create``, so the row keeps exactly what it was given."""
    with bypass_tenant_filter():
        async with model_module.get_async_db_session() as session:
            session.add(skill)
            await session.commit()
            await session.refresh(skill)
            return skill


async def _insert_created(dao, name: str, create_time: datetime) -> LinsightSkill:
    """Create through the DAO, the way an import does (no update_time given)."""
    with bypass_tenant_filter():
        return await dao.create(_skill(name, create_time=create_time, update_time=None))


async def _null_out_update_time(skill_id: int) -> None:
    """Reproduce a row written before this fix. The shipped DDL is ``update_time
    datetime DEFAULT NULL`` (the alembic table carries no server default), so
    such rows hold a real NULL — which is what sank them to the last page."""
    with bypass_tenant_filter():
        async with model_module.get_async_db_session() as session:
            await session.exec(update(LinsightSkill).where(col(LinsightSkill.id) == skill_id).values(update_time=None))
            await session.commit()


@pytest.fixture
async def dao(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(LinsightSkill.__table__.create)

    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(model_module, "get_async_db_session", _session)

    for i in range(BATCH_SIZE):
        await _insert_raw(_skill(f"batch-{i:02d}"))

    yield LinsightSkillDao
    await engine.dispose()


async def _walk_pages(dao, page_size: int = PAGE_SIZE) -> tuple[list[int], int]:
    """Page through the whole list the way the UI does; return ids in order."""
    with _as_request():
        _, total = await dao.get_page(page=1, page_size=page_size)
        ids: list[int] = []
        for page in range(1, (total + page_size - 1) // page_size + 1):
            rows, _ = await dao.get_page(page=page, page_size=page_size)
            ids += [r.id for r in rows]
    return ids, total


class TestPagingDeterminism:
    async def test_every_row_is_listed_exactly_once(self, dao):
        """Rows sharing an update_time must not repeat on one page and vanish
        from another — paging has to reach all of them."""
        ids, total = await _walk_pages(dao)
        assert total == BATCH_SIZE
        assert len(ids) == BATCH_SIZE
        assert len(set(ids)) == BATCH_SIZE, "a row repeated across pages, so another was never listed"

    async def test_order_is_a_total_order(self, dao):
        """Ties must be broken by id. Without a deterministic tiebreaker the
        database may cut a tie group anywhere it likes, and that is exactly what
        let one row repeat across two pages while another was never listed."""
        ids, _ = await _walk_pages(dao)
        with _as_request():
            rows, _ = await dao.get_page(page=1, page_size=BATCH_SIZE * 2)
        expected = [r.id for r in sorted(rows, key=lambda r: (r.update_time or r.create_time, r.id), reverse=True)]
        assert ids == expected

    async def test_page_order_is_stable_across_calls(self, dao):
        first, _ = await _walk_pages(dao)
        second, _ = await _walk_pages(dao)
        assert first == second


class TestOrdering:
    async def test_new_skill_leads_the_list(self, dao):
        """A just-imported skill goes through DAO.create, which must stamp
        update_time — otherwise it sinks below the whole seeded batch."""
        created = await _insert_created(dao, "freshly-imported", BATCH_TIME + timedelta(days=2))
        assert created.update_time == created.create_time

        with _as_request():
            rows, total = await dao.get_page(page=1, page_size=PAGE_SIZE)
        assert total == BATCH_SIZE + 1
        assert rows[0].name == "freshly-imported"

    async def test_legacy_null_update_time_falls_back_to_create_time(self, dao):
        """Rows written before the fix keep a NULL update_time; COALESCE must
        rank them by creation time instead of sinking them to the last page."""
        legacy = await _insert_raw(_skill("legacy-import", create_time=BATCH_TIME + timedelta(days=1)))
        await _null_out_update_time(legacy.id)

        with _as_request():
            rows, _ = await dao.get_page(page=1, page_size=PAGE_SIZE)
        assert rows[0].name == "legacy-import"
        assert rows[0].update_time is None, "the fixture must reproduce a real NULL, not a fallback value"


class TestKeyword:
    async def test_keyword_matches_skill_id(self, dao):
        """A Chinese display name must not make the ASCII skill id unsearchable
        — the duplicate check rejects on that id."""
        await _insert_raw(_skill("zhi-neng-chu-ti-ce-shi", display_name="智能出题测试", description="根据材料出题"))

        with _as_request():
            rows, total = await dao.get_page(keyword="zhi-neng")
        assert total == 1
        assert rows[0].name == "zhi-neng-chu-ti-ce-shi"

    async def test_keyword_still_matches_display_name_and_description(self, dao):
        await _insert_raw(_skill("zhi-neng-chu-ti-ce-shi", display_name="智能出题测试", description="根据材料出题"))

        with _as_request():
            by_display, _ = await dao.get_page(keyword="出题测试")
            by_description, _ = await dao.get_page(keyword="根据材料")
        assert [r.name for r in by_display] == ["zhi-neng-chu-ti-ce-shi"]
        assert [r.name for r in by_description] == ["zhi-neng-chu-ti-ce-shi"]

    async def test_keyword_that_matches_nothing_returns_empty(self, dao):
        with _as_request():
            rows, total = await dao.get_page(keyword="intelligent")
        assert (rows, total) == ([], 0)

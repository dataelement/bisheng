"""F078 T05: skill lookup by name for agent nodes and assistants.

The lookup must return disabled rows too (so the caller can tell "disabled"
from "deleted"), and must stay scoped to the current tenant: a child tenant
must not see a same-named Root skill.
"""

from contextlib import asynccontextmanager, contextmanager

import pytest
from sqlalchemy.pool import StaticPool

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.repositories.implementations.skill_repository_impl import SkillRepositoryImpl

ROOT = 1
LEAF = 2


def _skill(name: str, tenant_id: int, enabled: bool = True) -> LinsightSkill:
    return LinsightSkill(
        tenant_id=tenant_id,
        name=name,
        display_name=f"{name}-{tenant_id}",
        description=f"desc of {name}",
        enabled=enabled,
        source="manual",
        object_path=f"data/skills/{tenant_id}/{name}",
        size=10,
        created_by=7,
    )


@contextmanager
def _as_child_request():
    t1 = set_current_tenant_id(LEAF)
    t2 = set_visible_tenant_ids(frozenset({LEAF, ROOT}))
    try:
        yield
    finally:
        current_tenant_id.reset(t1)
        visible_tenant_ids.reset(t2)


@pytest.fixture
async def repo():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.database import tenant_filter

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

    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    tenant_filter.register_tenant_filter_events()

    with bypass_tenant_filter():
        async with _session() as session:
            session.add_all(
                [
                    _skill("pdf", ROOT),
                    _skill("root-only", ROOT),
                    _skill("pdf", LEAF),
                    _skill("docx", LEAF, enabled=False),
                ]
            )
            await session.commit()

    yield SkillRepositoryImpl(session_factory=_session)

    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    await engine.dispose()


class TestSkillRepository:
    async def test_returns_enabled_and_disabled_rows(self, repo):
        with _as_child_request():
            rows = await repo.list_by_names(["pdf", "docx"])
        by_name = {row.name: row for row in rows}
        assert set(by_name) == {"pdf", "docx"}
        # The column is an Integer flag (1/0), so compare by truthiness.
        assert bool(by_name["pdf"].enabled) is True
        assert bool(by_name["docx"].enabled) is False

    async def test_missing_names_are_absent(self, repo):
        with _as_child_request():
            rows = await repo.list_by_names(["pdf", "gone"])
        assert [row.name for row in rows] == ["pdf"]

    async def test_other_tenant_skill_not_visible(self, repo):
        with _as_child_request():
            rows = await repo.list_by_names(["root-only", "pdf"])
        assert [(row.name, row.tenant_id) for row in rows] == [("pdf", LEAF)]

    async def test_empty_names_skip_the_query(self, repo):
        with _as_child_request():
            assert await repo.list_by_names([]) == []

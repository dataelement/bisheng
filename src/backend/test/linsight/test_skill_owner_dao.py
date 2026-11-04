"""Personal skills share a name with tenant skills and with each other.

Queries and bulk updates must name both the tenant and the owner. The default
owner is 0, which is what the management pages still ask for.
"""

from contextlib import asynccontextmanager, contextmanager

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import select

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
TENANT = 5
LEAF = 6
USER_A = 11
USER_B = 22


def _skill(name: str, tenant_id: int, owner_user_id: int, enabled: bool = True) -> LinsightSkill:
    return LinsightSkill(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        name=name,
        display_name=f"{name}-{owner_user_id}",
        description=f"desc of {name}",
        enabled=enabled,
        source="manual",
        object_path=f"linsight/skills/{tenant_id}/{name}/hash.zip",
        size=10,
        created_by=7,
    )


@contextmanager
def _as_child_request():
    token_tenant = set_current_tenant_id(LEAF)
    token_visible = set_visible_tenant_ids(frozenset({LEAF, ROOT}))
    try:
        yield
    finally:
        current_tenant_id.reset(token_tenant)
        visible_tenant_ids.reset(token_visible)


async def _all(name: str) -> list[LinsightSkill]:
    with bypass_tenant_filter():
        async with model_module.get_async_db_session() as session:
            statement = select(LinsightSkill).where(LinsightSkill.name == name)
            return list((await session.exec(statement)).all())


@pytest.fixture
async def dao(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.database import tenant_filter

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    tenant_filter.register_tenant_filter_events()

    with bypass_tenant_filter():
        await LinsightSkillDao.create(_skill("pdf", TENANT, 0))
        await LinsightSkillDao.create(_skill("pdf", TENANT, USER_A))
        await LinsightSkillDao.create(_skill("pdf", TENANT, USER_B, enabled=False))
        await LinsightSkillDao.create(_skill("pdf", ROOT, 0))
        await LinsightSkillDao.create(_skill("pdf", ROOT, USER_A))
        await LinsightSkillDao.create(_skill("pdf", LEAF, 0))
        await LinsightSkillDao.create(_skill("mine", LEAF, USER_A))

    set_current_tenant_id(TENANT)
    yield LinsightSkillDao

    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    await engine.dispose()


class TestSkillOwnerDao:
    async def test_get_by_name_hits_only_the_given_owner(self, dao):
        enterprise = await dao.get_by_name("pdf")
        assert enterprise is not None
        assert enterprise.owner_user_id == 0
        assert enterprise.tenant_id == TENANT

        owned = await dao.get_by_name("pdf", owner_user_id=USER_A)
        assert owned is not None and owned.owner_user_id == USER_A and owned.tenant_id == TENANT

        other = await dao.get_by_name("pdf", owner_user_id=USER_B)
        assert other is not None and other.owner_user_id == USER_B
        assert await dao.get_by_name("pdf", owner_user_id=99) is None

    async def test_default_admin_queries_see_only_tenant_skills(self, dao):
        rows, total = await dao.get_page()
        assert total == 1
        assert rows[0].owner_user_id == 0 and rows[0].tenant_id == TENANT

        enabled = await dao.list_enabled()
        assert [row.owner_user_id for row in enabled] == [0]
        assert all(row.tenant_id == TENANT for row in enabled)

        personal, personal_total = await dao.get_page(owner_user_id=USER_A)
        assert personal_total == 1 and personal[0].owner_user_id == USER_A
        assert await dao.list_enabled(owner_user_id=USER_B) == []

    async def test_mutations_do_not_touch_other_owners(self, dao):
        assert await dao.set_enabled("pdf", False, owner_user_id=USER_A) is True
        assert await dao.set_default_checked("pdf", True, owner_user_id=USER_A) is True

        rows = {row.owner_user_id: row for row in await _all("pdf") if row.tenant_id == TENANT}
        assert bool(rows[0].enabled) is True
        assert bool(rows[0].default_checked) is False
        assert bool(rows[USER_A].enabled) is False
        assert bool(rows[USER_A].default_checked) is True
        assert bool(rows[USER_B].enabled) is False
        assert bool(rows[USER_B].default_checked) is False

        assert await dao.delete_by_name("pdf", owner_user_id=USER_B) is True
        remaining = {row.owner_user_id for row in await _all("pdf") if row.tenant_id == TENANT}
        assert remaining == {0, USER_A}
        assert await dao.delete_by_name("pdf") is True
        remaining = {row.owner_user_id for row in await _all("pdf") if row.tenant_id == TENANT}
        assert remaining == {USER_A}

    async def test_child_tenant_does_not_see_root_rows(self, dao):
        with _as_child_request():
            assert (await dao.get_by_name("pdf")).tenant_id == LEAF
            assert await dao.get_by_name("pdf", owner_user_id=USER_A) is None
            owned = await dao.get_by_name("mine", owner_user_id=USER_A)
            assert owned is not None and owned.tenant_id == LEAF

            rows, total = await dao.get_page()
            assert total == 1 and rows[0].name == "pdf" and rows[0].tenant_id == LEAF
            assert [row.name for row in await dao.list_enabled()] == ["pdf"]

            assert await dao.set_enabled("pdf", False) is True

        root_enterprise = [row for row in await _all("pdf") if row.tenant_id == ROOT and row.owner_user_id == 0]
        assert len(root_enterprise) == 1 and bool(root_enterprise[0].enabled) is True

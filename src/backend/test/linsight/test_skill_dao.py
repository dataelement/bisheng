"""F035 Track D — LinsightSkillDao tests against a real (sqlite) session.

The service/API tests replace the DAO with an in-memory fake; this file
exercises the real SQL paths (create/update/page/list/set_enabled/delete)
plus the automatic tenant filter."""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.pool import StaticPool

import bisheng.linsight.domain.models.linsight_skill as model_module
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao

TENANT = 1


def _skill(name: str, display_name: str, enabled: bool = True, tenant_id: int = TENANT) -> LinsightSkill:
    return LinsightSkill(
        tenant_id=tenant_id,
        name=name,
        display_name=display_name,
        description=f"desc of {display_name}",
        enabled=enabled,
        source="manual",
        object_path=f"data/skills/{tenant_id}/{name}",
        size=10,
        created_by=7,
    )


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
    set_current_tenant_id(TENANT)
    yield LinsightSkillDao
    await engine.dispose()


class TestSkillDao:
    async def test_create_and_lookups(self, dao):
        await dao.create(_skill("biao-shu", "标书撰写"))
        row = await dao.get_by_name("biao-shu")
        assert row is not None and row.display_name == "标书撰写"
        assert (await dao.get_by_display_name("标书撰写")).name == "biao-shu"
        assert await dao.get_by_name("nope") is None

    async def test_page_filters(self, dao):
        await dao.create(_skill("biao-shu", "标书撰写"))
        await dao.create(_skill("he-tong", "合同审阅", enabled=False))

        rows, total = await dao.get_page()
        assert total == 2
        rows, total = await dao.get_page(keyword="合同")
        assert total == 1 and rows[0].name == "he-tong"
        rows, total = await dao.get_page(enabled=True)
        assert total == 1 and rows[0].name == "biao-shu"
        rows, total = await dao.get_page(page=2, page_size=1)
        assert total == 2 and len(rows) == 1

    async def test_list_enabled_and_toggle(self, dao):
        await dao.create(_skill("biao-shu", "标书撰写"))
        assert [s.name for s in await dao.list_enabled()] == ["biao-shu"]
        assert await dao.set_enabled("biao-shu", False) is True
        assert await dao.list_enabled() == []
        assert await dao.set_enabled("nope", True) is False

    async def test_update_and_delete(self, dao):
        row = await dao.create(_skill("biao-shu", "标书撰写"))
        row.description = "new desc"
        await dao.update(row)
        assert (await dao.get_by_name("biao-shu")).description == "new desc"
        assert await dao.delete_by_name("biao-shu") is True
        assert await dao.delete_by_name("biao-shu") is False

    def test_model_registered_for_tenant_filter(self):
        # Cross-tenant isolation is enforced by the do_orm_execute listener
        # registered at app init (tenant_filter.py); the unit-level guarantee
        # is that linsight_skill is in the instrumented-model registry.
        from bisheng.core.database import tenant_filter

        registries = [
            value
            for name, value in vars(tenant_filter).items()
            if isinstance(value, (tuple, list, set, frozenset))
            and "bisheng.linsight.domain.models.linsight_skill" in value
        ]
        assert registries, "linsight_skill must be registered in the tenant filter model registry"

"""F035 multi-tenant isolation regression tests for tenant custom skills.

Skills are tenant-private: the F012 IN-list (``visible_tenant_ids = {leaf,
ROOT}``) must NOT leak Root skills into a child tenant's management list /
end-user picker, and a child admin must not be able to toggle, see, or delete
another tenant's skill. These tests exercise the *real* ``do_orm_execute``
tenant-filter listener against an async SQLite session, simulating a child
tenant request exactly as ``CustomMiddleware`` sets it up.

Bug context: ``LinsightSkillDao`` relied on "the automatic tenant filter" but
that filter injects ``WHERE tenant_id IN (leaf, ROOT)`` for child tenants, so
Root skills (created by the system admin) surfaced in tenant 00002's list. The
fix wraps every SELECT in ``strict_tenant_filter()`` and scopes the
``set_enabled`` bulk UPDATE explicitly.
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
    """Simulate a child-tenant request: current=LEAF, visible IN-list={LEAF, ROOT}."""
    t1 = set_current_tenant_id(LEAF)
    t2 = set_visible_tenant_ids(frozenset({LEAF, ROOT}))
    try:
        yield
    finally:
        current_tenant_id.reset(t1)
        visible_tenant_ids.reset(t2)


async def _all(name: str | None = None) -> list[LinsightSkill]:
    """Read rows across all tenants (bypass the filter) for assertions."""
    with bypass_tenant_filter():
        async with model_module.get_async_db_session() as session:
            stmt = select(LinsightSkill)
            if name is not None:
                stmt = stmt.where(LinsightSkill.name == name)
            return list((await session.exec(stmt)).all())


@pytest.fixture
async def dao(monkeypatch):
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

    monkeypatch.setattr(model_module, "get_async_db_session", _session)

    # Register the real tenant-filter listener so IN-list / strict semantics
    # actually apply to our async session.
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    tenant_filter.register_tenant_filter_events()
    assert "linsight_skill" in tenant_filter._tenant_aware_tables

    # Seed cross-tenant rows under bypass: Root (system-admin) skills + a child's
    # own skills, including a name ("pdf") that collides across tenants.
    with bypass_tenant_filter():
        await LinsightSkillDao.create(_skill("root-skill", ROOT))
        await LinsightSkillDao.create(_skill("pdf", ROOT))
        await LinsightSkillDao.create(_skill("leaf-skill", LEAF))
        await LinsightSkillDao.create(_skill("pdf", LEAF))

    yield LinsightSkillDao

    # Neutralize the listener for subsequent tests (empty table set ⇒ no filter).
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    await engine.dispose()


class TestSkillTenantIsolation:
    async def test_in_list_leak_is_real_without_strict(self, dao):
        """Control: a plain SELECT under the child request DOES surface Root rows
        via ``visible_tenant_ids`` — this is the leak the DAO must prevent."""
        with _as_child_request():
            async with model_module.get_async_db_session() as session:
                rows = (await session.exec(select(LinsightSkill))).all()
        assert {r.tenant_id for r in rows} == {ROOT, LEAF}

    async def test_get_page_excludes_root_skills(self, dao):
        """The management list (screenshot symptom) must show only the child's own skills."""
        with _as_child_request():
            rows, total = await dao.get_page()
        assert sorted(r.name for r in rows) == ["leaf-skill", "pdf"]
        assert total == 2
        assert all(r.tenant_id == LEAF for r in rows)

    async def test_list_enabled_excludes_root_skills(self, dao):
        """The end-user picker (/skill/selectable) must not offer Root skills."""
        with _as_child_request():
            rows = await dao.list_enabled()
        assert sorted(r.name for r in rows) == ["leaf-skill", "pdf"]
        assert all(r.tenant_id == LEAF for r in rows)

    async def test_get_by_name_cannot_reach_root_skill(self, dao):
        with _as_child_request():
            assert await dao.get_by_name("root-skill") is None
            assert (await dao.get_by_name("leaf-skill")).tenant_id == LEAF
            # A colliding name resolves to the child's own row, never Root's.
            assert (await dao.get_by_name("pdf")).tenant_id == LEAF

    async def test_get_by_display_name_scoped_to_child(self, dao):
        with _as_child_request():
            assert await dao.get_by_display_name("root-skill-1") is None
            assert (await dao.get_by_display_name("leaf-skill-2")).tenant_id == LEAF

    async def test_set_enabled_does_not_flip_other_tenants(self, dao):
        """The cross-tenant write hole: set_enabled is a bulk UPDATE keyed on
        name only. Toggling the child's 'pdf' must not touch Root's 'pdf'."""
        with _as_child_request():
            assert await dao.set_enabled("pdf", False) is True
        enabled_by_tenant = {r.tenant_id: bool(r.enabled) for r in await _all("pdf")}
        assert enabled_by_tenant == {ROOT: True, LEAF: False}

    async def test_set_enabled_on_root_only_name_is_noop_for_child(self, dao):
        with _as_child_request():
            assert await dao.set_enabled("root-skill", False) is False
        rows = await _all("root-skill")
        assert len(rows) == 1 and bool(rows[0].enabled) is True

    async def test_delete_cannot_remove_root_skill(self, dao):
        with _as_child_request():
            assert await dao.delete_by_name("root-skill") is False
        assert len(await _all("root-skill")) == 1  # untouched

    async def test_delete_own_skill_leaves_root_collision_intact(self, dao):
        with _as_child_request():
            assert await dao.delete_by_name("pdf") is True
        remaining = {r.tenant_id for r in await _all("pdf")}
        assert remaining == {ROOT}  # only the child's 'pdf' was deleted

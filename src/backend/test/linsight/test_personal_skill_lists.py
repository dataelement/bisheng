"""Skill center lists every owned skill. Task candidates stay enabled-only."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import bisheng.linsight.domain.models.linsight_skill as model_module
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao
from bisheng.linsight.domain.services.personal_skill_service import PersonalSkillService
from bisheng.linsight.domain.services.skill_store import SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 5
OTHER_TENANT = 9
USER = 11
OTHER = 22


def _row(
    name: str,
    owner: int,
    display: str,
    description: str,
    *,
    enabled: bool = True,
    tenant_id: int = TENANT,
) -> LinsightSkill:
    return LinsightSkill(
        tenant_id=tenant_id,
        owner_user_id=owner,
        name=name,
        display_name=display,
        description=description,
        enabled=enabled,
        source="manual",
        object_path=f"linsight/skills/{tenant_id}/{name}/hash.zip",
        content_hash="a" * 64,
        size=10,
        created_by=owner or 1,
    )


@pytest.fixture
async def env(monkeypatch, tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
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
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    monkeypatch.setattr(model_module, "get_async_db_session", _session)
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    tenant_filter.register_tenant_filter_events()
    set_current_tenant_id(TENANT)

    with bypass_tenant_filter():
        await LinsightSkillDao.create(_row("he-tong", 0, "合同审阅", "审阅合同"))
        await LinsightSkillDao.create(_row("old-ent", 0, "旧企业", "已停用的企业技能", enabled=False))
        await LinsightSkillDao.create(_row("pdf", 0, "企业报告", "企业版"))
        await LinsightSkillDao.create(_row("ji-du", USER, "季度报告", "生成报告"))
        await LinsightSkillDao.create(_row("ting", USER, "停用技能", "暂时不用", enabled=False))
        await LinsightSkillDao.create(_row("pdf", USER, "个人报告", "个人版"))
        await LinsightSkillDao.create(_row("other-skill", OTHER, "别人的", "不属于我"))
        await LinsightSkillDao.create(_row("foreign", 0, "外租户", "别的租户", tenant_id=OTHER_TENANT))

    monkeypatch.setattr(PersonalSkillService, "_audit", AsyncMock())
    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.require_business_action",
        AsyncMock(),
    )
    store = SkillStore(root=tmp_path, minio=FakeMinioStorage())
    service = PersonalSkillService(
        store=store,
        owner_projection=SimpleNamespace(authorize_created=AsyncMock()),
        unpack_root=tmp_path / "unpack",
    )
    yield SimpleNamespace(dao=LinsightSkillDao, service=service, store=store)

    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    await engine.dispose()


def _names(rows) -> set[str]:
    return {row.name for row in rows}


class TestPersonalSkillLists:
    async def test_center_keeps_disabled_personal_skills_and_enabled_tenant_skills(self, env):
        with patch("bisheng.permission.application.business_authorization.require_business_action") as gate:
            center = await env.service.list_center(USER)
            candidates = await env.service.list_candidates(USER)
            gate.assert_not_called()

        assert _names(center.personal) == {"ji-du", "ting", "pdf"}
        assert _names(center.enterprise) == {"he-tong", "pdf"}
        assert "foreign" not in _names(center.personal) | _names(center.enterprise)
        assert "other-skill" not in _names(center.personal)
        disabled = next(row for row in center.personal if row.name == "ting")
        assert bool(disabled.enabled) is False
        assert center.personal_count == 3
        assert center.enterprise_count == 2
        assert _names(candidates) == {"ji-du", "pdf", "he-tong"}
        personal_pdf = next(row for row in candidates if row.name == "pdf")
        assert personal_pdf.owner_user_id == USER

    async def test_disabling_or_deleting_the_personal_copy_restores_the_tenant_skill(self, env):
        personal = await env.dao.get_by_name("pdf", owner_user_id=USER)
        await env.service.set_enabled(user_id=USER, skill_id=personal.id, enabled=False)
        covered = {row.owner_user_id for row in await env.service.list_candidates(USER) if row.name == "pdf"}
        assert covered == {0}

        await env.service.delete(user_id=USER, skill_id=personal.id)
        covered = {row.owner_user_id for row in await env.service.list_candidates(USER) if row.name == "pdf"}
        assert covered == {0}
        center = await env.service.list_center(USER)
        assert "pdf" not in _names(center.personal)
        assert "pdf" in _names(center.enterprise)

    async def test_search_filters_only_the_current_tab(self, env):
        by_id = await env.service.list_center(USER, tab="personal", keyword="ji-du")
        assert _names(by_id.personal) == {"ji-du"}
        assert _names(by_id.enterprise) == {"he-tong", "pdf"}
        assert by_id.personal_count == 3 and by_id.enterprise_count == 2

        by_description = await env.service.list_center(USER, tab="enterprise", keyword="审阅")
        assert _names(by_description.enterprise) == {"he-tong"}
        assert _names(by_description.personal) == {"ji-du", "ting", "pdf"}

        by_title = await env.service.list_center(USER, tab="personal", keyword="合同")
        assert by_title.personal == []
        assert "he-tong" in _names(by_title.enterprise)

    async def test_disabling_a_tenant_skill_removes_it_from_every_candidate(self, env):
        assert await env.dao.set_enabled("he-tong", False) is True
        user_names = _names(await env.service.list_candidates(USER))
        other_names = _names(await env.service.list_candidates(OTHER))
        assert "he-tong" not in user_names and "he-tong" not in other_names
        assert "ji-du" in user_names
        assert "other-skill" in other_names and "other-skill" not in user_names
        mine = await env.service.list_center(USER)
        assert "he-tong" not in _names(mine.enterprise)
        assert "ji-du" in _names(mine.personal)

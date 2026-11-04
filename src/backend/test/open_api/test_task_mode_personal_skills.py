"""Task mode offers the caller's candidates. Daily chat is unchanged."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from contextlib import asynccontextmanager

import pytest

import bisheng.linsight.domain.models.linsight_skill as model_module
from bisheng.common.errcode.open_api import OpenApiTaskSkillUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao
from bisheng.open_api.domain.schemas.task_mode import OpenTaskSubmitReq
from bisheng.open_api.domain.schemas.workstation import OpenDailyChatCompletionReq
from bisheng.open_api.domain.services.task_mode_service import OpenTaskModeService

TENANT = 5
USER = 11
OTHER = 22


def _row(name: str, owner: int, *, enabled: bool = True, display: str = "") -> LinsightSkill:
    return LinsightSkill(
        tenant_id=TENANT,
        owner_user_id=owner,
        name=name,
        display_name=display or name,
        description="用途",
        enabled=enabled,
        source="manual",
        object_path=f"linsight/skills/{TENANT}/{owner}/{name}/hash.zip",
        content_hash="a" * 64,
        size=10,
        created_by=owner or 1,
    )


@pytest.fixture
async def skills(monkeypatch):
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
    monkeypatch.setattr(
        "bisheng.linsight.domain.services.user_skills.SkillAvailabilityRepository.disabled_ids",
        AsyncMock(return_value=set()),
    )

    async def permitted(_user, *, resource_ids, **kwargs):
        return {str(skill_id): {"use"} for skill_id in resource_ids}

    monkeypatch.setattr("bisheng.permission.application.business_authorization.batch_check_business_actions", permitted)
    with bypass_tenant_filter():
        await LinsightSkillDao.create(_row("pdf", 0, display="企业报告"))
        await LinsightSkillDao.create(_row("he-tong", 0, display="合同审阅"))
        await LinsightSkillDao.create(_row("pdf", USER, display="个人报告"))
        await LinsightSkillDao.create(_row("ting", USER, enabled=False, display="停用技能"))
        await LinsightSkillDao.create(_row("secret", OTHER, display="别人的技能"))
    yield
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    await engine.dispose()


class TestTaskModePersonalSkills:
    async def test_the_caller_sees_only_their_enabled_candidates(self, skills):
        rows = await OpenTaskModeService.enabled_skill_rows(SimpleNamespace(user_id=USER))
        by_name = {row.name: row for row in rows}
        assert set(by_name) == {"pdf", "he-tong"}
        assert by_name["pdf"].owner_user_id == USER
        assert by_name["pdf"].display_name == "个人报告"

        await OpenTaskModeService.check_skills(["pdf", "he-tong"], SimpleNamespace(user_id=USER))
        with pytest.raises(OpenApiTaskSkillUnavailableError) as caught:
            await OpenTaskModeService.check_skills(["secret", "ting"], SimpleNamespace(user_id=USER))
        assert caught.value.kwargs["unavailable"] == ["secret", "ting"]
        text = str(caught.value.to_dict())
        assert "别人的技能" not in text
        assert "停用技能" not in text

    async def test_disabling_the_personal_copy_restores_the_tenant_skill(self, skills):
        personal = await LinsightSkillDao.get_by_name("pdf", owner_user_id=USER)
        await LinsightSkillDao.set_owner_enabled(personal.id, owner_user_id=USER, enabled=False)
        rows = await OpenTaskModeService.enabled_skill_rows(SimpleNamespace(user_id=USER))
        pdf = next(row for row in rows if row.name == "pdf")
        assert pdf.owner_user_id == 0
        await OpenTaskModeService.check_skills(["pdf"], SimpleNamespace(user_id=USER))

    async def test_request_fields_stay_skill_names_and_daily_mode_is_unchanged(self):
        assert "skill_ids" not in OpenTaskSubmitReq.model_fields
        body = OpenTaskSubmitReq.model_validate(
            {
                "run_mode": "task",
                "execution": "async",
                "clientTimestamp": "t",
                "text": "go",
                "model": "7",
                "skills": ["pdf"],
            }
        )
        assert body.to_internal().skills == ["pdf"]
        daily = OpenDailyChatCompletionReq.model_validate(
            {"clientTimestamp": "t", "model": "7", "text": "hi", "skills": ["pdf"]}
        )
        internal = daily.to_internal()
        assert internal.task_mode is False
        assert internal.skills == ["pdf"]


async def test_open_api_honors_per_account_availability(skills, monkeypatch):
    personal = await LinsightSkillDao.get_by_name("pdf", owner_user_id=USER)
    monkeypatch.setattr(
        "bisheng.linsight.domain.services.user_skills.SkillAvailabilityRepository.disabled_ids",
        AsyncMock(return_value={personal.id}),
    )
    rows = await OpenTaskModeService.enabled_skill_rows(SimpleNamespace(user_id=USER))
    assert personal.id not in {row.id for row in rows}


async def test_open_api_filters_revoked_personal_permission(skills, monkeypatch):
    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.batch_check_business_actions", AsyncMock(return_value={})
    )
    assert await OpenTaskModeService.enabled_skill_rows(SimpleNamespace(user_id=USER)) == []

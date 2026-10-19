"""Enabling, disabling and deleting a personal skill."""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

import bisheng.linsight.domain.models.linsight_skill as model_module
import bisheng.linsight.domain.services.personal_skill_service as service_module
from bisheng.common.errcode.linsight import SkillNotFoundError
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.database.models.audit_log import AuditLog
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao
from bisheng.linsight.domain.services.personal_skill_service import PersonalSkillService
from bisheng.linsight.domain.services.skill_store import SKILL_MD, SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 5
USER = 11
OTHER = 22
STAMP = datetime(2020, 1, 1, 8, 0, 0)


def _md(body: str) -> bytes:
    return f"---\nname: pdf\ndescription: demo description\nmetadata:\n  display-name: 报告\n---\n\n# {body}\n".encode()


@pytest.fixture
async def env(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/skills.db", connect_args={"timeout": 5})
    async with engine.begin() as conn:
        await conn.run_sync(LinsightSkill.__table__.create)
        await conn.run_sync(AuditLog.__table__.create)

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
    monkeypatch.setattr(service_module, "get_async_db_session", _session)
    monkeypatch.setattr(
        "bisheng.permission.application.business_authorization.require_business_action",
        AsyncMock(),
    )
    set_current_tenant_id(TENANT)
    store = SkillStore(root=tmp_path / "cache", minio=FakeMinioStorage())
    service = PersonalSkillService(
        store=store,
        owner_projection=SimpleNamespace(authorize_created=AsyncMock()),
        unpack_root=tmp_path / "unpack",
    )
    yield SimpleNamespace(dao=LinsightSkillDao, service=service, store=store)
    await engine.dispose()


async def _skill(env, owner: int, body: str, *, enabled: bool = True) -> LinsightSkill:
    ref = env.store.write_bundle(TENANT, "pdf", {SKILL_MD: _md(body)}, owner_user_id=owner)
    return await env.dao.create(
        LinsightSkill(
            tenant_id=TENANT,
            owner_user_id=owner,
            name="pdf",
            display_name="报告",
            description="demo description",
            enabled=enabled,
            source="manual",
            object_path=ref.object_key,
            content_hash=ref.content_hash,
            size=ref.size,
            created_by=owner,
            create_time=STAMP,
            update_time=STAMP,
        )
    )


async def _audits() -> list[AuditLog]:
    with bypass_tenant_filter():
        async with model_module.get_async_db_session() as session:
            return list((await session.exec(select(AuditLog))).all())


class TestPersonalSkillLifecycle:
    async def test_same_state_keeps_the_row_and_skips_audit(self, env):
        skill = await _skill(env, USER, "one", enabled=True)
        saved = await env.service.set_enabled(user_id=USER, skill_id=skill.id, enabled=True)
        assert saved.id == skill.id
        stored = await env.dao.get_by_id(skill.id)
        assert stored.update_time == STAMP
        assert bool(stored.enabled) is True
        assert await _audits() == []

    async def test_disabling_keeps_the_row_and_the_object(self, env):
        skill = await _skill(env, USER, "one", enabled=True)
        saved = await env.service.set_enabled(user_id=USER, skill_id=skill.id, enabled=False)
        assert bool(saved.enabled) is False
        stored = await env.dao.get_by_id(skill.id)
        assert stored is not None
        assert bool(stored.enabled) is False
        assert env.store.exists(TENANT, "pdf", skill.content_hash, owner_user_id=USER)
        logs = await _audits()
        assert len(logs) == 1
        assert logs[0].system_id == "linsight"
        assert logs[0].operator_id == USER
        assert logs[0].target_id == str(skill.id)
        assert logs[0].audit_metadata["result"] == "success"

        again = await env.service.set_enabled(user_id=USER, skill_id=skill.id, enabled=False)
        assert bool(again.enabled) is False
        assert (await env.dao.get_by_id(skill.id)).update_time == stored.update_time
        assert len(await _audits()) == 1

    async def test_failed_toggle_keeps_the_previous_value(self, env, monkeypatch):
        skill = await _skill(env, USER, "one", enabled=True)

        async def _boom(*args, **kwargs):
            raise RuntimeError("toggle failed")

        monkeypatch.setattr(LinsightSkillDao, "set_owner_enabled", _boom)
        with pytest.raises(RuntimeError, match="toggle failed"):
            await env.service.set_enabled(user_id=USER, skill_id=skill.id, enabled=False)
        assert bool((await env.dao.get_by_id(skill.id)).enabled) is True
        assert await _audits() == []

    async def test_missing_skill_cannot_be_toggled(self, env):
        with pytest.raises(SkillNotFoundError) as caught:
            await env.service.set_enabled(user_id=USER, skill_id=999, enabled=False)
        assert caught.value.code == 11053

    async def test_delete_removes_the_row_and_its_object_only(self, env):
        mine = await _skill(env, USER, "mine")
        theirs = await _skill(env, OTHER, "theirs")
        result = await env.service.delete(user_id=USER, skill_id=mine.id)
        assert result is None
        assert await env.dao.get_by_id(mine.id) is None
        assert not env.store.exists(TENANT, "pdf", mine.content_hash, owner_user_id=USER)
        assert env.store.minio.keys(f"linsight/personal-skills/{TENANT}/{USER}/pdf/") == []
        still = await env.dao.get_by_name("pdf", owner_user_id=OTHER)
        assert still is not None and still.id == theirs.id
        assert env.store.exists(TENANT, "pdf", theirs.content_hash, owner_user_id=OTHER)

    async def test_delete_of_a_missing_or_other_skill_is_empty(self, env):
        skill = await _skill(env, USER, "mine")
        missing = await env.service.delete(user_id=USER, skill_id=999)
        someone_else = await env.service.delete(user_id=OTHER, skill_id=skill.id)
        assert missing is None and someone_else is None
        assert await env.dao.get_by_id(skill.id) is not None
        assert env.store.exists(TENANT, "pdf", skill.content_hash, owner_user_id=USER)

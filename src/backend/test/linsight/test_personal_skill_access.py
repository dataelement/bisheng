"""Single-skill reads authorize only after the row belongs to the caller.

A delete of a missing id, or of someone else's skill, stays the empty result
from the lifecycle tests. Detail, file read, update and enable/disable of those
ids are 11053. None of those misses call require_business_action.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import bisheng.linsight.domain.models.linsight_skill as model_module
from bisheng.common.errcode.linsight import SkillNotFoundError, SkillVersionConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao
from bisheng.linsight.domain.services.personal_skill_service import PersonalSkillService
from bisheng.linsight.domain.services.skill_store import SKILL_MD, SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 5
OTHER_TENANT = 9
USER = 11
OTHER = 22
GATE = "bisheng.permission.application.business_authorization.require_business_action"


def _md(name: str, body: str, display: str) -> bytes:
    return (
        f"---\nname: {name}\ndescription: 用途说明\nmetadata:\n  display-name: {display}\n---\n\n# {body}\n"
    ).encode()


def _assert_hidden(exc: SkillNotFoundError, *secrets: str) -> None:
    assert exc.code == 11053
    assert exc.kwargs == {}
    text = str(exc.to_dict())
    for secret in secrets:
        assert secret not in text


def _authorized(gate, *, action: str, skill_id: int) -> bool:
    return any(
        call.kwargs.get("action") == action
        and call.kwargs.get("resource_type") == "linsight_skill"
        and call.kwargs.get("resource_id") == skill_id
        for call in gate.await_args_list
    )


@pytest.fixture
async def env(tmp_path, monkeypatch):
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
    monkeypatch.setattr(PersonalSkillService, "_audit", AsyncMock())
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    tenant_filter.register_tenant_filter_events()
    set_current_tenant_id(TENANT)
    store = SkillStore(root=tmp_path / "cache", minio=FakeMinioStorage())
    service = PersonalSkillService(
        store=store,
        owner_projection=SimpleNamespace(authorize_created=AsyncMock()),
        unpack_root=tmp_path / "unpack",
    )
    yield SimpleNamespace(dao=LinsightSkillDao, service=service, store=store)
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    await engine.dispose()


async def _save(env, name: str, owner: int, body: str, display: str, *, enabled: bool = True, tenant_id: int = TENANT):
    if owner == 0 or tenant_id == TENANT:
        ref = env.store.write_bundle(tenant_id, name, {SKILL_MD: _md(name, body, display)}, owner_user_id=owner)
        object_path, content_hash, size = ref.object_key, ref.content_hash, ref.size
    else:
        object_path, content_hash, size = f"linsight/skills/{tenant_id}/{name}/missing.zip", "b" * 64, 10
    row = LinsightSkill(
        tenant_id=tenant_id,
        owner_user_id=owner,
        name=name,
        display_name=display,
        description="用途说明",
        enabled=enabled,
        source="manual",
        object_path=object_path,
        content_hash=content_hash,
        size=size,
        created_by=owner or 1,
    )
    with bypass_tenant_filter():
        return await env.dao.create(row)


class TestPersonalSkillAccess:
    async def test_missing_or_foreign_rows_stay_hidden(self, env):
        skill = await _save(env, "pdf", USER, "个人正文", "个人报告")
        secrets = (skill.display_name, skill.object_path, "个人正文")
        foreign = await _save(env, "foreign", 0, "外租户正文", "外租户技能", tenant_id=OTHER_TENANT)

        async def _reject(user_id: int, skill_id: int):
            with patch(GATE, new_callable=AsyncMock) as gate:
                with pytest.raises(SkillNotFoundError) as caught:
                    await env.service.get(user_id=user_id, skill_id=skill_id)
                _assert_hidden(caught.value, *secrets)
                with pytest.raises(SkillNotFoundError) as caught:
                    await env.service.read_file(user_id=user_id, skill_id=skill_id, path=SKILL_MD)
                _assert_hidden(caught.value, *secrets)
                with pytest.raises(SkillNotFoundError) as caught:
                    await env.service.overwrite(
                        user_id=user_id,
                        skill_id=skill_id,
                        filename="pdf.md",
                        data=b"nope",
                        expected_content_hash=skill.content_hash,
                        import_id="imp-hidden",
                    )
                _assert_hidden(caught.value, *secrets)
                with pytest.raises(SkillNotFoundError) as caught:
                    await env.service.set_enabled(user_id=user_id, skill_id=skill_id, enabled=False)
                _assert_hidden(caught.value, *secrets)
                assert await env.service.delete(user_id=user_id, skill_id=skill_id) is None
                gate.assert_not_called()
            stored = await env.dao.get_by_id(skill.id)
            assert stored is not None and bool(stored.enabled) is True

        await _reject(OTHER, skill.id)
        await _reject(USER, 999)
        await _reject(USER, foreign.id)

    async def test_owner_is_authorized_before_the_content_is_returned(self, env):
        skill = await _save(env, "pdf", USER, "个人正文", "个人报告")
        with patch(GATE, new_callable=AsyncMock) as gate:
            detail = await env.service.get(user_id=USER, skill_id=skill.id)
            assert detail.bundle_missing is False
            assert "个人正文" in detail.source_text
            assert _authorized(gate, action="edit", skill_id=skill.id)

            gate.reset_mock()
            opened = await env.service.read_file(user_id=USER, skill_id=skill.id, path=SKILL_MD)
            assert "个人正文" in opened.content
            assert _authorized(gate, action="edit", skill_id=skill.id)

            gate.reset_mock()
            with pytest.raises(SkillVersionConflictError):
                await env.service.overwrite(
                    user_id=USER,
                    skill_id=skill.id,
                    filename="pdf.md",
                    data=b"nope",
                    expected_content_hash="0" * 64,
                    import_id="imp-stale",
                )
            assert _authorized(gate, action="edit", skill_id=skill.id)

            gate.reset_mock()
            saved = await env.service.set_enabled(user_id=USER, skill_id=skill.id, enabled=False)
            assert bool(saved.enabled) is False
            assert _authorized(gate, action="edit", skill_id=skill.id)

            gate.reset_mock()
            assert await env.service.delete(user_id=USER, skill_id=skill.id) is None
            assert _authorized(gate, action="delete", skill_id=skill.id)
        assert await env.dao.get_by_id(skill.id) is None

    async def test_a_missing_bundle_is_still_a_detail(self, env):
        skill = await _save(env, "pdf", USER, "个人正文", "个人报告")
        env.store.delete_version(TENANT, "pdf", skill.content_hash, owner_user_id=USER)
        with patch(GATE, new_callable=AsyncMock) as gate:
            detail = await env.service.get(user_id=USER, skill_id=skill.id)
            assert detail.bundle_missing is True
            assert detail.source_text == ""
            assert detail.skill.id == skill.id
            assert _authorized(gate, action="edit", skill_id=skill.id)

    async def test_a_disabled_enterprise_skill_stays_distinct_from_a_deleted_one(self, env):
        skill = await _save(env, "he-tong", 0, "企业正文", "合同审阅", enabled=False)
        with patch(GATE, new_callable=AsyncMock) as gate:
            detail = await env.service.get(user_id=USER, skill_id=skill.id)
            assert bool(detail.skill.enabled) is False
            assert detail.bundle_missing is False
            assert "企业正文" in detail.source_text
            gate.assert_not_called()

            await env.dao.delete_by_name("he-tong")
            with pytest.raises(SkillNotFoundError) as caught:
                await env.service.get(user_id=USER, skill_id=skill.id)
            _assert_hidden(caught.value, "合同审阅", "企业正文", skill.object_path)
            gate.assert_not_called()

"""Overwriting a personal skill keeps its id and enabled flag."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

import bisheng.linsight.domain.models.linsight_skill as model_module
import bisheng.linsight.domain.services.personal_skill_service as service_module
from bisheng.common.errcode.linsight import (
    SkillNotFoundError,
    SkillStorageLimitError,
    SkillVersionConflictError,
)
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.database.models.audit_log import AuditLog
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao
from bisheng.linsight.domain.services.personal_skill_service import (
    PERSONAL_SKILL_BYTES_LIMIT,
    PersonalSkillService,
)
from bisheng.linsight.domain.services.skill_store import SKILL_MD, SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 5
USER = 11
OTHER = 22


def _md(name: str = "pdf", body: str = "one") -> bytes:
    return (
        f"---\nname: {name}\ndescription: demo description\nmetadata:\n  display-name: 报告\n---\n\n# {body}\n"
    ).encode()


@pytest.fixture
async def env(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/skills.db",
        connect_args={"timeout": 5},
    )
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


async def _owned(env, body: str = "one", *, enabled: bool = False, size: int | None = None) -> LinsightSkill:
    data = _md(body=body)
    ref = env.store.write_bundle(TENANT, "pdf", {SKILL_MD: data}, owner_user_id=USER)
    return await env.dao.create(
        LinsightSkill(
            tenant_id=TENANT,
            owner_user_id=USER,
            name="pdf",
            display_name="报告",
            description="demo description",
            enabled=enabled,
            source="manual",
            object_path=ref.object_key,
            content_hash=ref.content_hash,
            size=ref.size if size is None else size,
            created_by=USER,
        )
    )


class TestPersonalSkillOverwrite:
    async def test_stale_hash_does_not_write_or_change_the_row(self, env):
        skill = await _owned(env)
        puts = env.store.minio.put_calls
        with pytest.raises(SkillVersionConflictError) as caught:
            await env.service.overwrite(
                user_id=USER,
                skill_id=skill.id,
                filename="pdf.md",
                data=_md(body="two"),
                expected_content_hash="0" * 64,
                import_id="imp-stale",
                content_type="text/plain",
            )
        assert caught.value.code == 11064
        assert env.store.minio.put_calls == puts
        stored = await env.dao.get_by_id(skill.id)
        assert stored.content_hash == skill.content_hash
        assert stored.object_path == skill.object_path

    async def test_matching_hash_replaces_the_bundle_and_keeps_id_and_enabled(self, env):
        skill = await _owned(env, enabled=False)
        before = await env.service.usage(USER)
        saved = await env.service.overwrite(
            user_id=USER,
            skill_id=skill.id,
            filename="pdf.md",
            data=_md(body="two"),
            expected_content_hash=skill.content_hash,
            import_id="imp-next",
            content_type="text/plain",
        )
        assert saved.id == skill.id
        assert saved.enabled is False or saved.enabled == 0
        assert saved.content_hash != skill.content_hash
        assert saved.object_path.endswith(f"/{saved.content_hash}.zip")
        stored = await env.dao.get_by_id(skill.id)
        assert stored.content_hash == saved.content_hash
        assert "two" in env.store.read_text(TENANT, "pdf", saved.content_hash, owner_user_id=USER)
        assert env.store.minio.keys(f"linsight/personal-skills/{TENANT}/{USER}/pdf/") == [saved.object_path]
        assert (await env.service.usage(USER)).count == before.count

        with bypass_tenant_filter():
            async with model_module.get_async_db_session() as session:
                logs = list((await session.exec(select(AuditLog))).all())
        assert len(logs) == 1
        assert logs[0].operator_id == USER
        assert logs[0].tenant_id == TENANT
        assert logs[0].system_id == "linsight"
        assert logs[0].target_id == str(skill.id)
        assert logs[0].audit_metadata["content_hash"] == saved.content_hash
        assert logs[0].audit_metadata["result"] == "success"

    async def test_same_hash_does_not_delete_the_object(self, env):
        skill = await _owned(env)
        data = _md(body="one")
        saved = await env.service.overwrite(
            user_id=USER,
            skill_id=skill.id,
            filename="pdf.md",
            data=data,
            expected_content_hash=skill.content_hash,
            import_id="imp-same",
            content_type="text/plain",
        )
        assert saved.content_hash == skill.content_hash
        assert env.store.minio.keys(f"linsight/personal-skills/{TENANT}/{USER}/pdf/") == [skill.object_path]

    async def test_storage_limit_keeps_the_old_bundle(self, env):
        skill = await _owned(env, size=100)
        await env.dao.create(
            LinsightSkill(
                tenant_id=TENANT,
                owner_user_id=USER,
                name="filler",
                display_name="占位",
                description="seed",
                enabled=True,
                source="manual",
                object_path="linsight/personal-skills/5/11/filler/seed.zip",
                content_hash="c" * 64,
                size=PERSONAL_SKILL_BYTES_LIMIT - 100,
                created_by=USER,
            )
        )
        puts = env.store.minio.put_calls
        payload = _md(body="x" * 2000)
        with pytest.raises(SkillStorageLimitError) as caught:
            await env.service.overwrite(
                user_id=USER,
                skill_id=skill.id,
                filename="pdf.md",
                data=payload,
                expected_content_hash=skill.content_hash,
                import_id="imp-big",
                content_type="text/plain",
            )
        assert caught.value.code == 11062
        stored = await env.dao.get_by_id(skill.id)
        assert stored.content_hash == skill.content_hash
        assert stored.size == 100
        assert env.store.minio.put_calls == puts
        assert env.store.minio.keys(f"linsight/personal-skills/{TENANT}/{USER}/pdf/") == [skill.object_path]
        assert (await env.service.usage(USER)).count == 2

    async def test_failed_row_update_leaves_the_old_hash(self, env, monkeypatch):
        skill = await _owned(env)

        async def _boom(*args, **kwargs):
            raise RuntimeError("row update failed")

        monkeypatch.setattr(LinsightSkillDao, "update_bundle", _boom)
        with pytest.raises(RuntimeError, match="row update failed"):
            await env.service.overwrite(
                user_id=USER,
                skill_id=skill.id,
                filename="pdf.md",
                data=_md(body="two"),
                expected_content_hash=skill.content_hash,
                import_id="imp-fail",
                content_type="text/plain",
            )
        stored = await env.dao.get_by_id(skill.id)
        assert stored.content_hash == skill.content_hash
        assert stored.object_path == skill.object_path
        assert env.store.read_text(TENANT, "pdf", skill.content_hash, owner_user_id=USER)

    async def test_someone_elses_skill_is_not_found_and_skips_authorization(self, env):
        skill = await _owned(env)
        with patch("bisheng.permission.application.business_authorization.require_business_action") as gate:
            with pytest.raises(SkillNotFoundError) as caught:
                await env.service.overwrite(
                    user_id=OTHER,
                    skill_id=skill.id,
                    filename="pdf.md",
                    data=_md(body="two"),
                    expected_content_hash=skill.content_hash,
                    import_id="imp-other",
                    content_type="text/plain",
                )
            assert caught.value.code == 11053
            gate.assert_not_called()
        stored = await env.dao.get_by_id(skill.id)
        assert stored.content_hash == skill.content_hash

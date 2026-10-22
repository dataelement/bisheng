"""Personal skill create: quota, import id, and an audit row that cannot fail the save."""

import asyncio
import io
import shutil
import zipfile
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

import bisheng.database.models.audit_log as audit_module
import bisheng.linsight.domain.models.linsight_skill as model_module
import bisheng.linsight.domain.services.personal_skill_service as service_module
from bisheng.common.errcode.linsight import (
    SkillCountLimitError,
    SkillEmptyFileError,
    SkillImportMismatchError,
    SkillNameDuplicateError,
    SkillNotFoundError,
    SkillStorageLimitError,
)
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.database.models.audit_log import AuditLog
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao
from bisheng.linsight.domain.services.personal_skill_service import (
    PERSONAL_SKILL_BYTES_LIMIT,
    PERSONAL_SKILL_COUNT_LIMIT,
    PersonalSkillService,
)
from bisheng.linsight.domain.services.skill_store import SKILL_MD, SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 5
OTHER_TENANT = 6
USER = 11
OTHER_USER = 22


def _md(name: str, display: str = "报告", body: str = "body") -> bytes:
    return (
        f"---\nname: {name}\ndescription: demo description\nmetadata:\n  display-name: {display}\n---\n\n# {body}\n"
    ).encode()


def _zip(name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(SKILL_MD, _md(name))
    return buf.getvalue()


def _seed(name: str, owner_user_id: int, *, enabled: bool = True, size: int = 10) -> LinsightSkill:
    return LinsightSkill(
        tenant_id=TENANT,
        owner_user_id=owner_user_id,
        name=name,
        display_name=name,
        description="seed",
        enabled=enabled,
        source="manual",
        object_path=f"linsight/skills/{TENANT}/{name}/seed.zip",
        content_hash="b" * 64,
        size=size,
        created_by=owner_user_id or 1,
    )


@contextmanager
def _as_other_tenant():
    token_tenant = set_current_tenant_id(OTHER_TENANT)
    token_visible = set_visible_tenant_ids(frozenset({OTHER_TENANT, TENANT}))
    try:
        yield
    finally:
        current_tenant_id.reset(token_tenant)
        visible_tenant_ids.reset(token_visible)


@pytest.fixture
async def env(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core.database import tenant_filter

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/skills.db",
        connect_args={"timeout": 5},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
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
    monkeypatch.setattr(audit_module, "get_async_db_session", _session)
    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    tenant_filter.register_tenant_filter_events()
    set_current_tenant_id(TENANT)

    store = SkillStore(root=tmp_path / "cache", minio=FakeMinioStorage())
    unpack = tmp_path / "unpack"
    service = PersonalSkillService(
        store=store,
        owner_projection=SimpleNamespace(authorize_created=AsyncMock()),
        unpack_root=unpack,
    )
    yield SimpleNamespace(dao=LinsightSkillDao, service=service, store=store, unpack=unpack)

    tenant_filter._initialized = False
    tenant_filter._tenant_aware_tables = set()
    await engine.dispose()


async def _audits() -> list[AuditLog]:
    with bypass_tenant_filter():
        async with model_module.get_async_db_session() as session:
            return list((await session.exec(select(AuditLog))).all())


class TestPersonalSkillCreate:
    async def test_md_zip_and_skill_are_stored_for_the_user(self, env):
        md = await env.service.create(
            user_id=USER, filename="pdf.md", data=_md("pdf"), import_id="imp-md", content_type="text/plain"
        )
        zipped = await env.service.create(
            user_id=USER, filename="sheet.zip", data=_zip("sheet"), import_id="imp-zip", content_type="application/zip"
        )
        skill = await env.service.create(
            user_id=USER,
            filename="deck.skill",
            data=_zip("deck"),
            import_id="imp-skill",
            content_type="application/octet-stream",
        )
        for row in (md, zipped, skill):
            assert row.owner_user_id == USER
            stored = await env.dao.get_by_name(row.name, owner_user_id=USER)
            assert stored is not None and stored.id == row.id
        shutil.rmtree(env.store.root)
        assert "demo description" in env.store.read_text(TENANT, "pdf", md.content_hash, owner_user_id=USER)
        kwargs = env.service._owner_projection.authorize_created.await_args.kwargs
        assert kwargs["resource_type"] == "linsight_skill"
        assert kwargs["owner_user_id"] == USER
        assert kwargs["resource_id"] == str(skill.id)

    async def test_quota_counts_disabled_personal_skills_and_ignores_tenant_skills(self, env):
        await env.dao.create(_seed("enterprise", 0, size=PERSONAL_SKILL_BYTES_LIMIT))
        for index in range(PERSONAL_SKILL_COUNT_LIMIT):
            await env.dao.create(_seed(f"old-{index}", USER, enabled=False))
        usage = await env.service.usage(USER)
        assert usage.count == PERSONAL_SKILL_COUNT_LIMIT
        assert usage.count_limit == 20
        assert usage.bytes_limit == PERSONAL_SKILL_BYTES_LIMIT
        assert usage.used_bytes == 10 * PERSONAL_SKILL_COUNT_LIMIT

        with pytest.raises(SkillCountLimitError) as caught:
            await env.service.create(
                user_id=USER, filename="pdf.md", data=_md("pdf"), import_id="imp-over", content_type="text/plain"
            )
        assert caught.value.code == 11061
        assert await env.dao.get_by_name("pdf", owner_user_id=USER) is None
        assert env.store.minio.put_calls == 0
        assert list(env.unpack.iterdir()) == []

    async def test_storage_limit_leaves_existing_rows(self, env):
        payload = _md("extra")
        seeded = await env.dao.create(_seed("kept", USER, size=PERSONAL_SKILL_BYTES_LIMIT - len(payload) + 1))
        with pytest.raises(SkillStorageLimitError) as caught:
            await env.service.create(
                user_id=USER, filename="extra.md", data=payload, import_id="imp-bytes", content_type="text/plain"
            )
        assert caught.value.code == 11062
        assert (await env.dao.get_by_name("kept", owner_user_id=USER)).size == seeded.size
        assert env.store.minio.put_calls == 0

    async def test_rejected_upload_writes_nothing(self, env):
        with pytest.raises(SkillEmptyFileError):
            await env.service.create(
                user_id=USER, filename="pdf.md", data=b"", import_id="imp-empty", content_type="text/plain"
            )
        assert env.store.minio.put_calls == 0
        assert list(env.unpack.iterdir()) == []

    async def test_cancel_removes_the_unpack_directory(self, env, monkeypatch):
        def _cancel(*args, **kwargs):
            raise asyncio.CancelledError()

        monkeypatch.setattr(env.store, "write_bundle", _cancel)
        with pytest.raises(asyncio.CancelledError):
            await env.service.create(
                user_id=USER, filename="pdf.md", data=_md("pdf"), import_id="imp-cancel", content_type="text/plain"
            )
        assert await env.dao.get_by_name("pdf", owner_user_id=USER) is None
        assert env.store.minio.put_calls == 0
        assert list(env.unpack.iterdir()) == []

    async def test_same_personal_name_returns_11055_without_a_write(self, env):
        first = await env.service.create(
            user_id=USER, filename="pdf.md", data=_md("pdf", body="one"), import_id="imp-1", content_type="text/plain"
        )
        puts = env.store.minio.put_calls
        with pytest.raises(SkillNameDuplicateError) as caught:
            await env.service.create(
                user_id=USER,
                filename="pdf.md",
                data=_md("pdf", body="two"),
                import_id="imp-2",
                content_type="text/plain",
            )
        data = caught.value.to_dict()["data"]
        assert data["skill_id"] == first.id
        assert data["content_hash"] == first.content_hash
        assert env.store.minio.put_calls == puts
        assert (await env.dao.get_by_name("pdf", owner_user_id=USER)).content_hash == first.content_hash

    async def test_enterprise_skill_with_the_same_name_is_not_a_duplicate(self, env):
        await env.dao.create(_seed("pdf", 0))
        created = await env.service.create(
            user_id=USER, filename="pdf.md", data=_md("pdf"), import_id="imp-own", content_type="text/plain"
        )
        assert created.owner_user_id == USER
        assert await env.dao.get_by_name("pdf", owner_user_id=0) is not None

    async def test_import_id_retries_and_mismatches(self, env):
        payload = _md("pdf")
        first = await env.service.create(
            user_id=USER, filename="pdf.md", data=payload, import_id="imp-retry", content_type="text/plain"
        )
        puts = env.store.minio.put_calls
        again = await env.service.create(
            user_id=USER, filename="pdf.md", data=payload, import_id="imp-retry", content_type="text/plain"
        )
        assert again.id == first.id
        assert env.store.minio.put_calls == puts
        found = await env.service.find_by_import(USER, "imp-retry")
        assert found.id == first.id

        with pytest.raises(SkillImportMismatchError) as caught:
            await env.service.create(
                user_id=USER,
                filename="pdf.md",
                data=_md("pdf", body="changed"),
                import_id="imp-retry",
                content_type="text/plain",
            )
        assert caught.value.code == 11066
        assert (await env.dao.get_by_name("pdf", owner_user_id=USER)).content_hash == first.content_hash
        assert env.store.minio.put_calls == puts

        with pytest.raises(SkillNotFoundError) as missing:
            await env.service.find_by_import(USER, "missing")
        assert missing.value.code == 11053

    async def test_concurrent_same_name_keeps_one_row(self, env):
        async def _save(body: str, import_id: str):
            return await env.service.create(
                user_id=USER,
                filename="pdf.md",
                data=_md("pdf", body=body),
                import_id=import_id,
                content_type="text/plain",
            )

        results = await asyncio.gather(_save("one", "imp-a"), _save("two", "imp-b"), return_exceptions=True)
        saved = [item for item in results if not isinstance(item, Exception)]
        failed = [item for item in results if isinstance(item, Exception)]
        assert len(saved) == 1 and len(failed) == 1
        assert isinstance(failed[0], SkillNameDuplicateError)
        winner = await env.dao.get_by_name("pdf", owner_user_id=USER)
        assert winner is not None
        assert env.store.minio.keys(f"linsight/personal-skills/{TENANT}/{USER}/pdf/") == [winner.object_path]

    async def test_audit_records_the_save_and_a_failed_audit_keeps_the_skill(self, env, monkeypatch):
        skill = await env.service.create(
            user_id=USER, filename="pdf.md", data=_md("pdf"), import_id="imp-audit", content_type="text/plain"
        )
        logs = await _audits()
        assert len(logs) == 1
        entry = logs[0]
        assert entry.operator_id == USER
        assert entry.tenant_id == TENANT
        assert entry.system_id == "linsight"
        assert entry.target_id == str(skill.id)
        assert entry.audit_metadata == {"source": "manual", "content_hash": skill.content_hash, "result": "success"}
        assert entry.object_name is None
        assert entry.note is None

        class _Boom:
            def __init__(self, **kwargs):
                raise RuntimeError("audit down")

        monkeypatch.setattr(service_module, "AuditLog", _Boom)
        kept = await env.service.create(
            user_id=USER, filename="other.md", data=_md("other"), import_id="imp-audit-2", content_type="text/plain"
        )
        assert (await env.dao.get_by_name("other", owner_user_id=USER)).id == kept.id

    async def test_another_tenant_cannot_see_the_row(self, env):
        await env.service.create(
            user_id=USER, filename="pdf.md", data=_md("pdf"), import_id="imp-tenant", content_type="text/plain"
        )
        with _as_other_tenant():
            assert await env.dao.get_by_name("pdf", owner_user_id=USER) is None
            usage = await env.service.usage(USER)
            assert usage.count == 0 and usage.used_bytes == 0

    async def test_load_own_skill_hides_other_users(self, env):
        skill = await env.service.create(
            user_id=USER, filename="pdf.md", data=_md("pdf"), import_id="imp-load", content_type="text/plain"
        )
        with patch(
            "bisheng.permission.application.business_authorization.require_business_action",
            new_callable=AsyncMock,
        ) as gate:
            assert (await env.service._load_own_skill(USER, skill.id)).id == skill.id
            gate.assert_awaited()
            calls = env.service._owner_projection.authorize_created.await_count
            gate.reset_mock()
            with pytest.raises(SkillNotFoundError) as caught:
                await env.service._load_own_skill(OTHER_USER, skill.id)
            assert caught.value.code == 11053
            gate.assert_not_called()
            assert env.service._owner_projection.authorize_created.await_count == calls

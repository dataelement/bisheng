"""A personal skill may share a name with a tenant skill or with another user.

The same owner cannot save the skill id twice. A lost race leaves no object
that the saved row does not point at.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bisheng.linsight.domain.models.linsight_skill as model_module
from bisheng.common.errcode.linsight import SkillNameDuplicateError
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao
from bisheng.linsight.domain.services.skill_service import SkillService
from bisheng.linsight.domain.services.skill_store import SKILL_MD, SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 5
USER_A = 11
USER_B = 22


def _row(name: str, owner_user_id: int, display_name: str) -> LinsightSkill:
    return LinsightSkill(
        tenant_id=TENANT,
        owner_user_id=owner_user_id,
        name=name,
        display_name=display_name,
        description="d",
        enabled=True,
        source="manual",
        object_path=f"linsight/skills/{TENANT}/{name}/hash.zip",
        content_hash="a" * 64,
        size=1,
        created_by=owner_user_id or 1,
    )


@pytest.fixture
async def dao(monkeypatch, tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    # Separate connections: a single shared SQLite connection makes the winner's
    # refresh fail while the other insert is still in flight.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/skills.db",
        connect_args={"timeout": 5},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
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
    set_current_tenant_id(TENANT)
    yield LinsightSkillDao
    await engine.dispose()


@pytest.fixture
def service(dao, tmp_path):
    store = SkillStore(root=tmp_path, minio=FakeMinioStorage())
    return SkillService(store=store, owner_projection=SimpleNamespace(authorize_created=AsyncMock()))


class TestDuplicateScope:
    async def test_same_name_is_allowed_across_owners(self, dao, service):
        await dao.create(_row("pdf", 0, "企业报告"))
        await dao.create(_row("pdf", USER_A, "个人报告"))

        await service._check_duplicate("pdf", "另一份", owner_user_id=USER_B)
        saved = await dao.create(_row("pdf", USER_B, "另一份"))
        assert saved.owner_user_id == USER_B

        with pytest.raises(SkillNameDuplicateError) as caught:
            await service._check_duplicate("pdf", "再来一份", owner_user_id=USER_A)
        assert caught.value.code == 11055

    async def test_same_display_name_with_a_different_skill_id_is_saved(self, dao, service):
        await dao.create(_row("pdf", USER_A, "季度报告"))
        await service._check_duplicate("other", "季度报告", owner_user_id=USER_A)
        saved = await dao.create(_row("other", USER_A, "季度报告"))
        assert saved.name == "other"

    async def test_concurrent_same_owner_keeps_one_row_and_no_orphan_object(self, dao, service):
        async def _allow(*args, **kwargs):
            return None

        service._check_duplicate = _allow

        async def _save(body: bytes):
            return await service._create(TENANT, USER_A, "pdf", "报告", "d", {SKILL_MD: body})

        results = await asyncio.gather(_save(b"first-body"), _save(b"second-body"), return_exceptions=True)
        saved = [item for item in results if not isinstance(item, Exception)]
        failed = [item for item in results if isinstance(item, Exception)]
        assert len(saved) == 1
        assert len(failed) == 1
        assert isinstance(failed[0], SkillNameDuplicateError)
        assert failed[0].code == 11055

        again = await dao.get_by_name("pdf")
        assert again is not None
        assert service.store.read_text(TENANT, "pdf", again.content_hash) in ("first-body", "second-body")
        keys = service.store.minio.keys(f"linsight/skills/{TENANT}/pdf/")
        assert keys == [again.object_path]

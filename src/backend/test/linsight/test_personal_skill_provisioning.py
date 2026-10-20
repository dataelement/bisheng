"""New tasks copy every candidate bundle. Resume does not mix a second skill in."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import bisheng.linsight.domain.models.linsight_skill as model_module
from bisheng.core.context.tenant import bypass_tenant_filter, set_current_tenant_id
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao
from bisheng.linsight.domain.schemas.linsight_schema import LinsightQuestionSubmitSchema
from bisheng.linsight.domain.services.skill_provisioning import (
    materialize_session_skills,
    pending_skill_snapshot,
)
from bisheng.linsight.domain.services.skill_store import SkillStore
from bisheng.linsight.domain.services.workbench_impl import build_e2b_file_list
from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import SIZE_AUTOPUSH
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 5
USER = 11
OTHER = 22

_TASK_EXEC = Path(__file__).parents[2] / "bisheng/linsight/domain/task_exec.py"


def _skill_md(name: str, description: str) -> bytes:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n".encode()


class _Resp:
    def __init__(self, path: str, error: str | None = None):
        self.path = path
        self.error = error


class _CacheBackend:
    def __init__(self, file_dir: Path):
        self.file_dir = Path(file_dir)
        self.uploaded: list[tuple[str, bytes]] = []

    async def aupload_files(self, files):
        out = []
        for raw_path, data in files:
            rel = raw_path.lstrip("/")
            target = self.file_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            self.uploaded.append((raw_path, data))
            out.append(_Resp("/" + rel))
        return out


def _method_body(source: str, name: str) -> str:
    start = source.index(f"async def {name}(")
    rest = source[start:]
    match = re.search(r"\n    (?:async )?def ", rest[1:])
    return rest[: match.start() + 1] if match else rest


async def _seed(
    store: SkillStore,
    *,
    name: str,
    owner: int,
    description: str,
    extra: dict[str, bytes] | None = None,
    enabled: bool = True,
) -> LinsightSkill:
    files = {"SKILL.md": _skill_md(name, description), **(extra or {})}
    ref = store.write_bundle(TENANT, name, files, owner_user_id=owner)
    row = LinsightSkill(
        tenant_id=TENANT,
        owner_user_id=owner,
        name=name,
        display_name=description,
        description=description,
        enabled=enabled,
        source="manual",
        object_path=store.object_key(TENANT, name, ref.content_hash, owner_user_id=owner),
        content_hash=ref.content_hash,
        size=sum(len(item) for item in files.values()),
        created_by=owner or 1,
    )
    with bypass_tenant_filter():
        return await LinsightSkillDao.create(row)


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

    store = SkillStore(root=tmp_path / "skills", minio=FakeMinioStorage())
    personal = await _seed(
        store,
        name="pdf",
        owner=USER,
        description="个人用途",
        extra={"who.txt": b"personal"},
    )
    enterprise = await _seed(
        store,
        name="pdf",
        owner=0,
        description="企业用途",
        extra={"who.txt": b"enterprise", "enterprise-only.txt": b"tenant"},
    )
    contract = await _seed(store, name="he-tong", owner=0, description="审阅合同", extra={"note.txt": b"contract"})
    await _seed(store, name="ting-yong", owner=USER, description="已停用", enabled=False, extra={"who.txt": b"off"})
    await _seed(store, name="secret", owner=OTHER, description="别人的", extra={"who.txt": b"secret"})
    removed = await _seed(store, name="yi-shan", owner=USER, description="待删除", extra={"who.txt": b"gone"})
    with bypass_tenant_filter():
        await LinsightSkillDao.delete_owned(removed.id, owner_user_id=USER)

    def backend() -> _CacheBackend:
        slot = tmp_path / f"ws-{len(list(tmp_path.glob('ws-*')))}"
        return _CacheBackend(slot)

    return SimpleNamespace(store=store, backend=backend, personal=personal, enterprise=enterprise, contract=contract)


class TestCandidateCopy:
    async def test_new_task_copies_each_candidate_bundle(self, env):
        backend = env.backend()
        session = SimpleNamespace(skills=["he-tong"], skill_snapshot=None)
        result = await materialize_session_skills(
            backend, TENANT, session.skills, store=env.store, user_id=USER, session=session
        )

        assert result.copied == ["he-tong", "pdf"]
        pdf_md = (backend.file_dir / "skills" / "pdf" / "SKILL.md").read_bytes()
        assert pdf_md == _skill_md("pdf", "个人用途")
        assert (backend.file_dir / "skills" / "pdf" / "who.txt").read_bytes() == b"personal"
        assert not (backend.file_dir / "skills" / "pdf" / "enterprise-only.txt").exists()
        assert (backend.file_dir / "skills" / "he-tong" / "note.txt").read_bytes() == b"contract"
        assert not (backend.file_dir / "skills" / "ting-yong").exists()
        assert not (backend.file_dir / "skills" / "secret").exists()
        assert not (backend.file_dir / "skills" / "yi-shan").exists()
        by_name = {entry["name"]: entry for entry in session.skill_snapshot}
        assert by_name["pdf"] == {
            "name": "pdf",
            "skill_id": env.personal.id,
            "owner_user_id": USER,
            "content_hash": env.personal.content_hash,
        }
        assert by_name["he-tong"]["skill_id"] == env.contract.id
        assert by_name["he-tong"]["owner_user_id"] == 0
        # Name-only requests keep the names the client sent.
        assert session.skills == ["he-tong"]

    async def test_enterprise_skill_id_resolves_to_personal_directory(self, env):
        backend = env.backend()
        session = SimpleNamespace(
            skills=["stale"],
            skill_snapshot=pending_skill_snapshot([env.enterprise.id]),
        )
        await materialize_session_skills(
            backend,
            TENANT,
            session.skills,
            store=env.store,
            user_id=USER,
            skill_snapshot=session.skill_snapshot,
            session=session,
        )
        assert session.skills == ["pdf"]
        pdf = next(entry for entry in session.skill_snapshot if entry["name"] == "pdf")
        assert pdf["skill_id"] == env.personal.id
        assert pdf["owner_user_id"] == USER

    async def test_resume_does_not_mix_the_enterprise_bundle(self, env):
        backend = env.backend()
        first = SimpleNamespace(skills=["pdf"], skill_snapshot=None)
        await materialize_session_skills(backend, TENANT, first.skills, store=env.store, user_id=USER, session=first)
        env.personal.enabled = False
        with bypass_tenant_filter():
            await LinsightSkillDao.update(env.personal)
        uploaded_before = len(backend.uploaded)
        await materialize_session_skills(
            backend,
            TENANT,
            first.skills,
            store=env.store,
            user_id=USER,
            skill_snapshot=first.skill_snapshot,
            session=first,
        )
        assert (backend.file_dir / "skills" / "pdf" / "who.txt").read_bytes() == b"personal"
        assert not (backend.file_dir / "skills" / "pdf" / "enterprise-only.txt").exists()
        assert len(backend.uploaded) == uploaded_before
        assert next(entry["skill_id"] for entry in first.skill_snapshot if entry["name"] == "pdf") == env.personal.id

    async def test_disabled_personal_skill_is_absent_on_a_new_task(self, env):
        env.personal.enabled = False
        with bypass_tenant_filter():
            await LinsightSkillDao.update(env.personal)
        backend = env.backend()
        result = await materialize_session_skills(backend, TENANT, None, store=env.store, user_id=USER)
        assert "pdf" in result.copied
        assert (backend.file_dir / "skills" / "pdf" / "who.txt").read_bytes() == b"enterprise"
        assert "ting-yong" not in result.copied


class TestFileListOrder:
    async def test_file_list_sees_the_bundle_and_keeps_the_size_ceiling(self, env, monkeypatch):
        assert SIZE_AUTOPUSH == 5 * 1024 * 1024
        backend = env.backend()
        await materialize_session_skills(backend, TENANT, ["pdf"], store=env.store, user_id=USER)
        listed = {entry.path for entry in build_e2b_file_list(str(backend.file_dir))}
        assert any(path.endswith("skills/pdf/SKILL.md") or path.endswith("skills\\pdf\\SKILL.md") for path in listed)

        (backend.file_dir / "skills" / "pdf" / "ok.txt").write_bytes(b"ok")
        (backend.file_dir / "skills" / "pdf" / "big.bin").write_bytes(b"x" * 8)
        import bisheng.linsight.domain.services.code_tool_config as code_tool_config

        monkeypatch.setattr(code_tool_config, "SIZE_AUTOPUSH", 4)
        listed_after = {entry.path for entry in build_e2b_file_list(str(backend.file_dir))}
        assert any(path.endswith("ok.txt") for path in listed_after)
        assert all("big.bin" not in path for path in listed_after)

    def test_copy_runs_before_the_code_interpreter_snapshot(self):
        source = _TASK_EXEC.read_text()
        for name in ("_execute_workflow", "_resume_workflow", "_continue_workflow"):
            body = _method_body(source, name)
            assert body.index("_provision_session_skills") < body.index("_generate_tools")
        assert "_provision_session_skills" in _method_body(source, "_create_agent")
        assert "materialize_session_skills" in _method_body(source, "_provision_session_skills")

    def test_submit_accepts_skill_ids_without_requiring_them(self):
        named = LinsightQuestionSubmitSchema(question="q", skills=["pdf"])
        assert named.skill_ids is None
        assert named.skills == ["pdf"]
        chosen = LinsightQuestionSubmitSchema(question="q", skill_ids=[7])
        assert pending_skill_snapshot(chosen.skill_ids) == [{"pending_skill_ids": [7]}]
        assert pending_skill_snapshot(None) is None

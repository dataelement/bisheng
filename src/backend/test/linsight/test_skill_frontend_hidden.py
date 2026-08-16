"""F047 — frontend-hidden skills: hidden from the picker, force-dispatched in runs.

DAO layer runs against real sqlite SQL (mirrors test_skill_dao); the
provisioning force-include reuses the test_skill_provisioning harness style.

AC coverage: AC-02/03/04 (hide auto-enables atomically, unhide keeps enabled,
disable still allowed), AC-05 (selectable filter), AC-08/09 (force-include incl.
empty selection; disabled never dispatches), AC-11 (tenant-scoped writes).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

import bisheng.linsight.domain.models.linsight_skill as model_module
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, LinsightSkillDao
from bisheng.linsight.domain.services import skill_provisioning
from bisheng.linsight.domain.services.skill_provisioning import materialize_session_skills
from bisheng.linsight.domain.services.skill_store import SkillStore

TENANT = 1
OTHER_TENANT = 2


def _skill(
    name: str,
    *,
    enabled: bool = True,
    frontend_hidden: bool = False,
    tenant_id: int = TENANT,
) -> LinsightSkill:
    return LinsightSkill(
        tenant_id=tenant_id,
        name=name,
        display_name=name,
        description=f"desc of {name}",
        enabled=enabled,
        frontend_hidden=frontend_hidden,
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
    token = set_current_tenant_id(TENANT)
    yield LinsightSkillDao
    # Reset the ContextVar — a leaked tenant id poisons suites that run later
    # in the same worker (they may expect an unset context).
    from bisheng.core.context.tenant import current_tenant_id

    current_tenant_id.reset(token)
    await engine.dispose()


class TestDao:
    async def test_hide_auto_enables_in_same_update(self, dao):
        await dao.create(_skill("docx", enabled=False))
        assert await dao.set_frontend_hidden("docx", True) is True
        row = await dao.get_by_name("docx")
        assert bool(row.frontend_hidden) is True
        assert bool(row.enabled) is True  # AC-02: one save, no hidden-but-disabled transition

    async def test_unhide_keeps_enabled_untouched(self, dao):
        await dao.create(_skill("docx", enabled=True, frontend_hidden=True))
        assert await dao.set_frontend_hidden("docx", False) is True
        row = await dao.get_by_name("docx")
        assert bool(row.frontend_hidden) is False
        assert bool(row.enabled) is True  # AC-04

    async def test_hidden_skill_can_still_be_disabled(self, dao):
        await dao.create(_skill("docx", enabled=True, frontend_hidden=True))
        assert await dao.set_enabled("docx", False) is True
        row = await dao.get_by_name("docx")
        assert bool(row.enabled) is False and bool(row.frontend_hidden) is True  # AC-03

    async def test_hidden_write_is_tenant_scoped(self, dao):
        # Insert the other tenant's row under ITS context (a leaked global
        # tenant listener from earlier suites chokes on cross-context inserts),
        # then flip back: the same-named foreign row must not match the
        # explicitly tenant-scoped UPDATE (AC-11 — bulk-UPDATE injection gap,
        # same pitfall as set_enabled).
        from bisheng.core.context.tenant import current_tenant_id

        token = set_current_tenant_id(OTHER_TENANT)
        try:
            await dao.create(_skill("docx", tenant_id=OTHER_TENANT))
        finally:
            current_tenant_id.reset(token)
        assert await dao.set_frontend_hidden("docx", True) is False

    async def test_list_enabled_include_hidden_switch(self, dao):
        await dao.create(_skill("visible"))
        await dao.create(_skill("hidden", frontend_hidden=True))
        await dao.create(_skill("off", enabled=False, frontend_hidden=False))
        all_enabled = {s.name for s in await dao.list_enabled()}
        picker = {s.name for s in await dao.list_enabled(include_hidden=False)}
        assert all_enabled == {"visible", "hidden"}
        assert picker == {"visible"}  # AC-05


# ---------------------------------------------------------------------------
# Provisioning force-include (test_skill_provisioning harness style)
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, path: str, error: str | None = None):
        self.path = path
        self.error = error


class _CacheBackend:
    def __init__(self, file_dir: Path):
        self.file_dir = Path(file_dir)
        self.uploaded: list[str] = []

    async def aupload_files(self, files):
        out = []
        for raw_path, data in files:
            rel = raw_path.lstrip("/")
            target = self.file_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            self.uploaded.append(raw_path)
            out.append(_Resp("/" + rel))
        return out


def _write_skill(base: Path, name: str) -> None:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n\n# {name}\n", encoding="utf-8")


class _Row:
    def __init__(self, name: str, frontend_hidden: bool = False):
        self.name = name
        self.frontend_hidden = frontend_hidden


def _patch_enabled(monkeypatch, rows: list[_Row]) -> None:
    async def _fake_list_enabled(**_kwargs):
        return rows

    monkeypatch.setattr(skill_provisioning.LinsightSkillDao, "list_enabled", _fake_list_enabled)


@pytest.fixture
def store(tmp_path) -> SkillStore:
    s = SkillStore(root=tmp_path / "skills_root")
    for name in ("docx", "pptx", "visible-skill"):
        _write_skill(s.tenant_dir(TENANT), name)
    return s


@pytest.fixture
def backend(tmp_path) -> _CacheBackend:
    return _CacheBackend(tmp_path / "workspace_cache")


class TestForceInclude:
    async def test_hidden_enabled_forced_even_with_empty_selection(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, [_Row("docx", True), _Row("visible-skill")])
        for selected in (None, []):
            backend.uploaded.clear()
            copied = await materialize_session_skills(backend, TENANT, selected, store=store)
            assert copied == ["docx"]  # AC-08: forced despite nothing picked

    async def test_forced_set_is_added_on_top_of_selection(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, [_Row("docx", True), _Row("pptx", True), _Row("visible-skill")])
        copied = await materialize_session_skills(backend, TENANT, ["visible-skill"], store=store)
        assert set(copied) == {"docx", "pptx", "visible-skill"}

    async def test_disabled_hidden_skill_never_dispatched(self, monkeypatch, store, backend):
        # A disabled skill is absent from list_enabled regardless of the hidden
        # flag — the forced set is hidden ∩ enabled by construction (AC-09).
        _patch_enabled(monkeypatch, [_Row("visible-skill")])
        copied = await materialize_session_skills(backend, TENANT, None, store=store)
        assert copied == []

    async def test_user_picked_names_still_gated_by_enabled(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, [_Row("docx", True)])
        copied = await materialize_session_skills(backend, TENANT, ["pptx"], store=store)
        assert copied == ["docx"]  # picked-but-disabled dropped; forced kept

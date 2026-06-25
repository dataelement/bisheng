"""F035 Fork X — skill copy-time gate + workspace enumeration loop.

``materialize_session_skills`` is the whitelist gate that replaced the dormant
``TenantSkillsMiddleware`` runtime filter: it copies only the
``governance-enabled ∩ user-selected`` bundles into the session workspace
``/skills/`` subtree. These tests pin the C3 contract semantics (moved here from
``test_skill_middleware``):

- ``selected=["a"]``  → only governance-enabled selected names copied;
- ``selected=[]``     → nothing copied (UI disabled all);
- ``selected=None``   → every enabled skill copied (non-UI fallback);
- a DB-disabled skill is never copied even if selected;
- bundle bytes (incl. binary assets) are copied losslessly;
- the on-disk source is tenant-scoped (cross-tenant read yields nothing).

The final test runs the full loop: copy → real deepagents ``SkillsMiddleware``
enumerates the subtree → the injected path is the one the workspace ``read_file``
would resolve back to (``normalize_workspace_path`` closes the cross-backend loop).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bisheng.linsight.domain.services import skill_provisioning
from bisheng.linsight.domain.services.skill_provisioning import WORKSPACE_SKILLS_DIR, materialize_session_skills
from bisheng.linsight.domain.services.skill_store import SkillStore

TENANT = 1
OTHER_TENANT = 2

# A real PNG header — invalid UTF-8, so read_text(errors="replace") would corrupt it.
BINARY_ASSET = b"\x89PNG\r\n\x1a\n\x00\x01\xff\xfe\xfd\x00template"


def _write_skill(base: Path, name: str, *, assets: dict[str, bytes] | None = None) -> None:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: desc of {name}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    for rel, data in (assets or {}).items():
        target = d / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


class _Resp:
    def __init__(self, path: str, error: str | None = None):
        self.path = path
        self.error = error


class _CacheBackend:
    """Minimal WorkspaceBackend stand-in: aupload_files write-throughs to a dir.

    Mirrors ``WorkspaceBackend._cache_write`` (strip leading ``/``, write bytes),
    so a FilesystemBackend rooted at ``file_dir`` sees exactly what the real
    write-through cache would after the copy.
    """

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


@pytest.fixture
def store(tmp_path) -> SkillStore:
    s = SkillStore(root=tmp_path / "skills_root")
    _write_skill(s.tenant_dir(TENANT), "biao-shu-zhuan-xie")
    _write_skill(s.tenant_dir(TENANT), "he-tong-shen-yue")
    _write_skill(s.tenant_dir(TENANT), "ting-yong-ji-neng")  # exists on disk but DB-disabled
    return s


@pytest.fixture
def backend(tmp_path) -> _CacheBackend:
    return _CacheBackend(tmp_path / "workspace_cache")


class _EnabledSkill:
    """Stand-in for a LinsightSkill row (only ``.name`` is read)."""

    def __init__(self, name: str):
        self.name = name


def _patch_enabled(monkeypatch, names: set[str]) -> None:
    async def _fake_list_enabled():
        return [_EnabledSkill(n) for n in names]

    monkeypatch.setattr(skill_provisioning.LinsightSkillDao, "list_enabled", _fake_list_enabled)


ENABLED = {"biao-shu-zhuan-xie", "he-tong-shen-yue"}  # ting-yong-ji-neng disabled in DB


def _copied_rel_paths(backend: _CacheBackend) -> set[str]:
    return set(backend.uploaded)


class TestGate:
    async def test_selected_subset_copies_only_those(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED)
        copied = await materialize_session_skills(backend, TENANT, ["biao-shu-zhuan-xie"], store=store)
        assert copied == ["biao-shu-zhuan-xie"]
        assert _copied_rel_paths(backend) == {"/skills/biao-shu-zhuan-xie/SKILL.md"}

    async def test_empty_selection_copies_nothing(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED)
        copied = await materialize_session_skills(backend, TENANT, [], store=store)
        assert copied == []
        assert backend.uploaded == []

    async def test_none_selection_copies_all_enabled(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED)
        copied = await materialize_session_skills(backend, TENANT, None, store=store)
        assert copied == sorted(ENABLED)
        assert _copied_rel_paths(backend) == {
            "/skills/biao-shu-zhuan-xie/SKILL.md",
            "/skills/he-tong-shen-yue/SKILL.md",
        }

    async def test_db_disabled_skill_never_copied_even_if_selected(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED)
        copied = await materialize_session_skills(
            backend, TENANT, ["ting-yong-ji-neng", "biao-shu-zhuan-xie"], store=store
        )
        assert copied == ["biao-shu-zhuan-xie"]

    async def test_unknown_selected_name_ignored(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED)
        copied = await materialize_session_skills(backend, TENANT, ["does-not-exist"], store=store)
        assert copied == []


class TestByteFidelity:
    async def test_binary_asset_copied_losslessly(self, monkeypatch, tmp_path, backend):
        store = SkillStore(root=tmp_path / "skills_root")
        _write_skill(store.tenant_dir(TENANT), "with-asset", assets={"templates/logo.png": BINARY_ASSET})
        _patch_enabled(monkeypatch, {"with-asset"})

        copied = await materialize_session_skills(backend, TENANT, ["with-asset"], store=store)
        assert copied == ["with-asset"]
        # The binary asset round-trips byte-identical (read_bytes, not lossy read_text).
        cached = backend.file_dir / "skills" / "with-asset" / "templates" / "logo.png"
        assert cached.read_bytes() == BINARY_ASSET


class TestCrossTenant:
    async def test_other_tenant_cannot_read_disk_bundle(self, monkeypatch, store, backend):
        # DAO gate is tenant-scoped in production (strict_tenant_filter); here even if
        # the name were "enabled", the on-disk source path is keyed by tenant_id, so a
        # different tenant resolves an empty bundle and copies nothing.
        _patch_enabled(monkeypatch, {"biao-shu-zhuan-xie"})
        copied = await materialize_session_skills(backend, OTHER_TENANT, ["biao-shu-zhuan-xie"], store=store)
        assert copied == []
        assert backend.uploaded == []


class TestEnumerationLoop:
    async def test_copied_skill_is_enumerated_and_path_resolves(self, monkeypatch, store, backend):
        """Full Fork X loop: copy → real SkillsMiddleware enumerates → path consistency."""
        from deepagents.backends.filesystem import FilesystemBackend
        from deepagents.middleware.skills import SkillsMiddleware

        from bisheng.linsight.domain.services.workspace_backend import normalize_workspace_path

        _patch_enabled(monkeypatch, ENABLED)
        await materialize_session_skills(backend, TENANT, ["biao-shu-zhuan-xie"], store=store)

        # Enumerate via a FilesystemBackend over the same cache dir the copy wrote to —
        # this is exactly what agent_factory attaches when skills_present is True.
        mw = SkillsMiddleware(
            backend=FilesystemBackend(root_dir=str(backend.file_dir), virtual_mode=True),
            sources=[(f"/{WORKSPACE_SKILLS_DIR}/", "Skills")],
        )
        update = mw.before_agent({}, MagicMock(), {"configurable": {}})
        skills = {s["name"]: s for s in update["skills_metadata"]}
        assert "biao-shu-zhuan-xie" in skills

        injected_path = skills["biao-shu-zhuan-xie"]["path"]
        # The path the model is told to read_file is the same one the workspace
        # backend resolves back to the copied bundle (cross-backend loop closed).
        assert normalize_workspace_path(injected_path) == "skills/biao-shu-zhuan-xie/SKILL.md"

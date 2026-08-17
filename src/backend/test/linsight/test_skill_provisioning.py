"""F035 Fork X — skill copy-time gate + workspace enumeration loop.

``materialize_session_skills`` is the whitelist gate that replaced the dormant
``TenantSkillsMiddleware`` runtime filter: it copies only the
``governance-enabled ∩ user-selected`` bundles into the session workspace
``/skills/`` subtree. These tests pin the C3 contract semantics (moved here from
``test_skill_middleware``):

- ``selected=["a"]``  → only governance-enabled selected names copied;
- ``selected=[]``     → nothing copied (UI disabled all);
- ``selected=None``   → nothing copied (``None ≡ []``; skills are strictly opt-in);
- a DB-disabled skill is never copied even if selected;
- bundle bytes (incl. binary assets) are copied losslessly;
- the on-disk source is tenant-scoped (cross-tenant read yields nothing).

The final test runs the full loop: copy → real deepagents ``SkillsMiddleware``
enumerates the subtree → the injected path is the one the workspace ``read_file``
would resolve back to (``normalize_workspace_path`` closes the cross-backend loop).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bisheng.linsight.domain.services import skill_provisioning
from bisheng.linsight.domain.services.skill_provisioning import WORKSPACE_SKILLS_DIR, materialize_session_skills
from bisheng.linsight.domain.services.skill_store import SkillStore
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 1
OTHER_TENANT = 2

# A real PNG header — invalid UTF-8, so read_text(errors="replace") would corrupt it.
BINARY_ASSET = b"\x89PNG\r\n\x1a\n\x00\x01\xff\xfe\xfd\x00template"


def _write_skill(store: SkillStore, tenant_id: int, name: str, *, assets: dict[str, bytes] | None = None) -> str:
    """Seed a bundle through the store's own writer; returns its content hash.

    Goes through ``write_bundle`` rather than poking storage directly, so these
    tests keep exercising the real persistence path. The hash is also recorded on
    the store so ``_patch_enabled`` can hand it back the way a DB row would.
    """
    files: dict[str, bytes] = {
        "SKILL.md": f"---\nname: {name}\ndescription: desc of {name}\n---\n\n# {name}\n".encode(),
    }
    files.update(assets or {})
    ref = store.write_bundle(tenant_id, name, files)
    if not hasattr(store, "written_hashes"):
        store.written_hashes = {}
    store.written_hashes[name] = ref.content_hash
    return ref.content_hash


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
    s = SkillStore(root=tmp_path / "skills_root", minio=FakeMinioStorage())
    _write_skill(s, TENANT, "biao-shu-zhuan-xie")
    _write_skill(s, TENANT, "he-tong-shen-yue")
    _write_skill(s, TENANT, "ting-yong-ji-neng")  # stored, but DB-disabled
    return s


@pytest.fixture
def backend(tmp_path) -> _CacheBackend:
    return _CacheBackend(tmp_path / "workspace_cache")


class _EnabledSkill:
    """Stand-in for a LinsightSkill row (``.name`` + the pointer to its bundle)."""

    def __init__(self, name: str, content_hash: str = ""):
        self.name = name
        self.content_hash = content_hash


def _patch_enabled(monkeypatch, names: set[str], store: SkillStore | None = None) -> None:
    """Fake the governance query, resolving each name's stored content hash.

    Provisioning locates a bundle by the hash on the row, so the stub has to carry
    the same one the store wrote — exactly like the real DAO would.
    """
    hashes = dict(getattr(store, "written_hashes", {})) if store is not None else {}

    async def _fake_list_enabled():
        return [_EnabledSkill(n, hashes.get(n, "")) for n in names]

    monkeypatch.setattr(skill_provisioning.LinsightSkillDao, "list_enabled", _fake_list_enabled)


ENABLED = {"biao-shu-zhuan-xie", "he-tong-shen-yue"}  # ting-yong-ji-neng disabled in DB


def _copied_rel_paths(backend: _CacheBackend) -> set[str]:
    return set(backend.uploaded)


class TestGate:
    async def test_selected_subset_copies_only_those(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED, store)
        result = await materialize_session_skills(backend, TENANT, ["biao-shu-zhuan-xie"], store=store)
        assert result.copied == ["biao-shu-zhuan-xie"]
        assert _copied_rel_paths(backend) == {"/skills/biao-shu-zhuan-xie/SKILL.md"}

    async def test_empty_selection_copies_nothing(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED, store)
        result = await materialize_session_skills(backend, TENANT, [], store=store)
        assert result.copied == []
        assert backend.uploaded == []

    async def test_none_selection_copies_nothing(self, monkeypatch, store, backend):
        # None (field absent) is treated identically to [] — no skills this run.
        # Regression guard: None used to mean "copy every enabled skill", which
        # silently loaded ALL skills for any request that omitted the field
        # (stale/cached client, non-UI caller, legacy row), defeating the picker.
        _patch_enabled(monkeypatch, ENABLED, store)
        result = await materialize_session_skills(backend, TENANT, None, store=store)
        assert result.copied == []
        assert backend.uploaded == []

    async def test_db_disabled_skill_never_copied_even_if_selected(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED, store)
        result = await materialize_session_skills(
            backend, TENANT, ["ting-yong-ji-neng", "biao-shu-zhuan-xie"], store=store
        )
        assert result.copied == ["biao-shu-zhuan-xie"]

    async def test_unknown_selected_name_ignored(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED, store)
        result = await materialize_session_skills(backend, TENANT, ["does-not-exist"], store=store)
        assert result.copied == []


class TestByteFidelity:
    async def test_binary_asset_copied_losslessly(self, monkeypatch, tmp_path, backend):
        store = SkillStore(root=tmp_path / "skills_root", minio=FakeMinioStorage())
        _write_skill(store, TENANT, "with-asset", assets={"templates/logo.png": BINARY_ASSET})
        _patch_enabled(monkeypatch, {"with-asset"}, store)

        result = await materialize_session_skills(backend, TENANT, ["with-asset"], store=store)
        assert result.copied == ["with-asset"]
        # The binary asset round-trips byte-identical (read_bytes, not lossy read_text).
        cached = backend.file_dir / "skills" / "with-asset" / "templates" / "logo.png"
        assert cached.read_bytes() == BINARY_ASSET


class TestCrossTenant:
    async def test_other_tenant_cannot_read_disk_bundle(self, monkeypatch, store, backend):
        # DAO gate is tenant-scoped in production (strict_tenant_filter); here even if
        # the name were "enabled", the bundle's object key is scoped by tenant_id, so a
        # different tenant resolves nothing and copies nothing.
        _patch_enabled(monkeypatch, {"biao-shu-zhuan-xie"}, store)
        result = await materialize_session_skills(backend, OTHER_TENANT, ["biao-shu-zhuan-xie"], store=store)
        assert result.copied == []
        assert backend.uploaded == []


class TestAcrossNodes:
    """The defect this migration exists to fix, reproduced at unit scale.

    Two SkillStore instances with *disjoint* local cache roots stand in for two
    hosts. Under the previous local-disk storage the second one saw an empty
    directory and skipped the skill; sharing only the object store must now be
    enough.
    """

    async def test_a_worker_that_never_saw_the_upload_still_gets_the_skill(self, monkeypatch, tmp_path, backend, store):
        # Same object storage, a cache root that has never held this bundle.
        other_node = SkillStore(root=tmp_path / "worker-node", minio=store.minio)
        other_node.written_hashes = store.written_hashes
        _patch_enabled(monkeypatch, ENABLED, store)

        result = await materialize_session_skills(backend, TENANT, ["biao-shu-zhuan-xie"], store=other_node)

        assert result.copied == ["biao-shu-zhuan-xie"]
        assert (backend.file_dir / "skills" / "biao-shu-zhuan-xie" / "SKILL.md").exists()


class TestFailureIsReported:
    """A skill the user picked but that cannot load must not vanish silently.

    This is the failure mode the object-storage migration exists to kill: under
    the old local-disk layout a worker on another host logged one warning and ran
    the task without the skill, which is indistinguishable from "not selected".
    """

    async def test_unreachable_bundle_is_reported_not_swallowed(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED, store)
        # The row still points at a bundle, but the object is gone.
        store.minio.store.clear()
        shutil.rmtree(store.root)

        result = await materialize_session_skills(backend, TENANT, ["biao-shu-zhuan-xie"], store=store)

        assert result.copied == []
        assert result.failed == ["biao-shu-zhuan-xie"]
        assert backend.uploaded == []

    async def test_one_broken_skill_does_not_block_a_working_one(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED, store)
        broken_key = store.object_key(TENANT, "he-tong-shen-yue", store.written_hashes["he-tong-shen-yue"])
        store.minio.store.pop((store.minio.bucket, broken_key))
        shutil.rmtree(store.cache_dir(TENANT, "he-tong-shen-yue", store.written_hashes["he-tong-shen-yue"]))

        result = await materialize_session_skills(
            backend, TENANT, ["biao-shu-zhuan-xie", "he-tong-shen-yue"], store=store
        )

        assert result.copied == ["biao-shu-zhuan-xie"]
        assert result.failed == ["he-tong-shen-yue"]

    async def test_upload_error_counts_as_failure(self, monkeypatch, store, backend):
        _patch_enabled(monkeypatch, ENABLED, store)

        async def _failing_upload(files):
            return [_Resp(path, error="disk full") for path, _ in files]

        monkeypatch.setattr(backend, "aupload_files", _failing_upload)
        result = await materialize_session_skills(backend, TENANT, ["biao-shu-zhuan-xie"], store=store)
        assert (result.copied, result.failed) == ([], ["biao-shu-zhuan-xie"])


class TestEnumerationLoop:
    async def test_copied_skill_is_enumerated_and_path_resolves(self, monkeypatch, store, backend):
        """Full Fork X loop: copy → real SkillsMiddleware enumerates → path consistency."""
        from deepagents.backends.filesystem import FilesystemBackend
        from deepagents.middleware.skills import SkillsMiddleware

        from bisheng.linsight.domain.services.workspace_backend import normalize_workspace_path

        _patch_enabled(monkeypatch, ENABLED, store)
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


class TestProvisioningLog:
    """The summary line must actually carry its arguments.

    loguru formats with ``str.format`` ({}), not printf (%s). This line used to
    use printf placeholders, so every production log read literally
    ``tenant=%s selected=%r enabled=%s -> materialized %s`` with all four values
    dropped — the one record that says which skills a run loaded was useless
    exactly when a "my skill did not trigger" report had to be diagnosed.
    """

    async def test_summary_line_renders_its_arguments(self, monkeypatch, store, backend):
        from loguru import logger

        _patch_enabled(monkeypatch, ENABLED, store)
        captured: list[str] = []
        sink_id = logger.add(captured.append, level="INFO", format="{message}")
        try:
            await materialize_session_skills(backend, TENANT, ["biao-shu-zhuan-xie"], store=store)
        finally:
            logger.remove(sink_id)

        summary = next(line for line in captured if "skill provisioning" in line)
        assert "%s" not in summary and "%r" not in summary
        assert "tenant=1" in summary
        assert "selected=['biao-shu-zhuan-xie']" in summary
        assert "materialized ['biao-shu-zhuan-xie']" in summary

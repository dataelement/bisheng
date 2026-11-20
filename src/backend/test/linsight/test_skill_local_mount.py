"""F005: skill bundles are copied into the local run directory, never into the workspace in object storage.

``WorkspaceBackend`` then serves ``skills/`` reads and listings from the session's
``skill_snapshot`` through the skill store, so a node whose local directory is
empty resolves the same files as the node that copied them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bisheng.linsight.domain.services import skill_provisioning
from bisheng.linsight.domain.services.skill_store import SkillStore
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 1
PREFIX = "workspace/conv-1"


@pytest.fixture
def store(tmp_path) -> SkillStore:
    return SkillStore(root=tmp_path / "skill-cache", minio=FakeMinioStorage())


@pytest.fixture
def bundle(store):
    files = {
        "SKILL.md": b"---\nname: demo\ndescription: demo skill\n---\n\n# demo\nSee references/rules.md\n",
        "references/rules.md": b"rule one\nrule two\n",
        "scripts/run.py": b"print('ok')\n",
        "secrets/db.txt": b"password=hunter2\n",
    }
    ref = store.write_bundle(TENANT, "demo", files)
    entry = {
        "name": "demo",
        "skill_id": 7,
        "owner_user_id": 0,
        "content_hash": ref.content_hash,
        "tenant_id": TENANT,
    }
    return entry


def _backend(tmp_path: Path, store: SkillStore, snapshot: list[dict], name: str = "run") -> WorkspaceBackend:
    workspace_minio = FakeMinioStorage()
    backend = WorkspaceBackend(minio=workspace_minio, file_dir=str(tmp_path / name), workspace_prefix=PREFIX)
    backend.skill_store = store
    backend.skill_snapshot = snapshot
    backend.skill_row_enabled = lambda _skill_id: True
    return backend


async def test_copy_writes_nothing_to_the_workspace(tmp_path, store, bundle):
    backend = _backend(tmp_path, store, [])

    ok = await skill_provisioning._copy_one(backend, store, TENANT, "demo", bundle["content_hash"], owner_user_id=0)

    assert ok
    assert (Path(backend.file_dir) / "skills/demo/references/rules.md").read_bytes() == b"rule one\nrule two\n"
    assert backend.minio.keys(PREFIX) == []


async def test_copy_is_isolated_from_the_node_cache(tmp_path, store, bundle):
    backend = _backend(tmp_path, store, [])
    await skill_provisioning._copy_one(backend, store, TENANT, "demo", bundle["content_hash"], owner_user_id=0)

    (Path(backend.file_dir) / "skills/demo/scripts/run.py").write_bytes(b"tampered")

    cached = store.cache_dir(TENANT, "demo", bundle["content_hash"]) / "scripts/run.py"
    assert cached.read_bytes() == b"print('ok')\n"


async def test_prior_snapshot_entries_are_copied_again_into_an_empty_directory(tmp_path, store, bundle, monkeypatch):
    async def _no_candidates(self, user_id):
        return []

    async def _no_records(self, available_only=True, *, candidates=None, actor=None):
        return []

    monkeypatch.setattr(
        "bisheng.linsight.domain.services.personal_skill_service.PersonalSkillService.list_candidates", _no_candidates
    )
    monkeypatch.setattr("bisheng.linsight.domain.services.user_skills.UserSkillsService.records", _no_records)
    backend = _backend(tmp_path, store, [], name="next-round")

    result = await skill_provisioning.materialize_session_skills(
        backend, TENANT, [], store=store, user_id=11, skill_snapshot=[bundle]
    )

    assert result.copied == ["demo"]
    assert (Path(backend.file_dir) / "skills/demo/SKILL.md").is_file()


def test_read_on_another_node_comes_from_the_skill_store(tmp_path, store, bundle):
    backend = _backend(tmp_path, store, [bundle], name="other-node")

    result = backend.read("/skills/demo/references/rules.md")

    assert result.error is None
    assert "rule two" in result.file_data["content"]
    assert backend.minio.keys(PREFIX) == []


def test_listing_includes_the_snapshot_bundles(tmp_path, store, bundle):
    backend = _backend(tmp_path, store, [bundle], name="other-node")

    paths = {entry["path"] for entry in backend.ls("/skills").entries}
    root_paths = {entry["path"] for entry in backend.ls("").entries}
    globbed = {entry["path"] for entry in backend.glob("skills/**/*.md").matches}

    assert "/skills/demo/SKILL.md" in paths
    assert "/skills/demo/scripts/run.py" in paths
    assert paths <= root_paths
    assert globbed >= {"/skills/demo/SKILL.md", "/skills/demo/references/rules.md"}


def test_grep_finds_text_in_a_skill_and_skips_secrets(tmp_path, store, bundle):
    backend = _backend(tmp_path, store, [bundle], name="other-node")

    found = {(m["path"], m["text"]) for m in backend.grep("rule two", path="/skills").matches}
    secret = backend.grep("hunter2", path="/skills").matches
    single = backend.grep("rule one", path="/skills/demo/references/rules.md").matches

    assert ("/skills/demo/references/rules.md", "rule two") in found
    assert secret == []
    assert [m["path"] for m in single] == ["/skills/demo/references/rules.md"]


def test_secrets_stay_unreadable_through_the_file_tools(tmp_path, store, bundle):
    backend = _backend(tmp_path, store, [bundle], name="other-node")

    result = backend.read("/skills/demo/secrets/db.txt")

    assert result.error


def test_a_path_outside_the_bundle_is_not_served(tmp_path, store, bundle):
    backend = _backend(tmp_path, store, [bundle], name="other-node")

    # The workspace path normalizer refuses traversal before any store lookup.
    with pytest.raises(ValueError):
        backend.read("/skills/demo/../../etc/passwd")
    assert backend._load_skill_file("skills/demo/../../../outside.txt") is None

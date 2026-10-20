"""F078 T09: per-session agent workspaces backed by MinIO."""

import os
from types import SimpleNamespace

import pytest

import bisheng.linsight.domain.services.skill_provisioning as provisioning
from bisheng.agent_runtime.domain.services.agent_workspace import (
    AgentWorkspace,
    WorkspaceKey,
    adelete_session_workspaces,
)
from test.linsight.fixtures.fake_minio import FakeMinioStorage

TENANT = 2


class _FakeSkillStore:
    """Serves bundle files; ``version`` lets a test change a skill's content."""

    def __init__(self):
        self.version = "v1"

    def list_files(self, tenant_id, name, content_hash, *, owner_user_id=0):
        return [{"path": "SKILL.md", "size": 1}, {"path": "scripts/run.py", "size": 1}]

    def read_bytes(self, tenant_id, name, content_hash, rel, *, owner_user_id=0):
        return f"{name}:{rel}:{self.version}".encode()


@pytest.fixture
def minio():
    return FakeMinioStorage()


@pytest.fixture
def skill_store():
    return _FakeSkillStore()


@pytest.fixture(autouse=True)
def _enabled_skills(monkeypatch):
    rows = [SimpleNamespace(name="docx", content_hash="h1"), SimpleNamespace(name="pdf", content_hash="h2")]

    async def _list_enabled():
        return rows

    monkeypatch.setattr(provisioning.LinsightSkillDao, "list_enabled", _list_enabled)


def _workspace(minio, skill_store, tmp_path, key, cache="node-a"):
    return AgentWorkspace(
        key=key,
        minio=minio,
        tenant_id=TENANT,
        cache_root=str(tmp_path / cache),
        skill_store=skill_store,
    )


def _skills(*names):
    return [SimpleNamespace(name=name) for name in names]


class TestWorkspaceKey:
    def test_formal_temp_and_once_keys(self):
        assert WorkspaceKey.formal("c1", "wf-n1").svid == "agent/c1/wf-n1"
        assert WorkspaceKey.temp("t1", "wf-n1").svid == "agent/tmp-t1/wf-n1"
        once = WorkspaceKey.once("assistant")
        assert once.svid.startswith("agent/once-")
        assert once.kind == "once"
        assert WorkspaceKey.formal("c1", "assistant").object_prefix == "workspace/agent/c1/assistant/"

    @pytest.mark.parametrize("bad", ["", "a/b", "..", "c 1"])
    def test_rejects_unsafe_parts(self, bad):
        with pytest.raises(ValueError):
            WorkspaceKey.formal(bad, "wf-n1")


class TestAgentWorkspace:
    async def test_second_run_sees_files_from_the_first(self, minio, skill_store, tmp_path):
        key = WorkspaceKey.formal("c1", "wf-n1")
        first = _workspace(minio, skill_store, tmp_path, key)
        prepared = await first.aprepare(skills=[], input_files=[])
        prepared.backend.write("/output/report.md", "draft")
        first.cleanup_local()
        assert not os.path.exists(prepared.file_dir)

        second = _workspace(minio, skill_store, tmp_path, key)
        again = await second.aprepare(skills=[], input_files=[])
        with open(os.path.join(again.file_dir, "output", "report.md"), encoding="utf-8") as f:
            assert f.read() == "draft"
        second.cleanup_local()

    async def test_another_node_with_its_own_cache_sees_the_files(self, minio, skill_store, tmp_path):
        key = WorkspaceKey.formal("c1", "wf-n1")
        first = _workspace(minio, skill_store, tmp_path, key, cache="node-a")
        prepared = await first.aprepare(skills=[], input_files=[])
        prepared.backend.write("/output/report.md", "draft")

        other = _workspace(minio, skill_store, tmp_path, key, cache="node-b")
        seen = await other.aprepare(skills=[], input_files=[])
        assert os.path.isfile(os.path.join(seen.file_dir, "output", "report.md"))

    async def test_skills_are_recopied_at_their_current_version(self, minio, skill_store, tmp_path):
        key = WorkspaceKey.formal("c1", "wf-n1")
        ws = _workspace(minio, skill_store, tmp_path, key)
        await ws.aprepare(skills=_skills("docx", "pdf"), input_files=[])
        ws.cleanup_local()

        skill_store.version = "v2"
        ws2 = _workspace(minio, skill_store, tmp_path, key)
        prepared = await ws2.aprepare(skills=_skills("docx"), input_files=[])
        with open(os.path.join(prepared.file_dir, "skills", "docx", "SKILL.md"), encoding="utf-8") as f:
            assert f.read().endswith(":v2")
        # A skill dropped from the configuration is gone from the workspace.
        assert not os.path.exists(os.path.join(prepared.file_dir, "skills", "pdf"))
        assert not minio.keys("workspace/agent/c1/wf-n1/skills/pdf/")
        assert prepared.skill_names == ["docx"]

    async def test_input_files_land_in_uploads(self, minio, skill_store, tmp_path):
        ws = _workspace(minio, skill_store, tmp_path, WorkspaceKey.formal("c1", "wf-n1"))
        prepared = await ws.aprepare(skills=[], input_files=[("../季度表.xlsx", b"xls"), ("季度表.xlsx", b"xls2")])
        uploads = sorted(os.listdir(os.path.join(prepared.file_dir, "uploads")))
        assert uploads == ["季度表(1).xlsx", "季度表.xlsx"]

    async def test_baseline_covers_hydrated_files(self, minio, skill_store, tmp_path):
        key = WorkspaceKey.formal("c1", "wf-n1")
        ws = _workspace(minio, skill_store, tmp_path, key)
        prepared = await ws.aprepare(skills=[], input_files=[])
        prepared.backend.write("/output/old.md", "old")
        ws.cleanup_local()

        ws2 = _workspace(minio, skill_store, tmp_path, key)
        again = await ws2.aprepare(skills=[], input_files=[])
        assert os.path.join(again.file_dir, "output", "old.md") in again.baseline

    async def test_runs_on_one_node_use_separate_local_dirs(self, minio, skill_store, tmp_path):
        key = WorkspaceKey.formal("c1", "wf-n1")
        a = await _workspace(minio, skill_store, tmp_path, key).aprepare(skills=[], input_files=[])
        b = await _workspace(minio, skill_store, tmp_path, key).aprepare(skills=[], input_files=[])
        assert a.file_dir != b.file_dir


class TestDeleteSession:
    async def test_deletes_every_workspace_of_the_session(self, minio, skill_store, tmp_path):
        for surface in ("wf-n1", "wf-n2"):
            ws = _workspace(minio, skill_store, tmp_path, WorkspaceKey.formal("c1", surface))
            prepared = await ws.aprepare(skills=[], input_files=[])
            prepared.backend.write("/output/a.md", "x")
        other = _workspace(minio, skill_store, tmp_path, WorkspaceKey.formal("c2", "wf-n1"))
        (await other.aprepare(skills=[], input_files=[])).backend.write("/output/a.md", "y")

        removed = await adelete_session_workspaces(minio, "c1")

        assert removed == 2
        assert minio.keys("workspace/agent/c1/") == []
        assert minio.keys("workspace/agent/c2/") == ["workspace/agent/c2/wf-n1/output/a.md"]

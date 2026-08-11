"""Code-interpreter output must be mirrored into the session workspace prefix.

Root cause of "把封面加个副标题" finding an empty workspace: the executor writes
to a LOCAL working dir that is deleted when the task ends, and never wrote to
``workspace/<svid>/``. So a code-generated deck existed only on that disk —
``ls``/``read_file`` could not see it, and the follow-up turn (a fresh svid whose
workspace seeds from the previous one's ``output/``) inherited nothing. Verified
on 114: ``workspace/475f33d7…/`` held 113 objects, ALL of them ``skills/…``, with
no ``output/`` at all, while the deck sat in ``linsight/final_result/``.

These tests cover the mirror helper and its wiring into ``run_with_dir``; no real
MinIO or subprocess is involved.
"""

from __future__ import annotations

import os

from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor


class _FakeMinio:
    """Records fput_object calls; optionally fails the first n of them."""

    def __init__(self, fail_first: int = 0):
        self.calls: list[tuple[str, str, str]] = []
        self._fail_left = fail_first

    def fput_object(self, bucket_name: str, object_name: str, file_path: str):
        if self._fail_left > 0:
            self._fail_left -= 1
            raise RuntimeError("simulated object-storage failure")
        self.calls.append((bucket_name, object_name, file_path))


def _touch(root, rel: str) -> str:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"payload")
    return path


# ---------------------------------------------------------------------------
# sync_to_workspace
# ---------------------------------------------------------------------------
def test_mirror_is_a_noop_without_a_workspace_prefix(tmp_path, monkeypatch):
    """Non-linsight callers (and E2B) never get a prefix — they must not mirror."""
    _touch(tmp_path, "output/a.txt")
    exe = LocalExecutor(minio={"public_bucket": "bisheng"})
    fake = _FakeMinio()
    monkeypatch.setattr(exe, "_minio_client", lambda: fake)

    assert exe.sync_to_workspace(str(tmp_path), ["output/a.txt"]) == 0
    assert fake.calls == []


def test_mirror_is_a_noop_without_minio_config(tmp_path):
    _touch(tmp_path, "output/a.txt")
    exe = LocalExecutor(minio=None, workspace_prefix="workspace/abc")
    assert exe.sync_to_workspace(str(tmp_path), ["output/a.txt"]) == 0


def test_mirror_puts_each_file_under_the_workspace_prefix(tmp_path, monkeypatch):
    deck = _touch(tmp_path, "output/deck.pptx")
    chart = _touch(tmp_path, "scratch/chart.png")
    exe = LocalExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix="workspace/abc123")
    fake = _FakeMinio()
    monkeypatch.setattr(exe, "_minio_client", lambda: fake)

    synced = exe.sync_to_workspace(str(tmp_path), ["output/deck.pptx", "scratch/chart.png"])

    assert synced == 2
    assert fake.calls == [
        ("bisheng", "workspace/abc123/output/deck.pptx", deck),
        ("bisheng", "workspace/abc123/scratch/chart.png", chart),
    ]


def test_mirror_skips_paths_that_are_not_files(tmp_path, monkeypatch):
    """``touched`` carries a created/modified diff; a deleted or directory entry
    must be skipped rather than blow up the run."""
    _touch(tmp_path, "output/kept.txt")
    os.makedirs(os.path.join(tmp_path, "output", "subdir"), exist_ok=True)
    exe = LocalExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix="workspace/abc")
    fake = _FakeMinio()
    monkeypatch.setattr(exe, "_minio_client", lambda: fake)

    synced = exe.sync_to_workspace(str(tmp_path), ["output/kept.txt", "output/gone.txt", "output/subdir"])

    assert synced == 1
    assert [c[1] for c in fake.calls] == ["workspace/abc/output/kept.txt"]


def test_one_failed_object_does_not_abort_the_rest(tmp_path, monkeypatch):
    """Best-effort: the local copy is still harvested, so a mirror error must
    degrade that one file, never the run."""
    _touch(tmp_path, "output/first.txt")
    second = _touch(tmp_path, "output/second.txt")
    exe = LocalExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix="workspace/abc")
    fake = _FakeMinio(fail_first=1)
    monkeypatch.setattr(exe, "_minio_client", lambda: fake)

    synced = exe.sync_to_workspace(str(tmp_path), ["output/first.txt", "output/second.txt"])

    assert synced == 1
    assert fake.calls == [("bisheng", "workspace/abc/output/second.txt", second)]


def test_client_init_failure_is_swallowed(tmp_path, monkeypatch):
    _touch(tmp_path, "output/a.txt")
    exe = LocalExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix="workspace/abc")

    def _boom():
        raise RuntimeError("cannot reach object storage")

    monkeypatch.setattr(exe, "_minio_client", _boom)
    assert exe.sync_to_workspace(str(tmp_path), ["output/a.txt"]) == 0


def test_prefix_slashes_are_normalised(tmp_path, monkeypatch):
    _touch(tmp_path, "output/a.txt")
    exe = LocalExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix="/workspace/abc/")
    fake = _FakeMinio()
    monkeypatch.setattr(exe, "_minio_client", lambda: fake)

    exe.sync_to_workspace(str(tmp_path), ["/output/a.txt"])

    assert [c[1] for c in fake.calls] == ["workspace/abc/output/a.txt"]


# ---------------------------------------------------------------------------
# run_with_dir wiring
# ---------------------------------------------------------------------------
def test_run_with_dir_mirrors_exactly_what_the_run_touched(tmp_path, monkeypatch):
    """The mirror must receive the same ``touched`` set the tmp-bucket upload does —
    i.e. this run's files, not the whole working dir."""
    _touch(tmp_path, "uploads/preexisting.xlsx")  # present BEFORE the run

    exe = LocalExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix="workspace/abc")
    exe.local_sync_path = str(tmp_path)

    def _fake_execute(code, work_dir=None, lang=None, **kwargs):
        _touch(work_dir, "output/deck.pptx")
        return 0, "saved\n", []

    monkeypatch.setattr(exe, "execute_code", _fake_execute)
    monkeypatch.setattr(exe, "upload_minio", lambda object_name, file_path: "http://tmp/x")

    seen: dict = {}
    monkeypatch.setattr(exe, "sync_to_workspace", lambda dir_path, rels: seen.setdefault("rels", list(rels)) or 0)

    exitcode, _logs, _files = exe.run_with_dir("code", dir_path=str(tmp_path), lang="python")

    assert exitcode == 0
    assert seen["rels"] == ["output/deck.pptx"]


def test_run_with_dir_does_not_mirror_on_failure(tmp_path, monkeypatch):
    """A failed run returns early; nothing it half-wrote should reach the workspace."""
    exe = LocalExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix="workspace/abc")
    exe.local_sync_path = str(tmp_path)
    monkeypatch.setattr(exe, "execute_code", lambda code, work_dir=None, lang=None, **kw: (1, "boom\n", []))

    called = {"n": 0}
    monkeypatch.setattr(exe, "sync_to_workspace", lambda *a, **kw: called.__setitem__("n", called["n"] + 1))

    exitcode, logs, _ = exe.run_with_dir("code", dir_path=str(tmp_path), lang="python")

    assert exitcode == 1
    assert "boom" in logs
    assert called["n"] == 0

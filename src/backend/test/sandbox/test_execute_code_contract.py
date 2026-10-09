"""Shared ``execute_code`` / ``run_with_dir`` harvest contract (F068 T005).

A fake ``execute_code`` is injected on a ``BaseExecutor`` subclass so this file
never starts a real runner or a real subprocess. Regression after T006:

- ``test/linsight/test_code_interpreter_log_cap.py``
- ``test/linsight/test_code_interpreter_escape_guard.py``
- ``test/linsight/test_code_interpreter_output_path.py``
- ``test/linsight/test_code_interpreter_workspace_mirror.py``
- ``test/linsight/test_code_interpreter_timeout.py``
- ``test/linsight/test_code_interpreter_root_relocation.py``
"""

from __future__ import annotations

import os
from pathlib import Path

from bisheng_langchain.gpts.tools.code_interpreter.base_executor import BaseExecutor


class _FakeHarvestExecutor(BaseExecutor):
    """Writes files from the test, then lets shared ``run_with_dir`` harvest them."""

    def __init__(self, minio: dict | None = None, **kwargs):
        super().__init__(minio or {}, **kwargs)
        self._handler = None
        self._work_dir = ""

    def run(self, code: str):
        exitcode, log, file_list = self.run_with_dir(code, dir_path=self._work_dir, lang="python")
        return {"exitcode": exitcode, "log": log, "file_list": file_list}

    def execute_code(self, code=None, timeout=None, filename=None, work_dir=None, lang="python"):
        return self._handler(work_dir, code)

    def upload_minio(self, object_name: str, file_path) -> str:
        return f"https://files/{os.path.basename(file_path)}"


def _write(root: str, rel: str, content: str) -> None:
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_success_relocates_root_file_and_lists_only_this_run(tmp_path, monkeypatch):
    work = str(tmp_path)
    _write(work, "uploads/source.txt", "preexisting")
    _write(work, "output/old.txt", "orig")

    exe = _FakeHarvestExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix="workspace/s1")
    exe._work_dir = work

    def _handler(work_dir, code):
        _write(work_dir, "report.md", "new-root")
        _write(work_dir, "output/old.txt", "changed")
        return 0, "ok\n", ""

    exe._handler = _handler

    synced: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        exe,
        "sync_to_workspace",
        lambda dir_path, rels: synced.append((dir_path, list(rels))) or len(rels),
    )

    result = exe.run("print('ok')")

    assert set(result) == {"exitcode", "log", "file_list"}
    assert result["exitcode"] == 0
    assert "ok" in result["log"]
    assert not (tmp_path / "report.md").exists()
    assert (tmp_path / "output" / "report.md").read_text() == "new-root"
    assert "report.md -> output/report.md" in result["log"]
    assert result["file_list"] == ["https://files/report.md", "https://files/old.txt"]
    assert synced and synced[0][0] == work
    rels = synced[0][1]
    assert "output/report.md" in rels or os.path.join("output", "report.md") in rels
    assert "output/old.txt" in rels or os.path.join("output", "old.txt") in rels
    assert not any(rel.endswith("source.txt") for rel in rels)


def test_nonzero_exit_keeps_stdout_and_empty_file_list(tmp_path, monkeypatch):
    exe = _FakeHarvestExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix="workspace/s1")
    exe._work_dir = str(tmp_path)

    def _handler(work_dir, code):
        _write(work_dir, "half.txt", "partial")
        return 1, "printed before fail\nTraceback (most recent call last):\n", ""

    exe._handler = _handler
    called = {"n": 0}
    monkeypatch.setattr(exe, "sync_to_workspace", lambda *a, **kw: called.__setitem__("n", called["n"] + 1))

    result = exe.run("raise SystemExit(1)")

    assert set(result) == {"exitcode", "log", "file_list"}
    assert result["exitcode"] == 1
    assert "printed before fail" in result["log"]
    assert result["file_list"] == []
    assert called["n"] == 0
    # harvest skipped, so the half-written root file is not relocated
    assert (tmp_path / "half.txt").exists()

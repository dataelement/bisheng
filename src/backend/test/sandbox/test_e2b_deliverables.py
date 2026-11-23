"""F016: E2B runs publish the files they leave under output/ as deliverables."""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import E2bCodeExecutor

ROOT = "/home/user/"


@dataclass
class _Entry:
    name: str
    path: str
    type: str
    size: int
    modified_time: float


class _Execution:
    def __init__(self, error=None):
        self.results = []
        self.logs = type("Logs", (), {"stdout": [], "stderr": []})()
        self.error = error


class _Files:
    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.mtime: dict[str, float] = {}
        self.clock = 0.0
        self.depths: list = []

    def make_dir(self, path):
        pass

    def write(self, path, data):
        self.clock += 1
        self.store[path] = data
        self.mtime[path] = self.clock

    def list(self, path, depth=1):
        self.depths.append(depth)
        entries = []
        for p in sorted(self.store):
            rel = p[len(ROOT) :]
            if rel.count("/") >= depth:
                continue
            entries.append(_Entry(rel.rsplit("/", 1)[-1], p, "file", len(self.store[p]), self.mtime[p]))
        return entries

    def read(self, path, format="bytes"):
        return self.store[path]


class _Sandbox:
    def __init__(self, writes: dict[str, bytes], error=None):
        self.files = _Files()
        self.writes = writes
        self.error = error
        self.runs = 0
        self.killed = False

    def run_code(self, code):
        self.runs += 1
        for rel, data in self.writes.items():
            self.files.write(ROOT + rel, data)
        return _Execution(self.error)

    def kill(self):
        self.killed = True


@pytest.fixture
def uploads(monkeypatch):
    seen: list[tuple[str, bytes]] = []

    def upload(self, object_name, file_path):
        with open(file_path, "rb") as fh:
            seen.append((object_name, fh.read()))
        return f"http://h/tmp-dir/{object_name}?sig"

    monkeypatch.setattr(E2bCodeExecutor, "upload_minio", upload)
    return seen


def _executor(sandbox: _Sandbox, collect: bool = True) -> E2bCodeExecutor:
    exe = E2bCodeExecutor(minio={"endpoint": "x"}, api_key="k")
    exe.sandbox = sandbox
    exe.keep_sandbox = True
    exe.collect_deliverables = collect
    return exe


def test_nested_output_file_is_published(uploads):
    sandbox = _Sandbox({"output/reports/weather.docx": b"DOCX"})
    exe = _executor(sandbox)

    result = exe.run("save()")

    assert sandbox.files.depths and min(sandbox.files.depths) > 1
    (entry,) = exe.published_deliverables
    assert entry["path"] == "output/reports/weather.docx"
    assert entry["name"] == "weather.docx"
    assert entry["size"] == 4
    assert result["file_list"] == [entry["url"]]
    ((object_name, content),) = uploads
    assert object_name.endswith(".docx")
    assert content == b"DOCX"


def test_rewritten_file_is_published_again(uploads):
    sandbox = _Sandbox({"output/a.xlsx": b"v1"})
    exe = _executor(sandbox)
    exe.run("save()")
    sandbox.writes = {"output/a.xlsx": b"v2-longer"}

    exe.run("save()")

    assert [c for _, c in uploads] == [b"v1", b"v2-longer"]
    assert [e["size"] for e in exe.published_deliverables] == [2, 9]


def test_unchanged_file_is_not_republished(uploads):
    sandbox = _Sandbox({"output/a.txt": b"x"})
    exe = _executor(sandbox)
    exe.run("save()")
    sandbox.writes = {}

    exe.run("print(1)")

    assert len(uploads) == 1


def test_scratch_and_hidden_files_are_not_published(uploads):
    sandbox = _Sandbox({"scratch/tmp.csv": b"t", ".cache/x.bin": b"c", "output/r.pdf": b"p"})
    exe = _executor(sandbox)

    result = exe.run("save()")

    assert [e["path"] for e in exe.published_deliverables] == ["output/r.pdf"]
    assert {f["path"] for f in result["new_files"]} == {"scratch/tmp.csv", "output/r.pdf"}


def test_failed_run_publishes_nothing(uploads):
    sandbox = _Sandbox({"output/half.docx": b"h"}, error="Traceback")
    exe = _executor(sandbox)

    exe.run("boom()")

    assert uploads == []
    assert exe.published_deliverables == []


def test_collection_off_uploads_nothing(uploads):
    sandbox = _Sandbox({"output/a.docx": b"a"})
    exe = _executor(sandbox, collect=False)

    result = exe.run("save()")

    assert uploads == []
    assert result["file_list"] == []
    assert result["new_files"] == [{"path": "output/a.docx", "size": 1, "is_product": True}]


def test_kept_sandbox_survives_calls_until_close(uploads):
    sandbox = _Sandbox({"output/a.docx": b"a"})
    exe = _executor(sandbox)

    exe.run("save()")
    exe.run("check()")

    assert exe.sandbox is sandbox and not sandbox.killed
    exe.close()
    assert sandbox.killed and exe.sandbox is None


def test_temp_copy_is_removed(uploads, monkeypatch):
    created: list[str] = []
    real_mkstemp = __import__("tempfile").mkstemp

    def mkstemp(**kwargs):
        fd, path = real_mkstemp(**kwargs)
        created.append(path)
        return fd, path

    monkeypatch.setattr("bisheng_langchain.gpts.tools.code_interpreter.e2b_executor.tempfile.mkstemp", mkstemp)
    exe = _executor(_Sandbox({"output/a.docx": b"a"}))

    exe.run("save()")

    assert created and not any(os.path.exists(p) for p in created)

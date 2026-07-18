"""TC-4: E2B sandbox copy-in / copy-out for the F035 workspace integration.

The sandbox cannot reach MinIO; the worker mediates all file transfer
(design §9.3.9). These tests use a ``FakeSandbox`` mimicking the e2b
``sandbox.files`` API and a tiny in-memory workspace backend; no real E2B or
MinIO is involved.

Coverage:
  - copy-in: ``run(code, required_files=[])`` new param; small files
    auto-pushed (delta by md5, hit -> skipped); large files must be declared
    in ``required_files``; undeclared large files surface a hint.
  - copy-out: full-tree scan finds new files vs a pre-run snapshot; result
    appends ``new_files: [{path, size, is_product}]`` (``output/`` -> product);
    products are written back through the workspace backend.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import (
    SIZE_AUTOPUSH,
    SIZE_INLINE,
    E2bCodeExecutor,
)


# ---------------------------------------------------------------------------
# Fake e2b sandbox
# ---------------------------------------------------------------------------
@dataclass
class FakeEntry:
    name: str
    path: str
    type: str  # "file" | "dir"
    modified_time: float = 0.0


class FakeExecution:
    def __init__(self):
        self.results = []

        class _Logs:
            stdout = ""
            stderr = ""

        self.logs = _Logs()
        self.error = None


class FakeFiles:
    def __init__(self):
        # path -> bytes
        self.store: dict[str, bytes] = {}
        self.mtime: dict[str, float] = {}

    def make_dir(self, path):
        pass

    def write(self, *args):
        # supports write(list[{path,data}]) or write(path, data)
        if len(args) == 1 and isinstance(args[0], list):
            for item in args[0]:
                self.store[item["path"]] = item["data"]
                self.mtime[item["path"]] = time.time()
        else:
            path, data = args
            self.store[path] = data if isinstance(data, bytes) else bytes(data)
            self.mtime[path] = time.time()

    def list(self, path):
        entries = []
        for p in sorted(self.store):
            entries.append(FakeEntry(name=p.split("/")[-1], path=p, type="file", modified_time=self.mtime.get(p, 0.0)))
        return entries

    def read(self, path, format="bytes"):
        return self.store[path]


class FakeSandbox:
    def __init__(self):
        self.files = FakeFiles()
        self.killed = False

    def run_code(self, code):
        # simulate the code writing a couple of output files
        self.files.write("/home/user/output/result.csv", b"a,b\n1,2\n")
        self.files.write("/home/user/scratch/temp.txt", b"intermediate")
        return FakeExecution()

    def kill(self):
        self.killed = True


# ---------------------------------------------------------------------------
# Tiny in-memory workspace backend (records writes)
# ---------------------------------------------------------------------------
class RecordingWorkspace:
    def __init__(self):
        self.writes: dict[str, bytes] = {}

    def write(self, path, content):
        self.writes[path.lstrip("/")] = content if isinstance(content, bytes) else content.encode()

    def read(self, path, offset=0, limit=2000):
        class R:
            error = None
            file_data = {"content": "", "encoding": "utf-8"}

        return R()


def make_executor(monkeypatch, workspace=None):
    exe = E2bCodeExecutor(minio={}, api_key="k", keep_sandbox=True)
    # inject the fake sandbox directly, bypassing real init
    exe.sandbox = FakeSandbox()
    exe.sandbox_file_cache = {}
    if workspace is not None:
        exe.workspace_backend = workspace
    return exe


# ---------------------------------------------------------------------------
# copy-out: new_files enumerated + products written to workspace
# ---------------------------------------------------------------------------
def test_copy_out_enumerates_new_files(monkeypatch):
    ws = RecordingWorkspace()
    exe = make_executor(monkeypatch, workspace=ws)
    result = exe.run("print('hi')")

    assert "new_files" in result
    paths = {f["path"]: f for f in result["new_files"]}
    # both produced files captured
    assert any("result.csv" in p for p in paths)
    assert any("temp.txt" in p for p in paths)
    # output/ prefix => is_product True; scratch/ => False
    out = next(f for p, f in paths.items() if "result.csv" in p)
    scr = next(f for p, f in paths.items() if "temp.txt" in p)
    assert out["is_product"] is True
    assert scr["is_product"] is False
    assert out["size"] > 0


def test_copy_out_writes_products_to_workspace(monkeypatch):
    ws = RecordingWorkspace()
    exe = make_executor(monkeypatch, workspace=ws)
    exe.run("print('hi')")

    # output file written under output/, scratch under scratch/
    written = ws.writes
    assert any(k.startswith("output/") and k.endswith("result.csv") for k in written)
    assert any(k.startswith("scratch/") and k.endswith("temp.txt") for k in written)


# ---------------------------------------------------------------------------
# copy-in: small files auto-pushed, large must be declared
# ---------------------------------------------------------------------------
def test_copy_in_small_file_auto_pushed(monkeypatch):
    ws = RecordingWorkspace()
    exe = make_executor(monkeypatch, workspace=ws)

    pushed = {}

    def fake_materialize():
        # working set: one small file from the workspace
        return {"uploads/doc/index.md": b"small content"}

    exe._materialize_working_set = fake_materialize  # type: ignore[attr-defined]
    exe.run("print(1)", required_files=[])

    # small file auto-pushed into sandbox
    assert any("uploads/doc/index.md" in p for p in exe.sandbox.files.store)


def test_copy_in_large_undeclared_hint(monkeypatch):
    ws = RecordingWorkspace()
    exe = make_executor(monkeypatch, workspace=ws)

    big = b"x" * (SIZE_AUTOPUSH + 10)

    def fake_materialize():
        return {"uploads/big/index.md": big}

    exe._materialize_working_set = fake_materialize  # type: ignore[attr-defined]
    result = exe.run("print(1)", required_files=[])

    # big file NOT auto-pushed; a hint is surfaced
    assert not any("uploads/big/index.md" in p for p in exe.sandbox.files.store)
    assert "required_files" in (result.get("copy_in_hint") or "")


def test_copy_in_large_declared_pushed(monkeypatch):
    ws = RecordingWorkspace()
    exe = make_executor(monkeypatch, workspace=ws)

    big = b"x" * (SIZE_AUTOPUSH + 10)

    def fake_materialize():
        return {"uploads/big/index.md": big}

    exe._materialize_working_set = fake_materialize  # type: ignore[attr-defined]
    exe.run("print(1)", required_files=["uploads/big/index.md"])

    assert any("uploads/big/index.md" in p for p in exe.sandbox.files.store)


def test_copy_in_md5_hit_skips_repush(monkeypatch):
    ws = RecordingWorkspace()
    exe = make_executor(monkeypatch, workspace=ws)

    def fake_materialize():
        return {"uploads/doc/index.md": b"same content"}

    exe._materialize_working_set = fake_materialize  # type: ignore[attr-defined]
    exe.run("print(1)", required_files=[])
    writes_count_1 = len(exe._pushed_md5)

    exe.run("print(1)", required_files=[])
    # same content -> md5 hit, not re-tracked as a new push
    assert len(exe._pushed_md5) == writes_count_1


# ---------------------------------------------------------------------------
# run() backward compatible without required_files
# ---------------------------------------------------------------------------
def test_run_without_required_files(monkeypatch):
    exe = make_executor(monkeypatch, workspace=RecordingWorkspace())
    result = exe.run("print(1)")
    assert "results" in result
    assert "new_files" in result


def test_thresholds_exposed():
    assert SIZE_AUTOPUSH > 0
    assert SIZE_INLINE > 0

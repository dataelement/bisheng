"""Retained run dirs of the isolated LocalExecutor: the parts that do not need root.

Incremental copy-in, the per-workspace registry and its release, how calls on
one workspace are serialized, and the Linsight wiring. The end-to-end runs as
a pool uid live in ``test_local_isolation_root.py``.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from types import SimpleNamespace

import pytest

from bisheng_langchain.gpts.tools.code_interpreter import local_executor as local_executor_module
from bisheng_langchain.gpts.tools.code_interpreter import local_run_registry, workspace_copy
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import TASK_ENDED_MSG, LocalExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_isolation import IsolatedOutcome, RunClosed
from bisheng_langchain.gpts.tools.code_interpreter.tool import CodeInterpreterTool

LIMIT = 1 << 30


def _write(path, data: bytes = b"x") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


# --- incremental copy-in -----------------------------------------------------


def _sync(w, r, index=None):
    return workspace_copy.sync_in(str(w), str(r), None, index or {}, LIMIT, LIMIT)


def test_sync_in_copies_only_what_changed(tmp_path) -> None:
    w, r = tmp_path / "w", tmp_path / "r"
    r.mkdir()
    _write(w / "a.txt", b"aaa")
    _write(w / "sub" / "b.txt", b"bb")

    first = _sync(w, r)
    assert first.copied_bytes == 5
    assert set(first.index) == {"a.txt", os.path.join("sub", "b.txt")}

    second = _sync(w, r, first.index)
    assert second.copied_bytes == 0
    assert second.index == first.index

    time.sleep(0.01)
    _write(w / "a.txt", b"changed")
    third = _sync(w, r, second.index)
    assert third.copied_bytes == len(b"changed")
    assert (r / "a.txt").read_bytes() == b"changed"


def test_sync_in_restores_what_the_script_changed_in_r(tmp_path) -> None:
    w, r = tmp_path / "w", tmp_path / "r"
    r.mkdir()
    _write(w / "a.txt", b"original")
    _write(w / "b.txt", b"keep")
    index = _sync(w, r).index

    (r / "a.txt").write_bytes(b"edited by the script")
    os.remove(r / "b.txt")
    result = _sync(w, r, index)
    assert (r / "a.txt").read_bytes() == b"original"
    assert (r / "b.txt").read_bytes() == b"keep"
    assert result.copied_bytes == len(b"original") + len(b"keep")


def test_sync_in_replaces_planted_links_without_writing_through(tmp_path) -> None:
    w, r, outside = tmp_path / "w", tmp_path / "r", tmp_path / "outside"
    r.mkdir()
    outside.mkdir()
    _write(outside / "victim.txt", b"untouched")
    _write(w / "a.txt", b"payload")
    _write(w / "sub" / "b.txt", b"payload")
    index = _sync(w, r).index

    os.remove(r / "a.txt")
    os.symlink(outside / "victim.txt", r / "a.txt")
    os.remove(r / "sub" / "b.txt")
    os.rmdir(r / "sub")
    os.symlink(outside, r / "sub")
    _sync(w, r, index)

    assert (outside / "victim.txt").read_bytes() == b"untouched"
    assert not os.path.exists(outside / "b.txt")
    assert not os.path.islink(r / "a.txt") and (r / "a.txt").read_bytes() == b"payload"
    assert not os.path.islink(r / "sub") and (r / "sub" / "b.txt").read_bytes() == b"payload"


def test_sync_in_drops_files_gone_from_w(tmp_path) -> None:
    w, r = tmp_path / "w", tmp_path / "r"
    r.mkdir()
    _write(w / "a.txt")
    _write(w / "sub" / "b.txt")
    index = _sync(w, r).index

    os.remove(w / "sub" / "b.txt")
    result = _sync(w, r, index)
    assert not os.path.exists(r / "sub" / "b.txt")
    assert set(result.index) == {"a.txt"}


def test_sync_in_does_not_delete_through_a_planted_dir_link(tmp_path) -> None:
    w, r, outside = tmp_path / "w", tmp_path / "r", tmp_path / "outside"
    r.mkdir()
    _write(w / "sub" / "b.txt")
    index = _sync(w, r).index
    _write(outside / "b.txt", b"victim")
    os.remove(r / "sub" / "b.txt")
    os.rmdir(r / "sub")
    os.symlink(outside, r / "sub")

    os.remove(w / "sub" / "b.txt")
    os.rmdir(w / "sub")
    _sync(w, r, index)
    assert (outside / "b.txt").read_bytes() == b"victim"


def test_sync_in_skips_oversized_and_removes_their_stale_copy(tmp_path) -> None:
    w, r = tmp_path / "w", tmp_path / "r"
    r.mkdir()
    _write(w / "big.bin", b"small")
    index = _sync(w, r).index
    time.sleep(0.01)
    _write(w / "big.bin", b"x" * 64)

    result = workspace_copy.sync_in(str(w), str(r), None, index, 16, LIMIT)
    assert result.skipped == ["big.bin"]
    assert not os.path.exists(r / "big.bin")
    assert "big.bin" not in result.index


def test_copy_out_records_what_it_wrote(tmp_path) -> None:
    r, w = tmp_path / "r", tmp_path / "w"
    w.mkdir()
    _write(r / "output" / "x.txt", b"result")
    record: dict = {}
    written = workspace_copy.copy_out(str(r), str(w), {}, set(), LIMIT, LIMIT, record=record)
    assert written == [os.path.join("output", "x.txt")]
    st = os.stat(w / "output" / "x.txt")
    assert record[os.path.join("output", "x.txt")] == (st.st_size, st.st_mtime_ns)


# --- registry ------------------------------------------------------------------


@pytest.fixture
def registry():
    yield local_run_registry
    local_run_registry._registry.clear()


def test_register_is_keyed_by_realpath(registry, tmp_path) -> None:
    w = tmp_path / "w"
    w.mkdir()
    os.symlink(w, tmp_path / "alias")
    entry = registry.register(str(w))
    assert registry.register(str(tmp_path / "alias")) is entry
    assert entry.work_dir == os.path.realpath(w)


def test_release_without_registration_is_a_no_op(registry, tmp_path) -> None:
    registry.release_local_run(None)
    registry.release_local_run(str(tmp_path / "never-registered"))


def test_release_closes_and_unregisters(registry, tmp_path) -> None:
    entry = registry.register(str(tmp_path))
    registry.release_local_run(str(tmp_path))
    assert entry.closing
    assert registry.lookup(str(tmp_path)) is None
    assert not entry.acquire_inner()
    # a later round on the same W gets a fresh entry
    assert registry.register(str(tmp_path)) is not entry


def test_release_frees_the_uid_of_an_idle_entry(registry, tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(registry.local_uid_pool, "reap_uid", lambda uid: calls.append(("reap", uid)) or True)
    monkeypatch.setattr(registry.local_uid_pool, "free", lambda uid, root: calls.append(("free", uid, root)))
    entry = registry.register(str(tmp_path))
    entry.uid, entry.run_root, entry.run_dir = 30001, "/runs", "/runs/run-x"

    registry.release_local_run(str(tmp_path))
    assert ("free", 30001, "/runs") in calls
    assert entry.uid is None and entry.run_dir is None


def test_unconfirmed_reap_keeps_the_uid_quarantined(registry, tmp_path, monkeypatch) -> None:
    freed = []
    monkeypatch.setattr(registry.local_uid_pool, "reap_uid", lambda uid: False)
    monkeypatch.setattr(registry.local_uid_pool, "free", lambda uid, root: freed.append(uid))
    entry = registry.register(str(tmp_path))
    entry.uid, entry.run_root = 30002, "/runs"
    registry.release_local_run(str(tmp_path))
    assert freed == []


def test_release_waits_for_the_running_call(registry, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(registry.local_uid_pool, "reap_uid", lambda uid: True)
    entry = registry.register(str(tmp_path))
    assert entry.acquire_inner()
    done = threading.Event()
    threading.Thread(target=lambda: (registry.release_local_run(str(tmp_path)), done.set())).start()
    assert not done.wait(0.3)
    entry.inner.release()
    assert done.wait(5)


# --- executor ------------------------------------------------------------------


@pytest.fixture
def uid_mode(monkeypatch):
    monkeypatch.setattr(local_executor_module, "isolation_mode", lambda: "uid")


def _executor(w, keep: bool = True) -> LocalExecutor:
    return LocalExecutor(minio={}, local_sync_path=str(w), keep_run_dir=keep)


def test_no_entry_when_isolation_is_off(registry, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(local_executor_module, "isolation_mode", lambda: "off")
    assert _executor(tmp_path)._run_entry is None
    assert registry.lookup(str(tmp_path)) is None


def test_no_entry_without_keep_run_dir(registry, uid_mode, tmp_path) -> None:
    assert _executor(tmp_path, keep=False)._run_entry is None


def test_container_executor_never_gets_an_entry(registry, uid_mode, tmp_path) -> None:
    from bisheng_langchain.gpts.tools.code_interpreter.container_executor import ContainerExecutor

    assert ContainerExecutor.supports_retained_run is False


def test_workspace_calls_go_to_the_retained_run(registry, uid_mode, tmp_path, monkeypatch) -> None:
    seen = {}

    def fake_run_retained(entry, **kwargs):
        seen.update(kwargs, entry=entry)
        return IsolatedOutcome(returncode=0, stdout="hello\n", stderr="")

    monkeypatch.setattr(local_executor_module, "run_retained", fake_run_retained)
    executor = _executor(tmp_path)
    result = executor.run("print('hello')")
    assert result["exitcode"] == 0 and "hello" in result["log"]
    assert seen["entry"] is executor._run_entry
    assert seen["work_dir"] == str(tmp_path)
    assert not executor._run_entry.inner.locked()


def test_run_after_release_reports_task_ended(registry, uid_mode, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(local_executor_module, "run_retained", lambda *a, **k: pytest.fail("must not run"))
    executor = _executor(tmp_path)
    registry.release_local_run(str(tmp_path))
    assert executor.run("print(1)") == {"exitcode": 1, "log": TASK_ENDED_MSG, "file_list": []}
    assert asyncio.run(executor.arun("print(1)"))["log"] == TASK_ENDED_MSG


def test_run_closed_mid_run_reports_task_ended(registry, uid_mode, tmp_path, monkeypatch) -> None:
    def closed(*a, **k):
        raise RunClosed()

    monkeypatch.setattr(local_executor_module, "run_retained", closed)
    executor = _executor(tmp_path)
    assert executor.run("print(1)")["log"] == TASK_ENDED_MSG
    assert not executor._run_entry.inner.locked()


def test_calls_on_one_workspace_run_one_at_a_time_in_order(registry, uid_mode, tmp_path, monkeypatch) -> None:
    active, order, overlap = [0], [], []

    def fake_blocks(self, code):
        active[0] += 1
        if active[0] > 1:
            overlap.append(code)
        time.sleep(0.05)
        order.append(code)
        active[0] -= 1
        return {"exitcode": 0, "log": code, "file_list": []}

    monkeypatch.setattr(LocalExecutor, "_run_blocks", fake_blocks)
    executor = _executor(tmp_path)

    async def main():
        return await asyncio.gather(*(executor.arun(f"c{i}") for i in range(5)))

    results = asyncio.run(main())
    assert [r["log"] for r in results] == [f"c{i}" for i in range(5)]
    assert order == [f"c{i}" for i in range(5)]
    assert overlap == []


def test_queued_calls_return_when_the_task_is_released(registry, uid_mode, tmp_path, monkeypatch) -> None:
    started, finish = threading.Event(), threading.Event()

    def fake_blocks(self, code):
        started.set()
        finish.wait(5)
        return {"exitcode": 0, "log": code, "file_list": []}

    monkeypatch.setattr(LocalExecutor, "_run_blocks", fake_blocks)
    executor = _executor(tmp_path)

    async def main():
        first = asyncio.ensure_future(executor.arun("first"))
        second = asyncio.ensure_future(executor.arun("second"))
        await asyncio.to_thread(started.wait, 5)
        release = asyncio.ensure_future(asyncio.to_thread(registry.release_local_run, str(tmp_path)))
        await asyncio.sleep(0.2)
        finish.set()
        await release
        return await first, await second

    first, second = asyncio.run(main())
    assert first["log"] == "first"
    assert second["log"] == TASK_ENDED_MSG


# --- tool ----------------------------------------------------------------------


def test_tool_arun_goes_through_the_executor() -> None:
    class Exec:
        async def arun(self, code):
            return {"via": "arun", "code": code}

        def run(self, code):
            return {"via": "run"}

    tool = CodeInterpreterTool(executor=Exec())
    assert asyncio.run(tool.ainvoke({"python_code": "x"})) == {"via": "arun", "code": "x"}


def test_tool_arun_falls_back_to_run_without_executor_arun() -> None:
    tool = CodeInterpreterTool(executor=SimpleNamespace(run=lambda code: {"via": "run", "code": code}))
    assert asyncio.run(tool.ainvoke({"python_code": "y"})) == {"via": "run", "code": "y"}


# --- Linsight wiring -------------------------------------------------------------


def test_cleanup_releases_first_even_when_later_steps_fail(monkeypatch, tmp_path) -> None:
    from bisheng.linsight.domain import task_exec

    released = []
    monkeypatch.setattr(task_exec, "release_local_run", released.append)

    async def broken_monitor():
        raise RuntimeError("monitor failed")

    gone = str(tmp_path / "already-deleted")
    fake = SimpleNamespace(file_dir=gone, _stop_termination_monitor=broken_monitor)
    asyncio.run(task_exec.LinsightWorkflowTask._cleanup_resources(fake))
    assert released == [gone]


def test_cleanup_skips_release_before_the_workspace_exists(monkeypatch) -> None:
    from bisheng.linsight.domain import task_exec

    monkeypatch.setattr(task_exec, "release_local_run", lambda w: pytest.fail("must not release"))

    async def monitor():
        return None

    asyncio.run(
        task_exec.LinsightWorkflowTask._cleanup_resources(
            SimpleNamespace(file_dir=None, _stop_termination_monitor=monitor)
        )
    )

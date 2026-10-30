"""Runner: leftover processes, uid release, DELETE vs. lock holders, streamed copy-in.

Review findings on the F068 hardening: background jobs outlived exec and DELETE
while their uid was reissued; DELETE removed the tree under a running copy-in;
the copy-in body was spooled to the RAM tmpfs without a size bound.
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import tarfile
import threading
import time
import uuid

import execute
import procutil
import pytest
from app import copy_in_body_limit, create_app
from execute import handle_exec
from files import CopyInAbortedError, handle_put_files
from leases import LeaseStore
from procutil import kill_uid, uid_processes
from starlette.testclient import TestClient


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _session(client: TestClient) -> tuple[str, dict[str, str]]:
    body = client.post("/v1/sessions", headers=_auth()).json()
    return body["session_id"], {"X-Lease-Token": body["lease_token"]}


def _tar_gz(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", encoding="utf-8", format=tarfile.PAX_FORMAT) as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _framed(members: dict[str, bytes], manifest: dict | None = None) -> bytes:
    raw = json.dumps(manifest or {}).encode("utf-8")
    return len(raw).to_bytes(4, "big") + raw + _tar_gz(members)


class _FakeUidKill:
    """Stands in for the root-only kill(-1) helper and the /proc scan."""

    def __init__(self, survivors: int = 0):
        self.calls: list[tuple[int, str]] = []
        # Number of scans that still report a process after a kill.
        self.survivors = survivors

    def kill(self, uid: int, *, session_id: str = "", reason: str = "") -> bool:
        self.calls.append((uid, reason))
        return True

    def scan(self, uid: int) -> list[int]:
        if self.survivors > 0:
            self.survivors -= 1
            return [4242]
        return []


def _isolated_store(tmp_path, fake: _FakeUidKill, **kwargs) -> LeaseStore:
    return LeaseStore(
        sessions_root=str(tmp_path / "s"),
        max_sessions=4,
        enable_uid_isolation=True,
        uid_killer=fake.kill,
        uid_scanner=fake.scan,
        sleep=lambda _s: None,
        **kwargs,
    )


def _alive(marker: str) -> bool:
    done = subprocess.run(["pgrep", "-f", marker], capture_output=True, check=False)
    return done.returncode == 0


# ---- leftover processes ---------------------------------------------------------------


def test_background_job_does_not_outlive_exec(tmp_path, monkeypatch):
    # RLIMIT_NPROC counts every process of the developer's user on macOS.
    monkeypatch.setattr(execute, "_RLIMIT_NPROC", 1 << 30)
    store = LeaseStore(sessions_root=str(tmp_path / "s"))
    lease = store.create()
    seconds = 4000 + uuid.uuid4().int % 900
    marker = f"sleep {seconds}"
    result = handle_exec(
        store,
        lease,
        {"code": f"{marker} >/dev/null 2>&1 &", "lang": "sh", "timeout_s": 5},
    )
    assert result["exitcode"] == 0
    deadline = time.monotonic() + 3
    while _alive(marker) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(marker)
    store.delete(lease.session_id, lease.lease_token)


def test_exec_end_and_delete_kill_by_uid(tmp_path):
    fake = _FakeUidKill()
    store = _isolated_store(tmp_path, fake)
    lease = store.create()
    handle_exec(store, lease, {"code": "print(1)", "lang": "python", "timeout_s": 5})
    assert (lease.uid, "exec_end") in fake.calls
    store.delete(lease.session_id, lease.lease_token)
    assert [reason for uid, reason in fake.calls if uid == lease.uid].count("delete") >= 2
    # The uid is clean, so it goes back to the pool.
    assert store.create().uid == lease.uid


def test_uid_with_surviving_processes_is_quarantined(tmp_path):
    fake = _FakeUidKill(survivors=10)
    store = _isolated_store(tmp_path, fake)
    lease = store.create()
    store.delete(lease.session_id, lease.lease_token)
    assert not os.path.exists(lease.work_dir)
    assert store.create().uid != lease.uid


def test_uid_survivor_cleared_on_second_round_is_released(tmp_path):
    fake = _FakeUidKill(survivors=1)
    store = _isolated_store(tmp_path, fake)
    lease = store.create()
    store.delete(lease.session_id, lease.lease_token)
    assert store.create().uid == lease.uid


# ---- DELETE vs. lock holders -----------------------------------------------------------


def test_delete_hands_cleanup_to_lock_holder_and_keeps_uid_reserved(tmp_path):
    fake = _FakeUidKill()
    store = _isolated_store(tmp_path, fake, delete_wait_s=0.05)
    lease = store.create()
    entered = threading.Event()
    leave = threading.Event()

    def _holder() -> None:
        with store.locked(lease):
            entered.set()
            leave.wait(5)

    worker = threading.Thread(target=_holder)
    worker.start()
    assert entered.wait(5)
    store.delete(lease.session_id, lease.lease_token)
    # The holder still owns the tree: it is not removed under it, and the uid
    # is not reissued while the holder may still run as it.
    assert os.path.exists(lease.work_dir)
    other = store.create()
    assert other.uid != lease.uid
    leave.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert not os.path.exists(lease.work_dir)
    assert not os.path.exists(lease.home_dir)
    assert store.create().uid == lease.uid


class _GatedBody:
    """Tar stream that blocks after the first chunk until ``gate`` is set."""

    def __init__(self, data: bytes, gate: threading.Event, first: int):
        self._data = data
        self._pos = 0
        self._gate = gate
        self._first = first
        self.blocked = threading.Event()

    def read(self, size: int = -1) -> bytes:
        if self._pos >= self._first:
            self.blocked.set()
            self._gate.wait(5)
        if size is None or size < 0:
            size = len(self._data) - self._pos
        end = min(self._pos + size, len(self._data) if self._pos >= self._first else self._first)
        out = self._data[self._pos : end]
        self._pos = end
        return out


def test_delete_during_copy_in_leaves_no_orphan_tree(tmp_path):
    store = LeaseStore(sessions_root=str(tmp_path / "s"), delete_wait_s=0.05)
    lease = store.create()
    payload = _tar_gz({f"d{i}/f.bin": os.urandom(4096) for i in range(40)})
    gate = threading.Event()
    body = _GatedBody(payload, gate, first=len(payload) // 3)
    box: dict = {}

    def _copy_in() -> None:
        try:
            with store.locked(lease):
                handle_put_files(lease, body, {}, 1 << 20, 1 << 30, should_stop=lambda: lease.deleted)
            box["outcome"] = "done"
        except CopyInAbortedError:
            box["outcome"] = "aborted"

    worker = threading.Thread(target=_copy_in)
    worker.start()
    assert body.blocked.wait(5)
    store.delete(lease.session_id, lease.lease_token)
    gate.set()
    worker.join(timeout=5)
    assert box["outcome"] == "aborted"
    assert not os.path.exists(lease.work_dir)
    assert os.listdir(tmp_path / "s") == []


def test_should_stop_aborts_between_members(tmp_path):
    store = LeaseStore(sessions_root=str(tmp_path / "s"))
    lease = store.create()
    seen: list[int] = []

    def _stop() -> bool:
        seen.append(1)
        return len(seen) > 3

    with pytest.raises(CopyInAbortedError):
        handle_put_files(lease, _tar_gz({"a.txt": b"a", "b.txt": b"b", "c.txt": b"c"}), {}, 1024, None, _stop)
    assert not os.path.exists(os.path.join(lease.work_dir, "c.txt"))


# ---- streamed copy-in ------------------------------------------------------------------


@pytest.fixture
def small_limit(tmp_path):
    root = tmp_path / "sessions"
    app = create_app(
        token="test-token",
        sessions_root=str(root),
        max_copy_in_body_bytes=20_000,
    )
    with TestClient(app) as http:
        yield http, root


def test_copy_in_over_declared_limit_is_413(small_limit):
    http, _root = small_limit
    sid, headers = _session(http)
    resp = http.put(
        f"/v1/sessions/{sid}/files",
        headers=headers,
        content=_framed({"big.bin": os.urandom(30_000)}),
    )
    assert resp.status_code == 413
    assert resp.json() == {"error": "copy-in body too large"}


def test_copy_in_over_streamed_limit_is_413_and_session_survives(small_limit):
    http, root = small_limit
    sid, headers = _session(http)
    body = _framed({"big.bin": os.urandom(30_000)})

    def _chunks():
        # No Content-Length: the bound must trip while streaming.
        for start in range(0, len(body), 1000):
            yield body[start : start + 1000]

    resp = http.put(f"/v1/sessions/{sid}/files", headers=headers, content=_chunks())
    assert resp.status_code == 413
    assert not [name for name in os.listdir(root) if name.startswith(".copy-in-")]
    ok = http.put(f"/v1/sessions/{sid}/files", headers=headers, content=_framed({"a.txt": b"hello"}))
    assert ok.status_code == 200
    assert ok.json()["written"] == ["a.txt"]


def test_chunked_copy_in_extracts_while_streaming(tmp_path):
    root = tmp_path / "sessions"
    app = create_app(token="test-token", sessions_root=str(root))
    members = {f"dir/{i}.txt": f"line {i}\n".encode() * 200 for i in range(30)}
    body = _framed(members)

    def _chunks():
        for start in range(0, len(body), 777):
            yield body[start : start + 777]

    with TestClient(app) as http:
        sid, headers = _session(http)
        resp = http.put(f"/v1/sessions/{sid}/files", headers=headers, content=_chunks())
        assert resp.status_code == 200
        assert sorted(resp.json()["written"]) == sorted(members)
        lease = app.state.store._leases[sid]
        with open(os.path.join(lease.work_dir, "dir", "7.txt"), "rb") as fh:
            assert fh.read() == members["dir/7.txt"]


def test_garbage_archive_after_manifest_is_400(small_limit):
    http, _root = small_limit
    sid, headers = _session(http)
    raw = b"{}"
    resp = http.put(
        f"/v1/sessions/{sid}/files",
        headers=headers,
        content=len(raw).to_bytes(4, "big") + raw + b"not a tar at all" * 10,
    )
    assert resp.status_code == 400


def test_default_body_limit_covers_cap_and_overhead():
    cap = 512 * 1024 * 1024
    limit = copy_in_body_limit(cap)
    assert limit > cap + 64 * 1024 * 1024
    assert limit < cap * 2


# ---- procutil helpers ------------------------------------------------------------------


def test_uid_processes_skips_zombies_and_other_uids(tmp_path):
    def _proc(pid: str, uid_line: str, state: str = "S (sleeping)") -> None:
        d = tmp_path / pid
        d.mkdir()
        (d / "status").write_text(f"Name:\tx\nState:\t{state}\nUid:\t{uid_line}\n")

    _proc("10", "10001\t10001\t10001\t10001")
    _proc("11", "10002\t10002\t10002\t10002")
    _proc("12", "10001\t10001\t10001\t10001", state="Z (zombie)")
    _proc("13", "0\t10001\t0\t0")
    (tmp_path / "self").mkdir()
    assert sorted(uid_processes(10001, proc_root=str(tmp_path))) == [10, 13]
    assert uid_processes(10003, proc_root=str(tmp_path)) == []
    assert uid_processes(1, proc_root=str(tmp_path / "missing")) == []


def test_kill_uid_runs_helper_as_uid_and_reports_failure():
    seen: dict = {}

    def _run(cmd, **kwargs):
        seen.update(kwargs, cmd=cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    assert kill_uid(10007, run=_run) is True
    assert seen["user"] == 10007 and seen["group"] == 10007 and seen["extra_groups"] == []
    assert "os.kill(-1, signal.SIGKILL)" in seen["cmd"][-1]

    def _fail(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, b"", b"boom")

    assert kill_uid(10007, run=_fail) is False

    def _raise(cmd, **_kwargs):
        raise PermissionError("not root")

    assert kill_uid(10007, run=_raise) is False


def test_kill_uid_treats_concurrent_helper_kill_as_done(monkeypatch):
    # Exec end and DELETE each start a helper as the same uid; the first
    # kill(-1) also SIGKILLs the other helper. That is not a failure.
    errors: list = []
    monkeypatch.setattr(procutil._log, "error", lambda *a, **_k: errors.append(a))

    def _killed(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, -signal.SIGKILL, b"", b"")

    assert kill_uid(10007, run=_killed) is True
    assert errors == []

    def _fail(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, b"", b"boom")

    assert kill_uid(10007, run=_fail) is False
    assert len(errors) == 1

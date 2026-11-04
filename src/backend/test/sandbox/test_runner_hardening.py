"""Runner hardening from the F068 acceptance report (D1 D2 D3 D4 D6 D7 D9 D10 D13, C1-C6)."""

from __future__ import annotations

import io
import json
import os
import signal
import tarfile
import threading
import time

import execute
import pytest
from app import create_app
from execute import _preexec, classify_exit, handle_exec, read_oom_kills
from files import ManifestError, read_copy_in_manifest
from leases import CapacityError, LeaseStore, UnknownLeaseError
from procutil import kill_group
from starlette.testclient import TestClient


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def _session(client: TestClient) -> tuple[str, dict[str, str]]:
    body = client.post("/v1/sessions", headers=_auth()).json()
    return body["session_id"], {"X-Lease-Token": body["lease_token"]}


def _exec(client: TestClient, sid: str, headers: dict, code: str, timeout_s: float = 5):
    return client.post(
        f"/v1/sessions/{sid}/exec",
        headers=headers,
        json={"code": code, "lang": "python", "timeout_s": timeout_s},
    )


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


def _untar_names(payload: bytes) -> set[str]:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        return {m.name for m in tar if m.isfile()}


@pytest.fixture
def multi(tmp_path):
    app = create_app(
        token="test-token",
        sessions_root=str(tmp_path / "sessions"),
        max_sessions=4,
        enable_uid_isolation=True,
    )
    with TestClient(app) as http:
        yield http, app


# ---- D1 concurrency ----------------------------------------------------------------


def test_execs_on_different_sessions_run_concurrently_and_health_answers(multi):
    http, _app = multi
    sessions = [_session(http) for _ in range(2)]
    results: list[int] = []

    def _run(sid: str, headers: dict) -> None:
        results.append(_exec(http, sid, headers, "import time; time.sleep(0.8)").json()["exitcode"])

    threads = [threading.Thread(target=_run, args=s) for s in sessions]
    started = time.monotonic()
    for t in threads:
        t.start()
    time.sleep(0.2)
    health_started = time.monotonic()
    assert http.get("/health").status_code == 200
    health_s = time.monotonic() - health_started
    # A new session can be created while both execs are running.
    assert http.post("/v1/sessions", headers=_auth()).status_code == 200
    for t in threads:
        t.join()
    total = time.monotonic() - started
    assert results == [0, 0]
    assert health_s < 0.5
    assert total < 1.5, f"execs were serialized: {total:.2f}s"


# ---- D2 / C1 timeout ----------------------------------------------------------------


def test_timeout_when_killpg_is_denied_still_returns_124(multi, monkeypatch):
    http, _app = multi

    def _denied(_pgid, _sig):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "killpg", _denied)
    sid, headers = _session(http)
    resp = _exec(http, sid, headers, "import time; time.sleep(30)", timeout_s=0.3)
    assert resp.status_code == 200
    body = resp.json()
    assert body["exitcode"] == 124
    assert body["killed_reason"] == "timeout"


class _FakeProc:
    pid = 424242

    def __init__(self, kill_exc: BaseException | None = None):
        self.kill_exc = kill_exc
        self.killed = False

    def kill(self):
        if self.kill_exc is not None:
            raise self.kill_exc
        self.killed = True


def test_kill_group_falls_back_to_proc_kill_and_never_raises():
    def _denied(_pgid, _sig):
        raise PermissionError(1, "Operation not permitted")

    proc = _FakeProc()
    assert kill_group(proc, killpg=_denied) is True
    assert proc.killed

    hopeless = _FakeProc(PermissionError(1, "Operation not permitted"))
    assert kill_group(hopeless, killpg=_denied) is False


def test_kill_group_treats_missing_group_as_done():
    def _gone(_pgid, _sig):
        raise ProcessLookupError()

    proc = _FakeProc()
    assert kill_group(proc, killpg=_gone) is True
    assert not proc.killed


def test_unkillable_timeout_returns_124_and_quarantines_uid(tmp_path, monkeypatch):
    store = LeaseStore(sessions_root=str(tmp_path / "s"), max_sessions=2, enable_uid_isolation=True)
    lease = store.create()
    monkeypatch.setattr(execute, "kill_group", lambda *_a, **_k: False)
    result = handle_exec(
        store,
        lease,
        {"code": "import time; time.sleep(1.5)", "lang": "python", "timeout_s": 0.2},
        kill_grace_s=0.1,
    )
    assert result["exitcode"] == 124
    assert result["killed_reason"] == "timeout"
    assert lease.uid in store._quarantined_uids
    assert store.create().uid != lease.uid


# ---- D6 / C1 exit code + killed_reason -------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"returncode": 0, "timed_out": False}, (0, None)),
        ({"returncode": 3, "timed_out": False}, (3, None)),
        ({"returncode": -9, "timed_out": True}, (124, "timeout")),
        ({"returncode": None, "timed_out": True}, (124, "timeout")),
        ({"returncode": -9, "timed_out": False, "oom_delta": 1, "cpu_s": 2.0}, (137, "memory")),
        ({"returncode": -9, "timed_out": False, "oom_delta": None, "cpu_s": 2.0}, (137, "memory")),
        ({"returncode": -9, "timed_out": False, "oom_delta": 0, "cpu_s": 2.0}, (137, "signal")),
        ({"returncode": -9, "timed_out": False, "oom_delta": 0, "cpu_s": 599.2}, (137, "cpu")),
        ({"returncode": -int(signal.SIGXCPU), "timed_out": False}, (128 + int(signal.SIGXCPU), "cpu")),
        ({"returncode": -9, "timed_out": False, "kill_requested": True}, (137, "signal")),
        ({"returncode": -15, "timed_out": False}, (143, "signal")),
    ],
)
def test_classify_exit(kwargs, expected):
    assert classify_exit(**kwargs) == expected


def test_read_oom_kills_v2_v1_and_missing(tmp_path):
    v2 = tmp_path / "memory.events"
    v2.write_text("low 0\nhigh 0\nmax 4\noom 2\noom_kill 3\n")
    v1 = tmp_path / "memory.oom_control"
    v1.write_text("oom_kill_disable 0\nunder_oom 0\noom_kill 7\n")
    assert read_oom_kills([str(v2)]) == 3
    assert read_oom_kills([str(tmp_path / "nope"), str(v1)]) == 7
    assert read_oom_kills([str(tmp_path / "nope")]) is None


def test_oom_kill_reports_memory_and_keeps_lease(tmp_path):
    store = LeaseStore(sessions_root=str(tmp_path / "s"))
    lease = store.create()
    counter = iter([5, 6])
    result = handle_exec(
        store,
        lease,
        {"code": "import os, signal; os.kill(os.getpid(), signal.SIGKILL)", "lang": "python", "timeout_s": 5},
        oom_reader=lambda: next(counter),
    )
    assert result["exitcode"] == 137
    assert result["killed_reason"] == "memory"
    # C2: the session is still there and usable.
    assert store.get(lease.session_id, lease.lease_token) is lease
    again = handle_exec(store, lease, {"code": "print('ok')", "lang": "python", "timeout_s": 5})
    assert again["exitcode"] == 0


def test_signal_death_is_never_negative_over_http(multi):
    http, _app = multi
    sid, headers = _session(http)
    resp = _exec(http, sid, headers, "import os, signal; os.kill(os.getpid(), signal.SIGTERM)")
    assert resp.status_code == 200
    body = resp.json()
    assert body["exitcode"] == 143
    assert body["killed_reason"] == "signal"
    assert _exec(http, sid, headers, "print(1)").status_code == 200


# ---- D7 / C4 DELETE during exec -------------------------------------------------------


def test_delete_during_exec_kills_process_and_removes_session(multi):
    http, app = multi
    sid, headers = _session(http)
    lease = app.state.store._leases[sid]
    box: dict = {}

    def _run() -> None:
        box["resp"] = _exec(http, sid, headers, "import time; time.sleep(30)", timeout_s=60)

    worker = threading.Thread(target=_run)
    started = time.monotonic()
    worker.start()
    deadline = time.monotonic() + 5
    while lease.proc is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert lease.proc is not None
    deleted = http.delete(f"/v1/sessions/{sid}", headers=headers)
    assert deleted.status_code == 200
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert time.monotonic() - started < 5
    body = box["resp"].json()
    assert body["killed_reason"] == "signal"
    assert body["exitcode"] == 137
    assert not os.path.exists(lease.work_dir)
    assert not os.path.exists(lease.home_dir)
    assert _exec(http, sid, headers, "print(1)").status_code == 404


def test_exec_queued_behind_lock_gets_404_after_delete(tmp_path):
    # Short wait: DELETE hands the cleanup to the queued exec, which runs it.
    store = LeaseStore(sessions_root=str(tmp_path / "s"), delete_wait_s=0.05)
    lease = store.create()
    box: dict = {}

    def _run() -> None:
        try:
            handle_exec(store, lease, {"code": "print(1)", "lang": "python", "timeout_s": 5})
            box["outcome"] = "ran"
        except UnknownLeaseError:
            box["outcome"] = "404"

    with lease.lock:
        worker = threading.Thread(target=_run)
        worker.start()
        time.sleep(0.05)
        store.delete(lease.session_id, lease.lease_token)
    worker.join(timeout=5)
    assert box["outcome"] == "404"
    assert not os.path.exists(lease.work_dir)
    assert not os.path.exists(lease.home_dir)


# ---- C3 404 everywhere ------------------------------------------------------------------


def test_unknown_session_is_404_for_every_session_call(multi):
    http, _app = multi
    headers = {"X-Lease-Token": "whatever"}
    base = "/v1/sessions/does-not-exist"
    responses = [
        http.post(f"{base}/exec", headers=headers, json={"code": "print(1)"}),
        http.put(f"{base}/files", headers=headers, content=_framed({"a.txt": b"x"})),
        http.get(f"{base}/files", headers=headers),
        http.delete(base, headers=headers),
    ]
    for resp in responses:
        assert resp.status_code == 404
        assert resp.json() == {"error": "not found"}


# ---- D4 idle reaping ----------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_reaper_skips_inflight_and_restarts_clock_on_finish(tmp_path):
    clock = _Clock()
    store = LeaseStore(sessions_root=str(tmp_path / "s"), lease_ttl_s=60, clock=clock)
    lease = store.create()
    held = store.acquire(lease.session_id, lease.lease_token)
    clock.now += 600
    store.reap_expired()
    assert lease.session_id in store._leases
    store.release(held)
    # Finishing work counts as activity: not idle yet.
    clock.now += 30
    store.reap_expired()
    assert lease.session_id in store._leases
    clock.now += 31
    store.reap_expired()
    assert lease.session_id not in store._leases
    assert not os.path.exists(lease.home_dir)


def test_long_exec_is_not_reaped_and_copy_out_follows(tmp_path):
    clock = _Clock()
    app = create_app(token="test-token", sessions_root=str(tmp_path / "s"), lease_ttl_s=60, clock=clock)
    with TestClient(app) as http:
        sid, headers = _session(http)
        lease = app.state.store._leases[sid]
        box: dict = {}

        def _run() -> None:
            box["resp"] = _exec(http, sid, headers, "import time; open('after.txt','w').write('x'); time.sleep(0.5)")

        worker = threading.Thread(target=_run)
        worker.start()
        deadline = time.monotonic() + 5
        while lease.proc is None and time.monotonic() < deadline:
            time.sleep(0.02)
        clock.now += 600
        app.state.store.reap_expired()
        worker.join(timeout=10)
        assert box["resp"].json()["exitcode"] == 0
        got = http.get(f"/v1/sessions/{sid}/files", headers=headers)
        assert got.status_code == 200
        assert "after.txt" in _untar_names(got.content)


# ---- D9 uid allocation ----------------------------------------------------------------------


def test_uid_is_lowest_free_among_live_leases(tmp_path):
    store = LeaseStore(sessions_root=str(tmp_path / "s"), max_sessions=4, enable_uid_isolation=True)
    a, b, c = store.create(), store.create(), store.create()
    assert [a.uid, b.uid, c.uid] == [10000, 10001, 10002]
    store.delete(a.session_id, a.lease_token)
    d = store.create()
    # The old len()-based formula gave 10002 here and collided with c.
    assert d.uid == 10000
    live = [lease.uid for lease in store._leases.values()]
    assert len(live) == len(set(live))


def test_uid_pool_exhausted_raises_capacity(tmp_path):
    store = LeaseStore(sessions_root=str(tmp_path / "s"), max_sessions=3, enable_uid_isolation=True, max_uids=2)
    store.create()
    store.create()
    with pytest.raises(CapacityError):
        store.create()
    assert len(store._leases) == 2


# ---- D10 supplementary groups ---------------------------------------------------------------


def test_preexec_drops_supplementary_groups_before_ids(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(execute.resource, "setrlimit", lambda *_a: None)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "setgroups", lambda groups: calls.append(("setgroups", tuple(groups))))
    monkeypatch.setattr(os, "setgid", lambda gid: calls.append(("setgid", gid)))
    monkeypatch.setattr(os, "setuid", lambda uid: calls.append(("setuid", uid)))
    _preexec(10007)
    assert calls == [("setgroups", ()), ("setgid", 10007), ("setuid", 10007)]


# ---- D3 / C5 copy-in total cap and spooling --------------------------------------------------


def test_copy_in_total_cap_skips_and_lists(tmp_path):
    root = tmp_path / "s"
    app = create_app(
        token="test-token",
        sessions_root=str(root),
        max_copy_in_bytes=2048,
        max_copy_in_total_bytes=1500,
    )
    with TestClient(app) as http:
        sid, headers = _session(http)
        first = http.put(
            f"/v1/sessions/{sid}/files",
            headers=headers,
            content=_framed({"a.bin": b"a" * 1000, "b.bin": b"b" * 1000, "c.txt": b"c" * 100}),
        )
        assert first.status_code == 200
        body = first.json()
        assert body["written"] == ["a.bin", "c.txt"]
        assert body["skipped"] == [{"path": "b.bin", "size": 1000}]
        # Replacing a path counts its new size, not old + new.
        second = http.put(
            f"/v1/sessions/{sid}/files",
            headers=headers,
            content=_framed({"a.bin": b"A" * 1200}),
        )
        assert second.json()["written"] == ["a.bin"]
        third = http.put(
            f"/v1/sessions/{sid}/files",
            headers=headers,
            content=_framed({"d.txt": b"d" * 300}),
        )
        assert third.json()["skipped"] == [{"path": "d.txt", "size": 300}]
        # The spooled body is gone once the request finishes.
        assert not [name for name in os.listdir(root) if name.startswith(".copy-in-")]


def test_read_copy_in_manifest_from_file():
    raw = json.dumps({"a.txt": "0" * 32}).encode()
    fh = io.BytesIO(len(raw).to_bytes(4, "big") + raw + b"TAR")
    assert read_copy_in_manifest(fh) == {"a.txt": "0" * 32}
    assert fh.read() == b"TAR"
    with pytest.raises(ManifestError):
        read_copy_in_manifest(io.BytesIO(b"\x00\x00"))
    with pytest.raises(ManifestError):
        read_copy_in_manifest(io.BytesIO((100).to_bytes(4, "big") + b"{}"))
    with pytest.raises(ManifestError):
        read_copy_in_manifest(io.BytesIO((2).to_bytes(4, "big") + b"[]"))


# ---- D13 / C6 HOME outside the work dir, MATPLOTLIBRC ----------------------------------------


def test_home_caches_never_become_artifacts(multi, monkeypatch):
    http, app = multi
    monkeypatch.setenv("MATPLOTLIBRC", "/etc/matplotlibrc")
    sid, headers = _session(http)
    lease = app.state.store._leases[sid]
    code = (
        "import os, json, pathlib\n"
        "home = pathlib.Path(os.environ['HOME'])\n"
        "(home / '.cache' / 'fontconfig').mkdir(parents=True, exist_ok=True)\n"
        "(home / '.cache' / 'fontconfig' / 'x.cache-9').write_text('c')\n"
        "(home / 'dconf').mkdir(exist_ok=True)\n"
        "(home / 'dconf' / 'user').write_text('d')\n"
        "pathlib.Path('output/report.txt').write_text('r')\n"
        "print(json.dumps({k: os.environ.get(k) for k in "
        "('HOME', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'MATPLOTLIBRC')}))\n"
    )
    resp = _exec(http, sid, headers, code)
    assert resp.json()["exitcode"] == 0, resp.json()
    env = json.loads(resp.json()["stdout"])
    work = os.path.realpath(lease.work_dir)
    for key in ("HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
        path = os.path.realpath(env[key])
        assert not (path == work or path.startswith(work + os.sep)), key
        assert path.startswith(os.path.realpath(lease.home_dir))
    assert env["MATPLOTLIBRC"] == "/etc/matplotlibrc"
    got = http.get(f"/v1/sessions/{sid}/files", headers=headers)
    assert _untar_names(got.content) == {"output/report.txt"}
    assert http.delete(f"/v1/sessions/{sid}", headers=headers).status_code == 200
    assert not os.path.exists(lease.home_dir)


def test_matplotlibrc_absent_is_not_invented(monkeypatch):
    monkeypatch.delenv("MATPLOTLIBRC", raising=False)
    env = execute._child_env("/w", "/w.home")
    assert "MATPLOTLIBRC" not in env
    assert env["HOME"] == "/w.home"
    assert env["TMPDIR"] == "/w"

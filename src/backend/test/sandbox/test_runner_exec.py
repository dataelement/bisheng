"""Exec timeout, env whitelist, OOM reclaim (F068 T011)."""

from __future__ import annotations

import os
import resource as resource_mod
import threading
import time

import pytest
from app import create_app
from execute import _preexec
from leases import LeaseStore
from starlette.testclient import TestClient


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(tmp_path):
    app = create_app(token="test-token", sessions_root=str(tmp_path / "sessions"))
    with TestClient(app) as http:
        yield http


def _session(client: TestClient) -> tuple[str, dict[str, str]]:
    body = client.post("/v1/sessions", headers=_auth()).json()
    return body["session_id"], {"X-Lease-Token": body["lease_token"]}


def test_exec_returns_duration_and_streams(client: TestClient):
    sid, headers = _session(client)
    resp = client.post(
        f"/v1/sessions/{sid}/exec",
        headers=headers,
        json={"code": "import sys; print('out'); print('err', file=sys.stderr)", "lang": "python", "timeout_s": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["exitcode"] == 0
    assert "out" in body["stdout"]
    assert "err" in body["stderr"]
    assert body["duration_ms"] >= 0


def test_timeout_kills_process_group_and_skips_copy_out(client: TestClient):
    sid, headers = _session(client)
    resp = client.post(
        f"/v1/sessions/{sid}/exec",
        headers=headers,
        json={
            "code": "open('half.txt','w').write('partial')\nimport time\ntime.sleep(30)\n",
            "lang": "python",
            "timeout_s": 0.2,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["exitcode"] == 124
    got = client.get(f"/v1/sessions/{sid}/files", headers=headers)
    assert got.status_code == 200
    assert len(got.content) < 256


def test_child_env_has_no_secrets(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("MYSQL_PASSWORD", "secret")
    monkeypatch.setenv("token", "global-token")
    monkeypatch.setenv("lease_token", "lease")
    sid, headers = _session(client)
    resp = client.post(
        f"/v1/sessions/{sid}/exec",
        headers=headers,
        json={
            "code": "import os, json; print(json.dumps(dict(os.environ)))",
            "lang": "python",
            "timeout_s": 5,
        },
    )
    env = resp.json()["stdout"]
    assert "MINIO" not in env
    assert "MYSQL" not in env
    assert "global-token" not in env
    probe = client.post(
        f"/v1/sessions/{sid}/exec",
        headers=headers,
        json={
            "code": "import os; print(os.environ['HOME']); print(os.environ['TMPDIR'])",
            "lang": "python",
            "timeout_s": 5,
        },
    )
    lines = probe.json()["stdout"].strip().splitlines()
    assert lines[0] == lines[1]
    assert sid in lines[0]


def test_exit_137_deletes_lease(client: TestClient):
    sid, headers = _session(client)
    resp = client.post(
        f"/v1/sessions/{sid}/exec",
        headers=headers,
        json={"code": "import os; os._exit(137)", "lang": "python", "timeout_s": 5},
    )
    assert resp.status_code == 200
    assert resp.json()["exitcode"] == 137
    again = client.post(
        f"/v1/sessions/{sid}/exec",
        headers=headers,
        json={"code": "print(1)", "lang": "python", "timeout_s": 5},
    )
    assert again.status_code == 404


def test_two_execs_on_same_session_are_serial(client: TestClient):
    sid, headers = _session(client)
    order: list[str] = []

    def _run(tag: str, sleep_s: float) -> None:
        resp = client.post(
            f"/v1/sessions/{sid}/exec",
            headers=headers,
            json={
                "code": f"import time, pathlib; pathlib.Path('log.txt').write_text('{tag}'); time.sleep({sleep_s})",
                "lang": "python",
                "timeout_s": 5,
            },
        )
        order.append(tag + ":" + str(resp.json()["exitcode"]))

    t1 = threading.Thread(target=_run, args=("a", 0.25))
    t2 = threading.Thread(target=_run, args=("b", 0.01))
    started = time.monotonic()
    t1.start()
    time.sleep(0.05)
    t2.start()
    t1.join()
    t2.join()
    assert time.monotonic() - started >= 0.25
    assert all(item.endswith(":0") for item in order)


def test_preexec_sets_rlimits(monkeypatch: pytest.MonkeyPatch):
    captured: list[tuple[int, tuple[int, int]]] = []

    def _capture(res, limits):
        captured.append((res, limits))

    monkeypatch.setattr(resource_mod, "setrlimit", _capture)
    monkeypatch.setattr(os, "geteuid", lambda: 1)
    _preexec()
    kinds = {item[0] for item in captured}
    assert resource_mod.RLIMIT_AS in kinds
    assert resource_mod.RLIMIT_NPROC in kinds
    assert resource_mod.RLIMIT_CPU in kinds


def test_max_sessions_without_uid_isolation_refused(tmp_path):
    with pytest.raises(RuntimeError, match="enable_uid_isolation"):
        LeaseStore(sessions_root=str(tmp_path), max_sessions=2, enable_uid_isolation=False)

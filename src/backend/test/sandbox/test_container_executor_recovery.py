"""ContainerExecutor hardening from the F068 acceptance run (D2, D3, D4, D6, D7).

Contract with the runner: C1 (exit codes / killed_reason), C2 (a kill keeps the
session), C3 (404 = lease lost, retry once), C4 (DELETE while exec runs), C5
(copy-in total cap, streamed body). No real HTTP: a fake runner stands in.
"""

from __future__ import annotations

import threading
import time

import pytest
from fake_runner import FakeResponse
from fake_runner import FakeRunnerClient as _BaseFakeRunnerClient

from bisheng.common.errcode.sandbox import SandboxExecTimeoutError, SandboxProtocolError
from bisheng_langchain.gpts.tools.code_interpreter import container_executor as ce
from bisheng_langchain.gpts.tools.code_interpreter.container_executor import ContainerExecutor

URL = "http://runner-a:8080"


class ScriptedRunner(_BaseFakeRunnerClient):
    """Fake runner whose exec answers come from a script, one entry per call.

    An entry is a result dict, or a callable ``(replica, session) -> FakeResponse``.
    When the script is empty the base fake's success path answers.
    """

    def __init__(self):
        super().__init__()
        self.exec_script: list = []
        self.put_bodies: list = []
        self.put_headers: list[dict] = []
        self.lose_session_after_exec = 0

    def request(self, method, url, *, content=None, headers=None, **kwargs):
        if content is not None and not isinstance(content, (bytes, bytearray)):
            self.put_bodies.append(type(content))
            self.put_headers.append(dict(headers or {}))
            content = b"".join(content)
        return super().request(method, url, content=content, headers=headers, **kwargs)

    def _exec(self, replica, session, payload):
        if self.exec_script:
            entry = self.exec_script.pop(0)
            resp = entry(replica, session) if callable(entry) else FakeResponse(200, json_data=entry)
        else:
            resp = super()._exec(replica, session, payload)
        if self.lose_session_after_exec:
            # Idle reaper / restart right after exec (TC-33): copy-out must recover.
            self.lose_session_after_exec -= 1
            replica.sessions.clear()
        return resp


def _exe(fake, **kwargs) -> ContainerExecutor:
    opts = {"minio": {}, "endpoints": [URL], "token": "test-token", "client": fake, "keep_session": True}
    opts.update(kwargs)
    return ContainerExecutor(**opts)


def _count(fake, method: str, suffix: str) -> int:
    return sum(1 for m, url in fake.calls if m == method and url.rstrip("/").endswith(suffix))


def _killed(exitcode: int, reason, stderr: str = "") -> dict:
    return {"exitcode": exitcode, "stdout": "", "stderr": stderr, "duration_ms": 5, "killed_reason": reason}


# ---------------------------------------------------------------- D4 / C3


def test_lost_session_is_reacquired_with_full_copy_in(tmp_path):
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    fake = ScriptedRunner()
    replica = fake.add_replica(URL)
    exe = _exe(fake)
    assert exe.execute_code("print(1)", work_dir=str(tmp_path))[0] == 0
    # Second call: the md5 index says data.csv is already there, so nothing is resent.
    assert exe.execute_code("print(1)", work_dir=str(tmp_path))[0] == 0
    assert fake.last_put_members == []

    replica.sessions.clear()  # runner restart or TTL reap between two tool calls
    exitcode, logs, _ = exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert exitcode == 0
    assert "ok" in logs
    assert _count(fake, "POST", "/v1/sessions") == 2
    # Fresh lease = fresh copy of the whole workspace, not just the delta.
    assert fake.last_put_members == ["data.csv"]
    assert exe._session_id in replica.sessions


def test_exec_404_retries_once_on_new_lease(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    fake.exec_script = [lambda replica, session: FakeResponse(404, json_data={"error": "not found"})]
    exe = _exe(fake, keep_session=False)
    exitcode, _logs, _ = exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert exitcode == 0
    assert _count(fake, "POST", "/v1/sessions") == 2
    assert _count(fake, "POST", "/exec") == 2


def test_copy_out_404_reruns_and_keeps_outputs(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL, write_after_exec={"output/after.txt": b"after"})
    fake.lose_session_after_exec = 1
    exe = _exe(fake)
    exitcode, _logs, _ = exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert exitcode == 0
    assert (tmp_path / "output" / "after.txt").read_bytes() == b"after"
    assert _count(fake, "POST", "/v1/sessions") == 2


def test_session_lost_twice_surfaces_an_error_after_one_retry(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    lost = lambda replica, session: FakeResponse(404, json_data={"error": "not found"})  # noqa: E731
    fake.exec_script = [lost, lost, lost]
    exe = _exe(fake)
    with pytest.raises(SandboxProtocolError) as err:
        exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert err.value.Code == 28006
    assert "lost the session" in str(err.value)
    assert _count(fake, "POST", "/v1/sessions") == 2
    assert exe._session_id is None


def test_put_files_404_reacquires(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    fake = ScriptedRunner()
    replica = fake.add_replica(URL)
    exe = _exe(fake)
    original = fake._put_files
    calls = {"n": 0}

    def flaky_put(session, body):
        calls["n"] += 1
        if calls["n"] == 1:
            replica.sessions.clear()
            return FakeResponse(404, json_data={"error": "not found"})
        return original(session, body)

    fake._put_files = flaky_put
    assert exe.execute_code("print(1)", work_dir=str(tmp_path))[0] == 0
    assert _count(fake, "PUT", "/files") == 2
    assert fake.last_put_members == ["a.txt"]


def test_release_treats_404_as_success(tmp_path):
    fake = ScriptedRunner()
    replica = fake.add_replica(URL)
    exe = _exe(fake)
    exe.execute_code("print(1)", work_dir=str(tmp_path))
    session = exe._session_id
    replica.sessions.clear()
    exe.close()  # must not raise on the runner's 404
    assert exe._session_id is None
    assert _count(fake, "DELETE", session) == 1


# ---------------------------------------------------------------- D6 / D2 / C1 / C2


def test_oom_kill_names_the_cause_and_keeps_the_session(tmp_path):
    fake = ScriptedRunner()
    replica = fake.add_replica(URL)
    fake.exec_script = [_killed(137, "memory")]
    exe = _exe(fake)
    exitcode, logs, _ = exe.execute_code("x = [0] * 10**12", work_dir=str(tmp_path))
    assert exitcode == 137
    assert "[SYSTEM NOTICE]" in logs
    assert "ran out of memory" in logs
    assert "chunks" in logs
    # C2: only the process died; the next call reuses the same session.
    session = exe._session_id
    assert session in replica.sessions
    assert exe.execute_code("print(1)", work_dir=str(tmp_path))[0] == 0
    assert exe._session_id == session
    assert _count(fake, "POST", "/v1/sessions") == 1
    assert _count(fake, "DELETE", session) == 0


def test_cpu_limit_kill_names_the_cpu_limit(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    fake.exec_script = [_killed(137, "cpu")]
    exitcode, logs, _ = _exe(fake).execute_code("while True: pass", work_dir=str(tmp_path))
    assert exitcode == 137
    assert "CPU time limit (600s of CPU time)" in logs


def test_signal_kill_names_the_signal(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    fake.exec_script = [_killed(143, "signal", stderr="Terminated")]
    exitcode, logs, _ = _exe(fake).execute_code("import os", work_dir=str(tmp_path))
    assert exitcode == 143
    assert logs.startswith("Terminated")
    assert "killed by signal 15 (SIGTERM)" in logs


def test_old_runner_negative_exitcode_is_normalized(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    # Pre-fix runner: raw Popen returncode, no killed_reason, empty output (TC-35 / TC-37).
    fake.exec_script = [{"exitcode": -9, "stdout": "", "stderr": "", "duration_ms": 5}]
    exitcode, logs, _ = _exe(fake).execute_code("x = 1", work_dir=str(tmp_path))
    assert exitcode == 137
    assert "signal 9 (SIGKILL)" in logs
    assert "ran out of memory or used up its CPU time limit" in logs


def test_plain_failure_has_no_kill_notice(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    fake.exec_script = [_killed(1, None, stderr="Traceback: boom")]
    exitcode, logs, _ = _exe(fake).execute_code("raise SystemExit(1)", work_dir=str(tmp_path))
    assert exitcode == 1
    assert logs == "Traceback: boom"


def test_timeout_reaches_the_model_as_a_timeout_with_partial_output(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    fake.exec_script = [
        {"exitcode": 124, "stdout": "step 1 done\n", "stderr": "", "duration_ms": 60000, "killed_reason": "timeout"}
    ]
    exe = _exe(fake)
    with pytest.raises(SandboxExecTimeoutError) as err:
        exe.execute_code("import time; time.sleep(10**6)", timeout=60, work_dir=str(tmp_path))
    text = str(err.value)
    assert err.value.Code == 28003
    assert "wall-clock timeout of 60s" in text
    assert "step 1 done" in text
    # The session itself is fine; a later call reuses it.
    assert exe._session_id is not None


def test_http_timeout_on_exec_names_the_wall_clock_limit(tmp_path):
    import httpx

    class SlowRunner(ScriptedRunner):
        def request(self, method, url, **kwargs):
            if url.endswith("/exec"):
                raise httpx.ReadTimeout("slow")
            return super().request(method, url, **kwargs)

    fake = SlowRunner()
    fake.add_replica(URL)
    with pytest.raises(SandboxExecTimeoutError) as err:
        _exe(fake, keep_session=False).execute_code("x", timeout=30, work_dir=str(tmp_path))
    assert "wall-clock timeout of 30s" in str(err.value)


# ---------------------------------------------------------------- D3 / C5


def test_copy_in_total_cap_skips_without_reading_and_streams(tmp_path, monkeypatch):
    for name in ("a.bin", "b.bin", "c.bin"):
        (tmp_path / name).write_bytes(name.encode() * 20)  # 100 bytes each
    fake = ScriptedRunner()
    fake.add_replica(URL)
    hashed: list[str] = []
    real_md5 = ce._md5_file
    monkeypatch.setattr(ce, "_md5_file", lambda path: hashed.append(path.rsplit("/", 1)[-1]) or real_md5(path))
    exe = _exe(fake, max_copy_in_total_bytes=250)
    exitcode, logs, _ = exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert exitcode == 0
    sent = sorted(fake.last_put_members)
    assert len(sent) == 2
    skipped = ({"a.bin", "b.bin", "c.bin"} - set(sent)).pop()
    assert skipped not in hashed
    assert "250-byte copy-in limit" in logs
    assert skipped in logs
    assert exe.copy_in_bytes == 200
    # Streamed body with an explicit length, not one in-memory bytes blob.
    assert fake.put_bodies and fake.put_bodies[-1] not in (bytes, bytearray)
    assert int(fake.put_headers[-1]["Content-Length"]) == len(fake.last_put_body)

    # Unchanged files still count toward the session total on the next call.
    exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert fake.last_put_members == []
    assert skipped in exe._skipped_total


def test_copy_in_total_cap_reads_settings_default():
    from bisheng.core.config.settings import SandboxConf

    exe = ContainerExecutor(minio={}, sandbox_conf=SandboxConf(endpoints=[URL]))
    assert exe.max_copy_in_total_bytes == 512 * 1024 * 1024
    exe = ContainerExecutor(minio={}, sandbox_conf=SandboxConf(endpoints=[URL], max_copy_in_total_bytes=1000))
    assert exe.max_copy_in_total_bytes == 1000


# ---------------------------------------------------------------- D7 / C4


def test_close_during_blocked_exec_deletes_session_and_does_not_retry(tmp_path):
    fake = ScriptedRunner()
    replica = fake.add_replica(URL)
    started = threading.Event()
    deleted = threading.Event()

    def blocking_exec(rep, session):
        started.set()
        # The runner kills the group on DELETE; the exec answer then reflects the kill.
        assert deleted.wait(5), "close() never reached the runner"
        return FakeResponse(200, json_data=_killed(137, "signal"))

    fake.exec_script = [blocking_exec]
    original_request = fake.request

    def tracking_request(method, url, **kwargs):
        resp = original_request(method, url, **kwargs)
        if method == "DELETE":
            deleted.set()
        return resp

    fake.request = tracking_request
    exe = _exe(fake)
    out: dict = {}
    worker = threading.Thread(
        target=lambda: out.setdefault("result", exe.execute_code("sleep 300", work_dir=str(tmp_path)))
    )
    worker.start()
    assert started.wait(5)
    session = exe._session_id
    t0 = time.monotonic()
    exe.close()  # task cancel path: runs on another thread while exec is blocked
    assert time.monotonic() - t0 < 2
    worker.join(5)
    assert not worker.is_alive()
    assert session not in replica.sessions
    exitcode, logs, _ = out["result"]
    assert exitcode == 1
    assert logs == ce.TASK_STOPPED_MSG
    # No resurrection: no second lease, no copy-out after the stop.
    assert _count(fake, "POST", "/v1/sessions") == 1
    assert _count(fake, "GET", "/files") == 0
    # The executor is still usable for a later, unrelated run.
    assert exe.execute_code("print(1)", work_dir=str(tmp_path))[0] == 0


def test_close_while_exec_returns_404_does_not_reacquire(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    started = threading.Event()
    release = threading.Event()

    def blocking_exec(rep, session):
        started.set()
        release.wait(5)
        return FakeResponse(404, json_data={"error": "not found"})

    fake.exec_script = [blocking_exec]
    exe = _exe(fake, keep_session=False)
    out: dict = {}
    worker = threading.Thread(target=lambda: out.setdefault("r", exe.execute_code("x", work_dir=str(tmp_path))))
    worker.start()
    assert started.wait(5)
    exe.close()
    release.set()
    worker.join(5)
    assert out["r"] == (1, ce.TASK_STOPPED_MSG, "")
    assert _count(fake, "POST", "/v1/sessions") == 1


def test_runner_side_total_skip_is_reported_as_total_and_not_indexed(tmp_path):
    (tmp_path / "small.txt").write_text("x")
    fake = ScriptedRunner()
    fake.add_replica(URL)
    original = fake._put_files

    def put_with_total_skip(session, body):
        original(session, body)
        session.files.pop("small.txt", None)
        return FakeResponse(200, json_data={"written": [], "skipped": [{"path": "small.txt", "size": 1}]})

    fake._put_files = put_with_total_skip
    exe = _exe(fake)
    _code, logs, _ = exe.execute_code("print(1)", work_dir=str(tmp_path))
    assert "copy-in limit" in logs
    assert "oversized" not in logs
    assert "small.txt" not in exe._md5_index

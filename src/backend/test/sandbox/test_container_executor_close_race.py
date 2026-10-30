"""ContainerExecutor review follow-ups for F068.

The runner's ``killed_reason`` is authoritative (C1); exit-code heuristics apply only
to an older runner that omits it. close() racing the lease acquire or copy-in stops
the run and deletes the session it acquired (C4 / D7).
"""

from __future__ import annotations

import pytest
from test_container_executor_recovery import URL, ScriptedRunner, _count, _exe

from bisheng.common.errcode.sandbox import SandboxExecTimeoutError
from bisheng_langchain.gpts.tools.code_interpreter import container_executor as ce

# ---------------------------------------------------------------- C1 authority


def test_exit_124_with_null_killed_reason_is_a_normal_failure(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    fake.exec_script = [{"exitcode": 124, "stdout": "", "stderr": "curl timed out", "killed_reason": None}]
    exitcode, logs, _ = _exe(fake).execute_code("timeout 2 curl http://slow", lang="sh", work_dir=str(tmp_path))
    assert exitcode == 124
    assert logs == "curl timed out"
    assert "[SYSTEM NOTICE]" not in logs


def test_exit_130_with_null_killed_reason_has_no_signal_notice(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    fake.exec_script = [{"exitcode": 130, "stdout": "", "stderr": "bye", "killed_reason": None}]
    exitcode, logs, _ = _exe(fake).execute_code("import sys; sys.exit(130)", work_dir=str(tmp_path))
    assert exitcode == 130
    assert logs == "bye"


def test_old_runner_without_field_keeps_exitcode_heuristics(tmp_path):
    fake = ScriptedRunner()
    fake.add_replica(URL)
    fake.exec_script = [{"exitcode": 124, "stdout": "partial", "stderr": ""}]
    with pytest.raises(SandboxExecTimeoutError):
        _exe(fake).execute_code("x", timeout=60, work_dir=str(tmp_path))


@pytest.mark.parametrize(
    ("result", "exitcode", "expected"),
    [
        ({"killed_reason": None}, 124, None),
        ({"killed_reason": None}, 137, None),
        ({"killed_reason": "memory"}, 137, "memory"),
        ({"killed_reason": "timeout"}, 124, "timeout"),
        ({"killed_reason": "weird"}, 137, "signal"),
        ({"killed_reason": "weird"}, 1, None),
        ({}, 124, "timeout"),
        ({}, 143, "signal"),
        ({}, 1, None),
    ],
)
def test_killed_reason_table(result, exitcode, expected):
    assert ce._killed_reason(result, exitcode) == expected


# ---------------------------------------------------------------- close() races


class CloseDuringRunner(ScriptedRunner):
    """Calls ``executor.close()`` while one request of the chosen kind is in flight."""

    def __init__(self, trigger: str):
        super().__init__()
        self.trigger = trigger
        self.executor = None

    def request(self, method, url, **kwargs):
        resp = super().request(method, url, **kwargs)
        is_acquire = method == "POST" and url.rstrip("/").endswith("/v1/sessions")
        is_put = method == "PUT" and url.endswith("/files")
        if self.executor is not None and (
            (self.trigger == "acquire" and is_acquire) or (self.trigger == "put" and is_put)
        ):
            executor, self.executor = self.executor, None
            # The acquire answer has not reached the executor yet, so close()
            # sees no session and deletes nothing on its own.
            executor.close()
        return resp


@pytest.mark.parametrize("keep_session", [True, False])
def test_close_during_acquire_deletes_the_new_lease_and_skips_exec(tmp_path, keep_session):
    (tmp_path / "a.txt").write_text("x")
    fake = CloseDuringRunner("acquire")
    replica = fake.add_replica(URL)
    exe = _exe(fake, keep_session=keep_session)
    fake.executor = exe

    exitcode, logs, _ = exe.execute_code("print(1)", work_dir=str(tmp_path))

    assert exitcode == 1
    assert logs == ce.TASK_STOPPED_MSG
    assert _count(fake, "POST", "/exec") == 0
    assert _count(fake, "PUT", "/files") == 0
    assert replica.sessions == {}
    assert exe._session_id is None
    assert _count(fake, "POST", "/v1/sessions") == 1


def test_close_during_copy_in_deletes_the_lease_and_skips_exec(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    fake = CloseDuringRunner("put")
    replica = fake.add_replica(URL)
    exe = _exe(fake, keep_session=True)
    fake.executor = exe

    exitcode, logs, _ = exe.execute_code("print(1)", work_dir=str(tmp_path))

    assert (exitcode, logs) == (1, ce.TASK_STOPPED_MSG)
    assert _count(fake, "POST", "/exec") == 0
    assert replica.sessions == {}
    assert exe._session_id is None


def test_stop_after_acquire_does_not_drop_a_newer_lease(tmp_path):
    fake = ScriptedRunner()
    replica = fake.add_replica(URL)
    exe = _exe(fake)
    exe._ensure_lease()
    stale = (exe._bound_url, exe._session_id, exe._lease_token)
    exe._forget_lease()
    exe._ensure_lease()
    current = exe._session_id

    assert exe._stop_after_acquire(stale)[1] == ce.TASK_STOPPED_MSG

    assert exe._session_id == current
    assert set(replica.sessions) == {current}

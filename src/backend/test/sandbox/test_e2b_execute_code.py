"""E2B execute_code is code-only: no workspace copy-in and no file harvest."""

from types import SimpleNamespace

from bisheng_langchain.gpts.tools.code_interpreter.e2b_executor import E2bCodeExecutor


def _executor(sandbox) -> E2bCodeExecutor:
    executor = E2bCodeExecutor.__new__(E2bCodeExecutor)
    executor.sandbox = sandbox
    executor.keep_sandbox = False
    executor.minio = {}
    return executor


def test_execute_code_returns_stdout_and_does_not_copy_workspace():
    calls: list[str] = []

    class _Sandbox:
        def run_code(self, code, timeout=None):
            calls.append(code)
            return SimpleNamespace(logs=SimpleNamespace(stdout=["hello\n"], stderr=["warn"]), error=None)

        def kill(self):
            calls.append("kill")

    executor = _executor(_Sandbox())
    executor._copy_in = lambda *_a, **_k: calls.append("copy_in")
    executor._copy_out = lambda *_a, **_k: calls.append("copy_out")
    exitcode, logs, stderr = executor.execute_code(code="print(1)", lang="python", work_dir="/app")
    assert exitcode == 0
    assert logs == "hello\n"
    assert stderr == "warn"
    assert calls == ["print(1)", "kill"]


def test_execute_code_failure_puts_the_error_in_logs():
    class _Sandbox:
        def run_code(self, code, timeout=None):
            return SimpleNamespace(
                logs=SimpleNamespace(stdout=["partial"], stderr=[]),
                error=SimpleNamespace(name="ValueError", value="bad", traceback="tb"),
            )

        def kill(self):
            return None

    executor = _executor(_Sandbox())
    exitcode, logs, stderr = executor.execute_code(code="raise ValueError('bad')")
    assert exitcode == 1
    assert stderr == ""
    assert "ValueError" in logs
    assert "bad" in logs
    assert "partial" not in logs

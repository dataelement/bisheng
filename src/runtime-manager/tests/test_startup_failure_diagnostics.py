"""F119 覆盖 AC: AC-21, AC-22, AC-23, AC-25: output precedes cleanup and stays bounded."""

from types import SimpleNamespace

import pytest


def test_public_tail_is_bounded_by_lines_and_utf8_bytes():
    from runtime_manager.secret_redaction import bounded_diagnostic

    output = bounded_diagnostic("secret " + ("文" * 900 + "\n") * 100, {"TOKEN": "secret"})
    assert len(output.splitlines()) <= 40
    assert len(output.encode()) <= 16384
    assert "secret" not in output
    assert bounded_diagnostic("private", {}, ["BUSINESS_VALUE"]) == ""


@pytest.mark.parametrize("running,reason", [(False, "startup_exited"), (True, "readiness_timeout")])
def test_docker_startup_failure_collects_safe_output_before_caller_cleanup(tmp_path, running, reason):
    from runtime_manager.bundle_launch import BundleLauncher
    from runtime_manager.config import Config
    from runtime_manager.execution_errors import ExecutionError

    calls = []

    class Docker:
        def inspect_container(self, ref):
            return {"State": {"Running": running}}

        def container_logs(self, ref, **kwargs):
            calls.append((ref, kwargs))
            return "fixture-token\n" + "diagnostic 文\n" * 100

    clock = SimpleNamespace(monotonic=lambda: 0)
    launcher = BundleLauncher(Config(data_root=tmp_path, probe_timeout_seconds=0), Docker(), clock=clock)
    operation = {"payload": {"runtime_env": {"BISHENG_APP_TOKEN": "fixture-token"}}}
    with pytest.raises(ExecutionError, match=reason) as caught:
        launcher.wait_ready(operation, "ref")
    assert caught.value.tail and len(caught.value.tail.splitlines()) <= 40
    assert "fixture-token" not in caught.value.tail
    assert calls == [("ref", {"tail": 40})]


def test_log_read_failure_does_not_replace_startup_reason(tmp_path):
    from runtime_manager.bundle_launch import BundleLauncher
    from runtime_manager.config import Config
    from runtime_manager.execution_errors import ExecutionError

    class Docker:
        def inspect_container(self, ref):
            return {"State": {"Running": False}}

        def container_logs(self, *args, **kwargs):
            raise OSError("private transport details")

    with pytest.raises(ExecutionError, match="startup_exited") as caught:
        BundleLauncher(Config(data_root=tmp_path), Docker()).wait_ready({"payload": {}}, "ref")
    assert caught.value.tail == ""


def test_known_input_reason_survives_and_opportunistic_diagnostics_precede_cleanup(tmp_path):
    from runtime_manager.bundle_inputs import BundleInputError
    from runtime_manager.config import Config
    from runtime_manager.operations import OperationExecutor
    from tests.test_operations_v2 import Platform

    events = []
    platform = Platform("probe")
    runtime = SimpleNamespace(
        diagnostics=lambda op: events.append("logs") or "original output",
        cleanup=lambda op: events.append("cleanup") or {"complete": True},
    )
    executor = OperationExecutor(Config(data_root=tmp_path), platform, runtime=runtime)
    try:
        executor._failure(platform.op, None, BundleInputError("startup_command_required"))
        assert platform.op["failure"]["reason"] == "startup_command_required"
        assert platform.op["failure"]["diagnostic_tail"] == "original output"
        assert events == ["logs", "cleanup"]
    finally:
        executor.close()

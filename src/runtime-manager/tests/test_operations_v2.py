"""覆盖 AC: AC-31、AC-32、AC-34、AC-37、AC-40、AC-48、AC-50、AC-63。"""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from runtime_manager.config import Config
from runtime_manager.container_runner import ExecutionError
from runtime_manager.operations import OperationExecutor
from runtime_manager.platform_client import PREFIX, PlatformClient, PlatformError


class Platform:
    def __init__(self, kind="stop"):
        self.op = {
            "operation_id": "operation-a",
            "app_id": "app-a",
            "node_id": "node-a",
            "kind": kind,
            "generation": 1,
            "owner_epoch": 1,
            "status": "pending",
            "stage": "admitted",
            "deadline": (datetime.utcnow() + timedelta(minutes=5)).isoformat(),
            "fact_sequence": 0,
            "cleanup_status": "pending",
            "payload": {},
        }
        self.facts = []

    def application(self, app_id):
        return {"app_id": app_id, "node_id": "node-a", "exec_ref": None}

    def operation(self, ident):
        return deepcopy(self.op)

    def claim(self, ident):
        self.op["status"] = "running"

    def fact(self, operation, sequence, phase, **kwargs):
        if any(operation.get(key) != self.op.get(key) for key in ("node_id", "generation", "owner_epoch", "app_id")):
            raise PlatformError("execution_fence_mismatch", 409)
        assert sequence == self.op["fact_sequence"] + 1
        self.op.update(fact_sequence=sequence, stage=phase)
        detail = deepcopy(kwargs.get("detail", {}))
        self.op["result"] = detail
        if phase in {"completed", "failed", "cancelled", "timed_out"}:
            self.op["status"] = phase
            self.op["cleanup_status"] = "complete" if detail.get("cleanup_complete") else "pending"
            self.op["failure"] = (
                {
                    key: detail[key]
                    for key in ("reason", "failed_stage", "diagnostic_tail", "maintenance", "data_may_have_changed")
                    if key in detail
                }
                if phase != "completed"
                else {}
            )
        self.facts.append((phase, detail))


class Docker:
    def __init__(self):
        self.calls = []

    def list_containers(self, **kwargs):
        self.calls.append(kwargs)
        return []


def test_stop_is_fenced_and_confirms_cleanup(tmp_path):
    platform = Platform()
    docker = Docker()
    executor = OperationExecutor(Config(data_root=tmp_path, node_id="node-a"), platform, docker)
    executor.execute("operation-a")
    executor.close()
    assert platform.facts == [("completed", {"stopped": True, "cleanup_complete": True})]
    assert all("bisheng.runtime.node=node-a" in call["filters"]["label"] for call in docker.calls)


def test_checkpoint_refuses_stale_owner_and_expired_work(tmp_path):
    platform = Platform()
    executor = OperationExecutor(Config(data_root=tmp_path), platform, Docker())
    original = deepcopy(platform.op)
    platform.op["owner_epoch"] = 2
    with pytest.raises(ExecutionError, match="fence"):
        executor.checkpoint(original)
    platform.op = original
    platform.op["deadline"] = (datetime.utcnow() - timedelta(seconds=1)).isoformat()
    with pytest.raises(ExecutionError, match="timeout"):
        executor.checkpoint(original)
    executor.close()


def test_reply_loss_does_not_cleanup_committed_serving_candidate(tmp_path):
    platform = Platform("deploy")
    platform.op["stage"] = "serving"
    docker = Docker()
    executor = OperationExecutor(Config(data_root=tmp_path), platform, docker)
    executor._failure(platform.op, None, RuntimeError("lost reply"))
    executor.close()
    assert not docker.calls
    assert not platform.facts


def test_shutdown_preserves_operation_for_restart(tmp_path):
    platform = Platform()
    docker = Docker()
    executor = OperationExecutor(Config(data_root=tmp_path), platform, docker)
    executor.close()
    with pytest.raises(ExecutionError, match="manager_stopping"):
        executor.checkpoint(platform.op)
    executor._failure(platform.op, None, ExecutionError("manager_stopping"))
    assert not platform.facts


def _docker_runtime_status(tmp_path, monkeypatch, response):
    from types import SimpleNamespace

    from runtime_manager.api import platform_observe as api

    config = Config(
        data_root=tmp_path,
        node_id="docker-node",
        platform_base_url="http://backend",
        platform_key_id="node",
        platform_secret="test",
    )
    requests = []

    class Engine:
        def info(self):
            return {"MemTotal": 4 * 1024**3, "NCPU": 4}

    def reply(request):
        requests.append((request.method, request.url.path))
        if isinstance(response, Exception):
            raise response
        return response

    # Use the actual client so a fabricated method cannot hide a broken contract.
    client = PlatformClient(config, transport=httpx.MockTransport(reply))
    monkeypatch.setattr(api, "executor", lambda: SimpleNamespace(config=config, docker=Engine(), platform=client))
    try:
        return api.runtime_snapshot(), requests
    finally:
        client.close()


def test_runtime_status_uses_platform_capacity_and_retains_public_shape(tmp_path, monkeypatch):
    """AC-48, AC-50: Docker status reads the real signed platform-client contract."""
    response = httpx.Response(
        200,
        json={"capacity": {"memory_budget_mb": 2048, "committed_mb": 512, "committed_cpu": 0.5, "instances": 1}},
    )
    document, requests = _docker_runtime_status(tmp_path, monkeypatch, response)
    assert requests == [("GET", PREFIX + "/nodes/plan")]
    assert set(document) == {
        "backend_available",
        "supported_runtimes",
        "capacity",
        "preflight",
        "protocol_version",
        "node_id",
    }
    assert document["backend_available"]
    assert document["protocol_version"] == 2 and document["node_id"] == "docker-node"
    assert document["capacity"]["readable"]
    assert document["capacity"]["mem_available_mb"] == 1536
    assert document["capacity"]["total_mb"] == 4096
    assert document["capacity"]["cpu"] == 4
    assert document["capacity"]["committed_mb"] == 512
    assert document["capacity"]["committed_cpu"] == 0.5
    assert document["capacity"]["instances"] == 1
    assert document["supported_runtimes"] and isinstance(document["preflight"], list)
    assert next(check for check in document["preflight"] if check["name"] == "platform_ledger")["ok"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"error": {"reason": "private-platform-error"}}),
        httpx.Response(200, json={"capacity": {"memory_budget_mb": 2048}}),
        httpx.Response(200, content=b"invalid json"),
        httpx.ConnectError("private-platform-address"),
    ],
    ids=["platform-unavailable", "incomplete-ledger", "invalid-json", "connection-failure"],
)
def test_runtime_status_never_falls_back_to_docker_capacity(tmp_path, monkeypatch, response):
    """AC-48, AC-50: failed authoritative reads remain unreadable despite a reachable Engine."""
    document, requests = _docker_runtime_status(tmp_path, monkeypatch, response)
    assert requests == [("GET", PREFIX + "/nodes/plan")]
    assert document["backend_available"]
    assert document["capacity"] == {
        "readable": False,
        "mem_available_mb": 0,
        "committed_mb": 0,
        "total_mb": 0,
        "cpu": 0,
        "committed_cpu": 0,
        "instances": 0,
        "reserve_mb": Config().reserve_mb,
        "overcommit_ratio": Config().overcommit_ratio,
    }
    assert next(check for check in document["preflight"] if check["name"] == "platform_ledger") == {
        "name": "platform_ledger",
        "ok": False,
        "detail": "platform API unavailable; no local capacity fallback",
    }
    assert "private-platform" not in str(document)


def test_unconfirmed_legacy_build_does_not_release_resources(tmp_path):
    """AC-63: daemon build is not proven stopped by an empty container list."""
    platform = Platform("prepare")
    platform.op["payload"] = {"legacy_build_state": "started", "delivery": {"mode": "source-image"}}
    executor = OperationExecutor(Config(data_root=tmp_path), platform, Docker())
    from runtime_manager.container_runner import ContainerRunner

    executor._failure(platform.op, ContainerRunner(executor.config, executor.docker), ExecutionError("connection_lost"))
    executor.close()
    phase, detail = platform.facts[-1]
    assert phase == "failed"
    assert detail["reason"] == "legacy_build_stop_unconfirmed"
    assert detail["stopped"] is False and detail["cleanup_complete"] is False


def test_completed_legacy_build_is_adopted_without_rebuilding(tmp_path):
    """AC-36, AC-63: finished stream plus existing immutable result survives reply loss."""
    from types import SimpleNamespace

    from runtime_manager.legacy_prepare import prepare_image

    operation = {
        "operation_id": "finished",
        "payload": {"legacy_build_state": "finished", "runtime": "python3.11", "platform": "linux/arm64"},
    }
    engine = SimpleNamespace(inspect_image=lambda reference: {"Id": "sha256:" + "a" * 64})
    result = prepare_image(
        Config(data_root=tmp_path),
        None,
        engine,
        operation,
        checkpoint=lambda: None,
        report=lambda *args, **kwargs: None,
    )
    assert result["image_id"] == "sha256:" + "a" * 64


def test_offline_legacy_build_does_not_ask_engine_to_pull_missing_base(tmp_path):
    """AC-13, AC-28: network_mode=none alone does not prevent daemon-side base pulls."""
    from types import SimpleNamespace

    from runtime_manager.bundle_inputs import archive_directory
    from runtime_manager.legacy_prepare import prepare_image

    source = tmp_path / "source"
    source.mkdir()
    (source / "bisheng-app.yaml").write_text("manifest_version: 1")
    (source / "main.py").write_text("print('app')")
    archive = archive_directory(source, tmp_path / "source.tar.gz").read_bytes()

    def download(op, artifact, path, **kwargs):
        path.write_bytes(archive)

    def inspect(ref):
        raise KeyError(ref)

    engine = SimpleNamespace(inspect_image=inspect)
    op = {
        "operation_id": "offline",
        "payload": {
            "source_artifact_id": "source",
            "runtime": "python3.11",
            "platform": "linux/arm64",
            "offline": True,
        },
    }
    with pytest.raises(ExecutionError, match="legacy_base_image_missing"):
        prepare_image(
            Config(data_root=tmp_path / "data"),
            SimpleNamespace(download=download),
            engine,
            op,
            checkpoint=lambda: None,
            report=lambda *args, **kwargs: None,
        )


def test_restart_cleans_orphan_exports_and_protects_active_helpers_and_database(tmp_path):
    """AC-63: a lost FileResponse background callback must not retain exports forever."""
    import os
    import time
    from types import SimpleNamespace

    orphan, active = "a" * 32, "b" * 32
    for ident in [orphan, active]:
        root = tmp_path / "data-jobs" / ident
        root.mkdir(parents=True)
        (root / "rows.csv").write_text("data")
        os.utime(root, (time.time() - 60, time.time() - 60))
    database = tmp_path / "apps/app/db/app.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"production")
    engine = SimpleNamespace(
        list_containers=lambda **kwargs: [
            {
                "Id": "active",
                "Labels": {"bisheng.runtime.operation": active, "bisheng.runtime.deadline": str(int(time.time()) + 60)},
            }
        ]
    )
    executor = OperationExecutor(Config(data_root=tmp_path, cleanup_seconds=1), Platform(), engine)
    executor.cleanup_data_workers()
    executor.close()
    assert not (tmp_path / "data-jobs" / orphan).exists()
    assert (tmp_path / "data-jobs" / active).exists()
    assert database.read_bytes() == b"production"


def test_dependency_diagnostic_redacts_registry_and_query_credentials():
    """AC-29, AC-53: owners may see missing packages, never the administrator's package-source secret."""
    from runtime_manager.container_runner import redact

    text = "Missing wheel; https://user:password@packages.example/simple?token=fixture-secret"
    cleaned = redact(
        text, {"npm_config_registry": "https://user:password@packages.example/simple?token=fixture-secret"}
    )
    assert "Missing wheel" in cleaned and "password" not in cleaned and "fixture-secret" not in cleaned
    assert "fixture-secret" not in redact("https://example?token=fixture-secret", {})


@pytest.mark.parametrize("kind", ["probe", "preview"])
def test_preflight_records_starting_before_readiness_failure(tmp_path, monkeypatch, kind):
    """AC-17, AC-63: terminal cleanup retains the last actual execution stage."""
    platform = Platform(kind)
    executor = OperationExecutor(Config(data_root=tmp_path, node_id="node-a"), platform, Docker())

    def failed_launch(*args, **kwargs):
        raise ExecutionError("readiness_timeout")

    monkeypatch.setattr(executor, "_launch", failed_launch)
    executor.execute("operation-a")
    executor.close()
    assert [phase for phase, _ in platform.facts] == ["starting", "failed"]
    failure = platform.facts[-1][1]
    assert failure["reason"] == "readiness_timeout"
    assert failure["failed_stage"] == "starting"
    assert failure["cleanup_complete"] is True


@pytest.mark.parametrize(
    ("kind", "stage", "reason", "expected_status", "maintenance", "changed"),
    [
        ("prepare", "preparing", "preparation_phase_failed", "failed", False, False),
        ("deploy", "migrating", "migration_failed", "failed", True, True),
        ("restore", "starting", "restore_failed", "failed", True, True),
        ("deploy", "preparing", "operation_cancelled", "cancelled", False, False),
        ("prepare", "preparing", "operation_timeout", "timed_out", False, False),
    ],
)
def test_cleanup_retries_preserve_first_failure_but_refresh_stop_result(
    tmp_path, kind, stage, reason, expected_status, maintenance, changed
):
    """F059 覆盖 AC: AC-48、AC-49、AC-52、AC-55."""
    platform = Platform(kind)
    platform.op.update(status="running", stage=stage)
    if kind == "deploy":
        platform.op["payload"]["migration_plan"] = [{"op": "alter_table"}]
    outcomes = iter([False, False, True])
    runtime = SimpleNamespace(cleanup=lambda _: {"complete": next(outcomes)})
    executor = OperationExecutor(Config(data_root=tmp_path), platform=platform, runtime=runtime)
    tail = "storage-guard:\nverified\ntransfer:\nruntime helper failed (TypeError)"
    try:
        executor._failure(platform.op, None, ExecutionError(reason, tail=tail))
        first = deepcopy(platform.op["failure"])
        assert first == {
            "reason": reason,
            "failed_stage": stage,
            "diagnostic_tail": tail,
            "maintenance": maintenance,
            "data_may_have_changed": changed,
        }
        executor._failure(platform.op, None, ExecutionError("cleanup_retry_without_original_tail"))
        assert platform.op["failure"] == first
        assert not platform.facts[-1][1]["stopped"] and not platform.facts[-1][1]["cleanup_complete"]
        executor._failure(platform.op, None, ExecutionError("another_cleanup_attempt", tail="different later tail"))
        assert platform.op["failure"] == first
        assert platform.facts[-1][1]["stopped"] and platform.facts[-1][1]["cleanup_complete"]
        assert [phase for phase, _ in platform.facts] == [expected_status] * 3
        assert platform.op["status"] == expected_status and platform.op["cleanup_status"] == "complete"
    finally:
        executor.close()


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("tail", ["", "original bounded diagnostic"])
def test_terminal_cleanup_preserves_false_flags_and_empty_diagnostic(tmp_path, complete, tail):
    """F059 覆盖 AC: AC-48、AC-49、AC-52、AC-55."""
    platform = Platform("prepare")
    failure = {
        "reason": "first_failure",
        "failed_stage": "preparing",
        "diagnostic_tail": tail,
        "maintenance": False,
        "data_may_have_changed": False,
    }
    platform.op.update(status="failed", stage="failed", failure=deepcopy(failure))
    runtime = SimpleNamespace(cleanup=lambda _: {"complete": complete, "stopped": True})
    executor = OperationExecutor(Config(data_root=tmp_path), platform=platform, runtime=runtime)
    try:
        executor._failure(platform.op, None, ExecutionError("later_reason", tail="new diagnostic must not replace"))
        assert platform.op["failure"] == failure
        assert platform.facts[-1][1]["stopped"] is complete
        assert platform.facts[-1][1]["cleanup_complete"] is complete
    finally:
        executor.close()


def test_expired_diagnostic_is_not_resurrected_during_cleanup_retry(tmp_path):
    """F059 覆盖 AC: AC-48、AC-49、AC-52、AC-55."""
    platform = Platform("prepare")
    failure = {
        "reason": "original_failure",
        "failed_stage": "preparing",
        "maintenance": False,
        "data_may_have_changed": False,
    }
    platform.op.update(status="failed", stage="failed", failure=deepcopy(failure))
    executor = OperationExecutor(
        Config(data_root=tmp_path), platform=platform, runtime=SimpleNamespace(cleanup=lambda _: {"complete": False})
    )
    try:
        executor._failure(platform.op, None, ExecutionError("retry", tail="do not restore an expired tail"))
        assert platform.op["failure"] == failure
        assert "diagnostic_tail" not in platform.facts[-1][1]
    finally:
        executor.close()


def test_cleanup_exception_keeps_original_maintenance_failure_and_pending_state(tmp_path):
    """F059 覆盖 AC: AC-48、AC-49、AC-52、AC-55."""
    platform = Platform("deploy")
    failure = {
        "reason": "migration_failed",
        "failed_stage": "migrating",
        "diagnostic_tail": "first failure",
        "maintenance": True,
        "data_may_have_changed": True,
    }
    platform.op.update(status="failed", stage="failed", failure=deepcopy(failure))

    def unknown(_):
        raise RuntimeError("unconfirmed writer")

    executor = OperationExecutor(
        Config(data_root=tmp_path), platform=platform, runtime=SimpleNamespace(cleanup=unknown)
    )
    try:
        executor._failure(platform.op, None, ExecutionError("retry"))
        assert platform.op["failure"] == failure
        assert platform.op["cleanup_status"] == "pending" and platform.op["status"] == "failed"
        assert not platform.facts[-1][1]["stopped"] and not platform.facts[-1][1]["cleanup_complete"]
    finally:
        executor.close()


def test_reconcile_terminal_cleanup_keeps_diagnostic_without_resubmitting(tmp_path, monkeypatch):
    """F059 覆盖 AC: AC-48、AC-49、AC-52、AC-55."""
    platform = Platform("prepare")
    failure = {
        "reason": "preparation_phase_failed",
        "failed_stage": "preparing",
        "diagnostic_tail": "first transfer TypeError",
        "maintenance": False,
        "data_may_have_changed": False,
    }
    platform.op.update(status="failed", stage="failed", cleanup_status="pending", failure=deepcopy(failure))
    platform.plan = lambda: [deepcopy(platform.op)]
    calls = []
    executor = OperationExecutor(
        Config(data_root=tmp_path),
        platform=platform,
        runtime=SimpleNamespace(cleanup=lambda op: calls.append(op["operation_id"]) or {"complete": True}),
    )
    monkeypatch.setattr(executor, "cleanup_data_workers", lambda: None)
    monkeypatch.setattr(executor, "heartbeat", lambda: None)
    monkeypatch.setattr(executor, "submit", lambda *_: pytest.fail("terminal operation must not be resubmitted"))
    try:
        executor.reconcile()
        assert calls == ["operation-a"] and platform.op["failure"] == failure
        assert platform.facts[-1][0] == "failed" and platform.op["cleanup_status"] == "complete"
    finally:
        executor.close()


def test_unknown_terminal_legacy_build_remains_held_without_cleanup(tmp_path):
    """F059 覆盖 AC: AC-48、AC-49、AC-52、AC-55."""
    platform = Platform("prepare")
    failure = {
        "reason": "legacy_build_stop_unconfirmed",
        "failed_stage": "preparing",
        "diagnostic_tail": "original diagnostic",
    }
    platform.op.update(
        status="failed",
        stage="failed",
        cleanup_status="pending",
        failure=deepcopy(failure),
        payload={"legacy_build_state": "started"},
    )
    runtime = SimpleNamespace(cleanup=lambda _: pytest.fail("unknown daemon build must not be reclaimed"))
    executor = OperationExecutor(Config(data_root=tmp_path), platform=platform, runtime=runtime)
    try:
        executor._failure(platform.op, None, ExecutionError("retry"))
        assert platform.op["failure"] == failure and platform.op["cleanup_status"] == "pending"
        assert not platform.facts
    finally:
        executor.close()


def test_completed_cleanup_does_not_create_failure_or_restart_operation(tmp_path):
    """F059 覆盖 AC: AC-48、AC-49、AC-52、AC-55."""
    platform = Platform("preview")
    platform.op.update(status="completed", stage="completed", cleanup_status="pending", failure={})
    executor = OperationExecutor(
        Config(data_root=tmp_path), platform=platform, runtime=SimpleNamespace(cleanup=lambda _: {"complete": True})
    )
    try:
        executor._failure(platform.op, None, ExecutionError("synthetic_cleanup_reason", tail="not a new failure"))
        assert platform.op["status"] == "completed" and platform.op["failure"] == {}
        assert platform.facts == [("completed", {"stopped": True, "cleanup_complete": True})]
    finally:
        executor.close()


def test_cleanup_retry_never_reuses_stale_stop_or_cleanup_flags(tmp_path):
    """F059 覆盖 AC: AC-48、AC-49、AC-52、AC-55."""
    platform = Platform("prepare")
    platform.op.update(
        status="failed",
        stage="failed",
        cleanup_status="pending",
        failure={"reason": "first_failure", "failed_stage": "preparing", "stopped": True, "cleanup_complete": True},
    )
    executor = OperationExecutor(
        Config(data_root=tmp_path), platform=platform, runtime=SimpleNamespace(cleanup=lambda _: {"complete": False})
    )
    try:
        executor._failure(platform.op, None, ExecutionError("retry"))
        assert platform.op["status"] == "failed" and platform.op["cleanup_status"] == "pending"
        assert platform.facts[-1][1] == {
            "reason": "first_failure",
            "failed_stage": "preparing",
            "stopped": False,
            "cleanup_complete": False,
        }
    finally:
        executor.close()


class CleanupClock:
    def __init__(self):
        self.now = datetime.now().timestamp()
        self.sleeps = []
        self.on_sleep = lambda: None

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        self.on_sleep()


def cleanup_runtime(platform, outcomes):
    calls = []
    remaining = iter(outcomes)
    delivery = {
        "mode": "bundle",
        "compiled_artifact_id": "compiled-a",
        "dependency_artifact_id": "dependency-a",
        "platform": "linux/amd64",
    }

    def prepare(_):
        calls.append("prepare")
        return deepcopy(delivery)

    def cleanup(_):
        calls.append("cleanup")
        return {"complete": next(remaining)}

    def launch(_, **kwargs):
        calls.append("launch")
        return {"exec_ref": "pod-a", "ready": True}

    def data(_, action, parameters):
        calls.append(action)
        return cleanup(None) if action == "finish-session" else {"exec_ref": "data-pod"}

    runtime = SimpleNamespace(
        prepare=prepare,
        cleanup=cleanup,
        launch=launch,
        data=data,
        _controller=lambda: {"holder_id": "holder-a", "controller_epoch": 1},
    )
    return runtime, calls, delivery


def cleanup_executor(tmp_path, platform, runtime, clock):
    return OperationExecutor(
        Config(data_root=tmp_path, node_id="node-a", executor_kind="kubernetes", protocol_version=2),
        platform=platform,
        runtime=runtime,
        clock=clock,
    )


@pytest.mark.parametrize("kind", ["prepare", "probe"])
def test_async_cleanup_false_stays_live_until_actual_completion(tmp_path, kind):
    """F059 覆盖 AC: AC-04、AC-49、AC-52、AC-55."""
    platform, clock = Platform(kind), CleanupClock()
    original_deadline = platform.op["deadline"]
    runtime, calls, delivery = cleanup_runtime(platform, [False, False, True])
    executor = cleanup_executor(tmp_path, platform, runtime, clock)

    def assert_live():
        assert platform.op["status"] == "running" and platform.op["stage"] in {"preparing", "ready"}
        assert not any(phase in {"failed", "completed"} for phase, _ in platform.facts)
        if kind == "prepare":
            assert platform.op["result"]["prepared_delivery"] == delivery

    clock.on_sleep = assert_live
    try:
        executor.execute("operation-a")
        assert platform.op["status"] == "completed" and platform.op["cleanup_status"] == "complete"
        assert platform.op["deadline"] == original_deadline
        assert calls.count("cleanup") == 3 and calls.count("prepare" if kind == "prepare" else "launch") == 1
        assert len(clock.sleeps) == 2
        assert not any(phase == "failed" for phase, _ in platform.facts)
    finally:
        executor.close()


@pytest.mark.parametrize("kind", ["prepare", "probe"])
def test_restart_resumes_prepared_or_ready_cleanup_without_reexecution(tmp_path, kind):
    """F059 覆盖 AC: AC-04、AC-49、AC-52、AC-55."""
    platform, clock = Platform(kind), CleanupClock()
    runtime, calls, delivery = cleanup_runtime(platform, [False, True])
    first = cleanup_executor(tmp_path, platform, runtime, clock)
    clock.on_sleep = first._closing.set
    first.execute("operation-a")
    assert platform.op["status"] == "running" and platform.op["stage"] == (
        "preparing" if kind == "prepare" else "ready"
    )
    assert not any(phase == "failed" for phase, _ in platform.facts)
    if kind == "prepare":
        assert platform.op["result"]["prepared_delivery"] == delivery
    first.close()
    clock.on_sleep = lambda: None
    second = cleanup_executor(tmp_path, platform, runtime, clock)
    try:
        second.execute("operation-a")
        assert platform.op["status"] == "completed"
        assert calls.count("prepare" if kind == "prepare" else "launch") == 1
        assert calls.count("cleanup") == 2
        if kind == "probe":
            assert [phase for phase, _ in platform.facts].count("starting") == 1
    finally:
        second.close()


@pytest.mark.parametrize("cause", ["cancel", "deadline", "fence"])
def test_cleanup_wait_keeps_original_cancel_deadline_and_ownership_fences(tmp_path, cause):
    """F059 覆盖 AC: AC-49、AC-52、AC-55."""
    platform, clock = Platform("prepare"), CleanupClock()
    if cause == "deadline":
        platform.op["deadline"] = datetime.utcfromtimestamp(clock.time() + 0.5).isoformat()
    original_deadline = platform.op["deadline"]
    runtime, calls, _ = cleanup_runtime(platform, [False] * 10)
    executor = cleanup_executor(tmp_path, platform, runtime, clock)

    def interrupt():
        if cause == "cancel":
            platform.op["payload"]["cancel_requested"] = True
        elif cause == "fence":
            platform.op["owner_epoch"] += 1

    clock.on_sleep = interrupt
    try:
        executor.execute("operation-a")
        assert platform.op["status"] != "completed" and platform.op["cleanup_status"] == "pending"
        assert platform.op["deadline"] == original_deadline and calls.count("prepare") == 1
        if cause == "fence":
            assert platform.op["status"] == "running" and platform.op["stage"] == "preparing"
            assert not any(phase in {"failed", "completed"} for phase, _ in platform.facts)
        else:
            assert not platform.facts[-1][1]["stopped"] and not platform.facts[-1][1]["cleanup_complete"]
            assert (
                platform.op["failure"]["reason"]
                == {"cancel": "operation_cancelled", "deadline": "operation_timeout"}[cause]
            )
    finally:
        executor.close()


def test_controller_lease_loss_during_cleanup_does_not_complete_operation(tmp_path):
    """F059 覆盖 AC: AC-49、AC-52、AC-55."""
    from runtime_manager.platform_client import PlatformError

    platform, clock = Platform("prepare"), CleanupClock()
    runtime, calls, _ = cleanup_runtime(platform, [False] * 10)
    lost = False

    def controller():
        if lost:
            raise PlatformError("controller_lease_lost", 409)
        return {"holder_id": "holder-a", "controller_epoch": 1}

    def lose():
        nonlocal lost
        lost = True

    runtime._controller = controller
    clock.on_sleep = lose
    executor = cleanup_executor(tmp_path, platform, runtime, clock)
    try:
        executor.execute("operation-a")
        assert platform.op["status"] == "running" and platform.op["stage"] == "preparing"
        assert calls.count("prepare") == 1 and not any(phase in {"failed", "completed"} for phase, _ in platform.facts)
    finally:
        executor.close()


@pytest.mark.parametrize("finished", ["done", "failed", "unknown"])
def test_data_finished_cleanup_wait_does_not_prepare_another_session(tmp_path, finished):
    """F059 覆盖 AC: AC-35、AC-49、AC-52、AC-55."""
    platform, clock = Platform("data"), CleanupClock()
    platform.op.update(status="running", stage="ready", result={"data_target": {"exec_ref": "existing-data-pod"}})
    platform.op["payload"]["data_action_finished"] = finished
    runtime, calls, _ = cleanup_runtime(platform, [False, True])
    executor = cleanup_executor(tmp_path, platform, runtime, clock)
    try:
        executor.execute("operation-a")
        assert "prepare-session" not in calls and calls.count("finish-session") == 2
        assert platform.op["status"] == ("completed" if finished == "done" else "failed")
        assert platform.op["cleanup_status"] == "complete"
        assert not any(phase in {"starting", "ready"} for phase, _ in platform.facts)
    finally:
        executor.close()


def test_old_execution_async_cleanup_waits_with_current_operation_fence(tmp_path):
    """F059 覆盖 AC: AC-33、AC-49、AC-52、AC-55."""
    platform, clock = Platform("stop"), CleanupClock()
    platform.op["status"] = "running"
    old = {**deepcopy(platform.op), "operation_id": "old-operation", "kind": "deploy", "status": "completed"}
    old["deadline"] = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    platform.node_snapshot = lambda: {"operations": [old]}
    platform.resources = lambda _: [{"kind": "Pod", "purpose": "serve", "resource_ref": "old-pod"}]
    calls, answers = [], iter([False, True])
    runtime = SimpleNamespace(
        _controller=lambda: {"holder_id": "holder-a", "controller_epoch": 1},
        request_stop=lambda ref, op: calls.append(("stop", ref, op["operation_id"])),
        confirm_stopped=lambda ref: {"stopped": True},
        cleanup=lambda op: calls.append(("cleanup", op["operation_id"])) or {"complete": next(answers)},
    )
    executor = cleanup_executor(tmp_path, platform, runtime, clock)
    try:
        executor.stop_instances(platform.op)
        assert calls == [("stop", "old-pod", "operation-a"), ("cleanup", "old-operation"), ("cleanup", "old-operation")]
        assert clock.sleeps == [0.5] and platform.op["status"] == "running"
    finally:
        executor.close()


@pytest.mark.parametrize("saved", [None, [], {}])
def test_invalid_prepared_fact_cannot_trigger_rebuild_or_completion(tmp_path, saved):
    """F059 覆盖 AC: AC-04、AC-49、AC-52、AC-55."""
    platform, clock = Platform("prepare"), CleanupClock()
    platform.op.update(status="running", stage="preparing", result={"prepared_delivery": saved})
    runtime, calls, _ = cleanup_runtime(platform, [False])
    executor = cleanup_executor(tmp_path, platform, runtime, clock)
    try:
        executor.execute("operation-a")
        assert "prepare" not in calls and platform.op["status"] == "failed"
        assert platform.op["failure"]["reason"] == "prepared_delivery_invalid"
        assert not platform.facts[-1][1]["stopped"]
    finally:
        executor.close()


def test_lost_prepared_fact_reply_adopts_only_exact_committed_delivery(tmp_path, monkeypatch):
    """F059 覆盖 AC: AC-04、AC-49、AC-52、AC-55."""
    platform, clock = Platform("prepare"), CleanupClock()
    runtime, calls, delivery = cleanup_runtime(platform, [False, True])
    original = platform.fact
    lost = False

    def accepted(operation, sequence, phase, **kwargs):
        nonlocal lost
        result = original(operation, sequence, phase, **kwargs)
        if phase == "preparing" and "prepared_delivery" in kwargs.get("detail", {}) and not lost:
            lost = True
            raise PlatformError("platform_unreachable", 503)
        return result

    monkeypatch.setattr(platform, "fact", accepted)
    executor = cleanup_executor(tmp_path, platform, runtime, clock)
    try:
        executor.execute("operation-a")
        assert platform.op["status"] == "completed" and calls.count("prepare") == 1
        assert platform.op["result"]["delivery"] == delivery
    finally:
        executor.close()


def test_prepare_progress_survives_prepared_result_fact_and_restart(tmp_path):
    """F059 覆盖 AC: AC-04、AC-49、AC-52、AC-55."""
    platform, clock = Platform("prepare"), CleanupClock()
    progress = {
        stage: {"exec_ref": stage + "-pod", "result": {"phase": stage}}
        for stage in ("inputs", "resolve", "install", "upload")
    }
    platform.op.update(status="running", stage="preparing", result={"prepare_progress": deepcopy(progress)})
    runtime, calls, delivery = cleanup_runtime(platform, [False, True])
    first = cleanup_executor(tmp_path, platform, runtime, clock)
    clock.on_sleep = first._closing.set
    first.execute("operation-a")
    assert platform.op["result"]["prepare_progress"] == progress
    assert platform.op["result"]["prepared_delivery"] == delivery
    first.close()
    second = cleanup_executor(tmp_path, platform, runtime, clock)
    clock.on_sleep = lambda: None
    try:
        second.execute("operation-a")
        assert platform.op["status"] == "completed" and calls.count("prepare") == 1
        assert platform.op["result"]["prepare_progress"] == progress
    finally:
        second.close()


def test_cleanup_completion_after_original_deadline_is_not_reported_success(tmp_path):
    """F059 覆盖 AC: AC-49、AC-52、AC-55."""
    platform, clock = Platform("prepare"), CleanupClock()
    platform.op["deadline"] = datetime.utcfromtimestamp(clock.time() + 0.5).isoformat()
    runtime, _, _ = cleanup_runtime(platform, [])

    def late(_):
        clock.now += 1
        return {"complete": True}

    runtime.cleanup = late
    executor = cleanup_executor(tmp_path, platform, runtime, clock)
    try:
        executor.execute("operation-a")
        assert platform.op["status"] == "timed_out"
        assert platform.op["failure"]["reason"] == "operation_timeout"
        assert not any(phase == "completed" for phase, _ in platform.facts)
    finally:
        executor.close()


@pytest.mark.parametrize("finished", ["done", "failed", "unknown"])
def test_active_data_session_waits_for_async_finish_without_repreparing(tmp_path, finished):
    """F059 覆盖 AC: AC-35、AC-49、AC-52、AC-55."""
    platform, clock = Platform("data"), CleanupClock()
    runtime, calls, _ = cleanup_runtime(platform, [False, True])
    clock.on_sleep = lambda: platform.op["payload"].update(data_action_finished=finished)
    executor = cleanup_executor(tmp_path, platform, runtime, clock)
    try:
        executor.execute("operation-a")
        assert calls.count("prepare-session") == 1 and calls.count("finish-session") == 2
        assert platform.op["status"] == ("completed" if finished == "done" else "failed")
        if finished == "unknown":
            assert platform.op["failure"]["reason"] == "data_result_unknown"
    finally:
        executor.close()


def test_cleanup_exception_is_not_retried_as_success(tmp_path):
    """F059 覆盖 AC: AC-49、AC-52、AC-55."""
    platform, clock = Platform("prepare"), CleanupClock()
    runtime, calls, _ = cleanup_runtime(platform, [])

    def uncertain(_):
        calls.append("cleanup-error")
        raise ExecutionError("cleanup_api_failed")

    runtime.cleanup = uncertain
    executor = cleanup_executor(tmp_path, platform, runtime, clock)
    try:
        executor.execute("operation-a")
        assert platform.op["status"] == "failed" and platform.op["cleanup_status"] == "pending"
        assert platform.op["failure"]["reason"] == "cleanup_api_failed"
        assert not platform.facts[-1][1]["stopped"] and not clock.sleeps
    finally:
        executor.close()


@pytest.mark.parametrize("kind", ["prepare", "probe"])
def test_docker_async_cleanup_uses_same_wait_without_kubernetes_authority(tmp_path, kind):
    """F059 覆盖 AC: AC-49、AC-52、AC-55、AC-56."""
    platform, clock = Platform(kind), CleanupClock()
    runtime, calls, _ = cleanup_runtime(platform, [False, True])
    runtime._controller = lambda: pytest.fail("Docker must not claim Kubernetes control authority")
    runtime.cleanup_local_scratch = lambda _: calls.append("local-scratch")
    executor = OperationExecutor(
        Config(data_root=tmp_path, node_id="node-a", protocol_version=2),
        platform=platform,
        runtime=runtime,
        clock=clock,
    )
    try:
        executor.execute("operation-a")
        assert platform.op["status"] == "completed" and calls.count("cleanup") == 2
        assert calls.count("prepare" if kind == "prepare" else "launch") == 1
        assert calls[-1] == "local-scratch"
    finally:
        executor.close()

"""F115 current execution facts: AC-01 through AC-10, never historical guesses."""

from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from runtime_manager.api import platform_observe
from runtime_manager.config import Config
from runtime_manager.container_runner import OP_LABEL
from runtime_manager.executors.docker import DockerExecutor
from runtime_manager.executors.kubernetes import KubernetesExecutor


@pytest.fixture
def docker_service(tmp_path, monkeypatch):
    scope = {"app_id": "app-a", "node_id": "node-a", "operation_id": "op-a", "exec_ref": "container-a", "generation": 2}
    raw = {
        "Config": {
            "Labels": {
                "bisheng.runtime.node": "node-a",
                "bisheng.app.id": "app-a",
                "bisheng.managed": "v2",
                OP_LABEL: "op-a",
            }
        },
        "State": {"Running": True, "StartedAt": "2026-10-30T10:33:15.363879485Z"},
        "RestartCount": 0,
        "NetworkSettings": {"Networks": {"bisheng-apps": {"IPAddress": "127.0.0.2"}}},
    }

    class Platform:
        def application(self, app_id):
            assert app_id == "app-a"
            return dict(scope)

        def operation(self, operation_id):
            assert operation_id == "op-a"
            return {"operation_id": "op-a", "app_id": "app-a", "stage": "serving", "payload": {"port": 8080}}

    class Docker:
        def inspect_container(self, ref):
            assert ref == "container-a"
            return deepcopy(raw)

    config = Config(node_id="node-a", data_root=tmp_path, network="bisheng-apps")
    executor = DockerExecutor(config, Platform(), Docker())
    service = SimpleNamespace(config=config, platform=executor.platform, docker=executor.docker, runtime=executor)
    monkeypatch.setattr(platform_observe, "executor", lambda: service)
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: SimpleNamespace(status_code=200))
    return service, raw, scope


@pytest.mark.asyncio
async def test_current_http_health_and_real_zero_without_native_health(docker_service):
    result = await platform_observe.status("app-a")
    assert result["health"] == "healthy"
    assert result["restart_count"] == 0
    assert result["started_at"].startswith("2026-10-30T10:33:15.363")
    assert result["observation_state"] == "current"


@pytest.mark.asyncio
async def test_missing_count_is_unknown_not_zero(docker_service):
    _, raw, _ = docker_service
    raw.pop("RestartCount")
    raw["State"]["StartedAt"] = "0001-01-01T00:00:00Z"
    result = await platform_observe.status("app-a")
    assert result["restart_count"] is None and result["started_at"] is None


@pytest.mark.asyncio
async def test_failed_probe_is_not_healthy(docker_service, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: SimpleNamespace(status_code=503))
    result = await platform_observe.status("app-a")
    assert result["health"] == "unhealthy"


@pytest.mark.asyncio
async def test_stopped_execution_is_not_healthy(docker_service):
    _, raw, _ = docker_service
    raw["State"]["Running"] = False
    result = await platform_observe.status("app-a")
    assert result["phase"] == "stopped" and result["health"] is None


@pytest.mark.asyncio
async def test_no_binding_has_no_historical_facts(docker_service):
    _, _, scope = docker_service
    scope["exec_ref"] = None
    result = await platform_observe.status("app-a")
    assert result["observation_state"] == "no_execution"
    assert result["instance_id"] is None and result["restart_count"] is None


@pytest.mark.asyncio
async def test_changed_binding_cannot_mix_facts(docker_service, monkeypatch):
    service, _, _scope = docker_service
    previous = service.platform.application
    calls = []

    def application(app_id):
        calls.append(app_id)
        result = previous(app_id)
        if len(calls) > 1:
            result["generation"] += 1
        return result

    monkeypatch.setattr(service.platform, "application", application)
    with pytest.raises(Exception, match=r"assignment|binding"):
        await platform_observe.status("app-a")


def test_observe_never_counts_native_health_as_application_success(docker_service, monkeypatch):
    service, raw, _ = docker_service
    raw["State"]["Health"] = {"Status": "healthy"}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: SimpleNamespace(status_code=503))
    observed = service.runtime.observe("container-a")
    assert not observed["ready"] and observed["probe_state"] == "failed"


def test_stopped_instance_does_not_keep_a_failed_probe_phase():
    from runtime_manager.observation import public_status

    value = public_status("app-a", {}, {"running": False, "probe_state": "failed"})
    assert value["phase"] == "stopped" and value["health"] is None


def test_k8s_status_only_exact_pod_absence_is_missing(monkeypatch):
    from runtime_manager.executors.kubernetes import KubernetesExecutor
    from runtime_manager.k8s_client import KubernetesAPIError

    executor = object.__new__(KubernetesExecutor)
    executor.platform = SimpleNamespace(resource=lambda _: {"resource_ref": "pod-a"})

    def absent(_):
        raise KubernetesAPIError("fixture pod absent", 404)

    monkeypatch.setattr(executor, "_fresh", absent)
    assert executor.observe_status("pod-a") is None
    monkeypatch.setattr(executor, "_fresh", lambda _: {})
    monkeypatch.setattr(executor, "_observed", lambda *_: absent(None))
    with pytest.raises(KubernetesAPIError):
        executor.observe_status("pod-a")


@pytest.mark.parametrize(
    "app_status,expected_count,expected_time",
    [
        (
            {"name": "app", "restartCount": 3, "state": {"running": {"startedAt": "2026-11-01T01:02:03Z"}}},
            3,
            "2026-11-01T01:02:03Z",
        ),
        ({"name": "app", "restartCount": 0, "state": {}}, 0, None),
        ({}, None, None),
    ],
)
def test_kubernetes_only_current_app_container(app_status, expected_count, expected_time):
    runtime = object.__new__(KubernetesExecutor)
    runtime.platform = SimpleNamespace(resources=lambda op: [])
    runtime.client = SimpleNamespace()
    row = {"resource_ref": "pod-a", "uid": "uid-a", "operation_id": "op-a"}
    pod = {
        "metadata": {},
        "status": {
            "phase": "Running",
            "containerStatuses": [app_status],
            "initContainerStatuses": [{"name": "init", "restartCount": 99}],
            "startTime": "2020-01-01T00:00:00Z",
        },
    }
    result = runtime._observed(row, pod)
    assert result["restart_count"] == expected_count
    assert result["started_at"] == expected_time
    assert result["probe_state"] == "unknown"

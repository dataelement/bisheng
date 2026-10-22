"""Covers AC-01, AC-02, AC-07, AC-10, AC-13, AC-19, AC-20, AC-30, AC-31, AC-32, AC-36, AC-37, AC-40, AC-53, AC-55."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from runtime_manager.config import Config
from runtime_manager.errors import NotFoundError
from runtime_manager.executors.kubernetes import KubernetesExecutor
from runtime_manager.k8s_capabilities import REQUIRED_CHECKS, descriptor_digest
from runtime_manager.k8s_client import KubernetesAPIError
from runtime_manager.k8s_config import KubernetesConfig


@pytest.fixture
def service(tmp_path, monkeypatch):
    from runtime_manager.api import platform_observe as api

    scope = {"app_id": "app-a", "node_id": "node-a", "operation_id": "op-a", "exec_ref": "pod-a", "generation": 2}
    resource = {
        "resource_ref": "pod-a",
        "app_id": "app-a",
        "node_id": "node-a",
        "operation_id": "op-a",
        "kind": "Pod",
        "uid": "uid-a",
    }
    calls = []

    config = Config(executor_kind="kubernetes", protocol_version=2, data_root=tmp_path, node_id="node-a")
    clock = SimpleNamespace(value=101100.0)
    clock.time = lambda: clock.value
    document = {
        "schema_version": 1,
        "cluster_id": "cluster-a",
        "namespace": "runtime-apps",
        "platform": "linux/amd64",
        "memory_budget_mb": 4096,
        "cpu_budget_millicores": 4000,
        "status_policy_revision": "v1",
        "cni_username": "system:serviceaccount:kube-system:cni",
        "storage_controller_usernames": ["system:persistent-volume-binder"],
        "storage": {"sqlite_compatible": True, "filesystem": "ext4"},
    }
    document["probe_report"] = {
        "source": "cluster-probe",
        "observed_at": 100000,
        "descriptor_digest": descriptor_digest(document),
        "checks": [{"name": name, "ok": True, "evidence": {"uid": str(uuid4())}} for name in sorted(REQUIRED_CHECKS)],
    }
    descriptor = tmp_path / "descriptor.json"
    descriptor.write_text(json.dumps(document))
    settings = KubernetesConfig(namespace="runtime-apps", cluster_id="cluster-a", descriptor_file=descriptor)

    class ReadOnlyCluster:
        available = True

        def list(self, resource, *, label_selector):
            assert resource == "pods" and label_selector == "bisheng.managed=v2"
            if not self.available:
                raise KubernetesAPIError("fixture-sensitive-cluster-error", 503)
            return {"items": []}

    class Runtime(KubernetesExecutor):
        def observe(self, ref):
            return {"exec_ref": ref, "ready": True, "running": True, "phase": "Running", "restart_count": 2}

        def logs(self, ref, **kwargs):
            calls.append((ref, kwargs))
            return "INFO booted\nERROR fixture-business-token https://user:password@example.invalid/x\n"

    class Platform:
        def application(self, app_id):
            return dict(scope)

        def resource(self, ref):
            return dict(resource)

        def operation(self, ident):
            return {"payload": {"runtime_env": {"BISHENG_APP_TOKEN": "fixture-business-token"}}}

        def node_snapshot(self):
            return {
                "capacity": {"memory_budget_mb": 4096, "committed_mb": 512, "committed_cpu": 0.25, "instances": 1},
                "operations": [],
                "node": {"status": "ready"},
            }

    svc = SimpleNamespace(
        config=config,
        platform=Platform(),
    )
    svc.runtime = Runtime(config, settings, platform=svc.platform, client=ReadOnlyCluster(), clock=clock)
    monkeypatch.setattr(api, "executor", lambda: svc)
    return api, svc, scope, resource, calls


async def test_k8s_status_preserves_public_shape_without_docker(service):
    api, _, _, _, _ = service
    result = await api.status("app-a")
    assert result["phase"] == "running" and result["generation"] == 2
    assert result["instance_id"] == "pod-a" and result["restart_count"] == 2
    assert "containers" not in result and "namespace" not in result


@pytest.mark.parametrize("field,value", [("app_id", "other"), ("node_id", "other"), ("operation_id", "other")])
def test_logs_and_status_refuse_foreign_assignment(service, field, value):
    api, _, _, resource, _ = service
    resource[field] = value
    with pytest.raises(NotFoundError):
        api.record("app-a")


async def test_logs_use_bounded_runtime_access_and_redact_injected_credentials(service):
    api, _, _, _, calls = service
    result = await api.logs("app-a", tail=100000, since="30m", keyword="error")
    assert len(result["lines"]) == 1 and "ERROR" in result["lines"][0]
    assert "fixture-business-token" not in str(result) and "password" not in str(result)
    assert calls[0][0] == "pod-a" and calls[0][1]["tail"] == 1000
    assert isinstance(calls[0][1]["since"], int)


def test_runtime_status_reports_platform_capacity_and_live_prerequisites(service):
    api, svc, _, _, _ = service
    assert "ready" not in svc.runtime.document["probe_report"]
    result = api.runtime_snapshot()
    assert result["executor_kind"] == "kubernetes"
    assert result["backend_available"] is True and result["ready"] is True
    assert result["capacity"]["mem_available_mb"] == 3584
    assert result["capacity"]["instances"] == 1


@pytest.mark.parametrize("hint", [False, True])
def test_runtime_status_uses_assessed_report_instead_of_raw_ready_hint(service, hint):
    """AC-30, AC-31: installer evidence, rather than a raw boolean, determines readiness."""
    api, svc, _, _, _ = service
    path = svc.runtime.settings.descriptor_file
    document = json.loads(path.read_text())
    document["probe_report"]["ready"] = hint
    path.write_text(json.dumps(document))
    result = api.runtime_snapshot()
    assert result["ready"] is True
    assert next(check for check in result["preflight"] if check["name"] == "runtime_prerequisites")["ok"] is True


@pytest.mark.parametrize(
    "failure",
    ["expired", "cni-identity", "storage-identity", "mandatory-check", "cluster-api", "descriptor-unavailable"],
)
def test_runtime_status_fails_closed_when_live_assessment_changes(service, failure):
    """AC-13, AC-19, AC-20, AC-30, AC-31: unsafe or unavailable live evidence cannot reuse a raw ready hint."""
    api, svc, _, _, _ = service
    path = svc.runtime.settings.descriptor_file
    document = json.loads(path.read_text())
    document["probe_report"]["ready"] = True
    if failure == "expired":
        svc.runtime.clock.value = document["probe_report"]["observed_at"] + 86401
    elif failure == "cni-identity":
        document["cni_username"] = "system:serviceaccount:kube-system:replacement-cni"
    elif failure == "storage-identity":
        document["storage_controller_usernames"] = ["system:serviceaccount:kube-system:persistent-volume-binder"]
    elif failure == "mandatory-check":
        next(check for check in document["probe_report"]["checks"] if check["name"] == "network-direct-denied")[
            "ok"
        ] = False
    elif failure == "cluster-api":
        svc.runtime.client.available = False
    path.write_text(json.dumps(document))
    if failure == "descriptor-unavailable":
        path.unlink()
    result = api.runtime_snapshot()
    assert result["ready"] is False
    assert result["backend_available"] is (failure != "cluster-api")
    assert next(check for check in result["preflight"] if check["name"] == "runtime_prerequisites")["ok"] is False
    assert "fixture-sensitive" not in str(result)


def test_runtime_status_refreshes_projected_report_before_assessment(service):
    """AC-30, AC-31: a fresh projection recovers expired evidence without changing the descriptor."""
    api, svc, _, _, _ = service
    path = svc.runtime.settings.descriptor_file
    document = json.loads(path.read_text())
    svc.runtime.clock.value = document["probe_report"]["observed_at"] + 86401
    assert api.runtime_snapshot()["ready"] is False
    document["probe_report"]["observed_at"] = svc.runtime.clock.value
    path.write_text(json.dumps(document))
    assert "ready" not in document["probe_report"]
    assert api.runtime_snapshot()["ready"] is True


def test_failed_platform_read_never_falls_back_to_descriptor_capacity(service, monkeypatch):
    api, svc, _, _, _ = service

    def unavailable():
        raise RuntimeError("sensitive remote response")

    monkeypatch.setattr(svc.platform, "node_snapshot", unavailable)
    result = api.runtime_snapshot()
    assert result["ready"] is False and result["capacity"]["readable"] is False
    assert "sensitive" not in str(result)


def test_k8s_composition_omits_v1_and_keeps_only_liveness_public(monkeypatch):
    from runtime_manager.main import create_app

    config = Config(executor_kind="kubernetes", protocol_version=2, reconcile_enabled=False)
    monkeypatch.setattr("runtime_manager.api.operations.get_config", lambda: config)
    app = create_app(config)
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
    for path in ("/v1/intents/deploy", "/v1/intents/build"):
        assert client.post(path, json={}).status_code == 404
    assert client.get("/v2/runtime/capabilities").status_code in {401, 403}

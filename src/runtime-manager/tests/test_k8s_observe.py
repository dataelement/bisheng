"""Covers AC-33, AC-35, AC-01, AC-02, AC-07, AC-10, AC-13, AC-19, AC-20, AC-30, AC-31, AC-32, AC-36, AC-37, AC-40, AC-53, AC-55."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from runtime_manager.config import Config
from runtime_manager.errors import NotFoundError
from runtime_manager.executors.kubernetes import KubernetesExecutor
from runtime_manager.k8s_capabilities import REQUIRED_CHECKS, descriptor_digest
from runtime_manager.k8s_client import KubernetesAPIError
from runtime_manager.k8s_config import KubernetesConfig
from runtime_manager.platform_client import PREFIX, PlatformClient
from runtime_manager.platform_protocol import signed_headers


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


@pytest.fixture
def observed_application_http(tmp_path, monkeypatch):
    """Real signed ASGI requests and real PlatformClient; no replacement record()."""
    from runtime_manager.api import operations
    from runtime_manager.api import platform_observe as api
    from runtime_manager.container_runner import OP_LABEL
    from runtime_manager.main import create_app

    clients = []
    platforms = []

    def create(kind, *, application=None, resource=None, healthy=True):
        ref = "11111111-1111-4111-8111-111111111111"
        scope = {"app_id": "app-a", "node_id": "node-a", "operation_id": "op-a", "exec_ref": ref, "generation": 2}
        config = Config(
            executor_kind=kind,
            protocol_version=2,
            reconcile_enabled=False,
            data_root=tmp_path,
            node_id="node-a",
            platform_base_url="http://fixture-platform",
            platform_key_id="fixture-node",
            platform_secret="fixture-platform-secret",
            inbound_key_id="fixture-backend",
            inbound_secret="fixture-inbound-secret",
        )
        requests, executions = [], []

        def reply(request):
            requests.append((request.method, request.url.path))
            if request.url.path == PREFIX + "/nonces":
                assert request.method == "POST"
                return httpx.Response(200, json={"accepted": True})
            assert request.method == "GET", "observation must not mutate an application"
            if request.url.path == PREFIX + "/apps/app-a/execution":
                if isinstance(application, Exception):
                    raise application
                return application if application is not None else httpx.Response(200, json=scope)
            if request.url.path == PREFIX + "/resources/" + ref:
                if isinstance(resource, Exception):
                    raise resource
                return (
                    resource
                    if resource is not None
                    else httpx.Response(
                        200,
                        json={
                            "resource_ref": ref,
                            "app_id": "app-a",
                            "node_id": "node-a",
                            "operation_id": "op-a",
                            "kind": "Pod",
                            "uid": "22222222-2222-4222-8222-222222222222",
                        },
                    )
                )
            if request.url.path == PREFIX + "/operations/op-a":
                return httpx.Response(
                    200,
                    json={
                        "node_id": "node-a",
                        "payload": {"runtime_env": {"BISHENG_APP_TOKEN": "fixture-business-token"}},
                    },
                )
            pytest.fail("unexpected platform endpoint")

        class Engine:
            def inspect_container(self, reference):
                assert reference == ref
                executions.append(("docker-inspect", reference))
                return {
                    "Config": {
                        "Labels": {"bisheng.runtime.node": "node-a", OP_LABEL: "op-a"},
                        "Env": ["BISHENG_APP_TOKEN=fixture-business-token"],
                    },
                    "State": {"Running": healthy, "Health": {"Status": "healthy" if healthy else "unhealthy"}},
                    "RestartCount": 2,
                }

            def container_logs(self, reference, **kwargs):
                assert reference == ref
                executions.append(("docker-logs", reference))
                return "INFO fixture-business-token\n"

        class Runtime:
            def observe(self, reference):
                assert reference == ref
                executions.append(("k8s-observe", reference))
                return {"ready": healthy, "restart_count": 2}

            def logs(self, reference, **kwargs):
                assert reference == ref
                executions.append(("k8s-logs", reference))
                return "INFO fixture-business-token\n"

        platform = PlatformClient(config, transport=httpx.MockTransport(reply))
        platforms.append(platform)
        svc = SimpleNamespace(config=config, platform=platform, docker=Engine(), runtime=Runtime())
        monkeypatch.setattr(api, "executor", lambda: svc)
        monkeypatch.setattr(operations, "executor", lambda: svc)
        monkeypatch.setattr(operations, "get_config", lambda: config)
        client = TestClient(create_app(config), raise_server_exceptions=False)
        clients.append(client)

        def get(suffix):
            path = "/v2/apps/app-a/" + suffix
            return client.get(
                path,
                headers=signed_headers("GET", path, b"", key_id=config.inbound_key_id, secret=config.inbound_secret),
            )

        return get, requests, executions, scope

    yield create
    for client in clients:
        client.close()
    for platform in platforms:
        platform.close()


@pytest.mark.parametrize("kind", ["docker", "kubernetes"])
@pytest.mark.parametrize("suffix", ["status", "logs"])
def test_exact_unassigned_application_is_not_found_over_real_client_and_asgi(observed_application_http, kind, suffix):
    """覆盖 AC: AC-01、AC-33、AC-35、AC-36、AC-55."""
    get, requests, executions, _ = observed_application_http(
        kind, application=httpx.Response(404, json={"error": {"reason": "application_not_found"}})
    )
    response = get(suffix)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"
    assert [path for method, path in requests if method == "GET"] == [PREFIX + "/apps/app-a/execution"]
    assert not executions


@pytest.mark.parametrize("kind", ["docker", "kubernetes"])
@pytest.mark.parametrize("suffix", ["status", "logs"])
@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(404, json={"error": {"reason": "resource_not_found"}}),
        httpx.Response(403, json={"error": {"reason": "application_not_found"}}),
        httpx.Response(503, json={"error": {"reason": "application_not_found"}}),
        httpx.Response(403, json={"error": {"reason": "private-permission-detail"}}),
        httpx.Response(503, json={"error": {"reason": "private-platform-detail"}}),
        httpx.ReadTimeout("private-platform-timeout"),
    ],
    ids=["wrong-404-reason", "same-reason-403", "same-reason-503", "permission", "unavailable", "timeout"],
)
def test_platform_failures_are_not_reported_as_missing_instances(observed_application_http, kind, suffix, failure):
    """覆盖 AC: AC-01、AC-33、AC-35、AC-36、AC-55."""
    get, requests, executions, _ = observed_application_http(kind, application=failure)
    response = get(suffix)
    assert response.status_code == 500
    assert "not_found" not in response.text and "private-" not in response.text
    assert [path for method, path in requests if method == "GET"] == [PREFIX + "/apps/app-a/execution"]
    assert not executions


@pytest.mark.parametrize("suffix", ["status", "logs"])
@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(404, json={"error": {"reason": "application_not_found"}}),
        httpx.Response(503, json={"error": {"reason": "private-resource-detail"}}),
        httpx.ReadTimeout("private-resource-timeout"),
    ],
    ids=["resource-404", "resource-503", "resource-timeout"],
)
def test_resource_failures_are_not_application_absence(observed_application_http, suffix, failure):
    """覆盖 AC: AC-01、AC-33、AC-35、AC-36、AC-55."""
    get, requests, executions, scope = observed_application_http("kubernetes", resource=failure)
    response = get(suffix)
    assert response.status_code == 500
    assert "not_found" not in response.text and "private-" not in response.text
    assert [path for method, path in requests if method == "GET"] == [
        PREFIX + "/apps/app-a/execution",
        PREFIX + "/resources/" + scope["exec_ref"],
    ]
    assert not executions


@pytest.mark.parametrize("kind", ["docker", "kubernetes"])
@pytest.mark.parametrize("healthy", [True, False])
def test_assigned_instance_and_logs_retain_public_shape_with_real_platform_client(
    observed_application_http, kind, healthy
):
    """覆盖 AC: AC-01、AC-33、AC-35、AC-36、AC-55."""
    get, _, executions, scope = observed_application_http(kind, healthy=healthy)
    response = get("status")
    assert response.status_code == 200
    assert response.json() == {
        "app_id": "app-a",
        "phase": "running" if healthy else "unhealthy",
        "generation": 2,
        "instance_id": scope["exec_ref"],
        "health": "healthy" if healthy else "unhealthy",
        "restart_count": 2,
    }
    logs = get("logs")
    assert logs.status_code == 200 and set(logs.json()) == {"app_id", "lines"}
    assert logs.json()["app_id"] == "app-a" and len(logs.json()["lines"]) == 1
    assert "fixture-business-token" not in logs.text
    assert any(call[0] == ("docker-logs" if kind == "docker" else "k8s-logs") for call in executions)


@pytest.mark.parametrize("kind", ["docker", "kubernetes"])
@pytest.mark.parametrize("suffix", ["status", "logs"])
def test_assignment_without_execution_still_reports_not_found(observed_application_http, kind, suffix):
    """覆盖 AC: AC-01、AC-33、AC-35、AC-36、AC-55."""
    get, _, executions, _ = observed_application_http(
        kind, application=httpx.Response(200, json={"app_id": "app-a", "node_id": "node-a", "exec_ref": None})
    )
    response = get(suffix)
    assert response.status_code == 404 and response.json()["detail"]["code"] == "not_found"
    assert not executions

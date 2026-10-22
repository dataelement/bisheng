"""覆盖 AC: AC-02、AC-07、AC-10、AC-30、AC-31、AC-32、AC-36、AC-37、AC-40、AC-53."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from runtime_manager.config import Config
from runtime_manager.errors import NotFoundError


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

    class Runtime:
        descriptor = SimpleNamespace(memory_budget_mb=4096, cpu_budget_millicores=4000)
        document = {
            "probe_report": {"ready": True, "checks": [{"name": "isolation", "ok": True, "detail": "verified"}]},
            "storage": {"sqlite_compatible": True},
        }

        def capabilities(self):
            return {
                "executor_kind": "kubernetes",
                "orchestration_available": True,
                "mandatory_isolation": True,
                "status_protection": True,
                "binding_protection": True,
            }

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
        config=Config(executor_kind="kubernetes", protocol_version=2, data_root=tmp_path, node_id="node-a"),
        platform=Platform(),
        runtime=Runtime(),
    )
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
    api, _, _, _, _ = service
    result = api.runtime_snapshot()
    assert result["executor_kind"] == "kubernetes"
    assert result["backend_available"] is True and result["ready"] is True
    assert result["capacity"]["mem_available_mb"] == 3584
    assert result["capacity"]["instances"] == 1


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

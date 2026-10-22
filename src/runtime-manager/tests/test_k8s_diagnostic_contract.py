"""覆盖 AC: AC-03、AC-48、AC-49、AC-52."""

import copy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import certifi
import httpx
import pytest

from runtime_manager.executors.kubernetes import KubernetesExecutor
from runtime_manager.executors.protocol import ExecutorError
from runtime_manager.k8s_client import KubernetesClient
from runtime_manager.k8s_config import KubernetesConfig
from runtime_manager.k8s_templates import RESOURCE_LABEL, PodPlan, pod_template


@pytest.fixture
def diagnostic(tmp_path):
    token = tmp_path / "token"
    token.write_text("test.diagnostic.token")
    settings = KubernetesConfig(
        namespace="bisheng-runtime-apps",
        cluster_id="cluster-a",
        descriptor_file=tmp_path / "descriptor.json",
        token_file=token,
        ca_file=Path(certifi.where()),
        api_server="https://cluster.invalid",
    )
    plan = PodPlan(
        namespace=settings.namespace,
        app_id="app-a",
        operation_id="operation-a",
        resource_ref="ref-a",
        node_id="node-a",
        generation=1,
        owner_epoch=1,
        purpose="prepare-download",
        platform="linux/amd64",
        status_policy_revision="v1",
        image="example/runtime@sha256:" + "a" * 64,
        helper_image="example/helper@sha256:" + "b" * 64,
        command=("python", "main.py"),
        memory_mb=512,
        cpu_millicores=250,
        deadline_seconds=60,
        scratch_pvc="scratch-a",
        material_secret="material-a",
    )
    pod = pod_template(plan)
    pod["metadata"].update(uid="actual-pod-uid", resourceVersion="17")
    pod["status"] = {"phase": "Failed"}
    row = {
        "resource_ref": plan.resource_ref,
        "namespace": settings.namespace,
        "name": plan.name,
        "kind": "Pod",
        "uid": "actual-pod-uid",
    }
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/log"):
            return httpx.Response(200, text=request.url.params["container"] + " failed fixture-business-secret")
        assert request.url.path == f"/api/v1/namespaces/{settings.namespace}/pods/{plan.name}"
        return httpx.Response(200, json=pod)

    client = KubernetesClient(settings, transport=httpx.MockTransport(handler), sleep=lambda _: None)
    executor = object.__new__(KubernetesExecutor)
    executor.client = client
    executor.config = SimpleNamespace(build_index_url="", build_extra_index_url="", build_npm_registry="")
    operation = {
        "operation_id": plan.operation_id,
        "deadline": datetime.fromtimestamp(1792555200 + 1800, UTC).isoformat(),
        "payload": {"runtime_env": {"BISHENG_APP_TOKEN": "fixture-business-secret"}},
    }
    executor.platform = SimpleNamespace(resource=lambda _: copy.deepcopy(row), operation=lambda _: operation)
    executor.clock = SimpleNamespace(time=lambda: 1792555200)
    yield executor, operation, plan, pod, row, calls
    client.close()


def test_failed_preparation_preserves_reason_and_real_fixed_container_diagnostics(diagnostic, monkeypatch):
    """覆盖 AC: AC-03、AC-48、AC-49、AC-52."""
    executor, operation, plan, pod, row, calls = diagnostic
    monkeypatch.setattr(executor, "_intent", lambda *_: row)
    monkeypatch.setattr(executor, "_volume", lambda *_: None)
    monkeypatch.setattr(executor, "_material", lambda *_: None)
    monkeypatch.setattr(executor, "_create", lambda *_: pod)
    monkeypatch.setattr(executor, "_controller", lambda: {})
    with pytest.raises(ExecutorError, match=r"^preparation_phase_failed$") as caught:
        executor._phase(operation, "inputs", "prepare-download", {}, plan=plan)
    assert "storage-guard:" in caught.value.tail and "transfer:" in caught.value.tail
    assert "fixture-business-secret" not in caught.value.tail
    logs = [request for request in calls if request.url.path.endswith("/log")]
    assert [request.url.params["container"] for request in logs] == ["storage-guard", "transfer"]
    assert all(
        request.url.params["tailLines"] == "80" and request.url.params["limitBytes"] == "1048576" for request in logs
    )


@pytest.mark.parametrize("changed", ["uid", "namespace", "resource_ref"])
def test_diagnostic_rejects_changed_resource_identity_before_logs(diagnostic, changed):
    """覆盖 AC: AC-03、AC-48、AC-49、AC-52."""
    executor, operation, plan, pod, _, calls = diagnostic
    if changed == "resource_ref":
        pod["metadata"]["labels"][RESOURCE_LABEL] = "foreign-ref"
    else:
        pod["metadata"][changed] = "foreign-value"
    assert executor._diagnostic(operation, plan.resource_ref) == "Execution observation unavailable"
    assert calls and not any(request.url.path.endswith("/log") for request in calls)


def test_unknown_container_validation_is_not_swallowed_by_diagnostic(diagnostic):
    """覆盖 AC: AC-03、AC-48、AC-49、AC-52."""
    executor, operation, plan, pod, _, calls = diagnostic
    pod["spec"]["initContainers"] = [{"name": "custom-unregistered"}]
    with pytest.raises(ValueError, match="k8s_log_container_invalid"):
        executor._diagnostic(operation, plan.resource_ref)
    assert not any(request.url.path.endswith("/log") for request in calls)

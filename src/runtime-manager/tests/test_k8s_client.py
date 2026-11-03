"""F059 coverage: AC-03, AC-04, AC-13, AC-14, AC-48, AC-49, AC-52."""

import json
from pathlib import Path

import certifi
import httpx
import pytest

from runtime_manager.config import Config, load_config
from runtime_manager.k8s_config import KubernetesConfig, KubernetesConfigurationError

NAMESPACE = "bisheng-runtime-apps"
UID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def settings(tmp_path):
    token = tmp_path / "token"
    token.write_text("test.token.one")
    descriptor = tmp_path / "domain.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "cluster_id": "cluster-a",
                "platform": "linux/amd64",
                "memory_budget_mb": 4096,
                "cpu_budget_millicores": 2000,
                "status_policy_revision": "v1",
            }
        )
    )
    return KubernetesConfig(
        namespace=NAMESPACE,
        cluster_id="cluster-a",
        descriptor_file=descriptor,
        token_file=token,
        ca_file=Path(certifi.where()),
        api_server="https://cluster.invalid:6443",
    )


@pytest.fixture
def client_factory(settings):
    from runtime_manager.k8s_client import KubernetesClient

    clients = []

    def create(handler, **kwargs):
        client = KubernetesClient(settings, transport=httpx.MockTransport(handler), sleep=lambda _: None, **kwargs)
        clients.append(client)
        return client

    yield create
    for client in clients:
        client.close()


def test_executor_default_and_kubernetes_protocol_gate(monkeypatch):
    monkeypatch.delenv("RTM_EXECUTOR", raising=False)
    assert load_config().executor_kind == "docker"
    with pytest.raises(ValueError, match="requires_protocol_v2"):
        Config(executor_kind="kubernetes", protocol_version=1)
    with pytest.raises(ValueError, match="executor_invalid"):
        Config(executor_kind="other")
    assert Config(executor_kind="kubernetes", protocol_version=2).executor_kind == "kubernetes"


@pytest.mark.parametrize("namespace", ["default", "kube-system", "kube-public", "../foreign", "A", ""])
def test_namespace_is_a_dedicated_execution_scope(settings, namespace):
    from dataclasses import replace

    with pytest.raises(KubernetesConfigurationError, match="namespace_refused"):
        replace(settings, namespace=namespace)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.invalid",
        "https://user:password@api.invalid",
        "https://api.invalid/path",
        "https://api.invalid?token=x",
    ],
)
def test_api_server_cannot_disable_tls_or_include_credentials(settings, url):
    from dataclasses import replace

    with pytest.raises(KubernetesConfigurationError, match="api_server_invalid"):
        replace(settings, api_server=url)


def test_descriptor_scope_budget_and_duplicate_fields(settings):
    assert settings.descriptor().memory_budget_mb == 4096
    doc = json.loads(settings.descriptor_file.read_text())
    doc["namespace"] = "foreign"
    settings.descriptor_file.write_text(json.dumps(doc))
    with pytest.raises(KubernetesConfigurationError, match="scope_mismatch"):
        settings.descriptor()
    settings.descriptor_file.write_text('{"schema_version":1,"schema_version":2}')
    with pytest.raises(KubernetesConfigurationError, match="duplicate_field"):
        settings.descriptor()


def test_client_rotates_token_and_reads_only_scoped_pods(client_factory, settings):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"metadata": {"name": "app-a", "uid": UID}})

    client = client_factory(handler)
    assert client.get("pods", "app-a")["metadata"]["uid"] == UID
    settings.token_file.write_text("test.token.two")
    client.get("pods", "app-a")
    assert [x.headers["authorization"] for x in calls] == ["Bearer test.token.one", "Bearer test.token.two"]
    assert all(x.url.path == f"/api/v1/namespaces/{NAMESPACE}/pods/app-a" for x in calls)
    assert all(x.url.params.get("resourceVersion") != "0" for x in calls)


@pytest.mark.parametrize(
    "resource,name", [("nodes", "node-a"), ("pods/exec", "app-a"), ("pods", "../foreign"), ("secrets", "%2fother")]
)
def test_client_refuses_cluster_and_arbitrary_subresource_paths(client_factory, resource, name):
    calls = []
    client = client_factory(lambda request: calls.append(request) or httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        client.get(resource, name)
    assert not calls


def test_create_namespace_is_injected_without_mutating_template(client_factory):
    payload = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "app-a"}}
    calls = []
    client = client_factory(
        lambda request: calls.append(json.loads(request.content)) or httpx.Response(201, json=payload)
    )
    client.create("pods", payload)
    assert calls[0]["metadata"]["namespace"] == NAMESPACE
    assert "namespace" not in payload["metadata"]
    payload["metadata"]["namespace"] = "foreign"
    with pytest.raises(ValueError, match="scope"):
        client.create("pods", payload)
    assert len(calls) == 1


def test_delete_is_uid_and_resource_version_conditional_and_not_a_stop_proof(client_factory):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"metadata": {"uid": UID, "deletionTimestamp": "2026-10-21T00:00:00Z"}})

    client = client_factory(handler)
    result = client.delete("pods", "app-a", uid=UID, resource_version="17", grace_seconds=30)
    body = json.loads(calls[0].content)
    assert body["preconditions"] == {"uid": UID, "resourceVersion": "17"}
    assert body["gracePeriodSeconds"] == 30
    assert result["metadata"]["uid"] == UID
    assert "stopped" not in result
    with pytest.raises(ValueError):
        client.delete("pods", "app-a", uid="", resource_version="17")


def test_patch_carries_resource_version_and_refuses_scope_changes(client_factory):
    calls = []
    client = client_factory(lambda request: calls.append(request) or httpx.Response(200, json={}))
    client.patch("pods", "app-a", {"metadata": {"finalizers": []}}, resource_version="17")
    assert json.loads(calls[0].content)["metadata"]["resourceVersion"] == "17"
    assert calls[0].headers["content-type"] == "application/merge-patch+json"
    with pytest.raises(ValueError):
        client.patch("pods", "app-a", {"metadata": {"namespace": "foreign"}}, resource_version="17")
    assert len(calls) == 1


def test_list_paginates_a_single_snapshot(client_factory):
    calls = []

    def handler(request):
        calls.append(request)
        page = 1 if not request.url.params.get("continue") else 2
        return httpx.Response(
            200,
            json={
                "metadata": {"resourceVersion": "20", "continue": "next" if page == 1 else ""},
                "items": [{"metadata": {"name": f"app-{page}"}}],
            },
        )

    client = client_factory(handler)
    result = client.list("pods", label_selector="bisheng.managed=v2")
    assert [x["metadata"]["name"] for x in result["items"]] == ["app-1", "app-2"]
    assert result["metadata"]["resourceVersion"] == "20"
    assert calls[1].url.params["continue"] == "next"


def test_watch_410_relists_before_accepting_more_events(client_factory):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(410, json={"reason": "Expired"})
        if request.url.params.get("watch") != "true":
            return httpx.Response(200, json={"metadata": {"resourceVersion": "8"}, "items": []})
        assert request.url.params["resourceVersion"] == "8"
        event = {"type": "ADDED", "object": {"metadata": {"resourceVersion": "9", "uid": UID}}}
        return httpx.Response(200, text=json.dumps(event) + "\n")

    events = list(client_factory(handler).watch("pods", resource_version="5"))
    assert [x["type"] for x in events] == ["RESET", "ADDED"]


def test_transient_reads_retry_with_a_checkpoint(client_factory):
    calls = []
    checkpoints = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(503, json={"reason": "ServiceUnavailable"})
            if len(calls) == 1
            else httpx.Response(200, json={})
        )

    assert client_factory(handler, checkpoint=lambda: checkpoints.append(True)).get("pods", "app-a") == {}
    assert len(calls) == 2 and len(checkpoints) >= 2


def test_create_transport_reply_loss_is_not_blindly_retried(client_factory):
    from runtime_manager.k8s_client import KubernetesAPIError

    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadError("sensitive-transport-detail")

    with pytest.raises(KubernetesAPIError, match="transport_unavailable") as caught:
        client_factory(handler).create("pods", {"metadata": {"name": "app-a"}})
    assert len(calls) == 1
    assert "sensitive-transport-detail" not in str(caught.value)


@pytest.mark.parametrize("status", [403, 404, 409, 302])
def test_api_error_never_exposes_response_or_becomes_stopped(client_factory, status):
    from runtime_manager.k8s_client import KubernetesAPIError

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"reason": "Refused", "message": "secret-response-detail"},
            headers={"Location": "https://other.invalid"},
        )

    with pytest.raises(KubernetesAPIError) as caught:
        client_factory(handler).get("pods", "app-a")
    assert caught.value.status_code == status
    assert "secret-response-detail" not in str(caught.value)
    assert len(calls) == 1


def test_pod_logs_are_only_the_business_container(client_factory):
    calls = []
    client = client_factory(lambda request: calls.append(request) or httpx.Response(200, text="line\n"))
    assert client.logs("app-a", tail=20, previous=True) == "line\n"
    assert calls[0].url.path.endswith("/pods/app-a/log")
    assert calls[0].url.params["container"] == "app"
    assert calls[0].url.params["previous"] == "true"


def test_retry_limit_is_finite(client_factory):
    from runtime_manager.k8s_client import KubernetesAPIError

    calls = []
    client = client_factory(
        lambda request: calls.append(request) or httpx.Response(503, json={"reason": "ServiceUnavailable"})
    )
    with pytest.raises(KubernetesAPIError) as caught:
        client.get("pods", "app-a")
    assert caught.value.status_code == 503
    assert len(calls) == 3


def test_checkpoint_cancels_before_any_cluster_mutation(client_factory):
    calls = []

    def checkpoint():
        raise RuntimeError("controller_lease_lost")

    client = client_factory(
        lambda request: calls.append(request) or httpx.Response(201, json={}), checkpoint=checkpoint
    )
    with pytest.raises(RuntimeError, match="controller_lease_lost"):
        client.create("pods", {"metadata": {"name": "app-a"}})
    assert not calls


def test_inconsistent_list_snapshot_is_not_returned_as_complete(client_factory):
    from runtime_manager.k8s_client import KubernetesAPIError

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "metadata": {"resourceVersion": str(len(calls)), "continue": "next" if len(calls) == 1 else ""},
                "items": [],
            },
        )

    with pytest.raises(KubernetesAPIError, match="list_snapshot_changed"):
        client_factory(handler).list("pods")


def test_trusted_phase_results_use_only_a_named_bounded_container_log(client_factory):
    calls = []
    client = client_factory(lambda request: calls.append(request) or httpx.Response(200, text="fixture helper result"))
    assert client.logs("task-a", container="transfer", tail=100) == "fixture helper result"
    assert calls[0].url.params["container"] == "transfer" and calls[0].url.params["limitBytes"] == "1048576"
    with pytest.raises(ValueError):
        client.logs("task-a", container="../../foreign")
    assert len(calls) == 1


def test_platform_ca_and_material_issuer_are_independent_file_settings(monkeypatch, tmp_path):
    ca = tmp_path / "platform-ca.crt"
    issuer = tmp_path / "material-issuer.key"
    monkeypatch.setenv("RTM_PLATFORM_CA_FILE", str(ca))
    monkeypatch.setenv("RTM_MATERIAL_ISSUER_KEY_FILE", str(issuer))
    config = load_config()
    assert config.platform_ca_file == ca and config.material_issuer_key_file == issuer
    assert str(issuer) not in repr(config)
    with pytest.raises(ValueError):
        Config(material_issuer_key_file=Path("relative-key"))


def test_absolute_log_window_uses_since_time_without_changing_its_meaning(client_factory):
    calls = []
    client = client_factory(lambda request: calls.append(request) or httpx.Response(200, text="app log"))
    client.logs("app-a", since_time="2026-10-01T00:00:00Z")
    assert calls[0].url.params["sinceTime"] == "2026-10-01T00:00:00Z"
    assert "sinceSeconds" not in calls[0].url.params
    with pytest.raises(ValueError):
        client.logs("app-a", since_time="2026-10-01T00:00:00Z", since_seconds=30)


@pytest.mark.parametrize(
    "container",
    [
        "app",
        "transfer",
        "prepare",
        "material-fetch",
        "environment",
        "data-layout",
        "data-helper",
        "maintenance",
        "storage-guard",
        "schema-init",
        "assembler",
    ],
)
def test_every_fixed_managed_container_has_bounded_scoped_logs(client_factory, container):
    """覆盖 AC: AC-03、AC-48、AC-52."""
    calls = []
    client = client_factory(
        lambda request: calls.append(request) or httpx.Response(200, text="fixed helper diagnostic")
    )
    assert client.logs("task-a", container=container, tail=80) == "fixed helper diagnostic"
    assert len(calls) == 1 and calls[0].method == "GET"
    assert calls[0].url.path == f"/api/v1/namespaces/{NAMESPACE}/pods/task-a/log"
    assert dict(calls[0].url.params) == {
        "container": container,
        "tailLines": "80",
        "previous": "false",
        "limitBytes": "1048576",
    }


@pytest.mark.parametrize(
    "container",
    ["custom", "storage-guard-extra", "schema-init-extra", "ASSEMBLER", "", "../foreign", "app?container=foreign"],
)
def test_unregistered_log_container_is_rejected_without_request(client_factory, container):
    """覆盖 AC: AC-03、AC-48、AC-52."""
    calls = []
    client = client_factory(lambda request: calls.append(request) or httpx.Response(200, text="must not be requested"))
    with pytest.raises(ValueError, match="k8s_log_container_invalid"):
        client.logs("task-a", container=container)
    assert not calls


def test_log_contract_covers_only_real_fixed_template_names(client_factory):
    """覆盖 AC: AC-03、AC-48、AC-52."""
    from runtime_manager.k8s_templates import PREPARATION, PRODUCTION, PURPOSES, PodPlan, pod_template

    names = set()
    for purpose in PURPOSES:
        plan = PodPlan(
            namespace=NAMESPACE,
            app_id="app-a",
            operation_id="operation-a",
            resource_ref="ref-a",
            node_id="node-a",
            generation=1,
            owner_epoch=1,
            purpose=purpose,
            platform="linux/amd64",
            status_policy_revision="v1",
            image="example/runtime@sha256:" + "a" * 64,
            helper_image="example/helper@sha256:" + "b" * 64,
            command=("python", "main.py"),
            memory_mb=512,
            cpu_millicores=250,
            deadline_seconds=None if purpose == "serve" else 60,
            pvc_name="data-a" if purpose in PRODUCTION else "",
            scratch_pvc="scratch-a" if purpose in PREPARATION else "",
            material_secret="material-a",
            schema_plan=({"op": "create_table", "table": "items", "columns": []},),
        )
        spec = pod_template(plan)["spec"]
        names.update(c["name"] for c in spec["initContainers"] + spec["containers"])
    assert names == {
        "app",
        "transfer",
        "prepare",
        "material-fetch",
        "environment",
        "data-layout",
        "data-helper",
        "maintenance",
        "storage-guard",
        "schema-init",
        "assembler",
    }
    calls = []
    client = client_factory(lambda request: calls.append(request) or httpx.Response(200, text="fixed log"))
    for name in sorted(names):
        assert client.logs("task-a", container=name) == "fixed log"
    assert len(calls) == len(names)

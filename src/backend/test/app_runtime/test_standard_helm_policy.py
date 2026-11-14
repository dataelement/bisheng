"""F009 AC-01/02/06/17: expected deployment input, not probe age, is authority."""

import json
from types import SimpleNamespace

import pytest

from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.repositories.runtime_kubernetes_repository import pod_request
from bisheng.app_runtime.domain.services import runtime_deployment_policy as policy
from test.app_runtime.test_runtime_kubernetes_coordination import coordination as coordination
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import control as control


def document():
    return {
        "schema_version": 2,
        "configuration_source": "operator-configured",
        "installation_id": "test",
        "node_id": "node",
        "cluster_id": "cluster",
        "namespace": "apps",
        "platform": "linux/amd64",
        "status_policy_revision": "v1",
        "manager_username": "system:serviceaccount:control:manager",
        "storage_controller_usernames": ["system:kube-controller-manager"],
        "memory_budget_mb": 8192,
        "cpu_budget_millicores": 4000,
        "helper_image": "example/helper@sha256:" + "a" * 64,
        "service_cidrs": ["10.96.0.0/12"],
        "storage": {"class": None, "filesystem": "ext4", "sqlite_compatible": True},
    }


def test_backend_requires_its_own_expected_policy_and_ignores_diagnostic_age(monkeypatch):
    expected = document()
    raw = json.dumps(expected)
    monkeypatch.setattr(policy, "expected_policy", lambda _: (raw, expected))
    body = SimpleNamespace(
        engine_id="cluster/apps",
        platform="linux/amd64",
        memory_budget_mb=8192,
        cpu_budget_millicores=4000,
        probe_report={"observed_at": 1, "ready": False},
        capabilities={
            "node_id": "node",
            "status_policy_revision": "v1",
            "helper_image": expected["helper_image"],
            "service_cidrs": expected["service_cidrs"],
            "status_protection": True,
            "binding_protection": True,
            "mandatory_isolation": True,
            "orchestration_available": True,
            "configuration": {
                "version": 2,
                "source": "operator-configured",
                "state": "configured",
                "policy_digest": policy.policy_digest(raw),
                "protection_baseline_digest": policy.protection_digest(expected),
            },
        },
    )
    assert policy.matches_heartbeat(body, "node")
    body.probe_report = {"state": "not_run", "checks": []}
    assert policy.matches_heartbeat(body, "node")
    body.memory_budget_mb += 1
    assert not policy.matches_heartbeat(body, "node")


def test_frozen_policy_rejects_replaced_bytes():
    raw = json.dumps(document())
    operation = SimpleNamespace(
        node_id="node", payload={"execution_policy_json": raw, "execution_policy_digest": policy.policy_digest(raw)}
    )
    assert policy.operation_policy(operation)["namespace"] == "apps"
    operation.payload["execution_policy_json"] += "\n"
    with pytest.raises(RuntimeConflict, match="digest"):
        policy.operation_policy(operation)


def test_effective_requests_include_init_peak_and_enforce_equal_limits():
    def container(memory, cpu):
        values = {"memory": memory, "cpu": cpu}
        return {"resources": {"requests": dict(values), "limits": dict(values)}}

    template = {
        "spec": {
            "containers": [container("512Mi", "250m"), container("128Mi", "25m")],
            "initContainers": [container("1Gi", "1000m")],
        }
    }
    assert pod_request(template) == (1024, 1000)
    template["spec"]["containers"][0]["resources"]["limits"]["cpu"] = "1"
    with pytest.raises(RuntimeConflict, match="requests_limits"):
        pod_request(template)


async def test_helper_overlap_grows_reservation_and_refuses_exhaustion(repo):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCapacityReservation
    from test.app_runtime.test_runtime_kubernetes_repository import NOW, leased, resource, setup_operation

    op = await setup_operation(repo)
    op.payload = {"execution_policy_json": json.dumps(document())}
    await repo.save(op)
    await leased(repo)

    def pod(name, memory, cpu):
        row = resource(op, name=name, purpose="prepare-install")
        values = {"memory": f"{memory}Mi", "cpu": f"{cpu}m"}
        row.approved_template["spec"] = {"containers": [{"resources": {"requests": values, "limits": values}}]}
        return row

    first = await repo.create_resource_intent(
        pod("task-one", 1024, 1000), holder_id="controller-a", controller_epoch=1, now=NOW
    )
    reservation = (await repo.find(RuntimeCapacityReservation, operation_id=op.id))[0]
    assert (reservation.memory_mb, reservation.cpu_millicores) == (1024, 1000)
    await repo.create_resource_intent(pod("task-two", 512, 500), holder_id="controller-a", controller_epoch=1, now=NOW)
    reservation = (await repo.find(RuntimeCapacityReservation, operation_id=op.id))[0]
    assert (reservation.memory_mb, reservation.cpu_millicores) == (1536, 1500)
    with pytest.raises(RuntimeConflict, match="capacity_exhausted"):
        await repo.create_resource_intent(
            pod("task-too-large", 3072, 3000), holder_id="controller-a", controller_epoch=1, now=NOW
        )
    assert len(await repo.find(RuntimeExecutionResource, operation_id=op.id)) == 2
    assert first.stop_state != "confirmed"


def test_temporary_orchestration_loss_preserves_history_without_stop_authority(monkeypatch):
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService

    expected = document()
    monkeypatch.setattr(policy, "expected_policy", lambda _: (json.dumps(expected), expected))
    monkeypatch.setattr(policy, "matches_heartbeat", lambda *_: False)
    previous = {
        "configuration": {"version": 2},
        "namespace": "apps",
        "cluster_id": "cluster",
        "status_policy_revision": "v1",
        "protection_baseline_digest": policy.protection_digest(expected),
        "serving_protection_valid": True,
    }
    node = SimpleNamespace(id="node", capabilities=previous)
    body = SimpleNamespace(capabilities={**previous, "status_protection": True, "binding_protection": True})
    observed, status_changed, binding_changed, invalid = RuntimeOperationService._protection_update(node, body)
    assert invalid and not status_changed and not binding_changed
    assert observed["serving_protection_valid"] is True
    assert observed["status_protection"] is False and observed["binding_protection"] is False
    body.capabilities["status_policy_revision"] = "v2"
    observed, status_changed, binding_changed, _ = RuntimeOperationService._protection_update(node, body)
    assert status_changed and binding_changed and observed["serving_protection_valid"] is False


# Reuse real transaction fixtures, rather than mocking capacity aggregation.


def test_manager_heartbeat_pairs_with_backend_without_diagnostic_authority(monkeypatch):
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).parents[3] / "runtime-manager"))
    from runtime_manager.deployment_policy import DeploymentPolicy
    from runtime_manager.executors.kubernetes import KubernetesExecutor

    expected = {**document(), "storage": {"class": None, "filesystem": "ext4", "sqlite_compatible": True}}
    raw = json.dumps(expected)
    manager_policy = DeploymentPolicy.parse(raw)
    assert manager_policy.protection_digest == policy.protection_digest(expected)
    for role in policy.HELPERS:
        assert manager_policy.helper(role) == policy.helper_resources(expected, role)
    executor = KubernetesExecutor.__new__(KubernetesExecutor)
    descriptor = SimpleNamespace(raw_policy=raw, platform="linux/amd64", status_policy_revision="v1")
    executor.document = expected
    executor.descriptor = descriptor
    executor.settings = SimpleNamespace(descriptor=lambda: descriptor, cluster_id="cluster", namespace="apps")
    executor.config = SimpleNamespace(
        node_id="node", build_index_url="", build_extra_index_url="", build_npm_registry=""
    )
    executor.client = SimpleNamespace(list=lambda *_args, **_kwargs: [])
    executor.data_transport = None
    monkeypatch.delenv("RTM_K8S_DIAGNOSTIC_FILE", raising=False)
    snapshot = executor.heartbeat_snapshot()
    body = SimpleNamespace(
        engine_id="cluster/apps", platform="linux/amd64", memory_budget_mb=8192, cpu_budget_millicores=4000, **snapshot
    )
    monkeypatch.setattr(policy, "expected_policy", lambda _: (raw, expected))
    assert snapshot["probe_report"]["state"] == "not_run"
    assert policy.matches_heartbeat(body, "node")
    body.probe_report = {"state": "completed", "observed_at": 1, "checks": [{"name": "network", "ok": False}]}
    assert policy.matches_heartbeat(body, "node")
    # A substituted policy never gets authority merely from a successful report.
    descriptor.raw_policy = raw + "\n"
    body.capabilities = executor.heartbeat_snapshot()["capabilities"]
    body.probe_report = {"ready": True}
    assert not policy.matches_heartbeat(body, "node")


async def test_confirmed_guard_change_cannot_heal_old_route_on_next_heartbeat(coordination, monkeypatch):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeNode, RuntimeRoute
    from test.app_runtime.test_runtime_kubernetes_coordination import heartbeat
    from test.app_runtime.test_runtime_kubernetes_service import MANAGER

    c = coordination
    node = await c.repo.get(RuntimeNode, "node-a")
    node.capabilities = {}
    await c.repo.save(node)
    expected = {
        **document(),
        "node_id": "node-a",
        "cluster_id": "cluster-a",
        "namespace": "namespace-a",
        "memory_budget_mb": 4096,
    }
    monkeypatch.setattr(policy, "expected_policy", lambda _: (json.dumps(expected), expected))

    def body(available=True):
        result = heartbeat(probe_report={"state": "not_run", "checks": []})
        result.capabilities.update(
            node_id="node-a",
            orchestration_available=available,
            helper_image=expected["helper_image"],
            status_policy_revision=expected["status_policy_revision"],
            configuration={
                "version": 2,
                "source": "operator-configured",
                "state": "configured",
                "policy_digest": policy.policy_digest(json.dumps(expected)),
                "protection_baseline_digest": policy.protection_digest(expected),
            },
        )
        return result

    await c.svc.heartbeat(MANAGER, body())
    await c.repo.save(
        RuntimeRoute(
            tenant_id=1,
            app_id=c.op.app_id,
            version_id="version",
            route_key="standard-route",
            node_id="node-a",
            exec_ref="uid",
            generation=1,
            owner_epoch=1,
            status="serving",
        )
    )
    await c.svc.heartbeat(MANAGER, body(available=False))
    assert (await c.svc.route("standard-route"))["decision"] == "allow"
    expected["status_policy_revision"] = "v2"
    await c.svc.heartbeat(MANAGER, body())
    assert (await c.svc.route("standard-route"))["decision"] == "transition"
    await c.svc.heartbeat(MANAGER, body())
    assert (await c.svc.route("standard-route"))["phase"] == "unhealthy"


@pytest.mark.parametrize(
    "purpose",
    [
        "image-check",
        "prepare-download",
        "prepare-install",
        "prepare-upload",
        "assemble",
        "serve",
        "preview",
        "migrate",
        "restore",
        "data",
        "purge",
    ],
)
def test_manager_pod_budgets_match_backend_validator_for_every_phase(purpose):
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).parents[3] / "runtime-manager"))
    from runtime_manager.k8s_templates import PREPARATION, PRODUCTION, PodPlan, pod_template

    helpers = {
        name: {"memory_mb": value["memory_mb"] + 16, "cpu_millicores": value["cpu_millicores"] + 5}
        for name, value in policy.HELPERS.items()
    }
    image = "example/runtime@sha256:" + "a" * 64
    helper = "example/helper@sha256:" + "b" * 64
    kwargs = {
        "namespace": "apps",
        "app_id": "app",
        "operation_id": "operation",
        "resource_ref": "11111111-1111-4111-8111-111111111111",
        "node_id": "node",
        "generation": 1,
        "owner_epoch": 1,
        "purpose": purpose,
        "platform": "linux/amd64",
        "status_policy_revision": "v1",
        "image": image,
        "helper_image": helper,
        "command": ("python", "main.py"),
        "memory_mb": 512,
        "cpu_millicores": 250,
        "helper_resources": helpers,
        "deadline_seconds": None if purpose == "serve" else 60,
    }
    if purpose in PRODUCTION:
        kwargs["pvc_name"] = "data-app"
    if purpose in PREPARATION:
        kwargs["scratch_pvc"] = "scratch-op"
    if purpose in {"serve", "preview", "prepare-download", "prepare-upload"}:
        kwargs["material_secret"] = "material-op"
    if purpose == "image-check":
        kwargs.update(image=helper, mode="image", command=("python", "-I", "-m", "runtime_manager.image_check"))
    spec = pod_template(PodPlan(**kwargs))["spec"]
    operation = SimpleNamespace(payload={"tier": {"memory_mb": 512, "cpu_millicores": 250}})
    policy.validate_container_resources(spec, operation, {"helper_resources": helpers}, purpose)
    spec["containers"][0]["resources"]["limits"]["memory"] = "1Mi"
    with pytest.raises(RuntimeConflict, match="budget_mismatch"):
        policy.validate_container_resources(spec, operation, {"helper_resources": helpers}, purpose)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": 2.0},
        {"timeouts": {"health": 0}},
        {"storage": {"filesystem": "nfs", "sqlite_compatible": True}},
        {"service_cidrs": ["0.0.0.0/0"]},
        {"manager_username": "user"},
        {"placement": {"nodeName": "bypass"}},
        {"placement": {"nodeSelector": {"kubernetes.io/arch": "arm64"}}},
        {"helper_resources": {"image-check": {"memory_mb": 999999, "cpu_millicores": 1000}}},
    ],
)
def test_backend_independently_rejects_invalid_operator_policy(changes):
    with pytest.raises(RuntimeConflict, match="deployment_policy_invalid"):
        policy.parse_policy(json.dumps({**document(), **changes}), node_id="node")

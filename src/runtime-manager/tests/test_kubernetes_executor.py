"""覆盖 AC: AC-04、AC-05、AC-07、AC-08、AC-09、AC-11、AC-18、AC-30、AC-34、AC-33、AC-35、AC-43、AC-48、AC-49、AC-50、AC-52、AC-24、AC-25、AC-36、AC-55、AC-01、AC-13、AC-15."""

import base64
import copy
import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
import pytest

from runtime_manager.config import Config
from runtime_manager.executors.protocol import ExecutorError
from runtime_manager.k8s_client import KubernetesAPIError
from runtime_manager.k8s_config import KubernetesConfig
from runtime_manager.k8s_templates import RESOURCE_LABEL, STOP_FINALIZER, production_name
from runtime_manager.platform_client import PREFIX, PlatformClient, PlatformError

IMAGE = "example.invalid/python@sha256:" + "a" * 64
HELPER = "example.invalid/helper@sha256:" + "b" * 64
POD_UID = "22222222-2222-4222-8222-222222222222"


class Clock:
    def __init__(self):
        self.value = 1792555200.0

    def time(self):
        return self.value

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds

    def iso(self, seconds=0):
        return datetime.fromtimestamp(self.value + seconds, UTC).isoformat()


class Platform:
    def __init__(self, clock, events):
        self.clock, self.events = clock, events
        self.epoch = 0
        self.holder = ""
        self.lease_until = 0.0
        self.fences = []
        self.rows = {}
        self.operations = {}
        self.delegations = []

    def node_snapshot(self):
        return {
            "node": {
                "node_id": "node-a",
                "controller_epoch": self.epoch,
                "controller_holder": self.holder,
                "lease_until": self.clock.iso(self.lease_until - self.clock.value) if self.lease_until else None,
            },
            "operations": list(self.operations.values()),
        }

    def _receipt(self):
        return {
            "node_id": "node-a",
            "holder_id": self.holder,
            "controller_epoch": self.epoch,
            "lease_until": self.clock.iso(self.lease_until - self.clock.value),
        }

    def _fence(self, receipt):
        if (receipt["holder_id"], receipt["controller_epoch"]) != (
            self.holder,
            self.epoch,
        ) or self.lease_until <= self.clock.value:
            raise PlatformError("controller_lease_lost", 409)
        self.fences.append(dict(receipt))

    def claim_controller(self, holder_id, expected_epoch):
        if expected_epoch != self.epoch:
            raise PlatformError("controller_epoch_conflict", 409)
        if self.lease_until > self.clock.value:
            if holder_id != self.holder:
                raise PlatformError("controller_lease_held", 409)
            return self._receipt()
        self.epoch += 1
        self.holder = holder_id
        self.lease_until = self.clock.value + 30
        self.events.append(("claim", self.epoch))
        return self._receipt()

    def renew_controller(self, holder_id, controller_epoch):
        self._fence({"holder_id": holder_id, "controller_epoch": controller_epoch})
        self.lease_until = self.clock.value + 30
        self.events.append(("renew", self.epoch))
        return self._receipt()

    def operation(self, operation_id):
        return copy.deepcopy(self.operations[operation_id])

    def register_resource(self, document):
        self._fence({key: document[key] for key in ("holder_id", "controller_epoch")})
        self.events.append(("intent", document["template"]["kind"], document["resource_ref"]))
        op = self.operations[document["operation_id"]]
        row = {
            "resource_ref": document["resource_ref"],
            "operation_id": op["operation_id"],
            "app_id": op["app_id"],
            "node_id": op["node_id"],
            "cluster_id": "cluster-a",
            "namespace": "runtime-apps",
            "generation": op["generation"],
            "owner_epoch": op["owner_epoch"],
            "kind": document["template"]["kind"],
            "name": document["template"]["metadata"]["name"],
            "purpose": document["purpose"],
            "uid": None,
            "node_name": "",
            "stop_state": "held",
            "stop_requested_at": None,
            "cleanup_state": "pending",
            "status_policy_revision": "v1",
            "protected_since_creation": True,
            "binding_policy_verified": True,
            "template": copy.deepcopy(document["template"]),
            "spec_digest": "a" * 64,
            "observed_state": {"creation": {"version": 1, "state": "unattempted"}}
            if document["template"]["kind"] == "Pod"
            else {},
            "controller_epoch": document["controller_epoch"],
        }
        previous = self.rows.get(row["resource_ref"])
        if previous:
            assert previous["template"] == row["template"]
            if previous["uid"] is None and previous["stop_requested_at"] is None:
                previous["controller_epoch"] = document["controller_epoch"]
            return copy.deepcopy(previous)
        self.rows[row["resource_ref"]] = row
        return copy.deepcopy(row)

    def resource(self, resource_ref):
        if resource_ref not in self.rows:
            raise PlatformError("resource_not_found", 404)
        return copy.deepcopy(self.rows[resource_ref])

    def resources(self, operation_id):
        return [copy.deepcopy(row) for row in self.rows.values() if row["operation_id"] == operation_id]

    def observe_resource(self, resource_ref, document):
        self._fence({key: document[key] for key in ("holder_id", "controller_epoch")})
        self.events.append((document["action"], resource_ref))
        row = self.rows[resource_ref]
        creation = row.get("observed_state", {}).get("creation", {})
        if document["action"] == "create_begin":
            assert row["kind"] == "Pod" and row["uid"] is None and row["stop_requested_at"] is None
            assert creation == {"version": 1, "state": "unattempted"}
            assert str(UUID(document["create_attempt_id"])) == document["create_attempt_id"]
            row["observed_state"]["creation"] = {
                "version": 1,
                "state": "started",
                "create_attempt_id": document["create_attempt_id"],
                "controller_epoch": document["controller_epoch"],
            }
        elif document["action"] == "create_rejected":
            assert row["uid"] is None and creation["state"] == "started"
            assert creation["create_attempt_id"] == document["create_attempt_id"]
            assert creation["controller_epoch"] == document["controller_epoch"] and document["http_status"] == 403
            creation.update(state="rejected", http_status=403)
        elif document["action"] == "create_fence":
            assert row["uid"] is None and creation.get("state") in {"unattempted", "rejected"}
            creation.update(outcome=creation["state"], state="fenced")
            row["stop_requested_at"] = row["stop_requested_at"] or self.clock.iso()
            row["stop_state"] = "requested"
            row["controller_epoch"] = document["controller_epoch"]
        elif document["action"] == "not_created":
            assert row["uid"] is None and creation.get("state") in {"fenced", "not_created"}
            assert document["evidence"] == {
                "evidence_kind": "not_created",
                "namespace": row["namespace"],
                "name": row["name"],
                "observed_at": self.clock.iso(),
                "api_status": 404,
            }
            creation["state"] = "not_created"
            row["stop_state"] = "confirmed"
            row["stop_evidence"] = copy.deepcopy(document["evidence"])
        elif document["action"] == "bind":
            if row["uid"]:
                assert row["uid"] == document["uid"]
            if row["node_name"]:
                assert row["node_name"] == document.get("node_name", "")
            row["uid"] = document["uid"]
            row["node_name"] = document.get("node_name", "")
            row["controller_epoch"] = document["controller_epoch"]
            row["observed_state"] = document.get("runtime_state", row["observed_state"])
        elif document["action"] == "stop":
            row["controller_epoch"] = document["controller_epoch"]
            row["stop_requested_at"] = row["stop_requested_at"] or self.clock.iso()
            if row["stop_state"] != "confirmed":
                row["stop_state"] = "requested"
        elif document["action"] == "stopped":
            assert document["evidence"]["uid"] == row["uid"]
            assert document["evidence"]["node_name"] == row["node_name"]
            row["stop_state"] = "confirmed"
            row["stop_evidence"] = copy.deepcopy(document["evidence"])
        elif document["action"] == "cleanup":
            assert document["uid"] == row["uid"]
            assert row["uid"] or (
                creation.get("state") == "not_created" and row["stop_evidence"]["evidence_kind"] == "not_created"
            )
            row["cleanup_state"] = "complete"
        return copy.deepcopy(row)

    def create_material_delegation(self, document):
        assert "private_key" not in document
        self.delegations.append(document)
        operation = self.operations[document["operation_id"]]
        return {
            "delegation_id": str(uuid5(NAMESPACE_URL, document["key_id"])),
            "key_id": document["key_id"],
            "scope_kind": "deployment-init" if operation["kind"] in {"deploy", "preview", "restore"} else "operation",
            "expires_at": None if operation["kind"] == "deploy" else operation["deadline"],
            "proxy": {"principal": "material-fixture", "token": "fixture-material-proxy-token"},
        }

    def bind_material_delegation(self, delegation_id, pod_uid):
        self.events.append(("material-bind", delegation_id, pod_uid))
        return {"pod_uid": pod_uid}

    def fact(self, operation, sequence, phase, *, exec_ref="", detail=None):
        self.events.append(("fact", phase, sequence))
        op = self.operations[operation["operation_id"]]
        assert sequence == op.get("fact_sequence", 0) + 1
        self._fence(detail["controller"])
        op.update(fact_sequence=sequence, result=copy.deepcopy(detail))
        return copy.deepcopy(op)

    def egress(self, operation_id, phase, **kwargs):
        return {"principal": phase + "-" + operation_id, "token": "fixture-egress-token"}

    def dependencies(self, operation_id, input_key, *, artifact_id=None, verified=False):
        self.operations[operation_id]["payload"]["dependency_resolution"] = {
            "input_key": input_key,
            "artifact_id": artifact_id or "",
        }
        return {"state": "verified" if artifact_id else "claimed", "artifact_id": artifact_id}


class Cluster:
    def __init__(self, platform, clock, events):
        self.platform, self.clock, self.events = platform, clock, events
        self.objects = {}
        self.rv = 0
        self.still_running = False
        self.endpoints_ready = True
        self.fail_prepare = False
        self.delay_binding = False

    def get(self, resource, name):
        if (resource, name) not in self.objects:
            raise KubernetesAPIError("not_found", 404)
        return copy.deepcopy(self.objects[resource, name])

    def create(self, resource, document):
        ref = document["metadata"]["labels"][RESOURCE_LABEL]
        assert ref in self.platform.rows, "cluster I/O must follow committed SQL intent"
        if (resource, document["metadata"]["name"]) in self.objects:
            raise KubernetesAPIError("already_exists", 409)
        self.events.append(("create", resource, ref))
        self.rv += 1
        body = copy.deepcopy(document)
        body["metadata"].update(uid=str(uuid4()), resourceVersion=str(self.rv))
        if resource == "pods":
            body["spec"]["nodeName"] = "worker-a"
            body["status"] = {
                "phase": "Succeeded"
                if body["metadata"]["labels"]["runtime.bisheng.io/purpose"].startswith("prepare")
                else "Running",
                "podIP": "10.233.0.10",
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": [
                    {"name": c["name"], "ready": True, "imageID": c["image"], "state": {"running": {}}}
                    for c in body["spec"]["containers"]
                ],
            }
            if body["status"]["phase"] == "Succeeded":
                for container in body["status"]["containerStatuses"]:
                    container["state"] = {"terminated": {"exitCode": 0}}
            if self.delay_binding:
                body["spec"].pop("nodeName")
                body["status"] = {"phase": "Pending"}
        elif resource == "services":
            body["spec"]["clusterIP"] = "10.96.0.10"
        elif resource == "persistentvolumeclaims":
            body["status"] = {"phase": "Pending"}
        self.objects[resource, body["metadata"]["name"]] = body
        return copy.deepcopy(body)

    def patch(self, resource, name, document, **preconditions):
        body = self.objects[resource, name]
        assert preconditions["resource_version"] == body["metadata"]["resourceVersion"]
        self.events.append(("patch", resource, name))
        body["metadata"].update(document.get("metadata", {}))
        if body["metadata"].get("deletionTimestamp") and STOP_FINALIZER not in body["metadata"].get("finalizers", []):
            del self.objects[resource, name]
        return copy.deepcopy(body)

    def delete(self, resource, name, **preconditions):
        body = self.objects[resource, name]
        assert (
            preconditions["uid"] == body["metadata"]["uid"]
            and preconditions["resource_version"] == body["metadata"]["resourceVersion"]
        )
        self.events.append(("delete", resource, name))
        if resource == "pods":
            body["metadata"]["deletionTimestamp"] = self.clock.iso()
            if not self.still_running:
                body["status"] = (
                    {
                        "phase": "Succeeded",
                        "containerStatuses": [{"name": "app", "state": {"terminated": {"exitCode": 0}}}],
                    }
                    if body["spec"].get("nodeName")
                    else {"phase": "Pending"}
                )
        else:
            del self.objects[resource, name]
        return {}

    def list(self, resource, *, label_selector=""):
        if resource == "endpointslices":
            service_name = label_selector.partition("=")[2]
            service = self.objects.get(("services", service_name))
            ref = (service or {}).get("spec", {}).get("selector", {}).get(RESOURCE_LABEL)
            pod = next(
                (
                    p
                    for (kind, _), p in self.objects.items()
                    if kind == "pods" and p["metadata"]["labels"].get(RESOURCE_LABEL) == ref
                ),
                None,
            )
            return {
                "items": [
                    {
                        "endpoints": [
                            {
                                "addresses": ["10.233.0.10"],
                                "conditions": {"ready": self.endpoints_ready},
                                "targetRef": {"kind": "Pod", "uid": pod["metadata"]["uid"] if pod else "unknown"},
                            }
                        ],
                        "ports": [{"port": 8080, "name": "http"}],
                    }
                ]
            }
        return {"items": [copy.deepcopy(x) for (kind, _), x in self.objects.items() if kind == resource]}

    def logs(self, pod_name, **kwargs):
        assert "since" not in kwargs
        pod = self.objects["pods", pod_name]
        purpose = pod["metadata"]["labels"]["runtime.bisheng.io/purpose"]
        if purpose == "prepare-install":
            return "fixture build log"
        if purpose.startswith("prepare"):
            document = json.loads(
                next(e["value"] for e in pod["spec"]["containers"][0]["env"] if e["name"] == "MATERIAL_PLAN")
            )
            result = {"input_key": "c" * 64, "phase": document.get("phase", "upload")}
            if purpose == "prepare-upload":
                result = {
                    "mode": "bundle",
                    "compiled_artifact_id": "compiled-result",
                    "dependency_artifact_id": "dependencies-result",
                    "dependency_input_key": "c" * 64,
                    "profile": document["profile"],
                    "platform": document["profile"]["platform"],
                    "startup": {"command": ["python", "main.py"]},
                }
            return "BISHENG_RUNTIME_RESULT " + json.dumps(result)
        return "fixture app log"


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    from runtime_manager.executors.kubernetes import KubernetesExecutor

    monkeypatch.setattr(
        "runtime_manager.docker_backend.get_docker_backend", lambda: pytest.fail("K8s must not initialize Docker")
    )
    clock = Clock()
    events = []
    platform = Platform(clock, events)
    cluster = Cluster(platform, clock, events)
    issuer = tmp_path / "issuer"
    issuer.write_bytes(b"m" * 32)
    issuer.chmod(0o600)
    assert issuer.stat().st_size == 32
    descriptor = tmp_path / "descriptor.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cluster_id": "cluster-a",
                "namespace": "runtime-apps",
                "platform": "linux/amd64",
                "memory_budget_mb": 4096,
                "cpu_budget_millicores": 4000,
                "status_policy_revision": "v1",
                "helper_image": HELPER,
                "storage": {
                    "class": "",
                    "size_mb": 256,
                    "scratch_size_mb": 512,
                    "sqlite_compatible": True,
                    "node_local": True,
                },
                "probe_report": {"ready": True, "checks": []},
                "pod_cidrs": ["10.233.0.0/16"],
                "capabilities": {
                    "mandatory_isolation": True,
                    "status_protection": True,
                    "binding_protection": True,
                    "service_cidrs": ["10.96.0.0/12"],
                },
            }
        )
    )
    config = Config(
        executor_kind="kubernetes",
        protocol_version=2,
        node_id="node-a",
        platform_base_url="https://backend",
        platform_key_id="manager",
        platform_secret="fixture-control-hmac",
        material_issuer_key_file=issuer,
        egress_proxy="egress-proxy:3128",
    )
    settings = KubernetesConfig(namespace="runtime-apps", cluster_id="cluster-a", descriptor_file=descriptor)
    profile = {
        "profile_id": "python-profile",
        "language": "python3.11",
        "platform": "linux/amd64",
        "abi": "cpython-311-glibc",
        "runtime_image": IMAGE,
        "runtime_image_id": "sha256:" + "a" * 64,
        "preparer_image": IMAGE,
        "uid": 10001,
        "gid": 10001,
    }
    op = {
        "operation_id": uuid4().hex,
        "app_id": "app-a",
        "node_id": "node-a",
        "version_id": "version-a",
        "generation": 1,
        "owner_epoch": 1,
        "kind": "deploy",
        "status": "running",
        "deadline": clock.iso(1800),
        "payload": {
            "tenant_id": 1,
            "resolved_delivery": {
                "mode": "bundle",
                "platform": "linux/amd64",
                "profile": profile,
                "compiled_artifact_id": "compiled-a",
                "dependency_artifact_id": "dependencies-a",
                "environment_key": "c" * 64,
                "startup": {"command": ["python", "main.py"]},
            },
            "runtime_env": {"BISHENG_APP_TOKEN": "fixture-business-token"},
            "tier": {"memory_mb": 512, "cpu_millicores": 250},
            "port": 8080,
            "health": {"path": "/health", "start_period": 1, "interval": 1, "retries": 1},
        },
    }
    platform.operations[op["operation_id"]] = op
    executor = KubernetesExecutor(config, settings, platform=platform, client=cluster, clock=clock)
    return executor, platform, cluster, op, events, clock


def test_material_private_keys_recover_independently_and_change_for_each_workload():
    from runtime_manager.executors.kubernetes import workload_signer

    seed = b"m" * 32
    first = "11111111-1111-4111-8111-111111111111"
    second = "22222222-2222-4222-8222-222222222222"
    a = workload_signer(seed, first).public_key().public_bytes_raw()
    assert a == workload_signer(seed, first).public_key().public_bytes_raw()
    assert a != workload_signer(seed, second).public_key().public_bytes_raw()
    assert a != workload_signer(b"n" * 32, first).public_key().public_bytes_raw()
    assert workload_signer(seed, first).private_bytes_raw() != seed


def test_bundle_launch_registers_safe_resources_before_cluster_calls_and_returns_service_target(runtime):
    executor, platform, cluster, op, events, _ = runtime
    result = executor.launch(op)
    assert result["exec_ref"] in platform.rows and result["target"] == {"host": "10.96.0.10", "port": 8080}
    assert platform.rows[result["exec_ref"]]["name"] == production_name(op["app_id"])
    assert result["pod_uid"] == platform.rows[result["exec_ref"]]["uid"]
    assert result["service_uid"] == platform.rows[result["service_ref"]]["uid"]
    assert len([x for x in events if x[0] == "material-bind"]) == 1
    assert "fixture-business-token" not in json.dumps([r["template"] for r in platform.rows.values()])
    secret_bodies = [x for (kind, _), x in cluster.objects.items() if kind == "secrets"]
    identity = next(
        json.loads(base64.b64decode(s["data"]["identity.json"])) for s in secret_bodies if "identity.json" in s["data"]
    )
    assert identity["scope_kind"] == "deployment-init" and identity["private_key"]
    assert "private_key" not in json.dumps(platform.delegations)


def test_full_image_skips_material_identity_and_materialization(runtime):
    executor, platform, cluster, op, _, _ = runtime
    op["payload"]["resolved_delivery"] = {
        "mode": "image",
        "image_ref": IMAGE,
        "image_id": "sha256:" + "a" * 64,
        "platform": "linux/amd64",
        "startup": {},
    }
    result = executor.launch(op)
    pod = cluster.objects["pods", platform.rows[result["exec_ref"]]["name"]]
    assert not platform.delegations and "command" not in pod["spec"]["containers"][0]
    assert all(c["name"] not in {"environment", "material-fetch"} for c in pod["spec"]["initContainers"])


def test_retry_after_response_loss_adopts_only_the_same_bound_uid(runtime):
    executor, _platform, _cluster, op, events, _ = runtime
    first = executor.launch(op)
    count = len([e for e in events if e[0] == "create"])
    second = executor.launch(op)
    assert second["exec_ref"] == first["exec_ref"] and second["pod_uid"] == first["pod_uid"]
    assert len([e for e in events if e[0] == "create"]) == count


def test_same_name_replacement_is_not_adopted_or_deleted(runtime):
    from runtime_manager.executors.protocol import ExecutorError

    executor, platform, cluster, op, events, _ = runtime
    first = executor.launch(op)
    name = platform.rows[first["exec_ref"]]["name"]
    cluster.objects["pods", name]["metadata"]["uid"] = str(uuid4())
    with pytest.raises(ExecutorError):
        executor.launch(op)
    assert not any(e[0] == "delete" for e in events)


def test_stop_confirmation_is_committed_before_finalizer_removal_and_keeps_pvc(runtime):
    executor, _platform, cluster, op, events, _ = runtime
    first = executor.launch(op)
    executor.request_stop(first["exec_ref"], op)
    outcome = executor.confirm_stopped(first["exec_ref"])
    assert outcome["stopped"] is True and outcome["evidence_kind"] == "kubelet_terminal"
    stop_index = next(i for i, e in enumerate(events) if e[:2] == ("stopped", first["exec_ref"]))
    patch_index = next(i for i, e in enumerate(events) if e[:2] == ("patch", "pods"))
    assert stop_index < patch_index
    assert any(kind == "persistentvolumeclaims" for kind, _ in cluster.objects)


def test_running_or_missing_uid_never_releases_the_writer(runtime):
    executor, platform, cluster, op, events, _ = runtime
    first = executor.launch(op)
    cluster.still_running = True
    executor.request_stop(first["exec_ref"], op)
    assert executor.confirm_stopped(first["exec_ref"])["stopped"] is False
    del cluster.objects["pods", platform.rows[first["exec_ref"]]["name"]]
    assert executor.confirm_stopped(first["exec_ref"])["stopped"] is False
    assert (
        not any(e[0] == "stopped" for e in events) and platform.rows[first["exec_ref"]]["cleanup_state"] != "complete"
    )


def test_preview_never_reuses_production_volume(runtime):
    executor, platform, cluster, op, _, clock = runtime
    op["kind"] = "preview"
    op["payload"]["preview_expires_at"] = clock.iso(600)
    result = executor.launch(op, preview=True)
    pod = cluster.objects["pods", platform.rows[result["exec_ref"]]["name"]]
    assert pod["metadata"]["name"] != production_name(op["app_id"])
    assert all("persistentVolumeClaim" not in v for v in pod["spec"]["volumes"])


def test_readiness_requires_the_service_endpoint_for_this_pod_uid(runtime):
    from runtime_manager.executors.protocol import ExecutorError

    executor, _, cluster, op, _, clock = runtime
    cluster.endpoints_ready = False
    start = clock.time()
    with pytest.raises(ExecutorError):
        executor.launch(op)
    assert clock.time() - start < 120


def test_bad_frozen_architecture_is_rejected_before_cluster_mutations(runtime):
    from runtime_manager.executors.protocol import ExecutorError

    executor, _, _, op, events, _ = runtime
    op["payload"]["resolved_delivery"]["platform"] = "linux/arm64"
    with pytest.raises(ExecutorError):
        executor.launch(op)
    assert not any(e[0] == "create" for e in events)


def test_logs_uses_the_supported_bounded_core_parameters(runtime):
    executor, _, _, op, _, _ = runtime
    result = executor.launch(op)
    assert executor.logs(result["exec_ref"], since=30, tail=20) == "fixture app log"


def test_cleanup_checks_same_uid_and_keeps_production_volume(runtime):
    executor, platform, cluster, op, _, _ = runtime
    executor.launch(op)
    assert executor.cleanup(op) == {"complete": True}
    assert not any(kind == "pods" for kind, _ in cluster.objects)
    assert any(kind == "persistentvolumeclaims" for kind, _ in cluster.objects)
    assert all(r["cleanup_state"] == "complete" for r in platform.rows.values() if r["kind"] != "PersistentVolumeClaim")


@pytest.fixture
def bundle_delivery_contract():
    # Load the real, standalone manifest schema without installing backend services.
    source = Path(__file__).resolve().parents[2] / "backend/bisheng/app_publish/domain/schemas/app_manifest.py"
    name = "f059_test_bundle_delivery_contract"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module.BundleDelivery
    finally:
        del sys.modules[name]


@pytest.mark.parametrize("reference", ["python-test@1", None])
def test_prepare_consumes_resolved_profile_not_manifest_reference(runtime, bundle_delivery_contract, reference):
    """覆盖 AC: AC-04、AC-24、AC-25、AC-36、AC-55."""
    executor, platform, _cluster, operation, events, _ = runtime
    operation["kind"] = "prepare"
    profile = copy.deepcopy(operation["payload"].pop("resolved_delivery")["profile"])
    operation["payload"].update(
        profile=profile,
        source_artifact_id="source-a",
        delivery=bundle_delivery_contract(profile=reference).model_dump(mode="json"),
    )
    result = executor.prepare(operation)
    assert operation["payload"]["delivery"]["profile"] == reference
    assert result["profile"] == profile
    pods = [row for row in platform.rows.values() if row["kind"] == "Pod"]
    assert len(pods) == 4
    assert all(row["template"]["spec"]["securityContext"]["runAsUser"] == profile["uid"] for row in pods)
    assert all(row["stop_state"] == "confirmed" for row in pods)
    assert len([event for event in events if event[:2] == ("create", "pods")]) == 4


def test_runtime_plan_uses_frozen_delivery_profile_instead_of_prepare_input(runtime, bundle_delivery_contract):
    """覆盖 AC: AC-04、AC-24、AC-25、AC-36、AC-55."""
    executor, _, _, operation, _, _ = runtime
    operation["payload"].update(
        delivery=bundle_delivery_contract(profile="unrelated-reference@9").model_dump(mode="json"),
        profile={"platform": "linux/arm64", "runtime_image": "wrong:tag", "uid": 20002, "gid": 20002},
    )
    frozen = operation["payload"]["resolved_delivery"]["profile"]
    plan = executor._plan(operation, "serve")
    assert (plan.image, plan.platform, plan.uid, plan.gid) == (
        frozen["runtime_image"],
        frozen["platform"],
        frozen["uid"],
        frozen["gid"],
    )


@pytest.mark.parametrize("kind", ["prepare", "deploy"])
@pytest.mark.parametrize("invalid", ["python-test@1", ["profile"], None, {}])
def test_invalid_frozen_profile_is_refused_before_resource_reads(
    runtime, monkeypatch, bundle_delivery_contract, kind, invalid
):
    """覆盖 AC: AC-04、AC-24、AC-25、AC-36、AC-55."""
    from runtime_manager.executors.protocol import ExecutorError

    executor, platform, cluster, operation, events, _ = runtime
    operation["kind"] = kind
    if kind == "prepare":
        # Even a valid stale resolved_delivery must not mask invalid prepare input.
        operation["payload"]["profile"] = invalid
        operation["payload"]["delivery"] = bundle_delivery_contract(profile="python-test@1").model_dump(mode="json")
    else:
        # A valid top-level prepare profile must not repair invalid frozen output.
        operation["payload"]["profile"] = copy.deepcopy(operation["payload"]["resolved_delivery"]["profile"])
        operation["payload"]["resolved_delivery"]["profile"] = invalid
    monkeypatch.setattr(
        platform, "resource", lambda _reference: pytest.fail("invalid profile must not query a resource")
    )
    with pytest.raises(ExecutorError, match="frozen_profile_invalid"):
        if kind == "prepare":
            executor.prepare(operation)
        else:
            executor._plan(operation, "serve")
    assert not cluster.objects and not platform.rows and not events


@pytest.mark.parametrize("kind", ["prepare", "deploy"])
@pytest.mark.parametrize("invalid", ["bundle", ["bundle"], None])
def test_invalid_delivery_container_is_refused_before_resource_reads(runtime, monkeypatch, kind, invalid):
    """覆盖 AC: AC-04、AC-24、AC-25、AC-36、AC-55."""
    from runtime_manager.executors.protocol import ExecutorError

    executor, platform, cluster, operation, events, _ = runtime
    operation["kind"] = kind
    operation["payload"]["profile"] = copy.deepcopy(operation["payload"]["resolved_delivery"]["profile"])
    if kind == "prepare":
        operation["payload"]["delivery"] = invalid
    else:
        operation["payload"]["delivery"] = {"mode": "bundle"}
        operation["payload"]["resolved_delivery"] = invalid
    monkeypatch.setattr(
        platform, "resource", lambda _reference: pytest.fail("invalid delivery must not query a resource")
    )
    with pytest.raises(ExecutorError, match="frozen_delivery_invalid"):
        if kind == "prepare":
            executor.prepare(operation)
        else:
            executor._plan(operation, "serve")
    assert not cluster.objects and not platform.rows and not events


def test_prepare_separates_download_install_upload_and_persists_phase_results(runtime):
    executor, platform, _cluster, op, events, _ = runtime
    op["kind"] = "prepare"
    op["payload"]["profile"] = op["payload"].pop("resolved_delivery")["profile"]
    op["payload"].update(source_artifact_id="source-a", delivery={"mode": "bundle", "dependencies": {}})
    result = executor.prepare(op)
    assert result["compiled_artifact_id"] == "compiled-result"
    pods = [r for r in platform.rows.values() if r["kind"] == "Pod"]
    assert [r["purpose"] for r in pods] == ["prepare-download", "prepare-download", "prepare-install", "prepare-upload"]
    assert all(r["stop_state"] == "confirmed" for r in pods)
    assert all(
        stage in platform.operations[op["operation_id"]]["result"]["prepare_progress"]
        for stage in ("inputs", "resolve", "install", "upload")
    )
    first_fact = next(i for i, event in enumerate(events) if event[:2] == ("fact", "preparing"))
    first_stop = next(i for i, event in enumerate(events) if event[0] == "stop")
    assert first_fact < first_stop
    install = next(r["template"] for r in pods if r["purpose"] == "prepare-install")
    assert "material-auth" not in json.dumps(install) and "secretKeyRef" not in json.dumps(install)
    assert executor.prepare(op) == result
    assert len([event for event in events if event[:2] == ("create", "pods")]) == 4


@pytest.mark.parametrize(
    "limits",
    [
        {"compressed": 75 * 1024**2, "unpacked": 300 * 1024**2, "entries": 30000},
        {"compressed": 1024, "unpacked": 4096, "entries": 10},
    ],
)
def test_prepare_preserves_frozen_source_limits_in_each_phase(runtime, monkeypatch, limits):
    """AC-24, AC-44, AC-56: K8s passes the platform's exact source admission bounds."""
    executor, _, _, op, _, _ = runtime
    op["kind"] = "prepare"
    op["payload"]["profile"] = op["payload"].pop("resolved_delivery")["profile"]
    op["payload"].update(
        source_artifact_id="source-a", delivery={"mode": "bundle", "dependencies": {}}, source_limits=limits
    )
    seen = []
    run_phase = executor._phase

    def capture(operation, stage, purpose, document, **kwargs):
        seen.append((stage, copy.deepcopy(document)))
        assert document.get("source_limits") is not limits
        return run_phase(operation, stage, purpose, document, **kwargs)

    monkeypatch.setattr(executor, "_phase", capture)
    assert executor.prepare(op)["compiled_artifact_id"] == "compiled-result"
    assert [stage for stage, _ in seen] == ["inputs", "resolve", "install", "upload"]
    assert all(document.get("source_limits") == limits for _, document in seen)
    assert op["payload"]["source_limits"] == limits


def test_data_capability_is_explicit_and_has_no_docker_fallback(runtime):
    from runtime_manager.executors.protocol import ExecutorError

    executor, _, _, op, _, _ = runtime
    with pytest.raises(ExecutorError, match="data_transport_unavailable"):
        executor.data(op, "list", {})

    class Transport:
        def request(self, operation, action, parameters):
            return {"operation_id": operation["operation_id"], "action": action, "parameters": parameters}

    executor.data_transport = Transport()
    assert executor.data(op, "list", {"limit": 10})["parameters"] == {"limit": 10}


def test_preview_retry_does_not_mutate_a_committed_deadline_or_secret(runtime):
    executor, _, _, op, events, clock = runtime
    op["kind"] = "preview"
    op["payload"]["preview_expires_at"] = clock.iso(600)
    first = executor.launch(op, preview=True)
    count = len([event for event in events if event[0] == "create"])
    clock.sleep(20)
    again = executor.launch(op, preview=True)
    assert again["pod_uid"] == first["pod_uid"]
    assert len([event for event in events if event[0] == "create"]) == count


def test_restart_retries_finalizer_removal_after_committed_stop(runtime, monkeypatch):
    from runtime_manager.executors.kubernetes import KubernetesExecutor

    executor, platform, cluster, op, _, clock = runtime
    first = executor.launch(op)
    executor.request_stop(first["exec_ref"], op)
    patch = cluster.patch

    def fail(*args, **kwargs):
        raise KubernetesAPIError("temporary", 503)

    monkeypatch.setattr(cluster, "patch", fail)
    with pytest.raises(KubernetesAPIError):
        executor.confirm_stopped(first["exec_ref"])
    assert platform.rows[first["exec_ref"]]["stop_state"] == "confirmed"
    monkeypatch.setattr(cluster, "patch", patch)
    restarted = KubernetesExecutor(executor.config, executor.settings, platform=platform, client=cluster, clock=clock)
    # An expired former controller can be replaced without treating expiry as stop proof.
    clock.sleep(31)
    assert restarted.confirm_stopped(first["exec_ref"])["stopped"] is True
    assert not any(kind == "pods" for kind, _ in cluster.objects)


def test_capabilities_report_the_frozen_domain_and_current_api_reachability(runtime, monkeypatch):
    executor, _, cluster, _, _, _ = runtime
    report = executor.capabilities()
    assert report["cluster_id"] == "cluster-a" and report["namespace"] == "runtime-apps"
    assert report["orchestration_available"] is True

    def unavailable(*args, **kwargs):
        raise KubernetesAPIError("unavailable", 503)

    monkeypatch.setattr(cluster, "list", unavailable)
    assert executor.capabilities()["orchestration_available"] is False


def test_backend_naive_utc_deadlines_do_not_depend_on_manager_timezone(runtime, monkeypatch):
    import time

    executor, _, _, op, _, clock = runtime
    original = __import__("os").environ.get("TZ")
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    try:
        op["kind"] = "probe"
        op["deadline"] = clock.iso(1800).removesuffix("+00:00")
        assert executor.launch(op)["ready"] is True
    finally:
        if original is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original)
        time.tzset()


@pytest.mark.parametrize(
    "purpose", ["prepare-download", "prepare-install", "prepare-upload", "assemble", "serve", "probe", "preview"]
)
def test_volume_guard_uses_the_actual_pvc_budget_and_installer_identity(runtime, purpose):
    executor, _, _, operation, _, _ = runtime
    executor.document.update(
        installation_id="f059-owned",
        storage={"size_mb": 256, "scratch_size_mb": 2048, "filesystem": "xfs", "static_pool": True},
    )
    plan = executor._plan(operation, purpose)
    if purpose in {"probe", "preview"}:
        assert plan.volume_guard == {} and not plan.scratch_pvc
    else:
        assert plan.volume_guard == {
            "namespace": executor.settings.namespace,
            "installation_id": "f059-owned",
            "filesystem": "xfs",
            "capacity_bytes": (256 if purpose == "serve" else 2048) * 1024**2,
            "marker_required": True,
        }
        assert bool(plan.scratch_pvc) == (purpose.startswith("prepare-") or purpose == "assemble")


@pytest.mark.parametrize("language", ["python3.11", "node20", "static"])
def test_plan_preserves_frozen_bundle_runtime_language(runtime, language):
    executor, _, _, operation, _, _ = runtime
    operation["payload"]["resolved_delivery"]["profile"]["language"] = language
    assert executor._plan(operation, "serve").runtime_language == language


@pytest.mark.parametrize("kind", ["deploy", "probe", "preview"])
@pytest.mark.parametrize("original,refreshed", [("", "kata-runtime"), ("kata-runtime", "")])
def test_retry_keeps_the_admitted_sandbox_when_optional_probe_changes(runtime, monkeypatch, kind, original, refreshed):
    executor, _, _, operation, _, _ = runtime
    operation["kind"] = kind
    sandbox = {"runtime_class": original}
    monkeypatch.setattr(executor, "probe_report", lambda: {"sandbox": sandbox})
    first = executor.launch(operation, preview=kind == "preview")
    sandbox["runtime_class"] = refreshed
    second = executor.launch(operation, preview=kind == "preview")
    assert first["pod_uid"] == second["pod_uid"]


@pytest.mark.parametrize(
    "field",
    [
        "resource_ref",
        "operation_id",
        "app_id",
        "node_id",
        "cluster_id",
        "namespace",
        "purpose",
        "generation",
        "owner_epoch",
        "kind",
    ],
)
def test_retry_refuses_a_recorded_pod_outside_the_frozen_operation(runtime, field):
    from runtime_manager.executors.protocol import ExecutorError

    executor, platform, _, operation, _, _ = runtime
    first = executor.launch(operation)
    platform.rows[first["exec_ref"]][field] = "foreign"
    with pytest.raises(ExecutorError, match="frozen_resource_scope_mismatch"):
        executor.launch(operation)


@pytest.fixture
def controller_http(runtime):
    """Real client status/reason parsing over the repository's strict 30s lease model."""
    executor, server, _, _, _, clock = runtime
    state = SimpleNamespace(failure=None, read_failure=False, calls=[])

    def reply(request):
        path = request.url.path.removeprefix(PREFIX)
        state.calls.append(path)
        try:
            if path == "/nodes/plan":
                if state.read_failure:
                    return httpx.Response(503, json={"error": {"reason": "fixture_read_unavailable"}})
                return httpx.Response(200, json=server.node_snapshot())
            body = json.loads(request.content)
            if path == "/controllers/claim":
                receipt = server.claim_controller(**body)
                if state.failure == "claim-response-loss":
                    state.failure = None
                    raise httpx.ReadTimeout("fixture lost claim response")
            elif path == "/controllers/renew":
                failure, state.failure = state.failure, None
                if failure == "unavailable":
                    raise PlatformError("fixture_unavailable", 503)
                if failure == "held":
                    raise PlatformError("controller_lease_held", 409)
                if failure == "forbidden":
                    raise PlatformError("service_role_refused", 403)
                if failure == "wrong-conflict":
                    raise PlatformError("controller_fact_fence_stale", 409)
                receipt = server.renew_controller(**body)
                if failure == "renew-response-loss":
                    raise httpx.ReadTimeout("fixture lost renew response")
                if failure == "slow-response":
                    clock.sleep(21)
            else:
                pytest.fail("unexpected controller endpoint")
            return httpx.Response(200, json=receipt)
        except PlatformError as exc:
            return httpx.Response(exc.status, json={"error": {"reason": str(exc)}})

    client = PlatformClient(executor.config, transport=httpx.MockTransport(reply))
    executor.platform = client
    yield executor, server, state, clock
    client.close()


def test_controller_recovers_after_idle_expiry_with_fresh_epoch(controller_http):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    executor, server, state, clock = controller_http
    first = executor._controller()
    clock.sleep(31)
    state.calls.clear()
    second = executor._controller()
    assert second == {"holder_id": executor.holder_id, "controller_epoch": first["controller_epoch"] + 1}
    assert state.calls == ["/controllers/renew", "/nodes/plan", "/controllers/claim", "/controllers/renew"]
    assert server.lease_until > clock.value


@pytest.mark.parametrize("failure", ["unavailable", "wrong-conflict", "renew-response-loss", "held", "forbidden"])
def test_uncertain_or_other_renew_failure_reads_fresh_but_refuses_current_action(controller_http, failure):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    executor, server, state, clock = controller_http
    first = executor._controller()
    clock.sleep(11)
    state.failure = failure
    state.calls.clear()
    with pytest.raises(PlatformError):
        executor._controller()
    assert state.calls == ["/controllers/renew", "/nodes/plan"]
    assert executor.controller_epoch == 0 and not executor.renew_at
    assert executor._controller() == first
    assert server.epoch == first["controller_epoch"]


def test_unknown_claim_response_is_reread_without_allowing_current_action(controller_http):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    executor, server, state, _ = controller_http
    state.failure = "claim-response-loss"
    with pytest.raises(PlatformError, match="platform_unreachable"):
        executor._controller()
    assert state.calls == ["/nodes/plan", "/controllers/claim", "/nodes/plan"]
    assert server.epoch == 1 and executor.controller_epoch == 0
    assert executor._controller()["controller_epoch"] == 1
    assert state.calls[-3:] == ["/nodes/plan", "/controllers/claim", "/controllers/renew"]


@pytest.mark.parametrize("offset", [-3600, 3600])
def test_controller_cache_uses_monotonic_time_not_server_wall_clock(controller_http, monkeypatch, offset):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    executor, server, state, clock = controller_http
    first = executor._controller()
    monkeypatch.setattr(clock, "time", lambda: clock.value + offset)
    clock.sleep(11)
    assert executor._controller() == first
    assert state.calls[-1] == "/controllers/renew"
    assert server.lease_until == clock.value + 30


def test_controller_rejects_a_response_that_consumed_its_safe_lease_budget(controller_http):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    from runtime_manager.executors.protocol import ExecutorError

    executor, _, state, _ = controller_http
    state.failure = "slow-response"
    with pytest.raises(ExecutorError, match="controller_lease_receipt_expired"):
        executor._controller()
    assert executor.controller_epoch == 0
    assert state.calls[-1] == "/nodes/plan"


def test_idempotent_claim_renews_the_existing_lease_before_caching(controller_http):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    executor, server, state, clock = controller_http
    server.claim_controller(executor.holder_id, 0)
    clock.sleep(29)
    assert executor._controller()["controller_epoch"] == 1
    assert state.calls == ["/nodes/plan", "/controllers/claim", "/controllers/renew"]
    assert server.lease_until == clock.value + 30


def test_concurrent_idle_recovery_claims_only_one_new_epoch(controller_http):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    executor, server, state, clock = controller_http
    executor._controller()
    clock.sleep(31)
    state.calls.clear()
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda _: executor._controller(), range(8)))
    assert all(receipt == receipts[0] for receipt in receipts)
    assert server.epoch == 2 and state.calls.count("/controllers/claim") == 1
    assert state.calls.count("/controllers/renew") == 2


def test_new_epoch_preserves_existing_uid_then_fences_observation_cleanup_and_facts(runtime):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    from runtime_manager.operations import OperationExecutor

    executor, platform, cluster, operation, _, clock = runtime
    target = executor.launch(operation)
    ref = target["exec_ref"]
    before = platform.resource(ref)
    assert before["controller_epoch"] == 1 and before["stop_state"] == "held"
    clock.sleep(31)
    assert executor._controller()["controller_epoch"] == 2
    unchanged = platform.resource(ref)
    assert (unchanged["uid"], unchanged["controller_epoch"], unchanged["stop_state"]) == (before["uid"], 1, "held")
    assert executor.observe(ref)["ready"]
    marker = len(platform.fences)
    executor.request_stop(ref, operation)
    assert executor.confirm_stopped(ref)["stopped"]
    assert executor.cleanup(operation)["complete"]
    service = SimpleNamespace(config=executor.config, runtime=executor, platform=platform)
    OperationExecutor.report(service, operation, "completed", detail={"stopped": True, "cleanup_complete": True})
    assert all(fence == {"holder_id": executor.holder_id, "controller_epoch": 2} for fence in platform.fences[marker:])
    assert platform.resource(ref)["uid"] == before["uid"]
    assert not any(kind == "pods" for kind, _ in cluster.objects)


def test_live_other_holder_blocks_existing_writer_mutations_and_facts(runtime):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    from runtime_manager.operations import OperationExecutor

    executor, platform, cluster, operation, events, clock = runtime
    ref = executor.launch(operation)["exec_ref"]
    clock.sleep(31)
    platform.claim_controller("other-live-holder", platform.epoch)
    before = copy.deepcopy((platform.rows, cluster.objects))
    marker = len(events)
    with pytest.raises(PlatformError, match="controller_lease_held"):
        executor.request_stop(ref, operation)
    service = SimpleNamespace(config=executor.config, runtime=executor, platform=platform)
    with pytest.raises(PlatformError, match="controller_lease_held"):
        OperationExecutor.report(service, operation, "failed")
    assert (platform.rows, cluster.objects) == before
    assert not any(event[0] in {"stop", "stopped", "create", "delete", "fact"} for event in events[marker:])


def test_uncertain_renew_and_failed_fresh_read_never_reclaim(controller_http):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    executor, _, state, clock = controller_http
    executor._controller()
    clock.sleep(11)
    state.failure, state.read_failure = "renew-response-loss", True
    state.calls.clear()
    with pytest.raises(PlatformError, match="platform_unreachable"):
        executor._controller()
    assert executor.controller_epoch == 0
    assert state.calls == ["/controllers/renew", "/nodes/plan"]


def test_recovered_controller_only_cleans_an_expired_prepare_without_starting_it(runtime, monkeypatch):
    """覆盖 AC: AC-01、AC-13、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-55."""
    from runtime_manager.operations import OperationExecutor

    executor, platform, cluster, operation, events, clock = runtime
    operation.update(kind="prepare", stage="admitted", deadline=clock.iso(20))
    executor._controller()
    clock.sleep(31)

    def refuse_expired(operation_id):
        assert operation_id == operation["operation_id"]
        assert datetime.fromisoformat(operation["deadline"]).timestamp() <= clock.value
        raise PlatformError("operation_expired", 409)

    monkeypatch.setattr(platform, "claim", refuse_expired, raising=False)
    monkeypatch.setattr(executor, "prepare", lambda *_: pytest.fail("expired prepare must never start"))
    service = OperationExecutor(executor.config, platform=platform, runtime=executor, clock=clock)
    try:
        service.execute(operation["operation_id"])
    finally:
        service.close()
    assert executor.controller_epoch == 2
    facts = [event for event in events if event[0] == "fact"]
    assert len(facts) == 1 and facts[0][1] == "failed"
    assert platform.operations[operation["operation_id"]]["result"]["cleanup_complete"] is True
    assert platform.operations[operation["operation_id"]]["result"]["stopped"] is True
    assert not platform.rows and not cluster.objects


# T205/T206: creation rejection is distinct from a missing formerly-created UID.
def _uncreated_pod(runtime, *, purpose="prepare-download"):
    from runtime_manager.k8s_templates import pod_template

    executor, _, _, operation, _, _ = runtime
    plan = executor._plan(operation, purpose)
    template = pod_template(plan)
    row = executor._intent(operation, plan, template, plan.resource_ref)
    return row, template, plan


def test_pod_create_attempt_is_committed_before_post(runtime, monkeypatch):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, _, events, _ = runtime
    row, template, _ = _uncreated_pod(runtime)
    original = cluster.create

    def create(resource, body):
        saved = platform.resource(row["resource_ref"])["observed_state"]["creation"]
        assert saved["state"] == "started" and saved["create_attempt_id"]
        return original(resource, body)

    monkeypatch.setattr(cluster, "create", create)
    executor._create(row, template)
    begin = next(i for i, e in enumerate(events) if e[0] == "create_begin")
    post = next(i for i, e in enumerate(events) if e[:2] == ("create", "pods"))
    assert begin < post


def test_explicit_create_403_can_close_uncreated_pod_and_scratch(runtime, monkeypatch):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    row, template, plan = _uncreated_pod(runtime)
    executor._volume(operation, plan)
    original = cluster.create

    def refused(resource, body):
        if resource == "pods":
            raise KubernetesAPIError("k8s_api_refused", 403)
        return original(resource, body)

    monkeypatch.setattr(cluster, "create", refused)
    with pytest.raises(KubernetesAPIError):
        executor._create(row, template)
    assert platform.resource(row["resource_ref"])["observed_state"]["creation"]["state"] == "rejected"
    assert executor.cleanup(operation) == {"complete": True}
    saved = platform.resource(row["resource_ref"])
    assert saved["uid"] is None and saved["stop_state"] == "confirmed"
    assert saved["stop_evidence"]["evidence_kind"] == "not_created" and saved["cleanup_state"] == "complete"
    assert not cluster.objects
    assert not any(e[:2] in {("delete", "pods"), ("patch", "pods"), ("stopped", row["resource_ref"])} for e in events)
    fence = next(i for i, e in enumerate(events) if e[0] == "create_fence")
    proof = next(i for i, e in enumerate(events) if e[0] == "not_created")
    scratch_delete = next(i for i, e in enumerate(events) if e[:2] == ("delete", "persistentvolumeclaims"))
    assert fence < proof < scratch_delete


@pytest.mark.parametrize("status", [None, 409, 500, 429, 400, 401, 422])
def test_uncertain_or_unapproved_create_outcome_never_closes_missing_pod(runtime, monkeypatch, status):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    row, template, plan = _uncreated_pod(runtime)
    executor._volume(operation, plan)

    def uncertain(*_):
        raise KubernetesAPIError("transport_unavailable" if status is None else "k8s_api_refused", status)

    monkeypatch.setattr(cluster, "create", uncertain)
    with pytest.raises(KubernetesAPIError):
        executor._create(row, template)
    assert platform.resource(row["resource_ref"])["observed_state"]["creation"]["state"] == "started"
    assert executor.cleanup(operation)["complete"] is False
    assert not any(e[0] in {"create_fence", "not_created", "stopped", "cleanup", "delete", "patch"} for e in events)
    assert any(kind == "persistentvolumeclaims" for kind, _ in cluster.objects)


@pytest.mark.parametrize("state", ["unattempted", "rejected", "fenced"])
def test_new_controller_resumes_only_proven_uncreated_cleanup(runtime, state, monkeypatch):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, clock = runtime
    row, _, _ = _uncreated_pod(runtime)
    creation = platform.rows[row["resource_ref"]]["observed_state"]["creation"]
    creation.update(state=state)
    if state != "unattempted":
        creation.update(create_attempt_id=str(uuid4()), controller_epoch=1, http_status=403)
    if state == "fenced":
        creation["outcome"] = "rejected"
    clock.sleep(31)
    monkeypatch.setattr(cluster, "create", lambda *_: pytest.fail("cleanup must not POST"))
    assert executor.cleanup(operation)["complete"]
    assert platform.resource(row["resource_ref"])["uid"] is None and executor.controller_epoch == 2
    assert len([e for e in events if e[0] == "create_fence"]) == (state != "fenced")


@pytest.mark.parametrize(
    "creation", [{}, {"version": 1, "state": "started"}, {"version": True, "state": "unattempted"}]
)
def test_legacy_unknown_and_started_missing_intents_cannot_retry_or_cleanup(runtime, monkeypatch, creation):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    row, template, _ = _uncreated_pod(runtime)
    platform.rows[row["resource_ref"]]["observed_state"] = {"creation": creation} if creation else {}
    row = platform.resource(row["resource_ref"])
    monkeypatch.setattr(cluster, "create", lambda *_: pytest.fail("unknown intent must not be re-posted"))
    with pytest.raises(ExecutorError, match="pod_creation_unconfirmed"):
        executor._create(row, template)
    assert executor.cleanup(operation)["complete"] is False
    assert not any(
        e[0] in {"create_begin", "create_fence", "not_created", "cleanup", "delete", "patch"} for e in events
    )


@pytest.mark.parametrize("creation_state", ["started", "rejected", "legacy"])
def test_fresh_existing_unbound_pod_uses_uid_stop_instead_of_noncreation(runtime, creation_state):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    row, template, _ = _uncreated_pod(runtime)
    created = cluster.create("pods", template)
    platform.rows[row["resource_ref"]]["observed_state"] = (
        {} if creation_state == "legacy" else {"creation": {"version": 1, "state": creation_state}}
    )
    assert executor.cleanup(operation)["complete"]
    saved = platform.resource(row["resource_ref"])
    assert saved["uid"] == created["metadata"]["uid"]
    assert saved["stop_evidence"]["evidence_kind"] == "kubelet_terminal"
    assert any(e[:2] == ("delete", "pods") for e in events)
    assert not any(e[0] in {"create_fence", "not_created"} for e in events)


def test_noncreation_proof_never_removes_finalizer_from_reappearing_object(runtime):
    """覆盖 AC: AC-49、AC-52."""
    from runtime_manager.executors.protocol import ExecutorError

    executor, platform, cluster, operation, events, _ = runtime
    row, template, _ = _uncreated_pod(runtime)
    assert executor.cleanup(operation)["complete"]
    cluster.create("pods", template)
    marker = len(events)
    with pytest.raises(ExecutorError):
        executor.confirm_stopped(row["resource_ref"])
    assert not any(e[0] in {"bind", "delete", "patch", "cleanup", "stopped"} for e in events[marker:])
    assert platform.resource(row["resource_ref"])["uid"] is None


def test_create_receipt_loss_does_not_send_pod_post(runtime, monkeypatch):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, _, _, _ = runtime
    row, template, _ = _uncreated_pod(runtime)
    original = platform.observe_resource

    def loss(ref, document):
        result = original(ref, document)
        if document["action"] == "create_begin":
            raise PlatformError("platform_unreachable", 503)
        return result

    monkeypatch.setattr(platform, "observe_resource", loss)
    monkeypatch.setattr(cluster, "create", lambda *_: pytest.fail("unacknowledged begin must not POST"))
    with pytest.raises(PlatformError):
        executor._create(row, template)
    assert platform.resource(row["resource_ref"])["observed_state"]["creation"]["state"] == "started"


def test_rejection_receipt_loss_keeps_uncertainty(runtime, monkeypatch):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    row, template, _ = _uncreated_pod(runtime)
    original = platform.observe_resource

    def loss(ref, document):
        if document["action"] == "create_rejected":
            raise PlatformError("platform_unreachable", 503)
        return original(ref, document)

    monkeypatch.setattr(platform, "observe_resource", loss)
    monkeypatch.setattr(cluster, "create", lambda *_: (_ for _ in ()).throw(KubernetesAPIError("refused", 403)))
    with pytest.raises(PlatformError):
        executor._create(row, template)
    assert executor.cleanup(operation)["complete"] is False
    assert not any(e[0] in {"create_fence", "not_created", "cleanup"} for e in events)


def test_uncertain_fresh_read_after_fence_cannot_persist_noncreation(runtime, monkeypatch):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    row, _, _ = _uncreated_pod(runtime)
    original = cluster.get

    def read(resource, name):
        if (
            resource == "pods"
            and platform.resource(row["resource_ref"])["observed_state"]["creation"]["state"] == "fenced"
        ):
            raise KubernetesAPIError("transport_unavailable")
        return original(resource, name)

    monkeypatch.setattr(cluster, "get", read)
    with pytest.raises(KubernetesAPIError):
        executor.cleanup(operation)
    assert not any(e[0] in {"not_created", "cleanup", "delete", "patch"} for e in events)


def test_unknown_second_pod_blocks_scratch_cleanup(runtime):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    first, _, plan = _uncreated_pod(runtime)
    executor._volume(operation, plan)
    second, _, _ = _uncreated_pod(runtime, purpose="prepare-upload")
    platform.rows[second["resource_ref"]]["observed_state"] = {}
    assert executor.cleanup(operation)["complete"] is False
    assert platform.resource(first["resource_ref"])["stop_evidence"]["evidence_kind"] == "not_created"
    assert any(kind == "persistentvolumeclaims" for kind, _ in cluster.objects)
    assert not any(e[0] in {"delete", "patch", "cleanup"} for e in events)


@pytest.mark.parametrize(
    "field", ["resource_ref", "operation_id", "spec_digest", "uid", "state", "attempt", "epoch", "version"]
)
def test_invalid_create_begin_receipt_never_sends_post(runtime, monkeypatch, field):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, _, _, _ = runtime
    row, template, _ = _uncreated_pod(runtime)
    original = platform.observe_resource

    def changed(ref, document):
        result = original(ref, document)
        if document["action"] == "create_begin":
            creation = result["observed_state"]["creation"]
            if field in {"resource_ref", "operation_id", "spec_digest", "uid"}:
                result[field] = "changed"
            elif field == "state":
                creation["state"] = "rejected"
            elif field == "attempt":
                creation["create_attempt_id"] = str(uuid4())
            elif field == "epoch":
                creation["controller_epoch"] += 1
            else:
                creation["version"] = True
        return result

    monkeypatch.setattr(platform, "observe_resource", changed)
    monkeypatch.setattr(cluster, "create", lambda *_: pytest.fail("invalid creation receipt must not POST"))
    with pytest.raises(ExecutorError, match="pod_creation_receipt_refused"):
        executor._create(row, template)


def test_lost_create_response_recovers_real_uid_without_second_post(runtime, monkeypatch):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    row, template, _ = _uncreated_pod(runtime)
    original = cluster.create

    def lost(resource, body):
        original(resource, body)
        raise KubernetesAPIError("transport_unavailable")

    monkeypatch.setattr(cluster, "create", lost)
    with pytest.raises(KubernetesAPIError):
        executor._create(row, template)
    uid = cluster.objects["pods", row["name"]]["metadata"]["uid"]
    monkeypatch.setattr(cluster, "create", lambda *_: pytest.fail("must recover created UID without another POST"))
    assert executor._create(platform.resource(row["resource_ref"]), template)["metadata"]["uid"] == uid
    assert executor.cleanup(operation)["complete"]
    assert len([e for e in events if e[:2] == ("create", "pods")]) == 1
    assert not any(e[0] in {"create_fence", "not_created"} for e in events)


@pytest.mark.parametrize("action", ["create_fence", "not_created"])
def test_lost_noncreation_receipt_resumes_durable_fence_without_post(runtime, monkeypatch, action):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    row, _, _ = _uncreated_pod(runtime)
    original = platform.observe_resource
    lost = False

    def loss(ref, document):
        nonlocal lost
        result = original(ref, document)
        if document["action"] == action and not lost:
            lost = True
            raise PlatformError("platform_unreachable", 503)
        return result

    monkeypatch.setattr(platform, "observe_resource", loss)
    monkeypatch.setattr(cluster, "create", lambda *_: pytest.fail("cleanup must not create"))
    with pytest.raises(PlatformError):
        executor.cleanup(operation)
    assert executor.cleanup(operation)["complete"]
    assert len([e for e in events if e[0] == "create_fence"]) == 1
    assert len([e for e in events if e[0] == "not_created"]) == 1
    assert platform.resource(row["resource_ref"])["uid"] is None


def test_foreign_object_cannot_be_bound_or_closed_as_uncreated(runtime):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    row, template, _ = _uncreated_pod(runtime)
    cluster.create("pods", template)
    cluster.objects["pods", row["name"]]["metadata"]["labels"][RESOURCE_LABEL] = str(uuid4())
    marker = len(events)
    with pytest.raises(ExecutorError, match="resource_uid_or_scope_mismatch"):
        executor.cleanup(operation)
    assert not any(
        e[0] in {"bind", "create_fence", "not_created", "delete", "patch", "cleanup"} for e in events[marker:]
    )
    assert platform.resource(row["resource_ref"])["uid"] is None


def test_live_other_controller_cannot_close_uncreated_intent(runtime):
    """覆盖 AC: AC-49、AC-52."""
    executor, platform, _, operation, events, clock = runtime
    _uncreated_pod(runtime)
    clock.sleep(31)
    platform.claim_controller("other-live-holder", platform.epoch)
    marker = len(events)
    with pytest.raises(PlatformError, match="controller_lease_held"):
        executor.cleanup(operation)
    assert not any(
        e[0] in {"create_begin", "create_fence", "not_created", "delete", "patch", "cleanup"} for e in events[marker:]
    )


# T219/T220: the real scheduler binds after create/UID registration.
def _delayed_bound_task(runtime):
    executor, platform, cluster, _, _, _ = runtime
    cluster.delay_binding = True
    row, template, _ = _uncreated_pod(runtime)
    executor._create(row, template)
    saved = platform.resource(row["resource_ref"])
    assert saved["uid"] and not saved["node_name"]
    pod = cluster.objects["pods", row["name"]]
    assert pod["status"]["phase"] == "Pending" and not pod["spec"].get("nodeName")
    pod["spec"]["nodeName"] = "worker-a"
    pod["metadata"]["resourceVersion"] = str(int(pod["metadata"]["resourceVersion"]) + 1)
    pod["status"] = {
        "phase": "Succeeded",
        "containerStatuses": [{"name": "transfer", "state": {"terminated": {"exitCode": 0}}}],
    }
    return saved, pod


def test_delayed_scheduler_binding_is_persisted_before_stop_and_proof(runtime, monkeypatch):
    """覆盖 AC: AC-33、AC-49、AC-52."""
    executor, platform, _, operation, events, _ = runtime
    row, _ = _delayed_bound_task(runtime)
    original = platform.observe_resource
    bindings = []

    def observe(ref, body):
        if body["action"] == "bind":
            bindings.append((body["uid"], body["node_name"]))
        return original(ref, body)

    monkeypatch.setattr(platform, "observe_resource", observe)
    marker = len(events)
    executor.request_stop(row["resource_ref"], operation)
    assert executor.confirm_stopped(row["resource_ref"])["stopped"]
    saved = platform.resource(row["resource_ref"])
    assert bindings == [(row["uid"], "worker-a")]
    assert saved["node_name"] == saved["stop_evidence"]["node_name"] == "worker-a"
    subset = events[marker:]
    assert next(i for i, e in enumerate(subset) if e[0] == "bind") < next(
        i for i, e in enumerate(subset) if e[0] == "stop"
    )
    assert executor.cleanup(operation)["complete"]


def test_confirm_recovers_real_binding_left_empty_by_previous_manager(runtime):
    """覆盖 AC: AC-33、AC-49、AC-52."""
    executor, platform, cluster, operation, _, _ = runtime
    row, pod = _delayed_bound_task(runtime)
    executor._observation(row, "stop", operation_id=operation["operation_id"])
    cluster.delete("pods", row["name"], uid=row["uid"], resource_version=pod["metadata"]["resourceVersion"])
    assert executor.confirm_stopped(row["resource_ref"])["stopped"]
    saved = platform.resource(row["resource_ref"])
    assert saved["node_name"] == saved["stop_evidence"]["node_name"] == "worker-a"


def test_prepare_progress_and_cleanup_survive_real_delayed_binding(runtime, monkeypatch):
    """覆盖 AC: AC-33、AC-49、AC-52."""
    from dataclasses import replace

    executor, platform, cluster, operation, _, _ = runtime
    operation["kind"] = "prepare"
    delivery = operation["payload"]["resolved_delivery"]
    operation["payload"].update(delivery={"mode": "bundle"}, profile=delivery["profile"])
    cluster.delay_binding = True
    plan = replace(executor._plan(operation, "prepare-download"), helper_env={"MATERIAL_PLAN": '{"phase":"inputs"}'})
    original = cluster.get
    observed_pending = False

    def schedule(resource, name):
        nonlocal observed_pending
        pod = cluster.objects.get((resource, name))
        if resource == "pods" and pod and not pod["spec"].get("nodeName"):
            if observed_pending:
                pod["spec"]["nodeName"] = "worker-a"
                pod["metadata"]["resourceVersion"] = str(int(pod["metadata"]["resourceVersion"]) + 1)
                pod["status"] = {
                    "phase": "Succeeded",
                    "containerStatuses": [{"name": "transfer", "state": {"terminated": {"exitCode": 0}}}],
                }
            observed_pending = True
        return original(resource, name)

    monkeypatch.setattr(cluster, "get", schedule)
    assert executor._phase(operation, "inputs", "prepare-download", {}, plan=plan)["input_key"] == "c" * 64
    saved = platform.resource(plan.resource_ref)
    assert saved["node_name"] == "worker-a" and saved["stop_evidence"]["node_name"] == "worker-a"
    assert operation["result"]["prepare_progress"]["inputs"]["exec_ref"] == plan.resource_ref
    assert executor.cleanup(operation)["complete"]


@pytest.mark.parametrize("method", ["request_stop", "confirm_stopped"])
@pytest.mark.parametrize("change", ["replacement_uid", "different_node", "cleared_node"])
def test_binding_refresh_rejects_replacement_or_changed_nonempty_node(runtime, method, change):
    """覆盖 AC: AC-33、AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    ref = executor.launch(operation)["exec_ref"]
    row = platform.resource(ref)
    pod = cluster.objects["pods", row["name"]]
    if change == "replacement_uid":
        pod["metadata"]["uid"] = str(uuid4())
    elif change == "different_node":
        pod["spec"]["nodeName"] = "worker-b"
    else:
        pod["spec"].pop("nodeName")
    marker = len(events)
    with pytest.raises(ExecutorError):
        executor.request_stop(ref, operation) if method == "request_stop" else executor.confirm_stopped(ref)
    assert not any(e[0] in {"bind", "stop", "stopped", "delete", "patch", "cleanup"} for e in events[marker:])
    assert platform.resource(ref)["node_name"] == "worker-a"


def test_binding_receipt_failure_never_deletes_or_confirms_stop(runtime, monkeypatch):
    """覆盖 AC: AC-33、AC-49、AC-52."""
    executor, platform, _, operation, events, _ = runtime
    row, _ = _delayed_bound_task(runtime)
    original = platform.observe_resource

    def refused(ref, body):
        if body["action"] == "bind":
            raise PlatformError("platform_unreachable", 503)
        return original(ref, body)

    monkeypatch.setattr(platform, "observe_resource", refused)
    marker = len(events)
    with pytest.raises(PlatformError):
        executor.request_stop(row["resource_ref"], operation)
    assert not any(e[0] in {"stop", "stopped", "delete", "patch", "cleanup"} for e in events[marker:])
    assert not platform.resource(row["resource_ref"])["node_name"]


def test_completed_never_scheduled_proof_is_not_rewritten_as_later_binding(runtime):
    """覆盖 AC: AC-33、AC-49、AC-52."""
    executor, platform, _, _, events, _ = runtime
    row, pod = _delayed_bound_task(runtime)
    saved = platform.rows[row["resource_ref"]]
    saved.update(stop_state="confirmed", stop_evidence={"evidence_kind": "never_scheduled", "node_name": ""})
    pod["metadata"]["deletionTimestamp"] = "2026-10-21T04:00:00+00:00"
    marker = len(events)
    with pytest.raises(ExecutorError):
        executor.confirm_stopped(row["resource_ref"])
    assert not any(e[0] in {"bind", "stopped", "delete", "patch", "cleanup"} for e in events[marker:])
    assert not platform.resource(row["resource_ref"])["node_name"]


@pytest.mark.parametrize("status", [404, 403, None])
def test_binding_read_uncertainty_never_deletes_or_confirms(runtime, monkeypatch, status):
    """覆盖 AC: AC-33、AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    row, _ = _delayed_bound_task(runtime)

    def unavailable(*_):
        raise KubernetesAPIError("transport_unavailable" if status is None else "api_refused", status)

    monkeypatch.setattr(cluster, "get", unavailable)
    marker = len(events)
    assert not executor.request_stop(row["resource_ref"], operation)["stopped"]
    assert not executor.confirm_stopped(row["resource_ref"])["stopped"]
    assert not any(e[0] in {"bind", "stopped", "delete", "patch", "cleanup"} for e in events[marker:])
    assert not platform.resource(row["resource_ref"])["node_name"]


@pytest.mark.parametrize("field", ["uid", "node_name", "resource_ref"])
def test_changed_binding_receipt_never_permits_stop_effect(runtime, monkeypatch, field):
    """覆盖 AC: AC-33、AC-49、AC-52."""
    executor, platform, _, operation, events, _ = runtime
    row, _ = _delayed_bound_task(runtime)
    original = platform.observe_resource

    def changed(ref, body):
        result = original(ref, body)
        if body["action"] == "bind":
            result[field] = "changed"
        return result

    monkeypatch.setattr(platform, "observe_resource", changed)
    marker = len(events)
    with pytest.raises(ExecutorError, match="resource_binding_receipt_refused"):
        executor.request_stop(row["resource_ref"], operation)
    assert not any(e[0] in {"stop", "stopped", "delete", "patch", "cleanup"} for e in events[marker:])


def test_lost_binding_receipt_resumes_same_uid_stop_without_rebinding(runtime, monkeypatch):
    """覆盖 AC: AC-33、AC-49、AC-52."""
    executor, platform, _, operation, events, _ = runtime
    row, _ = _delayed_bound_task(runtime)
    original = platform.observe_resource
    lost = False

    def loss(ref, body):
        nonlocal lost
        result = original(ref, body)
        if body["action"] == "bind" and not lost:
            lost = True
            raise PlatformError("platform_unreachable", 503)
        return result

    monkeypatch.setattr(platform, "observe_resource", loss)
    marker = len(events)
    with pytest.raises(PlatformError):
        executor.request_stop(row["resource_ref"], operation)
    assert not any(e[0] in {"stop", "stopped", "delete", "patch"} for e in events[marker:])
    assert platform.resource(row["resource_ref"])["node_name"] == "worker-a"
    executor.request_stop(row["resource_ref"], operation)
    assert executor.confirm_stopped(row["resource_ref"])["stopped"]
    assert len([e for e in events[marker:] if e[0] == "bind"]) == 1


def test_never_scheduled_stop_does_not_invent_a_node_binding(runtime):
    """覆盖 AC: AC-33、AC-49、AC-52."""
    executor, platform, cluster, operation, events, _ = runtime
    cluster.delay_binding = True
    row, template, _ = _uncreated_pod(runtime)
    executor._create(row, template)
    marker = len(events)
    executor.request_stop(row["resource_ref"], operation)
    result = executor.confirm_stopped(row["resource_ref"])
    assert result["stopped"] and result["evidence_kind"] == "never_scheduled"
    saved = platform.resource(row["resource_ref"])
    assert saved["node_name"] == saved["stop_evidence"]["node_name"] == ""
    assert not any(e[0] == "bind" for e in events[marker:])

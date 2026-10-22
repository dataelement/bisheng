"""覆盖 AC: AC-04、AC-05、AC-07、AC-08、AC-09、AC-11、AC-18、AC-33、AC-35、AC-43、AC-48、AC-49、AC-50、AC-52."""

import base64
import copy
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from runtime_manager.config import Config
from runtime_manager.k8s_client import KubernetesAPIError
from runtime_manager.k8s_config import KubernetesConfig
from runtime_manager.k8s_templates import RESOURCE_LABEL, STOP_FINALIZER, production_name
from runtime_manager.platform_client import PlatformError

IMAGE = "example.invalid/python@sha256:" + "a" * 64
HELPER = "example.invalid/helper@sha256:" + "b" * 64
POD_UID = "22222222-2222-4222-8222-222222222222"


class Clock:
    def __init__(self):
        self.value = 1792555200.0

    def time(self):
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
        self.rows = {}
        self.operations = {}
        self.delegations = []

    def node_snapshot(self):
        return {
            "node": {"controller_epoch": self.epoch, "controller_holder": self.holder},
            "operations": list(self.operations.values()),
        }

    def claim_controller(self, holder_id, expected_epoch):
        assert expected_epoch == self.epoch
        self.epoch += 1
        self.holder = holder_id
        self.events.append(("claim", self.epoch))
        return self.renew_controller(holder_id, self.epoch)

    def renew_controller(self, holder_id, controller_epoch):
        assert (holder_id, controller_epoch) == (self.holder, self.epoch)
        return {"holder_id": holder_id, "controller_epoch": self.epoch, "lease_until": self.clock.iso(30)}

    def operation(self, operation_id):
        return copy.deepcopy(self.operations[operation_id])

    def register_resource(self, document):
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
            "observed_state": {},
            "controller_epoch": document["controller_epoch"],
        }
        previous = self.rows.get(row["resource_ref"])
        if previous:
            assert previous["template"] == row["template"]
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
        self.events.append((document["action"], resource_ref))
        row = self.rows[resource_ref]
        if document["action"] == "bind":
            if row["uid"]:
                assert row["uid"] == document["uid"]
            row["uid"] = document["uid"]
            row["node_name"] = document.get("node_name", "")
            row["observed_state"] = document.get("runtime_state", row["observed_state"])
        elif document["action"] == "stop":
            row["stop_requested_at"] = row["stop_requested_at"] or self.clock.iso()
            if row["stop_state"] != "confirmed":
                row["stop_state"] = "requested"
        elif document["action"] == "stopped":
            assert document["evidence"]["uid"] == row["uid"]
            row["stop_state"] = "confirmed"
            row["stop_evidence"] = copy.deepcopy(document["evidence"])
        elif document["action"] == "cleanup":
            assert document["uid"] == row["uid"]
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
        assert detail["controller"]["controller_epoch"] == self.epoch
        op.update(fact_sequence=sequence, result=copy.deepcopy(detail))
        return copy.deepcopy(op)

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
                body["status"] = {
                    "phase": "Succeeded",
                    "containerStatuses": [{"name": "app", "state": {"terminated": {"exitCode": 0}}}],
                }
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

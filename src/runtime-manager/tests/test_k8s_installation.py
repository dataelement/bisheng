"""覆盖 AC: AC-13、AC-14、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-35、AC-39、AC-40、AC-41、AC-42、AC-48、AC-49、AC-54、AC-55."""

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "deploy/kubernetes/app-runtime"
HELM = os.getenv("HELM_BIN", shutil.which("helm") or "/private/tmp/f059-tools/darwin-arm64/helm")


@pytest.fixture
def values():
    document = yaml.safe_load((CHART / "values.yaml").read_text())
    document["platform"].update(origin="https://platform.example", backendBase="http://backend.example:7860")
    document["services"]["egressClusterIP"] = "10.96.2.2"
    document["images"] = {key: "example/" + key + "@sha256:" + "a" * 64 for key in document["images"]}
    for key in document["network"]:
        if key.endswith("Cidrs"):
            document["network"][key] = ["10.96.0.0/12"]
    document["execution"]["dataPublicKeys"] = {"owner-v1": "b" * 64}
    document["storage"]["sqliteCompatible"] = True
    document["admission"]["caBundle"] = "Y2E="
    return document


def render(values, tmp_path, *, expect_success=True):
    path = tmp_path / "values.yaml"
    path.write_text(yaml.safe_dump(values))
    result = subprocess.run(
        [HELM, "template", "test-runtime", str(CHART), "-f", str(path)], capture_output=True, text=True
    )
    if not expect_success:
        assert result.returncode != 0
        return result
    assert result.returncode == 0, result.stderr
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def load_installer():
    path = ROOT / "scripts/verify_k8s_runtime.py"
    spec = importlib.util.spec_from_file_location("verify_runtime_installation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chart_processes_have_separate_identities_and_only_manager_has_projected_token(values, tmp_path):
    documents = render(values, tmp_path)
    workloads = {x["metadata"]["name"]: x for x in documents if x["kind"] == "Deployment"}
    assert set(workloads) == {"runtime-manager", "app-proxy", "egress-proxy", "runtime-admission"}
    for name, workload in workloads.items():
        spec = workload["spec"]["template"]["spec"]
        assert spec["automountServiceAccountToken"] is False
        token_volumes = [
            v
            for v in spec["volumes"]
            if "projected" in v and any("serviceAccountToken" in source for source in v["projected"]["sources"])
        ]
        assert bool(token_volumes) is (name == "runtime-manager")
        container = spec["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"]
        assert container["securityContext"]["allowPrivilegeEscalation"] is False
        refs = {e["valueFrom"]["secretKeyRef"]["key"] for e in container["env"] if "valueFrom" in e}
        assert not any("owner" in key or "minio" in key or "database" in key for key in refs)
        if name == "app-proxy":
            assert "manager-secret" not in refs and "control-secret" not in refs
        assert "hostPath" not in json.dumps(spec)
    manager = workloads["runtime-manager"]["spec"]["template"]["spec"]
    assert manager["serviceAccountName"] == values["services"]["managerAccount"]
    assert workloads["runtime-manager"]["spec"]["strategy"]["type"] == "Recreate"


def test_chart_retains_namespaces_volumes_and_public_keys_and_has_no_application_controllers(values, tmp_path):
    values["storage"]["volumes"] = [
        {
            "name": "preflight-data",
            "path": "/var/lib/bisheng-runtime/preflight",
            "role": "preflight",
            "node": "worker-a",
            "sizeMi": 1024,
        }
    ]
    documents = render(values, tmp_path)
    retained = [x for x in documents if x["kind"] in {"Namespace", "PersistentVolume"}]
    assert all(x["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep" for x in retained)
    pv = next(x for x in retained if x["kind"] == "PersistentVolume")
    assert pv["spec"]["persistentVolumeReclaimPolicy"] == "Retain"
    assert pv["spec"]["nodeAffinity"]["required"]
    assert not any(
        x["kind"] in {"Job", "StatefulSet", "DaemonSet", "ClusterRole", "ClusterRoleBinding"} for x in documents
    )
    manager_role = next(x for x in documents if x["kind"] == "Role")
    resources = {r for rule in manager_role["rules"] for r in rule["resources"]}
    assert not resources & {"pods/exec", "pods/status", "nodes", "persistentvolumes", "roles", "configmaps"}
    canary = next(x for x in documents if x["kind"] == "ConfigMap" and x["metadata"]["name"] == "runtime-canary-plans")
    assert json.loads(canary["data"]["plans.json"]) == {"schema_version": 1, "plans": {}, "profile_images": []}


@pytest.mark.parametrize(
    "change", ["unpinned", "protected", "same_namespace", "unknown", "public_keys_private", "nfs", "unsafe_path"]
)
def test_chart_refuses_unsafe_or_ambiguous_configuration(values, tmp_path, change):
    if change == "unpinned":
        values["images"]["helper"] = "example/helper:latest"
    elif change == "protected":
        values["execution"]["namespace"] = "kube-system"
    elif change == "same_namespace":
        values["execution"]["namespace"] = values["services"]["namespace"]
    elif change == "unknown":
        values["execution"]["privileged"] = True
    elif change == "public_keys_private":
        values["execution"]["dataPublicKeys"] = {"private_keys": {"secret": "x"}}
    elif change == "nfs":
        values["storage"]["filesystem"] = "nfs"
    else:
        values["storage"]["volumes"] = [
            {
                "name": "bad",
                "path": "/var/lib/bisheng-runtime/../other",
                "role": "production",
                "node": "worker-a",
                "sizeMi": 1024,
            }
        ]
    render(values, tmp_path, expect_success=False)


def test_descriptor_is_runtime_readable_and_report_updates_do_not_change_identity(values, tmp_path):
    from runtime_manager.k8s_capabilities import descriptor_digest

    documents = render(values, tmp_path)
    descriptor = next(
        x for x in documents if x["kind"] == "ConfigMap" and x["metadata"]["name"] == "runtime-deployment-descriptor"
    )
    document = json.loads(descriptor["data"]["descriptor.json"])
    assert document["namespace"] == values["execution"]["namespace"]
    assert document["installation_id"] == values["execution"]["installationId"]
    assert document["helper_image"] == values["images"]["helper"]
    assert document["storage"]["sqlite_compatible"] is True
    assert document["probe_report"] == {}
    before = descriptor_digest(document)
    document["probe_report"] = {"observed_at": 100}
    assert descriptor_digest(document) == before


def test_installer_requires_live_mode_and_bound_control_for_denials():
    tool = load_installer()
    with pytest.raises(ValueError, match="control"):
        tool.network_plan([{"name": "backend", "host": "10.0.0.1", "port": 443, "expected": "denied"}])
    with pytest.raises(ValueError, match="control"):
        tool.network_plan(
            [{"name": "backend", "host": "10.0.0.1", "port": 443, "expected": "denied", "control_confirmed": False}]
        )
    assert (
        tool.network_plan(
            [{"name": "backend", "host": "10.0.0.1", "port": 443, "expected": "denied", "control_confirmed": True}]
        )["targets"][0]["expected"]
        == "denied"
    )


def test_installer_rejects_unknown_proof_and_never_accepts_supplied_ready_flags():
    tool = load_installer()
    uid = str(uuid4())
    with pytest.raises(ValueError):
        tool.check_result("storage-sqlite", {"ready": True}, uid)
    result = tool.check_result(
        "storage-sqlite",
        {"locking": True, "fsync": True, "sqlite_integrity": True, "filesystem": "ext4", "capacity_bytes": 1024},
        uid,
    )
    assert result["ok"] and result["evidence"]["uid"] == uid
    with pytest.raises(ValueError):
        tool.check_result(
            "storage-sqlite",
            {"locking": True, "fsync": False, "sqlite_integrity": True, "filesystem": "ext4", "capacity_bytes": 1024},
            uid,
        )


def test_installer_does_not_clear_or_reuse_foreign_or_unknown_writers():
    tool = load_installer()
    row = {
        "metadata": {"name": "preflight-one", "uid": str(uuid4()), "resourceVersion": "12", "deletionTimestamp": "now"},
        "spec": {"nodeName": "worker-a"},
        "status": {"phase": "Unknown"},
    }
    assert not tool.stop_confirmed(row)
    row["status"] = {"phase": "Failed", "reason": "NodeLost"}
    assert not tool.stop_confirmed(row)
    row["status"] = {"phase": "Succeeded", "containerStatuses": [{"state": {"terminated": {"exitCode": 0}}}]}
    assert tool.stop_confirmed(row)
    row["metadata"]["name"] = "app-customer"
    assert not tool.stop_confirmed(row)


def test_report_is_failed_when_one_driver_fails_and_no_exception_secrets_escape():
    tool = load_installer()

    def driver():
        raise RuntimeError("secret-token-kubeconfig")

    result = tool.execute_checks({"storage-sqlite": driver}, {"schema_version": 1}, observed_at=123)
    assert result["checks"][0]["ok"] is False
    assert "secret" not in json.dumps(result)


def test_manager_requests_use_service_account_impersonation_without_token_arguments(monkeypatch):
    tool = load_installer()
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "yes\n", "")

    monkeypatch.setattr(tool.subprocess, "run", run)
    api = tool.Kubectl(
        context="test",
        control_namespace="runtime-system",
        execution_namespace="runtime-apps",
        manager_account="runtime-manager",
    )
    assert api.can("get", "pods", "runtime-apps")
    command = calls[0][0]
    assert "system:serviceaccount:runtime-system:runtime-manager" in command
    assert "system:serviceaccounts:runtime-system" in command
    assert not any("token" in part or "kubeconfig" in part for part in command)


def test_dangerous_admission_negative_is_server_dry_run(monkeypatch):
    tool = load_installer()
    from runtime_manager.k8s_templates import POLICY_ANNOTATION, RESOURCE_LABEL

    reference = str(uuid4())
    template = {
        "metadata": {
            "name": "preflight-base",
            "namespace": "runtime-apps",
            "labels": {RESOURCE_LABEL: reference},
            "annotations": {POLICY_ANNOTATION: "v1"},
        },
        "spec": {
            "containers": [{"image": "example/helper@sha256:" + "a" * 64, "securityContext": {"privileged": False}}]
        },
    }
    calls = []

    class Api:
        def raw(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            return subprocess.CompletedProcess([], 1, "", 'violates PodSecurity "restricted:v1.28"')

    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.api = Api()
    verifier.namespace = "runtime-apps"
    verifier.idle = {"metadata": {"uid": str(uuid4())}}
    verifier.created = [{"resource": "pods", "plan": {"template": template}}]
    verifier._plans = lambda *args, **kwargs: None
    verifier._wait = lambda callback: callback()
    assert verifier._admission_negative(psa=True)["ok"]
    assert calls[0][1].endswith("?dryRun=All")
    assert calls[0][2]["document"]["spec"]["containers"][0]["securityContext"]["privileged"] is True
    assert template["spec"]["containers"][0]["securityContext"]["privileged"] is False


def test_cleanup_never_releases_replaced_uid(monkeypatch):
    tool = load_installer()

    class Api:
        def get(self, *args, **kwargs):
            return {"metadata": {"uid": str(uuid4())}}

        def call(self, *args, **kwargs):
            pytest.fail("No mutation is allowed after an identity mismatch")

    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.api = Api()
    with pytest.raises(tool.ProbeError, match="identity_changed"):
        verifier._cleanup_one({"resource": "pods", "name": "preflight-one", "uid": str(uuid4())})


def test_offline_manifest_and_dependency_bytes_are_not_cri_or_resolution_proof(tmp_path):
    import hashlib

    tool = load_installer()
    names = [
        "runtime-manager",
        "app-proxy",
        "runtime-helper",
        "runtime-assembler",
        "app-python",
        "app-python-preparer",
        "app-node",
        "app-node-preparer",
        "app-static",
    ]
    images = {
        name: {"image": "example/" + name + "@sha256:" + "a" * 64, "platform": "linux/amd64", "native_smoke": True}
        for name in names
    }
    manifest = {"schema_version": 2, "platform": "linux/amd64", "state": "published-native-verified", "images": images}
    document = {"platform": "linux/amd64", "helper_image": images["runtime-helper"]["image"]}
    archive = tmp_path / "wheels.tar"
    archive.write_bytes(b"verified dependency archive")
    dependencies = [{"path": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}]
    result = tool.offline_inventory(manifest, document, dependencies)
    assert len(result["image_references"]) == 9 and result["dependencies"]
    assert (
        not result["cri_started"]
        and not result["dependency_resolution_executed"]
        and not result["platform_apis_verified"]
    )
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest_mismatch"):
        tool.offline_inventory(manifest, document, dependencies)
    images["runtime-helper"]["native_smoke"] = False
    with pytest.raises(ValueError, match="native_unverified"):
        tool.offline_inventory(manifest, document)


def test_empty_or_wrong_arch_manifest_cannot_satisfy_offline_delivery():
    tool = load_installer()
    document = {"platform": "linux/arm64", "helper_image": "example/helper@sha256:" + "a" * 64}
    with pytest.raises(ValueError):
        tool.offline_inventory(
            {"schema_version": 2, "platform": "linux/amd64", "state": "published-native-verified", "images": {}},
            document,
        )


def test_cleanup_failure_publishes_a_failed_report_instead_of_old_ready(tmp_path, monkeypatch, capsys):
    tool = load_installer()
    plan = tmp_path / "probe.json"
    plan.write_text("{}")
    published = []

    class Verifier:
        document = {"platform": "linux/amd64"}

        def __init__(self, *args, **kwargs):
            pass

        def live(self):
            raise RuntimeError("private-token")

        def publish(self, report):
            published.append(report)

    monkeypatch.setattr(tool, "Kubectl", lambda **kwargs: object())
    monkeypatch.setattr(tool, "InstallationVerifier", Verifier)
    code = tool.main(
        [
            "--context",
            "test",
            "--control-namespace",
            "runtime-system",
            "--execution-namespace",
            "runtime-apps",
            "--probe-plan",
            str(plan),
            "--live",
            "--write-report",
        ]
    )
    assert code == 1 and len(published) == 1
    assert all(row["ok"] is False for row in published[0]["checks"])
    assert "private-token" not in capsys.readouterr().out


def test_local_pool_rejects_two_claims_for_the_same_physical_directory(values, tmp_path):
    values["storage"]["volumes"] = [
        {
            "name": name,
            "path": "/var/lib/bisheng-runtime/shared",
            "role": "production",
            "node": "worker-a",
            "sizeMi": 1024,
        }
        for name in ("volume-a", "volume-b")
    ]
    render(values, tmp_path, expect_success=False)


def test_chart_freezes_native_profiles_and_sandbox_request_in_descriptor(values, tmp_path):
    profile = {
        "name": "python311",
        "runtime_image": "example/python@sha256:" + "b" * 64,
        "command": ["python", "--version"],
    }
    values["execution"].update(
        canaryProfiles=[profile], sandbox="recommended", runtimeClasses={"recommended": "gvisor", "hardened": ""}
    )
    documents = render(values, tmp_path)
    descriptor = next(
        x for x in documents if x["kind"] == "ConfigMap" and x["metadata"]["name"] == "runtime-deployment-descriptor"
    )
    document = json.loads(descriptor["data"]["descriptor.json"])
    assert document["canary_profiles"] == [profile]
    assert document["sandbox"] == {
        "requested": "recommended",
        "runtime_classes": {"recommended": "gvisor", "hardened": ""},
    }
    canary = next(x for x in documents if x["kind"] == "ConfigMap" and x["metadata"]["name"] == "runtime-canary-plans")
    assert json.loads(canary["data"]["plans.json"])["profile_images"] == [profile["runtime_image"]]
    profile["command"] = ["sh", "-c", "arbitrary-install-script"]
    render(values, tmp_path, expect_success=False)


@pytest.mark.parametrize("filesystem", ["nfs", "cifs", "overlay", "unknown"])
def test_storage_probe_requires_actual_qualified_filesystem(filesystem):
    tool = load_installer()
    with pytest.raises(ValueError, match="unconfirmed"):
        tool.check_result(
            "storage-sqlite",
            {
                "locking": True,
                "fsync": True,
                "sqlite_integrity": True,
                "filesystem": filesystem,
                "capacity_bytes": 1024,
            },
            str(uuid4()),
        )


def test_sandbox_probe_failure_is_actionable_without_making_up_success():
    tool = load_installer()

    def unavailable():
        raise tool.ProbeError("optional_runtime_class_not_configured")

    report = tool.execute_checks({"sandbox-recommended": unavailable}, {"platform": "linux/amd64"}, observed_at=123)
    assert report["checks"][0] == {
        "name": "sandbox-recommended",
        "ok": False,
        "reason": "optional_runtime_class_not_configured",
        "exception_type": "ProbeError",
        "evidence": {},
        "observed_at": 123,
    }


def test_cli_never_allows_report_write_without_live_execution(tmp_path):
    tool = load_installer()
    with pytest.raises(SystemExit) as stopped:
        tool.main(
            [
                "--context",
                "test",
                "--control-namespace",
                "runtime-system",
                "--execution-namespace",
                "runtime-apps",
                "--probe-plan",
                str(tmp_path / "missing.json"),
                "--write-report",
            ]
        )
    assert stopped.value.code == 2


def test_installer_pod_and_pvc_templates_pass_the_actual_canary_reader(tmp_path):
    from runtime_manager.k8s_admission import AdmissionPolicy, CanaryPlanReader, template_projection
    from runtime_manager.k8s_templates import RESOURCE_LABEL

    tool = load_installer()
    helper = "example/helper@sha256:" + "a" * 64
    native = "example/python@sha256:" + "b" * 64
    templates = []
    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.namespace = "runtime-apps"
    verifier.timeout = 180
    verifier.options = {"storage_size_mb": 1024}
    verifier.document = {
        "helper_image": helper,
        "platform": "linux/amd64",
        "status_policy_revision": "v1",
        "storage": {"class": "", "sqlite_compatible": True, "filesystem": "ext4", "static_pool": True},
    }

    def capture(template):
        templates.append(copy.deepcopy(template))
        return template | {"metadata": template["metadata"] | {"uid": str(uuid4())}}

    verifier._create = capture
    verifier._result = lambda pod: {
        "locking": True,
        "fsync": True,
        "sqlite_integrity": True,
        "filesystem": "ext4",
        "capacity_bytes": 1024**3,
    }
    verifier._pod("idle")
    verifier._pod("idle", unschedulable=True)
    verifier._pod("network", targets=[{"name": "egress", "host": "10.96.2.2", "port": 3128, "expected": "allowed"}])
    verifier._pod("idle", image=native, command=("python", "--version"))
    verifier._storage()
    plans = {}
    for template in templates:
        meta = template["metadata"]
        ref = meta["labels"][RESOURCE_LABEL]
        plans[ref] = {
            "resource_ref": ref,
            "namespace": verifier.namespace,
            "name": meta["name"],
            "kind": template["kind"],
            "template": template_projection(template),
            "uid": None,
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "stop_state": "held",
            "cleanup_only": False,
            "expires_at": 2000,
        }
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({"schema_version": 1, "plans": plans, "profile_images": [native]}))
    reader = CanaryPlanReader(
        lambda ref: pytest.fail("Preflight must not use backend business authority"),
        path,
        namespace=verifier.namespace,
        helper_image=helper,
        clock=lambda: 1000,
    )
    username = "system:serviceaccount:runtime-system:runtime-manager"
    policy = AdmissionPolicy(
        namespace=verifier.namespace, manager_username=username, status_policy_revision="v1", plan_reader=reader
    )
    kinds = {"Pod": "pods", "PersistentVolumeClaim": "persistentvolumeclaims"}
    for template in templates:
        ref = template["metadata"]["labels"][RESOURCE_LABEL]
        assert reader(ref)["uid"] is None
        result = policy.review(
            {
                "apiVersion": "admission.k8s.io/v1",
                "kind": "AdmissionReview",
                "request": {
                    "uid": str(uuid4()),
                    "operation": "CREATE",
                    "namespace": verifier.namespace,
                    "name": template["metadata"]["name"],
                    "resource": {"group": "", "version": "v1", "resource": kinds[template["kind"]]},
                    "userInfo": {"username": username},
                    "object": template,
                },
            }
        )
        assert result["response"]["allowed"], result


def test_create_has_only_create_authority_until_observed_uid_is_persisted(monkeypatch):
    tool = load_installer()
    reference, observed_uid = str(uuid4()), str(uuid4())
    template = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": "preflight-volume",
            "namespace": "runtime-apps",
            "labels": {"runtime.bisheng.io/resource": reference},
        },
        "spec": {"accessModes": ["ReadWriteOnce"]},
    }
    plans = []

    class Api:
        def raw(self, method, path, **kwargs):
            assert method == "POST" and kwargs["manager"] is True
            assert plans[-1]["uid"] is None and plans[-1]["allow_create"] is True
            assert plans[-1]["allow_update"] is False and plans[-1]["allow_delete"] is False
            observed = copy.deepcopy(template)
            observed["metadata"]["uid"] = observed_uid
            return subprocess.CompletedProcess([], 0, json.dumps(observed), "")

    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.api, verifier.namespace, verifier.document = Api(), "runtime-apps", {}
    verifier.created = []
    verifier._plans = lambda ref, plan: plans.append(copy.deepcopy(plan))
    verifier._wait = lambda callback: callback()
    observed = verifier._create(template)
    assert observed["metadata"]["uid"] == observed_uid
    assert plans[-1]["uid"] == observed_uid and plans[-1]["allow_create"] is False
    assert plans[-1]["allow_update"] is True and plans[-1]["allow_delete"] is True
    assert verifier.created[0]["uid"] == observed_uid


def test_unscheduled_canary_needs_verified_atomic_binding_fence():
    tool = load_installer()
    pod = {
        "metadata": {
            "name": "preflight-unassigned",
            "namespace": "runtime-apps",
            "uid": str(uuid4()),
            "deletionTimestamp": "2026-10-22T00:00:00Z",
        },
        "spec": {},
        "status": {},
    }
    assert not tool.stop_confirmed(pod)
    evidence = {key: pod["metadata"][key] for key in ("namespace", "name", "uid", "deletionTimestamp")}
    assert tool.stop_confirmed(pod, binding_evidence=evidence)
    for field in evidence:
        other = {**evidence, field: "different-resource"}
        assert not tool.stop_confirmed(pod, binding_evidence=other)


def diagnostic_cli(tool, tmp_path, monkeypatch, error, *, publish_error=None):
    path = tmp_path / "probe.json"
    path.write_text("{}")
    published = []

    class Verifier:
        document = {"platform": "linux/amd64"}

        def __init__(self, *_args, **_kwargs):
            pass

        def live(self):
            raise error

        def publish(self, report):
            if publish_error:
                raise publish_error
            published.append(report)

    monkeypatch.setattr(tool, "InstallationVerifier", Verifier)
    monkeypatch.setattr(tool, "Kubectl", lambda **_kwargs: None)
    code = tool.main(
        [
            "--context",
            "test",
            "--control-namespace",
            "runtime-system",
            "--execution-namespace",
            "runtime-apps",
            "--probe-plan",
            str(path),
            "--live",
            "--write-report",
        ]
    )
    return code, published


@pytest.mark.parametrize(
    "kind,expected_reason,expected_type",
    [
        ("safe", "preflight_create_refused", "ProbeError"),
        ("unknown", "probe_failed", "ProbeError"),
        ("generic", "probe_failed", "RuntimeError"),
    ],
)
def test_live_failure_reports_safe_reason_and_type_without_exception_content(
    tmp_path, monkeypatch, capsys, kind, expected_reason, expected_type
):
    tool = load_installer()
    private = "PRIVATE_HMAC_SENTINEL"
    error = (
        tool.ProbeError("preflight_create_refused")
        if kind == "safe"
        else (
            tool.ProbeError(private) if kind == "unknown" else RuntimeError("kubectl stderr Authorization=" + private)
        )
    )
    code, published = diagnostic_cli(tool, tmp_path, monkeypatch, error)
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert code == 1 and published == [report]
    assert report["failures"] == [{"phase": "probe", "reason": expected_reason, "exception_type": expected_type}]
    assert all(
        not row["ok"] and row["reason"] == expected_reason and row["exception_type"] == expected_type
        for row in report["checks"]
    )
    assert json.loads(captured.err)["failures"] == report["failures"]
    assert private not in captured.out + captured.err
    assert "Authorization" not in captured.out + captured.err


def test_per_check_diagnostics_reject_unknown_constant_shaped_probe_text():
    tool = load_installer()

    def refuse():
        raise tool.ProbeError("PRIVATE_ENV_SENTINEL")

    report = tool.execute_checks({"storage-sqlite": refuse}, {"platform": "linux/amd64"}, observed_at=123)
    assert report["checks"][0]["reason"] == "probe_failed"
    assert report["checks"][0]["exception_type"] == "ProbeError"
    assert "PRIVATE_ENV_SENTINEL" not in json.dumps(report)


def live_with_failures(tool, *, probe_error=None, cleanup_error=None, report=None):
    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.options, verifier.document = {}, {"platform": "linux/amd64"}
    for name in (
        "_namespace_budget",
        "_admission_negative",
        "_status",
        "_binding_fence",
        "_rbac",
        "_no_exec",
        "_storage",
        "_image",
        "_ingress",
        "_platform",
        "_network",
    ):
        setattr(verifier, name, lambda *_args, **_kwargs: None)

    def pod(*_args, **_kwargs):
        if probe_error:
            raise probe_error
        return {"metadata": {"uid": str(uuid4())}}

    def cleanup():
        if cleanup_error:
            raise cleanup_error

    verifier._pod, verifier._observe, verifier.cleanup = pod, lambda value, **_kwargs: value, cleanup
    if report is not None:
        tool.execute_checks = lambda *_args, **_kwargs: report
    return verifier


def test_cleanup_failure_preserves_initial_safe_classification(tmp_path, monkeypatch, capsys):
    tool = load_installer()
    verifier = live_with_failures(
        tool,
        probe_error=tool.ProbeError("preflight_pod_failed"),
        cleanup_error=tool.ProbeError("preflight_cleanup_identity_changed"),
    )
    with pytest.raises(tool.ProbeRunFailure) as stopped:
        verifier.live()
    code, _ = diagnostic_cli(tool, tmp_path, monkeypatch, stopped.value)
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert code == 1
    assert report["failures"] == [
        {"phase": "probe", "reason": "preflight_pod_failed", "exception_type": "ProbeError"},
        {"phase": "cleanup", "reason": "preflight_cleanup_identity_changed", "exception_type": "ProbeError"},
    ]


def test_cleanup_failure_retains_earlier_failed_check_classification(tmp_path, monkeypatch, capsys):
    tool = load_installer()
    previous = {
        "checks": [
            {
                "name": "storage-sqlite",
                "ok": False,
                "reason": "storage_capacity_not_bounded",
                "exception_type": "ProbeError",
                "evidence": {},
            }
        ]
    }
    verifier = live_with_failures(tool, cleanup_error=RuntimeError("SECRET_STDERR"), report=previous)
    with pytest.raises(tool.ProbeRunFailure) as stopped:
        verifier.live()
    code, _ = diagnostic_cli(tool, tmp_path, monkeypatch, stopped.value)
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert code == 1
    assert {
        "phase": "check",
        "name": "storage-sqlite",
        "reason": "storage_capacity_not_bounded",
        "exception_type": "ProbeError",
    } in report["failures"]
    assert {"phase": "cleanup", "reason": "probe_failed", "exception_type": "RuntimeError"} in report["failures"]
    assert "SECRET_STDERR" not in captured.out + captured.err
    assert all(not row["ok"] for row in report["checks"])


def test_failure_report_publication_error_keeps_initial_failure(tmp_path, monkeypatch, capsys):
    tool = load_installer()
    code, _ = diagnostic_cli(
        tool,
        tmp_path,
        monkeypatch,
        tool.ProbeError("probe_deadline_exceeded"),
        publish_error=RuntimeError("SECRET_PUBLISH_RESPONSE"),
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert code == 1
    assert report["failures"] == [
        {"phase": "probe", "reason": "probe_deadline_exceeded", "exception_type": "ProbeError"},
        {"phase": "publish", "reason": "probe_failed", "exception_type": "RuntimeError"},
    ]
    assert "SECRET_PUBLISH_RESPONSE" not in captured.out + captured.err


class PlanRefreshApi:
    control, execution = "runtime-system", "runtime-apps"

    def __init__(self, tool, *, failure=None, count=1):
        self.tool, self.failure, self.calls = tool, failure, []
        self.cm = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "runtime-canary-plans",
                "namespace": self.control,
                "uid": str(uuid4()),
                "resourceVersion": "10",
            },
            "data": {"plans.json": json.dumps({"schema_version": 1, "plans": {}})},
        }
        self.pods = [
            {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "name": "runtime-admission-" + str(index),
                    "namespace": self.control,
                    "uid": str(uuid4()),
                    "resourceVersion": "30",
                    "labels": {"app": "runtime-admission"},
                },
                "spec": {
                    "automountServiceAccountToken": False,
                    "volumes": [{"name": "canary-plans", "configMap": {"name": "runtime-canary-plans"}}],
                    "containers": [
                        {
                            "name": "runtime-admission",
                            "volumeMounts": [{"name": "canary-plans", "mountPath": "/run/preflight", "readOnly": True}],
                        }
                    ],
                },
                "status": {"phase": "Running"},
            }
            for index in range(count)
        ]

    def get(self, kind, name, *, namespace=None):
        self.calls.append(("get", kind, name, namespace))
        assert namespace == self.control
        if kind == "configmap":
            assert name == "runtime-canary-plans"
            return copy.deepcopy(self.cm)
        assert kind == "pod"
        pod = copy.deepcopy(next(row for row in self.pods if row["metadata"]["name"] == name))
        if self.failure == "replaced-before":
            pod["metadata"]["uid"] = str(uuid4())
        elif self.failure == "foreign-namespace":
            pod["metadata"]["namespace"] = self.execution
        elif self.failure == "foreign-label":
            pod["metadata"]["labels"] = {"app": "application"}
        elif self.failure == "terminating":
            pod["metadata"]["deletionTimestamp"] = "2026-10-22T00:00:00Z"
        elif self.failure == "subpath":
            pod["spec"]["containers"][0]["volumeMounts"][0]["subPath"] = "plans.json"
        elif self.failure == "other-volume":
            pod["spec"]["volumes"][0]["configMap"]["name"] = "some-other-config"
        return pod

    def call(self, arguments, *, document=None, manager=False):
        self.calls.append(("call", copy.deepcopy(arguments), copy.deepcopy(document), manager))
        assert manager is False
        if arguments[0] == "replace":
            if self.failure == "replace-failed":
                raise self.tool.ProbeError("kubectl_request_failed")
            assert arguments == ["replace", "-f", "-", "-o", "json"]
            self.cm = copy.deepcopy(document)
            self.cm["metadata"]["resourceVersion"] = str(int(self.cm["metadata"]["resourceVersion"]) + 1)
            return subprocess.CompletedProcess([], 0, json.dumps(self.cm), "")
        if arguments[0] == "get":
            assert arguments == ["get", "pods", "-n", self.control, "-l", "app=runtime-admission", "-o", "json"]
            return subprocess.CompletedProcess([], 0, json.dumps({"items": self.pods}), "")
        assert arguments[:2] == ["patch", "pod"]
        assert arguments[3:6] == ["-n", self.control, "--type=json"]
        if self.failure == "conflict":
            raise self.tool.ProbeError("kubectl_request_failed")
        patch = json.loads(arguments[arguments.index("-p") + 1])
        pod = next(row for row in self.pods if row["metadata"]["name"] == arguments[2])
        assert patch[0] == {"op": "test", "path": "/metadata/uid", "value": pod["metadata"]["uid"]}
        assert patch[1] == {
            "op": "test",
            "path": "/metadata/resourceVersion",
            "value": pod["metadata"]["resourceVersion"],
        }
        assert not any(row["path"].startswith("/spec") for row in patch)
        for row in patch[2:]:
            if row["path"] == "/metadata/annotations":
                pod["metadata"]["annotations"] = row["value"]
            else:
                assert row["path"] == "/metadata/annotations/runtime.bisheng.io~1canary-plans-revision"
                pod["metadata"].setdefault("annotations", {})["runtime.bisheng.io/canary-plans-revision"] = row["value"]
        pod["metadata"]["resourceVersion"] = str(int(pod["metadata"]["resourceVersion"]) + 1)
        result = copy.deepcopy(pod)
        if self.failure == "replaced-after":
            result["metadata"]["uid"] = str(uuid4())
        return subprocess.CompletedProcess([], 0, json.dumps(result), "")


def planning_verifier(tool, **kwargs):
    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.api = PlanRefreshApi(tool, **kwargs)
    verifier.namespace = verifier.api.execution
    return verifier


def test_plans_refresh_only_admission_pod_annotations_after_each_cm_revision():
    tool = load_installer()
    verifier = planning_verifier(tool, count=2)
    verifier.api.pods[0]["metadata"]["annotations"] = {"existing.annotation": "retained"}
    original_specs = [copy.deepcopy(row["spec"]) for row in verifier.api.pods]
    revisions = []
    reference = str(uuid4())
    plan = {"expires_at": 123, "uid": None, "allow_create": True}
    verifier._plans(reference, plan)
    revisions.append(verifier.api.pods[0]["metadata"]["annotations"]["runtime.bisheng.io/canary-plans-revision"])
    verifier._plans(reference, {**plan, "uid": str(uuid4()), "allow_create": False})
    revisions.append(verifier.api.pods[0]["metadata"]["annotations"]["runtime.bisheng.io/canary-plans-revision"])
    verifier._plans(reference, remove=True)
    revisions.append(verifier.api.pods[0]["metadata"]["annotations"]["runtime.bisheng.io/canary-plans-revision"])
    assert len(set(revisions)) == 3
    assert [row["spec"] for row in verifier.api.pods] == original_specs
    assert verifier.api.pods[0]["metadata"]["annotations"]["existing.annotation"] == "retained"
    assert json.loads(verifier.api.cm["data"]["plans.json"])["plans"] == {}
    assert len([row for row in verifier.api.calls if row[:1] == ("call",) and row[1][0] == "patch"]) == 6
    assert all("deployment" not in str(row).lower() for row in verifier.api.calls)


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("replaced-before", "admission_refresh_identity_changed"),
        ("replaced-after", "admission_refresh_identity_changed"),
        ("foreign-namespace", "admission_refresh_scope_invalid"),
        ("foreign-label", "admission_refresh_scope_invalid"),
        ("terminating", "admission_refresh_scope_invalid"),
        ("subpath", "admission_refresh_scope_invalid"),
        ("other-volume", "admission_refresh_scope_invalid"),
        ("conflict", "admission_refresh_refused"),
    ],
)
def test_plan_refresh_conflicts_or_scope_changes_fail_closed(failure, reason):
    tool = load_installer()
    verifier = planning_verifier(tool, failure=failure)
    with pytest.raises(tool.ProbeError, match=reason) as stopped:
        verifier._plans(str(uuid4()), {"expires_at": 123})
    assert tool.safe_failure(stopped.value)["reason"] == reason
    patches = [row for row in verifier.api.calls if row[:1] == ("call",) and row[1][0] == "patch"]
    assert len(patches) == (1 if failure in {"conflict", "replaced-after"} else 0)


def test_plan_refresh_never_runs_when_cm_update_fails_or_no_admission_pod_exists():
    tool = load_installer()
    failed = planning_verifier(tool, failure="replace-failed")
    with pytest.raises(tool.ProbeError, match="kubectl_request_failed"):
        failed._plans(str(uuid4()), {})
    assert not any(row[:1] == ("call",) and row[1][0] in {"get", "patch"} for row in failed.api.calls)
    missing = planning_verifier(tool, count=0)
    with pytest.raises(tool.ProbeError, match="admission_refresh_targets_unavailable"):
        missing._plans(str(uuid4()), {})


def test_plan_refresh_refuses_invalid_cm_scope_before_any_write():
    tool = load_installer()
    verifier = planning_verifier(tool)
    verifier.api.cm["metadata"]["namespace"] = "other-namespace"
    with pytest.raises(tool.ProbeError, match="admission_refresh_revision_unconfirmed"):
        verifier._plans(str(uuid4()), {})
    assert not any(row[:1] == ("call",) for row in verifier.api.calls)


class ExpiredCanaryApi:
    def __init__(self, tool, *, outcome="deleted", active=False, status=None, bound=False):
        self.control, self.execution = "runtime-system", "runtime-apps"
        self.tool, self.outcome, self.calls, self.released = tool, outcome, [], False
        reference, uid = str(uuid4()), str(uuid4())
        self.pod = {
            "metadata": {
                "name": "preflight-expired",
                "namespace": self.execution,
                "uid": uid,
                "resourceVersion": "19",
                "labels": {tool.RESOURCE_LABEL: reference},
                "deletionTimestamp": "2026-10-22T00:00:00Z",
                "finalizers": [tool.STOP_FINALIZER, "example/retain"],
            },
            "spec": {"nodeName": "worker-a"} if bound else {},
            "status": status or {"phase": "Pending"},
        }
        self.plan = {
            "resource_ref": reference,
            "namespace": self.execution,
            "name": self.pod["metadata"]["name"],
            "kind": "Pod",
            "uid": uid,
            "stop_state": "held",
            "expires_at": 2000 if active else 999,
        }

    def get(self, resource, name, **kwargs):
        self.calls.append(("get", resource, name))
        if resource == "configmap":
            return {
                "data": {
                    "plans.json": json.dumps({"schema_version": 1, "plans": {self.plan["resource_ref"]: self.plan}})
                }
            }
        return copy.deepcopy(self.pod)

    def list(self, resource, **kwargs):
        return []

    def raw(self, method, path, **kwargs):
        self.calls.append((method, path, copy.deepcopy(kwargs.get("document"))))
        if path.endswith("/binding"):
            assert kwargs["manager"] is False
            assert kwargs["document"]["metadata"]["uid"] == self.plan["uid"]
            if self.outcome == "api-unknown":
                raise self.tool.ProbeError("kubectl_request_failed")
            if self.outcome == "uid-replaced":
                self.pod["metadata"]["uid"] = str(uuid4())
            elif self.outcome == "bound-after":
                self.pod["spec"]["nodeName"] = "worker-a"
            elif self.outcome == "running-after":
                self.pod["status"]["containerStatuses"] = [{"state": {"running": {}}}]
            elif self.outcome == "not-deleting-after":
                self.pod["metadata"].pop("deletionTimestamp")
            if self.outcome == "accepted":
                self.pod["spec"]["nodeName"] = "worker-a"
                return subprocess.CompletedProcess([], 0, "{}", "")
            reason = "being deleted" if self.outcome != "wrong-rejection" else "Forbidden"
            return subprocess.CompletedProcess([], 1, "", reason)
        assert method == "GET" and self.released
        return subprocess.CompletedProcess([], 1, "", "NotFound")

    def call(self, args, **kwargs):
        assert args[:2] == ["patch", "pod"]
        self.calls.append(("patch", args[2], kwargs))
        patch = json.loads(args[args.index("-p") + 1])
        assert patch["metadata"]["finalizers"] == ["example/retain"]
        self.released = True
        return subprocess.CompletedProcess([], 0, "", "")


def expired_canary_verifier(tool, **kwargs):
    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.api = ExpiredCanaryApi(tool, **kwargs)
    verifier.namespace, verifier.options = verifier.api.execution, {"node_name": "worker-a", "installation_id": "test"}
    verifier.created, verifier.control_created = [], []
    verifier.plan_writes = []
    verifier._plans = lambda ref, plan=None, **kw: verifier.plan_writes.append((ref, copy.deepcopy(plan), kw))

    def wait(callback):
        result = callback()
        if not result:
            raise tool.ProbeError("probe_deadline_exceeded")
        return result

    verifier._wait = wait
    return verifier


def test_expired_unscheduled_recovery_reproves_binding_for_its_uid_before_release(monkeypatch):
    tool = load_installer()
    monkeypatch.setattr(tool.time, "time", lambda: 1000)
    verifier = expired_canary_verifier(tool)
    verifier.recover_expired()
    binding = next(i for i, row in enumerate(verifier.api.calls) if row[0] == "POST")
    release = next(i for i, row in enumerate(verifier.api.calls) if row[0] == "patch")
    assert any(row[0] == "get" and row[1] == "pod" for row in verifier.api.calls[binding + 1 : release])
    assert verifier.api.released and not verifier.created
    assert any(plan and plan.get("stop_state") == "confirmed" for _, plan, _ in verifier.plan_writes)


@pytest.mark.parametrize(
    "outcome",
    [
        "accepted",
        "wrong-rejection",
        "api-unknown",
        "uid-replaced",
        "bound-after",
        "running-after",
        "not-deleting-after",
    ],
)
def test_expired_unscheduled_recovery_retains_uncertain_or_changed_writers(monkeypatch, outcome):
    tool = load_installer()
    monkeypatch.setattr(tool.time, "time", lambda: 1000)
    verifier = expired_canary_verifier(tool, outcome=outcome)
    with pytest.raises(tool.ProbeError):
        verifier.recover_expired()
    assert not verifier.api.released
    assert not any(plan and plan.get("stop_state") == "confirmed" for _, plan, _ in verifier.plan_writes)


@pytest.mark.parametrize("state", ["bound-pending", "unknown", "node-lost", "running"])
def test_expired_recovery_never_probes_or_releases_possible_existing_writers(monkeypatch, state):
    tool = load_installer()
    monkeypatch.setattr(tool.time, "time", lambda: 1000)
    status = {"phase": "Pending"}
    if state == "unknown":
        status["phase"] = "Unknown"
    elif state == "node-lost":
        status.update(phase="Failed", reason="NodeLost")
    elif state == "running":
        status["containerStatuses"] = [{"state": {"running": {}}}]
    verifier = expired_canary_verifier(tool, status=status, bound=state == "bound-pending")
    with pytest.raises(tool.ProbeError):
        verifier.recover_expired()
    assert not verifier.api.released
    assert not any(row[0] == "POST" for row in verifier.api.calls)


def test_expired_recovery_skips_live_plan_without_mutation(monkeypatch):
    tool = load_installer()
    monkeypatch.setattr(tool.time, "time", lambda: 1000)
    verifier = expired_canary_verifier(tool, active=True)
    verifier.recover_expired()
    assert not verifier.api.released and not verifier.plan_writes
    assert not any(row[0] in {"POST", "patch"} for row in verifier.api.calls)


def test_chart_cni_identity_is_admission_source_and_invalidates_only_old_report(values, tmp_path):
    from runtime_manager.k8s_capabilities import REQUIRED_CHECKS, assess_capabilities, descriptor_digest

    def descriptor_and_admission():
        documents = render(values, tmp_path)
        cm = next(
            row
            for row in documents
            if row["kind"] == "ConfigMap" and row["metadata"]["name"] == "runtime-deployment-descriptor"
        )
        deployment = next(
            row for row in documents if row["kind"] == "Deployment" and row["metadata"]["name"] == "runtime-admission"
        )
        env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        cni = next(row["value"] for row in env if row["name"] == "RTM_ADMISSION_CNI_USERNAME")
        return json.loads(cm["data"]["descriptor.json"]), cni

    values["execution"]["cniUsername"] = "system:serviceaccount:kube-system:calico-cni-plugin"
    original, cni = descriptor_and_admission()
    assert original["cni_username"] == cni == values["execution"]["cniUsername"]
    identity = descriptor_digest(original)
    report = {
        "source": "cluster-probe",
        "observed_at": 1000,
        "descriptor_digest": identity,
        "checks": [{"name": name, "ok": True, "evidence": {"uid": str(uuid4())}} for name in REQUIRED_CHECKS],
    }
    values["execution"]["probeReport"] = report
    verified, _ = descriptor_and_admission()
    assert descriptor_digest(verified) == identity
    assert assess_capabilities(verified, now=1001)["ready"]
    values["execution"]["cniUsername"] = "system:serviceaccount:kube-system:another-cni"
    changed, cni = descriptor_and_admission()
    assert changed["cni_username"] == cni == values["execution"]["cniUsername"]
    assert {key: value for key, value in changed.items() if key != "cni_username"} == {
        key: value for key, value in verified.items() if key != "cni_username"
    }
    assert descriptor_digest(changed) != identity
    assert not assess_capabilities(changed, now=1001)["ready"]


@contextmanager
def chart_lookup_api(objects):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            requests.append(path)
            if path == "/version":
                response = {"major": "1", "minor": "28", "gitVersion": "v1.28.15"}
            elif path == "/api":
                response = {
                    "kind": "APIVersions",
                    "apiVersion": "v1",
                    "versions": ["v1"],
                    "serverAddressByClientCIDRs": [],
                }
            elif path == "/apis":
                response = {"kind": "APIGroupList", "apiVersion": "v1", "groups": []}
            elif path == "/api/v1":
                response = {
                    "kind": "APIResourceList",
                    "apiVersion": "v1",
                    "groupVersion": "v1",
                    "resources": [
                        {
                            "name": "configmaps",
                            "singularName": "",
                            "namespaced": True,
                            "kind": "ConfigMap",
                            "verbs": ["get"],
                        }
                    ],
                }
            else:
                response = objects.get(path)
            payload = json.dumps(
                response
                or {"kind": "Status", "apiVersion": "v1", "status": "Failure", "reason": "NotFound", "code": 404}
            ).encode()
            self.send_response(200 if response is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), requests
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def upgrade_lookup_objects(values, *, legacy=False):
    namespace = values["services"]["namespace"]
    execution = values["execution"]
    reference, uid = str(uuid4()), str(uuid4())
    plan = {
        "resource_ref": reference,
        "namespace": execution["namespace"],
        "name": "preflight-retained",
        "kind": "Pod",
        "uid": uid,
        "expires_at": 1234,
        "allow_create": False,
        "allow_update": True,
        "allow_delete": True,
        "cleanup_only": False,
        "stop_state": "held",
        "template": {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "preflight-retained",
                "namespace": execution["namespace"],
                "labels": {"runtime.bisheng.io/resource": reference},
            },
            "spec": {},
        },
    }
    plans = {"schema_version": 1, "plans": {reference: plan}, "profile_images": ["example/native@sha256:" + "b" * 64]}

    def cm(name, data):
        return {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "uid": str(uuid4()),
                "resourceVersion": "21",
                "labels": {"app.kubernetes.io/managed-by": "Helm"},
                "annotations": {
                    "meta.helm.sh/release-name": "test-runtime",
                    "meta.helm.sh/release-namespace": namespace,
                },
            },
            "data": data,
        }

    descriptor = {
        "installation_id": execution["installationId"],
        "cluster_id": execution["clusterId"],
        "namespace": execution["namespace"],
    }
    plan_cm = cm("runtime-canary-plans", {"plans.json": json.dumps(plans, indent=2)})
    if not legacy:
        plan_cm["metadata"]["labels"]["runtime.bisheng.io/installation"] = execution["installationId"]
    descriptor_cm = cm("runtime-deployment-descriptor", {"descriptor.json": json.dumps(descriptor)})
    prefix = "/api/v1/namespaces/" + namespace + "/configmaps/"
    return {prefix + row["metadata"]["name"]: row for row in (plan_cm, descriptor_cm)}


def render_upgrade(values, tmp_path, objects, *, expect_success=True):
    values_path, config_path = tmp_path / "upgrade-values.yaml", tmp_path / "lookup-kubeconfig.json"
    values_path.write_text(yaml.safe_dump(values))
    with chart_lookup_api(objects) as (url, requests):
        config_path.write_text(
            json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Config",
                    "clusters": [{"name": "lookup", "cluster": {"server": url}}],
                    "users": [{"name": "lookup", "user": {}}],
                    "contexts": [{"name": "lookup", "context": {"cluster": "lookup", "user": "lookup"}}],
                    "current-context": "lookup",
                }
            )
        )
        result = subprocess.run(
            [
                HELM,
                "template",
                "test-runtime",
                str(CHART),
                "-n",
                values["services"]["namespace"],
                "-f",
                str(values_path),
                "--is-upgrade",
                "--dry-run=server",
                "--kubeconfig",
                str(config_path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    if not expect_success:
        assert result.returncode != 0
        return result
    assert result.returncode == 0, result.stderr
    assert any(path.endswith("/configmaps/runtime-canary-plans") for path in requests)
    return [row for row in yaml.safe_load_all(result.stdout) if row]


@pytest.mark.parametrize("legacy", [False, True])
def test_chart_upgrade_preserves_live_canary_plans_and_profiles_with_identity_fence(values, tmp_path, legacy):
    objects = upgrade_lookup_objects(values, legacy=legacy)
    original = next(row for row in objects.values() if row["metadata"]["name"] == "runtime-canary-plans")
    documents = render_upgrade(values, tmp_path, objects)
    retained = next(
        row for row in documents if row["kind"] == "ConfigMap" and row["metadata"]["name"] == "runtime-canary-plans"
    )
    assert retained["data"] == original["data"]
    assert retained["metadata"]["uid"] == original["metadata"]["uid"]
    assert retained["metadata"]["resourceVersion"] == original["metadata"]["resourceVersion"]
    assert retained["metadata"]["labels"]["runtime.bisheng.io/installation"] == values["execution"]["installationId"]


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "release",
        "namespace",
        "managed-by",
        "uid",
        "rv",
        "installation",
        "descriptor-missing",
        "descriptor-release",
        "descriptor-scope",
        "malformed-json",
        "unknown-data",
        "plans-not-map",
        "profile-unpinned",
        "plan-scope",
        "plan-uid",
        "schema-version",
        "plan-flags",
        "plan-template",
    ],
)
def test_chart_upgrade_refuses_missing_foreign_or_invalid_canary_evidence(values, tmp_path, change):
    objects = upgrade_lookup_objects(values, legacy=change.startswith("descriptor-"))
    prefix = "/api/v1/namespaces/" + values["services"]["namespace"] + "/configmaps/"
    cm = objects[prefix + "runtime-canary-plans"]
    if change == "missing":
        objects.pop(prefix + "runtime-canary-plans")
    elif change == "release":
        cm["metadata"]["annotations"]["meta.helm.sh/release-name"] = "foreign"
    elif change == "namespace":
        cm["metadata"]["namespace"] = "foreign"
    elif change == "managed-by":
        cm["metadata"]["labels"]["app.kubernetes.io/managed-by"] = "foreign"
    elif change == "uid":
        cm["metadata"]["uid"] = "not-a-uid"
    elif change == "rv":
        cm["metadata"].pop("resourceVersion")
    elif change == "installation":
        cm["metadata"]["labels"]["runtime.bisheng.io/installation"] = "foreign"
    elif change == "descriptor-missing":
        objects.pop(prefix + "runtime-deployment-descriptor")
    elif change == "descriptor-release":
        objects[prefix + "runtime-deployment-descriptor"]["metadata"]["annotations"]["meta.helm.sh/release-name"] = (
            "foreign"
        )
    elif change == "descriptor-scope":
        descriptor_cm = objects[prefix + "runtime-deployment-descriptor"]
        descriptor_cm["data"]["descriptor.json"] = json.dumps(
            {
                "installation_id": "foreign",
                "cluster_id": values["execution"]["clusterId"],
                "namespace": values["execution"]["namespace"],
            }
        )
    elif change == "malformed-json":
        cm["data"]["plans.json"] = "{broken"
    elif change == "unknown-data":
        cm["data"]["extra"] = "unmanaged"
    else:
        data = json.loads(cm["data"]["plans.json"])
        if change == "plans-not-map":
            data["plans"] = []
        elif change == "profile-unpinned":
            data["profile_images"] = ["example/native:latest"]
        elif change == "plan-scope":
            next(iter(data["plans"].values()))["namespace"] = "foreign"
        elif change == "plan-uid":
            next(iter(data["plans"].values()))["uid"] = "not-a-uid"
        elif change == "schema-version":
            data["schema_version"] = 1.5
        elif change == "plan-flags":
            next(iter(data["plans"].values()))["allow_delete"] = "true"
        elif change == "plan-template":
            next(iter(data["plans"].values()))["template"]["metadata"]["namespace"] = "foreign"
        cm["data"]["plans.json"] = json.dumps(data)
    render_upgrade(values, tmp_path, objects, expect_success=False)


def test_chart_install_refuses_seeded_canary_plans(values, tmp_path):
    values["execution"]["canaryPlans"] = {str(uuid4()): {"allow_create": True}}
    render(values, tmp_path, expect_success=False)


def test_recovery_rechecks_stop_after_plan_persistence_before_releasing_finalizer(monkeypatch):
    tool = load_installer()
    monkeypatch.setattr(tool.time, "time", lambda: 1000)
    verifier = expired_canary_verifier(tool)
    save = verifier._plans

    def change_after_stop(ref, plan=None, **kwargs):
        save(ref, plan, **kwargs)
        if plan and plan.get("stop_state") == "confirmed":
            verifier.api.pod["status"]["phase"] = "Unknown"

    verifier._plans = change_after_stop
    with pytest.raises(tool.ProbeError, match="preflight_stop_unconfirmed"):
        verifier.recover_expired()
    assert not verifier.api.released


def test_process_flag_does_not_substitute_for_this_pod_binding_refusal(monkeypatch):
    tool = load_installer()
    monkeypatch.setattr(tool.time, "time", lambda: 1000)
    verifier = expired_canary_verifier(tool, outcome="wrong-rejection")
    verifier.binding_verified = True
    with pytest.raises(tool.ProbeError, match="binding_delete_fence_unconfirmed"):
        verifier.recover_expired()
    assert not verifier.api.released


@pytest.mark.parametrize(
    "resource,verb,allowed",
    [
        ("pods/exec", "create", False),
        ("pods/status", "patch", False),
        ("pods/attach", "create", False),
        ("pods/portforward", "create", False),
        ("pods/log", "get", True),
        ("pods", "create", True),
        ("pods", "get", True),
        ("deployments.apps", "create", False),
    ],
)
def test_rbac_can_i_distinguishes_subresources_from_named_parent_resources(monkeypatch, resource, verb, allowed):
    tool = load_installer()
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        # `pods/exec` is TYPE/NAME to kubectl can-i, and therefore falsely
        # observes allowed parent-pod creation rather than the exec subresource.
        if any(value.startswith("pods/") for value in args):
            result = True
        elif resource == "pods/log":
            result = "--subresource=log" in args and verb == "get"
        else:
            result = resource == "pods" and verb in {"create", "get"}
        return subprocess.CompletedProcess(args, 0 if result else 1, "yes\n" if result else "no\n", "")

    monkeypatch.setattr(tool.subprocess, "run", run)
    api = tool.Kubectl(
        context="test",
        control_namespace="runtime-system",
        execution_namespace="runtime-apps",
        manager_account="runtime-manager",
    )
    assert api.can(verb, resource, "runtime-apps") is allowed
    command = calls[0][0]
    index = command.index("can-i")
    base, _, subresource = resource.partition("/")
    assert command[index + 1 : index + 3] == [verb, base]
    assert (
        ("--subresource=" + subresource in command)
        if subresource
        else not any(value.startswith("--subresource=") for value in command)
    )
    assert command[-2:] == ["-n", "runtime-apps"]
    assert "system:serviceaccount:runtime-system:runtime-manager" in command


@pytest.mark.parametrize(
    "identities",
    [
        None,
        [
            "system:serviceaccount:kube-system:persistent-volume-binder",
            "system:serviceaccount:kube-system:pvc-protection-controller",
        ],
    ],
)
def test_chart_storage_controller_identities_are_shared_by_admission_and_report(values, tmp_path, identities):
    from runtime_manager.k8s_capabilities import REQUIRED_CHECKS, assess_capabilities, descriptor_digest

    default = ["system:kube-controller-manager", "system:kube-scheduler"]
    if identities is not None:
        values["execution"]["storageControllerUsernames"] = identities

    def rendered():
        documents = render(values, tmp_path)
        cm = next(
            row
            for row in documents
            if row["kind"] == "ConfigMap" and row["metadata"]["name"] == "runtime-deployment-descriptor"
        )
        deployment = next(
            row for row in documents if row["kind"] == "Deployment" and row["metadata"]["name"] == "runtime-admission"
        )
        environment = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        raw = next(row["value"] for row in environment if row["name"] == "RTM_STORAGE_CONTROLLER_USERNAMES")
        return json.loads(cm["data"]["descriptor.json"]), json.loads(raw)

    document, configured = rendered()
    assert configured == document["storage_controller_usernames"] == (identities if identities is not None else default)
    initial_digest = descriptor_digest(document)
    values["execution"]["probeReport"] = {
        "source": "cluster-probe",
        "observed_at": 1000,
        "descriptor_digest": initial_digest,
        "checks": [{"name": name, "ok": True, "evidence": {"uid": str(uuid4())}} for name in REQUIRED_CHECKS],
    }
    verified, _ = rendered()
    assert descriptor_digest(verified) == initial_digest
    assert assess_capabilities(verified, now=1001)["ready"]
    values["execution"]["storageControllerUsernames"] = ["system:serviceaccount:kube-system:replacement-volume-binder"]
    changed, configured = rendered()
    assert configured == changed["storage_controller_usernames"] == values["execution"]["storageControllerUsernames"]
    assert {key: value for key, value in changed.items() if key != "storage_controller_usernames"} == {
        key: value for key, value in verified.items() if key != "storage_controller_usernames"
    }
    assert descriptor_digest(changed) != initial_digest
    assert not assess_capabilities(changed, now=1001)["ready"]


@pytest.mark.parametrize(
    "identities",
    [
        [],
        [""],
        ["alice"],
        ["system:anonymous"],
        ["system:authenticated"],
        ["system:serviceaccounts"],
        ["system:node:worker-a"],
        ["system:serviceaccount:BadNamespace:pvc-binder"],
        ["system:serviceaccount:kube-system:-binder"],
        ["system:serviceaccount:kube-system:binder..controller"],
        ["system:serviceaccount:kube-system:"],
        ["system:kube-scheduler", "system:kube-scheduler"],
        [7],
        {"controller": "system:kube-controller-manager"},
    ],
)
def test_chart_refuses_empty_foreign_ambiguous_or_duplicate_storage_identities(values, tmp_path, identities):
    values["execution"]["storageControllerUsernames"] = identities
    render(values, tmp_path, expect_success=False)


def negative_probe_verifier(tool, *, outcome="psa", initial_failure=False, cleanup_failure=False):
    from runtime_manager.k8s_templates import RESOURCE_LABEL

    reference = str(uuid4())
    template = {
        "metadata": {"name": "preflight-base", "namespace": "runtime-apps", "labels": {RESOURCE_LABEL: reference}},
        "spec": {
            "containers": [
                {
                    "image": "example/helper@sha256:" + "a" * 64,
                    "securityContext": {"privileged": False, "allowPrivilegeEscalation": False},
                }
            ]
        },
    }
    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.namespace, verifier.idle = "runtime-apps", {"metadata": {"uid": str(uuid4())}}
    verifier.created = [{"resource": "pods", "plan": {"template": template}}]
    verifier.plans, verifier.calls = {}, []

    def plans(ref, plan=None, *, remove=False):
        verifier.calls.append(("plan", ref, remove))
        if remove:
            if cleanup_failure:
                raise tool.ProbeError("admission_refresh_revision_unconfirmed")
            verifier.plans.pop(ref, None)
        else:
            verifier.plans[ref] = copy.deepcopy(plan)
            if initial_failure:
                raise tool.ProbeError("admission_refresh_refused")

    class Api:
        def raw(self, method, path, **kwargs):
            verifier.calls.append((method, path, copy.deepcopy(kwargs)))
            assert method == "POST" and path.endswith("?dryRun=All") and kwargs["manager"] is True
            if outcome == "api-unknown":
                raise tool.ProbeError("kubectl_request_failed")
            security = kwargs["document"]["spec"]["containers"][0]["securityContext"]
            if security.get("privileged") is True and security.get("allowPrivilegeEscalation") is False:
                return subprocess.CompletedProcess(
                    [], 1, "", "cannot set allowPrivilegeEscalation to false and privileged to true"
                )
            if outcome == "accepted":
                return subprocess.CompletedProcess([], 0, "{}", "")
            reason = {
                "psa": 'violates PodSecurity "restricted:v1.28"',
                "template": "admission_template_mismatch",
                "schema": "Pod invalid: schema_validation_refused",
                "unavailable": "admission_plan_unavailable",
            }[outcome]
            return subprocess.CompletedProcess([], 1, "", reason)

    def wait(callback):
        if not callback():
            raise tool.ProbeError("probe_deadline_exceeded")

    verifier.api, verifier._plans, verifier._wait = Api(), plans, wait
    return verifier


def test_psa_negative_is_schema_valid_and_removes_only_its_dry_run_plan():
    tool = load_installer()
    verifier = negative_probe_verifier(tool)
    original = copy.deepcopy(verifier.created)
    assert verifier._admission_negative(psa=True)["ok"]
    submitted = next(row[2]["document"] for row in verifier.calls if row[0] == "POST")
    assert submitted["spec"]["containers"][0]["securityContext"] == {
        "privileged": True,
        "allowPrivilegeEscalation": True,
    }
    assert verifier.created == original
    assert not verifier.plans
    assert [row[2] for row in verifier.calls if row[0] == "plan"] == [False, True]


@pytest.mark.parametrize(
    "outcome,reason",
    [
        ("schema", "admission_negative_unconfirmed"),
        ("template", "admission_negative_unconfirmed"),
        ("accepted", "admission_negative_was_accepted"),
        ("api-unknown", "kubectl_request_failed"),
        ("unavailable", "probe_deadline_exceeded"),
    ],
)
def test_psa_probe_refuses_unproven_denials_and_cleans_dry_run_approval(outcome, reason):
    tool = load_installer()
    verifier = negative_probe_verifier(tool, outcome=outcome)
    with pytest.raises(tool.ProbeError, match=reason):
        verifier._admission_negative(psa=True)
    assert not verifier.plans
    assert [row[2] for row in verifier.calls if row[0] == "plan"] == [False, True]


@pytest.mark.parametrize("psa", [True, False])
def test_dry_run_plan_is_removed_when_registration_refresh_fails(psa):
    tool = load_installer()
    verifier = negative_probe_verifier(tool, initial_failure=True)
    with pytest.raises(tool.ProbeError, match="admission_refresh_refused"):
        verifier._admission_negative(psa=psa)
    assert not verifier.plans
    assert not any(row[0] == "POST" for row in verifier.calls)


@pytest.mark.parametrize("outcome,probe_reason", [("psa", None), ("schema", "admission_negative_unconfirmed")])
def test_negative_probe_preserves_cleanup_error_and_original_failure(outcome, probe_reason):
    tool = load_installer()
    verifier = negative_probe_verifier(tool, outcome=outcome, cleanup_failure=True)
    with pytest.raises(tool.ProbeRunFailure) as failed:
        verifier._admission_negative(psa=True)
    details = tool.failure_details(failed.value)
    assert details[-1] == {
        "phase": "cleanup",
        "reason": "admission_refresh_revision_unconfirmed",
        "exception_type": "ProbeError",
    }
    if probe_reason:
        assert details[0] == {"phase": "probe", "reason": probe_reason, "exception_type": "ProbeError"}
    else:
        assert len(details) == 1 and failed.value.probe_error is None
    assert verifier.plans and all(plan["uid"] is None for plan in verifier.plans.values())


def test_per_check_report_keeps_safe_negative_probe_and_cleanup_diagnostics():
    tool = load_installer()
    verifier = negative_probe_verifier(tool, outcome="schema", cleanup_failure=True)
    report = tool.execute_checks(
        {"restricted-psa": lambda: verifier._admission_negative(psa=True)}, {}, observed_at=1000
    )
    row = report["checks"][0]
    assert not row["ok"]
    assert row["failures"] == [
        {"phase": "probe", "reason": "admission_negative_unconfirmed", "exception_type": "ProbeError"},
        {"phase": "cleanup", "reason": "admission_refresh_revision_unconfirmed", "exception_type": "ProbeError"},
    ]


def test_outer_cleanup_failure_keeps_safe_nested_probe_cleanup_evidence():
    tool = load_installer()
    verifier = negative_probe_verifier(tool, outcome="schema", cleanup_failure=True)
    report = tool.execute_checks(
        {"restricted-psa": lambda: verifier._admission_negative(psa=True)}, {}, observed_at=1000
    )
    error = tool.ProbeRunFailure(None, tool.ProbeError("preflight_finalizer_release_refused"), report)
    details = tool.failure_details(error)
    assert any(
        row.get("name") == "restricted-psa"
        and row.get("step") == "probe"
        and row["reason"] == "admission_negative_unconfirmed"
        for row in details
    )
    assert any(
        row.get("name") == "restricted-psa"
        and row.get("step") == "cleanup"
        and row["reason"] == "admission_refresh_revision_unconfirmed"
        for row in details
    )
    assert details[-1]["phase"] == "cleanup" and details[-1]["reason"] == "preflight_finalizer_release_refused"


def test_nested_cleanup_diagnostics_do_not_copy_private_exception_fields():
    tool = load_installer()
    report = {
        "checks": [
            {
                "name": "restricted-psa",
                "ok": False,
                "exception_type": "ProbeRunFailure",
                "reason": "probe_failed",
                "failures": [
                    {"phase": "probe", "exception_type": "ProbeError", "reason": "PRIVATE_SENTINEL"},
                    {
                        "phase": "cleanup",
                        "exception_type": "ProbeError",
                        "reason": "admission_refresh_refused",
                        "stderr": "PRIVATE_SENTINEL",
                    },
                ],
            }
        ]
    }
    details = tool.failure_details(
        tool.ProbeRunFailure(None, tool.ProbeError("preflight_finalizer_release_refused"), report)
    )
    assert "PRIVATE_SENTINEL" not in json.dumps(details)
    assert any(row.get("step") == "probe" and row["reason"] == "probe_failed" for row in details)
    assert any(row.get("step") == "cleanup" and row["reason"] == "admission_refresh_refused" for row in details)


class RegistryUpstreamApi:
    """Model public K8s responses without granting the canary service credentials."""

    control, execution = "runtime-system", "runtime-apps"

    def __init__(self, tool, *, tcp_ok=True, publish_unready=False, observation="same"):
        self.tool, self.tcp_ok, self.publish_unready = tool, tcp_ok, publish_unready
        self.observation = observation
        self.calls, self.pod = [], None
        self.namespace_uid = str(uuid4())

    def get(self, kind, name, **kwargs):
        self.calls.append(("get", kind, name, kwargs))
        if kind == "service":
            assert name == "egress-proxy" and kwargs["namespace"] == self.control
            return {"spec": {"selector": {"app": name}, "publishNotReadyAddresses": self.publish_unready}}
        if kind == "namespace":
            return {"metadata": {"uid": self.namespace_uid}}
        assert kind == "pod" and kwargs["namespace"] == self.control and self.pod
        if self.observation == "unknown":
            raise self.tool.ProbeError("kubectl_request_failed")
        observed = copy.deepcopy(self.pod)
        observed["spec"]["nodeName"] = "worker-a"
        observed["status"] = {
            "phase": "Succeeded",
            "containerStatuses": [{"name": "app", "state": {"terminated": {"exitCode": 0}}}],
        }
        if self.observation == "replaced":
            observed["metadata"]["uid"] = str(uuid4())
        if self.observation == "failed":
            observed["status"]["phase"] = "Failed"
        return observed

    def call(self, args, *, document=None):
        self.calls.append(("call", args, copy.deepcopy(document)))
        if args[0] == "create":
            self.pod = copy.deepcopy(document)
            self.pod["metadata"].update(uid=str(uuid4()), resourceVersion="41")
            return subprocess.CompletedProcess([], 0, json.dumps(self.pod), "")
        if args[0] == "logs":
            targets = json.loads(self.pod["spec"]["containers"][0]["env"][0]["value"])["targets"]
            result = {
                "checks": [
                    {"name": row["name"], "ok": self.tcp_ok, "reason": "connected" if self.tcp_ok else "timeout"}
                    for row in targets
                ]
            }
            return subprocess.CompletedProcess([], 0, self.tool._RESULT + json.dumps(result), "")
        assert args[:2] == ["patch", "pod"]
        patch = json.loads(args[args.index("-p") + 1])
        assert patch == {"metadata": {"resourceVersion": "42", "finalizers": []}}
        return subprocess.CompletedProcess([], 0, "{}", "")

    def raw(self, method, path, *, document):
        self.calls.append(("raw", method, path, copy.deepcopy(document)))
        assert method == "DELETE" and path.endswith("/pods/" + self.pod["metadata"]["name"])
        assert document["preconditions"] == {"uid": self.pod["metadata"]["uid"], "resourceVersion": "41"}
        self.pod["metadata"].update(deletionTimestamp="2026-10-23T00:00:00Z", resourceVersion="42")
        return subprocess.CompletedProcess([], 0, "{}", "")


def registry_upstream_verifier(tool, monkeypatch, **kwargs):
    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.api = RegistryUpstreamApi(tool, **kwargs)
    verifier.namespace, verifier.timeout = verifier.api.execution, 5
    verifier.options = {"installation_id": "test-runtime"}
    verifier.document = {
        "platform": "linux/amd64",
        "status_policy_revision": "v1",
        "helper_image": "192.0.2.10:5443/team/helper@sha256:" + "a" * 64,
        "assembler_image": "192.0.2.10:5443/team/assembler@sha256:" + "b" * 64,
        "image_repository": "192.0.2.10:5443/team/apps",
        "image_registry_endpoints": [],
        "canary_profiles": [],
    }
    verifier.created, verifier.control_created, verifier.crane_calls = [], [], []

    def wait(callback):
        result = callback()
        if not result:
            raise tool.ProbeError("probe_deadline_exceeded")
        return result

    verifier._wait = wait

    def run(command, **kwargs):
        verifier.crane_calls.append(command)
        return subprocess.CompletedProcess(command, 0, "sha256:" + "a" * 64 if "digest" in command else "", "")

    monkeypatch.setattr(tool.subprocess, "run", run)
    return verifier


def test_registry_upstream_tcp_failure_blocks_external_crane_and_source_image_capability(monkeypatch):
    """覆盖 AC: AC-13、AC-16、AC-20、AC-28、AC-54、AC-55."""
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch, tcp_ok=False)
    report = tool.execute_checks({"registry-push": verifier._registry}, verifier.document, observed_at=1000)
    assert report["checks"][0]["ok"] is False
    assert verifier.crane_calls == []
    assert verifier.control_created, "failed canary must remain registered for guarded cleanup"


def test_registry_control_canary_uses_real_proxy_policy_without_becoming_service_ready(monkeypatch):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch)
    result = verifier._registry()
    pod = verifier.api.pod
    assert pod is not None, "external registry success is insufficient without the network canary"
    assert pod["metadata"]["labels"] == {
        "app": "egress-proxy",
        "runtime.bisheng.io/preflight-installation": "test-runtime",
    }
    assert pod["spec"]["readinessGates"] == [{"conditionType": "runtime.bisheng.io/preflight-not-serving"}]
    assert not pod["spec"]["automountServiceAccountToken"]
    assert all("secret" not in volume and "projected" not in volume for volume in pod["spec"]["volumes"])
    app = pod["spec"]["containers"][0]
    assert app["command"] == ["python", "-I", "-m", "runtime_manager.k8s_capabilities", "network"]
    assert [row["name"] for row in app["env"]] == ["CAPABILITY_PLAN"]
    assert result["evidence"]["uid"] == pod["metadata"]["uid"] != verifier.api.namespace_uid
    assert len(verifier.crane_calls) == 4
    assert [next(x for x in command if x in {"digest", "copy", "delete"}) for command in verifier.crane_calls] == [
        "digest",
        "copy",
        "digest",
        "delete",
    ]
    assert any(row[:3] == ("get", "service", "egress-proxy") for row in verifier.api.calls)


def test_registry_service_publishing_unready_is_refused_before_creating_canary(monkeypatch):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch, publish_unready=True)
    with pytest.raises(tool.ProbeError, match="control_probe_service_not_isolated"):
        verifier._registry()
    assert verifier.api.pod is None and verifier.crane_calls == []


@pytest.mark.parametrize(
    "observation,reason",
    [
        ("replaced", "control_probe_identity_changed"),
        ("unknown", "kubectl_request_failed"),
        ("failed", "control_probe_failed"),
    ],
)
def test_registry_canary_unknown_or_replaced_never_reaches_external_crane(monkeypatch, observation, reason):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch, observation=observation)
    with pytest.raises(tool.ProbeError, match=reason):
        verifier._registry()
    assert verifier.crane_calls == [] and verifier.control_created


def test_registry_control_canary_cleanup_retains_uid_preconditions(monkeypatch):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch)
    verifier._registry()
    assert len(verifier.control_created) == 1
    verifier.cleanup()
    assert not verifier.control_created
    deleted = [row for row in verifier.api.calls if row[:2] == ("raw", "DELETE")]
    assert len(deleted) == 1 and deleted[0][3]["preconditions"]["uid"] == verifier.api.pod["metadata"]["uid"]


def test_registry_origins_resolve_all_tcp_addresses_deduplicate_and_include_profile_bases(monkeypatch):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch)
    verifier.document.update(
        image_registry_endpoints=["https://cdn.example:5444", "https://cdn.example:5444"],
        canary_profiles=[{"runtime_image": "base.example/team/python@sha256:" + "c" * 64}],
    )
    resolved = []

    def addresses(host, port, **kwargs):
        assert kwargs["type"] == tool.socket.SOCK_STREAM
        resolved.append((host, port))
        return [
            (tool.socket.AF_INET, tool.socket.SOCK_STREAM, tool.socket.IPPROTO_TCP, "", ("192.0.2.20", port)),
            (tool.socket.AF_INET6, tool.socket.SOCK_STREAM, tool.socket.IPPROTO_TCP, "", ("2001:db8::20", port, 0, 0)),
            (tool.socket.AF_INET, tool.socket.SOCK_STREAM, tool.socket.IPPROTO_TCP, "", ("192.0.2.20", port)),
        ]

    monkeypatch.setattr(tool.socket, "getaddrinfo", addresses)
    verifier._registry()
    assert set(resolved) == {("cdn.example", 5444), ("base.example", 443)}
    targets = json.loads(verifier.api.pod["spec"]["containers"][0]["env"][0]["value"])["targets"]
    assert {(row["host"], row["port"]) for row in targets} == {
        ("192.0.2.10", 5443),
        ("192.0.2.20", 443),
        ("2001:db8::20", 443),
        ("192.0.2.20", 5444),
        ("2001:db8::20", 5444),
    }
    assert len(targets) == 5 and all(row["expected"] == "allowed" and row["protocol"] == "tcp" for row in targets)


@pytest.mark.parametrize("mode", ["dns-error", "dns-empty", "too-many", "origin-invalid", "profile-invalid"])
def test_registry_resolution_or_origin_failure_refuses_without_probe_or_crane(monkeypatch, mode):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch)
    verifier.document["image_registry_endpoints"] = ["https://cdn.example"]

    def addresses(*args, **kwargs):
        if mode == "dns-error":
            raise tool.socket.gaierror("PRIVATE_SENTINEL")
        return (
            []
            if mode == "dns-empty"
            else [
                (tool.socket.AF_INET, tool.socket.SOCK_STREAM, tool.socket.IPPROTO_TCP, "", (f"192.0.2.{i}", 443))
                for i in range(1, 34)
            ]
        )

    monkeypatch.setattr(tool.socket, "getaddrinfo", addresses)
    if mode == "origin-invalid":
        verifier.document["image_registry_endpoints"] = ["https://user:PRIVATE_SENTINEL@cdn.example"]
    if mode == "profile-invalid":
        verifier.document["canary_profiles"] = [{"runtime_image": "example/python:latest"}]
    report = tool.execute_checks({"registry-push": verifier._registry}, verifier.document, observed_at=1000)
    assert not report["checks"][0]["ok"] and "PRIVATE_SENTINEL" not in json.dumps(report)
    assert verifier.api.pod is None and verifier.crane_calls == []


def test_control_probe_rejects_unknown_role_before_creating_any_pod(monkeypatch):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch)
    with pytest.raises(tool.ProbeError, match="control_probe_role_invalid"):
        verifier._control_probe(
            "egress", [{"name": "registry", "host": "192.0.2.10", "port": 5443, "expected": "allowed"}]
        )
    assert verifier.api.pod is None


@pytest.mark.parametrize(
    "observation,reason", [("replaced", "control_cleanup_identity_changed"), ("unknown", "kubectl_request_failed")]
)
def test_registry_control_canary_cleanup_unknown_or_replacement_keeps_the_fence(monkeypatch, observation, reason):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch)
    verifier._registry()
    verifier.api.observation = observation
    with pytest.raises(tool.ProbeError, match=reason):
        verifier.cleanup()
    assert len(verifier.control_created) == 1
    assert not any(row[0] == "raw" or row[:2] == ("call", ["patch", "pod"]) for row in verifier.api.calls)


def test_registry_external_failure_after_tcp_success_retains_cleanup_and_safe_reason(monkeypatch):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch)

    def fail(command, **kwargs):
        verifier.crane_calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "PRIVATE_SENTINEL")

    monkeypatch.setattr(tool.subprocess, "run", fail)
    report = tool.execute_checks({"registry-push": verifier._registry}, verifier.document, observed_at=1000)
    assert report["checks"][0]["ok"] is False
    assert report["checks"][0]["reason"] == "registry_probe_failed"
    assert len(verifier.crane_calls) == 1 and len(verifier.control_created) == 1
    assert "PRIVATE_SENTINEL" not in json.dumps(report)


def test_registry_upstream_dns_timeout_fails_closed_without_raw_exception(monkeypatch):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch)
    verifier.document["image_registry_endpoints"] = ["https://cdn.example"]

    def fail(*args, **kwargs):
        raise TimeoutError("PRIVATE_SENTINEL")

    monkeypatch.setattr(tool.socket, "getaddrinfo", fail)
    report = tool.execute_checks({"registry-push": verifier._registry}, verifier.document, observed_at=1000)
    assert report["checks"][0]["reason"] == "registry_probe_resolution_failed"
    assert not report["checks"][0]["ok"] and "PRIVATE_SENTINEL" not in json.dumps(report)
    assert verifier.api.pod is None and verifier.crane_calls == []

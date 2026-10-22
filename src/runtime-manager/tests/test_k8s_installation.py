"""覆盖 AC: AC-13、AC-14、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-35、AC-39、AC-40、AC-41、AC-42、AC-54、AC-55."""

import importlib.util
import json
import os
import shutil
import subprocess
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
        "evidence": {},
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

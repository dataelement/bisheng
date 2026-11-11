"""F008 AC-01/02/06/16/17: operator policy is distinct from diagnostics."""

import copy
import hashlib
import json

import pytest

from runtime_manager.deployment_policy import DeploymentPolicy, PolicyError


def policy(**updates):
    return {
        "schema_version": 2,
        "configuration_source": "operator-configured",
        "installation_id": "test",
        "node_id": "node",
        "cluster_id": "cluster",
        "namespace": "apps",
        "platform": "linux/amd64",
        "status_policy_revision": "v1",
        "manager_username": "system:serviceaccount:platform:manager",
        "cni_username": "system:serviceaccount:kube-system:cni",
        "storage_controller_usernames": ["system:kube-controller-manager"],
        "memory_budget_mb": 8192,
        "cpu_budget_millicores": 4000,
        "helper_image": "example/helper@sha256:" + "a" * 64,
        "service_cidrs": ["10.96.0.0/12"],
        "storage": {"class": None, "filesystem": "ext4", "sqlite_compatible": True},
        **updates,
    }


def test_policy_digest_is_exact_bytes_and_has_no_report_age(tmp_path):
    raw = json.dumps(policy()).encode() + b"\n"
    path = tmp_path / "policy.json"
    path.write_bytes(raw)
    result = DeploymentPolicy.read(path)
    assert result.digest == hashlib.sha256(raw).hexdigest()
    assert result.raw == raw.decode()
    assert result.helper("image-check") == {"memory_mb": 256, "cpu_millicores": 1000}
    assert result.timeout("image_check") == 120


def test_ordinary_tuning_does_not_change_protection_but_actor_does():
    first = DeploymentPolicy.from_document(policy())
    changed = DeploymentPolicy.from_document(
        policy(timeouts={"image_check": 240}, placement={"nodeSelector": {"pool": "apps"}})
    )
    assert first.protection_digest == changed.protection_digest
    assert (
        first.protection_digest
        != DeploymentPolicy.from_document(
            policy(cni_username="system:serviceaccount:kube-system:other")
        ).protection_digest
    )


@pytest.mark.parametrize(
    "update",
    [
        {"schema_version": 1},
        {"memory_budget_mb": True},
        {"namespace": "kube-system"},
        {"helper_resources": {"image-check": {"memory_mb": 0, "cpu_millicores": 1000}}},
        {"helper_resources": {"untrusted": {"memory_mb": 128, "cpu_millicores": 100}}},
        {"timeouts": {"image_check": 0}},
        {"placement": {"nodeName": "node"}},
        {"placement": {"nodeSelector": {"kubernetes.io/arch": "arm64"}}},
        {"probe_report": {"ready": True}},
    ],
)
def test_unsafe_or_ambiguous_policies_fail(update):
    with pytest.raises(PolicyError):
        DeploymentPolicy.from_document(policy(**update))


def test_duplicate_fields_and_nonfinite_numbers_fail(tmp_path):
    for value in ('{"schema_version":2,"schema_version":2}', '{"schema_version":NaN}'):
        path = tmp_path / "policy.json"
        path.write_text(value)
        with pytest.raises(PolicyError):
            DeploymentPolicy.read(path)


def test_input_is_not_mutated_and_storage_class_modes_remain_distinct():
    document = policy()
    before = copy.deepcopy(document)
    parsed = DeploymentPolicy.from_document(document)
    assert parsed.document["storage"]["class"] is None
    assert document == before
    assert (
        DeploymentPolicy.from_document(
            policy(storage={"class": "", "filesystem": "xfs", "sqlite_compatible": True})
        ).document["storage"]["class"]
        == ""
    )

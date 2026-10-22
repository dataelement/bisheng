"""覆盖 AC: AC-12、AC-13、AC-16、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-30、AC-31、AC-32、AC-34、AC-42、AC-54."""

import copy
from uuid import uuid4

import pytest


def descriptor():
    return {
        "schema_version": 1,
        "cluster_id": "cluster-a",
        "namespace": "runtime-apps",
        "platform": "linux/amd64",
        "status_policy_revision": "v1",
        "helper_image": "example/helper@sha256:" + "a" * 64,
        "storage": {"sqlite_compatible": True, "node_local": True},
        "service_cidrs": ["10.96.0.0/12"],
    }


def complete(document, now=1000):
    from runtime_manager.k8s_capabilities import REQUIRED_CHECKS, descriptor_digest

    value = copy.deepcopy(document)
    value["probe_report"] = {
        "descriptor_digest": descriptor_digest(value),
        "observed_at": now,
        "source": "cluster-probe",
        "checks": [
            {"name": name, "ok": True, "reason": "verified", "evidence": {"uid": str(uuid4())}}
            for name in sorted(REQUIRED_CHECKS)
        ],
    }
    return value


def test_report_is_derived_from_every_actual_check_and_bound_to_installation():
    from runtime_manager.k8s_capabilities import assess_capabilities

    doc = complete(descriptor())
    report = assess_capabilities(doc, now=1001)
    assert report["ready"] and report["warnings"] == ["node_local_storage"]
    doc["helper_image"] = "example/helper@sha256:" + "b" * 64
    assert assess_capabilities(doc, now=1001)["ready"] is False


@pytest.mark.parametrize("change", ["missing", "unknown", "stale", "future", "boolean_only", "dry_run", "nfs"])
def test_unknown_or_unsafe_installation_never_becomes_ready(change):
    from runtime_manager.k8s_capabilities import assess_capabilities

    doc = complete(descriptor())
    if change == "missing":
        doc["probe_report"]["checks"].pop()
    elif change == "unknown":
        doc["probe_report"]["checks"][0]["ok"] = None
    elif change == "stale":
        doc["probe_report"]["observed_at"] = -100000
    elif change == "future":
        doc["probe_report"]["observed_at"] = 1010
    elif change == "boolean_only":
        doc["probe_report"] = {"ready": True}
    elif change == "dry_run":
        doc["probe_report"]["source"] = "dry-run"
    else:
        doc["storage"].update(sqlite_compatible=True, filesystem="nfs")
    assert not assess_capabilities(doc, now=1001)["ready"]


def test_optional_registry_does_not_block_bundles_and_is_required_for_assembly():
    from runtime_manager.k8s_capabilities import assess_capabilities

    report = assess_capabilities(complete(descriptor()), now=1001)
    assert report["ready"] and report["paths"]["bundle"] and report["paths"]["image"]
    assert not report["paths"]["source-image"]


def test_probe_exception_is_a_safe_failed_check_not_a_success():
    from runtime_manager.k8s_capabilities import run_checks

    def fail():
        raise ValueError("private kubeconfig token")

    result = run_checks({"network-direct-denied": fail}, observed_at=1000)
    assert result[0]["ok"] is False and "private" not in str(result)


def test_storage_probe_uses_real_private_files_and_retains_the_supplied_volume(tmp_path):
    from runtime_manager.k8s_capabilities import storage_checks

    result = storage_checks(tmp_path)
    assert result == {"locking": True, "fsync": True, "sqlite_integrity": True}
    assert tmp_path.is_dir() and list(tmp_path.iterdir()) == []

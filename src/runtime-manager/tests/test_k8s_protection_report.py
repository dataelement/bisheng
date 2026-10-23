"""覆盖 AC: AC-07、AC-30、AC-31、AC-35、AC-40、AC-48、AC-49、AC-52、AC-55."""

import copy
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from runtime_manager.config import Config
from runtime_manager.executors.kubernetes import KubernetesExecutor
from runtime_manager.k8s_capabilities import REQUIRED_CHECKS, descriptor_digest
from runtime_manager.k8s_client import KubernetesAPIError
from runtime_manager.k8s_config import KubernetesConfig

HELPER = "example.invalid/helper@sha256:" + "a" * 64
NEW_HELPER = "example.invalid/helper@sha256:" + "b" * 64


def descriptor():
    return {
        "schema_version": 1,
        "cluster_id": "cluster-a",
        "installation_id": "installation-a",
        "namespace": "runtime-apps",
        "platform": "linux/amd64",
        "status_policy_revision": "v1",
        "memory_budget_mb": 4096,
        "cpu_budget_millicores": 4000,
        "helper_image": HELPER,
        "assembler_image": "example.invalid/assembler@sha256:" + "c" * 64,
        "cni_username": "system:serviceaccount:system-a:cni",
        "storage_controller_usernames": ["system:controller-a"],
        "storage": {"sqlite_compatible": True, "filesystem": "ext4"},
        "capabilities": {"service_cidrs": ["10.96.0.0/12"]},
        "canary_profiles": {"profile-a": {"runtime_image": HELPER}},
        "network": {"egress_ports": [443]},
    }


def complete(document, observed_at=1000):
    value = copy.deepcopy(document)
    value["probe_report"] = {
        "observed_at": observed_at,
        "source": "cluster-probe",
        "descriptor_digest": descriptor_digest(value),
        "checks": [
            {"name": name, "ok": True, "reason": "verified", "evidence": {"uid": str(UUID(int=index + 1))}}
            for index, name in enumerate(sorted(REQUIRED_CHECKS))
        ],
    }
    return value


def check(document, name):
    return next(row for row in document["probe_report"]["checks"] if row.get("name") == name)


@pytest.fixture
def runtime(tmp_path):
    path = tmp_path / "descriptor.json"
    document = complete(descriptor())
    path.write_text(json.dumps(document))
    clock = SimpleNamespace(now=1001)
    cluster = SimpleNamespace(list=lambda *args, **kwargs: [])
    settings = KubernetesConfig(namespace="runtime-apps", cluster_id="cluster-a", descriptor_file=path)
    config = Config(executor_kind="kubernetes", protocol_version=2, node_id="node-a")
    executor = KubernetesExecutor(
        config,
        settings,
        platform=SimpleNamespace(),
        client=cluster,
        clock=SimpleNamespace(time=lambda: clock.now, sleep=lambda _: None),
    )
    return SimpleNamespace(executor=executor, path=path, document=document, clock=clock, cluster=cluster)


def project(runtime, document):
    runtime.path.write_text(json.dumps(document))


def observation(runtime, state, *, ready=None):
    result = runtime.executor.capabilities()
    value = result["protection_observation"]
    assert set(value) == {"version", "baseline_digest", "state"}
    assert type(value["version"]) is int and value["version"] == 1
    assert value["state"] == state
    assert len(value["baseline_digest"]) == 64
    assert all(character in "0123456789abcdef" for character in value["baseline_digest"])
    if ready is not None:
        assert runtime.executor.probe_report()["ready"] is ready
    if state != "current":
        assert result["status_protection"] is result["binding_protection"] is False
    return result


def test_protection_digest_excludes_only_report_and_helper_without_changing_full_digest():
    from runtime_manager.k8s_capabilities import protection_baseline_digest

    document = complete(descriptor())
    original = copy.deepcopy(document)
    expected = hashlib.sha256(
        json.dumps(
            {key: value for key, value in document.items() if key not in {"probe_report", "helper_image"}},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    assert protection_baseline_digest(document) == expected
    changed = {**document, "helper_image": NEW_HELPER, "probe_report": {"unverified": True}}
    assert protection_baseline_digest(changed) == expected
    assert descriptor_digest(changed) != descriptor_digest(document)
    assert document == original


@pytest.mark.parametrize("key", sorted(set(descriptor()) - {"helper_image"}))
def test_every_other_descriptor_field_changes_the_protection_baseline(key):
    from runtime_manager.k8s_capabilities import protection_baseline_digest

    first = descriptor()
    second = {**first, key: {"different": True}}
    assert protection_baseline_digest(first) != protection_baseline_digest(second)


@pytest.mark.parametrize("elapsed,state", [(0, "current"), (86400, "current"), (86400.001, "report_expired")])
def test_exact_report_ttl_retains_failed_current_capabilities(runtime, elapsed, state):
    runtime.clock.now = 1000 + elapsed
    result = observation(runtime, state, ready=state == "current")
    assert result["status_protection"] is (state == "current")
    assert result["binding_protection"] is (state == "current")


def test_expired_report_refresh_restores_current_not_ready_flag_override(runtime):
    runtime.clock.now = 100000
    first = observation(runtime, "report_expired", ready=False)["protection_observation"]
    refreshed = complete(runtime.document, runtime.clock.now)
    project(runtime, refreshed)
    second = observation(runtime, "current", ready=True)["protection_observation"]
    assert first["baseline_digest"] == second["baseline_digest"]
    assert "ready" not in refreshed["probe_report"]


@pytest.mark.parametrize("guard", ["status-provenance", "binding-delete-fence", "network-direct-denied"])
def test_current_report_keeps_individual_failed_check_semantics(runtime, guard):
    document = copy.deepcopy(runtime.document)
    check(document, guard)["ok"] = False
    project(runtime, document)
    result = observation(runtime, "current", ready=False)
    assert result["status_protection"] is (guard != "status-provenance")
    assert result["binding_protection"] is (guard != "binding-delete-fence")


def test_expired_report_can_contain_explicit_valid_non_guard_failure(runtime):
    document = copy.deepcopy(runtime.document)
    check(document, "network-direct-denied")["ok"] = False
    project(runtime, document)
    runtime.clock.now = 100000
    observation(runtime, "report_expired", ready=False)


def corrupt(document, variant):
    report = document["probe_report"]
    if variant == "source":
        report["source"] = "dry-run"
    elif variant == "digest":
        report["descriptor_digest"] = "0" * 64
    elif variant == "future":
        report["observed_at"] = 200000
    elif variant == "boolean_time":
        report["observed_at"] = True
    elif variant in {"nan", "infinity", "negative_infinity"}:
        report["observed_at"] = {"nan": float("nan"), "infinity": float("inf"), "negative_infinity": -float("inf")}[
            variant
        ]
    elif variant == "missing_guard":
        report["checks"].remove(check(document, "status-provenance"))
    elif variant == "missing_other":
        report["checks"].remove(check(document, "image-cri"))
    elif variant == "duplicate_guard":
        report["checks"].append(copy.deepcopy(check(document, "status-provenance")))
    elif variant == "duplicate_other":
        report["checks"].append(copy.deepcopy(check(document, "image-cri")))
    elif variant == "invalid_guard_uid":
        check(document, "binding-delete-fence")["evidence"]["uid"] = "not-a-uid"
    elif variant == "invalid_other_uid":
        check(document, "image-cri")["evidence"]["uid"] = "not-a-uid"
    elif variant == "failed_guard":
        check(document, "status-provenance")["ok"] = False
    elif variant == "non_boolean":
        check(document, "image-cri")["ok"] = 1
    elif variant == "missing_evidence":
        check(document, "image-cri").pop("evidence")
    elif variant == "bad_reason":
        check(document, "image-cri")["reason"] = "not a safe reason"
    elif variant == "non_list":
        report["checks"] = {}
    elif variant == "no_report":
        document.pop("probe_report")
    else:
        raise AssertionError("unknown fixture")


CORRUPTIONS = (
    "source",
    "digest",
    "future",
    "boolean_time",
    "nan",
    "infinity",
    "negative_infinity",
    "missing_guard",
    "missing_other",
    "duplicate_guard",
    "duplicate_other",
    "invalid_guard_uid",
    "invalid_other_uid",
    "failed_guard",
    "non_boolean",
    "missing_evidence",
    "bad_reason",
    "non_list",
    "no_report",
)


@pytest.mark.parametrize("variant", CORRUPTIONS)
def test_expiry_never_masks_unknown_or_invalid_guard_evidence(runtime, variant):
    document = copy.deepcopy(runtime.document)
    corrupt(document, variant)
    project(runtime, document)
    runtime.clock.now = 100000
    observation(runtime, "unconfirmed", ready=False)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True])
def test_nonfinite_or_boolean_clock_never_becomes_protection_observation(runtime, value):
    runtime.clock.now = value
    observation(runtime, "unconfirmed", ready=False)


@pytest.mark.parametrize("age", [1, 100000])
def test_only_hot_helper_change_can_use_original_positive_report(runtime, age):
    runtime.clock.now = 1000 + age
    project(runtime, {**runtime.document, "helper_image": NEW_HELPER})
    result = observation(runtime, "helper_changed", ready=False)
    assert result["helper_image"] == HELPER
    assert runtime.executor.probe_report()["warnings"] == ["installation_changed_restart_required"]
    assert runtime.executor.document["helper_image"] == HELPER


def test_hot_helper_change_with_new_matching_fresh_positive_report_still_requires_restart(runtime):
    project(runtime, complete({**runtime.document, "helper_image": NEW_HELPER}))
    observation(runtime, "helper_changed", ready=False)


@pytest.mark.parametrize("variant", CORRUPTIONS)
def test_hot_helper_exception_requires_a_fully_verified_original_report(runtime, variant):
    corrupt(runtime.executor.document, variant)
    project(runtime, {**runtime.document, "helper_image": NEW_HELPER})
    observation(runtime, "unconfirmed", ready=False)


@pytest.mark.parametrize("guard", ["status-provenance", "binding-delete-fence"])
@pytest.mark.parametrize("variant", ["failed", "missing", "bad_uid"])
def test_new_helper_report_guard_failure_or_unknown_cannot_be_hidden_by_old_positive(runtime, guard, variant):
    fresh = complete({**runtime.document, "helper_image": NEW_HELPER})
    if variant == "failed":
        check(fresh, guard)["ok"] = False
    elif variant == "missing":
        fresh["probe_report"]["checks"].remove(check(fresh, guard))
    else:
        check(fresh, guard)["evidence"]["uid"] = "wrong"
    project(runtime, fresh)
    observation(runtime, "unconfirmed", ready=False)


@pytest.mark.parametrize("helper", [None, [], "python:3.11", "example.invalid/helper@sha256:bad"])
def test_helper_exception_requires_valid_pinned_helper_images(runtime, helper):
    project(runtime, {**runtime.document, "helper_image": helper})
    observation(runtime, "unconfirmed", ready=False)


@pytest.mark.parametrize(
    "key,value",
    [
        ("status_policy_revision", "v2"),
        ("installation_id", "other-installation"),
        ("cni_username", "system:serviceaccount:other:cni"),
        ("storage_controller_usernames", ["system:other"]),
        ("assembler_image", NEW_HELPER),
        ("storage", {"sqlite_compatible": False}),
        ("canary_profiles", {}),
        ("network", {"egress_ports": [80]}),
        ("memory_budget_mb", 8192),
    ],
)
def test_any_other_descriptor_change_never_qualifies_as_helper_only(runtime, key, value):
    project(runtime, {**runtime.document, "helper_image": NEW_HELPER, key: value})
    observation(runtime, "unconfirmed", ready=False)


def test_cold_restart_with_new_helper_and_old_bound_report_does_not_qualify(runtime):
    project(runtime, {**runtime.document, "helper_image": NEW_HELPER})
    runtime.executor = KubernetesExecutor(
        runtime.executor.config,
        runtime.executor.settings,
        platform=SimpleNamespace(),
        client=runtime.cluster,
        clock=runtime.executor.clock,
    )
    observation(runtime, "unconfirmed", ready=False)


def test_descriptor_read_failure_is_unconfirmed_without_source_or_exception_text(runtime):
    runtime.path.write_text("not-json")
    result = observation(runtime, "unconfirmed", ready=False)
    assert "not-json" not in json.dumps(result)


def test_current_api_unavailability_does_not_change_individual_protection_results(runtime):
    def unavailable(*args, **kwargs):
        raise KubernetesAPIError("unavailable", 503)

    runtime.cluster.list = unavailable
    result = observation(runtime, "current", ready=True)
    assert result["orchestration_available"] is False
    assert result["status_protection"] is result["binding_protection"] is True

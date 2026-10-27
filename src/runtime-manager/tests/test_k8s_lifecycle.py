"""覆盖 AC: AC-08、AC-09、AC-11、AC-35、AC-43、AC-48、AC-49、AC-50、AC-52."""

import copy
from datetime import UTC, datetime

import pytest

from runtime_manager.k8s_client import KubernetesAPIError

NOW = datetime(2026, 10, 21, 5, 0, tzinfo=UTC)
UID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def identity():
    from runtime_manager.k8s_lifecycle import StopIdentity

    return StopIdentity(
        namespace="bisheng-runtime-apps",
        name="app-a",
        uid=UID,
        policy_revision="v1",
        protected_since_creation=True,
        binding_policy_verified=True,
    )


@pytest.fixture
def pod():
    from runtime_manager.k8s_templates import POLICY_ANNOTATION, STOP_FINALIZER

    return {
        "metadata": {
            "namespace": "bisheng-runtime-apps",
            "name": "app-a",
            "uid": UID,
            "resourceVersion": "17",
            "deletionTimestamp": "2026-10-21T04:59:50Z",
            "annotations": {POLICY_ANNOTATION: "v1"},
            "finalizers": [STOP_FINALIZER],
        },
        "spec": {"nodeName": "worker-a", "containers": [{"name": "app"}]},
        "status": {
            "phase": "Failed",
            "containerStatuses": [
                {"name": "app", "state": {"terminated": {"exitCode": 1}}, "containerID": "containerd://one"}
            ],
        },
    }


class Cluster:
    def __init__(self, pod):
        self.pod = pod
        self.calls = []

    def get(self, resource, name):
        self.calls.append(("get", resource, name))
        if isinstance(self.pod, Exception):
            raise self.pod
        return copy.deepcopy(self.pod)

    def delete(self, resource, name, **kwargs):
        self.calls.append(("delete", resource, name, kwargs))
        return {}

    def patch(self, resource, name, payload, **kwargs):
        self.calls.append(("patch", resource, name, payload, kwargs))
        return {}


def test_trusted_terminal_is_read_fresh_and_preserves_uid_version_evidence(identity, pod):
    from runtime_manager.k8s_lifecycle import observe_stop

    api = Cluster(pod)
    result = observe_stop(api, identity, now=NOW)
    assert result.confirmed and result.kind == "kubelet_terminal"
    assert api.calls == [("get", "pods", "app-a")]
    assert result.evidence["uid"] == UID and result.evidence["resource_version"] == "17"
    assert result.evidence["node_name"] == "worker-a" and len(result.evidence["status_digest"]) == 64


def test_init_failure_can_stop_without_ids_for_never_started_containers(identity, pod):
    from runtime_manager.k8s_lifecycle import observe_stop

    pod["status"] = {
        "phase": "Failed",
        "initContainerStatuses": [{"name": "material-fetch", "state": {"waiting": {"reason": "ImagePullBackOff"}}}],
    }
    result = observe_stop(Cluster(pod), identity, now=NOW)
    assert result.kind == "kubelet_terminal" and result.confirmed


def test_deleting_unscheduled_uid_has_a_distinct_stop_proof(identity, pod):
    from runtime_manager.k8s_lifecycle import observe_stop

    pod["spec"].pop("nodeName")
    pod["status"] = {"phase": "Pending"}
    assert observe_stop(Cluster(pod), identity, now=NOW).kind == "never_scheduled"


@pytest.mark.parametrize(
    "change",
    [
        "not-deleting",
        "different-uid",
        "running",
        "unknown",
        "node-lost",
        "wrong-policy",
        "no-finalizer",
        "no-version",
        "foreign-namespace",
        "changed-node",
    ],
)
def test_ambiguous_state_holds_writer_and_reservation(identity, pod, change):
    from dataclasses import replace

    from runtime_manager.k8s_lifecycle import observe_stop

    if change == "not-deleting":
        pod["metadata"].pop("deletionTimestamp")
    elif change == "different-uid":
        pod["metadata"]["uid"] = "other"
    elif change == "running":
        pod["status"]["containerStatuses"][0]["state"] = {"running": {"startedAt": "2026-10-21T04:00:00Z"}}
    elif change == "unknown":
        pod["status"]["phase"] = "Unknown"
    elif change == "node-lost":
        pod["status"]["reason"] = "NodeLost"
    elif change == "wrong-policy":
        pod["metadata"]["annotations"] = {}
    elif change == "no-finalizer":
        pod["metadata"]["finalizers"] = []
    elif change == "no-version":
        pod["metadata"].pop("resourceVersion")
    elif change == "foreign-namespace":
        pod["metadata"]["namespace"] = "foreign"
    elif change == "changed-node":
        identity = replace(identity, last_node_name="previous-worker")
    result = observe_stop(Cluster(pod), identity, now=NOW)
    assert result.kind == "unknown" and not result.confirmed


@pytest.mark.parametrize(
    "error",
    [
        KubernetesAPIError("refused", 404),
        KubernetesAPIError("refused", 403),
        KubernetesAPIError("transport_unavailable"),
    ],
)
def test_missing_or_unreachable_object_never_proves_stop(identity, error):
    from runtime_manager.k8s_lifecycle import observe_stop

    assert not observe_stop(Cluster(error), identity, now=NOW).confirmed


def test_unprotected_terminal_and_stale_cache_cannot_release(identity, pod):
    from dataclasses import replace

    from runtime_manager.k8s_lifecycle import classify_stop, observe_stop

    assert not observe_stop(Cluster(pod), replace(identity, protected_since_creation=False), now=NOW).confirmed
    assert not classify_stop(pod, identity, now=NOW, fresh=False).confirmed
    pod["spec"].pop("nodeName")
    assert not observe_stop(Cluster(pod), replace(identity, binding_policy_verified=False), now=NOW).confirmed
    assert not observe_stop(Cluster(pod), replace(identity, last_node_name="worker-a"), now=NOW).confirmed


def test_delete_acknowledgement_is_not_stop_and_uses_preconditions(identity, pod):
    from runtime_manager.k8s_lifecycle import request_stop

    pod["metadata"].pop("deletionTimestamp")
    api = Cluster(pod)
    result = request_stop(api, identity)
    assert not result.confirmed
    assert api.calls[-1][0] == "delete"
    assert api.calls[-1][3]["uid"] == UID and api.calls[-1][3]["resource_version"] == "17"


def test_finalizer_only_removed_after_backend_commits_same_uid_stop(identity, pod):
    from runtime_manager.k8s_lifecycle import finish_stop

    api = Cluster(pod)
    committed = []

    def commit(evidence):
        committed.append(evidence)
        assert not any(x[0] == "patch" for x in api.calls)
        return {"uid": UID, "stop_state": "confirmed"}

    assert finish_stop(api, identity, commit, now=NOW).confirmed
    assert len(committed) == 1 and api.calls[-1][0] == "patch"
    assert api.calls[-1][4]["resource_version"] == "17"


@pytest.mark.parametrize("receipt", [{"uid": "other", "stop_state": "confirmed"}, {"uid": UID, "stop_state": "held"}])
def test_uncommitted_receipt_keeps_finalizer(identity, pod, receipt):
    from runtime_manager.k8s_lifecycle import finish_stop

    api = Cluster(pod)
    with pytest.raises(RuntimeError, match="stop_receipt"):
        finish_stop(api, identity, lambda _: receipt, now=NOW)
    assert not any(x[0] == "patch" for x in api.calls)


def test_backend_failure_or_same_name_replacement_never_removes_protection(identity, pod):
    from runtime_manager.k8s_lifecycle import finish_stop

    api = Cluster(pod)

    def fail(_):
        raise RuntimeError("backend_unavailable")

    with pytest.raises(RuntimeError):
        finish_stop(api, identity, fail, now=NOW)
    assert not any(x[0] == "patch" for x in api.calls)

    def replaced(_):
        api.pod["metadata"]["uid"] = "new-uid"
        return {"uid": UID, "stop_state": "confirmed"}

    result = finish_stop(api, identity, replaced, now=NOW)
    assert not result.confirmed and not any(x[0] == "patch" for x in api.calls)

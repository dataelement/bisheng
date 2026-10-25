"""覆盖 AC: AC-35、AC-46、AC-49、AC-50、AC-52、AC-55.

The real operation/maintenance/helper/fact-schema chain uses the existing scoped
Kubernetes I/O doubles. This is not deployed kubelet or backend SQL evidence.
"""

from __future__ import annotations

import copy
from uuid import uuid4

import pytest

from runtime_manager.k8s_client import KubernetesAPIError
from runtime_manager.platform_client import PlatformError
from tests.test_k8s_destroy_fact_contract import ManagerCrash
from tests.test_k8s_destroy_fact_contract import destroy as destroy
from tests.test_kubernetes_executor import runtime as runtime


def volume(case):
    return next(r for r in case.platform.rows.values() if r["kind"] == "PersistentVolumeClaim")


def deferred(case, monkeypatch, tick):
    row = copy.deepcopy(volume(case))
    key = ("persistentvolumeclaims", row["name"])
    case.cluster.deferred_deletions.add(key)
    sleep, snapshots = case.kube.clock.sleep, []

    def advance(seconds):
        sleep(seconds)
        if key in case.cluster.pending_deletions:
            current = case.platform.operation(case.operation["operation_id"])
            snapshots.append((case.kube.clock.time(), copy.deepcopy(current), copy.deepcopy(volume(case))))
            tick(case, row, key, len(snapshots))

    monkeypatch.setattr(case.kube.clock, "sleep", advance)
    return row, key, snapshots


def closed(case):
    current = case.platform.operation(case.operation["operation_id"])
    assert current["status"] == current["stage"] == "completed"
    assert current["cleanup_status"] == "complete"
    assert current["result"]["maintenance_progress"]["purge"]["result"] == {"purged": True}
    assert len(case.helper_runs) == 1
    assert not case.database.exists() and not case.backups.exists()
    assert volume(case)["cleanup_state"] == "complete"
    assert not any(kind in {"pods", "persistentvolumeclaims"} for kind, _ in case.cluster.objects)
    assert all(status == 200 for _, status in case.boundary.responses)


def held(case):
    current = case.platform.operation(case.operation["operation_id"])
    assert current["status"] != "completed"
    assert not any(f["phase"] == "completed" for f in case.boundary.accepted)
    assert volume(case)["cleanup_state"] == "pending"
    assert len(case.helper_runs) == 1
    assert current["result"]["maintenance_progress"]["purge"]["result"] == {"purged": True}


def test_async_delete_waits_for_actual_absence_after_persisted_purge(destroy, monkeypatch):
    """F059 AC-35, AC-49, AC-52: a DELETE acknowledgement is not cleanup."""
    removed = []

    def tick(case, row, key, count):
        assert case.cluster.objects[key]["metadata"]["uid"] == row["uid"]
        assert case.cluster.objects[key]["metadata"]["deletionTimestamp"]
        current = case.platform.operation(case.operation["operation_id"])
        assert current["status"] == "running" and current["stage"] == "maintenance"
        assert current["result"]["maintenance_progress"]["purge"]["result"] == {"purged": True}
        pods = [r for r in case.platform.rows.values() if r["kind"] == "Pod"]
        assert len(pods) == 1 and pods[0]["stop_state"] == "confirmed" and pods[0]["cleanup_state"] == "complete"
        assert volume(case)["cleanup_state"] == "pending" and len(case.helper_runs) == 1
        if count == 3:
            assert case.cluster.complete_deletion(*key, uid=row["uid"])
            removed.append(case.kube.clock.time())

    row, key, snapshots = deferred(destroy, monkeypatch, tick)
    destroy.manager().execute(destroy.operation["operation_id"])
    closed(destroy)
    assert len(snapshots) == 3 and len(removed) == 1 and snapshots[0][0] < removed[0]
    assert key not in destroy.cluster.objects and not destroy.cluster.pending_deletions
    actual = volume(destroy)
    assert actual["uid"] == row["uid"]
    assert actual["operation_id"] == row["operation_id"] != destroy.operation["operation_id"]
    assert all(actual[k] is row[k] is True for k in ("protected_since_creation", "binding_policy_verified"))
    progress = destroy.events.index(("fact-committed", "maintenance", True))
    pvc = next(i for i, e in enumerate(destroy.events) if e[:2] == ("delete", "persistentvolumeclaims"))
    completed = destroy.events.index(("fact-committed", "completed", True))
    assert progress < pvc < completed


def test_restart_after_delete_ack_uses_saved_result_without_another_helper(destroy, monkeypatch):
    """F059 AC-46, AC-52: crash during cleanup cannot repeat the destructive helper."""
    crashed = []

    def tick(case, row, key, _count):
        if not crashed:
            crashed.append(True)
            raise ManagerCrash()
        assert case.platform.operation(case.operation["operation_id"])["status"] == "running"
        assert case.cluster.complete_deletion(*key, uid=row["uid"])

    _, _, snapshots = deferred(destroy, monkeypatch, tick)
    with pytest.raises(ManagerCrash):
        destroy.manager().execute(destroy.operation["operation_id"])
    current = destroy.platform.operation(destroy.operation["operation_id"])
    assert current["status"] == "running" and current["stage"] == "maintenance"
    assert current["result"]["maintenance_progress"]["purge"]["result"] == {"purged": True}
    assert volume(destroy)["cleanup_state"] == "pending"
    creates = [e for e in destroy.events if e[0] == "purge-pod-create"]
    assert len(creates) == len(destroy.helper_runs) == 1
    destroy.manager(fresh=True).execute(destroy.operation["operation_id"])
    closed(destroy)
    assert len(snapshots) >= 2
    assert [e for e in destroy.events if e[0] == "purge-pod-create"] == creates
    before = copy.deepcopy(destroy.events)
    destroy.manager(fresh=True).execute(destroy.operation["operation_id"])
    assert destroy.events == before


@pytest.mark.parametrize(
    "change", ["cancel", "deadline", "shortened-deadline", "owner-epoch", "generation", "app", "node"]
)
def test_pending_cleanup_preserves_deadline_cancel_and_scope(destroy, monkeypatch, change):
    """F059 AC-46, AC-49, AC-55: the original operation bounds every cleanup retry."""
    clock = destroy.kube.clock
    started = clock.time()
    if change == "deadline":
        # A task Pod requires a positive whole-second activeDeadlineSeconds.
        destroy.operation["deadline"] = clock.iso(2)
    initial, changed = copy.deepcopy(destroy.operation), []

    def tick(case, _row, _key, _count):
        if changed:
            return
        changed.append(change)
        current = case.platform.operations[initial["operation_id"]]
        if change == "cancel":
            current["payload"]["cancel_requested"] = True
        elif change == "shortened-deadline":
            current["deadline"] = clock.iso(0.1)
        elif change in {"owner-epoch", "generation"}:
            current[change.replace("-", "_")] += 1
        elif change in {"app", "node"}:
            current[change + "_id"] = "different-" + change

    _, key, snapshots = deferred(destroy, monkeypatch, tick)
    destroy.manager().execute(initial["operation_id"])
    assert changed and snapshots
    held(destroy)
    current = destroy.platform.operation(initial["operation_id"])
    expected = "cancelled" if change == "cancel" else "timed_out" if "deadline" in change else "failed"
    reason = (
        "operation_cancelled"
        if change == "cancel"
        else "operation_timeout"
        if "deadline" in change
        else "execution_fence_mismatch"
    )
    assert current["status"] == expected and current["failure"]["reason"] == reason
    assert key in destroy.cluster.objects
    if change == "deadline":
        assert clock.time() == started + 2
    else:
        assert clock.time() - snapshots[0][0] <= 1
    if change != "shortened-deadline":
        assert current["deadline"] == initial["deadline"]


@pytest.mark.parametrize("change", ["replacement-uid", "lost-controller", "operation-api-unavailable"])
def test_uncertain_identity_or_authority_never_confirms_cleanup(destroy, monkeypatch, change):
    """F059 AC-49, AC-50, AC-52: unknown identity or permission is still held."""
    changed = []

    def tick(case, _row, key, _count):
        if changed:
            return
        changed.append(change)
        if change == "replacement-uid":
            case.cluster.objects[key]["metadata"]["uid"] = str(uuid4())
        elif change == "lost-controller":
            case.platform.holder = "another-manager"
            case.platform.epoch += 1
            case.platform.lease_until = case.kube.clock.time() + 30
        else:
            operation = case.platform.operation

            def unavailable(ident):
                if ident == case.operation["operation_id"]:
                    raise PlatformError("fixture_control_unavailable", 503)
                return operation(ident)

            monkeypatch.setattr(case.platform, "operation", unavailable)

    _, key, snapshots = deferred(destroy, monkeypatch, tick)
    try:
        destroy.manager().execute(destroy.operation["operation_id"])
    except PlatformError as error:
        assert change == "operation-api-unavailable" and error.status == 503
    assert changed and snapshots and key in destroy.cluster.objects
    assert volume(destroy)["cleanup_state"] == "pending"
    assert not any(f["phase"] == "completed" for f in destroy.boundary.accepted)
    assert len(destroy.helper_runs) == 1


@pytest.mark.parametrize("status", [403, 503, None])
def test_non_pending_api_errors_are_not_accepted_as_cleanup_progress(destroy, monkeypatch, status):
    """F059 AC-49, AC-50: a forbidden/uncertain DELETE is not proof of absence."""
    delete, calls = destroy.cluster.delete, []

    def fail(resource, name, **preconditions):
        if resource == "persistentvolumeclaims":
            assert preconditions["uid"] == volume(destroy)["uid"]
            calls.append(preconditions)
            if status is None:
                delete(resource, name, **preconditions)
            raise KubernetesAPIError("fixture_api_unavailable", status)
        return delete(resource, name, **preconditions)

    row = volume(destroy)
    destroy.cluster.deferred_deletions.add(("persistentvolumeclaims", row["name"]))
    monkeypatch.setattr(destroy.cluster, "delete", fail)
    destroy.manager().execute(destroy.operation["operation_id"])
    held(destroy)
    assert len(calls) == 1
    assert destroy.platform.operation(destroy.operation["operation_id"])["failure"]["reason"] == "execution_failed"


def test_volume_cleanup_still_uses_destroy_authority_and_preserves_creator(destroy, monkeypatch):
    """F059 AC-35, AC-50: a retained PVC is not reassigned to its cleanup caller."""
    original = copy.deepcopy(volume(destroy))
    observed, authority = destroy.platform.observe_resource, []

    def observe(reference, document):
        if reference == original["resource_ref"] and document["action"] == "stop":
            assert document["operation_id"] == destroy.operation["operation_id"] != original["operation_id"]
            authority.append(document["operation_id"])
            result = observed(reference, document)
            destroy.platform.rows[reference]["stop_evidence"] = {"cleanup_operation_id": document["operation_id"]}
            return result
        return observed(reference, document)

    monkeypatch.setattr(destroy.platform, "observe_resource", observe)
    destroy.manager().execute(destroy.operation["operation_id"])
    closed(destroy)
    assert authority == [destroy.operation["operation_id"]]
    assert volume(destroy)["operation_id"] == original["operation_id"]
    assert volume(destroy)["stop_evidence"] == {"cleanup_operation_id": destroy.operation["operation_id"]}

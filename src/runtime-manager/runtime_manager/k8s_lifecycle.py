"""UID-scoped stop evidence. Unknown writers are never released on timeout."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from runtime_manager.k8s_client import KubernetesAPIError
from runtime_manager.k8s_templates import POLICY_ANNOTATION, STOP_FINALIZER


@dataclass(frozen=True)
class StopIdentity:
    namespace: str
    name: str
    uid: str
    policy_revision: str
    protected_since_creation: bool
    binding_policy_verified: bool
    last_node_name: str = ""


@dataclass(frozen=True)
class StopObservation:
    kind: str = "unknown"
    reason: str = "writer_stop_unconfirmed"
    evidence: dict = field(default_factory=dict)

    @property
    def confirmed(self) -> bool:
        return self.kind in {"never_scheduled", "kubelet_terminal"}


def _same(pod, identity):
    meta = pod.get("metadata", {})
    return bool(identity.uid) and (meta.get("namespace"), meta.get("name"), meta.get("uid")) == (
        identity.namespace,
        identity.name,
        identity.uid,
    )


def classify_stop(pod: dict, identity: StopIdentity, *, now: datetime, fresh: bool = False) -> StopObservation:
    if not fresh or not _same(pod, identity):
        return StopObservation(reason="stop_identity_or_freshness_unconfirmed")
    meta, spec, status = pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {})
    if not isinstance(spec, dict) or not isinstance(status, dict):
        return StopObservation(reason="stop_object_invalid")
    deleting, version = meta.get("deletionTimestamp"), meta.get("resourceVersion")
    if not deleting or not version or version == "0" or STOP_FINALIZER not in meta.get("finalizers", []):
        return StopObservation(reason="stop_protection_or_deletion_unconfirmed")
    try:
        deleted_at = datetime.fromisoformat(deleting.replace("Z", "+00:00"))
        if deleted_at.tzinfo is None or now.tzinfo is None or deleted_at > now:
            return StopObservation(reason="stop_deletion_time_invalid")
    except (TypeError, ValueError, AttributeError):
        return StopObservation(reason="stop_deletion_time_invalid")
    node = spec.get("nodeName", "")
    if identity.last_node_name and node != identity.last_node_name:
        return StopObservation(reason="stop_binding_changed")
    if not identity.policy_revision or meta.get("annotations", {}).get(POLICY_ANNOTATION) != identity.policy_revision:
        return StopObservation(reason="stop_policy_mismatch")
    states = []
    for key in ("initContainerStatuses", "containerStatuses", "ephemeralContainerStatuses"):
        rows = status.get(key, [])
        if not isinstance(rows, list):
            return StopObservation(reason="stop_container_status_invalid")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("state", {}), dict):
                return StopObservation(reason="stop_container_status_invalid")
            if "running" in row.get("state", {}):
                return StopObservation(reason="stop_container_still_running")
            # Exclude arbitrary kubelet messages from persisted evidence.
            states.append(
                {
                    "name": row.get("name"),
                    "container_id": row.get("containerID", ""),
                    "states": sorted(row.get("state", {})),
                    "exit_code": row.get("state", {}).get("terminated", {}).get("exitCode"),
                }
            )
    if status.get("reason") in {"NodeLost", "Unknown"} or status.get("phase") == "Unknown":
        return StopObservation(reason="stop_node_unknown")
    if not node:
        if not identity.binding_policy_verified or states:
            return StopObservation(reason="stop_unscheduled_unconfirmed")
        kind = "never_scheduled"
    elif status.get("phase") in {"Succeeded", "Failed"} and identity.protected_since_creation:
        kind = "kubelet_terminal"
    else:
        return StopObservation()
    digest = hashlib.sha256(
        json.dumps(
            {"phase": status.get("phase"), "reason": status.get("reason"), "containers": states},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    return StopObservation(
        kind=kind,
        reason="stopped",
        evidence={
            "evidence_kind": kind,
            "namespace": identity.namespace,
            "name": identity.name,
            "uid": identity.uid,
            "resource_version": version,
            "node_name": node,
            "deletion_timestamp": deleting,
            "status_digest": digest,
            "policy_revision": identity.policy_revision,
            "observed_at": now.isoformat(),
        },
    )


def observe_stop(client, identity: StopIdentity, *, now: datetime | None = None) -> StopObservation:
    try:
        pod = client.get("pods", identity.name)
    except KubernetesAPIError:
        return StopObservation(reason="stop_api_unconfirmed")
    return classify_stop(pod, identity, now=now or datetime.now(UTC), fresh=True)


def request_stop(client, identity: StopIdentity, *, grace_seconds: int = 30) -> StopObservation:
    try:
        pod = client.get("pods", identity.name)
    except KubernetesAPIError:
        return StopObservation(reason="stop_api_unconfirmed")
    if not _same(pod, identity):
        return StopObservation(reason="stop_identity_unconfirmed")
    if not pod["metadata"].get("deletionTimestamp"):
        client.delete(
            "pods",
            identity.name,
            uid=identity.uid,
            resource_version=pod["metadata"].get("resourceVersion", ""),
            grace_seconds=grace_seconds,
        )
    return StopObservation(reason="stop_requested")


def finish_stop(
    client, identity: StopIdentity, commit: Callable[[dict], dict], *, now: datetime | None = None
) -> StopObservation:
    observation = observe_stop(client, identity, now=now)
    if not observation.confirmed:
        return observation
    receipt = commit(observation.evidence)
    if not isinstance(receipt, dict) or receipt.get("uid") != identity.uid or receipt.get("stop_state") != "confirmed":
        raise RuntimeError("stop_receipt_unconfirmed")
    try:
        pod = client.get("pods", identity.name)
    except KubernetesAPIError as exc:
        # A committed same-UID stop remains valid even if finalizer removal already completed.
        if exc.status_code == 404:
            return observation
        raise
    if not _same(pod, identity):
        return StopObservation(reason="stop_replacement_detected")
    finalizers = pod["metadata"].get("finalizers", [])
    if STOP_FINALIZER in finalizers:
        client.patch(
            "pods",
            identity.name,
            {"metadata": {"finalizers": [x for x in finalizers if x != STOP_FINALIZER]}},
            resource_version=pod["metadata"].get("resourceVersion", ""),
        )
    return observation

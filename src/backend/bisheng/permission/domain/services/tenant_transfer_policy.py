"""Re-key existing Grants during a business-verified tenant transfer; never add sources."""

import json
from hashlib import sha256

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.openfga.authorization_model_f048 import TECHNICAL_MARKER_SUBJECTS
from bisheng.permission.domain.services.projection_effects import stable_grant_key
from bisheng.permission.domain.services.projection_plan import (
    ProjectionPlan,
    ProjectionTupleDelta,
    normalize_projection_plan,
)


def checksum(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def blocked(reason):
    raise PermissionPublishNotReadyError(msg="Tenant resource migration: " + reason)


def operation_prefix(source, destination):
    if (
        type(source) is not int
        or type(destination) is not int
        or min(source, destination) <= 0
        or source == destination
    ):
        blocked("invalid tenant scope")
    return f"tenant-resource-transfer:{source}:{destination}:"


def compile_transfer(snapshot, *, source, destination, pin, operator_id):
    mode = snapshot["mode"]
    kind, ident = mode["resource_type"], mode["resource_id"]
    if mode["tenant_id"] != source or mode["projection_state"] != "CURRENT" or operator_id <= 0:
        blocked("source mode is not CURRENT")
    grants, assignees = snapshot["grants"], snapshot["assignees"]
    by_grant = {row["id"]: row for row in grants}
    if any(
        row["tenant_id"] != source or row["projection_state"] != "CURRENT" or row["state"] not in {"ACTIVE", "INACTIVE"}
        for row in grants
    ):
        blocked("unsettled Grant")
    if any(
        row["tenant_id"] != source or row["grant_id"] not in by_grant or row["state"] not in {"ACTIVE", "INACTIVE"}
        for row in assignees
    ):
        blocked("unsettled authorization source")
    if any(row["tenant_id"] != source or row["state"] not in {"ACTIVE", "RETIRED"} for row in snapshot["visible"]):
        blocked("unsettled visibility source")
    stage, commit = [], []
    object_key = f"{kind}:{ident}"
    for subject in TECHNICAL_MARKER_SUBJECTS:
        stage.append(("DELETE", subject, "permission_enabled", object_key))
    for grant in grants:
        rows = [row for row in assignees if row["grant_id"] == grant["id"] and row["state"] == "ACTIVE"]
        if grant["state"] != "ACTIVE":
            if rows:
                blocked("inactive Grant has active sources")
            continue
        if not rows:
            blocked("active Grant has no source")
        old, new = (
            "permission_grant:"
            + stable_grant_key(tenant_id=tenant, resource_type=kind, resource_id=ident, model_key=grant["model_key"])
            for tenant in (source, destination)
        )
        for node, action in ((old, "DELETE"), (new, "WRITE")):
            stage.append((action, "permission_model:" + grant["model_key"], "model", node))
            for subject, protected in sorted({(row["projected_subject"], row["protected"]) for row in rows}):
                stage.append((action, subject, "protected_assignee" if protected else "ordinary_assignee", node))
        commit.extend((("DELETE", old, "grant", object_key), ("WRITE", new, "grant", object_key)))
    for subject in TECHNICAL_MARKER_SUBJECTS:
        commit.append(("WRITE", subject, "permission_enabled", object_key))
    # Every source identity, owner, model, parent, public/shared predicate and visible
    # tuple stays intact. In particular tenant:child#member is not widened to Root.
    deltas = tuple(
        ProjectionTupleDelta(phase=phase, sequence=index, action=action, user=user, relation=relation, object=obj)
        for phase, rows in (("STAGE", stage), ("COMMIT", commit))
        for index, (action, user, relation, obj) in enumerate(dict.fromkeys(rows))
    )
    return normalize_projection_plan(
        ProjectionPlan(
            tenant_id=destination,
            idempotency_key=operation_prefix(source, destination) + f"{kind}:{ident}:{mode['version']}",
            operation_type="RESOURCE_TENANT_TRANSFER",
            scope_type="resource",
            scope_key=object_key,
            expected_version=mode["version"],
            target_version=mode["version"] + 1,
            store_id=pin["store_id"],
            model_id=pin["model_id"],
            operator_id=operator_id,
            change_item_count=1,
            deltas=deltas,
        )
    )

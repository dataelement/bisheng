"""Closed F048 mirror effects shared by native finalize and F118 preview.

These functions have no session, transport or business-object authority. The
caller must acquire the original resource/operation fence before applying them.
"""

from copy import deepcopy
from hashlib import sha256

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.domain.services.projection_plan import projection_state_expectations


def stable_grant_key(*, tenant_id, resource_type, resource_id, model_key):
    canonical = "|".join((str(tenant_id), resource_type, resource_id, model_key))
    return sha256(canonical.encode("utf-8")).hexdigest()[:32]


def terminal_graph_effect(deltas):
    expected = projection_state_expectations(deltas, after=True)
    return (
        frozenset(key for key, present in expected.items() if present),
        frozenset(key for key, present in expected.items() if not present),
    )


def finalization_effect(plan, operation_id, mirrors):
    """Return the exact native SQL AFTER, retaining unrelated scope history."""
    result = deepcopy(mirrors)
    modes = result.get("resource_permission_mode", ())
    kind, separator, ident = plan.scope_key.partition(":")
    if plan.scope_type != "resource" or not separator or len(modes) != 1:
        raise PermissionPublishNotReadyError(msg="Projection finalizer requires one original resource fence")
    mode = modes[0]
    if (
        mode["tenant_id"] != plan.tenant_id
        or (mode["resource_type"], mode["resource_id"]) != (kind, ident)
        or mode["operation_id"] != operation_id
    ):
        raise PermissionPublishNotReadyError(msg="Permission scope operation changed before projection finalize")
    if mode["version"] == plan.target_version and mode["projection_state"] == "CURRENT":
        return result
    if mode["version"] != plan.expected_version or mode["projection_state"] not in {"PROJECTING", "FAILED_CLOSED"}:
        raise PermissionPublishNotReadyError(msg="Permission scope changed before projection finalize")

    original_keys = {
        endpoint.partition("#")[0].removeprefix("permission_grant:")
        for delta in plan.deltas
        for endpoint in (delta.user, delta.object)
        if endpoint.startswith("permission_grant:")
    }
    grants = {row["id"]: row for row in result.get("permission_grant", ())}
    selected = {
        row["id"]
        for row in grants.values()
        if row["projection_state"] in {"PROJECTING", "FAILED_CLOSED"}
        and (
            row["projection_state"] == "PROJECTING"
            or stable_grant_key(
                tenant_id=plan.tenant_id, resource_type=kind, resource_id=ident, model_key=row["model_key"]
            )
            in original_keys
        )
    }
    assignees = {row["id"]: row for row in result.get("permission_grant_assignee", ())}
    for row in assignees.values():
        if row["grant_id"] not in selected:
            continue
        if row["state"] == "PENDING":
            row["state"] = "ACTIVE"
        elif row["state"] == "PENDING_DELETE":
            row["state"], row["version"] = "INACTIVE", row["version"] + 1
    for ident in selected:
        row = grants[ident]
        if row["state"] == "PENDING":
            row["state"] = "ACTIVE"
        row["projection_state"] = "CURRENT"

    for source in result.get("permission_visible_source_projection", ()):
        if source["operation_id"] != operation_id or source["state"] != "PENDING":
            continue
        prefix = "grant_assignee:"
        if source["source_kind"] != "GRANT_ASSIGNEE" or not source["source_owner_key"].startswith(prefix):
            raise PermissionPublishNotReadyError(msg="Visible source recovery cannot infer its canonical owner state")
        try:
            owner_id = int(source["source_owner_key"].removeprefix(prefix))
        except ValueError as error:
            raise PermissionPublishNotReadyError(msg="Visible source recovery owner identity is invalid") from error
        assignee = assignees.get(owner_id)
        grant = grants.get(assignee["grant_id"]) if assignee else None
        if not assignee or not grant:
            raise PermissionPublishNotReadyError(msg="Visible source recovery canonical owner is missing")
        if assignee["state"] not in {"ACTIVE", "INACTIVE"} or grant["state"] not in {"ACTIVE", "INACTIVE"}:
            raise PermissionPublishNotReadyError(msg="Visible source recovery owner state is incomplete")
        if (grant["resource_type"], grant["resource_id"]) != (source["resource_type"], source["resource_id"]):
            raise PermissionPublishNotReadyError(msg="Visible source recovery owner resource is inconsistent")
        if assignee["state"] == "ACTIVE" and grant["state"] != "ACTIVE":
            raise PermissionPublishNotReadyError(msg="Visible source recovery active assignee has no active Grant")
        current = (
            assignee["state"] == grant["state"] == "ACTIVE"
            and grant["model_key"] == source["model_key"]
            and assignee["version"] == source["source_version"]
            and assignee["source_locator"] == source["source_locator"]
            and assignee["source_fingerprint"] == source["source_fingerprint"]
            and assignee["projected_subject"] == source["projected_subject"]
            and ("protected" if assignee["protected"] else "ordinary") == source["visibility_class"]
        )
        source["state"] = "ACTIVE" if current else "RETIRED"

    targets = {
        delta.relation.removesuffix("_mode").upper()
        for delta in plan.deltas
        if delta.action == "WRITE" and delta.relation in {"custom_mode", "inherit_mode"}
    }
    if len(targets) > 1:
        raise PermissionPublishNotReadyError(msg="Projection writes more than one resource permission mode")
    mode.update(version=plan.target_version, projection_state="CURRENT")
    if targets:
        mode["mode"] = next(iter(targets))
    return result

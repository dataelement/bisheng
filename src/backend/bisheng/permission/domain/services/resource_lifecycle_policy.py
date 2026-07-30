"""Pure F048 resource lifecycle projection-plan compiler."""

from __future__ import annotations

from dataclasses import replace

from bisheng.common.errcode.permission import InvalidPermissionModeError
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_service import (
    ProjectionPlan,
    ProjectionTupleDelta,
)

FLEXIBLE_MODE_TYPES = frozenset({"folder", "knowledge_file"})
FIXED_CUSTOM_TYPES = frozenset(
    {
        "knowledge_space",
        "knowledge_library",
        "workflow",
        "assistant",
        "tool",
        "channel",
        "dashboard",
        "linsight_skill",
    }
)


def default_permission_mode(resource_type: str, *, has_parent: bool) -> str:
    if resource_type in FLEXIBLE_MODE_TYPES:
        if not has_parent:
            raise InvalidPermissionModeError(msg=f"{resource_type} requires a canonical parent")
        return "INHERIT"
    if resource_type in FIXED_CUSTOM_TYPES:
        return "CUSTOM"
    raise InvalidPermissionModeError(msg=f"Unsupported permission-mode resource: {resource_type}")


def copy_permission_mode(source_mode: str) -> tuple[str, bool]:
    normalized = source_mode.upper()
    if normalized == "INHERIT":
        return "INHERIT", False
    if normalized == "CUSTOM":
        return "CUSTOM", True
    raise InvalidPermissionModeError(msg=f"Invalid copy mode: {source_mode}")


def _enabled_delta(
    target: VerifiedPermissionTarget,
    *,
    action: str,
    phase: str,
    sequence: int,
) -> ProjectionTupleDelta:
    return ProjectionTupleDelta(
        phase=phase,
        sequence=sequence,
        action=action,
        user="user:*",
        relation="permission_enabled",
        object=f"{target.resource_type}:{target.resource_id}",
    )


def _lifecycle_plan(
    target: VerifiedPermissionTarget,
    *,
    operation_type: str,
    deltas: tuple[ProjectionTupleDelta, ...],
    store_id: str,
    model_id: str,
    operator_id: int,
    idempotency_key: str,
    expected_version: int | None = None,
    target_version: int | None = None,
) -> ProjectionPlan:
    return ProjectionPlan(
        tenant_id=target.tenant_id,
        idempotency_key=idempotency_key,
        operation_type=operation_type,
        scope_type="resource",
        scope_key=f"{target.resource_type}:{target.resource_id}",
        expected_version=(target.resource_version if expected_version is None else expected_version),
        target_version=(target.resource_version + 1 if target_version is None else target_version),
        store_id=store_id,
        model_id=model_id,
        operator_id=operator_id,
        change_item_count=1,
        deltas=deltas,
    )


def build_create_plan(
    target: VerifiedPermissionTarget,
    *,
    store_id: str,
    model_id: str,
    operator_id: int,
    idempotency_key: str,
    protected_deltas: tuple[ProjectionTupleDelta, ...],
    permission_mode: str | None = None,
    operation_type: str = "RESOURCE_CREATE",
) -> ProjectionPlan:
    default_mode = default_permission_mode(
        target.resource_type,
        has_parent=target.parent_type is not None,
    )
    mode = (permission_mode or default_mode).upper()
    if (
        mode not in {"INHERIT", "CUSTOM"}
        or (target.resource_type not in FLEXIBLE_MODE_TYPES and mode != default_mode)
        or (mode == "INHERIT" and (target.parent_type is None or target.parent_id is None))
    ):
        raise InvalidPermissionModeError(msg=f"Invalid initial mode for {target.resource_type}: {mode}")
    if operation_type not in {"RESOURCE_CREATE", "RESOURCE_COPY"}:
        raise ValueError("Unsupported resource create operation type")
    staging: list[ProjectionTupleDelta] = []
    if target.parent_type and target.parent_id:
        staging.append(
            ProjectionTupleDelta(
                phase="STAGE",
                sequence=0,
                action="WRITE",
                user=f"{target.parent_type}:{target.parent_id}",
                relation="parent",
                object=f"{target.resource_type}:{target.resource_id}",
            )
        )
    staging.append(
        ProjectionTupleDelta(
            phase="STAGE",
            sequence=len(staging),
            action="WRITE",
            user="user:*",
            relation=f"{mode.lower()}_mode",
            object=f"{target.resource_type}:{target.resource_id}",
        )
    )
    staging.extend(replace(delta, phase="STAGE") for delta in protected_deltas)
    enabled = _enabled_delta(
        target,
        action="WRITE",
        phase="COMMIT",
        sequence=len(staging),
    )
    return _lifecycle_plan(
        target,
        operation_type=operation_type,
        deltas=(*staging, enabled),
        store_id=store_id,
        model_id=model_id,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
        expected_version=0,
        target_version=1,
    )


def build_move_plan(
    target: VerifiedPermissionTarget,
    *,
    old_parent: tuple[str, str],
    new_parent: tuple[str, str],
    mode: str,
    store_id: str,
    model_id: str,
    operator_id: int,
    idempotency_key: str,
) -> ProjectionPlan:
    if mode.upper() not in {"INHERIT", "CUSTOM"}:
        raise InvalidPermissionModeError(msg="Invalid move permission mode")
    object_key = f"{target.resource_type}:{target.resource_id}"
    deltas = (
        _enabled_delta(
            target,
            action="DELETE",
            phase="STAGE",
            sequence=0,
        ),
        ProjectionTupleDelta(
            phase="COMMIT",
            sequence=1,
            action="DELETE",
            user=f"{old_parent[0]}:{old_parent[1]}",
            relation="parent",
            object=object_key,
        ),
        ProjectionTupleDelta(
            phase="COMMIT",
            sequence=2,
            action="WRITE",
            user=f"{new_parent[0]}:{new_parent[1]}",
            relation="parent",
            object=object_key,
        ),
        _enabled_delta(
            target,
            action="WRITE",
            phase="COMMIT",
            sequence=3,
        ),
    )
    return _lifecycle_plan(
        target,
        operation_type="RESOURCE_MOVE",
        deltas=deltas,
        store_id=store_id,
        model_id=model_id,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
    )


def build_delete_plan(
    target: VerifiedPermissionTarget,
    *,
    store_id: str,
    model_id: str,
    operator_id: int,
    idempotency_key: str,
) -> ProjectionPlan:
    return _lifecycle_plan(
        target,
        operation_type="RESOURCE_DELETE",
        deltas=(
            _enabled_delta(
                target,
                action="DELETE",
                phase="COMMIT",
                sequence=0,
            ),
        ),
        store_id=store_id,
        model_id=model_id,
        operator_id=operator_id,
        idempotency_key=idempotency_key,
    )

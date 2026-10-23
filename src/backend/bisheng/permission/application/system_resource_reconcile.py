"""Audit and project verified system-owned business resources.

Business composition roots provide the canonical resource predicates. This
module owns only the F048 state transition: missing resources are created
through ``authorize_system_owned`` so SQL mirrors, the durable projection
ledger, and OpenFGA tuples advance together. Existing preset tools are checked
against actual system tuples and repaired through the same projection ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from sqlmodel import col, select

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.permission.domain.models import ResourcePermissionMode
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor

SYSTEM_RESOURCE_BOOTSTRAP_OPERATOR_ID = 1


@dataclass(frozen=True, slots=True)
class SystemOwnedResourceSpec:
    tenant_id: int
    resource_type: str
    resource_id: str
    action_codes: tuple[str, ...]
    context_version: str

    @property
    def object_key(self) -> str:
        return f"{self.resource_type}:{self.resource_id}"


@dataclass(frozen=True, slots=True)
class SystemOwnedResourceState:
    resource: SystemOwnedResourceSpec
    state: str
    mode: str | None = None
    version: int | None = None
    projection_state: str | None = None
    operation_id: int | None = None
    missing_relations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SystemOwnedReconcileReport:
    mode: str
    before: tuple[SystemOwnedResourceState, ...]
    after: tuple[SystemOwnedResourceState, ...]

    @property
    def missing_count(self) -> int:
        return sum(item.state == "MISSING" for item in self.before)

    @property
    def blocked_count(self) -> int:
        return sum(item.state == "NON_CURRENT" for item in self.before)

    @property
    def incomplete_count(self) -> int:
        return sum(item.state == "MISSING_TUPLES" for item in self.before)

    @property
    def missing_tuple_count(self) -> int:
        return sum(len(item.missing_relations) for item in self.before)

    @property
    def current_count(self) -> int:
        return sum(item.state == "CURRENT" for item in self.after)


def _normalize_resources(
    resources: tuple[SystemOwnedResourceSpec, ...],
) -> tuple[SystemOwnedResourceSpec, ...]:
    by_key: dict[tuple[int, str, str], SystemOwnedResourceSpec] = {}
    for resource in resources:
        if (
            resource.tenant_id <= 0
            or not resource.resource_type
            or not resource.resource_id
            or not resource.action_codes
            or not resource.context_version
        ):
            raise ValueError("system-owned resource specification is incomplete")
        key = (resource.tenant_id, resource.resource_type, resource.resource_id)
        existing = by_key.get(key)
        if existing is not None and existing != resource:
            raise ValueError(f"conflicting system-owned resource specification: {resource.object_key}")
        by_key[key] = resource
    return tuple(by_key[key] for key in sorted(by_key))


async def inspect_system_owned_resources(
    resources: tuple[SystemOwnedResourceSpec, ...],
) -> tuple[SystemOwnedResourceState, ...]:
    normalized = _normalize_resources(resources)
    if not normalized:
        return ()
    tenant_ids = tuple(dict.fromkeys(item.tenant_id for item in normalized))
    resource_types = tuple(dict.fromkeys(item.resource_type for item in normalized))
    resource_ids = tuple(dict.fromkeys(item.resource_id for item in normalized))
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(ResourcePermissionMode).where(
                        col(ResourcePermissionMode.tenant_id).in_(tenant_ids),
                        col(ResourcePermissionMode.resource_type).in_(resource_types),
                        col(ResourcePermissionMode.resource_id).in_(resource_ids),
                    )
                )
            ).all()
    row_map = {(int(row.tenant_id or 0), row.resource_type, row.resource_id): row for row in rows}
    states: list[SystemOwnedResourceState] = []
    for resource in normalized:
        row = row_map.get((resource.tenant_id, resource.resource_type, resource.resource_id))
        if row is None:
            states.append(SystemOwnedResourceState(resource=resource, state="MISSING"))
            continue
        states.append(
            SystemOwnedResourceState(
                resource=resource,
                state="CURRENT" if row.projection_state == "CURRENT" else "NON_CURRENT",
                mode=row.mode,
                version=int(row.version),
                projection_state=row.projection_state,
                operation_id=int(row.operation_id) if row.operation_id is not None else None,
            )
        )
    return tuple(states)


def _verified_target(item: SystemOwnedResourceState) -> VerifiedPermissionTarget:
    resource = item.resource
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=resource.tenant_id,
        resource_type=resource.resource_type,
        resource_id=resource.resource_id,
        resource_version=item.version if item.version is not None else 0,
        context_version=resource.context_version,
    )


async def _inspect_system_tuples(
    runtime, states: tuple[SystemOwnedResourceState, ...]
) -> tuple[SystemOwnedResourceState, ...]:
    result: list[SystemOwnedResourceState] = []
    for item in states:
        if item.state == "CURRENT":
            with tenant_execution_scope(item.resource.tenant_id):
                missing = await runtime.missing_system_owned_relations(
                    target=_verified_target(item),
                    action_codes=item.resource.action_codes,
                )
            item = replace(item, state="MISSING_TUPLES" if missing else "CURRENT", missing_relations=missing)
        result.append(item)
    return tuple(result)


async def reconcile_system_owned_resources(
    runtime,
    resources: tuple[SystemOwnedResourceSpec, ...],
    *,
    apply: bool,
    operator_id: int,
) -> SystemOwnedReconcileReport:
    """Create absent projections and repair missing system tuples on CURRENT tools."""

    if operator_id <= 0:
        raise ValueError("operator_id must be positive")
    normalized = _normalize_resources(resources)
    before = await inspect_system_owned_resources(normalized)
    blocked = tuple(item for item in before if item.state == "NON_CURRENT")
    if blocked:
        scopes = ", ".join(item.resource.object_key for item in blocked)
        raise PermissionPublishNotReadyError(msg=f"System-owned resources have non-current projection state: {scopes}")
    before = await _inspect_system_tuples(runtime, before)
    if apply:
        for item in before:
            if item.state not in {"MISSING", "MISSING_TUPLES"}:
                continue
            resource = item.resource
            with tenant_execution_scope(resource.tenant_id):
                actor = PermissionActor(
                    user_id=operator_id,
                    current_tenant_id=resource.tenant_id,
                )
                if item.state == "MISSING":
                    await runtime.authorize_system_owned(
                        actor=actor,
                        target=_verified_target(item),
                        action_codes=resource.action_codes,
                        idempotency_key=(
                            f"f048:system-bootstrap:{resource.tenant_id}:{resource.resource_type}:{resource.resource_id}"
                        ),
                    )
                else:
                    await runtime.repair_system_owned(
                        actor=actor,
                        target=_verified_target(item),
                        action_codes=resource.action_codes,
                    )
    after = await _inspect_system_tuples(runtime, await inspect_system_owned_resources(normalized)) if apply else before
    if apply and any(item.state != "CURRENT" for item in after):
        scopes = ", ".join(item.resource.object_key for item in after if item.state != "CURRENT")
        raise PermissionPublishNotReadyError(msg=f"System-owned resource projection did not finalize: {scopes}")
    return SystemOwnedReconcileReport(
        mode="apply" if apply else "dry-run",
        before=before,
        after=after,
    )

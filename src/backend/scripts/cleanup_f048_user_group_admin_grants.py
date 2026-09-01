#!/usr/bin/env python3
"""Audit or revoke F048 resource Grants assigned to user-group administrators.

This maintenance command removes only active resource Grant sources whose
canonical subject is ``user_group:<group-id>#admin``. It does not change group
membership, administrator membership, ordinary ``#member`` Grants, protected
creator Grants, or unrelated resource assignments.

Run from ``src/backend/`` with the same ``config`` value as the live service::

    export config=config.yaml
    PYTHONPATH=./ .venv/bin/python \
      scripts/cleanup_f048_user_group_admin_grants.py \
      --tenant-id 1 --user-group-id 2

Dry-run is the default. Apply requires the Store, model, and plan checksum
printed by the immediately preceding dry-run. The default apply mode requires
a maintenance window::

    PYTHONPATH=./ .venv/bin/python \
      scripts/cleanup_f048_user_group_admin_grants.py \
      --tenant-id 1 --user-group-id 2 --apply \
      --operator-id 7 \
      --confirm-store-id <store-id> \
      --confirm-model-id <model-id> \
      --confirm-plan-checksum <plan-checksum>

When the product cannot be stopped, ``--online`` allows a serialized, throttled
apply while F048 runtimes are active. Use it only after confirming that no new
matching user-group administrator Grants can be created during cleanup::

    PYTHONPATH=./ .venv/bin/python \
      scripts/cleanup_f048_user_group_admin_grants.py \
      --tenant-id 1 --user-group-id 2 --apply --online \
      --delay-ms 100 --operator-id 7 \
      --confirm-store-id <store-id> \
      --confirm-model-id <model-id> \
      --confirm-plan-checksum <plan-checksum>

Each resource is changed through the normal F048 Grant/projection service, so
SQL Grant state, the durable projection ledger, flattened ``visible`` sources,
and OpenFGA tuples converge together. Maintenance apply refuses active F048
runtimes or in-flight projection operations. Online apply relies on the same
per-resource version/source checks and stops on a concurrent change. Use
``--after-assignee-id`` and ``--max-resources`` to run reviewed, resumable
batches.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger  # noqa: E402
from sqlalchemy import func  # noqa: E402
from sqlmodel import col, select  # noqa: E402

from bisheng.api.services.f048_permission_runtime import (  # noqa: E402
    build_f048_resource_composition,
)
from bisheng.common.errcode.permission import PermissionInvalidResourceError  # noqa: E402
from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import (  # noqa: E402
    app_context,
    close_app_context,
    initialize_app_context,
)
from bisheng.core.context.tenant import (  # noqa: E402
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.core.openfga.runtime_heartbeat import (  # noqa: E402
    list_runtime_heartbeats,
)
from bisheng.database.models.group import Group  # noqa: E402
from bisheng.department.domain.services.department_projection_scope import (  # noqa: E402
    get_department_projection_scope,
)
from bisheng.permission.application.control_state import (  # noqa: E402
    SqlPermissionControlState,
)
from bisheng.permission.application.runtime import (  # noqa: E402
    F048PermissionRuntime,
    build_f048_permission_runtime,
)
from bisheng.permission.domain.models import (  # noqa: E402
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionProjectionOperation,
    ResourcePermissionMode,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget  # noqa: E402
from bisheng.permission.domain.services.grant_service import (  # noqa: E402
    CanonicalGrantChange,
)
from bisheng.permission.domain.services.permission_action_service import (  # noqa: E402
    PermissionActor,
)

EXIT_OK = 0
EXIT_BLOCKED = 3
EXIT_RUNTIME_ERROR = 4
ACTIVE_OPERATION_STATUSES = ("PREPARED", "STAGING", "COMMIT_UNKNOWN", "COMMITTED")
CLEANUP_CHANGE_BATCH_SIZE = 40
MAX_REVIEWED_RESOURCES = 50_000
SUPPORTED_RESOURCE_TYPES = frozenset(
    {
        "assistant",
        "channel",
        "dashboard",
        "folder",
        "knowledge_file",
        "knowledge_library",
        "knowledge_space",
        "tool",
        "workflow",
    }
)


class UserGroupAdminGrantCleanupBlockedError(RuntimeError):
    """A preflight, confirmation, or projection invariant blocked cleanup."""


@dataclass(frozen=True, slots=True)
class AdminGrantCandidate:
    assignee_id: int
    assignee_version: int
    grant_id: int
    grant_version: int
    resource_type: str
    resource_id: str
    model_key: str
    source_type: str
    source_ref: str
    source_locator: str
    source_fingerprint: str
    projected_subject: str
    protected: bool
    grant_state: str
    grant_projection_state: str
    resource_mode: str
    resource_version: int
    resource_projection_state: str
    resource_parent_type: str | None
    resource_parent_id: str | None


@dataclass(frozen=True, slots=True)
class ResourceCleanupPlan:
    resource_type: str
    resource_id: str
    first_assignee_id: int
    candidates: tuple[AdminGrantCandidate, ...]


@dataclass(frozen=True, slots=True)
class CleanupInventory:
    group_name: str
    matching_state_counts: dict[str, int]
    active_candidate_resource_count: int
    active_candidate_assignee_count: int
    active_resource_type_counts: dict[str, int]
    active_model_counts: dict[str, int]
    active_source_type_counts: dict[str, int]
    selected: tuple[ResourceCleanupPlan, ...]
    selected_assignee_count: int
    remaining_resource_count: int
    resume_after_assignee_id: int | None
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CleanupRuntime:
    client: Any
    permission: F048PermissionRuntime
    resources: Any
    adapters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ExecutionPreflight:
    active_operation_count: int
    active_heartbeat_count: int


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must not be negative")
    return parsed


def _resource_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_RESOURCE_TYPES:
        supported = ", ".join(sorted(SUPPORTED_RESOURCE_TYPES))
        raise argparse.ArgumentTypeError(f"unsupported resource type; choose one of: {supported}")
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--tenant-id", type=_positive_int, required=True)
    parser.add_argument("--user-group-id", type=_positive_int, required=True)
    parser.add_argument(
        "--resource-type",
        action="append",
        type=_resource_type,
        default=[],
        help="Limit cleanup to a resource type; repeatable (default: all supported types)",
    )
    parser.add_argument(
        "--after-assignee-id",
        type=_non_negative_int,
        default=0,
        help="Resume after the first assignee ID of the last completed resource",
    )
    parser.add_argument(
        "--max-resources",
        type=_positive_int,
        default=100,
        help=(
            "Maximum resources in this checksum-bound batch "
            f"(default: 100, maximum: {MAX_REVIEWED_RESOURCES})"
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress DEBUG/INFO runtime logs; JSON reports and failures remain visible",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--online",
        action="store_true",
        help=(
            "Allow apply while F048 runtimes are active; requires an operator "
            "guarantee that no new matching Grants can be created"
        ),
    )
    parser.add_argument(
        "--delay-ms",
        type=_non_negative_int,
        default=100,
        help="Delay between cleaned resources during online apply (default: 100 ms)",
    )
    parser.add_argument(
        "--allow-orphan-applications",
        action="store_true",
        help=(
            "Allow assistant/workflow cleanup only when the owning business loader "
            "confirms that the resource record no longer exists"
        ),
    )
    parser.add_argument(
        "--allow-unpublished-knowledge-containers",
        action="store_true",
        help=(
            "Allow knowledge space/library cleanup when the owning business loader "
            "confirms a valid record whose status is not PUBLISHED"
        ),
    )
    parser.add_argument(
        "--allow-orphan-knowledge-containers",
        action="store_true",
        help=(
            "Allow knowledge space/library cleanup only when the owning business "
            "loader confirms that the record no longer exists"
        ),
    )
    parser.add_argument(
        "--operator-id",
        type=_non_negative_int,
        default=0,
        help="Operator user ID recorded in projection operations; required with --apply",
    )
    parser.add_argument("--confirm-store-id")
    parser.add_argument("--confirm-model-id")
    parser.add_argument("--confirm-plan-checksum")
    args = parser.parse_args(argv)
    if args.max_resources > MAX_REVIEWED_RESOURCES:
        parser.error(f"--max-resources must not exceed {MAX_REVIEWED_RESOURCES}")
    if args.online and not args.apply:
        parser.error("--online requires --apply")
    args.resource_type = tuple(dict.fromkeys(args.resource_type))
    if args.apply:
        missing = [
            flag
            for flag, value in (
                ("--operator-id", args.operator_id),
                ("--confirm-store-id", args.confirm_store_id),
                ("--confirm-model-id", args.confirm_model_id),
                ("--confirm-plan-checksum", args.confirm_plan_checksum),
            )
            if not value
        ]
        if missing:
            parser.error(f"--apply requires {', '.join(missing)}")
    return args


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise UserGroupAdminGrantCleanupBlockedError(message)


def _checksum(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _candidate_payload(candidate: AdminGrantCandidate) -> dict[str, Any]:
    return asdict(candidate)


def _plan_checksum(
    *,
    args: argparse.Namespace,
    store_id: str,
    model_id: str,
    catalog_release_id: int,
    selected: tuple[ResourceCleanupPlan, ...],
) -> str:
    return _checksum(
        {
            "tenant_id": args.tenant_id,
            "user_group_id": args.user_group_id,
            "resource_types": list(args.resource_type),
            "after_assignee_id": args.after_assignee_id,
            "max_resources": args.max_resources,
            "allow_orphan_applications": args.allow_orphan_applications,
            "allow_unpublished_knowledge_containers": args.allow_unpublished_knowledge_containers,
            "allow_orphan_knowledge_containers": args.allow_orphan_knowledge_containers,
            "store_id": store_id,
            "model_id": model_id,
            "catalog_release_id": catalog_release_id,
            "resources": [
                {
                    "resource_type": item.resource_type,
                    "resource_id": item.resource_id,
                    "first_assignee_id": item.first_assignee_id,
                    "candidates": [_candidate_payload(row) for row in item.candidates],
                }
                for item in selected
            ],
        }
    )


def _candidate_blockers(candidate: AdminGrantCandidate) -> tuple[str, ...]:
    prefix = f"{candidate.resource_type}:{candidate.resource_id}:assignee:{candidate.assignee_id}"
    blockers: list[str] = []
    if candidate.protected:
        blockers.append(f"{prefix}:protected")
    if candidate.grant_state != "ACTIVE":
        blockers.append(f"{prefix}:grant_state={candidate.grant_state}")
    if candidate.grant_projection_state != "CURRENT":
        blockers.append(f"{prefix}:grant_projection_state={candidate.grant_projection_state}")
    if candidate.resource_mode != "CUSTOM":
        blockers.append(f"{prefix}:resource_mode={candidate.resource_mode}")
    if candidate.resource_projection_state != "CURRENT":
        blockers.append(f"{prefix}:resource_projection_state={candidate.resource_projection_state}")
    return tuple(blockers)


def _select_resource_batch(
    candidates: tuple[AdminGrantCandidate, ...],
    *,
    after_assignee_id: int,
    max_resources: int,
) -> tuple[tuple[ResourceCleanupPlan, ...], int]:
    grouped: dict[tuple[str, str], list[AdminGrantCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.resource_type, candidate.resource_id), []).append(candidate)
    plans = tuple(
        sorted(
            (
                ResourceCleanupPlan(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    first_assignee_id=min(row.assignee_id for row in rows),
                    candidates=tuple(sorted(rows, key=lambda row: row.assignee_id)),
                )
                for (resource_type, resource_id), rows in grouped.items()
            ),
            key=lambda row: (row.first_assignee_id, row.resource_type, row.resource_id),
        )
    )
    remaining = tuple(row for row in plans if row.first_assignee_id > after_assignee_id)
    selected = remaining[:max_resources]
    return selected, max(0, len(remaining) - len(selected))


async def _build_runtime(client: Any) -> CleanupRuntime:
    components = await build_f048_permission_runtime(
        client,
        external_scopes={
            "department": get_department_projection_scope(),
        },
    )
    adapters, resources = build_f048_resource_composition(components.facade)
    return CleanupRuntime(
        client=client,
        permission=components.facade,
        resources=resources,
        adapters=adapters,
    )


async def _load_group(*, tenant_id: int, user_group_id: int) -> Group:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            row = (
                await session.exec(
                    select(Group).where(
                        Group.id == user_group_id,
                        Group.tenant_id == tenant_id,
                    )
                )
            ).first()
    _require(row is not None, f"user group {user_group_id} does not exist in tenant {tenant_id}")
    return row


def _matching_assignee_predicates(*, user_group_id: int) -> tuple[Any, ...]:
    subject_id = str(user_group_id)
    return (
        PermissionGrantAssignee.subject_type == "user_group",
        PermissionGrantAssignee.subject_id == subject_id,
        PermissionGrantAssignee.userset_relation == "admin",
        PermissionGrantAssignee.projected_subject == f"user_group:{subject_id}#admin",
    )


async def _load_matching_state_counts(
    *,
    tenant_id: int,
    user_group_id: int,
    resource_types: tuple[str, ...],
) -> dict[str, int]:
    selected_types = resource_types or tuple(sorted(SUPPORTED_RESOURCE_TYPES))
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            statement = (
                select(
                    PermissionGrantAssignee.state,
                    PermissionGrant.state,
                    PermissionGrant.projection_state,
                    func.count(PermissionGrantAssignee.id),
                )
                .join(
                    PermissionGrant,
                    PermissionGrant.id == PermissionGrantAssignee.grant_id,
                )
                .where(
                    PermissionGrantAssignee.tenant_id == tenant_id,
                    PermissionGrant.tenant_id == tenant_id,
                    col(PermissionGrant.resource_type).in_(selected_types),
                    *_matching_assignee_predicates(user_group_id=user_group_id),
                )
                .group_by(
                    PermissionGrantAssignee.state,
                    PermissionGrant.state,
                    PermissionGrant.projection_state,
                )
            )
            # SQLModel returns SQL Row semantics for an explicit multi-column select.
            rows = (await session.exec(statement)).all()
    return {
        (f"assignee={assignee_state}|grant={grant_state}|grant_projection={grant_projection_state}"): int(count)
        for assignee_state, grant_state, grant_projection_state, count in rows
    }


def _state_matrix_blockers(state_counts: dict[str, int]) -> tuple[str, ...]:
    allowed_active = "assignee=ACTIVE|grant=ACTIVE|grant_projection=CURRENT"
    return tuple(
        f"matching_state:{state}:count={count}"
        for state, count in sorted(state_counts.items())
        if not state.startswith("assignee=INACTIVE|") and state != allowed_active
    )


async def _load_active_candidates(
    *,
    tenant_id: int,
    user_group_id: int,
    resource_types: tuple[str, ...],
) -> tuple[AdminGrantCandidate, ...]:
    selected_types = resource_types or tuple(sorted(SUPPORTED_RESOURCE_TYPES))
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            statement = (
                select(
                    PermissionGrantAssignee,
                    PermissionGrant,
                    ResourcePermissionMode,
                )
                .join(
                    PermissionGrant,
                    PermissionGrant.id == PermissionGrantAssignee.grant_id,
                )
                .outerjoin(
                    ResourcePermissionMode,
                    (ResourcePermissionMode.tenant_id == PermissionGrant.tenant_id)
                    & (ResourcePermissionMode.resource_type == PermissionGrant.resource_type)
                    & (ResourcePermissionMode.resource_id == PermissionGrant.resource_id),
                )
                .where(
                    PermissionGrantAssignee.tenant_id == tenant_id,
                    PermissionGrant.tenant_id == tenant_id,
                    col(PermissionGrant.resource_type).in_(selected_types),
                    PermissionGrantAssignee.state == "ACTIVE",
                    PermissionGrant.state == "ACTIVE",
                    *_matching_assignee_predicates(user_group_id=user_group_id),
                )
                .order_by(PermissionGrantAssignee.id)
            )
            # SQLModel returns SQL Row semantics for an explicit ORM tuple select.
            rows = (await session.exec(statement)).all()
    candidates: list[AdminGrantCandidate] = []
    for assignee, grant, mode in rows:
        _require(
            assignee.id is not None and grant.id is not None,
            "matching Grant source has an incomplete database identity",
        )
        candidates.append(
            AdminGrantCandidate(
                assignee_id=int(assignee.id),
                assignee_version=int(assignee.version),
                grant_id=int(grant.id),
                grant_version=int(grant.version),
                resource_type=str(grant.resource_type),
                resource_id=str(grant.resource_id),
                model_key=str(grant.model_key),
                source_type=str(assignee.source_type),
                source_ref=str(assignee.source_ref),
                source_locator=str(assignee.source_locator),
                source_fingerprint=str(assignee.source_fingerprint),
                projected_subject=str(assignee.projected_subject),
                protected=bool(assignee.protected),
                grant_state=str(grant.state),
                grant_projection_state=str(grant.projection_state),
                resource_mode=str(mode.mode) if mode is not None else "MISSING",
                resource_version=int(mode.version) if mode is not None else -1,
                resource_projection_state=(str(mode.projection_state) if mode is not None else "MISSING"),
                resource_parent_type=(str(mode.parent_type) if mode is not None and mode.parent_type else None),
                resource_parent_id=(str(mode.parent_id) if mode is not None and mode.parent_id else None),
            )
        )
    return tuple(candidates)


async def _load_inventory(
    args: argparse.Namespace,
) -> CleanupInventory:
    group = await _load_group(
        tenant_id=args.tenant_id,
        user_group_id=args.user_group_id,
    )
    state_counts = await _load_matching_state_counts(
        tenant_id=args.tenant_id,
        user_group_id=args.user_group_id,
        resource_types=args.resource_type,
    )
    candidates = await _load_active_candidates(
        tenant_id=args.tenant_id,
        user_group_id=args.user_group_id,
        resource_types=args.resource_type,
    )
    selected, remaining_count = _select_resource_batch(
        candidates,
        after_assignee_id=args.after_assignee_id,
        max_resources=args.max_resources,
    )
    blockers = _state_matrix_blockers(state_counts) + tuple(
        blocker
        for resource in selected
        for candidate in resource.candidates
        for blocker in _candidate_blockers(candidate)
    )
    return CleanupInventory(
        group_name=str(group.group_name),
        matching_state_counts=state_counts,
        active_candidate_resource_count=len({(row.resource_type, row.resource_id) for row in candidates}),
        active_candidate_assignee_count=len(candidates),
        active_resource_type_counts=dict(sorted(Counter(row.resource_type for row in candidates).items())),
        active_model_counts=dict(sorted(Counter(row.model_key for row in candidates).items())),
        active_source_type_counts=dict(sorted(Counter(row.source_type for row in candidates).items())),
        selected=selected,
        selected_assignee_count=sum(len(row.candidates) for row in selected),
        remaining_resource_count=remaining_count,
        resume_after_assignee_id=(selected[-1].first_assignee_id if selected else None),
        blockers=blockers,
    )


async def _assert_execution_window(*, apply: bool, online: bool) -> ExecutionPreflight:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            active_operations = int(
                (
                    await session.exec(
                        select(func.count(PermissionProjectionOperation.id)).where(
                            col(PermissionProjectionOperation.status).in_(ACTIVE_OPERATION_STATUSES)
                        )
                    )
                ).one()
            )
    heartbeats: tuple[Any, ...] = ()
    if apply:
        heartbeats = tuple(await list_runtime_heartbeats())
    if not online:
        _require(active_operations == 0, f"{active_operations} permission projection operations are active")
        _require(not heartbeats, f"{len(heartbeats)} F048 runtime heartbeats are still active")
    return ExecutionPreflight(
        active_operation_count=active_operations,
        active_heartbeat_count=len(heartbeats),
    )


def _report_payload(
    *,
    args: argparse.Namespace,
    store_id: str,
    model_id: str,
    catalog: Any,
    inventory: CleanupInventory,
    plan_checksum: str,
    preflight: ExecutionPreflight,
) -> dict[str, Any]:
    resource_type_counts = Counter(row.resource_type for row in inventory.selected)
    model_counts = Counter(candidate.model_key for resource in inventory.selected for candidate in resource.candidates)
    source_type_counts = Counter(
        candidate.source_type for resource in inventory.selected for candidate in resource.candidates
    )
    return {
        "event": "user_group_admin_grant_cleanup_plan",
        "mode": "apply" if args.apply else "dry-run",
        "execution_window": "online" if args.online else "maintenance",
        "delay_ms": args.delay_ms if args.online else 0,
        "allow_orphan_applications": args.allow_orphan_applications,
        "allow_unpublished_knowledge_containers": args.allow_unpublished_knowledge_containers,
        "allow_orphan_knowledge_containers": args.allow_orphan_knowledge_containers,
        "active_projection_operation_count": preflight.active_operation_count,
        "active_runtime_heartbeat_count": preflight.active_heartbeat_count,
        "tenant_id": args.tenant_id,
        "user_group_id": args.user_group_id,
        "user_group_name": inventory.group_name,
        "projected_subject": f"user_group:{args.user_group_id}#admin",
        "resource_types": list(args.resource_type) or sorted(SUPPORTED_RESOURCE_TYPES),
        "after_assignee_id": args.after_assignee_id,
        "max_resources": args.max_resources,
        "store_id": store_id,
        "model_id": model_id,
        "catalog_release_id": catalog.release_id,
        "catalog_checksum": catalog.checksum,
        "plan_checksum": plan_checksum,
        "matching_assignee_state_counts": inventory.matching_state_counts,
        "active_candidate_resource_count": inventory.active_candidate_resource_count,
        "active_candidate_assignee_count": inventory.active_candidate_assignee_count,
        "selected_resource_count": len(inventory.selected),
        "selected_assignee_count": inventory.selected_assignee_count,
        "remaining_resource_count_after_batch": inventory.remaining_resource_count,
        "resume_after_assignee_id": inventory.resume_after_assignee_id,
        "active_resource_type_counts": inventory.active_resource_type_counts,
        "active_model_counts": inventory.active_model_counts,
        "active_source_type_counts": inventory.active_source_type_counts,
        "selected_resource_type_counts": dict(sorted(resource_type_counts.items())),
        "selected_model_counts": dict(sorted(model_counts.items())),
        "selected_source_type_counts": dict(sorted(source_type_counts.items())),
        "selected_resources": [
            {
                "resource_type": resource.resource_type,
                "resource_id": resource.resource_id,
                "first_assignee_id": resource.first_assignee_id,
                "assignees": [
                    {
                        "assignee_id": candidate.assignee_id,
                        "assignee_version": candidate.assignee_version,
                        "model_key": candidate.model_key,
                        "source_type": candidate.source_type,
                    }
                    for candidate in resource.candidates
                ],
            }
            for resource in inventory.selected
        ],
        "blockers": list(inventory.blockers[:50]),
        "blocked_count": len(inventory.blockers),
    }


def _source_matches_candidate(
    source: Any,
    *,
    model_key: str,
    user_group_id: int,
    candidate: AdminGrantCandidate,
) -> bool:
    return (
        model_key == candidate.model_key
        and source.active
        and source.source_id == candidate.assignee_id
        and source.version == candidate.assignee_version
        and source.subject_type == "user_group"
        and source.subject_id == str(user_group_id)
        and source.userset_relation == "admin"
        and source.projected_subject == f"user_group:{user_group_id}#admin"
        and source.source_type == candidate.source_type
        and source.source_ref == candidate.source_ref
        and source.source_locator == candidate.source_locator
        and source.source_fingerprint == candidate.source_fingerprint
        and not source.protected
    )


async def _resolve_target(
    *,
    args: argparse.Namespace,
    runtime: CleanupRuntime,
    actor: PermissionActor,
    resource: ResourceCleanupPlan,
) -> VerifiedPermissionTarget:
    try:
        target = await runtime.resources.resolve(
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
            actor=actor,
            action="visible",
        )
    except PermissionInvalidResourceError:
        adapter = runtime.adapters[resource.resource_type]
        record = await adapter.load_permission_record(
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
        )
        if args.allow_orphan_applications and resource.resource_type in {"assistant", "workflow"}:
            _require(
                record is None,
                f"business resource still exists but is invalid: {resource.resource_type}:{resource.resource_id}",
            )
            versions = {row.resource_version for row in resource.candidates}
            parents = {(row.resource_parent_type, row.resource_parent_id) for row in resource.candidates}
            _require(len(versions) == 1 and len(parents) == 1, "orphan permission mirror is inconsistent")
            resource_version = versions.pop()
            parent_type, parent_id = parents.pop()
            target = VerifiedPermissionTarget.from_business_service(
                tenant_id=args.tenant_id,
                resource_type=resource.resource_type,
                resource_id=resource.resource_id,
                resource_version=resource_version,
                parent_type=parent_type,
                parent_id=parent_id,
                context_version=f"orphan-cleanup:{resource_version}",
            )
        elif resource.resource_type in {
            "knowledge_space",
            "knowledge_library",
        }:
            if record is None:
                _require(
                    args.allow_orphan_knowledge_containers,
                    "knowledge container business record is missing",
                )
                versions = {row.resource_version for row in resource.candidates}
                parents = {(row.resource_parent_type, row.resource_parent_id) for row in resource.candidates}
                _require(
                    len(versions) == 1 and len(parents) == 1,
                    "orphan knowledge permission mirror is inconsistent",
                )
                resource_version = versions.pop()
                parent_type, parent_id = parents.pop()
                target = VerifiedPermissionTarget.from_business_service(
                    tenant_id=args.tenant_id,
                    resource_type=resource.resource_type,
                    resource_id=resource.resource_id,
                    resource_version=resource_version,
                    parent_type=parent_type,
                    parent_id=parent_id,
                    context_version=f"orphan-cleanup:{resource_version}",
                )
            else:
                _require(
                    args.allow_unpublished_knowledge_containers,
                    "knowledge container business record is not published",
                )
                _require(record.status != "PUBLISHED", "published knowledge container was rejected unexpectedly")
                _require(
                    record.tenant_id == args.tenant_id
                    and record.resource_type == resource.resource_type
                    and record.resource_id == resource.resource_id,
                    "knowledge container business identity does not match the cleanup target",
                )
                versions = {row.resource_version for row in resource.candidates}
                _require(
                    versions == {record.permission_version},
                    "knowledge container business version does not match the permission mirror",
                )
                target = VerifiedPermissionTarget.from_business_service(
                    tenant_id=record.tenant_id,
                    resource_type=record.resource_type,
                    resource_id=record.resource_id,
                    resource_version=record.permission_version,
                    context_version=record.context_version,
                )
        else:
            raise UserGroupAdminGrantCleanupBlockedError(
                f"business resource is missing or invalid: {resource.resource_type}:{resource.resource_id}"
            )
    _require(target.tenant_id == actor.current_tenant_id, "business target resolved to another tenant")
    return target


async def _apply_resource(
    *,
    args: argparse.Namespace,
    runtime: CleanupRuntime,
    actor: PermissionActor,
    resource: ResourceCleanupPlan,
    plan_checksum: str,
) -> tuple[int, tuple[int, ...]]:
    pending = list(resource.candidates)
    operation_ids: list[int] = []
    removed_count = 0
    batch_index = 0
    while pending:
        target = await _resolve_target(args=args, runtime=runtime, actor=actor, resource=resource)
        context = await runtime.permission.build_grant_context(actor=actor, target=target)
        source_by_id = {
            source.source_id: (grant.model.model_key, source)
            for grant in context.grants
            for source in grant.sources
            if source.active
        }
        # One source removal can emit both an assignee tuple and a flattened
        # visible tuple. Keep the worst case below the 90-operation FGA reserve.
        batch = pending[:CLEANUP_CHANGE_BATCH_SIZE]
        for candidate in batch:
            matched = source_by_id.get(candidate.assignee_id)
            _require(
                matched is not None
                and _source_matches_candidate(
                    matched[1],
                    model_key=matched[0],
                    user_group_id=args.user_group_id,
                    candidate=candidate,
                ),
                (
                    f"candidate changed before apply: {resource.resource_type}:"
                    f"{resource.resource_id}:assignee:{candidate.assignee_id}"
                ),
            )
        idempotency_key = _checksum(
            {
                "operation": "cleanup_f048_user_group_admin_grants",
                "plan_checksum": plan_checksum,
                "resource_type": resource.resource_type,
                "resource_id": resource.resource_id,
                "batch_index": batch_index,
                "assignee_ids": [row.assignee_id for row in batch],
            }
        )
        result = await runtime.permission.mutate_grants(
            actor=actor,
            target=target,
            changes=tuple(
                CanonicalGrantChange(
                    operation="REMOVE",
                    assignee_id=row.assignee_id,
                    expected_assignee_version=row.assignee_version,
                )
                for row in batch
            ),
            expected_resource_version=target.resource_version,
            expected_catalog_release_id=context.current_catalog_release_id,
            idempotency_key=idempotency_key,
        )
        operation_ids.append(int(result.projection.operation_id))
        removed_count += len(batch)
        del pending[: len(batch)]
        batch_index += 1
    return removed_count, tuple(operation_ids)


async def _count_selected_active(
    *,
    tenant_id: int,
    user_group_id: int,
    selected: tuple[ResourceCleanupPlan, ...],
) -> int:
    if not selected:
        return 0
    keys = {(row.resource_type, row.resource_id) for row in selected}
    candidates = await _load_active_candidates(
        tenant_id=tenant_id,
        user_group_id=user_group_id,
        resource_types=tuple(sorted({row.resource_type for row in selected})),
    )
    return sum((row.resource_type, row.resource_id) in keys for row in candidates)


async def execute(args: argparse.Namespace) -> int:
    if args.apply:
        await initialize_app_context(config=settings)
    tenant_token = set_current_tenant_id(args.tenant_id)
    try:
        catalog = await SqlPermissionControlState().current_catalog()
        client = None
        if args.apply:
            client = await app_context.async_get_instance("openfga")
            _require(
                client.store_id == catalog.store_id and client.model_id == catalog.model_id,
                "runtime OpenFGA pin does not match the CURRENT permission Catalog",
            )
        preflight = await _assert_execution_window(apply=args.apply, online=args.online)
        inventory = await _load_inventory(args)
        plan_checksum = _plan_checksum(
            args=args,
            store_id=catalog.store_id,
            model_id=catalog.model_id,
            catalog_release_id=catalog.release_id,
            selected=inventory.selected,
        )
        print(
            json.dumps(
                _report_payload(
                    args=args,
                    store_id=catalog.store_id,
                    model_id=catalog.model_id,
                    catalog=catalog,
                    inventory=inventory,
                    plan_checksum=plan_checksum,
                    preflight=preflight,
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        if not args.apply:
            return EXIT_OK

        _require(client is not None, "OpenFGA runtime is unavailable for apply")
        _require(not inventory.blockers, "; ".join(inventory.blockers[:20]))
        _require(args.confirm_store_id == client.store_id, "Store confirmation does not match")
        _require(args.confirm_model_id == client.model_id, "model confirmation does not match")
        _require(args.confirm_plan_checksum == plan_checksum, "plan checksum confirmation does not match")
        if not inventory.selected:
            print(
                json.dumps(
                    {
                        "event": "user_group_admin_grant_cleanup_complete",
                        "removed_assignee_count": 0,
                        "removed_resource_count": 0,
                        "remaining_selected_active_count": 0,
                    },
                    sort_keys=True,
                )
            )
            return EXIT_OK

        runtime = await _build_runtime(client)
        actor = PermissionActor(
            user_id=args.operator_id,
            current_tenant_id=args.tenant_id,
            super_admin=True,
        )
        removed_assignee_count = 0
        operation_ids: list[int] = []
        for resource_index, resource in enumerate(inventory.selected):
            removed, resource_operation_ids = await _apply_resource(
                args=args,
                runtime=runtime,
                actor=actor,
                resource=resource,
                plan_checksum=plan_checksum,
            )
            removed_assignee_count += removed
            operation_ids.extend(resource_operation_ids)
            print(
                json.dumps(
                    {
                        "event": "user_group_admin_grant_resource_cleaned",
                        "resource_type": resource.resource_type,
                        "resource_id": resource.resource_id,
                        "first_assignee_id": resource.first_assignee_id,
                        "removed_assignee_count": removed,
                        "operation_ids": list(resource_operation_ids),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            if args.online and resource_index + 1 < len(inventory.selected) and args.delay_ms:
                await asyncio.sleep(args.delay_ms / 1000)

        remaining_selected = await _count_selected_active(
            tenant_id=args.tenant_id,
            user_group_id=args.user_group_id,
            selected=inventory.selected,
        )
        _require(remaining_selected == 0, f"{remaining_selected} selected active assignments remain")
        print(
            json.dumps(
                {
                    "event": "user_group_admin_grant_cleanup_complete",
                    "removed_assignee_count": removed_assignee_count,
                    "removed_resource_count": len(inventory.selected),
                    "operation_ids": operation_ids,
                    "remaining_selected_active_count": remaining_selected,
                    "remaining_resource_count_after_batch": inventory.remaining_resource_count,
                    "resume_after_assignee_id": inventory.resume_after_assignee_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return EXIT_OK
    finally:
        current_tenant_id.reset(tenant_token)
        if args.apply:
            await close_app_context()
        else:
            try:
                await app_context.get_context("database").async_close()
            except KeyError:
                # No database context exists when dry-run fails before its first query.
                pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.quiet:
        logger.remove()
        logger.add(sys.stderr, level="ERROR")
    try:
        return asyncio.run(execute(args))
    except UserGroupAdminGrantCleanupBlockedError as exc:
        print(f"F048 user-group admin Grant cleanup blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except Exception:
        traceback.print_exc()
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())

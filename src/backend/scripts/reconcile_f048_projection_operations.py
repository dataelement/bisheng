#!/usr/bin/env python3
"""Inspect or reconcile durable F048 permission projection operations.

The projection ledger is the only supported recovery source after a process
crash, an OpenFGA transport ambiguity, or an idempotent retry failure.  This
script validates the live Catalog/OpenFGA pin and every requested ledger row
before it allows the domain reconciler to resume any operation.  It never
edits ledger, resource, Grant, or OpenFGA rows directly.

Run from ``src/backend/`` with the same ``config`` value as the live service:

    export config=config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_projection_operations.py --tenant-id 1 11 15 18
    PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_projection_operations.py --tenant-id 1 11 15 18 --apply

The default is dry-run.  ``--apply`` resumes active operations sequentially
and verifies that each one reaches ``FINALIZED``.  Re-running a finalized
operation is safe and reports it as skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.common.errcode.permission import (  # noqa: E402
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
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
from bisheng.permission.application.runtime import (  # noqa: E402
    build_f048_permission_runtime,
)
from bisheng.permission.application.sql_runtime import (  # noqa: E402
    SqlCatalogDecisionState,
)
from bisheng.permission.domain.models import (  # noqa: E402
    PermissionProjectionOperation,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import (  # noqa: E402
    ProjectionRepository,
)
from bisheng.permission.domain.services.projection_service import (  # noqa: E402
    restore_projection_plan,
)

EXIT_OK = 0
EXIT_BLOCKED = 3
EXIT_RUNTIME_ERROR = 4
ACTIVE_OPERATION_STATUSES = frozenset(
    {
        "PREPARED",
        "STAGING",
        "COMMIT_UNKNOWN",
        "COMMITTED",
    }
)
SUPPORTED_SCOPE_TYPES = frozenset({"resource", "department"})


class ProjectionReconcileBlockedError(RuntimeError):
    """A preflight or post-reconcile safety invariant was not satisfied."""


@dataclass(frozen=True, slots=True)
class ProjectionReconcileRuntime:
    client: Any
    repository: Any
    projection: Any | None


@dataclass(frozen=True, slots=True)
class OperationInspection:
    operation_id: int
    tenant_id: int
    operation_type: str
    scope_type: str
    scope_key: str
    expected_version: int
    target_version: int
    store_id: str
    model_id: str
    status: str
    tuple_count: int
    tuple_summary: dict[str, int]
    visible_source_count: int
    visible_source_summary: dict[str, int]
    visible_source_checksum: str | None
    resource_mode: dict[str, Any] | None


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tenant-id",
        type=_positive_int,
        required=True,
        help="Expected tenant for every requested operation",
    )
    parser.add_argument(
        "operation_ids",
        nargs="+",
        type=_positive_int,
        metavar="OPERATION_ID",
        help="One or more durable permission projection operation IDs",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Resume and finalize the operations (default: dry-run only)",
    )
    args = parser.parse_args(argv)
    if len(set(args.operation_ids)) != len(args.operation_ids):
        parser.error("operation IDs must not be repeated")
    return args


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProjectionReconcileBlockedError(message)


async def _build_runtime(*, apply: bool) -> ProjectionReconcileRuntime:
    client = await app_context.async_get_instance("openfga")
    await SqlCatalogDecisionState(
        expected_store_id=client.store_id,
        expected_model_id=client.model_id,
    ).ensure_runtime_ready()

    projection = None
    if apply:
        from bisheng.department.domain.services.department_projection_scope import (
            get_department_projection_scope,
        )

        components = await build_f048_permission_runtime(
            client,
            external_scopes={
                "department": get_department_projection_scope(),
            },
        )
        projection = components.projection
    return ProjectionReconcileRuntime(
        client=client,
        repository=ProjectionRepository(),
        projection=projection,
    )


async def _load_resource_mode(
    *,
    tenant_id: int,
    scope_key: str,
) -> ResourcePermissionMode | None:
    resource_type, separator, resource_id = scope_key.partition(":")
    _require(
        bool(separator and resource_type and resource_id),
        f"invalid resource scope key: {scope_key}",
    )
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            statement = select(ResourcePermissionMode).where(
                ResourcePermissionMode.tenant_id == tenant_id,
                ResourcePermissionMode.resource_type == resource_type,
                ResourcePermissionMode.resource_id == resource_id,
            )
            return (await session.execute(statement)).scalars().first()


def _resource_mode_payload(row: ResourcePermissionMode) -> dict[str, Any]:
    return {
        "mode": row.mode,
        "version": int(row.version),
        "projection_state": row.projection_state,
        "operation_id": int(row.operation_id) if row.operation_id is not None else None,
    }


async def inspect_operation(
    runtime: ProjectionReconcileRuntime,
    *,
    operation_id: int,
    tenant_id: int,
) -> OperationInspection:
    with bypass_tenant_filter():
        operation = await runtime.repository.aget_operation(operation_id)
        tuple_rows = await runtime.repository.aget_operation_tuples(operation_id)
        visible_source_rows = await runtime.repository.aget_visible_operation_sources(
            operation_id,
        )
        visible_source_checksum = await runtime.repository.aget_visible_operation_checksum(
            operation_id,
        )

    _require(operation is not None, f"operation {operation_id} does not exist")
    _require(
        int(operation.tenant_id) == tenant_id,
        f"operation {operation_id} belongs to tenant {operation.tenant_id}, not {tenant_id}",
    )
    _require(
        operation.scope_type in SUPPORTED_SCOPE_TYPES,
        f"operation {operation_id} has unsupported scope type {operation.scope_type}",
    )
    _require(
        operation.store_id == runtime.client.store_id and operation.model_id == runtime.client.model_id,
        f"operation {operation_id} OpenFGA pin does not match the live runtime",
    )
    _require(
        operation.status in ACTIVE_OPERATION_STATUSES or operation.status == "FINALIZED",
        f"operation {operation_id} cannot be reconciled from status {operation.status}",
    )
    _require(tuple_rows, f"operation {operation_id} has no durable tuple ledger")
    if operation.operation_type == "GRANT_MUTATION":
        _require(
            bool(visible_source_rows),
            f"operation {operation_id} has no frozen visible source after-state",
        )
    visible_source_summary = Counter(row.state for row in visible_source_rows)
    _require(
        not visible_source_summary.get("FAILED_CLOSED"),
        f"operation {operation_id} has FAILED_CLOSED visible sources",
    )
    if operation.status == "FINALIZED":
        _require(
            not visible_source_summary.get("PENDING"),
            f"operation {operation_id} is FINALIZED with pending visible sources",
        )
    elif visible_source_rows:
        _require(
            set(visible_source_summary) == {"PENDING"},
            f"operation {operation_id} active visible source after-state is mixed",
        )
    try:
        restore_projection_plan(operation, tuple_rows)
    except (
        PermissionPublishNotReadyError,
        PermissionVersionConflictError,
        ValueError,
    ) as exc:
        raise ProjectionReconcileBlockedError(
            f"operation {operation_id} durable ledger cannot reconstruct its request checksum"
        ) from exc

    tuple_summary = Counter(f"{row.phase}:{row.action}" for row in tuple_rows)
    resource_mode = None
    if operation.scope_type == "resource":
        mode_row = await _load_resource_mode(
            tenant_id=tenant_id,
            scope_key=operation.scope_key,
        )
        _require(mode_row is not None, f"operation {operation_id} resource mode row does not exist")
        resource_mode = _resource_mode_payload(mode_row)
        if operation.status == "FINALIZED":
            _require(
                int(mode_row.version) >= int(operation.target_version) and mode_row.projection_state == "CURRENT",
                f"operation {operation_id} is FINALIZED but its resource mirror is inconsistent",
            )
        else:
            _require(
                mode_row.operation_id == operation_id
                and int(mode_row.version) == int(operation.expected_version)
                and mode_row.projection_state == "PROJECTING",
                f"operation {operation_id} active resource mirror does not match its ledger fence",
            )

    return OperationInspection(
        operation_id=operation_id,
        tenant_id=int(operation.tenant_id),
        operation_type=operation.operation_type,
        scope_type=operation.scope_type,
        scope_key=operation.scope_key,
        expected_version=int(operation.expected_version),
        target_version=int(operation.target_version),
        store_id=operation.store_id,
        model_id=operation.model_id,
        status=operation.status,
        tuple_count=len(tuple_rows),
        tuple_summary=dict(sorted(tuple_summary.items())),
        visible_source_count=len(visible_source_rows),
        visible_source_summary=dict(sorted(visible_source_summary.items())),
        visible_source_checksum=visible_source_checksum,
        resource_mode=resource_mode,
    )


async def load_active_operations() -> list[dict[str, Any]]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            statement = (
                select(
                    PermissionProjectionOperation.id,
                    PermissionProjectionOperation.tenant_id,
                    PermissionProjectionOperation.scope_type,
                    PermissionProjectionOperation.scope_key,
                    PermissionProjectionOperation.status,
                )
                .where(PermissionProjectionOperation.status.in_(tuple(sorted(ACTIVE_OPERATION_STATUSES))))
                .order_by(PermissionProjectionOperation.id)
            )
            rows = (await session.execute(statement)).all()
    return [
        {
            "operation_id": int(row[0]),
            "tenant_id": int(row[1]),
            "scope_type": row[2],
            "scope_key": row[3],
            "status": row[4],
        }
        for row in rows
    ]


RuntimeFactory = Callable[..., Awaitable[ProjectionReconcileRuntime]]
OperationInspector = Callable[..., Awaitable[OperationInspection]]
ActiveLoader = Callable[[], Awaitable[list[dict[str, Any]]]]


async def execute(
    args: argparse.Namespace,
    *,
    runtime_factory: RuntimeFactory = _build_runtime,
    operation_inspector: OperationInspector = inspect_operation,
    active_loader: ActiveLoader = load_active_operations,
    initialize_context: Callable[..., Awaitable[None]] = initialize_app_context,
    close_context: Callable[[], Awaitable[None]] = close_app_context,
    live_settings: Any = settings,
) -> int:
    tenant_token = set_current_tenant_id(args.tenant_id)
    initialized = False
    try:
        await initialize_context(config=live_settings)
        initialized = True
        runtime = await runtime_factory(apply=args.apply)
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "tenant_id": args.tenant_id,
                    "store_id": runtime.client.store_id,
                    "model_id": runtime.client.model_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

        inspections: list[OperationInspection] = []
        for operation_id in args.operation_ids:
            inspection = await operation_inspector(
                runtime,
                operation_id=operation_id,
                tenant_id=args.tenant_id,
            )
            inspections.append(inspection)
            print(
                json.dumps(
                    {"event": "preflight", **asdict(inspection)},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

        if not args.apply:
            print("[dry-run] no SQL or OpenFGA mutations were requested; add --apply to reconcile")
        else:
            _require(runtime.projection is not None, "apply runtime did not provide a projection reconciler")
            for inspection in inspections:
                if inspection.status == "FINALIZED":
                    print(
                        json.dumps(
                            {
                                "event": "skip_finalized",
                                "operation_id": inspection.operation_id,
                            },
                            sort_keys=True,
                        )
                    )
                    continue

                outcome = await runtime.projection.reconcile_operation(
                    inspection.operation_id,
                )
                verified = await operation_inspector(
                    runtime,
                    operation_id=inspection.operation_id,
                    tenant_id=args.tenant_id,
                )
                _require(
                    verified.status == "FINALIZED" and outcome.status == "FINALIZED",
                    f"operation {inspection.operation_id} did not reach FINALIZED",
                )
                print(
                    json.dumps(
                        {
                            "event": "reconciled",
                            "operation_id": inspection.operation_id,
                            "status": verified.status,
                            "resource_mode": verified.resource_mode,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )

        remaining = await active_loader()
        print(
            json.dumps(
                {
                    "event": "remaining_active",
                    "count": len(remaining),
                    "operations": remaining,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return EXIT_OK
    finally:
        try:
            if initialized:
                await close_context()
        finally:
            current_tenant_id.reset(tenant_token)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except ProjectionReconcileBlockedError as exc:
        print(f"F048 projection reconcile blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except Exception:
        traceback.print_exc()
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())

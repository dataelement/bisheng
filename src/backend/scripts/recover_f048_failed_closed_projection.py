#!/usr/bin/env python3
"""Forward-recover one FAILED_CLOSED F048 resource projection.

The script treats the durable projection operation as the frozen intent. It
reads the live OpenFGA state with higher consistency, proposes only the exact
differences required to reach the operation's AFTER state, and binds that
proposal to a confirmation checksum. It never updates SQL or OpenFGA directly;
``--apply`` delegates the write, verification, and SQL finalize sequence to the
normal permission projection domain service.

Run from ``src/backend/`` with the same ``config`` value as the live service:

    export config=config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/recover_f048_failed_closed_projection.py \
      --tenant-id 1 --resource-type knowledge_space --resource-id 4166

The default is dry-run. Review the output and repeat with ``--apply`` plus the
three exact confirmation values printed by the dry-run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from collections import Counter
from dataclasses import dataclass
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

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
from bisheng.department.domain.services.department_projection_scope import (  # noqa: E402
    get_department_projection_scope,
)
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

EXIT_OK = 0
EXIT_BLOCKED = 3
EXIT_RUNTIME_ERROR = 4


class FailedClosedRecoveryBlockedError(RuntimeError):
    """A recovery preflight or confirmation invariant was not satisfied."""


@dataclass(frozen=True, slots=True)
class RecoveryRuntime:
    client: Any
    projection: Any
    repository: Any


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _resource_type(value: str) -> str:
    if not value.strip() or ":" in value:
        raise argparse.ArgumentTypeError("resource type must be non-empty and must not contain ':'")
    return value


def _resource_id(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("resource ID must be non-empty")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--tenant-id", type=_positive_int, required=True)
    parser.add_argument("--resource-type", type=_resource_type, required=True)
    parser.add_argument("--resource-id", type=_resource_id, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-store-id")
    parser.add_argument("--confirm-model-id")
    parser.add_argument("--confirm-recovery-checksum")
    args = parser.parse_args(argv)
    if args.apply:
        missing = [
            flag
            for flag, value in (
                ("--confirm-store-id", args.confirm_store_id),
                ("--confirm-model-id", args.confirm_model_id),
                ("--confirm-recovery-checksum", args.confirm_recovery_checksum),
            )
            if not value
        ]
        if missing:
            parser.error(f"--apply requires {', '.join(missing)}")
    return args


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FailedClosedRecoveryBlockedError(message)


async def _build_runtime() -> RecoveryRuntime:
    client = await app_context.async_get_instance("openfga")
    await SqlCatalogDecisionState(
        expected_store_id=client.store_id,
        expected_model_id=client.model_id,
    ).ensure_runtime_ready()
    components = await build_f048_permission_runtime(
        client,
        external_scopes={
            "department": get_department_projection_scope(),
        },
    )
    return RecoveryRuntime(
        client=client,
        projection=components.projection,
        repository=ProjectionRepository(),
    )


async def _load_mode(
    *,
    tenant_id: int,
    resource_type: str,
    resource_id: str,
) -> ResourcePermissionMode | None:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            statement = select(ResourcePermissionMode).where(
                ResourcePermissionMode.tenant_id == tenant_id,
                ResourcePermissionMode.resource_type == resource_type,
                ResourcePermissionMode.resource_id == resource_id,
            )
            return (await session.exec(statement)).first()


def _mode_payload(mode: ResourcePermissionMode) -> dict[str, Any]:
    return {
        "mode": mode.mode,
        "version": int(mode.version),
        "projection_state": mode.projection_state,
        "operation_id": int(mode.operation_id) if mode.operation_id is not None else None,
    }


async def _load_operation(
    runtime: RecoveryRuntime,
    operation_id: int,
) -> PermissionProjectionOperation | None:
    with bypass_tenant_filter():
        return await runtime.repository.aget_operation(operation_id)


async def inspect(
    runtime: RecoveryRuntime,
    args: argparse.Namespace,
) -> tuple[Any | None, dict[str, Any]]:
    scope_key = f"{args.resource_type}:{args.resource_id}"
    mode = await _load_mode(
        tenant_id=args.tenant_id,
        resource_type=args.resource_type,
        resource_id=args.resource_id,
    )
    _require(mode is not None, "resource permission mode row does not exist")
    _require(mode.operation_id is not None, "resource has no bound projection operation")
    operation_id = int(mode.operation_id)
    operation = await _load_operation(runtime, operation_id)
    _require(operation is not None, f"bound operation {operation_id} does not exist")
    _require(
        int(operation.tenant_id) == args.tenant_id,
        f"operation belongs to tenant {operation.tenant_id}, not {args.tenant_id}",
    )
    _require(operation.scope_type == "resource", "only resource projection scopes are supported")
    _require(operation.scope_key == scope_key, "bound operation scope does not match the resource")
    _require(
        operation.store_id == runtime.client.store_id
        and operation.model_id == runtime.client.model_id,
        "operation Store/model pin does not match the CURRENT runtime",
    )

    if operation.status == "FINALIZED":
        _require(
            int(mode.version) >= int(operation.target_version)
            and mode.projection_state == "CURRENT",
            "FINALIZED operation has an inconsistent resource mirror",
        )
        return None, {
            "operation_id": operation_id,
            "status": "FINALIZED",
            "scope_key": scope_key,
            "resource_mode": _mode_payload(mode),
        }

    _require(
        operation.status in {"FAILED_CLOSED", "COMMITTED"},
        f"operation cannot be forward-recovered from status {operation.status}",
    )
    valid_mode = (
        int(mode.version) == int(operation.expected_version)
        and mode.projection_state == "FAILED_CLOSED"
    ) or (
        operation.status == "COMMITTED"
        and int(mode.version) == int(operation.target_version)
        and mode.projection_state == "CURRENT"
    )
    _require(valid_mode, "resource mirror does not match the failed operation fence")

    preview = await runtime.projection.inspect_failed_closed_recovery(operation_id)
    with bypass_tenant_filter():
        visible_sources = await runtime.repository.aget_visible_operation_sources(
            operation_id,
        )
    visible_source_summary = Counter(source.state for source in visible_sources)
    if operation.operation_type == "GRANT_MUTATION":
        _require(visible_sources, "Grant mutation has no frozen visible source after-state")
    if mode.projection_state == "FAILED_CLOSED" and visible_sources:
        _require(
            set(visible_source_summary) == {"PENDING"},
            "failed operation visible source after-state is incomplete or mixed",
        )
    correction_summary = Counter(
        f"{delta.action}:{delta.relation}" for delta in preview.correction_deltas
    )
    payload = {
        "operation_id": preview.operation_id,
        "tenant_id": preview.tenant_id,
        "operation_type": preview.operation_type,
        "status": preview.operation_status,
        "scope_key": preview.scope_key,
        "expected_version": preview.expected_version,
        "target_version": preview.target_version,
        "store_id": preview.store_id,
        "model_id": preview.model_id,
        "request_checksum": preview.request_checksum,
        "after_checksum": preview.after_checksum,
        "observed_state": preview.observed_state,
        "target_tuple_count": preview.target_tuple_count,
        "correction_tuple_count": len(preview.correction_deltas),
        "correction_summary": dict(sorted(correction_summary.items())),
        "visible_source_count": len(visible_sources),
        "visible_source_summary": dict(sorted(visible_source_summary.items())),
        "recovery_confirmation_checksum": preview.confirmation_checksum,
        "resource_mode": _mode_payload(mode),
    }
    return preview, payload


async def execute(args: argparse.Namespace) -> int:
    tenant_token = set_current_tenant_id(args.tenant_id)
    initialized = False
    try:
        await initialize_app_context(config=settings)
        initialized = True
        runtime = await _build_runtime()
        preview, payload = await inspect(runtime, args)
        print(
            json.dumps(
                {
                    "event": "failed_closed_recovery_preflight",
                    "mode": "apply" if args.apply else "dry-run",
                    **payload,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        if preview is None:
            print("[skip] operation is already FINALIZED and the resource mirror is CURRENT")
            return EXIT_OK
        if not args.apply:
            print(
                "[dry-run] no SQL or OpenFGA mutations were requested; repeat with --apply "
                "and the printed Store/model/recovery confirmation values"
            )
            return EXIT_OK

        _require(args.confirm_store_id == preview.store_id, "Store confirmation does not match")
        _require(args.confirm_model_id == preview.model_id, "model confirmation does not match")
        _require(
            args.confirm_recovery_checksum == preview.confirmation_checksum,
            "recovery confirmation checksum does not match the live proposal",
        )
        outcome = await runtime.projection.recover_failed_closed_operation(
            preview.operation_id,
            confirmation_checksum=args.confirm_recovery_checksum,
        )
        verified_preview, verified = await inspect(runtime, args)
        _require(verified_preview is None, "operation did not reach FINALIZED")
        print(
            json.dumps(
                {
                    "event": "failed_closed_recovery_finalized",
                    "operation_id": preview.operation_id,
                    "status": outcome.status,
                    "resource_mode": verified["resource_mode"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return EXIT_OK
    finally:
        try:
            if initialized:
                await close_app_context()
        finally:
            current_tenant_id.reset(tenant_token)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except FailedClosedRecoveryBlockedError as exc:
        print(f"F048 FAILED_CLOSED recovery blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except Exception:
        traceback.print_exc()
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())

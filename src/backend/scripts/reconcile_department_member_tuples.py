#!/usr/bin/env python3
"""Reconcile OpenFGA department-member tuples from ``user_department``.

Run from the backend root:

    PYTHONPATH=./ .venv/bin/python scripts/reconcile_department_member_tuples.py
    PYTHONPATH=./ .venv/bin/python scripts/reconcile_department_member_tuples.py --apply

The default mode is a read-only dry run. It compares every
``user_department`` row with OpenFGA and reports missing
``user:<id> member department:<id>`` tuples. ``--apply`` writes only those
missing tuples; it never removes database rows or OpenFGA tuples.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlmodel import select  # noqa: E402

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.core.openfga.client import FGAClient  # noqa: E402
from bisheng.database.models.department import UserDepartment  # noqa: E402
from bisheng.department.domain.services.department_change_handler import (  # noqa: E402
    DepartmentChangeHandler,
)
from bisheng.permission.domain.services.permission_service import PermissionService  # noqa: E402

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_DEPENDENCY_ERROR = 3
EXIT_APPLY_ERROR = 4


class FgaConfigurationError(RuntimeError):
    """Raised when the script cannot safely connect to OpenFGA."""


@dataclass(frozen=True)
class FgaReadContext:
    """A direct OpenFGA client that never creates a store or model."""

    client: FGAClient


@dataclass
class ReconcileReport:
    """Serializable reconciliation statistics and bounded samples."""

    apply: bool
    department_ids: list[int]
    batch_size: int
    database_membership_rows: int = 0
    existing_fga_member_tuples: int = 0
    missing_fga_member_tuples: int = 0
    applied_member_tuples: int = 0
    database_batches: int = 0
    read_department_count: int = 0
    missing_samples: list[dict[str, int]] = field(default_factory=list)
    error: str | None = None

    def add_missing_sample(self, user_id: int, department_id: int, limit: int) -> None:
        if len(self.missing_samples) < limit:
            self.missing_samples.append({"user_id": user_id, "department_id": department_id})

    def to_dict(self) -> dict[str, Any]:
        return {
            "script": "reconcile_department_member_tuples",
            "mode": "apply" if self.apply else "dry_run",
            "scope": {
                "department_ids": self.department_ids or "all",
                "database_batch_size": self.batch_size,
            },
            "database_membership_rows": self.database_membership_rows,
            "existing_fga_member_tuples": self.existing_fga_member_tuples,
            "missing_fga_member_tuples": self.missing_fga_member_tuples,
            "applied_member_tuples": self.applied_member_tuples,
            "database_batches": self.database_batches,
            "read_department_count": self.read_department_count,
            "missing_samples": self.missing_samples,
            "error": self.error,
        }


def _tuple_key(value: Any) -> dict[str, str]:
    """Normalize OpenFGA client tuple formats."""
    raw = value.get("key", value) if isinstance(value, dict) else {}
    return {
        "user": str(raw.get("user") or ""),
        "relation": str(raw.get("relation") or ""),
        "object": str(raw.get("object") or ""),
    }


def _user_id_from_member_tuple(value: Any, department_id: int) -> int | None:
    """Return the user ID when a tuple is the requested department member."""
    item = _tuple_key(value)
    if item["relation"] != "member" or item["object"] != f"department:{department_id}":
        return None
    prefix = "user:"
    if not item["user"].startswith(prefix):
        return None
    raw_user_id = item["user"][len(prefix) :]
    return int(raw_user_id) if raw_user_id.isdigit() else None


async def _create_read_only_fga_context() -> FgaReadContext:
    """Build a direct FGA client without any store/model bootstrap side effects."""
    config = getattr(settings, "openfga", None)
    if config is None or not bool(getattr(config, "enabled", False)):
        raise FgaConfigurationError("OpenFGA is disabled.")

    api_url = str(getattr(config, "api_url", "") or "").strip()
    store_id = str(getattr(config, "store_id", "") or "").strip()
    model_id = str(getattr(config, "model_id", "") or "").strip()
    if not api_url or not store_id or not model_id:
        raise FgaConfigurationError(
            "OpenFGA api_url, store_id, and model_id must all be configured; "
            "this script will not auto-create any of them."
        )

    timeout = float(getattr(config, "timeout", 10) or 10)
    return FgaReadContext(
        client=FGAClient(api_url=api_url, store_id=store_id, model_id=model_id, timeout=timeout),
    )


async def _iter_membership_batches(
    department_ids: list[int],
    batch_size: int,
) -> AsyncIterator[list[tuple[int, int]]]:
    """Yield ``(user_id, department_id)`` rows with keyset pagination."""
    last_id = 0
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            while True:
                statement = (
                    select(UserDepartment)
                    .where(UserDepartment.id > last_id)
                    .order_by(UserDepartment.id)
                    .limit(batch_size)
                )
                if department_ids:
                    statement = statement.where(UserDepartment.department_id.in_(department_ids))
                result = await session.exec(statement)
                rows = result.all()
                if not rows:
                    return

                last_id = max(int(row.id) for row in rows if row.id is not None)
                yield [(int(row.user_id), int(row.department_id)) for row in rows if row.id is not None]


def _group_user_ids_by_department(
    memberships: list[tuple[int, int]],
) -> dict[int, set[int]]:
    """Group one database page by department for bounded FGA reads."""
    result: dict[int, set[int]] = defaultdict(set)
    for user_id, department_id in memberships:
        result[department_id].add(user_id)
    return result


async def _find_missing_pairs(
    fga: FGAClient,
    memberships_by_department: dict[int, set[int]],
    report: ReconcileReport,
    sample_limit: int,
) -> list[tuple[int, int]]:
    """Read each department's member tuples and return only missing pairs."""
    missing_pairs: list[tuple[int, int]] = []
    for department_id, database_user_ids in memberships_by_department.items():
        tuples = await fga.read_tuples(
            object=f"department:{department_id}",
            relation="member",
        )
        fga_user_ids = {
            user_id
            for user_id in (_user_id_from_member_tuple(item, department_id) for item in tuples)
            if user_id is not None
        }
        missing_user_ids = sorted(database_user_ids - fga_user_ids)
        report.read_department_count += 1
        report.existing_fga_member_tuples += len(database_user_ids) - len(missing_user_ids)
        report.missing_fga_member_tuples += len(missing_user_ids)
        for user_id in missing_user_ids:
            missing_pairs.append((user_id, department_id))
            report.add_missing_sample(user_id, department_id, sample_limit)
    return missing_pairs


async def _apply_missing_pairs(missing_pairs: list[tuple[int, int]]) -> None:
    """Write missing tuples through the application's crash-safe permission path."""
    operations = []
    for user_id, department_id in missing_pairs:
        operations.extend(DepartmentChangeHandler.on_members_added(department_id, [user_id]))

    await PermissionService.batch_write_tuples(
        operations,
        crash_safe=True,
        raise_on_failure=True,
        stop_on_failure=True,
    )


async def _run(args: argparse.Namespace) -> tuple[ReconcileReport, int]:
    report = ReconcileReport(
        apply=args.apply,
        department_ids=sorted(set(args.department_ids)),
        batch_size=args.batch_size,
    )
    read_context: FgaReadContext | None = None
    app_context_initialized = False
    try:
        read_context = await _create_read_only_fga_context()
        if args.apply:
            # Explicitly validated store/model IDs prevent bootstrap writes here.
            await initialize_app_context(config=settings)
            app_context_initialized = True

        async for memberships in _iter_membership_batches(report.department_ids, args.batch_size):
            report.database_batches += 1
            report.database_membership_rows += len(memberships)
            missing_pairs = await _find_missing_pairs(
                read_context.client,
                _group_user_ids_by_department(memberships),
                report,
                args.sample_limit,
            )
            if args.apply and missing_pairs:
                await _apply_missing_pairs(missing_pairs)
                report.applied_member_tuples += len(missing_pairs)
    except FgaConfigurationError as exc:
        report.error = f"{type(exc).__name__}: {exc}"
        return report, EXIT_DEPENDENCY_ERROR
    except Exception as exc:
        logger.exception("Department member tuple reconciliation failed")
        report.error = f"{type(exc).__name__}: {exc}"
        return report, EXIT_APPLY_ERROR if args.apply else EXIT_DEPENDENCY_ERROR
    finally:
        if read_context is not None:
            await read_context.client.close()
        if app_context_initialized:
            await close_app_context()

    return report, EXIT_OK


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile OpenFGA user-to-department member tuples from user_department.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write missing OpenFGA tuples. Without this flag the script is read-only.",
    )
    parser.add_argument(
        "--department-id",
        dest="department_ids",
        type=int,
        action="append",
        default=[],
        help="Restrict reconciliation to one department ID. Repeat this option as needed.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Maximum user_department rows read per database page (default: 500).",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=20,
        help="Maximum missing pairs retained in the JSON output (default: 20).",
    )
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be a positive integer.")
    if args.sample_limit < 0:
        parser.error("--sample-limit must not be negative.")
    if any(department_id <= 0 for department_id in args.department_ids):
        parser.error("--department-id must be a positive integer.")
    return args


def main() -> int:
    args = _parse_args()
    report, exit_code = asyncio.run(_run(args))
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

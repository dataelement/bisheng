#!/usr/bin/env python3
"""Move non-canonical root departments under the default organization.

The default tenant has exactly one canonical root department referenced by
``tenant.root_dept_id`` (normally named ``默认组织``). Historical third-party
syncs could create additional rows with ``parent_id IS NULL``. This script
moves every other root in the default tenant under the canonical root, rewrites
the full materialized-path subtree, and submits the matching OpenFGA parent
tuple for active departments.

Run from ``src/backend``. Dry-run is the default:

    PYTHONPATH=./ .venv/bin/python scripts/migrate_root_departments_under_default_org.py

Apply after reviewing the JSON plan:

    PYTHONPATH=./ .venv/bin/python scripts/migrate_root_departments_under_default_org.py --apply
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import func, update
from sqlmodel import select

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
)


class PreflightError(RuntimeError):
    """Raised when the current tree cannot be migrated safely."""


@dataclass(frozen=True)
class RootDepartmentMove:
    department_id: int
    dept_id: str
    name: str
    source: str
    status: str
    old_path: str
    new_path: str


@dataclass(frozen=True)
class MigrationPlan:
    tenant_id: int
    default_root_id: int
    default_root_dept_id: str
    default_root_name: str
    default_root_path: str
    moves: tuple[RootDepartmentMove, ...]

    def summary(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "default_root": {
                "id": self.default_root_id,
                "dept_id": self.default_root_dept_id,
                "name": self.default_root_name,
                "path": self.default_root_path,
            },
            "move_count": len(self.moves),
            "moves": [asdict(move) for move in self.moves],
        }


def _normalized_path(path: str, *, label: str) -> str:
    normalized = (path or "").strip()
    if not normalized or not normalized.startswith("/") or not normalized.endswith("/"):
        raise PreflightError(f"Invalid {label} path: {path!r}")
    return normalized


async def build_plan() -> MigrationPlan:
    """Read and validate the canonical root plus every other DB root."""
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            tenant = (
                await session.exec(
                    select(Tenant).where(Tenant.id == ROOT_TENANT_ID),
                )
            ).first()
            if tenant is None or tenant.root_dept_id is None:
                raise PreflightError("Default tenant root_dept_id is not configured")

            default_root = (
                await session.exec(
                    select(Department).where(
                        Department.id == int(tenant.root_dept_id),
                    ),
                )
            ).first()
            if default_root is None:
                raise PreflightError("Default organization department does not exist")
            if int(default_root.tenant_id) != ROOT_TENANT_ID:
                raise PreflightError("Default organization belongs to another tenant")
            if default_root.parent_id is not None:
                raise PreflightError("Default organization is not a root department")
            if default_root.status != "active":
                raise PreflightError("Default organization is not active")

            default_root_id = int(default_root.id)
            default_root_path = _normalized_path(
                default_root.path,
                label="default organization",
            )
            if default_root_path != f"/{default_root_id}/":
                raise PreflightError(f"Default organization has a non-root path: {default_root_path!r}")
            other_roots = list(
                (
                    await session.exec(
                        select(Department)
                        .where(
                            Department.tenant_id == ROOT_TENANT_ID,
                            Department.parent_id.is_(None),
                            Department.id != default_root_id,
                        )
                        .order_by(Department.id),
                    )
                ).all()
            )

    moves: list[RootDepartmentMove] = []
    for department in other_roots:
        department_id = int(department.id)
        old_path = _normalized_path(
            department.path,
            label=f"department {department_id}",
        )
        if old_path != f"/{department_id}/":
            raise PreflightError(f"Root department {department_id} has a non-root path: {old_path!r}")
        moves.append(
            RootDepartmentMove(
                department_id=department_id,
                dept_id=department.dept_id,
                name=department.name,
                source=department.source,
                status=department.status,
                old_path=old_path,
                new_path=f"{default_root_path}{department_id}/",
            )
        )

    return MigrationPlan(
        tenant_id=ROOT_TENANT_ID,
        default_root_id=default_root_id,
        default_root_dept_id=default_root.dept_id,
        default_root_name=default_root.name,
        default_root_path=default_root_path,
        moves=tuple(moves),
    )


async def apply_plan(plan: MigrationPlan) -> dict:
    """Move all planned roots in one DB transaction, then update OpenFGA."""
    if not plan.moves:
        return {
            "moved_departments": 0,
            "openfga_operations_submitted": 0,
        }

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            department_ids = [move.department_id for move in plan.moves]
            current_rows = list(
                (
                    await session.exec(
                        select(Department).where(Department.id.in_(department_ids)),
                    )
                ).all()
            )
            current_by_id = {int(row.id): row for row in current_rows}

            for move in plan.moves:
                current = current_by_id.get(move.department_id)
                if current is None:
                    raise PreflightError(
                        f"Department {move.department_id} disappeared after dry-run",
                    )
                if current.parent_id is not None or current.path != move.old_path:
                    raise PreflightError(
                        f"Department {move.department_id} changed after dry-run; rerun the script",
                    )

                await session.exec(
                    update(Department)
                    .where(
                        Department.tenant_id == plan.tenant_id,
                        Department.path.like(f"{move.old_path}%"),
                    )
                    .values(
                        path=func.replace(
                            Department.path,
                            move.old_path,
                            move.new_path,
                        ),
                    )
                )
                await session.exec(
                    update(Department)
                    .where(
                        Department.id == move.department_id,
                        Department.parent_id.is_(None),
                    )
                    .values(parent_id=plan.default_root_id)
                )

            await session.commit()

    operations = []
    for move in plan.moves:
        if move.status == "active":
            operations.extend(
                DepartmentChangeHandler.on_created(
                    move.department_id,
                    plan.default_root_id,
                )
            )
    await DepartmentChangeHandler.execute_async(operations)

    return {
        "moved_departments": len(plan.moves),
        "openfga_operations_submitted": len(operations),
    }


async def run(args: argparse.Namespace) -> int:
    token = set_current_tenant_id(ROOT_TENANT_ID)
    try:
        plan = await build_plan()
        output = plan.summary()
        output["mode"] = "apply" if args.apply else "dry-run"
        if not args.apply:
            print(json.dumps(output, ensure_ascii=False, indent=2))
            print("Dry-run only. Re-run with --apply after reviewing this plan.")
            return 0

        output["result"] = await apply_plan(plan)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    finally:
        current_tenant_id.reset(token)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Move departments and submit OpenFGA tuples (default: dry-run).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except PreflightError as exc:
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

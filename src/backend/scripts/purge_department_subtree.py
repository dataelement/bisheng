#!/usr/bin/env python3
"""Permanently purge a department subtree and its users.

Run from ``src/backend``:

    PYTHONPATH=./ .venv/bin/python scripts/purge_department_subtree.py \
      --dept-id BS@example --transfer-to-user-id 1

Dry-run is the default. ``--apply`` transfers assets and deletes Linsight,
account-relation, and department records. The apply path is irreversible.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import delete
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.department_admin_grant import DepartmentAdminGrant
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import UserTenant
from bisheng.database.models.user_group import UserGroup
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
)
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
)
from bisheng.linsight.domain.models.linsight_sop import LinsightSOP, LinsightSOPRecord
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.tenant.domain.services.resource_ownership_service import (
    MAX_BATCH,
    ResourceOwnershipService,
)
from bisheng.tenant.domain.services.resource_type_registry import SUPPORTED_TYPES
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole
from bisheng.user.domain.services.auth import LoginUser


class PreflightError(RuntimeError):
    """Raised when an irreversible operation is not safe to start."""


@dataclass(frozen=True)
class AssetBatch:
    """A ResourceOwnershipService-compatible transfer batch."""

    from_user_id: int
    tenant_id: int
    resource_type: str
    resource_ids: tuple[int | str, ...]


@dataclass
class PurgePlan:
    """Read-only snapshot used by dry-run and apply paths."""

    departments_root_to_leaf: list[Department]
    users: list[User]
    user_department_pairs: list[tuple[int, int]]
    admin_pairs: list[tuple[int, int]]
    asset_batches: list[AssetBatch] = field(default_factory=list)
    linsight_counts: dict[str, int] = field(default_factory=dict)

    @property
    def department_ids(self) -> list[int]:
        return [int(dept.id) for dept in self.departments_root_to_leaf if dept.id is not None]

    @property
    def user_ids(self) -> list[int]:
        return [int(user.user_id) for user in self.users if user.user_id is not None]

    def summary(self) -> dict:
        return {
            "departments": [
                {
                    "id": int(dept.id),
                    "dept_id": dept.dept_id,
                    "name": dept.name,
                    "source": dept.source,
                }
                for dept in self.departments_root_to_leaf
                if dept.id is not None
            ],
            "user_ids": self.user_ids,
            "user_department_pairs": len(self.user_department_pairs),
            "department_admin_pairs": len(self.admin_pairs),
            "asset_batches": [
                {
                    "from_user_id": batch.from_user_id,
                    "tenant_id": batch.tenant_id,
                    "resource_type": batch.resource_type,
                    "resource_count": len(batch.resource_ids),
                }
                for batch in self.asset_batches
            ],
            "linsight_records": self.linsight_counts,
        }


def _build_subtree(root: Department, departments: Iterable[Department]) -> list[Department]:
    """Return a stable root-to-leaf subtree without dialect-specific SQL."""
    children: dict[int, list[Department]] = defaultdict(list)
    for department in departments:
        if department.parent_id is not None:
            children[int(department.parent_id)].append(department)
    for values in children.values():
        values.sort(key=lambda item: int(item.id or 0))

    result: list[Department] = []
    queue: deque[Department] = deque([root])
    seen: set[int] = set()
    while queue:
        department = queue.popleft()
        if department.id is None or int(department.id) in seen:
            continue
        seen.add(int(department.id))
        result.append(department)
        queue.extend(children.get(int(department.id), []))
    return result


def _delete_order(departments_root_to_leaf: list[Department]) -> list[Department]:
    """Delete leaf nodes first so parent references cannot block removal."""
    return list(reversed(departments_root_to_leaf))


def _chunks(values: list[int | str], size: int = MAX_BATCH) -> Iterable[tuple[int | str, ...]]:
    for start in range(0, len(values), size):
        yield tuple(values[start : start + size])


async def _collect_asset_batches(
    user_tenant_ids: dict[int, set[int]],
    receiver_id: int,
) -> list[AssetBatch]:
    batches: list[AssetBatch] = []
    for user_id, tenant_ids in user_tenant_ids.items():
        for tenant_id in sorted(tenant_ids | {1}):
            await ResourceOwnershipService._check_receiver_visible(receiver_id, tenant_id)
            for resource_type in SUPPORTED_TYPES:
                resources = await ResourceOwnershipService._resolve_resources(
                    tenant_id=tenant_id,
                    from_user_id=user_id,
                    resource_types=[resource_type],
                    resource_ids=None,
                )
                resource_ids = [resource.id for resource in resources]
                for chunk in _chunks(resource_ids):
                    batches.append(
                        AssetBatch(
                            from_user_id=user_id,
                            tenant_id=tenant_id,
                            resource_type=resource_type,
                            resource_ids=chunk,
                        )
                    )
    return batches


async def build_plan(
    dept_id: str | None,
    department_id: int | None,
    receiver_id: int,
) -> PurgePlan:
    """Collect every required fact before an apply path is allowed to write."""
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            departments = list((await session.exec(select(Department))).all())
            root = next(
                (
                    item
                    for item in departments
                    if (item.id == department_id if department_id is not None else item.dept_id == dept_id)
                ),
                None,
            )
            if root is None:
                identifier = f"department_id={department_id}" if department_id is not None else f"dept_id={dept_id}"
                raise PreflightError(f"Department not found: {identifier}")

            subtree = _build_subtree(root, departments)
            protected = [
                item.dept_id for item in subtree if item.dept_id == "BS@guest" or int(item.is_tenant_root or 0) == 1
            ]
            if protected:
                raise PreflightError(
                    f"Protected department in target subtree: {', '.join(protected)}",
                )

            department_ids = [int(item.id) for item in subtree if item.id is not None]
            target_members = list(
                (
                    await session.exec(
                        select(UserDepartment.user_id).where(
                            UserDepartment.department_id.in_(department_ids),
                        ),
                    )
                ).all()
            )
            user_ids = sorted({int(row[0] if isinstance(row, tuple) else row) for row in target_members})
            if receiver_id in user_ids:
                raise PreflightError("Transfer receiver is included in the deletion set")

            receiver = (
                await session.exec(
                    select(User).where(User.user_id == receiver_id),
                )
            ).first()
            if receiver is None:
                raise PreflightError(f"Transfer receiver not found: {receiver_id}")
            receiver_admin = (
                await session.exec(
                    select(UserRole.id).where(
                        UserRole.user_id == receiver_id,
                        UserRole.role_id == AdminRole,
                    ),
                )
            ).first()
            if receiver_admin is None:
                raise PreflightError("Transfer receiver must be an admin user")

            users = (
                []
                if not user_ids
                else list(
                    (
                        await session.exec(
                            select(User).where(User.user_id.in_(user_ids)),
                        )
                    ).all()
                )
            )
            if len(users) != len(user_ids):
                raise PreflightError("One or more department members no longer exist")

            all_memberships = (
                []
                if not user_ids
                else list(
                    (
                        await session.exec(
                            select(UserDepartment.user_id, UserDepartment.department_id).where(
                                UserDepartment.user_id.in_(user_ids),
                            ),
                        )
                    ).all()
                )
            )
            admin_rows = (
                []
                if not user_ids
                else list(
                    (
                        await session.exec(
                            select(DepartmentAdminGrant.user_id, DepartmentAdminGrant.department_id).where(
                                DepartmentAdminGrant.user_id.in_(user_ids),
                            ),
                        )
                    ).all()
                )
            )
            user_tenants = (
                []
                if not user_ids
                else list(
                    (
                        await session.exec(
                            select(UserTenant.user_id, UserTenant.tenant_id).where(
                                UserTenant.user_id.in_(user_ids),
                            ),
                        )
                    ).all()
                )
            )

            linsight_counts = {
                "linsight_session_version": int(
                    (
                        await session.exec(
                            select(LinsightSessionVersion).where(
                                LinsightSessionVersion.user_id.in_(user_ids),
                            ),
                        )
                    )
                    .all()
                    .__len__()
                )
                if user_ids
                else 0,
                "linsight_sop": int(
                    (
                        await session.exec(
                            select(LinsightSOP).where(LinsightSOP.user_id.in_(user_ids)),
                        )
                    )
                    .all()
                    .__len__()
                )
                if user_ids
                else 0,
                "linsight_sop_record": int(
                    (
                        await session.exec(
                            select(LinsightSOPRecord).where(LinsightSOPRecord.user_id.in_(user_ids)),
                        )
                    )
                    .all()
                    .__len__()
                )
                if user_ids
                else 0,
            }

    user_tenant_ids: dict[int, set[int]] = defaultdict(set)
    for user_id, tenant_id in user_tenants:
        user_tenant_ids[int(user_id)].add(int(tenant_id))
    for user_id in user_ids:
        user_tenant_ids.setdefault(user_id, set())

    asset_batches = await _collect_asset_batches(user_tenant_ids, receiver_id)
    return PurgePlan(
        departments_root_to_leaf=subtree,
        users=users,
        user_department_pairs=[(int(uid), int(did)) for uid, did in all_memberships],
        admin_pairs=[(int(uid), int(did)) for uid, did in admin_rows],
        asset_batches=asset_batches,
        linsight_counts=linsight_counts,
    )


async def _transfer_assets(plan: PurgePlan, receiver_id: int) -> int:
    # The receiver is intentionally outside plan.users, so construct an operator
    # from the checked target identity for ResourceOwnershipService authorization.
    operator = LoginUser(user_id=receiver_id, user_name="maintenance-transfer-receiver")
    if not operator.is_admin():
        raise PreflightError("Transfer receiver is no longer an admin user")

    transferred = 0
    for batch in plan.asset_batches:
        result = await ResourceOwnershipService.transfer_owner(
            tenant_id=batch.tenant_id,
            from_user_id=batch.from_user_id,
            to_user_id=receiver_id,
            resource_types=[batch.resource_type],
            resource_ids=list(batch.resource_ids),
            reason="purge department subtree maintenance script",
            operator=operator,
        )
        transferred += int(result.get("transferred_count", 0))
    return transferred


async def apply_plan(plan: PurgePlan, receiver_id: int) -> dict:
    """Execute the irreversible portion after all preflight checks pass."""
    transferred = await _transfer_assets(plan, receiver_id)
    user_ids = plan.user_ids
    department_ids = plan.department_ids
    operations = []

    for user_id, department_id in plan.user_department_pairs:
        operations.extend(DepartmentChangeHandler.on_member_removed(department_id, user_id))
    for user_id, department_id in plan.admin_pairs:
        operations.extend(DepartmentChangeHandler.on_admin_removed(department_id, [user_id]))

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            scoped_role_ids = (
                []
                if not department_ids
                else list(
                    (
                        await session.exec(
                            select(Role.id).where(Role.department_id.in_(department_ids)),
                        )
                    ).all()
                )
            )
            scoped_role_ids = [int(row[0] if isinstance(row, tuple) else row) for row in scoped_role_ids]

            if user_ids:
                await session.exec(
                    delete(LinsightSessionVersion).where(
                        LinsightSessionVersion.user_id.in_(user_ids),
                    )
                )
                await session.exec(delete(LinsightSOP).where(LinsightSOP.user_id.in_(user_ids)))
                await session.exec(
                    delete(LinsightSOPRecord).where(
                        LinsightSOPRecord.user_id.in_(user_ids),
                    )
                )
                await session.exec(
                    delete(DepartmentAdminGrant).where(
                        DepartmentAdminGrant.user_id.in_(user_ids),
                    )
                )
                await session.exec(delete(UserDepartment).where(UserDepartment.user_id.in_(user_ids)))
                await session.exec(delete(UserRole).where(UserRole.user_id.in_(user_ids)))
                await session.exec(delete(UserGroup).where(UserGroup.user_id.in_(user_ids)))
                await session.exec(delete(UserTenant).where(UserTenant.user_id.in_(user_ids)))

            if scoped_role_ids:
                await session.exec(delete(UserRole).where(UserRole.role_id.in_(scoped_role_ids)))
                await session.exec(delete(Role).where(Role.id.in_(scoped_role_ids)))
            if department_ids:
                await session.exec(
                    delete(DepartmentAdminGrant).where(
                        DepartmentAdminGrant.department_id.in_(department_ids),
                    )
                )
                await session.exec(
                    delete(UserDepartment).where(
                        UserDepartment.department_id.in_(department_ids),
                    )
                )

            for department in _delete_order(plan.departments_root_to_leaf):
                await session.delete(department)
            if user_ids:
                await session.exec(delete(User).where(User.user_id.in_(user_ids)))
            await session.commit()

    for department in plan.departments_root_to_leaf:
        if department.id is not None:
            operations.extend(DepartmentChangeHandler.on_purged(int(department.id), [], []))
    await PermissionService.batch_write_tuples(operations, crash_safe=True)

    return {
        "transferred_assets": transferred,
        "deleted_users": len(user_ids),
        "deleted_departments": len(department_ids),
        "openfga_operations_submitted": len(operations),
        "openfga_compensation": "FailedTuple retry queue is used for failed operations",
    }


async def run(args: argparse.Namespace) -> int:
    plan = await build_plan(args.dept_id, args.department_id, args.transfer_to_user_id)
    output = plan.summary()
    output["mode"] = "apply" if args.apply else "dry-run"
    if not args.apply:
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        print("Dry-run only. Re-run with --apply to perform irreversible deletion.")
        return 0

    result = await apply_plan(plan, args.transfer_to_user_id)
    output["result"] = result
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--dept-id", help="Target department business dept_id.")
    target_group.add_argument("--department-id", type=int, help="Target department internal ID.")
    parser.add_argument(
        "--transfer-to-user-id",
        type=int,
        required=True,
        help="Admin user_id that receives transferable assets.",
    )
    parser.add_argument("--apply", action="store_true", help="Perform irreversible writes.")
    return parser.parse_args()


def main() -> int:
    try:
        return asyncio.run(run(parse_args()))
    except PreflightError as exc:
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Execution failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())

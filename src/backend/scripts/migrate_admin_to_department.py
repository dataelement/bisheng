#!/usr/bin/env python3
"""Move one admin account to a target department while retaining its resources."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass

from sqlalchemy import update

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department, UserDepartment, UserDepartmentDao
from bisheng.database.models.tenant import UserTenantDao
from bisheng.department.domain.services.department_change_handler import DepartmentChangeHandler
from bisheng.tenant.domain.constants import TenantAuditAction, UserTenantSyncTrigger
from bisheng.tenant.domain.services.resource_ownership_service import ResourceOwnershipService
from bisheng.tenant.domain.services.tenant_resolver import TenantResolver
from bisheng.tenant.domain.services.user_tenant_sync_service import UserTenantSyncService
from bisheng.user.domain.models.user import User, UserDao

logger = logging.getLogger(__name__)


class PreflightError(RuntimeError):
    """Raised when a maintenance migration cannot safely start."""


@dataclass
class MigrationPlan:
    user: User
    target_department: Department
    current_primary_department_id: int | None
    current_leaf_tenant_id: int
    target_leaf_tenant_id: int
    secondary_department_count: int
    retained_resource_count: int

    @property
    def will_change_primary_department(self) -> bool:
        return self.current_primary_department_id != int(self.target_department.id)

    def summary(self) -> dict:
        return {
            "mode": "maintenance_force_retain_resources",
            "user": {"user_id": int(self.user.user_id), "user_name": self.user.user_name},
            "current_primary_department_id": self.current_primary_department_id,
            "target_department": {
                "id": int(self.target_department.id),
                "dept_id": self.target_department.dept_id,
                "name": self.target_department.name,
            },
            "current_leaf_tenant_id": self.current_leaf_tenant_id,
            "target_leaf_tenant_id": self.target_leaf_tenant_id,
            "secondary_department_count": self.secondary_department_count,
            "retained_resource_count": self.retained_resource_count,
            "will_change_primary_department": self.will_change_primary_department,
        }


async def build_plan(
    *,
    user_id: int | None,
    username: str | None,
    department_id: int | None,
    dept_id: str | None,
) -> MigrationPlan:
    """Resolve facts without changing resource ownership or global settings."""
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            user = (
                await session.exec(
                    select(User).where(
                        User.user_id == user_id if user_id is not None else User.user_name == username,
                    )
                )
            ).first()
            if user is None:
                raise PreflightError("Migration user not found")
            target_department = (
                await session.exec(
                    select(Department).where(
                        Department.id == department_id if department_id is not None else Department.dept_id == dept_id,
                    )
                )
            ).first()
            if target_department is None or target_department.status != "active":
                raise PreflightError("Target department not found or inactive")
            memberships = list(
                (
                    await session.exec(
                        select(UserDepartment).where(UserDepartment.user_id == user.user_id),
                    )
                ).all()
            )

    primary = next((row for row in memberships if int(row.is_primary or 0) == 1), None)
    current_primary_department_id = int(primary.department_id) if primary else None
    current_leaf_tenant_id = await ResourceOwnershipService._resolve_leaf_tenant(int(user.user_id))
    target_leaf_tenant_id = int((await TenantResolver._walk_from_dept(int(target_department.id))).id)
    retained_resource_count = await UserTenantSyncService._count_owned_resources(
        int(user.user_id),
        current_leaf_tenant_id,
    )
    return MigrationPlan(
        user=user,
        target_department=target_department,
        current_primary_department_id=current_primary_department_id,
        current_leaf_tenant_id=current_leaf_tenant_id,
        target_leaf_tenant_id=target_leaf_tenant_id,
        secondary_department_count=len(memberships) - (1 if primary else 0),
        retained_resource_count=retained_resource_count,
    )


async def apply_plan(plan: MigrationPlan) -> dict:
    if not plan.will_change_primary_department:
        return {"changed": False, "leaf_tenant_id": plan.current_leaf_tenant_id}
    user_id = int(plan.user.user_id)
    department_id = int(plan.target_department.id)
    primary = await UserDepartmentDao.aget_user_primary_department(user_id)
    async with get_async_db_session() as session:
        if primary is not None:
            await session.exec(update(UserDepartment).where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == primary.department_id,
            ).values(is_primary=0))
        target = await session.exec(select(UserDepartment).where(
            UserDepartment.user_id == user_id,
            UserDepartment.department_id == department_id,
        ))
        if target.first() is None:
            session.add(UserDepartment(user_id=user_id, department_id=department_id, is_primary=1))
        else:
            await session.exec(update(UserDepartment).where(
                UserDepartment.user_id == user_id,
                UserDepartment.department_id == department_id,
            ).values(is_primary=1))
        await session.commit()
    await DepartmentChangeHandler.execute_async(
        DepartmentChangeHandler.on_members_added(department_id, [user_id])
    )
    await UserTenantDao.aactivate_user_tenant(user_id, plan.target_leaf_tenant_id)
    await UserDao.aincrement_token_version(user_id)
    await UserTenantSyncService._rewrite_fga_member_tuples(
        user_id, plan.current_leaf_tenant_id, plan.target_leaf_tenant_id,
    )
    await UserTenantSyncService._invalidate_redis_caches(user_id)
    await UserTenantSyncService._write_relocation_audit(
        user_id=user_id,
        action=TenantAuditAction.USER_TENANT_RELOCATED,
        audit_tenant_id=plan.target_leaf_tenant_id,
        old_tenant_id=plan.current_leaf_tenant_id,
        new_tenant_id=plan.target_leaf_tenant_id,
        owned_count=plan.retained_resource_count,
        trigger=f"{UserTenantSyncTrigger.DEPT_CHANGE.value}:maintenance_force",
        reason="maintenance_force_retain_owned_resources",
    )
    return {"changed": True, "leaf_tenant_id": plan.target_leaf_tenant_id}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Move admin while retaining owned resources.")
    user_group = parser.add_mutually_exclusive_group(required=True)
    user_group.add_argument("--user-id", type=int, help="Migration user internal ID")
    user_group.add_argument("--username", help="Migration user exact username")
    department_group = parser.add_mutually_exclusive_group(required=True)
    department_group.add_argument("--department-id", type=int, help="Target department internal ID")
    department_group.add_argument("--dept-id", help="Target department business ID")
    parser.add_argument("--apply", action="store_true", help="Perform writes after preflight")
    return parser


async def run(args: argparse.Namespace) -> int:
    plan = await build_plan(
        user_id=args.user_id,
        username=args.username,
        department_id=args.department_id,
        dept_id=args.dept_id,
    )
    if not args.apply:
        print(json.dumps({"dry_run": True, **plan.summary()}, ensure_ascii=False, indent=2))
        return 0
    result = await apply_plan(plan)
    print(json.dumps({"dry_run": False, **plan.summary(), "result": result}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except PreflightError as exc:
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return 2
    except Exception:
        logger.exception("Admin department maintenance migration failed")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

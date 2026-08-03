#!/usr/bin/env python3
"""List platform Super Admin users (AdminRole / role_id=1) with full profile data.

Usage:

    PYTHONPATH=./ .venv/bin/python scripts/list_admin_users.py
    bash scripts/list_admin_users.sh
    bash scripts/list_admin_users.sh --brief
    bash scripts/list_admin_users.sh --include-deleted

Queries ``userrole`` for ``role_id=AdminRole``, then loads the full ``user`` row
plus related ``userrole``/``role``, ``user_tenant``/``tenant``, ``user_department``/
``department``, and ``user_group``/``group`` records.

Uses ``bypass_tenant_filter()`` so all tenants' admin rows are visible.
Password hashes are never printed in plain text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.constants import AdminRole  # noqa: E402
from bisheng.database.models.department import Department, UserDepartment  # noqa: E402
from bisheng.database.models.group import Group  # noqa: E402
from bisheng.database.models.role import Role  # noqa: E402
from bisheng.database.models.tenant import Tenant, UserTenant  # noqa: E402
from bisheng.database.models.user_group import UserGroup  # noqa: E402
from bisheng.user.domain.models.user import User  # noqa: E402
from bisheng.user.domain.models.user_role import UserRole  # noqa: E402

_PASSWORD_REDACTED = "***REDACTED***"


def _normalize_scalar_rows(rows: list[Any]) -> list[int]:
    out: list[int] = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            out.append(int(row[0]))
        else:
            out.append(int(row))
    return out


def _serialize_model(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(obj)


def _serialize_user(user: User) -> dict[str, Any]:
    data = _serialize_model(user)
    if data.get("password"):
        data["password"] = _PASSWORD_REDACTED
    return data


async def list_admin_users(*, include_deleted: bool) -> list[dict[str, Any]]:
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            admin_user_ids = _normalize_scalar_rows(
                (await session.exec(select(UserRole.user_id).where(UserRole.role_id == AdminRole).distinct())).all()
            )
            if not admin_user_ids:
                return []

            user_stmt = select(User).where(User.user_id.in_(admin_user_ids))
            if not include_deleted:
                user_stmt = user_stmt.where(User.delete == 0)
            users = (await session.exec(user_stmt.order_by(User.user_id))).all()
            if not users:
                return []

            user_ids = [int(u.user_id) for u in users if u.user_id is not None]

            user_roles = (
                await session.exec(
                    select(UserRole, Role)
                    .join(Role, Role.id == UserRole.role_id)
                    .where(UserRole.user_id.in_(user_ids))
                    .order_by(UserRole.user_id, UserRole.role_id)
                )
            ).all()

            user_tenants = (
                await session.exec(
                    select(UserTenant, Tenant)
                    .join(Tenant, Tenant.id == UserTenant.tenant_id)
                    .where(UserTenant.user_id.in_(user_ids))
                    .order_by(UserTenant.user_id, UserTenant.tenant_id)
                )
            ).all()

            user_departments = (
                await session.exec(
                    select(UserDepartment, Department)
                    .join(Department, Department.id == UserDepartment.department_id)
                    .where(UserDepartment.user_id.in_(user_ids))
                    .order_by(UserDepartment.user_id, UserDepartment.department_id)
                )
            ).all()

            user_groups = (
                await session.exec(
                    select(UserGroup, Group)
                    .join(Group, Group.id == UserGroup.group_id)
                    .where(UserGroup.user_id.in_(user_ids))
                    .order_by(UserGroup.user_id, UserGroup.group_id)
                )
            ).all()

    roles_by_user: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for user_role, role in user_roles:
        roles_by_user[int(user_role.user_id)].append(
            {
                "user_role": _serialize_model(user_role),
                "role": _serialize_model(role),
                "is_super_admin": int(user_role.role_id) == AdminRole,
            }
        )

    tenants_by_user: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for user_tenant, tenant in user_tenants:
        tenants_by_user[int(user_tenant.user_id)].append(
            {
                "user_tenant": _serialize_model(user_tenant),
                "tenant": _serialize_model(tenant),
            }
        )

    departments_by_user: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for user_department, department in user_departments:
        departments_by_user[int(user_department.user_id)].append(
            {
                "user_department": _serialize_model(user_department),
                "department": _serialize_model(department),
            }
        )

    groups_by_user: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for user_group, group in user_groups:
        groups_by_user[int(user_group.user_id)].append(
            {
                "user_group": _serialize_model(user_group),
                "group": _serialize_model(group),
            }
        )

    admins: list[dict[str, Any]] = []
    for user in users:
        uid = int(user.user_id)
        admin_role_rows = [item for item in roles_by_user.get(uid, []) if item["is_super_admin"]]
        admins.append(
            {
                "user": _serialize_user(user),
                "admin_roles": admin_role_rows,
                "roles": roles_by_user.get(uid, []),
                "tenants": tenants_by_user.get(uid, []),
                "departments": departments_by_user.get(uid, []),
                "groups": groups_by_user.get(uid, []),
            }
        )
    return admins


def _print_brief_table(admins: list[dict[str, Any]]) -> None:
    if not admins:
        print("No Super Admin users found.")
        return

    rows: list[dict[str, Any]] = []
    for item in admins:
        user = item["user"]
        admin_roles = item.get("admin_roles") or []
        tenant_ids = sorted(
            {
                int(r["user_role"]["tenant_id"])
                for r in admin_roles
                if r.get("user_role", {}).get("tenant_id") is not None
            }
        )
        rows.append(
            {
                "user_id": user.get("user_id"),
                "user_name": user.get("user_name"),
                "email": user.get("email"),
                "phone_number": user.get("phone_number"),
                "tenant_ids": ",".join(str(t) for t in tenant_ids),
                "delete": user.get("delete"),
                "source": user.get("source"),
            }
        )

    headers = ("user_id", "user_name", "email", "phone_number", "tenant_ids", "delete", "source")
    widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            widths[h] = max(widths[h], len(str(row.get(h) or "")))

    def fmt_row(values: tuple[str, ...]) -> str:
        return "  ".join(val.ljust(widths[h]) for val, h in zip(values, headers, strict=True))

    print(fmt_row(headers))
    print(fmt_row(tuple("-" * widths[h] for h in headers)))
    for row in rows:
        print(fmt_row(tuple(str(row.get(h) if row.get(h) is not None else "") for h in headers)))
    print(f"\nTotal: {len(rows)} Super Admin user(s). Use default JSON output for full details.")


async def run(include_deleted: bool, brief: bool) -> int:
    admins = await list_admin_users(include_deleted=include_deleted)
    if brief:
        _print_brief_table(admins)
    else:
        print(json.dumps(admins, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-deleted",
        action="store_true",
        help="Include disabled users (user.delete=1).",
    )
    parser.add_argument(
        "--brief",
        action="store_true",
        help="Print a compact table instead of full JSON.",
    )
    args = parser.parse_args()
    return asyncio.run(run(include_deleted=args.include_deleted, brief=args.brief))


if __name__ == "__main__":
    sys.exit(main())

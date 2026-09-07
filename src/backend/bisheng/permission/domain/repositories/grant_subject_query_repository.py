from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import column, select, table

from bisheng.core import database as database_module
from bisheng.core.context import tenant as tenant_context

_ROOT_TENANT_ID = 1

_TENANT = table(
    "tenant",
    column("id"),
    column("root_dept_id"),
    column("status"),
)
_DEPARTMENT = table(
    "department",
    column("id"),
    column("tenant_id"),
    column("path"),
    column("status"),
    column("is_tenant_root"),
    column("mounted_tenant_id"),
)
_USER_DEPARTMENT = table(
    "user_department",
    column("department_id"),
    column("user_id"),
)
_GROUP = table(
    "group",
    column("id"),
    column("tenant_id"),
)
_USER_GROUP = table(
    "user_group",
    column("group_id"),
    column("user_id"),
    column("tenant_id"),
    column("is_group_admin"),
)
_USER = table(
    "user",
    column("user_id"),
    column("delete"),
)
_USER_TENANT = table(
    "user_tenant",
    column("user_id"),
    column("tenant_id"),
    column("status"),
    column("is_active"),
)


@dataclass(frozen=True, slots=True)
class _DepartmentScope:
    positive_prefix: str | None
    exclude_prefixes: tuple[str, ...]
    tenant_id: int


def _department_scope_predicates(scope: _DepartmentScope):
    predicates = [_DEPARTMENT.c.status == "active"]
    if scope.positive_prefix is not None:
        predicates.append(_DEPARTMENT.c.path.like(f"{scope.positive_prefix}%"))
    else:
        predicates.append(_DEPARTMENT.c.tenant_id == scope.tenant_id)
    predicates.extend(~_DEPARTMENT.c.path.like(f"{prefix}%") for prefix in scope.exclude_prefixes)
    return predicates


def _row_value(row, key: str, index: int = 0):
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping[key]
    if isinstance(row, (tuple, list)):
        return row[index]
    return row


class GrantSubjectQueryRepository:
    """Expand authoritative OpenFGA subjects without importing business ORM models."""

    @staticmethod
    async def _resolve_department_scope(session, tenant_id: int) -> _DepartmentScope | None:
        tenant_row = (
            await session.exec(
                select(_TENANT.c.root_dept_id).where(
                    _TENANT.c.id == tenant_id,
                    _TENANT.c.status == "active",
                )
            )
        ).first()
        if tenant_row is None:
            return None

        root_path = None
        root_dept_id = _row_value(tenant_row, "root_dept_id")
        if root_dept_id is not None:
            root_row = (
                await session.exec(
                    select(_DEPARTMENT.c.path).where(
                        _DEPARTMENT.c.id == int(root_dept_id),
                        _DEPARTMENT.c.status == "active",
                    )
                )
            ).first()
            if root_row is not None:
                root_path = _row_value(root_row, "path")

        excluded: tuple[str, ...] = ()
        if root_path is not None and tenant_id == _ROOT_TENANT_ID:
            child_rows = (
                await session.exec(
                    select(_DEPARTMENT.c.path).where(
                        _DEPARTMENT.c.is_tenant_root == 1,
                        _DEPARTMENT.c.mounted_tenant_id.is_not(None),
                        _DEPARTMENT.c.mounted_tenant_id != _ROOT_TENANT_ID,
                        _DEPARTMENT.c.status == "active",
                    )
                )
            ).all()
            excluded = tuple(str(_row_value(row, "path")) for row in child_rows if _row_value(row, "path"))

        return _DepartmentScope(
            positive_prefix=str(root_path) if root_path is not None else None,
            exclude_prefixes=excluded,
            tenant_id=tenant_id,
        )

    async def resolve_exact_department_member_user_ids_batch(
        self,
        *,
        department_ids: set[int],
        tenant_id: int,
    ) -> dict[int, set[int]]:
        if not department_ids:
            return {}

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                scope = await self._resolve_department_scope(session, tenant_id)
                if scope is None:
                    return {}
                valid_rows = (
                    await session.exec(
                        select(_DEPARTMENT.c.id).where(
                            _DEPARTMENT.c.id.in_(department_ids),
                            *_department_scope_predicates(scope),
                        )
                    )
                ).all()
                valid_ids = {int(_row_value(row, "id")) for row in valid_rows}
                members = {department_id: set() for department_id in valid_ids}
                if not valid_ids:
                    return members

                member_rows = (
                    await session.exec(
                        select(_USER_DEPARTMENT.c.department_id, _USER_DEPARTMENT.c.user_id)
                        .select_from(
                            _USER_DEPARTMENT.join(
                                _DEPARTMENT,
                                _DEPARTMENT.c.id == _USER_DEPARTMENT.c.department_id,
                            )
                        )
                        .where(
                            _USER_DEPARTMENT.c.department_id.in_(valid_ids),
                            *_department_scope_predicates(scope),
                        )
                    )
                ).all()
                for row in member_rows:
                    members[int(_row_value(row, "department_id"))].add(int(_row_value(row, "user_id", 1)))
                return members

    async def resolve_user_group_member_user_ids_batch(
        self,
        *,
        group_ids: set[int],
        tenant_id: int,
    ) -> dict[int, set[int]]:
        return await self._resolve_user_group_user_ids_batch(
            group_ids=group_ids,
            tenant_id=tenant_id,
            admins_only=False,
        )

    async def resolve_user_group_admin_user_ids_batch(
        self,
        *,
        group_ids: set[int],
        tenant_id: int,
    ) -> dict[int, set[int]]:
        return await self._resolve_user_group_user_ids_batch(
            group_ids=group_ids,
            tenant_id=tenant_id,
            admins_only=True,
        )

    @staticmethod
    async def _resolve_user_group_user_ids_batch(
        *,
        group_ids: set[int],
        tenant_id: int,
        admins_only: bool,
    ) -> dict[int, set[int]]:
        if not group_ids:
            return {}

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                valid_rows = (
                    await session.exec(
                        select(_GROUP.c.id)
                        .select_from(_GROUP.join(_TENANT, _TENANT.c.id == _GROUP.c.tenant_id))
                        .where(
                            _GROUP.c.id.in_(group_ids),
                            _GROUP.c.tenant_id == tenant_id,
                            _TENANT.c.status == "active",
                        )
                    )
                ).all()
                valid_ids = {int(_row_value(row, "id")) for row in valid_rows}
                users = {group_id: set() for group_id in valid_ids}
                if not valid_ids:
                    return users

                statement = select(_USER_GROUP.c.group_id, _USER_GROUP.c.user_id).where(
                    _USER_GROUP.c.group_id.in_(valid_ids),
                    _USER_GROUP.c.tenant_id == tenant_id,
                )
                if admins_only:
                    statement = statement.where(_USER_GROUP.c.is_group_admin == 1)
                rows = (await session.exec(statement)).all()
                for row in rows:
                    users[int(_row_value(row, "group_id"))].add(int(_row_value(row, "user_id", 1)))
                return users

    @staticmethod
    async def filter_active_user_ids_in_tenant(
        *,
        user_ids: set[int],
        tenant_id: int,
    ) -> set[int]:
        if not user_ids:
            return set()

        with tenant_context.bypass_tenant_filter():
            async with database_module.get_async_db_session() as session:
                rows = (
                    await session.exec(
                        select(_USER.c.user_id)
                        .select_from(
                            _USER.join(_USER_TENANT, _USER_TENANT.c.user_id == _USER.c.user_id).join(
                                _TENANT,
                                _TENANT.c.id == _USER_TENANT.c.tenant_id,
                            )
                        )
                        .where(
                            _USER.c.user_id.in_(user_ids),
                            _USER.c.delete == 0,
                            _USER_TENANT.c.tenant_id == tenant_id,
                            _USER_TENANT.c.status == "active",
                            _USER_TENANT.c.is_active == 1,
                            _TENANT.c.status == "active",
                        )
                    )
                ).all()
                return {int(_row_value(row, "user_id")) for row in rows}

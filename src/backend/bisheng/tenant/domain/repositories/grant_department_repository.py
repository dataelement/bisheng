"""Department grant candidates inside a tenant's authoritative root subtree.

Mounted tenants share the original organisation tree: a department's storage
tenant and physical parent do not identify the tenant it is grantable within.
All reads bypass the automatic storage-tenant filter and apply the verified
root pointer, mount metadata, storage tenant, and optional resource binding.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.database.subject_search import exact_id_priority, subject_match_condition
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant

_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class DepartmentGrantBoundary:
    storage_tenant_id: int
    path: str


def _valid_path(path: str) -> bool:
    parts = path.strip("/").split("/")
    return path == f"/{'/'.join(parts)}/" and all(
        part.isascii() and part.isdecimal() and int(part) > 0 for part in parts
    )


class GrantDepartmentRepository:
    @staticmethod
    async def _boundary(session, scope) -> DepartmentGrantBoundary | None:
        row = (
            await session.exec(
                select(Tenant, Department)
                .join(Department, Department.id == Tenant.root_dept_id)
                .where(Tenant.id == scope.tenant_id, Tenant.status == "active", Department.status == "active")
            )
        ).first()
        if row is None:
            return None
        tenant, root = row
        if not root.tenant_id or not _valid_path(root.path) or not root.path.endswith(f"/{root.id}/"):
            return None
        if root.is_tenant_root:
            if root.mounted_tenant_id != tenant.id or root.parent_id is None:
                return None
        elif root.mounted_tenant_id is not None or root.parent_id is not None or root.tenant_id != tenant.id:
            return None

        path = root.path
        if scope.department_path is not None:
            confined = scope.department_path
            if not _valid_path(confined):
                return None
            if confined.startswith(path):
                path = confined
            elif not path.startswith(confined):
                return None
        return DepartmentGrantBoundary(storage_tenant_id=int(root.tenant_id), path=path)

    @staticmethod
    def _departments(boundary: DepartmentGrantBoundary):
        return select(Department).where(
            Department.tenant_id == boundary.storage_tenant_id,
            Department.status == "active",
            col(Department.path).like(f"{boundary.path}%"),
        )

    @classmethod
    async def _children_existence(cls, session, boundary, department_ids: list[int]) -> set[int]:
        result: set[int] = set()
        for start in range(0, len(department_ids), _BATCH_SIZE):
            statement = select(Department.parent_id).where(
                cls._departments(boundary).whereclause,
                col(Department.parent_id).in_(department_ids[start : start + _BATCH_SIZE]),
            )
            rows = (await session.exec(statement.distinct())).all()
            result.update(int(row) for row in rows)
        return result

    @classmethod
    async def layer(cls, scope, *, parent_id: int | None) -> tuple[list[Department], set[int]]:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                boundary = await cls._boundary(session, scope)
                if boundary is None:
                    return [], set()
                statement = cls._departments(boundary)
                if parent_id is None:
                    statement = statement.where(Department.path == boundary.path)
                else:
                    parent = (await session.exec(statement.where(Department.id == parent_id))).first()
                    if parent is None:
                        return [], set()
                    statement = statement.where(Department.parent_id == parent_id)
                rows = list((await session.exec(statement.order_by(col(Department.id)))).all())
                children = await cls._children_existence(session, boundary, [int(row.id) for row in rows])
        return rows, children

    @classmethod
    async def search(
        cls, scope, *, keyword: str, limit: int
    ) -> tuple[DepartmentGrantBoundary | None, list[Department]]:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                boundary = await cls._boundary(session, scope)
                if boundary is None:
                    return None, []
                statement = (
                    cls._departments(boundary)
                    .where(
                        subject_match_condition(
                            Department.id, Department.name, Department.external_id, keyword, name_prefix=False
                        )
                    )
                    .order_by(exact_id_priority(Department.external_id, keyword), col(Department.id))
                    .limit(limit)
                )
                return boundary, list((await session.exec(statement)).all())

    @classmethod
    async def get(cls, scope, *, department_id: int) -> tuple[DepartmentGrantBoundary | None, Department | None]:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                boundary = await cls._boundary(session, scope)
                if boundary is None:
                    return None, None
                row = (await session.exec(cls._departments(boundary).where(Department.id == department_id))).first()
                return boundary, row

    @classmethod
    async def forest(
        cls, boundary: DepartmentGrantBoundary, seeds: list[Department]
    ) -> tuple[list[Department], set[int]]:
        needed = sorted({int(part) for row in seeds for part in row.path.split("/") if part.isdigit()})
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows: list[Department] = []
                for start in range(0, len(needed), _BATCH_SIZE):
                    statement = cls._departments(boundary).where(
                        col(Department.id).in_(needed[start : start + _BATCH_SIZE])
                    )
                    rows.extend((await session.exec(statement)).all())
                children = await cls._children_existence(session, boundary, [int(row.id) for row in rows])
        return rows, children

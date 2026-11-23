"""Business-subtree facts for a physically shared organization directory."""

from sqlmodel import select

from bisheng.common.errcode.department import DepartmentPermissionDeniedError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.tenant import Tenant
from bisheng.department.domain.repositories.policy_scope_repository import PolicyScopeRepository
from bisheng.department.domain.schemas.directory_scope import DirectoryScope, current_directory_scope


def directory_condition():
    scope = current_directory_scope.get()
    if scope is None:
        return True
    condition = (Department.tenant_id == scope.storage_tenant_id) & Department.path.like(f"{scope.root_path}%")
    for excluded in scope.excluded_paths:
        condition &= ~Department.path.like(f"{excluded}%")
    return condition


class DirectoryRepository:
    @staticmethod
    async def scope(tenant_id):
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                tenant = await session.get(Tenant, tenant_id)
                if tenant is None or tenant.status != "active":
                    raise DepartmentPermissionDeniedError()
                root = await session.get(Department, tenant.root_dept_id) if tenant.root_dept_id else None
                if root is None:
                    roots = (
                        await session.exec(
                            select(Department).where(
                                Department.tenant_id == tenant_id,
                                Department.parent_id.is_(None),
                                Department.is_deleted == 0,
                            )
                        )
                    ).all()
                    if tenant.root_dept_id is not None or len(roots) != 1:
                        raise DepartmentPermissionDeniedError()
                    root = roots[0]
                facts = await PolicyScopeRepository.department(root.id, session=session)
                if facts.business_tenant_id != tenant_id:
                    raise DepartmentPermissionDeniedError()
                mounts = (
                    await session.exec(
                        select(Department).where(
                            Department.tenant_id == facts.storage_tenant_id,
                            Department.path.like(f"{root.path}%"),
                            Department.is_tenant_root == 1,
                            Department.id != root.id,
                        )
                    )
                ).all()
                # Descendant mounts, including disabled tenants, are never owned by the parent view.
                excluded = tuple(row.path for row in mounts)
                if any(not path or not path.endswith("/") for path in excluded):
                    raise DepartmentPermissionDeniedError()
                return DirectoryScope(tenant_id, facts.storage_tenant_id, root.id, root.path, excluded)

    @staticmethod
    async def require_department(department_id):
        scope = current_directory_scope.get()
        if scope is None:
            return
        facts = await PolicyScopeRepository.directory_department(int(department_id))
        if (
            facts.business_tenant_id != scope.tenant_id
            or facts.storage_tenant_id != scope.storage_tenant_id
            or not scope.contains(facts.path)
        ):
            raise DepartmentPermissionDeniedError()

    @staticmethod
    async def children_existence(ids, include_archived=False):
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(Department.parent_id).where(
                        Department.parent_id.in_(ids),
                        Department.status.in_(["active", "archived"] if include_archived else ["active"]),
                        directory_condition(),
                    )
                )
            ).all()
            return set(rows)

    @staticmethod
    async def primary_for_identity(user_id, home_tenant_id):
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows = (
                    await session.exec(
                        select(UserDepartment).where(UserDepartment.user_id == user_id, UserDepartment.is_primary == 1)
                    )
                ).all()
                if not rows:
                    return []
                if len(rows) != 1:
                    raise DepartmentPermissionDeniedError()
                department = await session.get(Department, rows[0].department_id)
                if department is None:
                    raise DepartmentPermissionDeniedError()
                facts = await PolicyScopeRepository.department(department.id, session=session)
                if facts.business_tenant_id != home_tenant_id:
                    raise DepartmentPermissionDeniedError()
                return [{"id": department.id, "dept_id": department.dept_id, "name": department.name}]

    @staticmethod
    def scope_sync(tenant_id):
        with bypass_tenant_filter():
            with get_sync_db_session() as session:
                tenant = session.get(Tenant, tenant_id)
                if tenant is None or tenant.status != "active":
                    raise DepartmentPermissionDeniedError()
                root = session.get(Department, tenant.root_dept_id) if tenant.root_dept_id else None
                if root is None:
                    roots = session.exec(
                        select(Department).where(
                            Department.tenant_id == tenant_id,
                            Department.parent_id.is_(None),
                            Department.is_deleted == 0,
                        )
                    ).all()
                    if tenant.root_dept_id is not None or len(roots) != 1:
                        raise DepartmentPermissionDeniedError()
                    root = roots[0]
                facts = PolicyScopeRepository.department_sync(root.id, session=session)
                if facts.business_tenant_id != tenant_id:
                    raise DepartmentPermissionDeniedError()
                mounts = session.exec(
                    select(Department).where(
                        Department.tenant_id == facts.storage_tenant_id,
                        Department.path.like(f"{root.path}%"),
                        Department.is_tenant_root == 1,
                        Department.id != root.id,
                    )
                ).all()
                return DirectoryScope(
                    tenant_id, facts.storage_tenant_id, root.id, root.path, tuple(row.path for row in mounts)
                )

    @staticmethod
    def require_subtree(path):
        scope = current_directory_scope.get()
        if scope is not None and any(excluded.startswith(path) for excluded in scope.excluded_paths):
            raise DepartmentPermissionDeniedError()

    @staticmethod
    async def root_department(scope):
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                row = await session.get(Department, scope.root_id)
                if row is None or row.tenant_id != scope.storage_tenant_id or row.path != scope.root_path:
                    raise DepartmentPermissionDeniedError()
                return row

    @staticmethod
    async def display_records(tenant_id, department_ids):
        from bisheng.department.domain.schemas.directory_scope import DepartmentDisplayRecord

        if not department_ids:
            return {}
        scope = await DirectoryRepository.scope(tenant_id)
        condition = (Department.tenant_id == scope.storage_tenant_id) & Department.path.like(f"{scope.root_path}%")
        for excluded in scope.excluded_paths:
            condition &= ~Department.path.like(f"{excluded}%")
        records = {}
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                ids = sorted(set(department_ids))
                for offset in range(0, len(ids), 500):
                    rows = (
                        await session.exec(
                            select(Department).where(
                                Department.id.in_(ids[offset : offset + 500]), condition, Department.is_deleted == 0
                            )
                        )
                    ).all()
                    records.update(
                        {
                            row.id: DepartmentDisplayRecord(row.id, row.name, tenant_id, row.tenant_id, row.status)
                            for row in rows
                        }
                    )
        return records

    @staticmethod
    async def active_departments(tenant_id, department_ids):
        """Active departments inside one business tenant's organization directory.

        Department rows stay on the directory storage tenant. A query filtered by
        the business tenant id misses a department the organization picker shows.
        """
        if not department_ids:
            return []
        scope = await DirectoryRepository.scope(tenant_id)
        condition = (Department.tenant_id == scope.storage_tenant_id) & Department.path.like(f"{scope.root_path}%")
        for excluded in scope.excluded_paths:
            condition &= ~Department.path.like(f"{excluded}%")
        ids = list(dict.fromkeys(int(department_id) for department_id in department_ids))
        found = []
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                for offset in range(0, len(ids), 500):
                    rows = (
                        await session.exec(
                            select(Department).where(
                                Department.id.in_(ids[offset : offset + 500]),
                                condition,
                                Department.status == "active",
                                Department.is_deleted == 0,
                            )
                        )
                    ).all()
                    found.extend(rows)
        return found

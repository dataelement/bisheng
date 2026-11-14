"""Narrow reads of authoritative department paths, including mounted storage."""

from dataclasses import dataclass

from sqlmodel import select

from bisheng.common.errcode.role import RolePolicyUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant


@dataclass(frozen=True)
class DepartmentPolicyFacts:
    department_id: int
    business_tenant_id: int
    storage_tenant_id: int
    ancestor_ids: tuple[int, ...]
    path: str
    version: tuple[int, ...]


def _resolve(
    rows: list[Department], tenants: dict[int, Tenant], home_tenant_id=None, for_binding_cleanup=False
) -> DepartmentPolicyFacts | None:
    ordered = list(reversed(rows))
    if not ordered:
        raise RolePolicyUnavailableError()
    storage = int(ordered[0].tenant_id or 0)
    root = tenants.get(storage)
    if root is None or root.root_dept_id not in (None, ordered[0].id):
        raise RolePolicyUnavailableError()
    business = storage
    boundary = 0
    for index, row in enumerate(ordered):
        expected_path = "/" + "/".join(str(part.id) for part in ordered[: index + 1]) + "/"
        if (
            row.tenant_id != storage
            or row.path != expected_path
            or row.parent_id != (ordered[index - 1].id if index else None)
        ):
            raise RolePolicyUnavailableError()
        if row.is_tenant_root:
            mounted = tenants.get(int(row.mounted_tenant_id or 0))
            if index == 0 or mounted is None or mounted.root_dept_id != row.id:
                raise RolePolicyUnavailableError()
            business, boundary = int(mounted.id), index
        elif row.mounted_tenant_id is not None:
            raise RolePolicyUnavailableError()
    if home_tenant_id is not None and business != home_tenant_id:
        return None  # A proven foreign affiliation cannot alter the home policy.
    inactive_department = any(row.status != "active" or row.is_deleted for row in ordered)
    if not for_binding_cleanup and (
        root.status != "active"
        or any(
            row.status != "active"
            or row.is_deleted
            or row.permission_projection_state != "CURRENT"
            or (row.is_tenant_root and tenants[int(row.mounted_tenant_id)].status != "active")
            for row in ordered
        )
    ):
        raise RolePolicyUnavailableError()
    return DepartmentPolicyFacts(
        int(ordered[-1].id),
        business,
        storage,
        () if for_binding_cleanup and inactive_department else tuple(int(row.id) for row in ordered[boundary:]),
        ordered[-1].path,
        tuple(int(row.permission_projection_version) for row in ordered),
    )


def _next(rows: list[Department], row: Department | None) -> int | None:
    if row is None or row.id in {part.id for part in rows} or len(rows) >= 128:
        raise RolePolicyUnavailableError()
    rows.append(row)
    return row.parent_id


def _tenant_ids(rows: list[Department]) -> set[int]:
    return {int(rows[-1].tenant_id or 0), *(int(row.mounted_tenant_id) for row in rows if row.mounted_tenant_id)}


class PolicyScopeRepository:
    @staticmethod
    async def edit_department(department_id):
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return await session.get(Department, department_id)

    @staticmethod
    def business_departments_sync(business_tenant_id, *, session=None):
        """Directory inventory batches paths; per-call DSH policy reads use exact subject facts."""
        if session is None:
            with get_sync_db_session() as owned_session:
                return PolicyScopeRepository.business_departments_sync(business_tenant_id, session=owned_session)
        with bypass_tenant_filter():
            tenant = session.get(Tenant, business_tenant_id)
            if tenant is None or tenant.status != "active":
                raise RolePolicyUnavailableError()
            root = session.get(Department, tenant.root_dept_id) if tenant.root_dept_id else None
            if root is None:
                # Legacy Root may not carry root_dept_id; only its exact storage
                # root is authoritative, never a name/path guess.
                roots = session.exec(
                    select(Department).where(
                        Department.tenant_id == business_tenant_id,
                        Department.parent_id.is_(None),
                        Department.is_deleted == 0,
                    )
                ).all()
                if tenant.root_dept_id is not None or len(roots) != 1:
                    raise RolePolicyUnavailableError()
                root = roots[0]
            if (
                PolicyScopeRepository.department_sync(root.id, session=session, home_tenant_id=business_tenant_id)
                is None
            ):
                raise RolePolicyUnavailableError()
            rows = list(
                session.exec(
                    select(Department)
                    .where(Department.tenant_id == root.tenant_id, Department.path.like(f"{root.path}%"))
                    .order_by(Department.sort_order, Department.id)
                ).all()
            )
            ancestors = list(
                session.exec(
                    select(Department).where(Department.id.in_([int(part) for part in root.path.split("/") if part]))
                ).all()
            )
            by_id = {row.id: row for row in [*ancestors, *rows]}
            tenant_ids = {
                int(root.tenant_id),
                *(int(row.mounted_tenant_id) for row in by_id.values() if row.mounted_tenant_id),
            }
            tenants = {row.id: row for row in session.exec(select(Tenant).where(Tenant.id.in_(tenant_ids))).all()}
            result = []
            for row in rows:
                if row.status != "active" or row.is_deleted:
                    continue
                lineage = []
                current = row.id
                while current is not None:
                    current = _next(lineage, by_id.get(current))
                if _resolve(lineage, tenants, business_tenant_id) is not None:
                    result.append(row)
            return result

    @staticmethod
    async def defaults(department_ids):
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows = (await session.exec(select(Department).where(Department.id.in_(department_ids)))).all()
                return {row.id: list(row.default_role_ids or []) for row in rows}

    @staticmethod
    async def department(
        department_id: int, *, session=None, home_tenant_id=None, for_binding_cleanup=False
    ) -> DepartmentPolicyFacts | None:
        if session is None:
            async with get_async_db_session() as owned_session:
                return await PolicyScopeRepository.department(
                    department_id,
                    session=owned_session,
                    home_tenant_id=home_tenant_id,
                    for_binding_cleanup=for_binding_cleanup,
                )
        with bypass_tenant_filter():
            rows: list[Department] = []
            current = department_id
            while current is not None:
                row = (await session.exec(select(Department).where(Department.id == current))).first()
                current = _next(rows, row)
            tenants = (await session.exec(select(Tenant).where(Tenant.id.in_(_tenant_ids(rows))))).all()
        return _resolve(rows, {int(row.id): row for row in tenants}, home_tenant_id, for_binding_cleanup)

    @staticmethod
    def department_sync(
        department_id: int, *, session=None, home_tenant_id=None, for_binding_cleanup=False
    ) -> DepartmentPolicyFacts | None:
        if session is None:
            with get_sync_db_session() as owned_session:
                return PolicyScopeRepository.department_sync(
                    department_id,
                    session=owned_session,
                    home_tenant_id=home_tenant_id,
                    for_binding_cleanup=for_binding_cleanup,
                )
        with bypass_tenant_filter():
            rows: list[Department] = []
            current = department_id
            while current is not None:
                row = session.exec(select(Department).where(Department.id == current)).first()
                current = _next(rows, row)
            tenants = session.exec(select(Tenant).where(Tenant.id.in_(_tenant_ids(rows)))).all()
        return _resolve(rows, {int(row.id): row for row in tenants}, home_tenant_id, for_binding_cleanup)

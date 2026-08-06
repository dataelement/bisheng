from __future__ import annotations

from sqlalchemy import exists, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant, UserTenant
from bisheng.permission.domain.models.grant_subject_user import (
    GrantSubjectDepartment,
    GrantSubjectUserCandidate,
    GrantSubjectUserDepartmentLink,
)
from bisheng.permission.domain.repositories.interfaces.grant_subject_user_repository import (
    GrantSubjectUserRepository,
)
from bisheng.user.domain.models.user import User


class GrantSubjectUserRepositoryImpl(
    BaseRepositoryImpl[User, int],
    GrantSubjectUserRepository,
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, User)

    async def list_visible_departments(self, *, tenant_id: int) -> list[GrantSubjectDepartment]:
        tenant = (
            await self.session.exec(
                select(Tenant).where(
                    Tenant.id == tenant_id,
                    Tenant.status == "active",
                )
            )
        ).first()
        if tenant is None:
            return []

        root_department = None
        if tenant.root_dept_id is not None:
            root_department = (
                await self.session.exec(
                    select(Department).where(
                        Department.id == int(tenant.root_dept_id),
                        Department.status == "active",
                    )
                )
            ).first()

        if root_department is None:
            statement = select(Department).where(
                Department.tenant_id == tenant_id,
                Department.status == "active",
            )
        else:
            statement = select(Department).where(
                Department.path.like(f"{root_department.path}%"),
                Department.status == "active",
            )
            if tenant_id == ROOT_TENANT_ID:
                child_path_rows = (
                    await self.session.exec(
                        select(Department.path).where(
                            Department.is_tenant_root == 1,
                            Department.mounted_tenant_id.is_not(None),
                            Department.mounted_tenant_id != ROOT_TENANT_ID,
                            Department.status == "active",
                        )
                    )
                ).all()
                for child_path_row in child_path_rows:
                    child_path = child_path_row if isinstance(child_path_row, str) else child_path_row[0]
                    statement = statement.where(~Department.path.like(f"{child_path}%"))

        departments = list(
            (
                await self.session.exec(
                    statement.order_by(Department.sort_order, Department.id)
                )
            ).all()
        )
        return [
            GrantSubjectDepartment(
                department_id=int(department.id),
                dept_id=department.dept_id,
                name=department.name,
                parent_id=int(department.parent_id) if department.parent_id is not None else None,
                path=department.path,
            )
            for department in departments
            if department.id is not None
        ]

    async def list_candidates(
        self,
        *,
        tenant_id: int,
        visible_department_ids: tuple[int, ...],
        keyword: str,
        page: int,
        page_size: int,
        department_id: int | None,
        unassigned: bool,
    ) -> list[GrantSubjectUserCandidate]:
        statement = (
            select(User)
            .join(UserTenant, UserTenant.user_id == User.user_id)
            .join(Tenant, Tenant.id == UserTenant.tenant_id)
            .where(
                UserTenant.tenant_id == tenant_id,
                UserTenant.status == "active",
                Tenant.status == "active",
                User.delete == 0,
            )
        )
        if department_id is not None:
            statement = statement.join(
                UserDepartment,
                UserDepartment.user_id == User.user_id,
            ).where(UserDepartment.department_id == department_id)
        elif unassigned and visible_department_ids:
            visible_assignment_exists = exists().where(
                UserDepartment.user_id == User.user_id,
                col(UserDepartment.department_id).in_(visible_department_ids),
            )
            statement = statement.where(~visible_assignment_exists)

        normalized_keyword = keyword.strip()
        if normalized_keyword:
            keyword_pattern = f"%{normalized_keyword}%"
            statement = statement.where(
                or_(
                    col(User.user_name).like(keyword_pattern),
                    col(User.external_id).like(keyword_pattern),
                )
            )

        statement = (
            statement.order_by(User.user_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        users = list((await self.session.exec(statement)).all())
        return [
            GrantSubjectUserCandidate(
                user_id=int(user.user_id),
                user_name=user.user_name,
                external_id=user.external_id,
            )
            for user in users
            if user.user_id is not None
        ]

    async def list_department_links(
        self,
        *,
        user_ids: tuple[int, ...],
        visible_department_ids: tuple[int, ...],
    ) -> list[GrantSubjectUserDepartmentLink]:
        if not user_ids or not visible_department_ids:
            return []
        links = list(
            (
                await self.session.exec(
                    select(UserDepartment).where(
                        col(UserDepartment.user_id).in_(user_ids),
                        col(UserDepartment.department_id).in_(visible_department_ids),
                    )
                )
            ).all()
        )
        return [
            GrantSubjectUserDepartmentLink(
                user_id=int(link.user_id),
                department_id=int(link.department_id),
                is_primary=int(link.is_primary or 0) == 1,
            )
            for link in links
        ]

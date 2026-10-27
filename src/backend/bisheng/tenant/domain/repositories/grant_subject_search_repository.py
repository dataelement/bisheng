"""Tenant-owned SQL for the existing resource grant candidate directory."""

from sqlmodel import col, func, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.database.subject_search import (
    exact_id_priority,
    numeric_id_priority,
    numeric_subject_match_condition,
    subject_match_condition,
)
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.group import Group
from bisheng.database.models.tenant import UserTenant
from bisheng.user.domain.models.user import User


class GrantSubjectSearchRepository:
    @staticmethod
    def _users(scope, keyword: str):
        in_tenant = (
            select(UserTenant.id)
            .where(
                UserTenant.user_id == User.user_id,
                UserTenant.tenant_id == scope.tenant_id,
                UserTenant.status == "active",
                UserTenant.is_active == 1,
            )
            .exists()
        )
        statement = select(User.user_id, User.user_name, User.external_id).where(User.delete == 0, in_tenant)
        if scope.department_path is not None:
            membership = (
                select(UserDepartment.id)
                .join(Department, Department.id == UserDepartment.department_id)
                .where(UserDepartment.user_id == User.user_id, Department.status == "active")
            )
            membership = membership.where(col(Department.path).like(f"{scope.department_path}%"))
            statement = statement.where(membership.exists())
        if keyword:
            statement = statement.where(
                subject_match_condition(User.user_id, User.user_name, User.external_id, keyword, name_prefix=True)
            )
        return statement

    @classmethod
    async def users(cls, scope, *, keyword: str, page: int = 1, page_size: int = 50):
        statement = cls._users(scope, keyword)
        if keyword:
            statement = statement.order_by(exact_id_priority(User.external_id, keyword))
        statement = statement.order_by(col(User.user_id).desc()).offset((page - 1) * page_size).limit(page_size)
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return list((await session.exec(statement)).all())

    @classmethod
    async def count_users(cls, scope, *, keyword: str):
        statement = select(func.count()).select_from(cls._users(scope, keyword).subquery())
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return int((await session.exec(statement)).one())

    @staticmethod
    def _groups(scope, keyword: str):
        statement = select(Group.id, Group.group_name).where(Group.tenant_id == scope.tenant_id)
        if keyword:
            statement = statement.where(numeric_subject_match_condition(Group.id, Group.group_name, keyword))
        return statement

    @classmethod
    async def groups(cls, scope, *, keyword: str, page: int, page_size: int):
        statement = cls._groups(scope, keyword)
        if keyword:
            statement = statement.order_by(numeric_id_priority(Group.id, keyword))
        statement = statement.order_by(col(Group.id).desc()).offset((page - 1) * page_size).limit(page_size)
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return list((await session.exec(statement)).all())

    @classmethod
    async def count_groups(cls, scope, *, keyword: str):
        statement = select(func.count()).select_from(cls._groups(scope, keyword).subquery())
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return int((await session.exec(statement)).one())

    @staticmethod
    async def departments(scope, *, keyword: str, limit: int):
        statement = select(Department).where(
            Department.tenant_id == scope.tenant_id,
            Department.status == "active",
            subject_match_condition(Department.id, Department.name, Department.external_id, keyword, name_prefix=False),
        )
        if scope.department_path is not None:
            statement = statement.where(col(Department.path).like(f"{scope.department_path}%"))
        statement = statement.order_by(exact_id_priority(Department.external_id, keyword), col(Department.id)).limit(
            limit
        )
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return list((await session.exec(statement)).all())

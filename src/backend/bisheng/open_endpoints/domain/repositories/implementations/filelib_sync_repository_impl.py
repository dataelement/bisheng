from __future__ import annotations

from sqlalchemy import and_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.tenant import UserTenant
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.open_endpoints.domain.repositories.interfaces.filelib_sync_repository import (
    FilelibSyncRepository,
)
from bisheng.user.domain.models.user import User


class FilelibSyncRepositoryImpl(
    BaseRepositoryImpl[KnowledgeFile, int],
    FilelibSyncRepository,
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, KnowledgeFile)

    async def find_user_by_id(self, user_id: int) -> User | None:
        result = await self.session.exec(
            select(User)
            .join(UserTenant, UserTenant.user_id == User.user_id)
            .join(UserDepartment, UserDepartment.user_id == User.user_id)
            .join(
                Department,
                and_(
                    Department.id == UserDepartment.department_id,
                    Department.tenant_id == UserTenant.tenant_id,
                ),
            )
            .where(
                User.user_id == user_id,
                User.delete == 0,
                UserTenant.status == "active",
                UserTenant.is_active == 1,
                Department.status == "active",
                Department.is_deleted == 0,
            )
            .distinct()
        )
        return result.first()

    async def find_primary_departments(self, user_id: int) -> list[UserDepartment]:
        result = await self.session.exec(
            select(UserDepartment)
            .join(Department, Department.id == UserDepartment.department_id)
            .where(
                UserDepartment.user_id == user_id,
                UserDepartment.is_primary == 1,
                Department.status == "active",
                Department.is_deleted == 0,
            )
            .order_by(UserDepartment.department_id.asc())
        )
        return list(result.all())

    async def find_department_by_id(self, department_id: int) -> Department | None:
        result = await self.session.exec(
            select(Department).where(
                Department.id == department_id,
                Department.status == "active",
                Department.is_deleted == 0,
            )
        )
        return result.first()

    async def find_knowledge_by_id(self, knowledge_id: int) -> Knowledge | None:
        result = await self.session.exec(
            select(Knowledge).where(
                Knowledge.id == knowledge_id,
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            )
        )
        return result.first()

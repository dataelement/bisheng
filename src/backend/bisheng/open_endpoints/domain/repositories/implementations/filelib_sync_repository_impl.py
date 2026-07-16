from __future__ import annotations

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.department import Department, UserDepartment
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScope,
)
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
        result = await self.session.exec(select(User).where(User.user_id == user_id, User.delete == 0))
        return result.first()

    async def find_primary_department(self, user_id: int) -> UserDepartment | None:
        result = await self.session.exec(
            select(UserDepartment).where(
                UserDepartment.user_id == user_id,
                UserDepartment.is_primary == 1,
            )
        )
        return result.first()

    async def find_department_by_id(self, department_id: int) -> Department | None:
        result = await self.session.exec(
            select(Department).where(
                Department.id == department_id,
                Department.status == "active",
                Department.is_deleted == 0,
            )
        )
        return result.first()

    async def find_department_by_name(self, name: str) -> Department | None:
        result = await self.session.exec(
            select(Department)
            .where(
                func.trim(Department.name) == name.strip(),
                Department.status == "active",
                Department.is_deleted == 0,
            )
            .order_by(Department.id.asc())
        )
        return result.first()

    async def find_department_space(self, department_id: int) -> DepartmentKnowledgeSpace | None:
        result = await self.session.exec(
            select(DepartmentKnowledgeSpace).where(
                DepartmentKnowledgeSpace.department_id == department_id,
            )
        )
        return result.first()

    async def find_public_space_by_name(self, name: str) -> Knowledge | None:
        result = await self.session.exec(
            select(Knowledge)
            .join(KnowledgeSpaceScope, Knowledge.id == KnowledgeSpaceScope.space_id)
            .where(
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                func.trim(Knowledge.name) == name.strip(),
                KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.PUBLIC.value,
            )
            .order_by(Knowledge.id.asc())
        )
        return result.first()

    async def find_knowledge_by_id(self, knowledge_id: int) -> Knowledge | None:
        return await self.session.get(Knowledge, knowledge_id)

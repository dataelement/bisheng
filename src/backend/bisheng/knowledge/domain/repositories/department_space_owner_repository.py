"""Serialize department ownership projection with canonical binding updates."""

from contextlib import asynccontextmanager

from sqlmodel import select

from bisheng.common.errcode.knowledge_space import SpaceAdminConflictError, SpaceNotFoundError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace


class DepartmentSpaceOwnerRepository:
    @staticmethod
    @asynccontextmanager
    async def lock_binding(
        space_id: int,
        *,
        expected_admin_user_id: int | None = None,
        excluded_admin_user_id: int | None = None,
    ):
        # The existing conditional UPDATE must wait for this row lock. Keep it
        # until the owner projection and membership restoration finish, so a
        # different binding cannot commit while an old owner is being projected.
        async with get_async_db_session() as session:
            async with session.begin():
                binding = (
                    await session.exec(
                        select(DepartmentKnowledgeSpace)
                        .where(DepartmentKnowledgeSpace.space_id == space_id)
                        .with_for_update()
                    )
                ).first()
                if binding is None:
                    raise SpaceNotFoundError()
                if expected_admin_user_id is not None and binding.admin_user_id != expected_admin_user_id:
                    raise SpaceAdminConflictError()
                if excluded_admin_user_id is not None and binding.admin_user_id == excluded_admin_user_id:
                    raise SpaceAdminConflictError()
                yield binding

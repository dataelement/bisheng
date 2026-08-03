"""Read-only dept-admin access helpers for member-owned personal knowledge spaces."""

from __future__ import annotations

from sqlmodel import col, select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import DepartmentDao, UserDepartment
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
)


async def aget_dept_admin_scoped_user_ids(admin_user_id: int) -> set[int] | None:
    """Return user ids under managed department subtrees; None if not a dept admin."""
    admin_depts = await DepartmentDao.aget_user_admin_departments(int(admin_user_id))
    if not admin_depts:
        return None

    internal_ids: set[int] = set()
    for dept in admin_depts:
        path = getattr(dept, "path", None) or ""
        if not path:
            continue
        subtree = await DepartmentDao.aget_subtree_ids(path)
        internal_ids.update(int(item) for item in subtree)
    if not internal_ids:
        return set()

    async with get_async_db_session() as session:
        stmt = select(UserDepartment.user_id).where(
            col(UserDepartment.department_id).in_(list(internal_ids)),
        )
        result = await session.exec(stmt)
        rows = result.all()
    return {int(user_id) for user_id in rows}


async def is_dept_admin_of_user(admin_user_id: int, target_user_id: int) -> bool:
    """True when target_user belongs to any department subtree managed by admin_user."""
    scoped_user_ids = await aget_dept_admin_scoped_user_ids(int(admin_user_id))
    if scoped_user_ids is None:
        return False
    return int(target_user_id) in scoped_user_ids


async def aget_member_personal_space_ids(scoped_user_ids: set[int]) -> set[int]:
    """Personal knowledge space ids owned by users in a dept-admin member scope."""
    if not scoped_user_ids:
        return set()
    owner_ids = sorted(int(user_id) for user_id in scoped_user_ids)
    async with get_async_db_session() as session:
        stmt = (
            select(KnowledgeSpaceScope.space_id)
            .join(Knowledge, Knowledge.id == KnowledgeSpaceScope.space_id)
            .where(
                KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.PERSONAL.value,
                KnowledgeSpaceScope.owner_type == KnowledgeSpaceOwnerTypeEnum.USER.value,
                col(KnowledgeSpaceScope.owner_id).in_(owner_ids),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                Knowledge.is_favorite == False,  # noqa: E712
            )
        )
        result = await session.exec(stmt)
        rows = result.all()
    return {int(space_id) for space_id in rows}

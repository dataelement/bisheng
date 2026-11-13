"""Paginated membership rows for a department and its visible subtree."""

from sqlalchemy import case, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.subject_search import escape_like
from bisheng.database.models.department import Department, UserDepartment
from bisheng.department.domain.repositories.organization_search_repository import scoped_departments
from bisheng.user.domain.models.user import User


class DepartmentMemberRepository:
    @staticmethod
    async def page(
        session: AsyncSession,
        dept_id: int,
        page: int,
        limit: int,
        keyword: str,
        is_primary: int | None,
        *,
        subtree: Department | None = None,
        visible_paths: set[str] | None = None,
        include_archived: bool = False,
    ):
        base = select(
            UserDepartment.user_id,
            User.user_name,
            User.external_id.label("user_external_id"),
            UserDepartment.department_id,
            UserDepartment.is_primary,
            UserDepartment.source,
            UserDepartment.create_time.label("member_join_time"),
            User.create_time.label("user_create_time"),
            User.update_time.label("user_update_time"),
            User.delete.label("user_deleted"),
            User.disable_source.label("user_disable_source"),
        ).join(User, User.user_id == UserDepartment.user_id)
        is_direct = UserDepartment.department_id == dept_id
        if subtree is None:
            base = base.where(is_direct)
        else:
            scope = is_direct
            if subtree.path and subtree.path.endswith("/"):
                scope = or_(is_direct, Department.path.like(f"{escape_like(subtree.path)}%", escape="/"))
            base = scoped_departments(
                base.join(Department, Department.id == UserDepartment.department_id)
                .add_columns(
                    Department.dept_id.label("department_dept_id"),
                    Department.name.label("department_name"),
                    Department.status.label("department_status"),
                )
                .where(scope),
                visible_paths,
                include_archived,
            )
        if keyword:
            pattern = f"%{escape_like(keyword)}%"
            base = base.where(or_(User.user_name.like(pattern, escape="/"), User.external_id.like(pattern, escape="/")))
        if is_primary is not None:
            base = base.where(UserDepartment.is_primary == is_primary)

        filtered = base.subquery()
        if subtree is None:
            total = (await session.exec(select(func.count()).select_from(filtered))).one()
            direct_total = total
            ordered = base.order_by(UserDepartment.id)
        else:
            direct_count = func.count(case((filtered.c.department_id == dept_id, 1)))
            total, direct_total = (await session.exec(select(func.count(), direct_count).select_from(filtered))).one()
            # Keep direct rows at their existing offsets for member search and location.
            ordered = base.order_by(case((is_direct, 0), else_=1), UserDepartment.id)
        rows = (await session.exec(ordered.offset((page - 1) * limit).limit(limit))).all()
        return rows, total, direct_total

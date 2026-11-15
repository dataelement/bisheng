"""Name-only management search, bounded by the department tree's visible scope."""

from sqlalchemy import case, func, or_
from sqlmodel import select

from bisheng.common.subject_search import escape_like
from bisheng.core.database import get_async_db_session
from bisheng.core.database.tenant_filter import build_tenant_filter_clause
from bisheng.database.models.department import Department, UserDepartment
from bisheng.user.domain.models.user import User


def tenant_scoped(statement):
    # Grouped counts and membership joins hide Department from the outer ORM hook.
    clause = build_tenant_filter_clause(Department.tenant_id)
    return statement.where(clause) if clause is not None else statement


def scoped_departments(statement, paths: set[str] | None, include_archived: bool):
    statement = tenant_scoped(statement)
    statement = statement.where(Department.status.in_(["active", "archived"] if include_archived else ["active"]))
    if paths is not None:
        statement = (
            statement.where(or_(*[Department.path.like(f"{path}%") for path in paths]))
            if paths
            else statement.where(False)
        )
    return statement


def visible_chain(department, ancestors, paths: set[str] | None):
    ids = [int(part) for part in department.path.split("/") if part.isdigit()]
    return [
        ancestors[identifier]
        for identifier in ids
        if identifier in ancestors
        and (paths is None or any(ancestors[identifier].path.startswith(path) for path in paths))
    ]


class OrganizationSearchRepository:
    @classmethod
    async def department(cls, dept_id: str):
        async with get_async_db_session() as session:
            return (await session.exec(tenant_scoped(select(Department).where(Department.dept_id == dept_id)))).first()

    @staticmethod
    async def ancestors(session, departments):
        ids = {int(part) for department in departments for part in department.path.split("/") if part.isdigit()}
        if not ids:
            return {}
        rows = (await session.exec(tenant_scoped(select(Department).where(Department.id.in_(ids))))).all()
        return {row.id: row for row in rows}

    @classmethod
    async def departments(cls, keyword, page, limit, paths, include_archived):
        statement = scoped_departments(
            select(Department).where(Department.name.like(f"%{escape_like(keyword)}%", escape="/")),
            paths,
            include_archived,
        )
        async with get_async_db_session() as session:
            total = (await session.exec(select(func.count()).select_from(statement.subquery()))).one()
            rows = (
                await session.exec(
                    statement.order_by(
                        case((Department.name == keyword, 0), else_=1),
                        Department.sort_order,
                        Department.id,
                    )
                    .offset((page - 1) * limit)
                    .limit(limit)
                )
            ).all()
            ancestors = await cls.ancestors(session, rows)
        return {
            "data": [
                {
                    "id": row.id,
                    "dept_id": row.dept_id,
                    "name": row.name,
                    "status": row.status,
                    "parent_path": " / ".join(
                        node.name for node in visible_chain(row, ancestors, paths) if node.id != row.id
                    ),
                }
                for row in rows
            ],
            "total": total,
        }

    @classmethod
    async def members(cls, keyword, page, limit, paths, include_archived, preferred_department_id):
        statement = scoped_departments(
            select(User.user_id, User.user_name, User.external_id, User.delete)
            .join(UserDepartment, UserDepartment.user_id == User.user_id)
            .join(Department, Department.id == UserDepartment.department_id)
            .where(User.user_name.like(f"%{escape_like(keyword)}%", escape="/"))
            .group_by(User.user_id, User.user_name, User.external_id, User.delete),
            paths,
            include_archived,
        )
        async with get_async_db_session() as session:
            total = (await session.exec(select(func.count()).select_from(statement.subquery()))).one()
            rows = (
                await session.exec(
                    statement.order_by(
                        case((User.user_name == keyword, 0), else_=1),
                        User.user_name,
                        User.user_id,
                    )
                    .offset((page - 1) * limit)
                    .limit(limit)
                )
            ).all()
            if not rows:
                return {"data": [], "total": total}
            memberships = (
                await session.exec(
                    scoped_departments(
                        select(UserDepartment.user_id, UserDepartment.is_primary, Department)
                        .join(Department, Department.id == UserDepartment.department_id)
                        .where(UserDepartment.user_id.in_([row.user_id for row in rows])),
                        paths,
                        include_archived,
                    )
                )
            ).all()
            ancestors = await cls.ancestors(session, [row[2] for row in memberships])
        candidates = {}
        for user_id, is_primary, department in memberships:
            chain = visible_chain(department, ancestors, paths)
            tree_order = tuple((node.sort_order or 0, node.id) for node in chain)
            priority = (0 if is_primary else 1, 0 if department.id == preferred_department_id else 1, tree_order)
            previous = candidates.get(user_id)
            if previous is None or priority < previous[0]:
                candidates[user_id] = (priority, department, is_primary, chain)
        data = []
        for row in rows:
            candidate = candidates.get(row.user_id)
            if candidate is None:
                continue
            _, department, is_primary, chain = candidate
            data.append(
                {
                    "user_id": row.user_id,
                    "user_name": row.user_name,
                    "person_id": row.external_id,
                    "enabled": row.delete == 0,
                    "is_primary": bool(is_primary),
                    "department": {
                        "id": department.id,
                        "dept_id": department.dept_id,
                        "name": department.name,
                        "status": department.status,
                        "path": " / ".join(node.name for node in chain),
                    },
                }
            )
        return {"data": data, "total": total}

    @classmethod
    async def member_location(cls, department_id, user_id, limit, is_primary):
        base = (
            select(UserDepartment.id)
            .join(User, User.user_id == UserDepartment.user_id)
            .where(
                UserDepartment.department_id == department_id,
            )
        )
        async with get_async_db_session() as session:
            target = (
                await session.exec(
                    select(UserDepartment)
                    .join(User, User.user_id == UserDepartment.user_id)
                    .where(
                        UserDepartment.department_id == department_id,
                        UserDepartment.user_id == user_id,
                    )
                )
            ).first()
            if target is None:
                return None
            adjusted = is_primary is not None and target.is_primary != is_primary
            effective_filter = None if adjusted else is_primary
            if effective_filter is not None:
                base = base.where(UserDepartment.is_primary == effective_filter)
            preceding = (
                await session.exec(
                    select(func.count()).select_from(
                        base.where(UserDepartment.id < target.id).subquery(),
                    )
                )
            ).one()
        return {
            "page": preceding // limit + 1,
            "is_primary_filter": effective_filter,
            "filter_adjusted": adjusted,
        }

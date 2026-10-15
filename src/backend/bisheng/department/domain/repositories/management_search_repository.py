"""Organization-management search queries; caller supplies authorized scope."""

from sqlalchemy import func, or_
from sqlmodel import col, select

from bisheng.common.subject_search import normalize_keyword
from bisheng.core.database import get_async_db_session
from bisheng.core.database.subject_search import exact_id_priority, subject_match_condition
from bisheng.database.models.department import Department, UserDepartment


class ManagementSearchRepository:
    @classmethod
    async def global_members(cls, keyword, page, limit, admin_paths=None, requested_root_path=None):
        kw = normalize_keyword(keyword or "")
        if not kw or admin_paths == set():
            return {"data": [], "total": 0}
        # Keep indexed prefixes, a unique primary-department join and window counting.
        async with get_async_db_session() as session:
            from bisheng.user.domain.models.user import User

            id_to_name: dict[int, str] = {}

            def _primary_dept_display_path(dept: Department) -> str:
                """Resolve the primary department and ancestor labels in path order."""
                labels: list[str] = []
                ancestor_ids: list[int] = []
                for part in (dept.path or "").split("/"):
                    if not part.strip():
                        continue
                    try:
                        i = int(part)
                    except ValueError:
                        continue
                    ancestor_ids.append(i)
                    labels.append(id_to_name.get(i, f"#{i}"))
                self_id = int(dept.id)
                self_nm = id_to_name.get(self_id) or (dept.name or "")
                if self_id not in ancestor_ids and self_nm:
                    labels.append(self_nm)
                return "/".join(labels) if labels else (self_nm or "")

            def _scoped(stmt):
                stmt = (
                    stmt.join(
                        UserDepartment,
                        (UserDepartment.user_id == User.user_id) & (UserDepartment.is_primary == 1),
                    )
                    .join(Department, Department.id == UserDepartment.department_id)
                    .where(
                        Department.status == "active",
                        subject_match_condition(User.user_id, User.user_name, User.external_id, kw, name_prefix=True),
                    )
                )
                if requested_root_path is not None:
                    stmt = stmt.where(
                        Department.path.like(f"{requested_root_path}%"),
                    )
                elif admin_paths is not None:
                    stmt = stmt.where(or_(*[Department.path.like(f"{p}%") for p in admin_paths]))
                return stmt

            page_stmt = (
                _scoped(
                    select(
                        User.user_id,
                        User.user_name,
                        User.external_id,
                        col(Department.id).label("dept_int_id"),
                        col(User.delete).label("user_deleted"),
                        func.count().over().label("match_total"),
                    )
                )
                .order_by(exact_id_priority(User.external_id, kw), User.user_name, User.user_id)
                .offset((page - 1) * limit)
                .limit(limit)
            )
            rows = (await session.exec(page_stmt)).all()

            if rows:
                total = int(getattr(rows[0], "match_total", 0) or 0)
            else:
                # An empty page has no window row; retain the full matching count.
                count_stmt = _scoped(select(func.count()).select_from(User))
                total = int((await session.exec(count_stmt)).one() or 0)
                return {"data": [], "total": total}

            dept_int_ids = [int(r.dept_int_id) for r in rows]
            dept_rows = (await session.exec(select(Department).where(Department.id.in_(dept_int_ids)))).all()
            dept_by_id = {int(d.id): d for d in dept_rows}
            ancestor_ids = {int(part) for dept in dept_rows for part in (dept.path or "").split("/") if part.isdigit()}
            name_ids = ancestor_ids | set(dept_by_id)
            name_rows = await session.exec(
                select(Department.id, Department.name).where(Department.id.in_(name_ids), Department.status == "active")
            )
            id_to_name.update({int(row.id): row.name for row in name_rows.all()})

        data = []
        for r in rows:
            d = dept_by_id.get(int(r.dept_int_id))
            if not d:
                continue
            udel = int(getattr(r, "user_deleted", 0) or 0)
            data.append(
                {
                    "user_id": int(r.user_id),
                    "user_name": r.user_name,
                    "external_id": r.external_id,
                    "primary_department_dept_id": d.dept_id,
                    "primary_department_path": _primary_dept_display_path(d),
                    "enabled": udel == 0,
                }
            )
        return {"data": data, "total": int(total)}

    @classmethod
    async def department_matches(cls, keyword, path_prefixes=None, limit=50, include_archived=False):
        kw = normalize_keyword(keyword or "")
        if not kw or path_prefixes == []:
            return []
        stmt = select(Department).where(
            subject_match_condition(Department.id, Department.name, Department.external_id, kw, name_prefix=False),
            Department.status.in_(["active", "archived"] if include_archived else ["active"]),
        )
        if path_prefixes:
            stmt = stmt.where(or_(*[Department.path.like(f"{path}%") for path in path_prefixes]))
        stmt = stmt.order_by(exact_id_priority(Department.external_id, kw), Department.sort_order, Department.id).limit(
            limit
        )
        async with get_async_db_session() as session:
            return (await session.exec(stmt)).all()

"""Tenant management membership search preserves primary-department semantics."""

from sqlalchemy import func
from sqlmodel import select

from bisheng.common.subject_search import normalize_keyword
from bisheng.core.database import get_async_db_session
from bisheng.core.database.subject_search import exact_id_priority, subject_match_condition
from bisheng.database.models.department import Department, UserDepartment


class ManagementSearchRepository:
    @classmethod
    async def tenant_users(
        cls,
        tenant_id: int,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
    ) -> tuple[list[dict], int]:
        """Get users whose primary department is mounted under the tenant.

        Resolution rules (in order):
          1. Look up ``tenant.root_dept_id`` → fetch the root dept's path,
             match ``Department.path LIKE '<root_path>%'``.
          2. If the tenant has no ``root_dept_id`` (legacy data from v2.5.0
             or early v2.5.1), fall back to ``Department.tenant_id == tenant_id``
             — preserves the v2.5.0 flat-model semantic so the UI keeps
             working during migration.

        ``UserTenant`` is LEFT-JOINed only to surface ``last_access_time``
        as ``join_time`` for the response (matches the legacy DAO's shape).
        Phantom UserTenant rows whose user has a primary dept outside the
        subtree are NOT considered (AC-12).
        """
        keyword = normalize_keyword(keyword or "")
        from bisheng.database.models.tenant import Tenant, UserTenant
        from bisheng.user.domain.models.user import User

        async with get_async_db_session() as session:
            # Step 1: resolve tenant.root_dept_id (if set) → path prefix
            root_path: str | None = None
            tenant_row = (await session.exec(select(Tenant.root_dept_id).where(Tenant.id == tenant_id))).first()
            # session.exec with a column-tuple select returns the value
            # directly on SQLModel >=0.0.14, but on some versions returns a
            # 1-tuple Row. Normalise.
            root_dept_id = tenant_row[0] if isinstance(tenant_row, tuple) else tenant_row
            if root_dept_id is not None:
                path_row = (
                    await session.exec(
                        select(Department.path).where(
                            Department.id == root_dept_id,
                        )
                    )
                ).first()
                root_path = path_row[0] if isinstance(path_row, tuple) else path_row

            # Step 2: build the subtree filter
            if root_path:
                subtree_filter = Department.path.like(f"{root_path}%")
            else:
                # Fallback: legacy flat model
                subtree_filter = Department.tenant_id == tenant_id

            # Step 3: count distinct users matching the filter
            count_stmt = (
                select(func.count(func.distinct(User.user_id)))
                .select_from(User)
                .join(
                    UserDepartment,
                    UserDepartment.user_id == User.user_id,
                )
                .join(
                    Department,
                    Department.id == UserDepartment.department_id,
                )
                .where(
                    UserDepartment.is_primary == 1,
                    subtree_filter,
                )
            )
            if keyword:
                count_stmt = count_stmt.where(
                    subject_match_condition(User.user_id, User.user_name, User.external_id, keyword, name_prefix=False),
                )
            total = (await session.exec(count_stmt)).one()
            # ``.one()`` returns a Row(count) on some versions and a scalar
            # on others; normalise.
            if isinstance(total, tuple):
                total = total[0]

            # Step 4: paginated user list. Use a distinct subquery on
            # user_id to guard against multi-primary anomalies (the G1 fix
            # closes the write path, but defensive DISTINCT here makes
            # historical data render cleanly).
            uid_subq = (
                select(UserDepartment.user_id)
                .join(
                    Department,
                    Department.id == UserDepartment.department_id,
                )
                .where(
                    UserDepartment.is_primary == 1,
                    subtree_filter,
                )
                .distinct()
                .subquery()
            )

            stmt = (
                select(
                    User.user_id,
                    User.user_name,
                    User.external_id,
                    User.avatar,
                    UserTenant.last_access_time.label("join_time"),
                )
                .join(uid_subq, uid_subq.c.user_id == User.user_id)
                .outerjoin(
                    UserTenant,
                    (UserTenant.user_id == User.user_id)
                    & (UserTenant.tenant_id == tenant_id)
                    & (UserTenant.is_active == 1),
                )
            )
            if keyword:
                stmt = stmt.where(
                    subject_match_condition(User.user_id, User.user_name, User.external_id, keyword, name_prefix=False)
                )
            if keyword:
                stmt = stmt.order_by(exact_id_priority(User.external_id, keyword))
            stmt = (
                stmt.order_by(
                    UserTenant.last_access_time.desc(),
                    User.user_id,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = (await session.exec(stmt)).all()

            return [
                {
                    "user_id": row.user_id,
                    "user_name": row.user_name,
                    "external_id": row.external_id,
                    "avatar": row.avatar,
                    "join_time": row.join_time,
                }
                for row in rows
            ], total

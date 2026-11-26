"""Management user search without changing the shared legacy DAO contract."""

from contextlib import nullcontext

from sqlalchemy import func, or_
from sqlmodel import select

from bisheng.common.request_scope import get_admitted_request_scope
from bisheng.common.subject_search import normalize_keyword
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_sync_db_session
from bisheng.core.database.subject_search import exact_id_priority, subject_match_condition
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.tenant import UserTenant
from bisheng.department.application.directory import management_directory_facts_sync
from bisheng.user.domain.models.user import User


class ManagementSearchRepository:
    @classmethod
    def list_users(cls, user_ids=None, keyword=None, page=0, limit=0):
        kw = normalize_keyword(keyword or "")
        filters = []
        admitted = get_admitted_request_scope()
        tenant_view = admitted is not None and admitted.kind == "tenant"
        if tenant_view:
            scope = management_directory_facts_sync(admitted.tenant_id)
            in_tree = (Department.tenant_id == scope.storage_tenant_id) & Department.path.like(f"{scope.root_path}%")
            for excluded in scope.excluded_paths:
                in_tree &= ~Department.path.like(f"{excluded}%")
            members = (
                select(UserDepartment.user_id)
                .join(Department, Department.id == UserDepartment.department_id)
                .where(in_tree, Department.status == "active", Department.is_deleted == 0)
            )
            homes = select(UserTenant.user_id).where(
                UserTenant.tenant_id == admitted.tenant_id, UserTenant.is_active == 1
            )
            # Keep legacy Home accounts with no department visible, and include proven affiliations.
            filters.append(or_(User.user_id.in_(members), User.user_id.in_(homes)))
        if user_ids is not None:
            filters.append(User.user_id.in_(user_ids))
        if kw:
            filters.append(
                subject_match_condition(User.user_id, User.user_name, User.external_id, kw, name_prefix=False)
            )
        stmt = select(User).where(*filters)
        if kw:
            stmt = stmt.order_by(exact_id_priority(User.external_id, kw))
        stmt = stmt.order_by(User.user_id.desc())
        if page and limit:
            stmt = stmt.offset((page - 1) * limit).limit(limit)
        # Only this exact directory join needs its physical storage tenant; all
        # predicates are explicit, and no caller-wide filter bypass is installed.
        with bypass_tenant_filter() if tenant_view else nullcontext(), get_sync_db_session() as session:
            total = session.scalar(select(func.count(User.user_id)).where(*filters))
            return session.exec(stmt).all(), total

    @staticmethod
    def department_hints(user_ids):
        admitted = get_admitted_request_scope()
        scope = management_directory_facts_sync(admitted.tenant_id)
        in_tree = (Department.tenant_id == scope.storage_tenant_id) & Department.path.like(f"{scope.root_path}%")
        for excluded in scope.excluded_paths:
            in_tree &= ~Department.path.like(f"{excluded}%")
        with bypass_tenant_filter(), get_sync_db_session() as session:
            rows = session.exec(
                select(UserDepartment, Department)
                .join(Department, Department.id == UserDepartment.department_id)
                .where(
                    UserDepartment.user_id.in_(user_ids),
                    in_tree,
                    Department.status == "active",
                    Department.is_deleted == 0,
                )
                .order_by(UserDepartment.is_primary.desc(), UserDepartment.id)
            ).all()
            ids = {int(part) for _, row in rows for part in row.path.split("/") if part.isdigit()}
            ancestors = session.exec(select(Department).where(Department.id.in_(ids), in_tree)).all() if ids else []
        names = {row.id: row.name for row in ancestors}
        by_user = {}
        labels = {}
        for membership, row in rows:
            by_user.setdefault(membership.user_id, row.id)
            labels[row.id] = "/".join(
                names[int(part)] for part in row.path.split("/") if part.isdigit() and int(part) in names
            )
        return by_user, labels

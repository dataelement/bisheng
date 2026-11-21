"""Search only active natural people with one proven eligible Home."""

from sqlalchemy import func, or_
from sqlmodel import select

from bisheng.common.subject_search import normalize_keyword
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.database.subject_search import exact_id_priority, subject_match_condition
from bisheng.database.models.tenant import UserTenant
from bisheng.user.domain.models.user import User


class ApproverCandidateRepository:
    @staticmethod
    async def search(tenant_id, *, keyword, page, limit, global_ids=(), excluded_ids=()):
        keyword = normalize_keyword(keyword)
        homes = (
            select(UserTenant.user_id)
            .where(UserTenant.is_active == 1, UserTenant.status == "active")
            .group_by(UserTenant.user_id)
            .having(func.count(UserTenant.id) == 1)
            .having(or_(func.max(UserTenant.tenant_id) == tenant_id, UserTenant.user_id.in_(global_ids)))
        )
        filters = [User.delete == 0, User.user_id.in_(homes), User.user_id.not_in(excluded_ids)]
        if keyword:
            filters.append(
                subject_match_condition(User.user_id, User.user_name, User.external_id, keyword, name_prefix=False)
            )
        query = select(User.user_id, User.user_name, User.external_id).where(*filters)
        if keyword:
            query = query.order_by(exact_id_priority(User.external_id, keyword))
        query = query.order_by(User.user_id.desc()).offset((page - 1) * limit).limit(limit)
        # UserTenant is global identity storage. The grouped Home proof above
        # explicitly limits rows to this tenant or verified global administrators.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                total = (await session.exec(select(func.count(User.user_id)).where(*filters))).one()
                rows = (await session.exec(query)).all()
        return [
            {"user_id": row.user_id, "user_name": row.user_name, "external_id": row.external_id} for row in rows
        ], total

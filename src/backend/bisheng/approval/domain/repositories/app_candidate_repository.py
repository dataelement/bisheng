"""Current people and complete Root-role facts for app-specific review qualification."""

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.database.models.tenant import UserTenant
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole


class AppCandidateRepository:
    @staticmethod
    async def root_role_ids():
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return tuple((await session.exec(select(UserRole.user_id).where(UserRole.role_id == AdminRole))).all())

    @staticmethod
    async def eligible_ids(tenant_id, user_ids, *, global_ids=()):
        people = {}
        values = tuple(dict.fromkeys(user_ids))
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                for offset in range(0, len(values), 500):
                    rows = (
                        await session.exec(
                            select(User.user_id, UserTenant.tenant_id)
                            .join(UserTenant, UserTenant.user_id == User.user_id)
                            .where(
                                User.user_id.in_(values[offset : offset + 500]),
                                User.delete == 0,
                                UserTenant.is_active == 1,
                                UserTenant.status == "active",
                            )
                        )
                    ).all()
                    for uid, tid in rows:
                        people.setdefault(uid, []).append(tid)
        return tuple(
            uid
            for uid in values
            if len(people.get(uid, ())) == 1 and (people[uid][0] == tenant_id or uid in global_ids)
        )

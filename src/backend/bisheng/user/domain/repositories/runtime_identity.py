"""Exact current person membership for delayed web actions."""

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.user.domain.models.user import User


async def current_runtime_person(user_id):
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(User, UserTenant.tenant_id)
                    .join(UserTenant, UserTenant.user_id == User.user_id)
                    .join(Tenant, Tenant.id == UserTenant.tenant_id)
                    .where(
                        User.user_id == user_id,
                        User.delete == 0,
                        UserTenant.is_active == 1,
                        UserTenant.status == "active",
                        Tenant.status == "active",
                    )
                    .limit(2)
                )
            ).all()
    return rows[0] if len(rows) == 1 else None

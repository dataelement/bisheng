"""Narrow identity-directory reads for verified management scope resolution."""

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.user.domain.models.user import User


class TenantScopeRepository:
    @classmethod
    async def status(cls, tenant_id: int) -> str | None:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(select(Tenant.status).where(Tenant.id == tenant_id))).one_or_none()

    @classmethod
    async def own_tenant_ids(cls, user_id: int) -> tuple[int, ...]:
        # The lookup establishes identity membership, independent of the selected view.
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                rows = (
                    await session.exec(
                        select(UserTenant.tenant_id)
                        .join(User, User.user_id == UserTenant.user_id)
                        .where(
                            User.user_id == user_id,
                            User.delete == 0,
                            UserTenant.is_active == 1,
                            UserTenant.status == "active",
                        )
                        .limit(2)
                    )
                ).all()
        return tuple(int(value) for value in rows)

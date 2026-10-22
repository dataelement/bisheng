from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.tenant.domain.repositories.interfaces.tenant_membership_repository import TenantMembershipRepository


class TenantMembershipRepositoryImpl(BaseRepositoryImpl[UserTenant, int], TenantMembershipRepository):
    def __init__(self, session: AsyncSession | Session) -> None:
        super().__init__(session, UserTenant)

    async def list_current_by_user(self, user_id: int) -> list[UserTenant]:
        statement = select(UserTenant).where(UserTenant.user_id == user_id, UserTenant.is_active == 1)
        result = await self.session.exec(statement)
        return list(result.all())

    async def find_tenant(self, tenant_id: int) -> Tenant | None:
        return await self.session.get(Tenant, tenant_id)

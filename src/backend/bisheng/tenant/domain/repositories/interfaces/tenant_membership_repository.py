from abc import ABC, abstractmethod

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.database.models.tenant import Tenant, UserTenant


class TenantMembershipRepository(BaseRepository[UserTenant, int], ABC):
    @abstractmethod
    async def list_current_by_user(self, user_id: int) -> list[UserTenant]:
        raise NotImplementedError

    @abstractmethod
    async def find_tenant(self, tenant_id: int) -> Tenant | None:
        raise NotImplementedError

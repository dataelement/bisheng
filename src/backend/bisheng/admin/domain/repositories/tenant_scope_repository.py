"""Availability reads for a tenant selected in service-account management."""

from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import Tenant


class TenantScopeRepository:
    @classmethod
    async def status(cls, tenant_id: int) -> str | None:
        async with get_async_db_session() as session:
            return (await session.exec(select(Tenant.status).where(Tenant.id == tenant_id))).one_or_none()

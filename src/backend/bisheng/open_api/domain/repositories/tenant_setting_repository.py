"""Persistence boundary for tenant-scoped Open API settings."""

from __future__ import annotations

from sqlmodel import select

from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.open_api.domain.models.open_api_tenant_setting import OpenApiTenantSetting


class TenantSettingRepository:
    @classmethod
    async def get(cls, tenant_id: int) -> OpenApiTenantSetting | None:
        async with get_async_db_session() as session:
            return (
                await session.exec(
                    select(OpenApiTenantSetting).where(OpenApiTenantSetting.tenant_id == tenant_id)
                )
            ).first()

    @classmethod
    def get_sync(cls, tenant_id: int) -> OpenApiTenantSetting | None:
        with get_sync_db_session() as session:
            return session.exec(
                select(OpenApiTenantSetting).where(OpenApiTenantSetting.tenant_id == tenant_id)
            ).first()

    @classmethod
    async def save(cls, row: OpenApiTenantSetting) -> OpenApiTenantSetting:
        async with get_async_db_session() as session:
            merged = await session.merge(row)
            await session.commit()
            await session.refresh(merged)
            return merged

import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, text
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import LargeText

_LOG = logging.getLogger(__name__)
_ROOT_TENANT_ID = 1


class TenantWorkstationConfigBase(SQLModelSerializable):
    tenant_id: int = Field(
        sa_column=Column(
            Integer, nullable=False, index=True,
            comment='Owner tenant; 1=Root, others=Child leaf',
        ),
    )
    key: str = Field(
        sa_column=Column(
            String(64), nullable=False, index=True,
            comment='ConfigKeyEnum value: workstation/workstation_linsight/...',
        ),
    )
    value: Optional[str] = Field(
        default=None,
        sa_column=Column(
            LargeText, nullable=True,
            comment='JSON-encoded workstation config payload',
        ),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
            onupdate=text('CURRENT_TIMESTAMP'),
        ),
    )


class TenantWorkstationConfig(TenantWorkstationConfigBase, table=True):
    __tablename__ = 'tenant_workstation_config'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'key', name='uq_tenant_workstation_tenant_key'),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Optional[int] = Field(default=None, primary_key=True)


class TenantWorkstationConfigDao:
    @classmethod
    async def aget(cls, tenant_id: int, key: str) -> Optional[TenantWorkstationConfig]:
        async with get_async_db_session() as session:
            stmt = select(TenantWorkstationConfig).where(
                TenantWorkstationConfig.tenant_id == tenant_id,
                TenantWorkstationConfig.key == key,
            )
            result = await session.exec(stmt)
            return result.first()

    @classmethod
    def get(cls, tenant_id: int, key: str) -> Optional[TenantWorkstationConfig]:
        with get_sync_db_session() as session:
            stmt = select(TenantWorkstationConfig).where(
                TenantWorkstationConfig.tenant_id == tenant_id,
                TenantWorkstationConfig.key == key,
            )
            return session.exec(stmt).first()

    @classmethod
    async def aupsert(
        cls, tenant_id: int, key: str, value: Optional[str],
    ) -> TenantWorkstationConfig:
        async with get_async_db_session() as session:
            stmt = select(TenantWorkstationConfig).where(
                TenantWorkstationConfig.tenant_id == tenant_id,
                TenantWorkstationConfig.key == key,
            )
            existing = (await session.exec(stmt)).first()
            if existing is None:
                row = TenantWorkstationConfig(tenant_id=tenant_id, key=key, value=value)
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row
            existing.value = value
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
            return existing

    @classmethod
    async def aresolve(
        cls, tenant_id: int, key: str,
    ) -> Tuple[Optional[str], bool, int, bool]:
        own = await cls.aget(tenant_id, key)
        if own is not None and own.value:
            return own.value, False, tenant_id, True

        if tenant_id == _ROOT_TENANT_ID:
            return None, False, _ROOT_TENANT_ID, False

        with bypass_tenant_filter():
            root = await cls.aget(_ROOT_TENANT_ID, key)
        if root is None or not root.value:
            return None, False, _ROOT_TENANT_ID, False
        return root.value, True, _ROOT_TENANT_ID, False

    @classmethod
    def resolve(
        cls, tenant_id: int, key: str,
    ) -> Tuple[Optional[str], bool, int, bool]:
        own = cls.get(tenant_id, key)
        if own is not None and own.value:
            return own.value, False, tenant_id, True

        if tenant_id == _ROOT_TENANT_ID:
            return None, False, _ROOT_TENANT_ID, False

        with bypass_tenant_filter():
            root = cls.get(_ROOT_TENANT_ID, key)
        if root is None or not root.value:
            return None, False, _ROOT_TENANT_ID, False
        return root.value, True, _ROOT_TENANT_ID, False

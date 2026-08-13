import logging
from datetime import datetime

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
            Integer,
            nullable=False,
            index=True,
            comment="Owner tenant; 1=Root, others=Child leaf",
        ),
    )
    key: str = Field(
        sa_column=Column(
            String(64),
            nullable=False,
            index=True,
            comment="ConfigKeyEnum value: workstation/workstation_linsight/...",
        ),
    )
    value: str | None = Field(
        default=None,
        sa_column=Column(
            LargeText,
            nullable=True,
            comment="JSON-encoded workstation config payload",
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            onupdate=text("CURRENT_TIMESTAMP"),
        ),
    )


class TenantWorkstationConfig(TenantWorkstationConfigBase, table=True):
    __tablename__ = "tenant_workstation_config"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_workstation_tenant_key"),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: int | None = Field(default=None, primary_key=True)


class TenantWorkstationConfigDao:
    @classmethod
    async def aget(cls, tenant_id: int, key: str) -> TenantWorkstationConfig | None:
        async with get_async_db_session() as session:
            stmt = select(TenantWorkstationConfig).where(
                TenantWorkstationConfig.tenant_id == tenant_id,
                TenantWorkstationConfig.key == key,
            )
            result = await session.exec(stmt)
            return result.first()

    @classmethod
    def get(cls, tenant_id: int, key: str) -> TenantWorkstationConfig | None:
        with get_sync_db_session() as session:
            stmt = select(TenantWorkstationConfig).where(
                TenantWorkstationConfig.tenant_id == tenant_id,
                TenantWorkstationConfig.key == key,
            )
            return session.exec(stmt).first()

    @classmethod
    async def aupsert(
        cls,
        tenant_id: int,
        key: str,
        value: str | None,
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
        cls,
        tenant_id: int,
        key: str,
    ) -> tuple[str | None, bool, int, bool]:
        own = await cls.aget(tenant_id, key)
        if own is not None and own.value:
            return own.value, False, tenant_id, True

        if tenant_id == _ROOT_TENANT_ID:
            # A filtered-out row and an absent row look identical from here: the
            # tenant auto-filter narrows every SELECT by the request's
            # visible-tenant set, so Root's own row reads back as "missing"
            # whenever that set does not contain Root. Concluding "no config"
            # from that is destructive — callers fabricate defaults from it and
            # the admin UI persists whatever it was shown, which is how a whole
            # workstation config got silently overwritten with defaults on
            # 2026-08-13. Re-read unfiltered before deciding.
            with bypass_tenant_filter():
                own = await cls.aget(_ROOT_TENANT_ID, key)
            if own is not None and own.value:
                return own.value, False, _ROOT_TENANT_ID, True
            return None, False, _ROOT_TENANT_ID, False

        with bypass_tenant_filter():
            root = await cls.aget(_ROOT_TENANT_ID, key)
        if root is None or not root.value:
            return None, False, _ROOT_TENANT_ID, False
        return root.value, True, _ROOT_TENANT_ID, False

    @classmethod
    def resolve(
        cls,
        tenant_id: int,
        key: str,
    ) -> tuple[str | None, bool, int, bool]:
        own = cls.get(tenant_id, key)
        if own is not None and own.value:
            return own.value, False, tenant_id, True

        if tenant_id == _ROOT_TENANT_ID:
            # See ``aresolve``: for Root, "filtered out" is indistinguishable
            # from "absent", so re-read unfiltered before reporting no config.
            with bypass_tenant_filter():
                own = cls.get(_ROOT_TENANT_ID, key)
            if own is not None and own.value:
                return own.value, False, _ROOT_TENANT_ID, True
            return None, False, _ROOT_TENANT_ID, False

        with bypass_tenant_filter():
            root = cls.get(_ROOT_TENANT_ID, key)
        if root is None or not root.value:
            return None, False, _ROOT_TENANT_ID, False
        return root.value, True, _ROOT_TENANT_ID, False

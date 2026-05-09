"""F022: tenant-scoped storage for the 5 system-level LLM default selections.

Replaces the globally-unique rows in ``config`` (knowledge_llm /
assistant_llm / evaluation_llm / workflow_llm / linsight_llm) with a
per-tenant table. Resolution honors ``Tenant.share_default_to_children``
fallback semantics: a Child without its own row inherits Root's value
when Root opts in.

The single ``aresolve()`` entry point returns
``(value, inherited_from_root, fallback_blocked)`` so the API layer can
render the right banner without each consumer repeating the fallback
logic.
"""
import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import Column, DateTime, Integer, SmallInteger, String, UniqueConstraint, text
from bisheng.core.database.dialect_helpers import LargeText
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session

_LOG = logging.getLogger(__name__)
# Inline to avoid an import cycle: tenant.py loads SQLModelSerializable
# before ORM table registration completes. Same pattern as llm_server.py.
_ROOT_TENANT_ID = 1


class TenantSystemModelConfigBase(SQLModelSerializable):
    tenant_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True,
                         comment='Owner tenant; 1=Root, others=Child leaf'),
    )
    key: str = Field(
        sa_column=Column(String(64), nullable=False, index=True,
                         comment='ConfigKeyEnum value: linsight_llm/knowledge_llm/...'),
    )
    value: Optional[str] = Field(
        default=None,
        sa_column=Column(LONGTEXT, nullable=True,
                         comment='JSON-encoded config payload'),
    )
    is_shared_to_children: Optional[int] = Field(
        default=None,
        sa_column=Column(SmallInteger, nullable=True,
                         comment='Reserved (v2.6+): row-level override of '
                                 'Tenant.share_default_to_children; '
                                 'NULL means use the tenant default'),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False,
                         server_default=text('CURRENT_TIMESTAMP')),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')),
    )


class TenantSystemModelConfig(TenantSystemModelConfigBase, table=True):
    __tablename__ = 'tenant_system_model_config'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'key', name='uq_tenant_system_model_tenant_key'),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )

    id: Optional[int] = Field(default=None, primary_key=True)


class TenantSystemModelConfigDao:
    """DAO for ``tenant_system_model_config`` with Root-fallback resolution.

    Reads of Root rows from a Child scope go through ``bypass_tenant_
    filter()`` because the global event listener injects
    ``WHERE tenant_id = <current scope>`` for every tenant-aware table
    (see ``core/database/tenant_filter.py``); without bypass a Child
    Admin's ``aresolve`` would never find the Root row.
    """

    @classmethod
    async def aget(
        cls, tenant_id: int, key: str,
    ) -> Optional[TenantSystemModelConfig]:
        async with get_async_db_session() as session:
            stmt = select(TenantSystemModelConfig).where(
                TenantSystemModelConfig.tenant_id == tenant_id,
                TenantSystemModelConfig.key == key,
            )
            result = await session.exec(stmt)
            return result.first()

    @classmethod
    def get(
        cls, tenant_id: int, key: str,
    ) -> Optional[TenantSystemModelConfig]:
        with get_sync_db_session() as session:
            stmt = select(TenantSystemModelConfig).where(
                TenantSystemModelConfig.tenant_id == tenant_id,
                TenantSystemModelConfig.key == key,
            )
            return session.exec(stmt).first()

    @classmethod
    async def aupsert(
        cls, tenant_id: int, key: str, value: Optional[str],
    ) -> TenantSystemModelConfig:
        """Insert or update the ``(tenant_id, key)`` row.

        The unique key is ``(tenant_id, key)`` so concurrent writers settle
        deterministically. SQLModel's session.add path triggers MySQL's
        ON DUPLICATE KEY UPDATE through the unique constraint.
        """
        async with get_async_db_session() as session:
            stmt = select(TenantSystemModelConfig).where(
                TenantSystemModelConfig.tenant_id == tenant_id,
                TenantSystemModelConfig.key == key,
            )
            existing = (await session.exec(stmt)).first()
            if existing is None:
                row = TenantSystemModelConfig(
                    tenant_id=tenant_id, key=key, value=value,
                )
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
    ) -> Tuple[Optional[str], bool, bool]:
        """Resolve ``key`` for ``tenant_id`` with Root fallback.

        Returns ``(value, inherited_from_root, fallback_blocked)``:
          * own row + non-empty value           → (value, False, False)
          * tenant_id == Root                    → (None, False, False)
          * Root row missing/empty               → (None, False, False)
          * Root has value, share opted in       → (root.value, True, False)
          * Root has value, share opted out      → (None, False, True)
        """
        own = await cls.aget(tenant_id, key)
        if own is not None and own.value:
            return own.value, False, False

        if tenant_id == _ROOT_TENANT_ID:
            return None, False, False

        # Local import to dodge the same cycle that forces _ROOT_TENANT_ID
        # to be inlined at module top.
        from bisheng.database.models.tenant import TenantDao
        # Single bypass block covers both cross-scope reads — ContextVar
        # set/reset is cheap but not free, and pairing the two reads
        # also makes the "we're crossing the tenant boundary" intent
        # obvious in one place.
        with bypass_tenant_filter():
            root = await cls.aget(_ROOT_TENANT_ID, key)
            if root is None or not root.value:
                return None, False, False
            root_tenant = await TenantDao.aget_by_id(_ROOT_TENANT_ID)
        if root_tenant is not None and bool(root_tenant.share_default_to_children):
            return root.value, True, False
        return None, False, True

    @classmethod
    def resolve(
        cls, tenant_id: int, key: str,
    ) -> Tuple[Optional[str], bool, bool]:
        """Sync mirror of ``aresolve`` for sync consumers (workflow nodes).

        Same five-branch contract, same bypass semantics.
        """
        own = cls.get(tenant_id, key)
        if own is not None and own.value:
            return own.value, False, False

        if tenant_id == _ROOT_TENANT_ID:
            return None, False, False

        from bisheng.database.models.tenant import TenantDao
        with bypass_tenant_filter():
            root = cls.get(_ROOT_TENANT_ID, key)
            if root is None or not root.value:
                return None, False, False
            root_tenant = TenantDao.get_by_id(_ROOT_TENANT_ID)
        if root_tenant is not None and bool(root_tenant.share_default_to_children):
            return root.value, True, False
        return None, False, True

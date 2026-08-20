"""Tenant routing table for SPACE shared storage (F1.2, refactor spec 6.2).

Single source of truth for "is this tenant's SPACE storage routed to the
shared Milvus collection / ES index". Switching a tenant is a single-row
atomic ``UPDATE`` that also bumps ``routing_version`` so every process can
detect gray-release staleness (risk R16): readers must carry the routing
version they resolved and assert it on each store access.

Mirror-level backward compatibility (spec 6.3 / 7.4): this table is purely
additive; the previous image neither reads nor writes it, and every column
is nullable or carries a server default.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, text, update
from sqlmodel import Field, Session, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class KnowledgeSpaceSharedStorageRoutingBase(SQLModelSerializable):
    # ``default=None`` + nullable=False + server_default keeps SQLModel happy
    # both when rows are created through the ORM (value always provided) and
    # when fresh installs create the table via create_all (DDL default only).
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            index=True,
            comment="Tenant ID (one row per tenant)",
        ),
    )
    shared_enabled: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("0"),
            comment="Whether this tenant's SPACE storage is routed to the shared store",
        ),
    )
    routing_version: int = Field(
        default=1,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            comment="Monotonic version; bumped on every routing switch",
        ),
    )
    write_frozen: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("0"),
            comment="TENANT_WRITE_FROZEN migration flag; SPACE writes fail closed while set",
        ),
    )
    collection_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True, comment="Shared Milvus collection name"),
    )
    index_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True, comment="Shared ES index name"),
    )
    embedding_model_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=True,
            comment="Tenant-wide target embedding model ID for shared SPACE storage",
        ),
    )
    schema_fingerprint: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(128),
            nullable=True,
            comment="Schema fingerprint recorded at shared-store bootstrap time",
        ),
    )
    migration_state: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(64),
            nullable=True,
            comment="Migration state machine label (F4); empty when not migrating",
        ),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class KnowledgeSpaceSharedStorageRouting(
    KnowledgeSpaceSharedStorageRoutingBase, table=True
):
    __tablename__ = "knowledge_space_shared_storage_routing"
    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeSpaceSharedStorageRoutingDao:
    """Accessors for the tenant routing table.

    All write paths are single-statement SQL updates so the switch itself is
    atomic and idempotent (F1.2 acceptance).
    """

    TABLE = KnowledgeSpaceSharedStorageRouting

    @classmethod
    def get_by_tenant(
        cls, tenant_id: int
    ) -> Optional[KnowledgeSpaceSharedStorageRouting]:
        with get_sync_db_session() as session:
            return cls._get_by_tenant(session, tenant_id)

    @classmethod
    def _get_by_tenant(
        cls, session: Session, tenant_id: int
    ) -> Optional[KnowledgeSpaceSharedStorageRouting]:
        statement = select(KnowledgeSpaceSharedStorageRouting).where(
            KnowledgeSpaceSharedStorageRouting.tenant_id == int(tenant_id)
        )
        return session.exec(statement).first()

    @classmethod
    async def aget_by_tenant(
        cls, tenant_id: int
    ) -> Optional[KnowledgeSpaceSharedStorageRouting]:
        async with get_async_db_session() as session:
            statement = select(KnowledgeSpaceSharedStorageRouting).where(
                KnowledgeSpaceSharedStorageRouting.tenant_id == int(tenant_id)
            )
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def ensure_row(cls, tenant_id: int) -> KnowledgeSpaceSharedStorageRouting:
        """Idempotently create the (disabled) routing row for a tenant."""
        with get_sync_db_session() as session:
            row = cls._get_by_tenant(session, tenant_id)
            if row is not None:
                return row
            row = KnowledgeSpaceSharedStorageRouting(tenant_id=int(tenant_id))
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    @classmethod
    def switch_to_shared(
        cls,
        tenant_id: int,
        *,
        collection_name: str,
        index_name: str,
        embedding_model_id: int,
        schema_fingerprint: str,
        migration_state: str = "",
    ) -> bool:
        """Atomically route a tenant's SPACE storage to the shared store.

        Single-row ``UPDATE`` that bumps ``routing_version``; returns True when
        a row was updated. Safe to re-run (idempotent end state).
        """
        with get_sync_db_session() as session:
            statement = (
                update(KnowledgeSpaceSharedStorageRouting)
                .where(KnowledgeSpaceSharedStorageRouting.tenant_id == int(tenant_id))
                .values(
                    shared_enabled=True,
                    routing_version=KnowledgeSpaceSharedStorageRouting.routing_version + 1,
                    collection_name=collection_name,
                    index_name=index_name,
                    embedding_model_id=int(embedding_model_id),
                    schema_fingerprint=schema_fingerprint,
                    migration_state=migration_state,
                )
            )
            result = session.exec(statement)
            session.commit()
            return bool(result.rowcount)

    @classmethod
    def switch_to_legacy(cls, tenant_id: int) -> bool:
        """Atomically route a tenant back to per-space storage (rollback path,
        only valid before TENANT_WRITE_RESUMED - spec 7.4)."""
        with get_sync_db_session() as session:
            statement = (
                update(KnowledgeSpaceSharedStorageRouting)
                .where(KnowledgeSpaceSharedStorageRouting.tenant_id == int(tenant_id))
                .values(
                    shared_enabled=False,
                    routing_version=KnowledgeSpaceSharedStorageRouting.routing_version + 1,
                )
            )
            result = session.exec(statement)
            session.commit()
            return bool(result.rowcount)

    @classmethod
    def set_write_frozen(cls, tenant_id: int, frozen: bool) -> bool:
        """Set/clear the migration write freeze for a tenant."""
        with get_sync_db_session() as session:
            statement = (
                update(KnowledgeSpaceSharedStorageRouting)
                .where(KnowledgeSpaceSharedStorageRouting.tenant_id == int(tenant_id))
                .values(
                    write_frozen=bool(frozen),
                    routing_version=KnowledgeSpaceSharedStorageRouting.routing_version + 1,
                )
            )
            result = session.exec(statement)
            session.commit()
            return bool(result.rowcount)

    @classmethod
    def set_migration_state(cls, tenant_id: int, state: str) -> bool:
        """Persist migration progress without changing the active route."""
        with get_sync_db_session() as session:
            statement = (
                update(KnowledgeSpaceSharedStorageRouting)
                .where(KnowledgeSpaceSharedStorageRouting.tenant_id == int(tenant_id))
                .values(migration_state=state)
            )
            result = session.exec(statement)
            session.commit()
            return bool(result.rowcount)

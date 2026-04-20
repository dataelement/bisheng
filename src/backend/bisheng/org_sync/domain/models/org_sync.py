"""OrgSyncConfig and OrgSyncLog ORM models + DAO classes.

Part of F009-org-sync.
"""

import json
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    update,
)
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.config.settings import decrypt_token, encrypt_token
from bisheng.core.database import get_async_db_session


# ---------------------------------------------------------------------------
# Encryption helpers for auth_config (Fernet, AD-02)
# ---------------------------------------------------------------------------

def encrypt_auth_config(config_dict: dict) -> str:
    """Encrypt auth_config dict to a Fernet-encrypted string for DB storage."""
    raw = json.dumps(config_dict, ensure_ascii=False)
    encrypted_bytes = encrypt_token(raw)
    # encrypt_token returns bytes; decode to str for TEXT column
    return encrypted_bytes.decode() if isinstance(encrypted_bytes, bytes) else encrypted_bytes


def decrypt_auth_config(encrypted: str) -> dict:
    """Decrypt a Fernet-encrypted auth_config string back to a dict."""
    raw = decrypt_token(encrypted)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class OrgSyncConfig(SQLModelSerializable, table=True):
    __tablename__ = 'org_sync_config'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False,
            server_default=text('1'), index=True,
            comment='Tenant ID',
        ),
    )
    provider: str = Field(
        sa_column=Column(
            String(32), nullable=False,
            comment='Provider: feishu/wecom/dingtalk/generic_api',
        ),
    )
    config_name: str = Field(
        sa_column=Column(
            String(128), nullable=False,
            comment='User-given label, e.g. Feishu Production',
        ),
    )
    auth_type: str = Field(
        sa_column=Column(
            String(16), nullable=False,
            comment='Auth mode: api_key/password (oauth reserved)',
        ),
    )
    auth_config: str = Field(
        sa_column=Column(
            Text, nullable=False,
            comment='Fernet-encrypted JSON: credentials per auth_type',
        ),
    )
    sync_scope: Optional[dict] = Field(
        default=None,
        sa_column=Column(
            JSON, nullable=True,
            comment='Sync scope: {"root_dept_ids": ["id1","id2"]} or null=all',
        ),
    )
    schedule_type: str = Field(
        default='manual',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'manual'"),
            comment='Execution mode: manual/cron',
        ),
    )
    cron_expression: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(64), nullable=True,
            comment='Cron expression, e.g. 0 2 * * *',
        ),
    )
    sync_status: str = Field(
        default='idle',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'idle'"),
            comment='Runtime mutex: idle/running',
        ),
    )
    last_sync_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True, comment='Last sync time'),
    )
    last_sync_result: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(16), nullable=True,
            comment='Last sync result: success/partial/failed',
        ),
    )
    status: str = Field(
        default='active',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'active'"), index=True,
            comment='Config status: active/disabled/deleted',
        ),
    )
    create_user: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment='Creator user ID'),
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
            server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
        ),
    )

    __table_args__ = (
        UniqueConstraint(
            'tenant_id', 'provider', 'config_name',
            name='uk_tenant_provider_name',
        ),
    )


class OrgSyncLog(SQLModelSerializable, table=True):
    __tablename__ = 'org_sync_log'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    tenant_id: int = Field(
        default=1,
        sa_column=Column(
            Integer, nullable=False,
            server_default=text('1'), index=True,
        ),
    )
    config_id: int = Field(
        sa_column=Column(
            Integer, nullable=False, index=True,
            comment='FK to org_sync_config.id',
        ),
    )
    trigger_type: str = Field(
        sa_column=Column(
            String(16), nullable=False,
            comment='Trigger: manual/scheduled',
        ),
    )
    trigger_user: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, nullable=True,
            comment='User who triggered (null for scheduled)',
        ),
    )
    status: str = Field(
        default='running',
        sa_column=Column(
            String(16), nullable=False,
            server_default=text("'running'"),
            comment='Status: running/success/partial/failed',
        ),
    )
    dept_created: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    dept_updated: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    dept_archived: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    member_created: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    member_updated: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    member_disabled: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    member_reactivated: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text('0')),
    )
    error_details: Optional[list] = Field(
        default=None,
        sa_column=Column(
            JSON, nullable=True,
            comment='Error list: [{entity_type, external_id, error_msg}]',
        ),
    )
    # F015: event-scoped columns. Legacy batch-summary rows (F009/F014) keep
    # event_type='' and rely on the counter columns above; F015 event rows set
    # event_type to one of {ts_conflict, stale_ts, conflict_weekly_sent,
    # conflict_daily_escalation_sent}.
    event_type: str = Field(
        default='',
        sa_column=Column(
            String(32), nullable=False, server_default=text("''"),
            comment=(
                "F015 event type; empty for F009 batch-summary rows"
            ),
        ),
    )
    level: str = Field(
        default='info',
        sa_column=Column(
            String(16), nullable=False, server_default=text("'info'"),
            comment='F015 log severity: info / warn / error',
        ),
    )
    external_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String(128), nullable=True,
            comment='F015: department external_id for event rows',
        ),
    )
    source_ts: Optional[int] = Field(
        default=None,
        sa_column=Column(
            BigInteger, nullable=True,
            comment='F015: incoming ts captured for INV-T12 audit',
        ),
    )
    start_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    end_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )


# ---------------------------------------------------------------------------
# DAO Classes
# ---------------------------------------------------------------------------

class OrgSyncConfigDao:

    @classmethod
    async def acreate(cls, config: OrgSyncConfig) -> OrgSyncConfig:
        async with get_async_db_session() as session:
            session.add(config)
            await session.flush()
            await session.refresh(config)
            await session.commit()
            return config

    @classmethod
    async def aget_by_id(cls, config_id: int) -> Optional[OrgSyncConfig]:
        async with get_async_db_session() as session:
            statement = select(OrgSyncConfig).where(
                OrgSyncConfig.id == config_id,
            )
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def aget_list(
        cls, tenant_id: int, status: Optional[str] = None,
    ) -> List[OrgSyncConfig]:
        """List configs for a tenant. Pass status to filter, or None for all non-deleted."""
        async with get_async_db_session() as session:
            statement = select(OrgSyncConfig).where(
                OrgSyncConfig.tenant_id == tenant_id,
                OrgSyncConfig.status != 'deleted',
            )
            if status is not None:
                statement = statement.where(OrgSyncConfig.status == status)
            statement = statement.order_by(OrgSyncConfig.id.desc())
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def aupdate(cls, config: OrgSyncConfig) -> OrgSyncConfig:
        async with get_async_db_session() as session:
            session.add(config)
            await session.commit()
            await session.refresh(config)
            return config

    @classmethod
    async def aset_sync_status(
        cls, config_id: int, old_status: str, new_status: str,
    ) -> bool:
        """Atomic CAS update of sync_status. Returns True if row was updated."""
        async with get_async_db_session() as session:
            stmt = (
                update(OrgSyncConfig)
                .where(
                    OrgSyncConfig.id == config_id,
                    OrgSyncConfig.sync_status == old_status,
                )
                .values(sync_status=new_status)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    @classmethod
    async def aget_active_cron_configs(cls) -> List[OrgSyncConfig]:
        """Get all configs with schedule_type='cron' and status='active'."""
        async with get_async_db_session() as session:
            statement = select(OrgSyncConfig).where(
                OrgSyncConfig.schedule_type == 'cron',
                OrgSyncConfig.status == 'active',
            )
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def aget_all_active(cls) -> List[OrgSyncConfig]:
        """F015: return every active OrgSyncConfig regardless of schedule_type.

        The 6h forced reconcile beat (``reconcile_all_organizations``) uses
        this DAO entry to fan out across every active config. Callers must
        filter ``provider='sso_realtime'`` (the F014 seed id=9999) since the
        seed is not a real provider.
        """
        async with get_async_db_session() as session:
            statement = select(OrgSyncConfig).where(
                OrgSyncConfig.status == 'active',
            )
            result = await session.exec(statement)
            return result.all()


class OrgSyncLogDao:

    @classmethod
    async def acreate(cls, log: OrgSyncLog) -> OrgSyncLog:
        async with get_async_db_session() as session:
            session.add(log)
            await session.flush()
            await session.refresh(log)
            await session.commit()
            return log

    @classmethod
    async def aupdate(cls, log: OrgSyncLog) -> OrgSyncLog:
        async with get_async_db_session() as session:
            session.add(log)
            await session.commit()
            await session.refresh(log)
            return log

    @classmethod
    async def aget_by_config(
        cls, config_id: int, page: int = 1, limit: int = 20,
    ) -> Tuple[List[OrgSyncLog], int]:
        """Paginated query of logs for a given config, newest first."""
        async with get_async_db_session() as session:
            base = select(OrgSyncLog).where(
                OrgSyncLog.config_id == config_id,
            )
            # Total count
            count_stmt = select(func.count()).select_from(base.subquery())
            total = await session.scalar(count_stmt) or 0
            # Page data
            data_stmt = base.order_by(OrgSyncLog.id.desc())
            if page and limit:
                data_stmt = data_stmt.offset((page - 1) * limit).limit(limit)
            result = await session.exec(data_stmt)
            return result.all(), total

    # ------------------------------------------------------------------
    # F015 event-row helpers
    # ------------------------------------------------------------------

    @classmethod
    async def acreate_event(
        cls,
        *,
        event_type: str,
        level: str,
        external_id: Optional[str],
        source_ts: Optional[int],
        config_id: int,
        tenant_id: int = 1,
        error_details: Optional[dict] = None,
    ) -> OrgSyncLog:
        """F015: persist an event-scoped log row.

        Counter columns (``dept_created``, ``member_*``) stay at 0 so the
        F009 batch-summary reader continues to treat these rows as "no-op
        batches" — inspection paths that filter by ``event_type='' `` are
        unaffected.

        ``error_details`` is persisted verbatim. Callers should keep the
        payload flat enough for JSON serialisation; the DDL column is
        ``JSON`` on MySQL and ``TEXT`` under SQLite, so nested dicts are
        fine.
        """
        log = OrgSyncLog(
            tenant_id=tenant_id,
            config_id=config_id,
            trigger_type='event',
            status='success',
            event_type=event_type,
            level=level,
            external_id=external_id,
            source_ts=source_ts,
            error_details=error_details,
        )
        return await cls.acreate(log)

    @classmethod
    async def acount_recent_conflicts(
        cls, external_id: str, days: int = 7,
    ) -> int:
        """F015: count ts_conflict warn events for one external_id.

        Backs the weekly report threshold (AC-12). Uses the
        ``idx_conflict_lookup`` composite index.
        """
        threshold = datetime.utcnow() - timedelta(days=days)
        async with get_async_db_session() as session:
            stmt = (
                select(func.count())
                .select_from(OrgSyncLog)
                .where(
                    OrgSyncLog.level == 'warn',
                    OrgSyncLog.event_type == 'ts_conflict',
                    OrgSyncLog.external_id == external_id,
                    OrgSyncLog.create_time > threshold,
                )
            )
            count = await session.scalar(stmt)
            return int(count or 0)

    @classmethod
    async def aget_conflicts_since(
        cls,
        since: datetime,
        event_type: str = 'ts_conflict',
        level: str = 'warn',
    ) -> List[OrgSyncLog]:
        """F015: fetch event rows for the weekly aggregation window.

        ``since`` is interpreted inclusively so the caller can align with
        the cron job's ``datetime.utcnow() - timedelta(days=7)`` window.
        """
        async with get_async_db_session() as session:
            stmt = (
                select(OrgSyncLog)
                .where(
                    OrgSyncLog.level == level,
                    OrgSyncLog.event_type == event_type,
                    OrgSyncLog.create_time >= since,
                )
                .order_by(OrgSyncLog.create_time.asc())
            )
            result = await session.exec(stmt)
            return result.all()

    @classmethod
    async def aget_latest_event(
        cls, event_type: str,
    ) -> Optional[OrgSyncLog]:
        """F015: last event row of the given type (used by daily escalation).

        Returns ``None`` when no such row exists — callers treat this as
        "weekly report never ran yet" and skip escalation.
        """
        async with get_async_db_session() as session:
            stmt = (
                select(OrgSyncLog)
                .where(OrgSyncLog.event_type == event_type)
                .order_by(OrgSyncLog.create_time.desc())
                .limit(1)
            )
            result = await session.exec(stmt)
            return result.first()

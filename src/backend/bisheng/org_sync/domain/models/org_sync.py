"""OrgSyncConfig and OrgSyncLog ORM models + DAO classes.

Part of F009-org-sync.
"""

import json
from datetime import datetime
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

"""F017 llm_call_log — tenant-attributed model invocation log.

Every call-site through ``ModelCallLogger.log`` writes one row, including
errors. Unlike llm_token_log (which gates monthly quota), this table is
for latency analytics, error tracking, and future per-call cost accounting.

INV-T13: ``tenant_id`` is the user's leaf tenant at call time — same rule
as llm_token_log, so a Child user's call against a Root-shared model logs
to the Child's analytics surface without cross-contaminating Root.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, DateTime, Integer, String, text
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session


class LLMCallLogBase(SQLModelSerializable):
    """Declarative shape of one LLM invocation audit row."""

    tenant_id: int = Field(
        sa_column=Column(
            Integer, nullable=False, server_default=text('1'), index=True,
            comment='F017 INV-T13: user leaf tenant at write time',
        ),
    )
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True),
    )
    model_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True, comment='llm_model.id'),
    )
    server_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, comment='llm_server.id'),
    )
    endpoint: Optional[str] = Field(
        default=None,
        sa_column=Column(String(256), nullable=True,
                         comment='Request endpoint URL (not secrets)'),
    )
    status: str = Field(
        sa_column=Column(String(16), nullable=False, index=True,
                         comment='success | error'),
    )
    latency_ms: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    error_msg: Optional[str] = Field(
        default=None,
        sa_column=Column(String(512), nullable=True,
                         comment='Truncated (<=500 chars) error string for failures'),
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'),
        ),
    )


class LLMCallLog(LLMCallLogBase, table=True):
    __tablename__ = 'llm_call_log'
    id: Optional[int] = Field(default=None, primary_key=True)


class LLMCallLogDao:
    @classmethod
    async def acreate(cls, log: LLMCallLog) -> LLMCallLog:
        async with get_async_db_session() as session:
            session.add(log)
            await session.commit()
            await session.refresh(log)
            return log

    @classmethod
    def create(cls, log: LLMCallLog) -> LLMCallLog:
        with get_sync_db_session() as session:
            session.add(log)
            session.commit()
            session.refresh(log)
            return log

    @classmethod
    async def alist_by_tenant(cls, tenant_id: int, limit: int = 100) -> List[LLMCallLog]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(LLMCallLog)
                .where(LLMCallLog.tenant_id == tenant_id)
                .order_by(LLMCallLog.created_at.desc())
                .limit(limit)
            )
            return list(result.all())

"""F017 llm_token_log — tenant-attributed token usage log.

INV-T13: token usage produced by a Child user talking to a Root-shared
model is attributed to the Child's leaf tenant (not Root), so the monthly
token quota (``model_tokens_monthly`` in QuotaService) can meter the Child
without reaching across the share boundary to drain Root.

The table mirrors the contract QuotaService already assumed:

  ``SELECT COALESCE(SUM(total_tokens), 0) FROM llm_token_log
   WHERE tenant_id = ? AND created_at >= DATE_FORMAT(NOW(), '%Y-%m-01')``

Before F017 the table did not exist; the SQL template degraded to 0 which
made AC-09 untestable. F017 creates the table, wires LLMTokenTracker to
populate it on ``on_llm_end``, and F016's monthly-count SQL begins
returning real numbers the moment a row lands.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, DateTime, Integer, String, text
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session


class LLMTokenLogBase(SQLModelSerializable):
    """Declarative shape of a single LLM invocation's token usage row.

    Kept intentionally flat — the analytics layer joins by ``tenant_id`` /
    ``user_id`` / ``model_id`` / ``server_id`` so they are all indexed.
    """

    tenant_id: int = Field(
        sa_column=Column(
            Integer, nullable=False, server_default=text('1'), index=True,
            comment='F017 INV-T13: user leaf tenant at write time (not resource tenant)',
        ),
    )
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment='Invoking user id'),
    )
    model_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True, comment='llm_model.id'),
    )
    server_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True, comment='llm_server.id'),
    )
    session_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(64), nullable=True, comment='Originating chat session (if any)'),
    )
    prompt_tokens: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default='0'),
    )
    completion_tokens: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default='0'),
    )
    total_tokens: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default='0'),
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'),
            comment='Write time; composite index with tenant_id serves the monthly sum query',
        ),
    )


class LLMTokenLog(LLMTokenLogBase, table=True):
    __tablename__ = 'llm_token_log'
    id: Optional[int] = Field(default=None, primary_key=True)


class LLMTokenLogDao:
    """Thin DAO — analytics read paths live in QuotaService SQL templates."""

    @classmethod
    async def acreate(cls, log: LLMTokenLog) -> LLMTokenLog:
        async with get_async_db_session() as session:
            session.add(log)
            await session.commit()
            await session.refresh(log)
            return log

    @classmethod
    def create(cls, log: LLMTokenLog) -> LLMTokenLog:
        with get_sync_db_session() as session:
            session.add(log)
            session.commit()
            session.refresh(log)
            return log

    @classmethod
    async def alist_by_tenant(cls, tenant_id: int, limit: int = 100) -> List[LLMTokenLog]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(LLMTokenLog)
                .where(LLMTokenLog.tenant_id == tenant_id)
                .order_by(LLMTokenLog.created_at.desc())
                .limit(limit)
            )
            return list(result.all())

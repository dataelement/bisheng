"""FailedTuple ORM — compensation queue for OpenFGA write failures (INV-4)."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, text, BigInteger
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session


class FailedTupleBase(SQLModelSerializable):
    action: str = Field(
        default='write',
        sa_column=Column(String(8), nullable=False, server_default='write',
                         comment='write | delete'),
    )
    fga_user: str = Field(
        sa_column=Column(String(256), nullable=False,
                         comment='OpenFGA user, e.g. user:7, department:5#member'),
    )
    relation: str = Field(
        sa_column=Column(String(64), nullable=False,
                         comment='OpenFGA relation, e.g. owner, viewer'),
    )
    object: str = Field(
        sa_column=Column(String(256), nullable=False,
                         comment='OpenFGA object, e.g. workflow:abc-123'),
    )
    retry_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default='0'))
    max_retries: int = Field(default=3, sa_column=Column(Integer, nullable=False, server_default='3'))
    status: str = Field(
        default='pending',
        sa_column=Column(String(16), nullable=False, server_default='pending',
                         comment='pending | succeeded | dead', index=True),
    )
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    tenant_id: int = Field(default=1, sa_column=Column(Integer, nullable=False, server_default='1', index=True))
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False,
                         server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
    )


class FailedTuple(FailedTupleBase, table=True):
    __tablename__ = 'failed_tuple'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )


class FailedTupleDao:
    @classmethod
    def get_pending(cls, limit: int = 100) -> List[FailedTuple]:
        """Get pending tuples that haven't exceeded max retries."""
        with get_sync_db_session() as session:
            stmt = (
                select(FailedTuple)
                .where(FailedTuple.status == 'pending')
                .where(FailedTuple.retry_count < FailedTuple.max_retries)
                .order_by(FailedTuple.create_time.asc())
                .limit(limit)
            )
            result = session.exec(stmt)
            return list(result.all())

    @classmethod
    def update_succeeded(cls, tuple_id: int) -> None:
        """Mark a tuple as succeeded."""
        with get_sync_db_session() as session:
            item = session.get(FailedTuple, tuple_id)
            if item:
                item.status = 'succeeded'
                session.add(item)
                session.commit()

    @classmethod
    def update_retry(cls, tuple_id: int, error: str) -> None:
        """Increment retry count and record error."""
        with get_sync_db_session() as session:
            item = session.get(FailedTuple, tuple_id)
            if item:
                item.retry_count += 1
                item.error_message = error
                session.add(item)
                session.commit()

    @classmethod
    def mark_dead(cls, tuple_id: int, error: str) -> None:
        """Mark a tuple as dead (exceeded max retries)."""
        with get_sync_db_session() as session:
            item = session.get(FailedTuple, tuple_id)
            if item:
                item.status = 'dead'
                item.error_message = error
                session.add(item)
                session.commit()

    @classmethod
    async def acreate_batch(cls, tuples: List[FailedTuple]) -> None:
        """Bulk insert failed tuples."""
        if not tuples:
            return
        async with get_async_db_session() as session:
            session.add_all(tuples)
            await session.commit()

    @classmethod
    async def aget_pending(cls, limit: int = 100) -> List[FailedTuple]:
        """Get pending tuples that haven't exceeded max retries."""
        async with get_async_db_session() as session:
            stmt = (
                select(FailedTuple)
                .where(FailedTuple.status == 'pending')
                .where(FailedTuple.retry_count < FailedTuple.max_retries)
                .order_by(FailedTuple.create_time.asc())
                .limit(limit)
            )
            result = await session.exec(stmt)
            return list(result.all())

    @classmethod
    async def aupdate_succeeded(cls, tuple_id: int) -> None:
        """Mark a tuple as succeeded."""
        async with get_async_db_session() as session:
            stmt = select(FailedTuple).where(FailedTuple.id == tuple_id)
            result = await session.exec(stmt)
            item = result.one_or_none()
            if item:
                item.status = 'succeeded'
                session.add(item)
                await session.commit()

    @classmethod
    async def aupdate_retry(cls, tuple_id: int, error: str) -> None:
        """Increment retry count and record error."""
        async with get_async_db_session() as session:
            stmt = select(FailedTuple).where(FailedTuple.id == tuple_id)
            result = await session.exec(stmt)
            item = result.one_or_none()
            if item:
                item.retry_count += 1
                item.error_message = error
                session.add(item)
                await session.commit()

    @classmethod
    async def amark_dead(cls, tuple_id: int, error: str) -> None:
        """Mark a tuple as dead (exceeded max retries)."""
        async with get_async_db_session() as session:
            stmt = select(FailedTuple).where(FailedTuple.id == tuple_id)
            result = await session.exec(stmt)
            item = result.one_or_none()
            if item:
                item.status = 'dead'
                item.error_message = error
                session.add(item)
                await session.commit()

    @classmethod
    async def adelete_old_succeeded(cls, before: datetime) -> int:
        """Delete succeeded records older than given datetime. Returns count deleted."""
        from sqlalchemy import delete as sa_delete

        async with get_async_db_session() as session:
            stmt = (
                sa_delete(FailedTuple)
                .where(FailedTuple.status == 'succeeded')
                .where(FailedTuple.update_time < before)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount

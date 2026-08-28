"""Rejected tag names that must not be generated or re-proposed."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, delete, func, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, col, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class TagBlacklistBase(SQLModelSerializable):
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("1"),
            index=True,
            comment="Tenant ID",
        ),
    )
    name: str = Field(
        sa_column=Column(String(255), nullable=False, comment="Blacklisted tag name"),
    )
    name_key: str = Field(
        sa_column=Column(String(255), nullable=False, comment="Normalized unique name key"),
    )
    user_id: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0"), comment="User who added the row"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class TagBlacklist(TagBlacklistBase, table=True):
    __tablename__ = "tag_blacklist"
    __table_args__ = (UniqueConstraint("tenant_id", "name_key", name="uq_tag_blacklist_tenant_name_key"),)

    id: int | None = Field(default=None, primary_key=True)


class TagBlacklistDao:
    @classmethod
    def count_sync(cls) -> int:
        statement = select(func.count(TagBlacklist.id))
        with get_sync_db_session() as session:
            return session.scalar(statement) or 0

    @classmethod
    async def acount(cls) -> int:
        statement = select(func.count(TagBlacklist.id))
        async with get_async_db_session() as session:
            return await session.scalar(statement) or 0

    @classmethod
    def list_catalog_entries_sync(cls) -> list[tuple[str, str]]:
        statement = select(TagBlacklist.name, TagBlacklist.name_key)
        with get_sync_db_session() as session:
            rows = session.exec(statement).all()
        return [(str(name).strip(), str(key)) for name, key in rows if str(name or "").strip() and key]

    @classmethod
    async def alist_existing_name_keys(cls, name_keys: list[str]) -> set[str]:
        if not name_keys:
            return set()
        statement = select(TagBlacklist.name_key).where(col(TagBlacklist.name_key).in_(name_keys))
        async with get_async_db_session() as session:
            rows = (await session.exec(statement)).all()
        return {str(key) for key in rows if key}

    @classmethod
    def list_existing_name_keys_sync(cls, name_keys: list[str]) -> set[str]:
        if not name_keys:
            return set()
        statement = select(TagBlacklist.name_key).where(col(TagBlacklist.name_key).in_(name_keys))
        with get_sync_db_session() as session:
            rows = session.exec(statement).all()
        return {str(key) for key in rows if key}

    @classmethod
    async def asearch(
        cls,
        *,
        keyword: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[TagBlacklist], int]:
        statement = select(TagBlacklist)
        count_statement = select(func.count(TagBlacklist.id))
        trimmed = (keyword or "").strip()
        if trimmed:
            like = f"%{trimmed}%"
            statement = statement.where(TagBlacklist.name.like(like))
            count_statement = count_statement.where(TagBlacklist.name.like(like))
        statement = statement.order_by(col(TagBlacklist.id).desc()).offset(offset).limit(limit)
        async with get_async_db_session() as session:
            rows = list((await session.exec(statement)).all())
            total = await session.scalar(count_statement) or 0
        return rows, int(total)

    @classmethod
    async def aget(cls, blacklist_id: int) -> TagBlacklist | None:
        async with get_async_db_session() as session:
            return await session.get(TagBlacklist, blacklist_id)

    @classmethod
    async def aadd(cls, *, name: str, name_key: str, user_id: int) -> TagBlacklist | None:
        row = TagBlacklist(name=name, name_key=name_key, user_id=user_id)
        async with get_async_db_session() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return None
            await session.refresh(row)
        return row

    @classmethod
    def add_sync(cls, *, name: str, name_key: str, user_id: int) -> TagBlacklist | None:
        row = TagBlacklist(name=name, name_key=name_key, user_id=user_id)
        with get_sync_db_session() as session:
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return None
            session.refresh(row)
        return row

    @classmethod
    async def adelete(cls, blacklist_id: int) -> bool:
        statement = delete(TagBlacklist).where(TagBlacklist.id == blacklist_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            await session.commit()
        return bool(getattr(result, "rowcount", 0))

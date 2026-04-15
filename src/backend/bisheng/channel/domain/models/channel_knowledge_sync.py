"""v2.5 Module D — Channel ➜ Knowledge Space sync configuration table.

One row per (channel, sub-channel?, knowledge_space, folder?) binding. NULL
`sub_channel_name` means the row is the main-channel's sync target.

The Celery worker (`worker/information/article.py::sync_information_article`)
reads enabled rows for each channel after its articles are indexed, then calls
`ChannelService.add_articles_to_knowledge_space` for the new article ids.
"""
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    CHAR,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    Text,
    VARCHAR,
    text,
)
from sqlmodel import Field, col, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session, get_sync_db_session


class ChannelKnowledgeSync(SQLModelSerializable, table=True):
    """Config row binding a channel (or one of its sub-channels) to a
    knowledge-space folder so that newly-synced articles auto-import."""

    __tablename__ = "channel_knowledge_sync"
    __table_args__ = (
        Index("idx_cks_channel_id", "channel_id"),
        Index("idx_cks_knowledge_space_id", "knowledge_space_id"),
    )

    id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Sync config ID",
        sa_column=Column(CHAR(36), unique=True, nullable=False, primary_key=True),
    )
    channel_id: str = Field(
        ...,
        description="Owning channel ID",
        sa_column=Column(CHAR(36), nullable=False),
    )
    # NULL ⇒ main channel; otherwise the sub-channel filter name
    # (matches ChannelFilterRules.name). See channel.py::ChannelFilterRules.
    sub_channel_name: Optional[str] = Field(
        default=None,
        description="Sub-channel name; NULL means main channel",
        sa_column=Column(VARCHAR(255), nullable=True),
    )
    knowledge_space_id: str = Field(
        ...,
        description="Target knowledge space ID",
        sa_column=Column(VARCHAR(36), nullable=False),
    )
    folder_id: Optional[str] = Field(
        default=None,
        description="Target folder ID inside the space; NULL = root",
        sa_column=Column(VARCHAR(36), nullable=True),
    )
    folder_path: Optional[str] = Field(
        default=None,
        description="Full display path of the target folder for UI (parent/child/target)",
        sa_column=Column(Text, nullable=True),
    )
    is_enabled: bool = Field(
        default=True,
        description="Whether auto-sync is currently active",
        sa_column=Column(Boolean, nullable=False, server_default=text("1")),
    )
    user_id: int = Field(
        ...,
        description="Creator user_id (only creator can edit)",
        sa_column=Column(Integer, nullable=False),
    )
    create_time: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(
            DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
        ),
    )
    update_time: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
    )


# --------------------------------------------------------------------------- #
# DAO — kept as classmethods rather than repository-pattern interfaces since
# this table is small & self-contained. Matches the style of other small DAOs
# (e.g. ChatMessageDao in database/models/message.py).
# --------------------------------------------------------------------------- #


class ChannelKnowledgeSyncDao:
    # ------- sync (used by Celery worker) -------

    @classmethod
    def list_by_channel_ids_enabled(cls, channel_ids: List[str]) -> List[ChannelKnowledgeSync]:
        if not channel_ids:
            return []
        with get_sync_db_session() as session:
            stmt = select(ChannelKnowledgeSync).where(
                col(ChannelKnowledgeSync.channel_id).in_(channel_ids),
                ChannelKnowledgeSync.is_enabled.is_(True),
            )
            return list(session.exec(stmt).all())

    @classmethod
    def touch_update_time(cls, sync_id: str) -> None:
        with get_sync_db_session() as session:
            row = session.get(ChannelKnowledgeSync, sync_id)
            if not row:
                return
            row.update_time = datetime.now()
            session.add(row)
            session.commit()

    # ------- async (used by API endpoints) -------

    @classmethod
    async def alist_by_channel_id(cls, channel_id: str) -> List[ChannelKnowledgeSync]:
        async with get_async_db_session() as session:
            stmt = (
                select(ChannelKnowledgeSync)
                .where(ChannelKnowledgeSync.channel_id == channel_id)
                .order_by(ChannelKnowledgeSync.create_time.asc())
            )
            res = await session.exec(stmt)
            return list(res.all())

    @classmethod
    async def abulk_insert(cls, rows: List[ChannelKnowledgeSync]) -> List[ChannelKnowledgeSync]:
        if not rows:
            return []
        async with get_async_db_session() as session:
            for r in rows:
                session.add(r)
            await session.commit()
            for r in rows:
                await session.refresh(r)
            return rows

    @classmethod
    async def adelete_by_channel(cls, channel_id: str) -> int:
        async with get_async_db_session() as session:
            stmt = select(ChannelKnowledgeSync).where(
                ChannelKnowledgeSync.channel_id == channel_id,
            )
            res = await session.exec(stmt)
            rows = list(res.all())
            for r in rows:
                await session.delete(r)
            await session.commit()
            return len(rows)

    @classmethod
    async def aget(cls, sync_id: str) -> Optional[ChannelKnowledgeSync]:
        async with get_async_db_session() as session:
            return await session.get(ChannelKnowledgeSync, sync_id)

    @classmethod
    async def ainsert(cls, row: ChannelKnowledgeSync) -> ChannelKnowledgeSync:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    @classmethod
    async def adelete(cls, sync_id: str) -> int:
        async with get_async_db_session() as session:
            row = await session.get(ChannelKnowledgeSync, sync_id)
            if not row:
                return 0
            await session.delete(row)
            await session.commit()
            return 1

    @classmethod
    async def aset_enabled(
        cls, channel_id: str, sub_channel_name: Optional[str], enabled: bool,
    ) -> int:
        """Toggle all rows for a given (channel, sub_channel) scope."""
        async with get_async_db_session() as session:
            stmt = select(ChannelKnowledgeSync).where(
                ChannelKnowledgeSync.channel_id == channel_id,
                (
                    ChannelKnowledgeSync.sub_channel_name.is_(None)
                    if sub_channel_name is None
                    else ChannelKnowledgeSync.sub_channel_name == sub_channel_name
                ),
            )
            res = await session.exec(stmt)
            rows = list(res.all())
            for r in rows:
                r.is_enabled = enabled
                r.update_time = datetime.now()
                session.add(r)
            await session.commit()
            return len(rows)

    @classmethod
    async def areplace_for_channel(
        cls, channel_id: str, rows: List["ChannelKnowledgeSync"],
    ) -> int:
        """Atomically replace every sync row for a channel with the provided list.

        Used when the channel's sync config is saved together with the channel
        itself. Existing rows for `channel_id` are deleted; `rows` are inserted.
        The caller is responsible for setting `channel_id` / `user_id` on each row.
        """
        async with get_async_db_session() as session:
            old_stmt = select(ChannelKnowledgeSync).where(
                ChannelKnowledgeSync.channel_id == channel_id,
            )
            old_rows = list((await session.exec(old_stmt)).all())
            for r in old_rows:
                await session.delete(r)
            for r in rows:
                session.add(r)
            await session.commit()
            return len(rows)

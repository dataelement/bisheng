from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, Column, DateTime, Integer, UniqueConstraint, delete, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session


class ChannelUserPinBase(SQLModelSerializable):
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment="User who pinned the channel"),
    )
    channel_id: str = Field(
        sa_column=Column(CHAR(36), nullable=False, comment="Pinned channel id"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )


class ChannelUserPin(ChannelUserPinBase, table=True):
    """Per-user channel pin.

    Mirrors ``knowledge_space_user_pin``: pinning is a pure personal UI preference,
    intentionally decoupled from ``space_channel_member``. A user may pin a channel
    reached only via ReBAC / department authorization (no membership row). Storing
    pins here keeps them out of member counts, member-management and approval flows,
    and makes a stale pin (user later loses access) inert — the channel lists
    re-check visibility on read, so an unreachable pin simply never renders.
    """

    __tablename__ = "channel_user_pin"
    __table_args__ = (UniqueConstraint("user_id", "channel_id", name="uk_cup_user_channel"),)

    id: int | None = Field(default=None, primary_key=True)


class ChannelUserPinDao(ChannelUserPinBase):
    @classmethod
    async def pin(cls, user_id: int, channel_id: str) -> None:
        """Idempotently pin ``channel_id`` for ``user_id``.

        A duplicate pin is a no-op: we pre-check by natural key, and still guard
        the INSERT against a concurrent racer with the unique constraint.
        """
        async with get_async_db_session() as session:
            existing = (
                await session.exec(
                    select(ChannelUserPin).where(
                        ChannelUserPin.user_id == user_id,
                        ChannelUserPin.channel_id == channel_id,
                    )
                )
            ).first()
            if existing is not None:
                return
            session.add(ChannelUserPin(user_id=user_id, channel_id=channel_id))
            try:
                await session.commit()
            except IntegrityError:
                # Concurrent request inserted the same (user_id, channel_id) first;
                # the unique constraint rejected ours — the pin already exists.
                await session.rollback()

    @classmethod
    async def unpin(cls, user_id: int, channel_id: str) -> None:
        """Remove the pin for ``channel_id`` / ``user_id``. No-op if absent."""
        async with get_async_db_session() as session:
            await session.exec(
                delete(ChannelUserPin).where(
                    ChannelUserPin.user_id == user_id,
                    ChannelUserPin.channel_id == channel_id,
                )
            )
            await session.commit()

    @classmethod
    async def list_pinned_channel_ids(cls, user_id: int) -> set[str]:
        """Return the set of channel ids the user has pinned."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(ChannelUserPin.channel_id).where(
                    ChannelUserPin.user_id == user_id,
                )
            )
            return set(result.all())

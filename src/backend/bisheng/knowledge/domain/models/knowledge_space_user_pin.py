from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, UniqueConstraint, delete, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session


class KnowledgeSpaceUserPinBase(SQLModelSerializable):
    user_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True, comment="User who pinned the space"),
    )
    space_id: int = Field(
        sa_column=Column(Integer, nullable=False, comment="Pinned knowledge space id"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )


class KnowledgeSpaceUserPin(KnowledgeSpaceUserPinBase, table=True):
    """Per-user knowledge-space pin.

    Pinning is a pure personal UI preference, intentionally decoupled from
    ``space_channel_member``: a user may pin a space they can only reach via
    ReBAC / department authorization (no membership row). Storing pins here
    keeps them out of member counts, member-management and approval flows, and
    makes a stale pin (user later loses access) inert — every space listing
    re-checks ``view_space`` on read, so an unreachable pin simply never renders.
    """

    __tablename__ = "knowledge_space_user_pin"
    __table_args__ = (UniqueConstraint("user_id", "space_id", name="uk_ksup_user_space"),)

    id: int | None = Field(default=None, primary_key=True)


class KnowledgeSpaceUserPinDao(KnowledgeSpaceUserPinBase):
    @classmethod
    async def pin(cls, user_id: int, space_id: int) -> None:
        """Idempotently pin ``space_id`` for ``user_id``.

        A duplicate pin is a no-op: we pre-check by natural key, and still guard
        the INSERT against a concurrent racer with the unique constraint.
        """
        async with get_async_db_session() as session:
            existing = (
                await session.exec(
                    select(KnowledgeSpaceUserPin).where(
                        KnowledgeSpaceUserPin.user_id == user_id,
                        KnowledgeSpaceUserPin.space_id == space_id,
                    )
                )
            ).first()
            if existing is not None:
                return
            session.add(KnowledgeSpaceUserPin(user_id=user_id, space_id=space_id))
            try:
                await session.commit()
            except IntegrityError:
                # Concurrent request inserted the same (user_id, space_id) first;
                # the unique constraint rejected ours — the pin already exists.
                await session.rollback()

    @classmethod
    async def unpin(cls, user_id: int, space_id: int) -> None:
        """Remove the pin for ``space_id`` / ``user_id``. No-op if absent."""
        async with get_async_db_session() as session:
            await session.exec(
                delete(KnowledgeSpaceUserPin).where(
                    KnowledgeSpaceUserPin.user_id == user_id,
                    KnowledgeSpaceUserPin.space_id == space_id,
                )
            )
            await session.commit()

    @classmethod
    async def list_pinned_space_ids(cls, user_id: int) -> set[int]:
        """Return the set of space ids the user has pinned."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(KnowledgeSpaceUserPin.space_id).where(
                    KnowledgeSpaceUserPin.user_id == user_id,
                )
            )
            return set(result.all())

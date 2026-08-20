"""F051 — backfill legacy space_channel_member.is_pinned (channel rows) into the
new per-user channel_user_pin table. Mirrors the F044 space-pin backfill test."""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel_user_pin import ChannelUserPin
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from scripts.backfill_channel_user_pin import backfill

_CID = "cccccccccccc4cccccccccccccccccccc"
_CID_OTHER = "dddddddddddd4dddddddddddddddddddd"


async def _member(session, *, user_id, business_id, is_pinned, business_type, status):
    session.add(
        SpaceChannelMember(
            business_id=str(business_id),
            business_type=business_type,
            user_id=user_id,
            user_role=UserRoleEnum.MEMBER,
            status=status,
            is_pinned=is_pinned,
        )
    )
    await session.commit()


async def test_backfill_copies_active_pinned_channel_members(async_db_session: AsyncSession):
    # pinned channel member → copied
    await _member(
        async_db_session,
        user_id=1,
        business_id=_CID,
        is_pinned=True,
        business_type=BusinessTypeEnum.CHANNEL,
        status=MembershipStatusEnum.ACTIVE,
    )
    # not pinned → skipped
    await _member(
        async_db_session,
        user_id=1,
        business_id=_CID_OTHER,
        is_pinned=False,
        business_type=BusinessTypeEnum.CHANNEL,
        status=MembershipStatusEnum.ACTIVE,
    )
    # pinned but a SPACE, not a channel → skipped
    await _member(
        async_db_session,
        user_id=1,
        business_id=100,
        is_pinned=True,
        business_type=BusinessTypeEnum.SPACE,
        status=MembershipStatusEnum.ACTIVE,
    )
    # pinned channel but not ACTIVE → skipped
    await _member(
        async_db_session,
        user_id=2,
        business_id=_CID,
        is_pinned=True,
        business_type=BusinessTypeEnum.CHANNEL,
        status=MembershipStatusEnum.PENDING,
    )

    report = await backfill(async_db_session)
    assert report.created == 1

    rows = (await async_db_session.exec(select(ChannelUserPin))).all()
    assert {(r.user_id, r.channel_id) for r in rows} == {(1, _CID)}


async def test_backfill_is_idempotent(async_db_session: AsyncSession):
    await _member(
        async_db_session,
        user_id=1,
        business_id=_CID,
        is_pinned=True,
        business_type=BusinessTypeEnum.CHANNEL,
        status=MembershipStatusEnum.ACTIVE,
    )

    first = await backfill(async_db_session)
    assert first.created == 1
    second = await backfill(async_db_session)
    assert second.created == 0  # already backfilled, no duplicate

    rows = (await async_db_session.exec(select(ChannelUserPin))).all()
    assert len(rows) == 1

"""F037 AC6 — backfill legacy space_channel_member.is_pinned into the new
per-user knowledge_space_user_pin table."""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.knowledge.domain.models.knowledge_space_user_pin import KnowledgeSpaceUserPin
from scripts.backfill_knowledge_space_user_pin import backfill


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


async def test_backfill_copies_active_pinned_space_members(async_db_session: AsyncSession):
    # pinned space member → copied
    await _member(
        async_db_session,
        user_id=1,
        business_id=100,
        is_pinned=True,
        business_type=BusinessTypeEnum.SPACE,
        status=MembershipStatusEnum.ACTIVE,
    )
    # not pinned → skipped
    await _member(
        async_db_session,
        user_id=1,
        business_id=101,
        is_pinned=False,
        business_type=BusinessTypeEnum.SPACE,
        status=MembershipStatusEnum.ACTIVE,
    )
    # pinned but a CHANNEL, not a space → skipped
    await _member(
        async_db_session,
        user_id=1,
        business_id=200,
        is_pinned=True,
        business_type=BusinessTypeEnum.CHANNEL,
        status=MembershipStatusEnum.ACTIVE,
    )

    report = await backfill(async_db_session)
    assert report.created == 1

    rows = (await async_db_session.exec(select(KnowledgeSpaceUserPin))).all()
    assert {(r.user_id, r.space_id) for r in rows} == {(1, 100)}


async def test_backfill_is_idempotent(async_db_session: AsyncSession):
    await _member(
        async_db_session,
        user_id=1,
        business_id=100,
        is_pinned=True,
        business_type=BusinessTypeEnum.SPACE,
        status=MembershipStatusEnum.ACTIVE,
    )

    first = await backfill(async_db_session)
    assert first.created == 1
    second = await backfill(async_db_session)
    assert second.created == 0  # already backfilled, no duplicate

    rows = (await async_db_session.exec(select(KnowledgeSpaceUserPin))).all()
    assert len(rows) == 1

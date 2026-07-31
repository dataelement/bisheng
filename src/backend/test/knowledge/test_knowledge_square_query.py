from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.models.knowledge import (
    AuthTypeEnum,
    Knowledge,
    KnowledgeDao,
    KnowledgeTypeEnum,
)


def _space(space_id: int, update_time: datetime) -> Knowledge:
    return Knowledge(
        id=space_id,
        user_id=99,
        name=f"space-{space_id}",
        type=KnowledgeTypeEnum.SPACE.value,
        description="",
        is_released=True,
        auth_type=AuthTypeEnum.PUBLIC,
        create_time=update_time,
        update_time=update_time,
    )


def _member(
    space_id: int,
    user_id: int,
    status: MembershipStatusEnum = MembershipStatusEnum.ACTIVE,
) -> SpaceChannelMember:
    return SpaceChannelMember(
        business_id=str(space_id),
        business_type=BusinessTypeEnum.SPACE,
        user_id=user_id,
        user_role=UserRoleEnum.MEMBER,
        status=status,
        update_time=datetime(2026, 1, 1),
    )


@pytest.mark.asyncio
async def test_square_orders_unsubscribed_before_applied_then_by_unique_subscriber_count(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Knowledge.__table__.create)
        await connection.run_sync(SpaceChannelMember.__table__.create)

    now = datetime(2026, 1, 1)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                _space(1, now),
                _space(2, now),
                _space(3, now),
                _space(4, now),
                _space(5, now),
                _member(1, 7, MembershipStatusEnum.PENDING),
                _member(1, 10),
                _member(1, 10),
                _member(1, 11),
                _member(2, 12),
                _member(3, 7),
                _member(3, 13),
                _member(3, 13),
                _member(4, 7),
                _member(5, 14),
                _member(5, 14),
                _member(5, 15),
            ]
        )
        await session.commit()

        @asynccontextmanager
        async def _get_test_session():
            yield session

        monkeypatch.setattr(knowledge_module, "get_async_db_session", _get_test_session)
        with bypass_tenant_filter():
            rows = await KnowledgeDao.async_get_public_spaces_paginated(
                user_id=7,
                page=1,
                page_size=20,
            )

    await engine.dispose()

    assert [row[0].id for row in rows] == [5, 2, 1, 3, 4]
    assert [row[3] for row in rows] == [2, 1, 2, 2, 1]
    assert rows[2][1] == MembershipStatusEnum.PENDING

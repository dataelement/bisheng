from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.channel.domain.repositories.implementations.channel_repository_impl import (
    ChannelRepositoryImpl,
)
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.tenant import bypass_tenant_filter


class _DmDialect(DefaultDialect):
    name = "dm"


class _EmptyResult:
    def all(self) -> list[object]:
        return []

    def one(self) -> int:
        return 0


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def exec(self, statement):
        self.statements.append(statement)
        return _EmptyResult()


def _channel(channel_id: str, update_time: datetime) -> Channel:
    return Channel(
        id=channel_id,
        name=channel_id,
        description="",
        source_list=[],
        visibility=ChannelVisibilityEnum.PUBLIC,
        filter_rules=[],
        user_id=99,
        is_released=True,
        create_time=update_time,
        update_time=update_time,
    )


def _member(
    channel_id: str,
    user_id: int,
    status: MembershipStatusEnum = MembershipStatusEnum.ACTIVE,
) -> SpaceChannelMember:
    return SpaceChannelMember(
        business_id=channel_id,
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=user_id,
        user_role=UserRoleEnum.MEMBER,
        status=status,
        update_time=datetime(2026, 1, 1),
    )


@pytest.mark.asyncio
async def test_square_orders_unsubscribed_before_applied_then_by_unique_subscriber_count():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Channel.__table__.create)
        await connection.run_sync(SpaceChannelMember.__table__.create)

    now = datetime(2026, 1, 1)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                _channel("00-not-member-popular", now),
                _channel("01-pending-popular", now),
                _channel("02-not-member-less-popular", now),
                _channel("03-member-popular", now),
                _channel("04-member-less-popular", now),
                _member("00-not-member-popular", 14),
                _member("00-not-member-popular", 14),
                _member("00-not-member-popular", 15),
                _member("01-pending-popular", 7, MembershipStatusEnum.PENDING),
                _member("01-pending-popular", 10),
                _member("01-pending-popular", 10),
                _member("01-pending-popular", 11),
                _member("02-not-member-less-popular", 12),
                _member("03-member-popular", 7),
                _member("03-member-popular", 13),
                _member("03-member-popular", 13),
                _member("04-member-less-popular", 7),
            ]
        )
        await session.commit()

        with bypass_tenant_filter():
            rows = await ChannelRepositoryImpl(session).find_square_channels(
                user_id=7,
                page=1,
                page_size=20,
            )

    await engine.dispose()

    assert [row[0].id for row in rows] == [
        "00-not-member-popular",
        "02-not-member-less-popular",
        "01-pending-popular",
        "03-member-popular",
        "04-member-less-popular",
    ]
    assert [row[3] for row in rows] == [2, 1, 2, 2, 1]
    assert rows[2][1] == MembershipStatusEnum.PENDING


async def test_channel_release_filters_compile_as_dm8_compatible_equality():
    session = _RecordingSession()
    repository = ChannelRepositoryImpl(session)

    await repository.find_square_channels(user_id=7)
    await repository.find_public_recommend_channels(user_id=7)
    await repository.count_square_channels()

    compiled_statements = [
        str(
            statement.compile(
                dialect=_DmDialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for statement in session.statements
    ]

    assert len(compiled_statements) == 3
    assert all("channel.is_released IS 1" not in statement for statement in compiled_statements)
    assert all("channel.is_released = 1" in statement for statement in compiled_statements)


async def test_square_subscriber_sort_uses_subquery_column_without_parameterized_coalesce():
    session = _RecordingSession()

    await ChannelRepositoryImpl(session).find_square_channels(user_id=7)

    subscriber_order = str(list(session.statements[0]._order_by_clauses)[1])
    assert "coalesce" not in subscriber_order.lower()
    assert subscriber_order.endswith("subscriber_count DESC")

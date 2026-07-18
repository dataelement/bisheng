from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    ChannelRelationEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.common.repositories.implementations.space_channel_member_repository_impl import (
    SpaceChannelMemberRepositoryImpl,
)


@pytest.mark.asyncio
async def test_channel_membership_reads_lowercase_relation_values(async_db_session: AsyncSession):
    repo = SpaceChannelMemberRepositoryImpl(async_db_session)
    await async_db_session.exec(
        text(
            """
            INSERT INTO space_channel_member (
                business_id,
                business_type,
                user_id,
                user_role,
                status,
                relation,
                grant_relation
            )
            VALUES (
                'channel-lowercase-relation',
                'CHANNEL',
                42,
                'ADMIN',
                'ACTIVE',
                'manager',
                'manager'
            )
            """
        )
    )
    await async_db_session.commit()

    rows = await repo.find_channel_memberships(42, [UserRoleEnum.ADMIN])

    assert len(rows) == 1
    assert rows[0].relation == ChannelRelationEnum.MANAGER
    assert rows[0].grant_relation == ChannelRelationEnum.MANAGER


@pytest.mark.asyncio
async def test_legacy_channel_roles_resolve_to_four_level_relations(async_db_session: AsyncSession):
    repo = SpaceChannelMemberRepositoryImpl(async_db_session)
    rows = [
        SpaceChannelMember(
            business_id='channel-1',
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=1,
            user_role=UserRoleEnum.CREATOR,
            status=MembershipStatusEnum.ACTIVE,
        ),
        SpaceChannelMember(
            business_id='channel-1',
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=2,
            user_role=UserRoleEnum.ADMIN,
            status=MembershipStatusEnum.ACTIVE,
        ),
        SpaceChannelMember(
            business_id='channel-1',
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=3,
            user_role=UserRoleEnum.MEMBER,
            status=MembershipStatusEnum.ACTIVE,
        ),
    ]
    async_db_session.add_all(rows)
    await async_db_session.commit()

    assert await repo.get_effective_channel_relation('channel-1', 1) == ChannelRelationEnum.OWNER
    assert await repo.get_effective_channel_relation('channel-1', 2) == ChannelRelationEnum.MANAGER
    assert await repo.get_effective_channel_relation('channel-1', 3) == ChannelRelationEnum.VIEWER


@pytest.mark.asyncio
async def test_channel_membership_sources_return_highest_relation(async_db_session: AsyncSession):
    repo = SpaceChannelMemberRepositoryImpl(async_db_session)

    await repo.upsert_channel_membership_source(
        channel_id='channel-2',
        user_id=10,
        relation=ChannelRelationEnum.VIEWER,
        grant_subject_type='department',
        grant_subject_id=100,
        grant_binding_key='department-viewer',
    )
    await repo.upsert_channel_membership_source(
        channel_id='channel-2',
        user_id=10,
        relation=ChannelRelationEnum.MANAGER,
        grant_subject_type='user',
        grant_subject_id=10,
        grant_binding_key='user-manager',
    )
    await repo.upsert_channel_membership_source(
        channel_id='channel-2',
        user_id=10,
        relation=ChannelRelationEnum.EDITOR,
        grant_subject_type='user_group',
        grant_subject_id=200,
        grant_binding_key='group-editor',
    )

    membership = await repo.find_membership('channel-2', BusinessTypeEnum.CHANNEL, 10)
    assert membership is not None
    assert membership.relation == ChannelRelationEnum.MANAGER
    assert await repo.get_effective_channel_relation('channel-2', 10) == ChannelRelationEnum.MANAGER


@pytest.mark.asyncio
async def test_revoke_channel_membership_source_downgrades_to_remaining_relation(
    async_db_session: AsyncSession,
):
    repo = SpaceChannelMemberRepositoryImpl(async_db_session)
    await repo.upsert_channel_membership_source(
        channel_id='channel-3',
        user_id=20,
        relation=ChannelRelationEnum.MANAGER,
        grant_subject_type='user',
        grant_subject_id=20,
        grant_binding_key='user-manager',
    )
    await repo.upsert_channel_membership_source(
        channel_id='channel-3',
        user_id=20,
        relation=ChannelRelationEnum.VIEWER,
        grant_subject_type='department',
        grant_subject_id=300,
        grant_binding_key='department-viewer',
    )

    deleted = await repo.delete_channel_membership_source('channel-3', 'user-manager')

    assert deleted == 1
    assert await repo.get_effective_channel_relation('channel-3', 20) == ChannelRelationEnum.VIEWER
    membership = await repo.find_membership('channel-3', BusinessTypeEnum.CHANNEL, 20)
    assert membership is not None
    assert membership.grant_subject_type == 'department'


@pytest.mark.asyncio
async def test_revoke_last_channel_membership_source_removes_visibility(async_db_session: AsyncSession):
    repo = SpaceChannelMemberRepositoryImpl(async_db_session)
    await repo.upsert_channel_membership_source(
        channel_id='channel-4',
        user_id=30,
        relation=ChannelRelationEnum.VIEWER,
        grant_subject_type='user_group',
        grant_subject_id=400,
        grant_binding_key='group-viewer',
    )

    deleted = await repo.delete_channel_membership_source('channel-4', 'group-viewer')

    assert deleted == 1
    assert await repo.get_effective_channel_relation('channel-4', 30) is None
    rows = (
        await async_db_session.exec(
            select(SpaceChannelMember).where(
                SpaceChannelMember.business_id == 'channel-4',
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
                SpaceChannelMember.user_id == 30,
            )
        )
    ).all()
    assert rows == []


@pytest.mark.asyncio
async def test_remove_channel_subscription_members_preserves_authorized_grants(async_db_session: AsyncSession):
    repo = SpaceChannelMemberRepositoryImpl(async_db_session)
    rows = [
        SpaceChannelMember(
            business_id='channel-private',
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=1,
            user_role=UserRoleEnum.CREATOR,
            status=MembershipStatusEnum.ACTIVE,
            relation=ChannelRelationEnum.OWNER,
            grant_subject_type='self',
            grant_subject_id=1,
            grant_binding_key='channel:channel-private:self:1:owner:-',
        ),
        SpaceChannelMember(
            business_id='channel-private',
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=2,
            user_role=UserRoleEnum.MEMBER,
            status=MembershipStatusEnum.ACTIVE,
            relation=ChannelRelationEnum.VIEWER,
        ),
        SpaceChannelMember(
            business_id='channel-private',
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=3,
            user_role=UserRoleEnum.MEMBER,
            status=MembershipStatusEnum.PENDING,
            relation=ChannelRelationEnum.VIEWER,
        ),
        SpaceChannelMember(
            business_id='channel-private',
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=4,
            user_role=UserRoleEnum.MEMBER,
            status=MembershipStatusEnum.ACTIVE,
            relation=ChannelRelationEnum.EDITOR,
            grant_subject_type='user',
            grant_subject_id=4,
            grant_binding_key='channel:channel-private:user:4:editor:-',
        ),
        SpaceChannelMember(
            business_id='channel-private',
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=5,
            user_role=UserRoleEnum.MEMBER,
            status=MembershipStatusEnum.ACTIVE,
            relation=ChannelRelationEnum.VIEWER,
            grant_subject_type='department',
            grant_subject_id=10,
            grant_binding_key='channel:channel-private:department:10:viewer:children',
        ),
    ]
    async_db_session.add_all(rows)
    await async_db_session.commit()

    removed = await repo.remove_channel_subscription_members('channel-private')

    remaining = (
        await async_db_session.exec(
            select(SpaceChannelMember.user_id).where(
                SpaceChannelMember.business_id == 'channel-private',
                SpaceChannelMember.business_type == BusinessTypeEnum.CHANNEL,
            )
        )
    ).all()
    assert removed == 2
    assert sorted(remaining) == [1, 4, 5]


@pytest.mark.asyncio
async def test_find_membership_skips_pending_channel_by_default(async_db_session: AsyncSession):
    """Default channel lookup only returns ACTIVE members (existing behavior)."""
    repo = SpaceChannelMemberRepositoryImpl(async_db_session)
    async_db_session.add(
        SpaceChannelMember(
            business_id='channel-pending',
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=427,
            user_role=UserRoleEnum.MEMBER,
            status=MembershipStatusEnum.PENDING,
            relation=ChannelRelationEnum.VIEWER,
        )
    )
    await async_db_session.commit()

    found = await repo.find_membership('channel-pending', BusinessTypeEnum.CHANNEL, 427)

    assert found is None


@pytest.mark.asyncio
async def test_find_membership_returns_pending_channel_when_include_inactive(async_db_session: AsyncSession):
    """Approval activation must locate the PENDING membership to flip it to ACTIVE."""
    repo = SpaceChannelMemberRepositoryImpl(async_db_session)
    async_db_session.add(
        SpaceChannelMember(
            business_id='channel-pending',
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=427,
            user_role=UserRoleEnum.MEMBER,
            status=MembershipStatusEnum.PENDING,
            relation=ChannelRelationEnum.VIEWER,
        )
    )
    await async_db_session.commit()

    found = await repo.find_membership(
        'channel-pending', BusinessTypeEnum.CHANNEL, 427, include_inactive=True
    )

    assert found is not None
    assert found.status == MembershipStatusEnum.PENDING

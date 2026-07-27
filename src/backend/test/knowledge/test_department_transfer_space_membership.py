from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import (
    KnowledgeSpaceSubscribeScenarioHandler,
)
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupItemStatus,
)
from bisheng.permission.domain.repositories.implementations.department_transfer_permission_cleanup_repository_impl import (
    DepartmentTransferPermissionCleanupRepositoryImpl,
)


async def _add_membership(
    session,
    *,
    source: str,
    role: UserRoleEnum = UserRoleEnum.MEMBER,
) -> SpaceChannelMember:
    member = SpaceChannelMember(
        business_id="100",
        business_type=BusinessTypeEnum.SPACE,
        user_id=7,
        user_role=role,
        status=MembershipStatusEnum.ACTIVE,
        membership_source=source,
    )
    session.add(member)
    await session.flush()
    return member


@pytest.mark.asyncio
async def test_manual_membership_snapshot_is_removed(async_db_session):
    member = await _add_membership(async_db_session, source="manual")
    repository = DepartmentTransferPermissionCleanupRepositoryImpl(async_db_session)

    result = await repository.remove_membership_snapshot(
        member_id=int(member.id),
        user_id=7,
        space_id=100,
        expected_source="manual",
    )

    assert result == DepartmentTransferCleanupItemStatus.REVOKED
    assert await async_db_session.get(SpaceChannelMember, int(member.id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "role"),
    [
        ("department_admin", UserRoleEnum.ADMIN),
        ("manual", UserRoleEnum.CREATOR),
    ],
)
async def test_intrinsic_or_department_admin_membership_is_preserved(
    async_db_session,
    source,
    role,
):
    member = await _add_membership(async_db_session, source=source, role=role)
    repository = DepartmentTransferPermissionCleanupRepositoryImpl(async_db_session)

    result = await repository.remove_membership_snapshot(
        member_id=int(member.id),
        user_id=7,
        space_id=100,
        expected_source=source,
    )

    assert result == DepartmentTransferCleanupItemStatus.SKIPPED
    assert await async_db_session.get(SpaceChannelMember, int(member.id)) is member


@pytest.mark.asyncio
async def test_membership_rebound_after_snapshot_is_not_removed(async_db_session):
    member = await _add_membership(async_db_session, source="manual")
    member.membership_source = "rebac"
    async_db_session.add(member)
    await async_db_session.flush()
    repository = DepartmentTransferPermissionCleanupRepositoryImpl(async_db_session)

    result = await repository.remove_membership_snapshot(
        member_id=int(member.id),
        user_id=7,
        space_id=100,
        expected_source="manual",
    )

    assert result == DepartmentTransferCleanupItemStatus.SKIPPED
    assert await async_db_session.get(SpaceChannelMember, int(member.id)) is member


@pytest.mark.asyncio
async def test_approved_space_subscription_is_included_in_cleanup(async_db_session):
    member = SpaceChannelMember(
        business_id="100",
        business_type=BusinessTypeEnum.SPACE,
        user_id=7,
        user_role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.PENDING,
        membership_source="manual",
    )
    async_db_session.add(member)
    await async_db_session.flush()

    async def update_member(row):
        async_db_session.add(row)
        await async_db_session.flush()
        return row

    handler = KnowledgeSpaceSubscribeScenarioHandler(
        find_member=AsyncMock(return_value=member),
        update_member=AsyncMock(side_effect=update_member),
        sync_permissions=AsyncMock(),
    )
    await handler.on_approved(
        instance_id=5001,
        payload_snapshot={
            "space_id": 100,
            "applicant_user_id": 7,
        },
    )
    repository = DepartmentTransferPermissionCleanupRepositoryImpl(async_db_session)

    result = await repository.remove_membership_snapshot(
        member_id=int(member.id),
        user_id=7,
        space_id=100,
        expected_source="manual",
    )

    assert result == DepartmentTransferCleanupItemStatus.REVOKED
    assert await async_db_session.get(SpaceChannelMember, int(member.id)) is None


@pytest.mark.asyncio
async def test_pending_space_subscription_is_not_snapshotted_or_cancelled(
    async_db_session,
):
    pending = SpaceChannelMember(
        business_id="100",
        business_type=BusinessTypeEnum.SPACE,
        user_id=7,
        user_role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.PENDING,
        membership_source="manual",
    )
    async_db_session.add(pending)
    await async_db_session.flush()
    repository = DepartmentTransferPermissionCleanupRepositoryImpl(async_db_session)

    active = await repository.list_active_memberships(user_id=7)

    assert active == []
    assert await async_db_session.get(SpaceChannelMember, int(pending.id)) is pending

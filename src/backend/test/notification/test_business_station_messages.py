from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bisheng.channel.domain.schemas.channel_manager_schema import UpdateMemberRoleRequest
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)


class _FakeChannelMemberRepository:
    def __init__(self, current_member: SpaceChannelMember, target_member: SpaceChannelMember) -> None:
        self.current_member = current_member
        self.target_member = target_member
        self.updated: SpaceChannelMember | None = None

    async def find_membership(self, *, user_id: int, **_kwargs) -> SpaceChannelMember | None:
        if user_id == self.current_member.user_id:
            return self.current_member
        if user_id == self.target_member.user_id:
            return self.target_member
        return None

    async def find_members_by_role(self, **_kwargs) -> list[SpaceChannelMember]:
        return []

    async def update(self, member: SpaceChannelMember) -> SpaceChannelMember:
        self.updated = member
        return member


def _channel_member(*, user_id: int, role: UserRoleEnum) -> SpaceChannelMember:
    return SpaceChannelMember(
        id=user_id,
        business_id="channel-1",
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=user_id,
        user_role=role,
        status=MembershipStatusEnum.ACTIVE,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("already_can_manage", "expected_notification_count"),
    [(False, 1), (True, 0)],
)
async def test_channel_admin_assignment_notifies_only_when_effective_admin_is_new(
    monkeypatch: pytest.MonkeyPatch,
    already_can_manage: bool,
    expected_notification_count: int,
) -> None:
    repo = _FakeChannelMemberRepository(
        current_member=_channel_member(user_id=1, role=UserRoleEnum.CREATOR),
        target_member=_channel_member(user_id=2, role=UserRoleEnum.MEMBER),
    )
    service = ChannelService(
        channel_repository=MagicMock(),
        space_channel_member_repository=repo,
        channel_info_source_repository=MagicMock(),
        article_es_service=MagicMock(),
        message_service=MagicMock(),
    )

    async def _can_manage(_user_id: int, _channel_id: str) -> bool:
        return already_can_manage

    send_calls: list[dict] = []

    async def _send_admin_assignment_notification(self, **kwargs) -> None:
        send_calls.append(kwargs)

    monkeypatch.setattr(ChannelService, "_user_can_manage_channel", staticmethod(_can_manage))
    monkeypatch.setattr(
        ChannelService,
        "_send_admin_assignment_notification",
        _send_admin_assignment_notification,
    )

    await service.update_member_role(
        UpdateMemberRoleRequest(channel_id="channel-1", user_id=2, role="admin"),
        login_user=SimpleNamespace(user_id=1, user_name="owner"),
    )

    assert repo.updated is repo.target_member
    assert repo.target_member.user_role == UserRoleEnum.ADMIN
    assert len(send_calls) == expected_notification_count

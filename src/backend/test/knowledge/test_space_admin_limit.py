"""Regression for the knowledge-space admin cap (max 5 admins per space).

Promoting a member to admin once the space already has MAX_SPACE_ADMIN_COUNT admins must
raise the structured ``SpaceAdminLimitExceededError`` (18042) — mirroring the channel side
(19051) — instead of the bare ``ValueError`` that used to surface as a generic 500.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge_space import SpaceAdminLimitExceededError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    SpaceChannelMemberDao,
    UserRoleEnum,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import UpdateSpaceMemberRoleRequest
from bisheng.knowledge.domain.services.knowledge_space_service import (
    MAX_SPACE_ADMIN_COUNT,
    KnowledgeSpaceService,
)


def _space_member(*, user_id: int, role: UserRoleEnum) -> SpaceChannelMember:
    return SpaceChannelMember(
        id=user_id,
        business_id="42",
        business_type=BusinessTypeEnum.SPACE,
        user_id=user_id,
        user_role=role,
        status=MembershipStatusEnum.ACTIVE,
    )


@pytest.mark.asyncio
async def test_promote_to_admin_blocked_at_max_with_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_member = _space_member(user_id=2, role=UserRoleEnum.MEMBER)
    existing_admins = [_space_member(user_id=100 + i, role=UserRoleEnum.ADMIN) for i in range(MAX_SPACE_ADMIN_COUNT)]
    service = KnowledgeSpaceService(
        request=None,
        login_user=SimpleNamespace(user_id=1, user_name="owner"),
    )

    async def _require_permission_id(self, *_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(KnowledgeSpaceService, "_require_permission_id", _require_permission_id)
    # Creator promoting someone → the admin-on-admin restrictions in step 4 are skipped.
    monkeypatch.setattr(
        SpaceChannelMemberDao,
        "async_get_active_member_role",
        AsyncMock(return_value=UserRoleEnum.CREATOR),
    )
    monkeypatch.setattr(SpaceChannelMemberDao, "async_find_member", AsyncMock(return_value=target_member))
    # Space already at the admin cap → the next promotion must be rejected.
    monkeypatch.setattr(
        SpaceChannelMemberDao,
        "async_get_members_by_space",
        AsyncMock(return_value=existing_admins),
    )

    with pytest.raises(SpaceAdminLimitExceededError) as exc_info:
        await service.update_member_role(
            UpdateSpaceMemberRoleRequest(space_id=42, user_id=2, role="admin"),
        )

    assert exc_info.value.Code == 18042

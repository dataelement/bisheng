"""F040 (B) T5: _format_accessible_spaces builds the ReBAC binding index ONCE and
shares it (+ a tuple cache) across all spaces in the page, instead of rebuilding it
per space. The membership/public merge stays inside _get_effective_permission_ids, so
the permission filter result is unchanged — locked here by asserting both the shared
context is threaded AND the required-permission filter still includes/excludes correctly.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    ChannelRelationEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_KS = "bisheng.knowledge.domain.services.knowledge_space_service"


class _User:
    user_id = 5
    tenant_id = 1

    def is_admin(self):
        return False


def _space(space_id: int, name: str, user_id: int):
    return SimpleNamespace(
        id=space_id,
        user_id=user_id,
        model_dump=lambda: {"id": space_id, "name": name, "user_id": user_id},
    )


def _member(space_id: int) -> SpaceChannelMember:
    return SpaceChannelMember(
        business_id=str(space_id),
        business_type=BusinessTypeEnum.CHANNEL,
        user_id=5,
        user_role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.ACTIVE,
        relation=ChannelRelationEnum.VIEWER,
        update_time=datetime.now(),
    )


async def test_format_accessible_spaces_shares_binding_index_and_filters():
    service = KnowledgeSpaceService(request=None, login_user=_User())
    # Two non-creator spaces the user has a membership row on; require view_space.
    spaces = [_space(100, "alpha", user_id=9), _space(200, "beta", user_id=9)]
    captured = {"shared_objs": [], "calls": 0}

    async def _fake_eff(self, object_type, object_id, *, space_id=None, shared=None):
        captured["calls"] += 1
        captured["shared_objs"].append(shared)
        # space 100 grants view_space, space 200 does not → 200 must be filtered out.
        return {"view_space"} if int(object_id) == 100 else set()

    with (
        patch(f"{_KS}.KnowledgeDao.async_get_spaces_by_ids", new=AsyncMock(return_value=spaces)),
        patch(f"{_KS}.KnowledgeSpaceUserPinDao.list_pinned_space_ids", new=AsyncMock(return_value=set())),
        patch.object(service, "_decorate_department_metadata", new=AsyncMock(side_effect=lambda x: x)),
        patch.object(
            service, "_get_relation_bindings", new=AsyncMock(return_value=[{"resource_type": "knowledge_space"}])
        ),
        patch(f"{_KS}.FineGrainedPermissionService.build_binding_index", return_value={"_idx": True}),
        patch.object(KnowledgeSpaceService, "_get_effective_permission_ids", _fake_eff),
    ):
        result = await service._format_accessible_spaces(
            [100, 200],
            "name",
            memberships=[_member(100), _member(200)],
            required_permission_id="view_space",
        )

    # Filter preserved: only space 100 (which grants view_space) survives.
    assert [r.id for r in result] == [100]
    # Shared context threaded: every per-space eval got the SAME index object, built once.
    assert captured["calls"] == 2
    assert all(s is not None and s.get("binding_index") == {"_idx": True} for s in captured["shared_objs"])
    assert captured["shared_objs"][0]["binding_index"] is captured["shared_objs"][1]["binding_index"]
